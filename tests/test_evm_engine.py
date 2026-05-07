"""
Tests for agent/evm_engine.py — EVM metrics computation.

Phase 9.2: EVM Metrics Engine
"""

from datetime import datetime, timezone, timedelta
import pytest
from agent.evm_engine import compute_evm, _planned_pct, _compute_bei, _spi_health, _aggregate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _task(
    task_id="1",
    name="Task A",
    cam="Alice",
    duration_days=10.0,
    percent_complete=50,
    start_offset_days=-5,   # days relative to NOW
    finish_offset_days=5,   # days relative to NOW
    is_milestone=False,
):
    """Build a minimal task dict for EVM testing."""
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "task_id": task_id,
        "name": name,
        "cam": cam,
        "duration_days": duration_days,
        "percent_complete": percent_complete,
        "start": now + timedelta(days=start_offset_days),
        "finish": now + timedelta(days=finish_offset_days),
        "baseline_start": now + timedelta(days=start_offset_days),
        "baseline_finish": now + timedelta(days=finish_offset_days),
        "is_milestone": is_milestone,
        "predecessors": [],
    }


REF_DATE = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# compute_evm — top-level
# ---------------------------------------------------------------------------


class TestComputeEvm:
    def test_returns_expected_keys(self):
        tasks = [_task()]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert "program" in result
        assert "by_cam" in result
        assert "task_detail" in result
        assert "computed_at" in result
        assert "data_unit" in result
        assert result["data_unit"] == "work-days"

    def test_empty_tasks_returns_zero_program(self):
        result = compute_evm([], reference_date=REF_DATE)
        assert result["program"]["bac"] == 0.0
        assert result["program"]["bcwp"] == 0.0
        assert result["program"]["task_count"] == 0

    def test_milestones_excluded(self):
        tasks = [
            _task("1", duration_days=10, percent_complete=50),
            _task("2", duration_days=0, percent_complete=0, is_milestone=True),
        ]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["task_count"] == 1
        assert result["program"]["bac"] == 10.0

    def test_bac_equals_sum_of_durations(self):
        tasks = [
            _task("1", duration_days=8.0, percent_complete=100),
            _task("2", duration_days=4.0, percent_complete=0, cam="Bob",
                  start_offset_days=3, finish_offset_days=7),
        ]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["bac"] == 12.0

    def test_bcwp_equals_earned_duration(self):
        # Task 1: 10 days × 60% = 6 BCWP
        # Task 2: 5 days × 40% = 2 BCWP
        tasks = [
            _task("1", duration_days=10.0, percent_complete=60),
            _task("2", duration_days=5.0, percent_complete=40, cam="Bob"),
        ]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["bcwp"] == pytest.approx(8.0, abs=0.01)

    def test_by_cam_groups_correctly(self):
        tasks = [
            _task("1", cam="Alice", duration_days=10),
            _task("2", cam="Alice", duration_days=5),
            _task("3", cam="Bob", duration_days=8),
        ]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert "Alice" in result["by_cam"]
        assert "Bob" in result["by_cam"]
        assert result["by_cam"]["Alice"]["bac"] == pytest.approx(15.0, abs=0.01)
        assert result["by_cam"]["Bob"]["bac"] == pytest.approx(8.0, abs=0.01)

    def test_task_detail_count_matches_non_milestones(self):
        tasks = [
            _task("1"),
            _task("2"),
            _task("3", is_milestone=True),
        ]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert len(result["task_detail"]) == 2

    def test_program_spi_for_on_plan_task(self):
        # Task is halfway through schedule (start -5, finish +5), 50% complete
        # BCWS = 50% of duration = 5.0; BCWP = 50% of duration = 5.0 → SPI = 1.0
        tasks = [_task("1", duration_days=10, percent_complete=50,
                        start_offset_days=-5, finish_offset_days=5)]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["spi"] == pytest.approx(1.0, abs=0.01)

    def test_program_spi_behind_schedule(self):
        # Task is 80% through schedule but only 40% complete → SPI < 1
        tasks = [_task("1", duration_days=10, percent_complete=40,
                        start_offset_days=-8, finish_offset_days=2)]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["spi"] < 1.0

    def test_program_spi_ahead_of_schedule(self):
        # Task is 20% through schedule but 60% complete → SPI > 1
        tasks = [_task("1", duration_days=10, percent_complete=60,
                        start_offset_days=-2, finish_offset_days=8)]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["spi"] > 1.0

    def test_completed_task_bcwp_equals_bac(self):
        tasks = [_task("1", duration_days=10, percent_complete=100,
                        start_offset_days=-10, finish_offset_days=-1)]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["bcwp"] == pytest.approx(10.0, abs=0.01)

    def test_future_task_bcws_is_zero(self):
        # Task hasn't started yet
        tasks = [_task("1", duration_days=10, percent_complete=0,
                        start_offset_days=2, finish_offset_days=12)]
        result = compute_evm(tasks, reference_date=REF_DATE)
        assert result["program"]["bcws"] == pytest.approx(0.0, abs=0.01)

    def test_bei_computed_at_program_level(self):
        tasks = [_task("1", percent_complete=50), _task("2", percent_complete=0)]
        result = compute_evm(tasks, reference_date=REF_DATE)
        # Both tasks should have started (start -5 days); task2 pct=0 → not started
        bei = result["program"]["bei"]
        assert bei == pytest.approx(0.5, abs=0.01)

    def test_reference_date_stored_in_result(self):
        result = compute_evm([], reference_date=REF_DATE)
        assert "2026-05-06" in result["reference_date"]

    def test_task_with_no_start_finish_contributes_zero_bcws(self):
        task = {
            "task_id": "99", "name": "No Dates", "cam": "Alice",
            "duration_days": 5.0, "percent_complete": 50,
            "start": None, "finish": None,
            "is_milestone": False, "predecessors": [],
        }
        result = compute_evm([task], reference_date=REF_DATE)
        # bcwp should still be computed from percent_complete
        assert result["program"]["bcwp"] == pytest.approx(2.5, abs=0.01)
        # bcws = 0 because no dates
        assert result["program"]["bcws"] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# _planned_pct
# ---------------------------------------------------------------------------


class TestPlannedPct:
    def test_before_start_returns_zero(self):
        task = _task(start_offset_days=5, finish_offset_days=15)
        assert _planned_pct(task, REF_DATE) == pytest.approx(0.0)

    def test_after_finish_returns_one(self):
        task = _task(start_offset_days=-15, finish_offset_days=-1)
        assert _planned_pct(task, REF_DATE) == pytest.approx(1.0)

    def test_halfway_through_returns_half(self):
        task = _task(start_offset_days=-5, finish_offset_days=5)
        pct = _planned_pct(task, REF_DATE)
        assert pct == pytest.approx(0.5, abs=0.01)

    def test_no_dates_returns_zero(self):
        task = {**_task(), "start": None, "finish": None}
        assert _planned_pct(task, REF_DATE) == 0.0

    def test_zero_duration_returns_one(self):
        task = _task(start_offset_days=0, finish_offset_days=0)
        # start == finish == ref → returns 1.0 (elapsed >= total)
        assert _planned_pct(task, REF_DATE) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _compute_bei
# ---------------------------------------------------------------------------


class TestComputeBei:
    def test_all_started_bei_one(self):
        tasks = [
            _task("1", percent_complete=50),  # started
            _task("2", percent_complete=30),  # started
        ]
        bei = _compute_bei(tasks, REF_DATE)
        assert bei == pytest.approx(1.0, abs=0.01)

    def test_none_started_bei_zero(self):
        tasks = [
            _task("1", percent_complete=0),
            _task("2", percent_complete=0),
        ]
        bei = _compute_bei(tasks, REF_DATE)
        assert bei == pytest.approx(0.0, abs=0.01)

    def test_half_started_bei_half(self):
        tasks = [
            _task("1", percent_complete=50),
            _task("2", percent_complete=0),
        ]
        bei = _compute_bei(tasks, REF_DATE)
        assert bei == pytest.approx(0.5, abs=0.01)

    def test_future_task_not_counted(self):
        tasks = [
            _task("1", percent_complete=100, start_offset_days=-10, finish_offset_days=-1),
            _task("2", percent_complete=0, start_offset_days=5, finish_offset_days=15),
        ]
        # Only task 1 should have started by ref date
        bei = _compute_bei(tasks, REF_DATE)
        assert bei == pytest.approx(1.0, abs=0.01)

    def test_empty_tasks_returns_none(self):
        bei = _compute_bei([], REF_DATE)
        assert bei is None


# ---------------------------------------------------------------------------
# _spi_health
# ---------------------------------------------------------------------------


class TestSpiHealth:
    def test_green_above_threshold(self):
        assert _spi_health(1.05) == "GREEN"
        assert _spi_health(0.95) == "GREEN"

    def test_yellow_in_range(self):
        assert _spi_health(0.90) == "YELLOW"
        assert _spi_health(0.85) == "YELLOW"

    def test_red_below_threshold(self):
        assert _spi_health(0.80) == "RED"
        assert _spi_health(0.50) == "RED"

    def test_none_returns_unknown(self):
        assert _spi_health(None) == "UNKNOWN"


# ---------------------------------------------------------------------------
# _aggregate
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_eac_when_behind_schedule(self):
        # SPI < 1 → EAC > BAC
        rows = [
            {"bac": 10.0, "bcwp": 4.0, "bcws": 8.0, "sv": -4.0,
             "planned_pct": 80.0, "actual_pct": 40.0, "task_id": "1", "name": "", "cam": "A"}
        ]
        result = _aggregate(rows, "TEST")
        assert result["eac"] > result["bac"]

    def test_vac_negative_when_behind(self):
        rows = [
            {"bac": 10.0, "bcwp": 4.0, "bcws": 8.0, "sv": -4.0,
             "planned_pct": 80.0, "actual_pct": 40.0, "task_id": "1", "name": "", "cam": "A"}
        ]
        result = _aggregate(rows, "TEST")
        assert result["vac"] < 0  # over-runs projected

    def test_spi_none_when_no_bcws(self):
        rows = [
            {"bac": 10.0, "bcwp": 0.0, "bcws": 0.0, "sv": 0.0,
             "planned_pct": 0.0, "actual_pct": 0.0, "task_id": "1", "name": "", "cam": "A"}
        ]
        result = _aggregate(rows, "TEST")
        assert result["spi"] is None

    def test_completion_pct_reflects_bcwp_over_bac(self):
        rows = [
            {"bac": 10.0, "bcwp": 7.0, "bcws": 5.0, "sv": 2.0,
             "planned_pct": 50.0, "actual_pct": 70.0, "task_id": "1", "name": "", "cam": "A"}
        ]
        result = _aggregate(rows, "TEST")
        assert result["completion_pct"] == pytest.approx(70.0, abs=0.1)
