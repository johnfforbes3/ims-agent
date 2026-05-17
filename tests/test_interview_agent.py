"""
Tests for agent.voice.interview_agent — conversation state machine.

Covers 2.4 checklist:
- State machine handles all expected conversation paths
- Numeric extraction from natural language
- Yes/no interpretation
- "I don't know" handling
- Timeout / retry logic
- Confirmation and closing flow
"""

from datetime import datetime, timedelta
import pytest
from agent.voice.interview_agent import (
    InterviewAgent, InterviewState, TaskResult,
    _extract_percent, _is_affirmative, _is_negative, _is_unknown,
)

BASE = datetime(2026, 1, 5, 8, 0, 0)


def _make_task(uid: str, name: str, pct: int = 50, behind: bool = False) -> dict:
    start = BASE
    finish = BASE + timedelta(days=20)
    if behind:
        # Task that started 18 days ago, should be ~90% done
        start = datetime.now() - timedelta(days=18)
        finish = datetime.now() + timedelta(days=2)
    return {
        "task_id": uid,
        "name": name,
        "start": start,
        "finish": finish,
        "percent_complete": pct,
        "predecessors": [],
        "cam": "Test CAM",
        "is_milestone": False,
        "duration_days": 20,
        "baseline_start": start,
        "baseline_finish": finish,
        "notes": "",
    }


def _make_agent(tasks: list[dict] | None = None) -> InterviewAgent:
    if tasks is None:
        tasks = [_make_task("1", "Design Task", pct=50)]
    return InterviewAgent("Alice Nguyen", tasks)


# ---------------------------------------------------------------------------
# NLU helpers
# ---------------------------------------------------------------------------

class TestExtractPercent:
    def test_plain_integer(self):
        assert _extract_percent("75") == 75

    def test_with_percent_sign(self):
        assert _extract_percent("75%") == 75

    def test_natural_language_about(self):
        assert _extract_percent("about 80 percent") == 80

    def test_word_half(self):
        assert _extract_percent("about half done") == 50

    def test_word_three_quarters(self):
        assert _extract_percent("three quarters done") == 75

    def test_zero(self):
        assert _extract_percent("zero percent") == 0

    def test_hundred(self):
        assert _extract_percent("hundred percent") == 100

    def test_invalid_returns_none(self):
        assert _extract_percent("I don't know") is None

    def test_out_of_range_rejected(self):
        # 150 is out of range
        assert _extract_percent("150") is None

    def test_i_would_say_60(self):
        assert _extract_percent("I'd say 60") == 60


class TestIsAffirmative:
    def test_yes(self):
        assert _is_affirmative("yes")

    def test_yeah(self):
        assert _is_affirmative("yeah sure")

    def test_that_is_right(self):
        assert _is_affirmative("that's right")

    def test_negative_not_affirmative(self):
        assert not _is_affirmative("no")


class TestIsNegative:
    def test_no(self):
        assert _is_negative("no")

    def test_nope(self):
        assert _is_negative("nope")

    def test_not_really(self):
        assert _is_negative("not really")

    def test_yes_not_negative(self):
        assert not _is_negative("yes")

    def test_know_not_negative(self):
        # "know" contains "no" as substring but not as whole word — should not match
        assert not _is_negative("i know the answer")


class TestIsUnknown:
    def test_i_dont_know(self):
        assert _is_unknown("i don't know")

    def test_not_sure(self):
        assert _is_unknown("not sure")

    def test_need_to_check(self):
        assert _is_unknown("i need to check on that")

    def test_a_number_is_not_unknown(self):
        assert not _is_unknown("75 percent")


# ---------------------------------------------------------------------------
# State machine — happy path
# ---------------------------------------------------------------------------

class TestStateMachineHappyPath:
    def test_greeting_starts_in_greeting_state(self):
        agent = _make_agent()
        turn = agent.start()
        assert agent.state == InterviewState.GREETING
        assert "Alice" in turn.text

    def test_greeting_yes_transitions_to_awaiting_pct(self):
        agent = _make_agent()
        agent.start()
        turn = agent.process("yeah, ready")
        assert agent.state == InterviewState.AWAITING_PCT

    def test_on_track_task_no_blocker_asked(self):
        # Task with pct == expected — no blocker prompt
        task = _make_task("1", "Easy Task", pct=50)
        # Force expected to also be 50 by providing it explicitly
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 50})
        agent.start()
        agent.process("yes")           # greeting
        agent.process("50")            # percent — on track → AWAITING_EAC_DATE
        assert agent.state == InterviewState.AWAITING_EAC_DATE
        turn = agent.process("still on track")  # EAC date → on track, no blocker
        # Should jump straight to confirm/close, not ask for blocker
        assert agent.state in (
            InterviewState.CONFIRM, InterviewState.COMPLETE, InterviewState.TASK_INTRO
        )

    def test_behind_task_asks_for_blocker(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")            # behind → AWAITING_EAC_DATE
        assert agent.state == InterviewState.AWAITING_EAC_DATE
        turn = agent.process("end of next month")  # EAC date → AWAITING_BLOCKER
        assert agent.state == InterviewState.AWAITING_BLOCKER

    def test_blocker_asks_risk_flag(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")            # pct — behind → AWAITING_EAC_DATE
        agent.process("end of month")  # EAC date → AWAITING_BLOCKER
        turn = agent.process("waiting on vendor parts")   # blocker
        assert agent.state == InterviewState.AWAITING_RISK_FLAG

    def test_risk_yes_asks_for_description(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")            # pct → AWAITING_EAC_DATE
        agent.process("mid next month") # EAC date → AWAITING_BLOCKER
        agent.process("vendor delay")
        turn = agent.process("yes")    # risk flag = yes
        assert agent.state == InterviewState.AWAITING_RISK_DESC

    def test_full_path_single_task_completes(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")                       # pct → AWAITING_EAC_DATE
        agent.process("end of next month")        # EAC date → AWAITING_BLOCKER
        agent.process("waiting on vendor")
        agent.process("yes")           # risk flag
        agent.process("vendor lead time extended 3 weeks")  # risk desc
        # After last task, should request confirmation
        assert agent.state in (InterviewState.CONFIRM, InterviewState.COMPLETE)

    def test_results_captured_after_complete_path(self):
        task = _make_task("1", "Test Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")                 # pct → AWAITING_EAC_DATE
        agent.process("mid june")           # EAC date → AWAITING_BLOCKER
        agent.process("license contention")
        agent.process("no")            # no risk flag
        if agent.state == InterviewState.CONFIRM:
            agent.process("yes")

        results = agent.results
        assert len(results) == 1
        r = results[0]
        assert r.percent_complete == 30
        assert "license" in r.blocker.lower()
        assert r.risk_flag is False
        assert r.status == "captured"

    def test_risk_captured_in_result(self):
        task = _make_task("1", "Test Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")                 # pct → AWAITING_EAC_DATE
        agent.process("end of next month")  # EAC date → AWAITING_BLOCKER
        agent.process("waiting on parts")
        agent.process("yes")           # risk
        agent.process("Supplier lead time extended")
        if agent.state == InterviewState.CONFIRM:
            agent.process("yes")
        results = agent.results
        assert results[0].risk_flag is True
        assert "Supplier" in results[0].risk_description


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_i_dont_know_flags_no_response(self):
        task = _make_task("1", "Task", pct=50)
        agent = InterviewAgent("Carol", [task], expected_pcts={"1": 50})
        agent.start()
        agent.process("yes")
        agent.process("I don't know, I need to check")
        results = agent.results
        assert len(results) == 1
        assert results[0].status == "no_response"

    def test_greeting_no_aborts(self):
        agent = _make_agent()
        agent.start()
        turn = agent.process("no, not right now")
        assert agent.state == InterviewState.ABORTED

    def test_greeting_no_problem_ready_proceeds(self):
        # "no problem, I'm ready" is affirmative — should NOT abort
        agent = _make_agent()
        agent.start()
        agent.process("no problem, I'm ready to start")
        assert agent.state != InterviewState.ABORTED

    def test_invalid_pct_triggers_retry(self, monkeypatch):
        # This test validates the interview-agent's retry logic when no percent
        # can be determined.  The LLM classifier is patched to return null so the
        # test is isolated from model behaviour (the LLM may infer ~50% from a
        # vague phrase if the task's expected_pct is also 50%).
        import agent.voice.interview_agent as ia
        def _null_classify(*args, **kwargs):
            return {
                "percent": None, "blocker_mentioned": False, "blocker_text": "",
                "sentiment": "unclear", "unknown": False,
                "key_insight": "", "cam_question": False,
            }
        monkeypatch.setattr(ia, "_classify_cam_response", _null_classify)

        task = _make_task("1", "Task", pct=50)
        agent = InterviewAgent("Carol", [task], expected_pcts={"1": 50})
        agent.start()
        agent.process("yes")
        # A phrase that is neither a known "I don't know" nor a parseable percent
        turn = agent.process("a reasonable amount of progress")
        # Should re-prompt, not advance
        assert agent.state == InterviewState.AWAITING_PCT

    def test_multiple_tasks_all_captured(self):
        tasks = [_make_task(str(i), f"Task {i}", pct=50) for i in range(1, 4)]
        agent = InterviewAgent("Alice", tasks, expected_pcts={str(i): 50 for i in range(1, 4)})
        agent.start()
        agent.process("yes")
        for i in range(1, 4):
            agent.process("50")               # pct → AWAITING_EAC_DATE (1-99%)
            agent.process("still on track")   # EAC date → finalise, next task
        # All three should be captured
        assert len(agent.results) == 3

    def test_transcript_records_all_turns(self):
        task = _make_task("1", "Task", pct=50)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")
        transcript = agent.transcript
        speakers = [t.speaker for t in transcript]
        assert "agent" in speakers
        assert "cam" in speakers

    def test_confirm_affirmative_closes(self):
        task = _make_task("T1", "Task One", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")                  # pct → AWAITING_EAC_DATE
        agent.process("still on track")      # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM
        agent.process("yes that's right")
        assert agent.state == InterviewState.COMPLETE

    def test_confirm_flat_denial_reasks_then_closes(self):
        # TD-004: flat denials (no percent, no task ID) should re-ask at most 2
        # times, then close — not loop forever
        task = _make_task("T1", "Task One", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")              # pct → AWAITING_EAC_DATE
        agent.process("on track")        # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")          # flat denial #1 → re-ask
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")          # flat denial #2 → re-ask
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")          # flat denial #3 → cap hit, close
        assert agent.state == InterviewState.COMPLETE

    def test_confirm_inline_correction_does_not_loop(self):
        # TD-004 (updated): if CAM provides an inline correction (percent or task ID),
        # the bot should either re-confirm after applying it (if LLM extraction works)
        # OR close gracefully (if LLM extraction fails) — it must NOT stay in a loop.
        task = _make_task("T1", "Task One", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")              # pct → AWAITING_EAC_DATE
        agent.process("on track")        # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM
        agent.process("No, T1 is 75%, not 50%")
        # LLM may succeed (→ CONFIRM for re-confirmation) or fail (→ COMPLETE gracefully)
        assert agent.state in (InterviewState.CONFIRM, InterviewState.COMPLETE)

    def test_confirm_no_problem_closes(self):
        # "no problem" is affirmative → should close, not re-ask
        task = _make_task("T1", "Task One", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")              # pct → AWAITING_EAC_DATE
        agent.process("on track")        # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM
        agent.process("no problem, looks good")
        assert agent.state == InterviewState.COMPLETE

    def test_task_result_to_cam_input_dict(self):
        r = TaskResult(
            task_id="5",
            cam_name="Alice",
            percent_complete=75,
            blocker="waiting on specs",
            risk_flag=True,
            risk_description="may affect PDR",
            status="captured",
        )
        d = r.to_cam_input_dict()
        assert d["task_id"] == "5"
        assert d["percent_complete"] == 75
        assert d["risk_flag"] is True
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# Conversational context — context retention, correction handling, transcript
# ---------------------------------------------------------------------------

class TestConversationalContext:
    """
    Verify that conversational context is retained and corrections are handled
    correctly.  LLM calls are not made in these tests (no API key in CI) so
    we rely on the graceful fallback paths.
    """

    def test_transcript_accumulates_through_all_states(self):
        """Every agent + CAM turn should be recorded in the transcript."""
        task = _make_task("T1", "Behind Task", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 80})
        agent.start()
        agent.process("yes")              # greeting response
        agent.process("30")              # pct — behind → AWAITING_EAC_DATE
        agent.process("end of next month")  # EAC date → AWAITING_BLOCKER
        agent.process("vendor delay")    # blocker
        agent.process("yes")             # risk flag
        agent.process("need 3 more weeks")  # risk description

        transcript = agent.transcript
        agents = [t for t in transcript if t.speaker == "agent"]
        cams = [t for t in transcript if t.speaker == "cam"]
        assert len(cams) == 6, f"Expected 6 CAM turns, got {len(cams)}"
        assert len(agents) >= 5, f"Expected ≥5 agent turns, got {len(agents)}"

    def test_transcript_records_cam_corrections(self):
        """CAM corrections in the CONFIRM state must appear in the transcript."""
        task = _make_task("T1", "Task", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")              # pct → AWAITING_EAC_DATE
        agent.process("on track")        # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM

        pre_count = len(agent.transcript)
        agent.process("No, T1 is actually 60%, not 50%")

        post_count = len(agent.transcript)
        cam_turns = [t for t in agent.transcript if t.speaker == "cam"]
        # At minimum the correction utterance and agent reply were added
        assert post_count > pre_count
        assert any("60" in t.text or "50" in t.text for t in cam_turns)

    def test_last_confirmation_text_saved(self):
        """_last_confirmation_text should be set when request_confirmation runs."""
        task = _make_task("T1", "Behind Task", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")              # pct → AWAITING_EAC_DATE
        agent.process("end of june")     # EAC date → AWAITING_BLOCKER
        agent.process("vendor delay")
        agent.process("no")   # no risk flag — will jump to confirm

        assert agent.state == InterviewState.CONFIRM
        assert hasattr(agent, "_last_confirmation_text")
        assert len(agent._last_confirmation_text) > 10
        assert "sound right" in agent._last_confirmation_text.lower()

    def test_correction_with_failed_llm_closes_gracefully(self):
        """When LLM correction extraction fails (mocked to return False), bot closes gracefully."""
        from unittest.mock import patch
        task = _make_task("AI-07", "AI Platform", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"AI-07": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")                    # pct → AWAITING_EAC_DATE
        agent.process("end of next month")     # EAC date → AWAITING_BLOCKER
        agent.process("waiting on GPU allocation")
        agent.process("no")   # no risk flag → confirm
        assert agent.state == InterviewState.CONFIRM

        # Force the correction extraction to fail (simulates LLM unavailable / parse error)
        with patch.object(agent, "_extract_and_apply_correction", return_value=[]):
            turn = agent.process(
                "Actually, AI-07 is wrong — it should be at 45%, not 30%"
            )
        # When extraction fails, bot must close gracefully rather than crash or loop
        assert agent.state == InterviewState.COMPLETE
        assert turn.text  # must produce a response

    def test_correction_applied_stays_in_confirm(self, monkeypatch):
        """When _extract_and_apply_correction succeeds (mocked), bot re-confirms.

        Phase 15.x fix: deterministic mock of _classify_cam_response and
        _classify_eac_date (same pattern as TD-042's test_flat_denial fix).
        Without these mocks the test depends on the live Anthropic API
        being reachable AND in-credit, which makes it flaky / blocked when
        credit is exhausted.  The mocks reproduce the LLM's expected
        classifications without hitting the network.
        """
        from unittest.mock import patch
        import agent.voice.interview_agent as ia

        def _classify(state, question, response, *args, **kwargs):
            import re as _re
            r = (response or "").strip().lower()
            if r == "yes" or "that's right" in r or "thats right" in r:
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "affirmative", "unknown": False, "key_insight": "", "cam_question": False}
            if r == "no":
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "negative", "unknown": False, "key_insight": "", "cam_question": False}
            if r.isdigit():
                return {"percent": int(r), "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "affirmative", "unknown": False, "key_insight": "", "cam_question": False}
            # Task-ID correction patterns ("AI-07 should be …", "not AI-09")
            if _re.search(r"\b[a-z]{2,4}-\d{2}\b", r) and ("should be" in r or "not " in r or "actually" in r):
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "negative", "unknown": False, "key_insight": response, "cam_question": False}
            if "waiting" in r or "blocked" in r or "blocker" in r:
                return {"percent": None, "blocker_mentioned": True, "blocker_text": response,
                        "sentiment": "unclear", "unknown": False, "key_insight": "", "cam_question": False}
            return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                    "sentiment": "unclear", "unknown": False, "key_insight": "", "cam_question": False}

        monkeypatch.setattr(ia, "_classify_cam_response", _classify)
        monkeypatch.setattr(ia, "_classify_eac_date",
                            lambda *a, **kw: {"intent": "on_track", "uncertain": False})

        task = _make_task("AI-07", "AI Platform", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"AI-07": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")                    # pct → AWAITING_EAC_DATE
        agent.process("end of next month")     # EAC date → AWAITING_BLOCKER
        agent.process("waiting on GPU allocation")
        agent.process("no")   # no risk flag
        assert agent.state == InterviewState.CONFIRM

        with patch.object(agent, "_extract_and_apply_correction",
                          return_value=[{"task_id": "AI-07", "field": "risk_flag"}]):
            turn = agent.process("AI-07 should be risk-flagged, not AI-09")

        # Correction was applied → bot stays in CONFIRM to re-confirm
        assert agent.state == InterviewState.CONFIRM
        assert turn.text  # must produce a re-confirmation message

    def test_after_correction_affirmative_closes(self, monkeypatch):
        """After correction is applied and re-confirmed, 'yes' closes properly.

        Phase 15.x fix: same deterministic LLM mock as
        test_correction_applied_stays_in_confirm above.
        """
        from unittest.mock import patch
        import agent.voice.interview_agent as ia

        def _classify(state, question, response, *args, **kwargs):
            import re as _re
            r = (response or "").strip().lower()
            if r == "yes" or "that's right" in r or "thats right" in r:
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "affirmative", "unknown": False, "key_insight": "", "cam_question": False}
            if r == "no":
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "negative", "unknown": False, "key_insight": "", "cam_question": False}
            if r.isdigit():
                return {"percent": int(r), "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "affirmative", "unknown": False, "key_insight": "", "cam_question": False}
            # Task-ID correction patterns ("AI-07 should be …", "not AI-09")
            if _re.search(r"\b[a-z]{2,4}-\d{2}\b", r) and ("should be" in r or "not " in r or "actually" in r):
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "negative", "unknown": False, "key_insight": response, "cam_question": False}
            if "waiting" in r or "blocked" in r or "blocker" in r:
                return {"percent": None, "blocker_mentioned": True, "blocker_text": response,
                        "sentiment": "unclear", "unknown": False, "key_insight": "", "cam_question": False}
            return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                    "sentiment": "unclear", "unknown": False, "key_insight": "", "cam_question": False}

        monkeypatch.setattr(ia, "_classify_cam_response", _classify)
        monkeypatch.setattr(ia, "_classify_eac_date",
                            lambda *a, **kw: {"intent": "on_track", "uncertain": False})

        task = _make_task("AI-07", "AI Platform", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"AI-07": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")                    # pct → AWAITING_EAC_DATE
        agent.process("end of next month")     # EAC date → AWAITING_BLOCKER
        agent.process("waiting on GPU allocation")
        agent.process("no")
        assert agent.state == InterviewState.CONFIRM

        with patch.object(agent, "_extract_and_apply_correction",
                          return_value=[{"task_id": "AI-07", "field": "risk_flag"}]):
            agent.process("AI-07 should be risk-flagged, not AI-09")

        assert agent.state == InterviewState.CONFIRM
        # Now CAM confirms the re-confirmation
        agent.process("yes, that's right")
        assert agent.state == InterviewState.COMPLETE

    def test_re_request_confirmation_produces_message(self):
        """_re_request_confirmation must return an AgentTurn with non-empty text."""
        task = _make_task("AI-07", "AI Platform", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"AI-07": 80})
        # Manually add a risk-flagged result to see it reflected
        from agent.voice.interview_agent import TaskResult
        agent._results = [TaskResult(
            task_id="AI-07",
            cam_name="Alice",
            percent_complete=30,
            blocker="GPU allocation",
            risk_flag=True,
            risk_description="delays PDR",
            status="captured",
        )]
        agent._state = InterviewState.CONFIRM
        turn = agent._re_request_confirmation()

        assert turn.text
        assert agent.state == InterviewState.CONFIRM
        # Should mention the risk-flagged task ID or ask for confirmation
        assert any(kw in turn.text.lower() for kw in ["ai-07", "right", "risk", "flagged"])

    def test_format_transcript_for_llm(self):
        """_format_transcript_for_llm should format recent turns correctly."""
        from agent.voice.interview_agent import _format_transcript_for_llm, ConversationTurn
        turns = [
            ConversationTurn(speaker="agent", text="Hey Alice, quick check-in."),
            ConversationTurn(speaker="cam", text="Hi, ready to go."),
            ConversationTurn(speaker="agent", text="What's the pct on Task A?"),
            ConversationTurn(speaker="cam", text="About 60%."),
        ]
        result = _format_transcript_for_llm(turns, max_turns=4)
        assert "ATLAS:" in result
        assert "CAM:" in result
        assert "Hey Alice" in result
        assert "60%" in result

    def test_format_transcript_for_llm_empty(self):
        """_format_transcript_for_llm handles empty transcript gracefully."""
        from agent.voice.interview_agent import _format_transcript_for_llm
        result = _format_transcript_for_llm([], max_turns=10)
        assert "(no prior conversation)" in result

    def test_format_transcript_for_llm_truncates(self):
        """_format_transcript_for_llm should only include the last max_turns turns."""
        from agent.voice.interview_agent import _format_transcript_for_llm, ConversationTurn
        turns = [ConversationTurn(speaker="cam", text=f"Turn {i}") for i in range(20)]
        result = _format_transcript_for_llm(turns, max_turns=5)
        assert "Turn 15" in result   # last 5
        assert "Turn 0" not in result  # first 15 truncated

    def test_format_task_results(self):
        """_format_task_results should include task IDs, pct, and risk status."""
        from agent.voice.interview_agent import _format_task_results, TaskResult
        results = [
            TaskResult("AI-07", "Alice", 30, "GPU blocker", True, "PDR at risk", "captured"),
            TaskResult("AI-09", "Alice", 80, "", False, "", "captured"),
        ]
        tasks = [
            _make_task("AI-07", "AI-07 AI Platform"),
            _make_task("AI-09", "AI-09 Model Training"),
        ]
        out = _format_task_results(results, tasks)
        assert "AI-07" in out
        assert "RISK FLAGGED" in out
        assert "AI-09" in out
        assert "no risk" in out

    def test_flat_denial_retry_limit_still_works(self, monkeypatch):
        """Plain 'no' without task ID or percent should still exhaust retries and close.

        TD-042 RESOLUTION (2026-05-08): mock the LLM classifier to make this test
        fully deterministic. Previously this test made live ANTHROPIC API calls
        that were sporadically slow / rate-limited / non-deterministic in the
        full 1010-test suite, causing flaky failures despite passing in
        isolation. Mocking gives identical behaviour to the regex fallback
        (which is also what would happen if the API key were missing) but with
        zero variance and zero cost.
        """
        import agent.voice.interview_agent as ia

        def _deterministic_classify(state, question, response, *args, **kwargs):
            """Return classifier output the LLM would produce for these exact inputs."""
            r = (response or "").strip().lower()
            if r == "yes":
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "affirmative", "unknown": False, "key_insight": "", "cam_question": False}
            if r == "no":
                return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "negative", "unknown": False, "key_insight": "", "cam_question": False}
            if r.isdigit():
                return {"percent": int(r), "blocker_mentioned": False, "blocker_text": "",
                        "sentiment": "affirmative", "unknown": False, "key_insight": "", "cam_question": False}
            # "on track", anything else → benign default
            return {"percent": None, "blocker_mentioned": False, "blocker_text": "",
                    "sentiment": "unclear", "unknown": False, "key_insight": "", "cam_question": False}

        monkeypatch.setattr(ia, "_classify_cam_response", _deterministic_classify)
        # The EAC-date classifier is also LLM-backed; force its "on track" → no_change path.
        monkeypatch.setattr(ia, "_classify_eac_date",
                            lambda *a, **kw: {"intent": "on_track", "uncertain": False})

        task = _make_task("T1", "Task", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")              # pct → AWAITING_EAC_DATE
        agent.process("on track")        # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM

        agent.process("no")   # flat denial #1 → re-ask
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")   # flat denial #2 → re-ask
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")   # flat denial #3 → cap reached, close
        assert agent.state == InterviewState.COMPLETE

    def test_milestone_no_count_skips_repeated_risk_question(self):
        """After 2 NO answers for the same milestone, the risk question is suppressed
        for subsequent tasks — avoids asking the same question 5+ times."""
        from unittest.mock import patch

        # Three tasks, all behind schedule, all with the same nearest milestone
        tasks = [
            _make_task("T1", "Task One", pct=0, behind=True),
            _make_task("T2", "Task Two", pct=0, behind=True),
            _make_task("T3", "Task Three", pct=0, behind=True),
        ]
        agent = InterviewAgent("Alice", tasks, expected_pcts={"T1": 90, "T2": 90, "T3": 90})

        # Patch _nearest_milestone_name to always return "Milestone A"
        with patch.object(agent, "_nearest_milestone_name", return_value="Milestone A"):
            agent.start()
            agent.process("yes")           # greeting

            # Task 1: behind, no blocker explicitly given → fast-path captures
            agent.process("0")             # pct → behind, asks for blocker
            agent.process("blocked on vendor")  # blocker → risk question asked
            assert agent.state == InterviewState.AWAITING_RISK_FLAG
            agent.process("no")            # NO #1 → no_count=1

            # Task 2: behind → blocker → risk question still asked (count=1 < 2)
            agent.process("0")
            agent.process("waiting on parts")
            assert agent.state == InterviewState.AWAITING_RISK_FLAG
            agent.process("no")            # NO #2 → no_count=2

            # Task 3: behind → blocker → risk question SKIPPED (count >= 2)
            # State should advance directly to TASK_INTRO or CONFIRM, not AWAITING_RISK_FLAG
            agent.process("0")
            agent.process("waiting on approval")
            assert agent.state != InterviewState.AWAITING_RISK_FLAG, (
                "risk question should be suppressed after 2 NO answers for the same milestone"
            )
            # Risk flag should be auto-set to False
            assert agent._results[2].risk_flag is False


def test_nearest_milestone_uses_task_finish_date():
    """_nearest_milestone_name must return the nearest milestone AT OR AFTER
    the current task's finish date, not just the globally-nearest milestone.

    Prevents the logically wrong question "Could this put Milestone X at risk?"
    when the task is actually scheduled to complete AFTER Milestone X.
    """
    # Task finishes 2026-06-10.  Network and Security Hardened = 2026-06-03.
    # System Accepted = 2026-06-25.  Correct answer: System Accepted.
    late_task = {
        "task_id": "DOC-01",
        "name": "Write system administration runbook",
        "percent_complete": 15,
        "cam": "David Lee",
        "start": datetime(2026, 6, 5),
        "finish": datetime(2026, 6, 10),
        "is_milestone": False,
    }
    agent = InterviewAgent("David Lee", [late_task], expected_pcts={"DOC-01": 100})
    agent._milestones = [
        {"name": "MILESTONE: AI Stack Deployed",          "finish": datetime(2026, 4, 28)},
        {"name": "MILESTONE: Network and Security Hardened", "finish": datetime(2026, 6, 3)},
        {"name": "MILESTONE: System Accepted",             "finish": datetime(2026, 6, 25)},
    ]
    result = agent._nearest_milestone_name()
    assert result == "System Accepted", (
        f"Expected 'System Accepted' for a task finishing 2026-06-10, got {result!r}. "
        "The bot should not ask about 'Network and Security Hardened' (2026-06-03) "
        "for a task that completes AFTER that milestone."
    )
