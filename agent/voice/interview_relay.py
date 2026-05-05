"""
Live interview event relay bus.

Producers push InterviewEvent objects (one per bot/cam turn) into the bus.
Consumers (SSE endpoint) poll events_since() to drive the listen-in panel.
Audio bytes for bot utterances are generated asynchronously in a background
thread and stored by event_id for on-demand retrieval.

Design goals:
  - No asyncio in the bus itself — works from sync helpers and async handlers.
  - Sequential event numbering for reliable cursor-based polling.
  - TTS generation in a background thread so it never blocks the interview loop.
"""

import collections
import dataclasses
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500       # keep last N events in memory
_MAX_AUDIO = 50         # keep last N audio blobs (~5 MB @ 100 KB/clip)
_TTS_WORKERS = 1        # single worker: ElevenLabs has per-account rate limits


@dataclasses.dataclass
class InterviewEvent:
    seq: int            # monotonic counter; used for cursor-based SSE polling
    event_id: str       # UUID; links to audio at /api/interview-audio/{event_id}
    timestamp: float    # unix epoch
    speaker: str        # "bot" | "cam"
    cam_name: str
    cam_email: str
    text: str
    has_audio: bool = False
    cycle_id: str = ""
    session_id: str = ""  # str(id(ChatInterviewSession)) — unique per run


class InterviewRelayBus:
    """
    Singleton in-memory relay for live interview turn events.

    Thread-safe; works from sync helpers and async FastAPI handlers alike.
    No event loop required — bus state is plain Python dicts and lists.
    """

    _instance: Optional["InterviewRelayBus"] = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._events: list[InterviewEvent] = []
        self._seq: int = 0
        self._lock = threading.Lock()
        # Audio store: event_id → bytes
        self._audio: dict[str, bytes] = {}
        self._audio_order: collections.deque = collections.deque(maxlen=_MAX_AUDIO)
        # Active sessions: cam_email → {cam_name, started_at, session_id}
        self._active_sessions: dict[str, dict] = {}
        # Background TTS thread
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
    # Core event production
    # ------------------------------------------------------------------

    def push_event(self, event: InterviewEvent) -> InterviewEvent:
        """Assign a seq number and append event to the bus."""
        with self._lock:
            event = dataclasses.replace(event, seq=self._seq)
            self._seq += 1
            self._events.append(event)
            # Trim oldest events if over limit
            if len(self._events) > _MAX_EVENTS:
                self._events = self._events[-_MAX_EVENTS:]
        logger.debug(
            "action=relay_event seq=%d speaker=%s cam=%s chars=%d",
            event.seq, event.speaker, event.cam_name, len(event.text),
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

        If synthesize=True and TTS is configured, generates audio in the background.
        Returns immediately (before TTS completes); has_audio is patched once done.
        """
        ev = InterviewEvent(
            seq=0,
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            speaker="bot",
            cam_name=cam_name,
            cam_email=cam_email.lower(),
            text=text,
            has_audio=False,
            cycle_id=cycle_id,
            session_id=session_id,
        )
        ev = self.push_event(ev)
        if synthesize and text:
            self._tts_pool.submit(self._synthesize_audio, ev.event_id, text)
        return ev

    def push_cam_turn(
        self,
        cam_name: str,
        cam_email: str,
        text: str,
        session_id: str = "",
        cycle_id: str = "",
    ) -> InterviewEvent:
        """Push a CAM→bot response turn (no audio generated)."""
        ev = InterviewEvent(
            seq=0,
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            speaker="cam",
            cam_name=cam_name,
            cam_email=cam_email.lower(),
            text=text,
            has_audio=False,
            cycle_id=cycle_id,
            session_id=session_id,
        )
        return self.push_event(ev)

    def store_audio(self, event_id: str, audio_bytes: bytes) -> None:
        """Store audio bytes for an event (thread-safe; patches has_audio flag)."""
        with self._lock:
            self._audio[event_id] = audio_bytes
            self._audio_order.append(event_id)
            while len(self._audio) > _MAX_AUDIO:
                if self._audio_order:
                    oldest = self._audio_order[0]
                    self._audio.pop(oldest, None)
            for i, ev in enumerate(self._events):
                if ev.event_id == event_id:
                    self._events[i] = dataclasses.replace(ev, has_audio=True)
                    break

    def _synthesize_audio(self, event_id: str, text: str) -> None:
        """Background thread: TTS → store_audio → patch has_audio on the event."""
        try:
            from agent.voice.tts_engine import build_tts_engine
            engine = build_tts_engine()
            audio = engine.synthesize(text)
            if not audio:
                logger.debug("action=tts_empty event_id=%s (mock or key missing)", event_id)
                return
            self.store_audio(event_id, audio)
            logger.info("action=tts_stored event_id=%s bytes=%d", event_id, len(audio))
        except Exception as exc:
            logger.debug(
                "action=tts_background_failed event_id=%s error=%s", event_id, exc
            )

    # ------------------------------------------------------------------
    # Event consumption (SSE polling cursor pattern)
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
        """Return the last n events for new SSE subscriber backfill."""
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
            return [
                {"cam_email": k, **v}
                for k, v in self._active_sessions.items()
            ]
