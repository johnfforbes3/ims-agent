"""
Integration tests: SSE /api/interview-stream endpoint.

Verifies that:
  ✓ Endpoint returns correct content-type (text/event-stream)
  ✓ Events already in relay bus are backfilled immediately on connect
  ✓ Each SSE event has all required fields (serialization via dataclasses.asdict)
  ✓ ?since=N parameter correctly skips old events
  ✓ /api/interview-recent and ?since=0 backfill return the same event set
  ✓ Cache-Control and X-Accel-Buffering headers are correct (no proxy caching)

NOTE ON SSE TESTING STRATEGY
------------------------------
httpx.ASGITransport (used by TestClient) buffers the *entire* response body
before returning — it does not support true infinite streaming.  Using
TestClient.stream() with an infinite SSE generator hangs indefinitely.

The fix: the SSE endpoint accepts ?_backfill_only=1 which makes it yield
only the already-buffered events and then close, skipping the infinite
polling loop.  Tests use plain TestClient.get() (no streaming) with this
param — fast, deterministic, and no hang risk.  The infinite loop is the
live-push mechanism; it is exercised by the relay-wiring tests and the
full E2E cycle test, not here.
"""

import json

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_relay():
    from agent.voice import interview_relay
    interview_relay.InterviewRelayBus._instance = None
    return interview_relay.InterviewRelayBus.get()


def _read_sse_data_lines(client, url_path, max_data_events=50):
    """
    Fetch the SSE endpoint in backfill-only mode (appends ?_backfill_only=1
    if not already present) and return a list of parsed JSON dicts for every
    'data: ...' line in the response body.

    Uses plain TestClient.get() — no streaming, no hang risk.
    """
    sep = "&" if "?" in url_path else "?"
    full_url = f"{url_path}{sep}_backfill_only=1"
    resp = client.get(full_url)
    assert resp.status_code == 200, f"SSE endpoint returned {resp.status_code}"

    events = []
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            events.append(json.loads(payload))
            if len(events) >= max_data_events:
                break
    return events


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def sse_client(tmp_path, monkeypatch):
    state_file = str(tmp_path / "state.json")
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", state_file)
    monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)
    srv._STATE_FILE = state_file
    srv._REPORTS_DIR = str(tmp_path)
    _reset_relay()
    yield TestClient(srv.app, raise_server_exceptions=False)
    _reset_relay()


# ===========================================================================
# Tests: content-type and headers
# ===========================================================================

class TestSSEHeaders:
    def test_returns_event_stream_content_type(self, sse_client):
        resp = sse_client.get("/api/interview-stream?_backfill_only=1")
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "text/event-stream" in ct

    def test_cache_control_no_cache(self, sse_client):
        resp = sse_client.get("/api/interview-stream?_backfill_only=1")
        cc = resp.headers.get("cache-control", "").lower()
        assert "no-cache" in cc

    def test_x_accel_buffering_no(self, sse_client):
        """nginx proxy buffering must be disabled for SSE to work."""
        resp = sse_client.get("/api/interview-stream?_backfill_only=1")
        xab = resp.headers.get("x-accel-buffering", "").lower()
        assert xab == "no"


# ===========================================================================
# Tests: backfill of existing events
# ===========================================================================

class TestSSEBackfill:
    def test_empty_stream_when_no_events(self, sse_client):
        _reset_relay()
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")
        assert events == []

    def test_backfills_one_event(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@example.com",
                          "Hi Alice!", synthesize=False)
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")
        assert len(events) == 1
        assert events[0]["speaker"] == "bot"
        assert "Alice" in events[0]["text"]

    def test_backfills_multiple_events_in_order(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice", "alice@example.com", "Q1", synthesize=False)
        bus.push_cam_turn("Alice", "alice@example.com", "A1")
        bus.push_bot_turn("Alice", "alice@example.com", "Q2", synthesize=False)
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")
        assert len(events) == 3
        seqs = [ev["seq"] for ev in events]
        assert seqs == sorted(seqs)

    def test_backfill_preserves_speaker_order(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice", "alice@example.com", "Q1", synthesize=False)
        bus.push_cam_turn("Alice", "alice@example.com", "A1")
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")
        assert events[0]["speaker"] == "bot"
        assert events[1]["speaker"] == "cam"


# ===========================================================================
# Tests: event field completeness (serialization)
# ===========================================================================

class TestSSEEventFields:
    def test_all_required_fields_present(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Carol Smith", "carol@example.com",
                          "Test message", synthesize=False)
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")
        assert len(events) == 1
        ev = events[0]
        for field in ("seq", "event_id", "timestamp", "speaker",
                      "cam_name", "cam_email", "text", "has_audio"):
            assert field in ev, f"Missing SSE field: {field}"

    def test_seq_is_integer(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Carol Smith", "carol@example.com", "Hi", synthesize=False)
        ev = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")[0]
        assert isinstance(ev["seq"], int)

    def test_has_audio_false_without_tts(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Carol Smith", "carol@example.com",
                          "No TTS", synthesize=False)
        ev = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")[0]
        assert ev["has_audio"] is False

    def test_cam_email_lowercase(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Carol Smith", "Carol@Example.COM", "Hi", synthesize=False)
        ev = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")[0]
        assert ev["cam_email"] == "carol@example.com"

    def test_event_id_is_uuid_string(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Carol Smith", "carol@example.com", "Hi", synthesize=False)
        ev = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")[0]
        import uuid
        # Should parse as a valid UUID
        uuid.UUID(ev["event_id"])  # raises ValueError if not valid


# ===========================================================================
# Tests: ?since=N parameter
# ===========================================================================

class TestSSESinceParameter:
    def test_since_0_returns_all_events(self, sse_client):
        bus = _reset_relay()
        for i in range(3):
            bus.push_bot_turn("Alice", "alice@example.com", f"Msg {i}", synthesize=False)
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=0")
        assert len(events) == 3

    def test_since_1_skips_first_event(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice", "alice@example.com", "First", synthesize=False)
        bus.push_cam_turn("Alice", "alice@example.com", "Second")
        bus.push_bot_turn("Alice", "alice@example.com", "Third", synthesize=False)
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=1")
        assert len(events) == 2
        assert all(ev["seq"] >= 1 for ev in events)

    def test_since_equal_to_seq_skips_all(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice", "alice@example.com", "Only", synthesize=False)
        # since=1 means "give me events with seq >= 1" — there are none (only seq=0)
        events = _read_sse_data_lines(sse_client, "/api/interview-stream?since=1")
        assert events == []

    def test_invalid_since_defaults_gracefully(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice", "alice@example.com", "Hello", synthesize=False)
        # Should not 500 — falls back to default behaviour
        resp = sse_client.get("/api/interview-stream?since=notanumber&_backfill_only=1")
        assert resp.status_code == 200


# ===========================================================================
# Tests: consistency between /api/interview-recent and SSE backfill
# ===========================================================================

class TestSSEAndRecentConsistency:
    def test_same_events_via_both_endpoints(self, sse_client):
        """
        /api/interview-recent and /api/interview-stream?since=0 must return
        identical events (same seq, same speaker, same text).
        """
        bus = _reset_relay()
        bus.push_bot_turn("Bob Martinez", "bob@example.com", "Hi Bob!", synthesize=False)
        bus.push_cam_turn("Bob Martinez", "bob@example.com", "Hi, SE-05 is 60%.")

        # From /api/interview-recent
        recent_resp = sse_client.get("/api/interview-recent")
        recent_events = recent_resp.json()["events"]

        # From SSE backfill
        stream_events = _read_sse_data_lines(
            sse_client, "/api/interview-stream?since=0"
        )

        assert len(recent_events) == len(stream_events) == 2
        for r, s in zip(recent_events, stream_events):
            assert r["seq"] == s["seq"]
            assert r["speaker"] == s["speaker"]
            assert r["text"] == s["text"]
            assert r["cam_email"] == s["cam_email"]

    def test_seq_from_recent_matches_stream_seq(self, sse_client):
        bus = _reset_relay()
        bus.push_bot_turn("Bob", "bob@example.com", "Q1", synthesize=False)
        bus.push_bot_turn("Bob", "bob@example.com", "Q2", synthesize=False)

        recent_seq = sse_client.get("/api/interview-recent").json()["seq"]
        stream_events = _read_sse_data_lines(
            sse_client, "/api/interview-stream?since=0"
        )
        max_stream_seq = max(ev["seq"] for ev in stream_events)
        # recent["seq"] is the NEXT seq (current_seq); max event seq = current_seq - 1
        assert recent_seq == max_stream_seq + 1
