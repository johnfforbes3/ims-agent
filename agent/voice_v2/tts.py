"""
ElevenLabs streaming TTS wrapper — Phase 17.

Wraps the existing `agent/voice/tts_engine.py` for the voice agent v2
pipeline. Adds:
    - per-CAM voice selection (ELEVENLABS_CAM_VOICES env list)
    - streaming output (chunks) so the web tester can play audio while
      the rest of the reply is still being generated
    - latency tracking (time-to-first-audio) for the turn log
    - NATO phonetic + number spelling pass before synthesis (article §11 #6:
      "TTS reads codes and IDs literally — A3X7 becomes 'ay three ex seven'")
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Iterator, Optional

from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

_ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")
_DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2")
# Per-CAM voice IDs (comma-separated, matches CAM order in CAMS list)
_CAM_VOICES_RAW = os.getenv("ELEVENLABS_CAM_VOICES", "")
_CAM_VOICES = [v.strip() for v in _CAM_VOICES_RAW.split(",") if v.strip()]


# NATO phonetic for letter-spelling task IDs / codes
_NATO = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
    "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliet",
    "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
    "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "Xray", "Y": "Yankee",
    "Z": "Zulu",
}

_DIGIT_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}


def voice_for_cam(cam_name: str, cam_email: str = "") -> str:
    """Pick a voice ID for a CAM. Hashed pick from the configured list, falls
    back to the default voice when no CAM voices are configured."""
    if not _CAM_VOICES:
        return _DEFAULT_VOICE_ID
    # Stable: same CAM always gets the same voice
    key = (cam_email or cam_name or "").lower()
    if not key:
        return _CAM_VOICES[0]
    idx = sum(ord(c) for c in key) % len(_CAM_VOICES)
    return _CAM_VOICES[idx]


# ──────────────────────────────────────────────────────────────────────────
# Text pre-processing for voice (article §4 + §11 #6)
# ──────────────────────────────────────────────────────────────────────────


def _spell_code(token: str) -> str:
    """Convert a mixed-case alphanumeric code into NATO + digit-spelled form.

    Example: 'A3X7' → 'Alpha three Xray seven'
             'AI-07' → 'Alpha India zero seven'
    """
    out = []
    for ch in token:
        upper = ch.upper()
        if upper in _NATO:
            out.append(_NATO[upper])
        elif ch in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[ch])
        elif ch in ("-", "_"):
            continue  # skip separators
        else:
            out.append(ch)
    return " ".join(out)


def prepare_for_voice(text: str) -> str:
    """Apply article §4 + §11 #6 rules: spell numbers and codes, strip markdown.

    Codes are detected as `[A-Z]+\\d` or `\\d[A-Z]+` mixed tokens. We do NOT
    spell out plain numbers in normal speech ("50 percent" stays "50 percent" —
    TTS handles those fine); we only spell digit-mixed codes that TTS would
    butcher.
    """
    if not text:
        return ""
    # Strip markdown that snuck through (output_guard does this too, defense-in-depth)
    text = re.sub(r"\*\*?", "", text)
    text = re.sub(r"(?<!\w)_(?!\w)", "", text)

    # Codes: at least one letter + one digit, hyphens allowed
    code_re = re.compile(r"\b(?=[A-Z\d-]*[A-Z])(?=[A-Z\d-]*\d)[A-Z\d-]{2,}\b")
    text = code_re.sub(lambda m: _spell_code(m.group(0)), text)
    return text


# ──────────────────────────────────────────────────────────────────────────
# TTS interface
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class TTSResult:
    audio_bytes: bytes
    voice_id: str
    char_count: int
    first_audio_ms: int = 0  # for streaming variant; same as total in batch
    total_ms: int = 0
    cost_usd: float = 0.0


# ElevenLabs Turbo v2 pricing: ~$0.06 / 1000 characters
_PER_KCHAR_USD = 0.06 / 1000


def _record_tts_spend(cost: float) -> None:
    """Track TTS spend in the unified $25 cap file."""
    from agent.voice_v2 import llm_openai
    llm_openai._record_spend(cost)


def synthesize(text: str, voice_id: Optional[str] = None) -> TTSResult:
    """Batch synthesis — returns full audio bytes after generation completes.

    Two-tier provider strategy (Phase 17): prefer ElevenLabs (per-CAM voices,
    higher quality); fall back to OpenAI TTS-1 when ElevenLabs returns quota
    exhausted, auth failure, or any other error. The fallback is automatic
    and logged but does NOT raise — the pipeline always gets audio bytes
    when possible.

    Use this for short replies (≤ 80 chars / ~5 seconds of audio). For longer
    replies use `synthesize_streaming()` to start playback earlier.
    """
    voice_id = voice_id or _DEFAULT_VOICE_ID
    speakable = prepare_for_voice(text)

    # ───── Tier 1: ElevenLabs ─────
    t0 = time.monotonic()
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings
        client = ElevenLabs(api_key=_ELEVENLABS_KEY)
        audio_iter = client.text_to_speech.convert(
            voice_id=voice_id,
            model_id=_MODEL,
            text=speakable,
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
        )
        audio = b"".join(audio_iter) if hasattr(audio_iter, "__iter__") else audio_iter

        total_ms = round((time.monotonic() - t0) * 1000)
        cost = round(len(speakable) * _PER_KCHAR_USD, 6)
        _record_tts_spend(cost)

        logger.info(
            "action=tts_synth provider=elevenlabs voice=%s chars=%d bytes=%d ms=%d cost_usd=%.4f",
            voice_id, len(speakable), len(audio), total_ms, cost,
        )
        return TTSResult(
            audio_bytes=audio,
            voice_id=voice_id,
            char_count=len(speakable),
            first_audio_ms=total_ms,
            total_ms=total_ms,
            cost_usd=cost,
        )
    except Exception as exc:
        msg = str(exc)[:200]
        logger.warning("action=tts_elevenlabs_failed reason=%s — falling back to openai", msg)

    # ───── Tier 2: OpenAI TTS-1 fallback ─────
    return _synthesize_openai(speakable)


def synthesize_fast(text: str, voice_id: Optional[str] = None) -> TTSResult:
    """Latency-optimized variant — skips ElevenLabs (slow first-byte) and goes
    straight to OpenAI TTS-1 (typically 60-150ms first-byte for short replies).

    Use this when ElevenLabs is rate-limited / quota-exhausted, OR when the
    pipeline knows it's serving a short response and per-CAM voice isn't
    important (e.g. small-talk gate replies, confirmations, acknowledgments).
    """
    return _synthesize_openai(text)


def _synthesize_openai(text: str, model: str = "tts-1", voice: str = "alloy") -> TTSResult:
    """OpenAI TTS-1 fallback. Pricing: $15/1M chars (~$0.015 per 1K chars).

    Voices: alloy (neutral), echo (male), fable (British), onyx (deep male),
    nova (female), shimmer (warm female). We default to 'alloy' because it
    sounds most professional for a business interview context.
    """
    import os
    from openai import OpenAI

    t0 = time.monotonic()
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        resp = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        audio = resp.content
    except Exception as exc:
        logger.error("action=tts_openai_failed error=%s", str(exc)[:200])
        return TTSResult(audio_bytes=b"", voice_id="", char_count=len(text))

    total_ms = round((time.monotonic() - t0) * 1000)
    cost = round(len(text) * (15.0 / 1_000_000), 6)
    _record_tts_spend(cost)

    logger.info(
        "action=tts_synth provider=openai voice=%s chars=%d bytes=%d ms=%d cost_usd=%.4f",
        voice, len(text), len(audio), total_ms, cost,
    )
    return TTSResult(
        audio_bytes=audio,
        voice_id=f"openai:{voice}",
        char_count=len(text),
        first_audio_ms=total_ms,
        total_ms=total_ms,
        cost_usd=cost,
    )


def synthesize_streaming(text: str, voice_id: Optional[str] = None) -> Iterator[bytes]:
    """Streaming synthesis — yields audio chunks as they arrive from ElevenLabs.

    Lets the web tester start playback before the full audio is generated.
    The first chunk typically arrives within 60-100ms for short text.
    """
    voice_id = voice_id or _DEFAULT_VOICE_ID
    speakable = prepare_for_voice(text)

    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings
        client = ElevenLabs(api_key=_ELEVENLABS_KEY)
        for chunk in client.text_to_speech.stream(
            voice_id=voice_id,
            model_id=_MODEL,
            text=speakable,
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
        ):
            if chunk:
                yield chunk
    except Exception as exc:
        logger.error("action=tts_stream_failed error=%s", exc)
        raise

    cost = round(len(speakable) * _PER_KCHAR_USD, 6)
    _record_tts_spend(cost)
