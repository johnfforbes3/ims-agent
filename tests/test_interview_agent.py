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
        turn = agent.process("50")     # percent — on track
        # Should jump straight to confirm/close, not ask for blocker
        assert agent.state in (
            InterviewState.CONFIRM, InterviewState.COMPLETE, InterviewState.TASK_INTRO
        )

    def test_behind_task_asks_for_blocker(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        turn = agent.process("30")     # behind — should ask for blocker
        assert agent.state == InterviewState.AWAITING_BLOCKER
        assert agent.state == InterviewState.AWAITING_BLOCKER

    def test_blocker_asks_risk_flag(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")            # pct — behind
        turn = agent.process("waiting on vendor parts")   # blocker
        assert agent.state == InterviewState.AWAITING_RISK_FLAG

    def test_risk_yes_asks_for_description(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")
        agent.process("vendor delay")
        turn = agent.process("yes")    # risk flag = yes
        assert agent.state == InterviewState.AWAITING_RISK_DESC

    def test_full_path_single_task_completes(self):
        task = _make_task("1", "Behind Task", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")
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
        agent.process("30")
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
        agent.process("30")
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

    def test_invalid_pct_triggers_retry(self):
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
            agent.process("50")        # all on track
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
        agent.process("50")
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
        agent.process("50")
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
        agent.process("50")
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
        agent.process("50")
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
        agent.process("yes")           # greeting response
        agent.process("30")            # pct — behind schedule
        agent.process("vendor delay")  # blocker
        agent.process("yes")           # risk flag
        agent.process("need 3 more weeks")  # risk description

        transcript = agent.transcript
        agents = [t for t in transcript if t.speaker == "agent"]
        cams = [t for t in transcript if t.speaker == "cam"]
        assert len(cams) == 5, f"Expected 5 CAM turns, got {len(cams)}"
        assert len(agents) >= 4, f"Expected ≥4 agent turns, got {len(agents)}"

    def test_transcript_records_cam_corrections(self):
        """CAM corrections in the CONFIRM state must appear in the transcript."""
        task = _make_task("T1", "Task", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")
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
        agent.process("30")
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
        agent.process("30")
        agent.process("waiting on GPU allocation")
        agent.process("no")   # no risk flag → confirm
        assert agent.state == InterviewState.CONFIRM

        # Force the correction extraction to fail (simulates LLM unavailable / parse error)
        with patch.object(agent, "_extract_and_apply_correction", return_value=False):
            turn = agent.process(
                "Actually, AI-07 is wrong — it should be at 45%, not 30%"
            )
        # When extraction fails, bot must close gracefully rather than crash or loop
        assert agent.state == InterviewState.COMPLETE
        assert turn.text  # must produce a response

    def test_correction_applied_stays_in_confirm(self):
        """When _extract_and_apply_correction succeeds (mocked), bot re-confirms."""
        from unittest.mock import patch
        task = _make_task("AI-07", "AI Platform", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"AI-07": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")
        agent.process("waiting on GPU allocation")
        agent.process("no")   # no risk flag
        assert agent.state == InterviewState.CONFIRM

        with patch.object(agent, "_extract_and_apply_correction", return_value=True):
            turn = agent.process("AI-07 should be risk-flagged, not AI-09")

        # Correction was applied → bot stays in CONFIRM to re-confirm
        assert agent.state == InterviewState.CONFIRM
        assert turn.text  # must produce a re-confirmation message

    def test_after_correction_affirmative_closes(self):
        """After correction is applied and re-confirmed, 'yes' closes properly."""
        from unittest.mock import patch
        task = _make_task("AI-07", "AI Platform", pct=30)
        agent = InterviewAgent("Alice", [task], expected_pcts={"AI-07": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")
        agent.process("waiting on GPU allocation")
        agent.process("no")
        assert agent.state == InterviewState.CONFIRM

        with patch.object(agent, "_extract_and_apply_correction", return_value=True):
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

    def test_flat_denial_retry_limit_still_works(self):
        """Plain 'no' without task ID or percent should still exhaust retries and close."""
        task = _make_task("T1", "Task", pct=50)
        agent = InterviewAgent("Alice", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")
        assert agent.state == InterviewState.CONFIRM

        agent.process("no")   # flat denial #1 → re-ask
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")   # flat denial #2 → re-ask
        assert agent.state == InterviewState.CONFIRM
        agent.process("no")   # flat denial #3 → cap reached, close
        assert agent.state == InterviewState.COMPLETE
