"""
Tests for agent.voice.tts_engine — TTS abstraction layer.

Covers 2.3 checklist:
- MockTTSEngine records utterances and returns empty bytes
- build_tts_engine returns MockTTSEngine when TTS_ENGINE env is not set
- synthesize_to_file writes to the given path
"""

import os
import pytest
from pathlib import Path
from agent.voice.tts_engine import MockTTSEngine, build_tts_engine


class TestMockTTSEngine:
    def test_synthesize_returns_bytes(self):
        engine = MockTTSEngine()
        result = engine.synthesize("Hello, this is a test.")
        assert isinstance(result, bytes)

    def test_synthesize_records_utterance(self):
        engine = MockTTSEngine()
        engine.synthesize("First line.")
        engine.synthesize("Second line.")
        assert engine.utterances == ["First line.", "Second line."]

    def test_synthesize_to_file_creates_file(self, tmp_path):
        engine = MockTTSEngine()
        out = str(tmp_path / "test_audio.wav")
        path = engine.synthesize_to_file("Test text.", out)
        assert Path(path).exists()

    def test_synthesize_to_file_returns_path(self, tmp_path):
        engine = MockTTSEngine()
        out = str(tmp_path / "audio.wav")
        returned = engine.synthesize_to_file("Text.", out)
        assert returned == out

    def test_empty_utterances_on_init(self):
        engine = MockTTSEngine()
        assert engine.utterances == []


class TestBuildTTSEngine:
    def test_returns_mock_when_no_key(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
        monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
        # Re-import to pick up patched env (module-level vars are already cached;
        # call the factory which re-reads the module globals via closure)
        from agent.voice import tts_engine as _mod
        _mod._ELEVENLABS_KEY = ""
        engine = _mod.build_tts_engine()
        assert isinstance(engine, MockTTSEngine)

    def test_returns_mock_for_mock_provider(self, monkeypatch):
        from agent.voice import tts_engine as _mod
        original = _mod._PROVIDER
        _mod._PROVIDER = "mock_fallback"
        _mod._ELEVENLABS_KEY = ""
        try:
            engine = _mod.build_tts_engine()
            assert isinstance(engine, MockTTSEngine)
        finally:
            _mod._PROVIDER = original
