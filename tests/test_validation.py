"""Tests for agent.validation — ScheduleValidator."""

import pytest
from agent.validation import ScheduleValidator, ValidationResult


def _task(task_id: str, pct: int, cam: str = "Alice", milestone: bool = False) -> dict:
    return {
        "task_id": task_id,
        "name": f"Task {task_id}",
        "percent_complete": pct,
        "cam": cam,
        "is_milestone": milestone,
    }


def _input(task_id: str, pct: int | None, cam: str = "Alice") -> dict:
    return {
        "task_id": task_id,
        "cam_name": cam,
        "percent_complete": pct,
        "blocker": "",
        "risk_flag": False,
        "risk_description": "",
        "status": "captured" if pct is not None else "no_response",
    }


class TestBackwardsMovement:
    def test_decrease_is_a_failure(self):
        current = [_task("T1", 50)]
        inputs = [_input("T1", 40)]
        result = ScheduleValidator().validate(inputs, current)
        assert not result.passed
        assert any(f.rule == "backwards_movement" for f in result.failures)

    def test_same_pct_is_ok(self):
        current = [_task("T1", 50)]
        inputs = [_input("T1", 50)]
        result = ScheduleValidator().validate(inputs, current)
        assert result.passed

    def test_increase_is_ok(self):
        current = [_task("T1", 50)]
        inputs = [_input("T1", 70)]
        result = ScheduleValidator().validate(inputs, current)
        assert result.passed


class TestLargeJump:
    def test_jump_over_threshold_is_warning(self):
        current = [_task("T1", 10)]
        inputs = [_input("T1", 65)]  # 55 point jump
        result = ScheduleValidator().validate(inputs, current)
        assert result.passed  # warning, not failure
        assert any(w.rule == "large_jump" for w in result.warnings)

    def test_jump_at_threshold_is_ok(self):
        current = [_task("T1", 10)]
        inputs = [_input("T1", 60)]  # exactly 50 — not over threshold
        result = ScheduleValidator().validate(inputs, current)
        assert not any(w.rule == "large_jump" for w in result.warnings)


class TestCoverageCheck:
    def test_missing_response_is_warning(self):
        current = [_task("T1", 50), _task("T2", 30)]
        inputs = [_input("T1", 55)]  # T2 not responded
        result = ScheduleValidator().validate(inputs, current)
        assert result.passed  # warning only
        assert any(w.rule == "missing_response" and w.task_id == "T2" for w in result.warnings)

    def test_no_response_input_not_a_failure(self):
        current = [_task("T1", 50)]
        inputs = [_input("T1", None)]  # no_response — no pct
        result = ScheduleValidator().validate(inputs, current)
        assert result.passed
        assert not any(f.rule == "backwards_movement" for f in result.failures)

    def test_milestones_excluded_from_coverage(self):
        current = [_task("M1", 0, milestone=True), _task("T1", 50)]
        inputs = [_input("T1", 55)]
        result = ScheduleValidator().validate(inputs, current)
        # M1 is a milestone — should not appear in missing_response warnings
        assert not any(w.task_id == "M1" for w in result.warnings)


class TestUnknownTask:
    def test_unknown_task_id_is_warning(self):
        current = [_task("T1", 50)]
        inputs = [_input("T999", 60)]  # not in schedule
        result = ScheduleValidator().validate(inputs, current)
        assert result.passed
        assert any(w.rule == "unknown_task" for w in result.warnings)


class TestToDict:
    def test_to_dict_structure(self):
        current = [_task("T1", 80)]
        inputs = [_input("T1", 60)]  # backwards
        result = ScheduleValidator().validate(inputs, current)
        d = result.to_dict()
        assert "passed" in d
        assert "failures" in d
        assert "warnings" in d
        assert d["passed"] is False
        assert d["failures"][0]["rule"] == "backwards_movement"
