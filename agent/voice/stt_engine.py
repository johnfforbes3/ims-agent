"""
Speech-to-Text engine abstraction.

Provides a common STTEngine interface with two concrete implementations:
  - WhisperSTTEngine  — local Whisper model (no API key, ITAR-safe)
  - MockSTTEngine     — testing / simulation mode (passes text through directly)

In simulation mode the CAM simulator returns text, not audio, so MockSTTEngine
is always used. WhisperSTTEngine activates when processing real recorded audio.
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
_WHISPER_PROMPT = os.getenv(
    "WHISPER_INITIAL_PROMPT",
    "IMS schedule status, percent complete, critical path, PDR, CDR, TRR, CAM, milestone",
)

try:
    import whisper as _whisper_lib  # type: ignore
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False
    logger.debug("openai-whisper not installed — WhisperSTTEngine unavailable")


@dataclass
class TranscriptionResult:
    """Result of a speech-to-text transcription."""
    text: str
    confidence: float          # 0.0–1.0; <0.7 flagged for human review
    language: str
    flagged_for_review: bool

    _REVIEW_THRESHOLD = 0.70

    @classmethod
    def from_text(cls, text: str, confidence: float = 1.0) -> "TranscriptionResult":
        """Build a result from a plain text string (simulation / mock path)."""
        return cls(
            text=text,
            confidence=confidence,
            language="en",
            flagged_for_review=confidence < cls._REVIEW_THRESHOLD,
        )


class STTEngine(ABC):
    """Abstract base class for all STT engines."""

    @abstractmethod
    def transcribe_file(self, audio_path: str) -> TranscriptionResult:
        """
        Transcribe an audio file to text.

        Args:
            audio_path: Path to audio file (WAV, MP3, M4A, etc.)

        Returns:
            TranscriptionResult with text and confidence.
        """

    @abstractmethod
    def transcribe_text(self, text: str) -> TranscriptionResult:
        """
        Pass pre-transcribed text through the engine (simulation shortcut).

        Used in simulation mode to bypass actual STT while still exercising
        the rest of the pipeline.
        """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable engine name for logging."""


class WhisperSTTEngine(STTEngine):
    """
    Local Whisper speech-to-text engine.

    Requires:
      pip install openai-whisper
      ffmpeg on system PATH (https://ffmpeg.org/download.html)
    """

    def __init__(self, model_size: str | None = None) -> None:
        """
        Args:
            model_size: Whisper model size (tiny/base/small/medium/large).
                        Larger = slower + more accurate.
        """
        if not _WHISPER_AVAILABLE:
            raise ImportError(
                "openai-whisper is not installed. "
                "Run: pip install openai-whisper  (also requires ffmpeg on PATH)"
            )
        self._model_size = model_size or _WHISPER_MODEL_SIZE
        logger.info("action=stt_init engine=whisper model=%s", self._model_size)
        self._model = _whisper_lib.load_model(self._model_size)
        logger.info("action=stt_model_loaded model=%s", self._model_size)

    def transcribe_file(self, audio_path: str) -> TranscriptionResult:
        """Transcribe an audio file using Whisper."""
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        logger.info("action=stt_transcribe engine=whisper file=%s", audio_path)
        result = self._model.transcribe(
            audio_path,
            language="en",
            initial_prompt=_WHISPER_PROMPT,
        )
        text = result["text"].strip()
        # Whisper doesn't expose a direct confidence score; use segment avg log_prob
        segments = result.get("segments", [])
        if segments:
            avg_log_prob = sum(s.get("avg_logprob", -1.0) for s in segments) / len(segments)
            # Convert log_prob to rough 0-1 confidence: logprob of -0.5 ≈ 0.9 confidence
            confidence = min(1.0, max(0.0, 1.0 + avg_log_prob))
        else:
            confidence = 0.8

        flagged = confidence < TranscriptionResult._REVIEW_THRESHOLD
        logger.info("action=stt_done engine=whisper chars=%d confidence=%.2f flagged=%s",
                    len(text), confidence, flagged)
        return TranscriptionResult(
            text=text,
            confidence=confidence,
            language=result.get("language", "en"),
            flagged_for_review=flagged,
        )

    def transcribe_text(self, text: str) -> TranscriptionResult:
        """Pass-through for simulation mode (text already available)."""
        return TranscriptionResult.from_text(text)

    @property
    def engine_name(self) -> str:
        return f"whisper-{self._model_size}"


class MockSTTEngine(STTEngine):
    """
    Pass-through STT engine for simulation and testing.

    Used when no audio infrastructure is available; the input text is
    returned as-is with full confidence.
    """

    def __init__(self) -> None:
        logger.debug("action=stt_init engine=mock")

    def transcribe_file(self, audio_path: str) -> TranscriptionResult:
        """Read a .txt sidecar file if present; otherwise return empty."""
        txt_path = Path(audio_path).with_suffix(".txt")
        if txt_path.exists():
            return TranscriptionResult.from_text(txt_path.read_text().strip())
        logger.warning("action=stt_mock_no_sidecar path=%s", audio_path)
        return TranscriptionResult.from_text("")

    def transcribe_text(self, text: str) -> TranscriptionResult:
        """Pass text through with full confidence."""
        return TranscriptionResult.from_text(text, confidence=1.0)

    @property
    def engine_name(self) -> str:
        return "mock"


def build_stt_engine() -> STTEngine:
    """
    Factory — select and instantiate the configured STT engine.

    Falls back to MockSTTEngine if Whisper is not installed.
    """
    if _WHISPER_AVAILABLE:
        try:
            return WhisperSTTEngine()
        except Exception as exc:
            logger.warning("action=stt_fallback reason=%s using=mock", exc)
    return MockSTTEngine()
