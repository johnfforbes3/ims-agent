"""
Teams voice-IO shim — Phase 17.2 / 17.3.

Edge plumbing that adds voice capability to the existing /bot/messages
text path WITHOUT touching `interview_agent.py`, `teams_chat_connector.py`,
or `cycle_runner.py`.

Two flows:

  17.2 VOICE-IN — incoming audio attachment from CAM:
        is_voice_message(body) → True
        download_voice_attachment(body)  → bytes
        transcribe_voice_attachment(body) → str
        → caller passes transcript to ChatInterviewSession.process()

  17.3 VOICE-OUT — outgoing audio alongside text reply:
        register_outbound_audio(text, voice_id) → audio_id (str)
        bf_reply_with_audio(service_url, conv_id, activity_id, text,
                            audio_id, cam_name, cam_email) → None
        → posts a Teams activity with BOTH `text` and an audio attachment
        → Teams renders the text bubble; audio plays inline / on-tap.

The audio attachment uses a one-shot HTTPS URL handed back by our own
server (route `/teams/audio/{audio_id}` registered in `dashboard/server.py`).
This mirrors the pattern already proven by `/graph/audio/{audio_id}` for
ACS playPrompt.

Env flags (both default ON, per user direction):
  TEAMS_VOICE_IN=true   - process voice attachments
  TEAMS_VOICE_OUT=true  - send audio attachments alongside text replies

CAM "preference" is implicit: typing always works (text path unchanged);
voice memo from CAM triggers STT; ATLAS always provides both modalities so
the CAM picks in real time.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import uuid
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────

def voice_in_enabled() -> bool:
    return os.getenv("TEAMS_VOICE_IN", "true").lower() in ("1", "true", "yes")


def voice_out_enabled() -> bool:
    return os.getenv("TEAMS_VOICE_OUT", "true").lower() in ("1", "true", "yes")


# Audio reply length floor — short acknowledgments aren't worth the TTS
# overhead. "Got it." / "OK." stay text-only.
_MIN_AUDIO_REPLY_CHARS = int(os.getenv("TEAMS_VOICE_OUT_MIN_CHARS", "20"))

# Audio cache size and TTL (seconds). Each generated audio is held briefly,
# served once by /teams/audio/{audio_id}, then dropped.
_AUDIO_CACHE_TTL = int(os.getenv("TEAMS_VOICE_OUT_TTL_SECONDS", "300"))


# Public-facing base URL of THIS server — the Bot Framework / Teams client
# uses this when fetching the audio attachment. In production this is the
# ngrok / public domain; default to localhost for dev.
def _public_base_url() -> str:
    return os.getenv("DASHBOARD_PUBLIC_URL", "").rstrip("/") \
        or os.getenv("NGROK_URL", "").rstrip("/") \
        or "http://localhost:" + os.getenv("DASHBOARD_PORT", "9000")


# ──────────────────────────────────────────────────────────────────────────
# 17.2 — VOICE-IN: incoming audio attachment detection + transcription
# ──────────────────────────────────────────────────────────────────────────

# Bot Framework / Teams content types that mean "audio attachment".
# Teams voice messages typically arrive as audio/mp3, audio/wav, audio/webm,
# audio/ogg, or audio/mp4 (depending on client + version).
_AUDIO_CONTENT_TYPES = (
    "audio/", "voice/",
)


def _attachments_of(body: dict) -> list[dict]:
    """Pull the attachments array from a Bot Framework activity body."""
    raw = body.get("attachments") or []
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict)]


def is_voice_message(body: dict) -> bool:
    """True iff the incoming activity has at least one audio attachment.

    Robust to missing / malformed attachments — returns False on anything
    that isn't unambiguously audio.
    """
    if not voice_in_enabled():
        return False
    for att in _attachments_of(body):
        ct = (att.get("contentType") or "").lower()
        if any(ct.startswith(prefix) for prefix in _AUDIO_CONTENT_TYPES):
            return True
    return False


def _bf_authed_get(url: str, timeout: int = 30) -> Optional[bytes]:
    """Download an audio resource via Bot Framework Bearer auth.

    Teams voice attachments are served under the Bot Framework service URL;
    they require the same token we use for posting replies.
    """
    from agent.voice.teams_chat_connector import _get_bf_token
    try:
        token = _get_bf_token()
    except Exception as exc:
        logger.warning("action=voice_in_token_failed error=%s", exc)
        return None
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        if not resp.ok:
            logger.warning("action=voice_in_download_failed status=%d url=%s",
                           resp.status_code, url[:80])
            return None
        return resp.content
    except Exception as exc:
        logger.warning("action=voice_in_download_error error=%s url=%s",
                       exc, url[:80])
        return None


def download_voice_attachment(body: dict) -> Optional[tuple[bytes, str]]:
    """Download the FIRST audio attachment from an activity body.

    Returns (bytes, filename) on success, None on failure. Tries each
    audio attachment in order; uses the first that downloads successfully.
    """
    for att in _attachments_of(body):
        ct = (att.get("contentType") or "").lower()
        if not any(ct.startswith(prefix) for prefix in _AUDIO_CONTENT_TYPES):
            continue
        content_url = att.get("contentUrl") or ""
        if not content_url:
            continue
        # Some Teams clients put the audio inline in `content` instead of
        # `contentUrl` — we don't support that path yet (rare); the common
        # case is contentUrl pointing at the Bot Framework's
        # /v3/attachments/{id}/views/original endpoint.
        audio = _bf_authed_get(content_url)
        if audio is None or len(audio) < 100:
            continue
        # Pick a filename extension Whisper recognizes
        ext = "mp3"
        if "wav" in ct: ext = "wav"
        elif "webm" in ct: ext = "webm"
        elif "ogg" in ct: ext = "ogg"
        elif "mp4" in ct: ext = "m4a"
        elif "mpeg" in ct: ext = "mp3"
        filename = f"teams-voice.{ext}"
        logger.info("action=voice_in_downloaded bytes=%d type=%s ext=%s",
                    len(audio), ct, ext)
        return audio, filename
    return None


def transcribe_voice_attachment(body: dict) -> Optional[str]:
    """Convenience: download + Whisper-transcribe the first audio attachment.

    Returns the transcript string, or None when no audio was found or
    transcription failed.
    """
    pair = download_voice_attachment(body)
    if not pair:
        return None
    audio_bytes, filename = pair
    try:
        # Reuse the existing Phase 17 STT module (Whisper API)
        from agent.voice_v2 import stt_openai
        result = stt_openai.transcribe_bytes(audio_bytes, filename=filename)
        text = (result.text or "").strip()
        logger.info(
            "action=voice_in_transcribed text_len=%d latency_ms=%d cost_usd=%.4f",
            len(text), result.latency_ms, result.cost_usd,
        )
        return text or None
    except Exception as exc:
        logger.error("action=voice_in_stt_failed error=%s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────
# 17.3 — VOICE-OUT: TTS + one-shot audio URL + audio attachment send
# ──────────────────────────────────────────────────────────────────────────

# In-memory cache: audio_id → (bytes, content_type, created_at).
# Served once by /teams/audio/{audio_id} then dropped.
_audio_cache: dict[str, tuple[bytes, str, float]] = {}
_audio_cache_lock = threading.Lock()


def _gc_audio_cache() -> None:
    """Expire audio entries older than TTL."""
    now = time.monotonic()
    with _audio_cache_lock:
        stale = [aid for aid, (_, _, ts) in _audio_cache.items()
                 if now - ts > _AUDIO_CACHE_TTL]
        for aid in stale:
            _audio_cache.pop(aid, None)


def register_outbound_audio(audio_bytes: bytes, content_type: str = "audio/mpeg") -> str:
    """Cache the audio bytes under a fresh UUID and return the audio_id.

    The audio is served exactly once by /teams/audio/{audio_id} then
    evicted. Stale entries are GC'd on every register call.
    """
    _gc_audio_cache()
    audio_id = uuid.uuid4().hex
    with _audio_cache_lock:
        _audio_cache[audio_id] = (audio_bytes, content_type, time.monotonic())
    logger.debug("action=voice_out_audio_registered audio_id=%s bytes=%d",
                 audio_id, len(audio_bytes))
    return audio_id


def consume_outbound_audio(audio_id: str) -> Optional[tuple[bytes, str]]:
    """Pop the audio from cache (serve-once). Returns (bytes, content_type)
    or None when not found."""
    with _audio_cache_lock:
        entry = _audio_cache.pop(audio_id, None)
    if entry is None:
        return None
    audio_bytes, content_type, _ts = entry
    return audio_bytes, content_type


def _should_synthesize(text: str) -> bool:
    """Skip TTS for very short acks ('Got it.', 'OK.') — text is fine."""
    if not text or not text.strip():
        return False
    if len(text.strip()) < _MIN_AUDIO_REPLY_CHARS:
        return False
    return True


def _voice_id_for(cam_name: str, cam_email: str) -> str:
    """Pick the per-CAM voice ID. Reuses the existing voice_v2 helper which
    hashes the CAM email into the ELEVENLABS_CAM_VOICES list."""
    try:
        from agent.voice_v2 import tts
        return tts.voice_for_cam(cam_name, cam_email)
    except Exception:
        return os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


def synthesize_reply_audio(text: str, cam_name: str = "", cam_email: str = "") -> Optional[bytes]:
    """Run text through ElevenLabs (with OpenAI TTS fallback) and return
    audio bytes. None when synthesis fails."""
    if not _should_synthesize(text):
        return None
    voice_id = _voice_id_for(cam_name, cam_email)
    try:
        from agent.voice_v2 import tts
        result = tts.synthesize(text, voice_id=voice_id)
        if not result.audio_bytes:
            return None
        logger.info(
            "action=voice_out_synthesized voice=%s chars=%d bytes=%d cost_usd=%.4f",
            voice_id, len(text), len(result.audio_bytes), result.cost_usd,
        )
        return result.audio_bytes
    except Exception as exc:
        logger.error("action=voice_out_tts_failed error=%s", exc)
        return None


def bf_reply_with_audio(
    service_url: str,
    conversation_id: str,
    reply_to_id: str,
    text: str,
    audio_bytes: Optional[bytes],
    cam_name: str = "",
    cam_email: str = "",
) -> None:
    """Post a Teams chat reply with text + optional audio attachment.

    Drops to text-only behavior identical to `_bf_reply()` when:
      - voice_out is disabled
      - audio_bytes is None / empty
      - DASHBOARD_PUBLIC_URL is localhost (Teams can't reach our local URL)

    Text is ALWAYS sent. Audio is supplementary.
    """
    # Always send the text via the existing helper — this is the unchanged
    # safety net. If anything below fails, the CAM still gets the text.
    from agent.voice.teams_chat_connector import _bf_reply, _get_bf_token

    # When voice-out is disabled or audio not available, fall through to
    # the unchanged text-only path
    if not voice_out_enabled() or not audio_bytes:
        _bf_reply(service_url, conversation_id, reply_to_id, text)
        return

    base = _public_base_url()
    # Localhost URLs are not reachable by Teams clients — fall back to
    # text-only so we don't post a broken attachment URL.
    if base.startswith("http://localhost") or base.startswith("http://127."):
        logger.info("action=voice_out_skipped_localhost reason=base=%s — sending text only", base)
        _bf_reply(service_url, conversation_id, reply_to_id, text)
        return

    audio_id = register_outbound_audio(audio_bytes, content_type="audio/mpeg")
    audio_url = f"{base}/teams/audio/{audio_id}"

    try:
        token = _get_bf_token()
        url = (
            f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}"
            f"/activities/{reply_to_id}"
        )
        payload = {
            "type": "message",
            "text": text,
            "attachments": [
                {
                    "contentType": "audio/mpeg",
                    "contentUrl": audio_url,
                    "name": "atlas-reply.mp3",
                }
            ],
        }
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        if not resp.ok:
            logger.warning(
                "action=voice_out_send_failed status=%d body=%s — falling back to text",
                resp.status_code, resp.text[:200],
            )
            # Drop the cached audio (we won't be serving it) and resend as text
            consume_outbound_audio(audio_id)
            _bf_reply(service_url, conversation_id, reply_to_id, text)
        else:
            logger.info(
                "action=voice_out_sent audio_id=%s text_len=%d",
                audio_id, len(text),
            )
    except Exception as exc:
        logger.error("action=voice_out_send_error error=%s — falling back to text", exc)
        consume_outbound_audio(audio_id)
        _bf_reply(service_url, conversation_id, reply_to_id, text)
