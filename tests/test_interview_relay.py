"""
Tests for agent.voice.interview_relay — the live interview event bus.

Covers:
  - Event push / seq numbering
  - Cursor-based polling (events_since)
  - Bot and CAM turn helpers
  - Audio store / retrieve
  - Session registration / unregister
  - MAX_EVENTS trim
  - TTS mock path (no ElevenLabs key)
"""

import dataclasses
import time

import pytest


# ---------------------------------------------------------------------------
# Fresh bus for each test (bypass singleton)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_bus():
    """Return a new InterviewRelayBus (bypasses singleton) for isolation."""
    from agent.voice import interview_relay as _mod
    bus = _mod.InterviewRelayBus()
    yield bus
    # Ensure background thread pool is drained
    bus._tts_pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Basic event push
# ---------------------------------------------------------------------------

def test_push_assigns_seq(fresh_bus):
    bus = fresh_bus
    from agent.voice.interview_relay import InterviewEvent
    ev = InterviewEvent(seq=0, event_id="a", timestamp=time.time(),
                        speaker="bot", cam_name="Alice", cam_email="a@x.com", text="Hello")
    out = bus.push_event(ev)
    assert out.seq == 0
    assert bus.current_seq == 1


def test_push_increments_seq(fresh_bus):
    bus = fresh_bus
    from agent.voice.interview_relay import InterviewEvent
    for i in range(5):
        ev = InterviewEvent(seq=0, event_id=str(i), timestamp=time.time(),
                            speaker="bot", cam_name="Alice", cam_email="a@x.com", text=f"turn {i}")
        bus.push_event(ev)
    assert bus.current_seq == 5


# ---------------------------------------------------------------------------
# Cursor-based polling
# ---------------------------------------------------------------------------

def test_events_since_zero(fresh_bus):
    bus = fresh_bus
    from agent.voice.interview_relay import InterviewEvent
    for i in range(3):
        ev = InterviewEvent(seq=0, event_id=str(i), timestamp=time.time(),
                            speaker="cam", cam_name="Bob", cam_email="b@x.com", text=str(i))
        bus.push_event(ev)
    result = bus.events_since(0)
    assert len(result) == 3
    assert [e.seq for e in result] == [0, 1, 2]


def test_events_since_cursor(fresh_bus):
    bus = fresh_bus
    from agent.voice.interview_relay import InterviewEvent
    for i in range(5):
        ev = InterviewEvent(seq=0, event_id=str(i), timestamp=time.time(),
                            speaker="bot", cam_name="C", cam_email="c@x.com", text=str(i))
        bus.push_event(ev)
    result = bus.events_since(3)
    assert len(result) == 2
    assert result[0].seq == 3
    assert result[1].seq == 4


def test_events_since_beyond_end(fresh_bus):
    bus = fresh_bus
    from agent.voice.interview_relay import InterviewEvent
    ev = InterviewEvent(seq=0, event_id="x", timestamp=time.time(),
                        speaker="bot", cam_name="D", cam_email="d@x.com", text="hi")
    bus.push_event(ev)
    assert bus.events_since(99) == []


# ---------------------------------------------------------------------------
# push_bot_turn / push_cam_turn helpers
# ---------------------------------------------------------------------------

def test_push_bot_turn_no_tts(fresh_bus):
    bus = fresh_bus
    ev = bus.push_bot_turn("Alice", "a@x.com", "What's your status?", synthesize=False)
    assert ev.speaker == "bot"
    assert ev.cam_email == "a@x.com"
    assert ev.has_audio is False
    assert bus.current_seq == 1


def test_push_cam_turn(fresh_bus):
    bus = fresh_bus
    ev = bus.push_cam_turn("Alice", "alice@example.com", "I'm on track")
    assert ev.speaker == "cam"
    assert ev.cam_email == "alice@example.com"
    # has_audio depends on TTS config; just check it's a bool
    assert isinstance(ev.has_audio, bool)


def test_push_bot_turn_email_lowercased(fresh_bus):
    bus = fresh_bus
    ev = bus.push_bot_turn("Bob", "BOB@Corp.com", "hi", synthesize=False)
    assert ev.cam_email == "bob@corp.com"


# ---------------------------------------------------------------------------
# Audio store / retrieve
# ---------------------------------------------------------------------------

def test_store_and_get_audio(fresh_bus):
    bus = fresh_bus
    bus.store_audio("ev1", b"FAKEMP3")
    assert bus.get_audio("ev1") == b"FAKEMP3"


def test_get_audio_missing(fresh_bus):
    bus = fresh_bus
    assert bus.get_audio("nonexistent") is None


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------

def test_register_and_list_session(fresh_bus):
    bus = fresh_bus
    bus.register_session("alice@x.com", "Alice", "sess-1")
    sessions = bus.active_sessions()
    assert len(sessions) == 1
    assert sessions[0]["cam_email"] == "alice@x.com"
    assert sessions[0]["cam_name"] == "Alice"


def test_unregister_session(fresh_bus):
    bus = fresh_bus
    bus.register_session("bob@x.com", "Bob", "sess-2")
    bus.unregister_session("bob@x.com")
    assert bus.active_sessions() == []


def test_register_case_insensitive(fresh_bus):
    bus = fresh_bus
    bus.register_session("Alice@Corp.COM", "Alice", "s")
    bus.unregister_session("alice@corp.com")
    assert bus.active_sessions() == []


# ---------------------------------------------------------------------------
# MAX_EVENTS trim
# ---------------------------------------------------------------------------

def test_max_events_trim():
    """Bus should not grow unboundedly past _MAX_EVENTS."""
    from agent.voice import interview_relay as _mod
    bus = _mod.InterviewRelayBus()
    try:
        original_max = _mod._MAX_EVENTS
        _mod._MAX_EVENTS = 10
        from agent.voice.interview_relay import InterviewEvent
        for i in range(15):
            ev = InterviewEvent(seq=0, event_id=str(i), timestamp=time.time(),
                                speaker="bot", cam_name="X", cam_email="x@x.com", text=str(i))
            bus.push_event(ev)
        # After trimming, at most _MAX_EVENTS events remain
        with bus._lock:
            assert len(bus._events) <= 10
    finally:
        _mod._MAX_EVENTS = original_max
        bus._tts_pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# recent_events
# ---------------------------------------------------------------------------

def test_recent_events(fresh_bus):
    bus = fresh_bus
    from agent.voice.interview_relay import InterviewEvent
    for i in range(10):
        ev = InterviewEvent(seq=0, event_id=str(i), timestamp=time.time(),
                            speaker="cam", cam_name="Z", cam_email="z@z.com", text=str(i))
        bus.push_event(ev)
    recent = bus.recent_events(3)
    assert len(recent) == 3
    assert recent[-1].seq == 9


# ---------------------------------------------------------------------------
# Voice assignment
# ---------------------------------------------------------------------------

def test_cam_voice_assigned(fresh_bus):
    bus = fresh_bus
    voice = bus.get_cam_voice("alice@x.com")
    assert isinstance(voice, str)
    assert len(voice) > 5   # sanity: not empty


def test_cam_voice_stable(fresh_bus):
    """Same email always returns the same voice."""
    bus = fresh_bus
    v1 = bus.get_cam_voice("bob@x.com")
    v2 = bus.get_cam_voice("bob@x.com")
    assert v1 == v2


def test_cam_voices_distinct(fresh_bus):
    """Different CAMs get different voices (assuming pool has ≥ 2 entries)."""
    from agent.voice import interview_relay as _mod
    if len(_mod._CAM_VOICE_POOL) < 2:
        pytest.skip("pool too small to guarantee distinct voices")
    bus = fresh_bus
    v_alice = bus.get_cam_voice("alice@x.com")
    v_bob   = bus.get_cam_voice("bob@x.com")
    assert v_alice != v_bob


def test_cam_voice_email_case_insensitive(fresh_bus):
    bus = fresh_bus
    v1 = bus.get_cam_voice("Carol@Corp.COM")
    v2 = bus.get_cam_voice("carol@corp.com")
    assert v1 == v2


def test_cam_voice_assignments_map(fresh_bus):
    bus = fresh_bus
    bus.get_cam_voice("alice@x.com")
    bus.get_cam_voice("bob@x.com")
    assignments = bus.cam_voice_assignments()
    assert "alice@x.com" in assignments
    assert "bob@x.com" in assignments


# ---------------------------------------------------------------------------
# Dataclass serialisation (used by SSE json.dumps(dataclasses.asdict(ev)))
# ---------------------------------------------------------------------------

def test_event_asdict(fresh_bus):
    bus = fresh_bus
    ev = bus.push_bot_turn("Carol", "carol@x.com", "Test text", synthesize=False)
    d = dataclasses.asdict(ev)
    assert d["speaker"] == "bot"
    assert d["text"] == "Test text"
    assert "event_id" in d
    assert "seq" in d
    assert "has_audio" in d
    assert "timestamp" in d
