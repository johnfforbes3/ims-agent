"""
OpenAI Whisper STT wrapper — Phase 17.

User chose OpenAI Whisper API over Deepgram Flux. Trade-off:
    + No new vendor; reuses the OPENAI_API_KEY
    + Excellent transcription quality on schedule jargon (we pass an
      initial_prompt with IMS vocabulary)
    - No semantic end-of-turn detection (Whisper API is batch, not
      streaming) — we rely on silence threshold in the client
    - Per-request latency includes the round-trip; we set audio chunks
      to ~2-5 second segments to keep this snappy

Cost: $0.006 / minute of audio. A 5-CAM cycle ≈ 80 min total → ~$0.48 / cycle.

The wrapper supports two modes:
    transcribe_file(path)          — synchronous; for the web tester after
                                      the full utterance is recorded
    transcribe_bytes(audio_bytes, mime_type)
                                   — same, in-memory; used by Teams voice
                                      message bridge after Graph download
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

_WHISPER_INITIAL_PROMPT = os.getenv(
    "WHISPER_INITIAL_PROMPT",
    "IMS schedule status, percent complete, critical path, PDR, CDR, TRR, "
    "CAM, milestone, baseline, blocker, slip, float, EVM, BEI, SPI, CPI, "
    "DCMA, SRA, turbopump, qual, GFE, ICD, FTE, TVAC, RFQ.",
)

# Per-minute pricing — keep in sync with llm_openai._PRICING
_PER_MINUTE_USD = 0.006


@dataclass
class STTResult:
    text: str
    duration_seconds: float = 0.0
    latency_ms: int = 0
    model: str = "whisper-1"
    cost_usd: float = 0.0
    language: str = "en"


def _record_stt_spend(cost: float) -> None:
    """Track STT spend in the same file as LLM spend so the $25 cap covers both."""
    from agent.voice_v2 import llm_openai
    llm_openai._record_spend(cost)


def transcribe_file(path: Union[str, Path],
                    initial_prompt: Optional[str] = None,
                    language: str = "en") -> STTResult:
    """Transcribe a local audio file via OpenAI Whisper API.

    Accepts mp3, mp4, mpeg, mpga, m4a, wav, webm — the file extension is
    passed through to OpenAI's content-type detection.
    """
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    # Audio duration for cost calc — best-effort, falls back to 0 (no cost).
    duration = _audio_duration_seconds(path)

    t0 = time.monotonic()
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            prompt=initial_prompt or _WHISPER_INITIAL_PROMPT,
            language=language,
            response_format="json",
        )
    latency = round((time.monotonic() - t0) * 1000)
    cost = round((duration / 60.0) * _PER_MINUTE_USD, 6)
    _record_stt_spend(cost)

    logger.info(
        "action=stt_whisper file=%s duration_s=%.1f latency_ms=%d cost_usd=%.4f text_len=%d",
        path.name, duration, latency, cost, len(resp.text),
    )
    return STTResult(
        text=resp.text.strip(),
        duration_seconds=duration,
        latency_ms=latency,
        cost_usd=cost,
        language=language,
    )


def transcribe_bytes(audio_bytes: bytes,
                     filename: str = "audio.webm",
                     initial_prompt: Optional[str] = None,
                     language: str = "en") -> STTResult:
    """In-memory variant. `filename` extension drives content-type detection."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    duration = _audio_duration_bytes(audio_bytes, filename)
    t0 = time.monotonic()
    file_tuple = (filename, io.BytesIO(audio_bytes))
    resp = client.audio.transcriptions.create(
        model="whisper-1",
        file=file_tuple,
        prompt=initial_prompt or _WHISPER_INITIAL_PROMPT,
        language=language,
        response_format="json",
    )
    latency = round((time.monotonic() - t0) * 1000)
    cost = round((duration / 60.0) * _PER_MINUTE_USD, 6)
    _record_stt_spend(cost)

    logger.info(
        "action=stt_whisper_bytes filename=%s bytes=%d duration_s=%.1f latency_ms=%d cost_usd=%.4f",
        filename, len(audio_bytes), duration, latency, cost,
    )
    return STTResult(
        text=resp.text.strip(),
        duration_seconds=duration,
        latency_ms=latency,
        cost_usd=cost,
        language=language,
    )


def _audio_duration_seconds(path: Path) -> float:
    """Best-effort audio duration. Falls back to 0 (no cost) when pydub absent."""
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(path)
        return seg.duration_seconds
    except Exception as exc:
        logger.debug("action=audio_duration_skip reason=%s", exc)
        return 0.0


def _audio_duration_bytes(audio_bytes: bytes, filename: str) -> float:
    """In-memory variant of duration detection."""
    try:
        from pydub import AudioSegment
        ext = Path(filename).suffix.lstrip(".") or "webm"
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=ext)
        return seg.duration_seconds
    except Exception as exc:
        logger.debug("action=audio_duration_skip reason=%s", exc)
        return 0.0
