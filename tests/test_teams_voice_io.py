"""
Tests for Phase 17.2 + 17.3 — Teams voice IO shim.

Verifies the edge plumbing without making any real Bot Framework or
Whisper API calls. All externals (BF token + audio download, Whisper STT,
ElevenLabs TTS) are mocked.

The text path through /bot/messages MUST remain unchanged when voice
features are disabled — this is the primary safety property.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────
# is_voice_message — attachment detection
# ──────────────────────────────────────────────────────────────────────────


class TestIsVoiceMessage:
    def setup_method(self):
        os.environ["TEAMS_VOICE_IN"] = "true"
        import importlib, agent.voice.teams_voice_io as M
        importlib.reload(M)
        self.M = M

    def test_returns_false_on_text_only_activity(self):
        body = {"type": "message", "text": "Task one at sixty percent."}
        assert self.M.is_voice_message(body) is False

    def test_returns_false_on_empty_body(self):
        assert self.M.is_voice_message({}) is False
        assert self.M.is_voice_message({"attachments": []}) is False
        assert self.M.is_voice_message({"attachments": None}) is False

    def test_returns_true_on_audio_attachment(self):
        body = {
            "type": "message",
            "text": "",
            "attachments": [
                {"contentType": "audio/mpeg",
                 "contentUrl": "https://bot.example.com/audio/abc"},
            ],
        }
        assert self.M.is_voice_message(body) is True

    def test_returns_true_on_voice_contenttype(self):
        body = {
            "type": "message",
            "attachments": [{"contentType": "voice/wav", "contentUrl": "x"}],
        }
        assert self.M.is_voice_message(body) is True

    def test_returns_false_for_image_attachment(self):
        body = {
            "type": "message",
            "attachments": [{"contentType": "image/png", "contentUrl": "x"}],
        }
        assert self.M.is_voice_message(body) is False

    def test_returns_false_when_voice_in_disabled(self):
        os.environ["TEAMS_VOICE_IN"] = "false"
        import importlib
        importlib.reload(self.M)
        body = {
            "type": "message",
            "attachments": [{"contentType": "audio/mpeg", "contentUrl": "x"}],
        }
        assert self.M.is_voice_message(body) is False


# ──────────────────────────────────────────────────────────────────────────
# transcribe_voice_attachment — happy path + failure modes
# ──────────────────────────────────────────────────────────────────────────


class TestTranscribeVoiceAttachment:
    def setup_method(self):
        os.environ["TEAMS_VOICE_IN"] = "true"
        import importlib, agent.voice.teams_voice_io as M
        importlib.reload(M)
        self.M = M

    def test_returns_transcript_on_happy_path(self):
        body = {
            "attachments": [
                {"contentType": "audio/mpeg", "contentUrl": "https://x/audio.mp3"},
            ],
        }
        with patch.object(self.M, "_bf_authed_get", return_value=b"\x00" * 4096), \
             patch("agent.voice_v2.stt_openai.transcribe_bytes") as mock_stt:
            mock_stt.return_value = MagicMock(text="Task one at sixty percent.",
                                              latency_ms=200, cost_usd=0.001)
            text = self.M.transcribe_voice_attachment(body)
        assert text == "Task one at sixty percent."

    def test_returns_none_when_download_fails(self):
        body = {
            "attachments": [
                {"contentType": "audio/mpeg", "contentUrl": "https://x/audio.mp3"},
            ],
        }
        with patch.object(self.M, "_bf_authed_get", return_value=None):
            assert self.M.transcribe_voice_attachment(body) is None

    def test_returns_none_when_no_audio_attachment(self):
        body = {"attachments": [{"contentType": "image/png", "contentUrl": "x"}]}
        assert self.M.transcribe_voice_attachment(body) is None

    def test_returns_none_when_stt_raises(self):
        body = {
            "attachments": [
                {"contentType": "audio/wav", "contentUrl": "https://x/audio.wav"},
            ],
        }
        with patch.object(self.M, "_bf_authed_get", return_value=b"\x00" * 4096), \
             patch("agent.voice_v2.stt_openai.transcribe_bytes",
                   side_effect=RuntimeError("whisper down")):
            assert self.M.transcribe_voice_attachment(body) is None

    def test_returns_none_when_transcript_empty(self):
        body = {
            "attachments": [
                {"contentType": "audio/mpeg", "contentUrl": "https://x/audio.mp3"},
            ],
        }
        with patch.object(self.M, "_bf_authed_get", return_value=b"\x00" * 4096), \
             patch("agent.voice_v2.stt_openai.transcribe_bytes") as mock_stt:
            mock_stt.return_value = MagicMock(text="   ", latency_ms=200, cost_usd=0)
            assert self.M.transcribe_voice_attachment(body) is None

    def test_extension_picked_from_content_type(self):
        body = {
            "attachments": [
                {"contentType": "audio/webm", "contentUrl": "https://x/a.webm"},
            ],
        }
        captured = {}
        def _stt(audio_bytes, filename="audio.webm", **kwargs):
            captured["filename"] = filename
            return MagicMock(text="hi", latency_ms=0, cost_usd=0)
        with patch.object(self.M, "_bf_authed_get", return_value=b"\x00" * 4096), \
             patch("agent.voice_v2.stt_openai.transcribe_bytes", side_effect=_stt):
            self.M.transcribe_voice_attachment(body)
        assert captured["filename"].endswith(".webm")


# ──────────────────────────────────────────────────────────────────────────
# Outbound audio cache — one-shot serve-and-discard
# ──────────────────────────────────────────────────────────────────────────


class TestAudioCache:
    def setup_method(self):
        import importlib, agent.voice.teams_voice_io as M
        importlib.reload(M)
        self.M = M

    def test_register_and_consume_roundtrip(self):
        aid = self.M.register_outbound_audio(b"audio-bytes-here", "audio/mpeg")
        pair = self.M.consume_outbound_audio(aid)
        assert pair == (b"audio-bytes-here", "audio/mpeg")

    def test_consume_is_one_shot(self):
        aid = self.M.register_outbound_audio(b"x", "audio/mpeg")
        self.M.consume_outbound_audio(aid)
        assert self.M.consume_outbound_audio(aid) is None  # already consumed

    def test_consume_unknown_id_returns_none(self):
        assert self.M.consume_outbound_audio("not-a-real-id") is None


# ──────────────────────────────────────────────────────────────────────────
# bf_reply_with_audio — preserves text-only behavior on every fail path
# ──────────────────────────────────────────────────────────────────────────


class TestBfReplyWithAudio:
    def setup_method(self):
        os.environ["TEAMS_VOICE_OUT"] = "true"
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://ngrok.example.com"
        import importlib, agent.voice.teams_voice_io as M
        importlib.reload(M)
        self.M = M

    def test_voice_out_disabled_uses_text_only(self):
        """When TEAMS_VOICE_OUT=false, falls through to the unchanged
        text-only _bf_reply path. This is the safety property."""
        os.environ["TEAMS_VOICE_OUT"] = "false"
        import importlib
        importlib.reload(self.M)
        with patch("agent.voice.teams_chat_connector._bf_reply") as mock_reply:
            self.M.bf_reply_with_audio("https://svc", "conv1", "act1",
                                       "Hello", b"audio-bytes", "Alice", "alice@x")
            mock_reply.assert_called_once_with("https://svc", "conv1", "act1", "Hello")

    def test_no_audio_bytes_uses_text_only(self):
        """When audio synthesis returned None, falls through to text-only."""
        with patch("agent.voice.teams_chat_connector._bf_reply") as mock_reply:
            self.M.bf_reply_with_audio("https://svc", "conv1", "act1",
                                       "Hello", None, "Alice", "alice@x")
            mock_reply.assert_called_once_with("https://svc", "conv1", "act1", "Hello")

    def test_localhost_base_url_falls_back_to_text(self):
        """Teams clients can't fetch http://localhost — fall back to text."""
        os.environ["DASHBOARD_PUBLIC_URL"] = "http://localhost:9000"
        import importlib
        importlib.reload(self.M)
        with patch("agent.voice.teams_chat_connector._bf_reply") as mock_reply:
            self.M.bf_reply_with_audio("https://svc", "conv1", "act1",
                                       "Hello", b"\x00" * 100, "Alice", "alice@x")
            mock_reply.assert_called_once_with("https://svc", "conv1", "act1", "Hello")

    def test_happy_path_posts_text_with_audio_attachment(self):
        """When all conditions met, posts ONE activity with text + audio attachment."""
        with patch("agent.voice.teams_chat_connector._get_bf_token", return_value="tok"), \
             patch("agent.voice.teams_chat_connector._bf_reply") as mock_text_fallback, \
             patch("agent.voice.teams_voice_io.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200, text="ok")
            self.M.bf_reply_with_audio("https://svc", "conv1", "act1",
                                       "Hello there", b"\x00" * 100, "Alice", "alice@x")
            # The text fallback must NOT have been called
            mock_text_fallback.assert_not_called()
            # The combined post must have happened
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1] if len(mock_post.call_args.args) > 1 else mock_post.call_args.kwargs["json"]
            assert payload["type"] == "message"
            assert payload["text"] == "Hello there"
            assert len(payload["attachments"]) == 1
            assert payload["attachments"][0]["contentType"] == "audio/mpeg"
            assert payload["attachments"][0]["contentUrl"].startswith("https://ngrok.example.com/teams/audio/")

    def test_failed_post_falls_back_to_text(self):
        """If the combined post fails (4xx/5xx), fall back to text-only."""
        with patch("agent.voice.teams_chat_connector._get_bf_token", return_value="tok"), \
             patch("agent.voice.teams_chat_connector._bf_reply") as mock_text_fallback, \
             patch("agent.voice.teams_voice_io.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=500, text="boom")
            self.M.bf_reply_with_audio("https://svc", "conv1", "act1",
                                       "Hello", b"\x00" * 100, "Alice", "alice@x")
            mock_text_fallback.assert_called_once_with("https://svc", "conv1", "act1", "Hello")


# ──────────────────────────────────────────────────────────────────────────
# /teams/audio/{audio_id} server route
# ──────────────────────────────────────────────────────────────────────────


class TestTeamsAudioRoute:
    def test_serves_registered_audio_once(self):
        from agent.voice.teams_voice_io import register_outbound_audio
        from fastapi.testclient import TestClient
        from agent.dashboard import server as srv
        client = TestClient(srv.app)
        aid = register_outbound_audio(b"mp3-bytes", "audio/mpeg")
        r1 = client.get(f"/teams/audio/{aid}")
        assert r1.status_code == 200
        assert r1.content == b"mp3-bytes"
        # Second fetch should 404 (one-shot semantics)
        r2 = client.get(f"/teams/audio/{aid}")
        assert r2.status_code == 404

    def test_unknown_audio_id_404(self):
        from fastapi.testclient import TestClient
        from agent.dashboard import server as srv
        client = TestClient(srv.app)
        r = client.get("/teams/audio/nonexistent-id-xyz")
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# _should_synthesize gate — skip TTS for short acknowledgments
# ──────────────────────────────────────────────────────────────────────────


class TestSynthesisGate:
    def setup_method(self):
        os.environ["TEAMS_VOICE_OUT_MIN_CHARS"] = "20"
        import importlib, agent.voice.teams_voice_io as M
        importlib.reload(M)
        self.M = M

    def test_short_reply_skips_synthesis(self):
        assert self.M._should_synthesize("Got it.") is False
        assert self.M._should_synthesize("OK.") is False
        assert self.M._should_synthesize("") is False

    def test_normal_reply_synthesizes(self):
        assert self.M._should_synthesize(
            "Got it. Any blockers on this task?"
        ) is True

    def test_synthesize_reply_audio_returns_none_for_short(self):
        # Don't even hit TTS on short replies
        with patch("agent.voice_v2.tts.synthesize") as mock_tts:
            result = self.M.synthesize_reply_audio("Got it.", "Alice", "alice@x")
            assert result is None
            mock_tts.assert_not_called()
