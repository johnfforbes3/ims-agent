"""
Tests for agent/dcma_assessment.py — DCMA 14-Point Assessment.

Phase 9.3: DCMA 14-Point Assessment Engine
"""

from datetime import datetime, timezone, timedelta
import pytest
from agent.dcma_assessment import (
    run_assessment,
    _check_01_logic,
    _check_02_leads,
    _check_03_lags,
    _check_04_relationship_types,
    _check_05_hard_constraints,
    _check_06_high_float,
    _check_07_negative_float,
    _check_08_high_duration,
    _check_09_invalid_dates,
    _check_10_resources,
    _check_11_missed_milestones,
    _check_12_critical_path_integrity,
    _check_13_bei,
    _check_14_summary_tasks,
    _score_health,
    _TENTHS_PER_DAY,
)

REF_DATE = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
PAST = REF_DATE - timedelta(days=20)
FUTURE = REF_DATE + timedelta(days=20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _work_task(
    task_id="1",
    name="Task A",
    cam="Alice",
    duration_days=5.0,
    percent_complete=50,
    start=None,
    finish=None,
    baseline_finish=None,
    predecessor_links=None,
    predecessors=None,
    has_hard_constraint=False,
    constraint_type=0,
    total_float_days=None,
):
    if start is None:
        start = REF_DATE - timedelta(days=5)
    if finish is None:
        finish = REF_DATE + timedelta(days=5)
    if baseline_finish is None:
        baseline_finish = FUTURE
    return {
        "task_id": task_id,
        "name": name,
        "cam": cam,
        "duration_days": duration_days,
        "percent_complete": percent_complete,
        "start": start,
        "finish": finish,
        "baseline_start": start,
        "baseline_finish": baseline_finish,
        "predecessor_links": predecessor_links or [],
        "predecessors": predecessors or [],
        "has_hard_constraint": has_hard_constraint,
        "constraint_type": constraint_type,
        "total_float_days": total_float_days,
        "is_milestone": False,
    }


def _milestone(
    task_id="M1",
    name="Milestone A",
    baseline_finish=None,
    percent_complete=0,
):
    if baseline_finish is None:
        baseline_finish = FUTURE
    return {
        "task_id": task_id,
        "name": name,
        "cam": "Alice",
        "duration_days": 0.0,
        "percent_complete": percent_complete,
        "start": REF_DATE,
        "finish": REF_DATE,
        "baseline_start": REF_DATE,
        "baseline_finish": baseline_finish,
        "predecessor_links": [],
        "predecessors": [],
        "has_hard_constraint": False,
        "constraint_type": 0,
        "total_float_days": 0.0,
        "is_milestone": True,
    }


# ---------------------------------------------------------------------------
# run_assessment — top level
# ---------------------------------------------------------------------------


class TestRunAssessment:
    def test_returns_14_checks(self):
        result = run_assessment([], reference_date=REF_DATE)
        assert result["total_checks"] == 14
        assert len(result["checks"]) == 14

    def test_check_ids_1_through_14(self):
        result = run_assessment([], reference_date=REF_DATE)
        ids = [c["check_id"] for c in result["checks"]]
        assert ids == list(range(1, 15))

    def test_score_present(self):
        result = run_assessment([], reference_date=REF_DATE)
        assert "score" in result
        assert "score_pct" in result
        assert "health" in result

    def test_clean_schedule_passes_most_checks(self):
        """A well-structured schedule with logic links should score well."""
        t1 = _work_task("1", predecessors=[], predecessor_links=[])
        t2 = _work_task("2",
                         predecessors=["1"],
                         predecessor_links=[{"predecessor_uid": "1", "type": 1, "lag_tenths_min": 0}])
        result = run_assessment([t1, t2], reference_date=REF_DATE)
        # Should pass most checks
        assert result["score"] >= 8

    def test_health_label_in_result(self):
        result = run_assessment([], reference_date=REF_DATE)
        assert result["health"] in ("GREEN", "YELLOW", "RED")

    def test_computed_at_present(self):
        result = run_assessment([], reference_date=REF_DATE)
        assert "computed_at" in result


# ---------------------------------------------------------------------------
# Check 1 — Logic
# ---------------------------------------------------------------------------


class TestCheck01Logic:
    def test_task_with_both_pred_and_succ_passes(self):
        t1 = _work_task("1")
        t2 = _work_task("2", predecessors=["1"])
        result = _check_01_logic([t1, t2], [], [t1, t2])
        assert result["passed"]

    def test_orphan_task_flagged(self):
        t1 = _work_task("1")  # no pred, no succ (only task)
        result = _check_01_logic([t1], [], [t1])
        # Single task with no pred or succ — 100% violation rate → fail
        assert not result["passed"]

    def test_check_id_is_1(self):
        result = _check_01_logic([], [], [])
        assert result["check_id"] == 1


# ---------------------------------------------------------------------------
# Check 2 — Leads
# ---------------------------------------------------------------------------


class TestCheck02Leads:
    def test_no_leads_passes(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 1, "lag_tenths_min": 0}])
        result = _check_02_leads([t])
        assert result["passed"]

    def test_negative_lag_fails(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 1, "lag_tenths_min": -480}])
        result = _check_02_leads([t])
        assert not result["passed"]
        assert result["violations"] == 1

    def test_positive_lag_not_flagged_as_lead(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 1, "lag_tenths_min": 4800}])
        result = _check_02_leads([t])
        assert result["passed"]

    def test_empty_tasks_passes(self):
        assert _check_02_leads([])["passed"]


# ---------------------------------------------------------------------------
# Check 3 — Lags
# ---------------------------------------------------------------------------


class TestCheck03Lags:
    def test_no_lags_passes(self):
        t = _work_task(predecessor_links=[])
        assert _check_03_lags([t])["passed"]

    def test_small_lag_passes(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 1, "lag_tenths_min": 480}])  # 0.1 days
        assert _check_03_lags([t])["passed"]

    def test_large_lag_fails_if_above_pct_threshold(self):
        # 6 days lag > default 5-day threshold; need > 5% of tasks to fail
        big_lag = int(6 * _TENTHS_PER_DAY + 1)
        tasks = [
            _work_task(str(i),
                        predecessor_links=[{"predecessor_uid": "0", "type": 1, "lag_tenths_min": big_lag}])
            for i in range(10)
        ] + [
            _work_task(str(i + 100), predecessor_links=[])
            for i in range(10)  # clean tasks
        ]
        # 10/20 = 50% have large lag → should fail
        result = _check_03_lags(tasks)
        assert not result["passed"]


# ---------------------------------------------------------------------------
# Check 4 — Relationship Types
# ---------------------------------------------------------------------------


class TestCheck04RelationshipTypes:
    def test_fs_link_passes(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 1, "lag_tenths_min": 0}])
        assert _check_04_relationship_types([t])["passed"]

    def test_sf_link_fails(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 2, "lag_tenths_min": 0}])
        assert not _check_04_relationship_types([t])["passed"]

    def test_ss_link_passes(self):
        t = _work_task(predecessor_links=[{"predecessor_uid": "0", "type": 3, "lag_tenths_min": 0}])
        assert _check_04_relationship_types([t])["passed"]  # SS is acceptable


# ---------------------------------------------------------------------------
# Check 5 — Hard Constraints
# ---------------------------------------------------------------------------


class TestCheck05HardConstraints:
    def test_no_hard_constraint_passes(self):
        t = _work_task(has_hard_constraint=False)
        assert _check_05_hard_constraints([t])["passed"]

    def test_hard_constraint_fails_above_threshold(self):
        tasks = [_work_task(str(i), has_hard_constraint=True) for i in range(10)]
        assert not _check_05_hard_constraints(tasks)["passed"]

    def test_single_constrained_in_many_passes(self):
        constrained = [_work_task("1", has_hard_constraint=True)]
        clean = [_work_task(str(i)) for i in range(100)]
        result = _check_05_hard_constraints(constrained + clean)
        assert result["passed"]  # 1/101 ≈ 1% < 5% threshold


# ---------------------------------------------------------------------------
# Check 6 — High Float
# ---------------------------------------------------------------------------


class TestCheck06HighFloat:
    def test_normal_float_passes(self):
        t = _work_task(total_float_days=10.0)
        assert _check_06_high_float([t])["passed"]

    def test_high_float_fails(self):
        tasks = [_work_task(str(i), total_float_days=50.0) for i in range(10)]
        assert not _check_06_high_float(tasks)["passed"]

    def test_no_float_data_skipped(self):
        t = _work_task(total_float_days=None)
        assert _check_06_high_float([t])["passed"]  # no data → vacuously passes


# ---------------------------------------------------------------------------
# Check 7 — Negative Float
# ---------------------------------------------------------------------------


class TestCheck07NegativeFloat:
    def test_zero_float_passes(self):
        t = _work_task(total_float_days=0.0)
        assert _check_07_negative_float([t])["passed"]

    def test_negative_float_fails(self):
        t = _work_task(total_float_days=-2.0)
        assert not _check_07_negative_float([t])["passed"]
        assert _check_07_negative_float([t])["violations"] == 1


# ---------------------------------------------------------------------------
# Check 8 — High Duration
# ---------------------------------------------------------------------------


class TestCheck08HighDuration:
    def test_short_task_passes(self):
        t = _work_task(duration_days=5.0)
        assert _check_08_high_duration([t])["passed"]

    def test_long_task_fails_above_pct(self):
        tasks = [_work_task(str(i), duration_days=50.0) for i in range(10)]
        assert not _check_08_high_duration(tasks)["passed"]


# ---------------------------------------------------------------------------
# Check 9 — Invalid Dates
# ---------------------------------------------------------------------------


class TestCheck09InvalidDates:
    def test_in_progress_task_passes(self):
        t = _work_task(percent_complete=50, finish=FUTURE)
        assert _check_09_invalid_dates([t], REF_DATE)["passed"]

    def test_complete_with_future_finish_flagged(self):
        t = _work_task(percent_complete=100, finish=FUTURE)
        assert not _check_09_invalid_dates([t], REF_DATE)["passed"]

    def test_zero_pct_past_finish_flagged(self):
        very_old_finish = REF_DATE - timedelta(days=60)
        t = _work_task(percent_complete=0, finish=very_old_finish)
        assert not _check_09_invalid_dates([t], REF_DATE)["passed"]

    def test_milestone_excluded(self):
        m = _milestone(percent_complete=100, baseline_finish=PAST)
        # Even though milestone is 100% with past finish, check 9 skips milestones
        result = _check_09_invalid_dates([m], REF_DATE)
        assert result["passed"]


# ---------------------------------------------------------------------------
# Check 10 — Resources
# ---------------------------------------------------------------------------


class TestCheck10Resources:
    def test_assigned_task_passes(self):
        t = _work_task(cam="Alice")
        assert _check_10_resources([t])["passed"]

    def test_unassigned_task_flagged(self):
        tasks = [_work_task(str(i), cam="Unassigned") for i in range(10)]
        assert not _check_10_resources(tasks)["passed"]

    def test_empty_cam_flagged(self):
        t = _work_task(cam="")
        tasks = [t] + [_work_task(str(i)) for i in range(30)]
        # 1/31 ≈ 3% — under 5% threshold → pass
        result = _check_10_resources(tasks)
        assert result["passed"]


# ---------------------------------------------------------------------------
# Check 11 — Missed Milestones
# ---------------------------------------------------------------------------


class TestCheck11MissedMilestones:
    def test_future_milestone_passes(self):
        m = _milestone(baseline_finish=FUTURE, percent_complete=0)
        assert _check_11_missed_milestones([m], REF_DATE)["passed"]

    def test_past_milestone_zero_pct_flagged(self):
        m = _milestone(baseline_finish=PAST, percent_complete=0)
        assert not _check_11_missed_milestones([m], REF_DATE)["passed"]

    def test_past_milestone_complete_passes(self):
        m = _milestone(baseline_finish=PAST, percent_complete=100)
        assert _check_11_missed_milestones([m], REF_DATE)["passed"]


# ---------------------------------------------------------------------------
# Check 12 — Critical Path Integrity
# ---------------------------------------------------------------------------


class TestCheck12CriticalPath:
    def test_no_cp_result_fails(self):
        result = _check_12_critical_path_integrity([], None)
        assert not result["passed"]

    def test_empty_critical_path_fails(self):
        tasks = [_work_task(str(i)) for i in range(10)]
        cp = {"critical_path": []}
        assert not _check_12_critical_path_integrity(tasks, cp)["passed"]

    def test_reasonable_critical_path_passes(self):
        tasks = [_work_task(str(i)) for i in range(20)]
        cp = {"critical_path": [str(i) for i in range(5)]}  # 25% of tasks
        assert _check_12_critical_path_integrity(tasks, cp)["passed"]

    def test_all_tasks_on_critical_path_fails(self):
        tasks = [_work_task(str(i)) for i in range(10)]
        cp = {"critical_path": [str(i) for i in range(10)]}  # 100% → fails
        assert not _check_12_critical_path_integrity(tasks, cp)["passed"]


# ---------------------------------------------------------------------------
# Check 13 — BEI
# ---------------------------------------------------------------------------


class TestCheck13Bei:
    def test_all_started_passes(self):
        tasks = [_work_task(str(i), percent_complete=50) for i in range(5)]
        assert _check_13_bei(tasks, REF_DATE)["passed"]

    def test_poor_bei_fails(self):
        tasks = [_work_task(str(i), percent_complete=0) for i in range(5)]
        result = _check_13_bei(tasks, REF_DATE)
        assert not result["passed"]

    def test_future_tasks_not_counted(self):
        future_task = _work_task("99", percent_complete=0, start=FUTURE, finish=FUTURE + timedelta(days=10))
        result = _check_13_bei([future_task], REF_DATE)
        assert result["passed"]  # No tasks should have started yet → vacuous pass


# ---------------------------------------------------------------------------
# Check 14 — Summary Tasks
# ---------------------------------------------------------------------------


class TestCheck14SummaryTasks:
    def test_normal_duration_passes(self):
        t = _work_task(duration_days=5.0)
        assert _check_14_summary_tasks([t])["passed"]

    def test_zero_duration_non_milestone_flagged(self):
        tasks = [_work_task(str(i), duration_days=0.0) for i in range(10)]
        assert not _check_14_summary_tasks(tasks)["passed"]


# ---------------------------------------------------------------------------
# _score_health
# ---------------------------------------------------------------------------


class TestScoreHealth:
    def test_green_at_11(self):
        assert _score_health(11) == "GREEN"
        assert _score_health(14) == "GREEN"

    def test_yellow_at_8_to_10(self):
        assert _score_health(8) == "YELLOW"
        assert _score_health(10) == "YELLOW"

    def test_red_below_8(self):
        assert _score_health(7) == "RED"
        assert _score_health(0) == "RED"
