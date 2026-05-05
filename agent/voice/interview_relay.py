"""
Live interview event relay bus — Phase 9.3 voice overhaul.

Key improvements over 9.2:
  - Each CAM gets a distinct ElevenLabs voice (assigned round-robin from pool).
  - CAM turns now generate TTS audio, not just bot turns.
  - has_audio is set eagerly (True before TTS completes) so the browser
    starts fetching immediately rather than waiting for a patch event.
  - Shared TTS engine instance (one ElevenLabs client, multiple voices).
  - Worker pool bumped to 2 so bot and CAM audio can generate in parallel.

Voice configuration (env vars):
  ELEVENLABS_VOICE_ID       — ATLAS (bot) voice  [default: Rachel]
  ELEVENLABS_CAM_VOICES     — comma-separated voice IDs for the CAM pool
                              defaults to 5 ElevenLabs pre-made voices

Design goals:
  - No asyncio in the bus — works from sync helpers and async handlers.
  - Sequential event numbering for reliable cursor-based SSE polling.
  - TTS in a background thread so it never blocks the interview loop.
"""

import collections
import dataclasses
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500       # keep last N events in memory
_MAX_AUDIO  = 80        # keep last N audio blobs (bot + cam ≈ 2× previous)
_TTS_WORKERS = 2        # 2 so bot & CAM can synthesize in parallel

# ---------------------------------------------------------------------------
# Voice pool
# ---------------------------------------------------------------------------

# ATLAS (bot) voice — same env var as the rest of the TTS stack
_ATLAS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# CAM voice pool — 5 ElevenLabs pre-made voices (available on all plans).
# Override with ELEVENLABS_CAM_VOICES="id1,id2,id3,id4,id5"
_DEFAULT_CAM_VOICE_POOL = [
    "AZnzlk1XvdvUeBnXmlld",   # Domi  (female, energetic)
    "ErXwobaYiN019PkySvjV",   # Antoni (male, professional)
    "MF3mGyEYCl7XYWbV9V6O",   # Elli  (female, clear)
    "TxGEqnHWrfWFTfGW9XjX",   # Josh  (male, confident)
    "pNInz6obpgDQGcFmaJgB",   # Adam  (male, deep)
]
_CAM_VOICE_POOL: list[str] = [
    v.strip()
    for v in os.getenv("ELEVENLABS_CAM_VOICES", ",".join(_DEFAULT_CAM_VOICE_POOL)).split(",")
    if v.strip()
]

# ---------------------------------------------------------------------------
# Shared TTS engine (one client, used with voice-specific calls)
# ---------------------------------------------------------------------------

_tts_engine_singleton = None
_tts_engine_lock = threading.Lock()
_tts_real: Optional[bool] = None   # cached result of _tts_is_real()


def _get_tts_engine():
    """Lazy singleton — builds the TTS engine once, reuses for all calls."""
    global _tts_engine_singleton
    if _tts_engine_singleton is None:
        with _tts_engine_lock:
            if _tts_engine_singleton is None:
                from agent.voice.tts_engine import build_tts_engine
                _tts_engine_singleton = build_tts_engine()
    return _tts_engine_singleton


def _tts_is_real() -> bool:
    """True if TTS is configured with a real key (not mock). Cached after first call."""
    global _tts_real
    if _tts_real is None:
        try:
            from agent.voice.tts_engine import tts_configured
            _tts_real = tts_configured()
        except Exception:
            _tts_real = False
    return _tts_real


def validate_cam_voice_pool() -> list[str]:
    """
    Query ElevenLabs and return a list of validation warnings for the pool.

    Called once at relay bus startup so problems appear in server logs rather
    than silently producing silent audio during a live interview.
    """
    if not _tts_is_real():
        return []
    warnings: list[str] = []
    try:
        from agent.voice.tts_engine import _ELEVENLABS_KEY, _ELEVENLABS_AVAILABLE
        if not (_ELEVENLABS_AVAILABLE and _ELEVENLABS_KEY):
            return []
        from elevenlabs.client import ElevenLabs as _EL
        client = _EL(api_key=_ELEVENLABS_KEY)
        available_ids = {v.voice_id for v in client.voices.get_all().voices}
        for vid in _CAM_VOICE_POOL:
            if vid not in available_ids:
                warnings.append(f"CAM voice {vid!r} not found in account — audio for that CAM will be silent")
        if _ATLAS_VOICE_ID not in available_ids:
            warnings.append(f"ATLAS voice {_ATLAS_VOICE_ID!r} not in account")
    except Exception as exc:
        warnings.append(f"Voice validation failed: {exc}")
    return warnings


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class InterviewEvent:
    seq: int            # monotonic counter — SSE cursor
    event_id: str       # UUID — audio key at /api/interview-audio/{event_id}
    timestamp: float    # unix epoch
    speaker: str        # "bot" | "cam"
    cam_name: str
    cam_email: str
    text: str
    has_audio: bool = False   # True = audio expected; browser should pre-fetch
    cycle_id: str = ""
    session_id: str = ""      # str(id(ChatInterviewSession))


# ---------------------------------------------------------------------------
# Relay bus
# ---------------------------------------------------------------------------

class InterviewRelayBus:
    """
    Singleton in-memory relay for live interview turn events.

    Thread-safe; works from sync handlers and async FastAPI handlers alike.
    """

    _instance: Optional["InterviewRelayBus"] = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._events: list[InterviewEvent] = []
        self._seq: int = 0
        self._lock = threading.Lock()
        # Audio: event_id → bytes
        self._audio: dict[str, bytes] = {}
        self._audio_order: collections.deque = collections.deque(maxlen=_MAX_AUDIO)
        # Active sessions: cam_email → {cam_name, started_at, session_id}
        self._active_sessions: dict[str, dict] = {}
        # CAM voice assignments: cam_email → voice_id (stable per session)
        self._cam_voice_map: dict[str, str] = {}
        self._cam_voice_idx: int = 0
        # Background TTS workers
        self._tts_pool = ThreadPoolExecutor(
            max_workers=_TTS_WORKERS, thread_name_prefix="relay-tts"
        )

    @classmethod
    def get(cls) -> "InterviewRelayBus":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = InterviewRelayBus()
        return cls._instance

    # ------------------------------------------------------------------
    # Voice assignment
    # ------------------------------------------------------------------

    def get_cam_voice(self, cam_email: str) -> str:
        """
        Return a stable voice ID for this CAM.

        Assignment is round-robin from _CAM_VOICE_POOL, first-seen wins.
        The ATLAS voice is skipped so bot and CAMs always sound different.
        """
        email = cam_email.lower()
        with self._lock:
            if email not in self._cam_voice_map:
                pool = [v for v in _CAM_VOICE_POOL if v != _ATLAS_VOICE_ID] or _CAM_VOICE_POOL
                if pool:
                    voice = pool[self._cam_voice_idx % len(pool)]
                    self._cam_voice_idx += 1
                else:
                    voice = _ATLAS_VOICE_ID   # last-resort fallback
                self._cam_voice_map[email] = voice
            return self._cam_voice_map[email]

    def cam_voice_assignments(self) -> dict[str, str]:
        with self._lock:
            return dict(self._cam_voice_map)

    # ------------------------------------------------------------------
    # Core event production
    # ------------------------------------------------------------------

    def push_event(self, event: InterviewEvent) -> InterviewEvent:
        """Assign a seq number and append to bus. Thread-safe."""
        with self._lock:
            event = dataclasses.replace(event, seq=self._seq)
            self._seq += 1
            self._events.append(event)
            if len(self._events) > _MAX_EVENTS:
                self._events = self._events[-_MAX_EVENTS:]
        logger.debug(
            "action=relay_event seq=%d speaker=%s cam=%s chars=%d has_audio=%s",
            event.seq, event.speaker, event.cam_name, len(event.text), event.has_audio,
        )
        return event

    def push_bot_turn(
        self,
        cam_name: str,
        cam_email: str,
        text: str,
        session_id: str = "",
        cycle_id: str = "",
        synthesize: bool = True,
    ) -> InterviewEvent:
        """
        Push a bot→CAM question turn.

        has_audio is set to True eagerly when TTS is configured so the browser
        starts pre-fetching immediately without waiting for the patch.
        TTS generation runs in a background thread; audio is ready typically
        1-2 s after the event fires — well before it's time to play.
        """
        will_have_audio = synthesize and bool(text) and _tts_is_real()
        ev = InterviewEvent(
            seq=0,
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            speaker="bot",
            cam_name=cam_name,
            cam_email=cam_email.lower(),
            text=text,
            has_audio=will_have_audio,
            cycle_id=cycle_id,
            session_id=session_id,
        )
        ev = self.push_event(ev)
        if will_have_audio:
            self._tts_pool.submit(self._synthesize_audio, ev.event_id, text, _ATLAS_VOICE_ID)
        return ev

    def push_cam_turn(
        self,
        cam_name: str,
        cam_email: str,
        text: str,
        session_id: str = "",
        cycle_id: str = "",
    ) -> InterviewEvent:
        """
        Push a CAM→bot response turn.

        Phase 9.3: CAM turns now generate audio too, using the CAM's
        assigned voice from the pool. has_audio set eagerly like bot turns.
        """
        voice_id = self.get_cam_voice(cam_email)
        will_have_audio = bool(text) and _tts_is_real()
        ev = InterviewEvent(
            seq=0,
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            speaker="cam",
            cam_name=cam_name,
            cam_email=cam_email.lower(),
            text=text,
            has_audio=will_have_audio,
            cycle_id=cycle_id,
            session_id=session_id,
        )
        ev = self.push_event(ev)
        if will_have_audio:
            self._tts_pool.submit(self._synthesize_audio, ev.event_id, text, voice_id)
        return ev

    # ------------------------------------------------------------------
    # TTS synthesis (background thread)
    # ------------------------------------------------------------------

    def store_audio(self, event_id: str, audio_bytes: bytes) -> None:
        """Store audio bytes (thread-safe). Patches has_audio on stored event."""
        with self._lock:
            self._audio[event_id] = audio_bytes
            self._audio_order.append(event_id)
            while len(self._audio) > _MAX_AUDIO:
                if self._audio_order:
                    oldest = self._audio_order[0]
                    self._audio.pop(oldest, None)
            # Patch stored event (belt-and-suspenders; usually already True)
            for i, ev in enumerate(self._events):
                if ev.event_id == event_id:
                    self._events[i] = dataclasses.replace(ev, has_audio=True)
                    break

    def _synthesize_audio(self, event_id: str, text: str, voice_id: str) -> None:
        """Background: synthesize TTS with a specific voice and store bytes."""
        try:
            engine = _get_tts_engine()
            # Use voice-specific synthesis if the engine supports it
            if hasattr(engine, "synthesize_with_voice"):
                audio = engine.synthesize_with_voice(text, voice_id)
            else:
                audio = engine.synthesize(text)   # mock / fallback
            if not audio:
                logger.debug("action=tts_empty event_id=%s voice=%s", event_id, voice_id)
                return
            self.store_audio(event_id, audio)
            logger.info(
                "action=tts_stored event_id=%s voice=%s bytes=%d",
                event_id, voice_id, len(audio),
            )
        except Exception as exc:
            logger.debug(
                "action=tts_failed event_id=%s voice=%s error=%s", event_id, voice_id, exc
            )

    # ------------------------------------------------------------------
    # Event consumption
    # ------------------------------------------------------------------

    def events_since(self, seq: int, limit: int = 50) -> list[InterviewEvent]:
        """Return events with seq >= `seq`, up to `limit`."""
        with self._lock:
            result = [e for e in self._events if e.seq >= seq]
        return result[:limit]

    @property
    def current_seq(self) -> int:
        with self._lock:
            return self._seq

    def recent_events(self, n: int = 30) -> list[InterviewEvent]:
        with self._lock:
            return list(self._events[-n:])

    # ------------------------------------------------------------------
    # Audio retrieval
    # ------------------------------------------------------------------

    def get_audio(self, event_id: str) -> bytes | None:
        with self._lock:
            return self._audio.get(event_id)

    # ------------------------------------------------------------------
    # Active session tracking
    # ------------------------------------------------------------------

    def register_session(self, cam_email: str, cam_name: str, session_id: str) -> None:
        with self._lock:
            self._active_sessions[cam_email.lower()] = {
                "cam_name": cam_name,
                "started_at": time.time(),
                "session_id": session_id,
            }
        logger.info("action=relay_session_started cam=%s", cam_email)

    def unregister_session(self, cam_email: str) -> None:
        with self._lock:
            self._active_sessions.pop(cam_email.lower(), None)
        logger.info("action=relay_session_ended cam=%s", cam_email)

    def active_sessions(self) -> list[dict]:
        with self._lock:
            return [{"cam_email": k, **v} for k, v in self._active_sessions.items()]
