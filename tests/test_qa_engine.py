"""Tests for Phase 4 Q&A engine and context builder."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STATE = {
    "last_updated": "2026-04-26T10:56:33+00:00",
    "cycle_id": "20260426T104747Z",
    "schedule_health": "RED",
    "critical_path_task_ids": ["1", "3", "21", "22", "33"],
    "milestones": [
        {
            "task_id": "52",
            "milestone_name": "MS-02 PDR Complete",
            "baseline_date": "2026-05-29",
            "p50_date": "2026-05-30",
            "p80_date": "2026-06-01",
            "p95_date": "2026-06-02",
            "prob_on_baseline": 0.219,
            "risk_level": "HIGH",
        },
        {
            "task_id": "51",
            "milestone_name": "MS-01 SRR Complete",
            "baseline_date": "2026-02-13",
            "p50_date": "2026-02-13",
            "p80_date": "2026-02-14",
            "p95_date": "2026-02-15",
            "prob_on_baseline": 0.514,
            "risk_level": "MEDIUM",
        },
    ],
    "top_risks": "1. RF Specs Dependency\n2. Near-Zero SAT probability",
    "recommended_actions": "1. Get committed RF specs date by EOB today.\n2. Correct SE-01 data integrity.",
    "narrative": "The program is in critical condition. PDR probability is 22%.",
    "tasks_behind": [
        {
            "task_id": "3",
            "cam_name": "Alice Nguyen",
            "percent_complete": 60,
            "blocker": "RF specs from Hardware not received.",
        }
    ],
    "cam_response_status": {
        "Alice Nguyen": {"responded": True, "attempts": 1, "last_outcome": "completed"},
        "Bob Martinez": {"responded": True, "attempts": 1, "last_outcome": "completed"},
    },
    "completion_report": {"total": 5, "responded": 5, "threshold": 0.8, "threshold_met": True},
}

SAMPLE_HISTORY = [
    {"cycle_id": "20260419T060000Z", "timestamp": "2026-04-19T06:00:00Z",
     "schedule_health": "YELLOW", "cams_responded": 4, "cams_total": 5},
    {"cycle_id": "20260426T104747Z", "timestamp": "2026-04-26T10:56:33Z",
     "schedule_health": "RED", "cams_responded": 5, "cams_total": 5},
]


@pytest.fixture
def mock_state_files(tmp_path, monkeypatch):
    state_file = tmp_path / "dashboard_state.json"
    history_file = tmp_path / "cycle_history.json"
    state_file.write_text(json.dumps(SAMPLE_STATE), encoding="utf-8")
    history_file.write_text(json.dumps(SAMPLE_HISTORY), encoding="utf-8")
    # Patch module-level Path vars directly — avoids load_dotenv(override=True)
    # on reload fighting with monkeypatch.setenv.
    import agent.qa.context_builder as cb
    monkeypatch.setattr(cb, "_STATE_FILE", state_file)
    monkeypatch.setattr(cb, "_HISTORY_FILE", history_file)
    return state_file, history_file


# ---------------------------------------------------------------------------
# Intent detection tests
# ---------------------------------------------------------------------------

class TestDetectIntent:
    def test_critical_path_intent(self):
        from agent.qa.context_builder import detect_intent
        assert "critical_path" in detect_intent("What is the critical path?")

    def test_milestone_intent(self):
        from agent.qa.context_builder import detect_intent
        assert "milestone" in detect_intent("What is the probability of hitting PDR?")

    def test_risk_intent(self):
        from agent.qa.context_builder import detect_intent
        assert "risks" in detect_intent("What are the top risks right now?")

    def test_blocker_intent(self):
        from agent.qa.context_builder import detect_intent
        assert "blocker" in detect_intent("Why is SE-03 behind schedule?")

    def test_changes_intent(self):
        from agent.qa.context_builder import detect_intent
        assert "changes" in detect_intent("What changed since last cycle?")

    def test_actions_intent(self):
        from agent.qa.context_builder import detect_intent
        assert "actions" in detect_intent("What should I focus on this week?")

    def test_health_intent_default(self):
        from agent.qa.context_builder import detect_intent
        # Unrecognised question falls back to health
        intents = detect_intent("bananas")
        assert intents == ["health"]

    def test_multi_intent(self):
        from agent.qa.context_builder import detect_intent
        intents = detect_intent("What is the critical path and top risks?")
        assert "critical_path" in intents
        assert "risks" in intents


# ---------------------------------------------------------------------------
# Context builder tests
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_returns_no_data_when_state_missing(self, tmp_path, monkeypatch):
        import agent.qa.context_builder as cb
        monkeypatch.setattr(cb, "_STATE_FILE", tmp_path / "nonexistent.json")
        ctx = cb.build_context("anything")
        assert "No schedule data" in ctx

    def test_always_includes_health_header(self, mock_state_files):
        from agent.qa.context_builder import build_context
        ctx = build_context("What is the schedule health?")
        assert "RED" in ctx
        assert "20260426T104747Z" in ctx

    def test_critical_path_section_present(self, mock_state_files):
        from agent.qa.context_builder import build_context
        ctx = build_context("What is the critical path?")
        assert "CRITICAL PATH" in ctx
        assert "1" in ctx  # task ID on critical path

    def test_milestone_section_present(self, mock_state_files):
        from agent.qa.context_builder import build_context
        ctx = build_context("What is the probability of hitting PDR on time?")
        assert "MILESTONE" in ctx
        assert "21.9%" in ctx  # prob_on_baseline formatted

    def test_blocker_section_present(self, mock_state_files):
        from agent.qa.context_builder import build_context
        ctx = build_context("Why is SE-03 behind?")
        assert "RF specs" in ctx

    def test_changes_section_shows_history(self, mock_state_files):
        from agent.qa.context_builder import build_context
        ctx = build_context("What changed since last cycle?")
        assert "YELLOW" in ctx  # previous cycle health
        assert "RED" in ctx


# ---------------------------------------------------------------------------
# QAEngine tests
# ---------------------------------------------------------------------------

class TestQAEngine:
    def test_direct_health_answer(self, mock_state_files):
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask("What is the schedule health?")
        assert response.direct is True
        assert "RED" in response.answer
        assert response.source_cycle == "20260426T104747Z"

    def test_direct_top_risks(self, mock_state_files):
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask("What are the top risks right now?")
        assert response.direct is True
        assert "RF Specs Dependency" in response.answer  # from SAMPLE_STATE top_risks

    def test_direct_recommended_actions(self, mock_state_files):
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask("What should I focus on this week?")
        assert response.direct is True
        assert "RF specs date" in response.answer  # from SAMPLE_STATE recommended_actions

    def test_direct_critical_path(self, mock_state_files):
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask("What are the critical path tasks?")
        assert response.direct is True
        assert "5" in response.answer  # 5 CP tasks

    def test_llm_routed_question(self, mock_state_files):
        from agent.qa.qa_engine import QAEngine
        mock_answer = "SE-03 is blocked by missing RF specifications from Hardware."
        with patch("agent.llm_interface.LLMInterface.ask_with_tools", return_value=mock_answer):
            response = QAEngine().ask("Why is SE-03 behind schedule?")
        assert response.direct is False
        assert response.answer == mock_answer
        assert "blocker" in response.intent

    def test_no_state_returns_graceful_message(self, tmp_path, monkeypatch):
        import agent.qa.context_builder as cb
        monkeypatch.setattr(cb, "_STATE_FILE", tmp_path / "nope.json")
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask("What is the critical path?")
        assert "No schedule data" in response.answer
        assert response.source_cycle == ""

    def test_response_to_dict(self, mock_state_files):
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask("What is the schedule health?")
        d = response.to_dict()
        assert "answer" in d
        assert "source_cycle" in d
        assert "intent" in d
        assert "direct" in d


# ---------------------------------------------------------------------------
# Slack command handler tests (no Slack connection needed)
# ---------------------------------------------------------------------------

class TestSlackCommand:
    def test_start_skips_when_no_tokens(self, monkeypatch):
        import agent.slack_command as sc
        monkeypatch.setattr(sc, "_APP_TOKEN", "")
        monkeypatch.setattr(sc, "_BOT_TOKEN", "")
        thread = sc.start()
        assert thread is None

    def test_start_skips_when_slack_bolt_missing(self, monkeypatch):
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-fake")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        import importlib
        import agent.slack_command as sc
        importlib.reload(sc)
        with patch.dict("sys.modules", {"slack_bolt": None,
                                        "slack_bolt.adapter.socket_mode": None}):
            thread = sc.start()
        assert thread is None

    def test_handle_empty_question(self):
        from agent.slack_command import _handle_ims_command
        ack = MagicMock()
        respond = MagicMock()
        _handle_ims_command({"text": ""}, ack, respond)
        ack.assert_called_once()
        respond.assert_called_once()
        # respond called with text= keyword arg
        call_text = respond.call_args.kwargs.get("text", "")
        assert "Usage" in call_text

    def test_handle_too_long_question(self):
        from agent.slack_command import _handle_ims_command
        ack = MagicMock()
        respond = MagicMock()
        long_q = "x" * 500
        _handle_ims_command({"text": long_q}, ack, respond)
        ack.assert_called_once()
        call_text = respond.call_args[1].get("text", respond.call_args[0][0] if respond.call_args[0] else "")
        assert "long" in call_text.lower() or "max" in call_text.lower()

    def test_handle_valid_question(self, mock_state_files):
        from agent.slack_command import _handle_ims_command
        ack = MagicMock()
        respond = MagicMock()
        _handle_ims_command({"text": "What is the schedule health?"}, ack, respond)
        ack.assert_called_once()
        # respond called at least twice: once for "thinking", once for the answer
        assert respond.call_count >= 1
