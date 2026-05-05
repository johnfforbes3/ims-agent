"""
Tests for agent.voice.stt_engine — STT abstraction layer.

Covers 2.2 checklist:
- MockSTTEngine returns pass-through transcription
- TranscriptionResult fields are correct
- build_stt_engine returns MockSTTEngine in test mode

Integration tests (TD-010):
- WhisperSTTEngine loads model and processes a synthetic WAV without errors
- Marked @pytest.mark.integration; skipped automatically when openai-whisper
  is not installed.  Run manually: pytest tests/test_stt_engine.py -m integration
  Requires: pip install openai-whisper  (and ffmpeg on PATH)
"""

import math
import struct
import wave
import os
import pytest
from agent.voice.stt_engine import MockSTTEngine, TranscriptionResult, build_stt_engine


class TestMockSTTEngine:
    def test_transcribe_text_passthrough(self):
        engine = MockSTTEngine()
        result = engine.transcribe_text("Hello world.")
        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world."

    def test_confidence_is_one(self):
        engine = MockSTTEngine()
        result = engine.transcribe_text("Test.")
        assert result.confidence == 1.0

    def test_language_is_en(self):
        engine = MockSTTEngine()
        result = engine.transcribe_text("Test.")
        assert result.language == "en"

    def test_not_flagged_for_review(self):
        engine = MockSTTEngine()
        result = engine.transcribe_text("Normal response.")
        assert result.flagged_for_review is False

    def test_transcribe_file_returns_result(self, tmp_path):
        # Create a dummy audio file (content irrelevant for mock)
        f = tmp_path / "dummy.wav"
        f.write_bytes(b"\x00" * 100)
        engine = MockSTTEngine()
        result = engine.transcribe_file(str(f))
        assert isinstance(result, TranscriptionResult)


class TestBuildSTTEngine:
    def test_returns_mock_when_whisper_unavailable(self, monkeypatch):
        from agent.voice import stt_engine as _mod
        original = _mod._WHISPER_AVAILABLE
        _mod._WHISPER_AVAILABLE = False
        try:
            engine = _mod.build_stt_engine()
            assert isinstance(engine, MockSTTEngine)
        finally:
            _mod._WHISPER_AVAILABLE = original


# ---------------------------------------------------------------------------
# TD-010 — Whisper integration tests
# Run manually: pytest tests/test_stt_engine.py -m integration
# Requires: pip install openai-whisper  (and ffmpeg on PATH)
# ---------------------------------------------------------------------------

def _make_wav(path, duration_sec: float = 0.5, sample_rate: int = 16000) -> None:
    """Generate a minimal WAV file containing a 440 Hz sine tone."""
    n = int(sample_rate * duration_sec)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)          # 16-bit PCM
        wf.setframerate(sample_rate)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / sample_rate)))
            for i in range(n)
        )
        wf.writeframes(frames)


def _whisper_available() -> bool:
    try:
        import whisper  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.integration
class TestWhisperIntegration:
    """Integration tests for WhisperSTTEngine (TD-010).

    Skipped automatically when openai-whisper is not installed.
    These tests validate the full pipeline without asserting specific
    transcription content (a 440 Hz tone is not intelligible speech).
    """

    def test_whisper_package_importable(self):
        if not _whisper_available():
            pytest.skip("openai-whisper not installed")
        import whisper  # noqa: F401

    def test_engine_instantiates_with_tiny_model(self):
        if not _whisper_available():
            pytest.skip("openai-whisper not installed")
        from agent.voice.stt_engine import WhisperSTTEngine
        engine = WhisperSTTEngine(model_size="tiny")
        assert engine.engine_name == "whisper-tiny"

    def test_transcribe_file_returns_transcription_result(self, tmp_path):
        if not _whisper_available():
            pytest.skip("openai-whisper not installed")
        from agent.voice.stt_engine import WhisperSTTEngine, TranscriptionResult
        wav = tmp_path / "tone.wav"
        _make_wav(wav)
        engine = WhisperSTTEngine(model_size="tiny")
        result = engine.transcribe_file(str(wav))
        assert isinstance(result, TranscriptionResult)
        assert isinstance(result.text, str)
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.language, str)
        assert isinstance(result.flagged_for_review, bool)

    def test_transcribe_missing_file_raises(self):
        if not _whisper_available():
            pytest.skip("openai-whisper not installed")
        from agent.voice.stt_engine import WhisperSTTEngine
        engine = WhisperSTTEngine(model_size="tiny")
        with pytest.raises(FileNotFoundError):
            engine.transcribe_file("/nonexistent/path/to/audio.wav")
