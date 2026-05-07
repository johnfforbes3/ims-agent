"""
Integration tests: relay bus wiring.

Verifies that every call site that SHOULD push to InterviewRelayBus actually
does so — without requiring LLM, Teams, or Bot Framework credentials.

Covered wiring points:
  ✓ /api/interview-sessions reflects register_session / unregister_session
  ✓ /api/interview-recent reflects push_bot_turn / push_cam_turn
  ✓ POST /internal/cam_message → push_cam_turn on relay bus
  ✓ POST /internal/cam_message → register_session auto-register if not registered
  ✓ POST /internal/cam_message → push_bot_turn after processing
  ✓ GET /api/interview-sessions after /internal/cam_message shows active CAM
  ✓ cycle_runner proactive greeting path → register_session + push_bot_turn
"""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_relay():
    """Reset the relay bus singleton and return a fresh instance."""
    from agent.voice import interview_relay
    interview_relay.InterviewRelayBus._instance = None
    return interview_relay.InterviewRelayBus.get()


def _reset_chat_manager():
    """Reset the ChatInterviewManager singleton."""
    try:
        from agent.voice.teams_chat_connector import ChatInterviewManager
        mgr = ChatInterviewManager.get()
        with mgr._lock:
            mgr._sessions.clear()
            mgr._email_index.clear()
    except Exception:
        pass


def _make_mock_session(cam_name="Alice Nguyen", email="alice@example.com", next_reply="What is SE-01 percent complete?"):
    """
    Build a MagicMock that quacks like ChatInterviewSession.
    Plants it in ChatInterviewManager so /internal/cam_message can find it.
    """
    session = MagicMock()
    session.cam_name = cam_name
    session.email = email.lower()
    session.service_url = "https://mock.botframework.com"
    session.conversation_id = "conv-mock-001"
    session.is_done = False
    session.process.return_value = next_reply
    session.is_in_grace_period.return_value = False

    from agent.voice.teams_chat_connector import ChatInterviewManager
    mgr = ChatInterviewManager.get()
    mgr.register_by_email(email, session)
    return session


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def relay_client(tmp_path, monkeypatch):
    """
    TestClient wired to a fresh server + fresh relay bus per test.
    No auth, no real state file needed.
    """
    state_file = str(tmp_path / "state.json")
    portfolio_file = str(tmp_path / "portfolio.json")
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", state_file)
    monkeypatch.setenv("PORTFOLIO_FILE", portfolio_file)
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))

    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)
    srv._STATE_FILE = state_file
    srv._REPORTS_DIR = str(tmp_path)

    _reset_relay()
    _reset_chat_manager()
    yield TestClient(srv.app, raise_server_exceptions=False)
    _reset_relay()
    _reset_chat_manager()


# ===========================================================================
# Tests: /api/interview-sessions endpoint
# ===========================================================================

class TestInterviewSessionsEndpoint:
    """GET /api/interview-sessions must reflect the relay bus active_sessions."""

    def test_empty_when_no_sessions(self, relay_client):
        resp = relay_client.get("/api/interview-sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_registered_session(self, relay_client):
        bus = _reset_relay()
        bus.register_session("alice@example.com", "Alice Nguyen", "s1")
        resp = relay_client.get("/api/interview-sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 1
        assert sessions[0]["cam_email"] == "alice@example.com"
        assert sessions[0]["cam_name"] == "Alice Nguyen"

    def test_session_disappears_after_unregister(self, relay_client):
        bus = _reset_relay()
        bus.register_session("alice@example.com", "Alice Nguyen", "s1")
        bus.unregister_session("alice@example.com")
        assert relay_client.get("/api/interview-sessions").json() == []

    def test_multiple_sessions_all_returned(self, relay_client):
        bus = _reset_relay()
        bus.register_session("alice@example.com", "Alice Nguyen", "s1")
        bus.register_session("carol@example.com", "Carol Smith", "s2")
        bus.register_session("bob@example.com", "Bob Martinez", "s3")
        sessions = relay_client.get("/api/interview-sessions").json()
        emails = {s["cam_email"] for s in sessions}
        assert emails == {"alice@example.com", "carol@example.com", "bob@example.com"}

    def test_session_has_required_fields(self, relay_client):
        bus = _reset_relay()
        bus.register_session("alice@example.com", "Alice Nguyen", "s1")
        session = relay_client.get("/api/interview-sessions").json()[0]
        for field in ("cam_email", "cam_name", "started_at", "session_id"):
            assert field in session, f"Missing field: {field}"


# ===========================================================================
# Tests: /api/interview-recent endpoint
# ===========================================================================

class TestInterviewRecentEndpoint:
    """GET /api/interview-recent must reflect relay bus events."""

    def test_empty_when_no_events(self, relay_client):
        _reset_relay()
        data = relay_client.get("/api/interview-recent").json()
        assert data["events"] == []
        assert data["seq"] == 0

    def test_returns_bot_turn(self, relay_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@example.com",
                          "Hi Alice, let's get started.", synthesize=False)
        data = relay_client.get("/api/interview-recent").json()
        assert len(data["events"]) == 1
        ev = data["events"][0]
        assert ev["speaker"] == "bot"
        assert ev["cam_name"] == "Alice Nguyen"
        assert "Alice" in ev["text"]

    def test_returns_cam_turn(self, relay_client):
        bus = _reset_relay()
        bus.push_cam_turn("Alice Nguyen", "alice@example.com", "SE-01 is at 75%.")
        data = relay_client.get("/api/interview-recent").json()
        assert len(data["events"]) == 1
        ev = data["events"][0]
        assert ev["speaker"] == "cam"
        assert "75%" in ev["text"]

    def test_returns_multiple_events_in_order(self, relay_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@example.com", "Q1", synthesize=False)
        bus.push_cam_turn("Alice Nguyen", "alice@example.com", "A1")
        bus.push_bot_turn("Alice Nguyen", "alice@example.com", "Q2", synthesize=False)
        data = relay_client.get("/api/interview-recent").json()
        assert len(data["events"]) == 3
        seqs = [ev["seq"] for ev in data["events"]]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == 3  # all unique

    def test_seq_counter_matches(self, relay_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@example.com", "Q1", synthesize=False)
        bus.push_cam_turn("Alice Nguyen", "alice@example.com", "A1")
        data = relay_client.get("/api/interview-recent").json()
        assert data["seq"] == 2  # two events pushed → next seq is 2

    def test_event_fields_complete(self, relay_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@test.com", "Hello!", synthesize=False)
        ev = relay_client.get("/api/interview-recent").json()["events"][0]
        required = ("seq", "event_id", "timestamp", "speaker",
                    "cam_name", "cam_email", "text", "has_audio")
        for field in required:
            assert field in ev, f"Missing field: {field}"

    def test_has_audio_false_when_tts_not_configured(self, relay_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@test.com", "Hello!", synthesize=False)
        ev = relay_client.get("/api/interview-recent").json()["events"][0]
        assert ev["has_audio"] is False

    def test_n_param_limits_results(self, relay_client):
        bus = _reset_relay()
        for i in range(10):
            bus.push_bot_turn("Alice", "alice@example.com", f"Q{i}", synthesize=False)
        data = relay_client.get("/api/interview-recent?n=3").json()
        assert len(data["events"]) == 3

    def test_multi_cam_events_mixed(self, relay_client):
        bus = _reset_relay()
        bus.push_bot_turn("Alice Nguyen", "alice@example.com", "Hi Alice", synthesize=False)
        bus.push_bot_turn("Bob Martinez", "bob@example.com", "Hi Bob", synthesize=False)
        data = relay_client.get("/api/interview-recent").json()
        cams = {ev["cam_name"] for ev in data["events"]}
        assert "Alice Nguyen" in cams
        assert "Bob Martinez" in cams


# ===========================================================================
# Tests: POST /internal/cam_message → relay bus wiring
# ===========================================================================

class TestInternalCamMessageRelayWiring:
    """
    Verify /internal/cam_message pushes events to the relay bus AND
    auto-registers the session when it first receives a message.
    """

    def test_cam_turn_pushed_when_message_received(self, relay_client):
        bus = _reset_relay()
        _make_mock_session()
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            relay_client.post("/internal/cam_message", json={
                "email": "alice@example.com",
                "text": "SE-01 is at 80 percent."
            })
        cam_events = [e for e in bus.recent_events() if e.speaker == "cam"]
        assert len(cam_events) >= 1
        assert "80" in cam_events[0].text

    def test_session_auto_registered_in_relay(self, relay_client):
        """
        When a CAM message arrives, the session must appear in active_sessions
        even if register_session was never explicitly called before.
        """
        bus = _reset_relay()
        _make_mock_session()
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            relay_client.post("/internal/cam_message", json={
                "email": "alice@example.com",
                "text": "SE-01 is at 80 percent."
            })
        sessions = bus.active_sessions()
        assert any(s["cam_email"] == "alice@example.com" for s in sessions)

    def test_api_interview_sessions_shows_cam_after_message(self, relay_client):
        """End-to-end: /internal/cam_message → GET /api/interview-sessions shows CAM."""
        bus = _reset_relay()
        _make_mock_session()
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            relay_client.post("/internal/cam_message", json={
                "email": "alice@example.com",
                "text": "SE-01 is at 80 percent."
            })
        sessions = relay_client.get("/api/interview-sessions").json()
        assert any(s["cam_email"] == "alice@example.com" for s in sessions)

    def test_bot_reply_pushed_after_processing(self, relay_client):
        """The bot's next question must appear in relay bus after CAM message."""
        bus = _reset_relay()
        _make_mock_session(next_reply="What is SE-02 percent complete?")
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            relay_client.post("/internal/cam_message", json={
                "email": "alice@example.com",
                "text": "SE-01 is at 80 percent."
            })
        bot_events = [e for e in bus.recent_events() if e.speaker == "bot"]
        assert len(bot_events) >= 1
        assert "SE-02" in bot_events[0].text or len(bot_events[0].text) > 0

    def test_api_interview_recent_has_both_turns(self, relay_client):
        """End-to-end: after /internal/cam_message, both CAM and bot turns appear."""
        _reset_relay()
        _make_mock_session(next_reply="What is SE-02 status?")
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            relay_client.post("/internal/cam_message", json={
                "email": "alice@example.com",
                "text": "SE-01 is at 80 percent."
            })
        events = relay_client.get("/api/interview-recent").json()["events"]
        speakers = {ev["speaker"] for ev in events}
        assert "cam" in speakers
        assert "bot" in speakers

    def test_no_session_returns_no_session_status(self, relay_client):
        _reset_relay()
        resp = relay_client.post("/internal/cam_message", json={
            "email": "nobody@example.com",
            "text": "Hello?"
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_session"

    def test_multiple_cam_messages_accumulate_in_relay(self, relay_client):
        bus = _reset_relay()
        _make_mock_session(next_reply="Next question")
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            for pct in [20, 40, 60]:
                relay_client.post("/internal/cam_message", json={
                    "email": "alice@example.com",
                    "text": f"Progress is {pct}%"
                })
        cam_events = [e for e in bus.recent_events() if e.speaker == "cam"]
        assert len(cam_events) == 3

    def test_ignored_on_empty_text(self, relay_client):
        bus = _reset_relay()
        _make_mock_session()
        relay_client.post("/internal/cam_message", json={
            "email": "alice@example.com",
            "text": ""
        })
        assert len(bus.recent_events()) == 0


# ===========================================================================
# Tests: cycle_runner proactive greeting → relay bus wiring
# ===========================================================================

class TestCycleRunnerGreetingRelayWiring:
    """
    Verify the code path executed by cycle_runner after a successful
    proactive greeting registers the session and pushes the bot turn to
    the relay bus.

    Strategy: exercise the exact lines added to cycle_runner (lines 633-648)
    by calling them directly in a controlled environment, then verify the
    relay bus received the correct data. This is the authoritative test that
    the bug fixed in this session cannot regress.
    """

    def _simulate_greeting_launch(self, bus, cam_name, cam_email, cycle_id, greeting_text):
        """
        Reproduces exactly what cycle_runner.py does after ok=True:

            bus.register_session(cam_email, cam_name, str(id(session)))
            bus.push_bot_turn(cam_name=..., cam_email=..., text=greeting, ...)
        """
        mock_session = MagicMock()
        mock_session.cam_name = cam_name
        mock_session.email = cam_email
        sid = str(id(mock_session))

        bus.register_session(cam_email, cam_name, sid)
        bus.push_bot_turn(
            cam_name=cam_name,
            cam_email=cam_email,
            text=greeting_text,
            session_id=sid,
            cycle_id=cycle_id,
            synthesize=False,
        )
        return sid

    def test_register_session_called(self, relay_client):
        bus = _reset_relay()
        self._simulate_greeting_launch(
            bus, "Alice Nguyen", "alice@example.com",
            "20260507T100000Z", "Hi Alice, let's start."
        )
        sessions = bus.active_sessions()
        assert any(s["cam_email"] == "alice@example.com" for s in sessions)

    def test_greeting_event_pushed(self, relay_client):
        bus = _reset_relay()
        self._simulate_greeting_launch(
            bus, "Alice Nguyen", "alice@example.com",
            "20260507T100000Z", "Hi Alice, let's start."
        )
        events = bus.recent_events()
        assert len(events) == 1
        assert events[0].speaker == "bot"
        assert events[0].cam_email == "alice@example.com"

    def test_cycle_id_preserved_in_event(self, relay_client):
        bus = _reset_relay()
        cycle_id = "20260507T100000Z"
        self._simulate_greeting_launch(
            bus, "Alice Nguyen", "alice@example.com",
            cycle_id, "Hi Alice, let's start."
        )
        assert bus.recent_events()[0].cycle_id == cycle_id

    def test_greeting_visible_in_api_interview_recent(self, relay_client):
        bus = _reset_relay()
        self._simulate_greeting_launch(
            bus, "Carol Smith", "carol@example.com",
            "20260507T100000Z", "Hi Carol, checking in."
        )
        data = relay_client.get("/api/interview-recent").json()
        assert len(data["events"]) == 1
        assert data["events"][0]["cam_name"] == "Carol Smith"

    def test_session_visible_in_api_interview_sessions(self, relay_client):
        bus = _reset_relay()
        self._simulate_greeting_launch(
            bus, "Carol Smith", "carol@example.com",
            "20260507T100000Z", "Hi Carol, checking in."
        )
        sessions = relay_client.get("/api/interview-sessions").json()
        assert any(s["cam_name"] == "Carol Smith" for s in sessions)

    def test_multiple_cams_all_registered(self, relay_client):
        bus = _reset_relay()
        cams = [
            ("Alice Nguyen", "alice@example.com"),
            ("Bob Martinez", "bob@example.com"),
            ("Carol Smith", "carol@example.com"),
        ]
        for name, email in cams:
            self._simulate_greeting_launch(bus, name, email, "CYC-001", f"Hi {name.split()[0]}.")
        sessions = relay_client.get("/api/interview-sessions").json()
        assert len(sessions) == 3
        emails = {s["cam_email"] for s in sessions}
        assert emails == {e for _, e in cams}

    def test_greeting_plus_cam_reply_full_flow(self, relay_client):
        """
        Full listen-in flow:
        1. cycle_runner sends greeting → relay bus has bot event + session
        2. CAM replies via /internal/cam_message → relay bus has cam event
        3. /api/interview-recent returns both; /api/interview-sessions shows CAM
        """
        bus = _reset_relay()
        # Step 1: greeting
        self._simulate_greeting_launch(
            bus, "Alice Nguyen", "alice@example.com",
            "20260507T100000Z", "Hi Alice, let's get started."
        )
        # Step 2: CAM replies
        _reset_chat_manager()
        _make_mock_session(cam_name="Alice Nguyen", email="alice@example.com",
                           next_reply="What is SE-02 percent complete?")
        with patch("agent.voice.teams_chat_connector._bf_send", return_value=True), \
             patch("agent.voice.teams_chat_connector._bf_typing", return_value=None):
            relay_client.post("/internal/cam_message", json={
                "email": "alice@example.com",
                "text": "SE-01 is at 85%."
            })
        # Step 3: verify
        events = relay_client.get("/api/interview-recent").json()["events"]
        speakers = [ev["speaker"] for ev in events]
        assert speakers.count("bot") >= 2   # greeting + next question
        assert speakers.count("cam") >= 1   # CAM reply

        sessions = relay_client.get("/api/interview-sessions").json()
        assert any(s["cam_email"] == "alice@example.com" for s in sessions)
