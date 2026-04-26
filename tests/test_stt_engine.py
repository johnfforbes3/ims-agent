"""
Tests for agent.voice.stt_engine — STT abstraction layer.

Covers 2.2 checklist:
- MockSTTEngine returns pass-through transcription
- TranscriptionResult fields are correct
- build_stt_engine returns MockSTTEngine in test mode
"""

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
