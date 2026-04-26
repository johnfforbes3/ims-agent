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
        assert "Alice Nguyen" in turn.text

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
        assert "block" in turn.text.lower() or "behind" in turn.text.lower()

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
