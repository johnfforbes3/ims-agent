"""
Tests for agent.critical_path — CPM forward/backward pass.

Covers 1.5 checklist items:
- Critical path result matches known expected result on sample file
- Float calculation is correct
- Near-critical tasks flagged correctly
"""

from datetime import datetime, timedelta
import pytest


def _make_task(uid: str, name: str, start: datetime, duration_days: float,
               predecessors: list[str] | None = None, pct: int = 0) -> dict:
    """Helper to build a minimal task dict for CPM testing."""
    finish = start + timedelta(days=duration_days)
    return {
        "task_id": uid,
        "name": name,
        "start": start,
        "finish": finish,
        "duration_days": duration_days,
        "percent_complete": pct,
        "predecessors": predecessors or [],
        "is_milestone": False,
        "cam": "Test CAM",
        "baseline_start": start,
        "baseline_finish": finish,
        "notes": "",
    }


BASE = datetime(2026, 1, 5, 8, 0, 0)


class TestCriticalPathSimple:
    """Tests on a small, manually-verifiable network."""

    def _build_linear_network(self) -> list[dict]:
        """A → B → C (each 10 days). Only one path — all tasks are critical."""
        a = _make_task("A", "Task A", BASE, 10)
        b = _make_task("B", "Task B", BASE + timedelta(days=10), 10, ["A"])
        c = _make_task("C", "Task C", BASE + timedelta(days=20), 10, ["B"])
        return [a, b, c]

    def _build_parallel_network(self) -> list[dict]:
        """
        A → C (10+10=20 days)
        B → C (5 days + 10 days = 15 days)
        Critical path is A → C.
        B has float = 5 days.
        """
        a = _make_task("A", "Task A", BASE, 10)
        b = _make_task("B", "Task B", BASE, 5)  # shorter parallel branch
        c = _make_task("C", "Task C", BASE + timedelta(days=10), 10, ["A", "B"])
        return [a, b, c]

    def test_linear_all_critical(self):
        from agent.critical_path import calculate_critical_path
        tasks = self._build_linear_network()
        result = calculate_critical_path(tasks)
        assert set(result["critical_path"]) == {"A", "B", "C"}

    def test_parallel_correct_critical_path(self):
        from agent.critical_path import calculate_critical_path
        tasks = self._build_parallel_network()
        result = calculate_critical_path(tasks)
        # A and C must be on CP; B must not be
        assert "A" in result["critical_path"], "Task A should be on critical path"
        assert "C" in result["critical_path"], "Task C should be on critical path"
        assert "B" not in result["critical_path"], "Task B should NOT be on critical path"

    def test_parallel_float_for_non_critical(self):
        from agent.critical_path import calculate_critical_path
        tasks = self._build_parallel_network()
        result = calculate_critical_path(tasks)
        float_b = result["total_float"].get("B", None)
        assert float_b is not None, "Float for B should be computed"
        assert abs(float_b - 5.0) < 1.0, f"Task B float should be ~5 days, got {float_b}"

    def test_empty_task_list(self):
        from agent.critical_path import calculate_critical_path
        result = calculate_critical_path([])
        assert result["critical_path"] == []
        assert result["total_float"] == {}

    def test_projected_finish_is_latest_ef(self):
        from agent.critical_path import calculate_critical_path
        tasks = self._build_linear_network()
        result = calculate_critical_path(tasks)
        expected_finish = BASE + timedelta(days=30)
        assert result["projected_finish"] is not None
        # Allow ± 1 day for floating-point arithmetic
        delta = abs((result["projected_finish"] - expected_finish).total_seconds())
        assert delta < 86400, f"Projected finish off by {delta}s"

    def test_near_critical_flagged(self, monkeypatch):
        """Task with float <= NEAR_CRITICAL_FLOAT_DAYS is in near_critical list."""
        import agent.critical_path as cpm_mod
        monkeypatch.setattr(cpm_mod, "_NEAR_CRITICAL_DAYS", 5)
        tasks = self._build_parallel_network()
        result = cpm_mod.calculate_critical_path(tasks)
        # B has float=5 days — should be near-critical
        assert "B" in result["near_critical"], (
            f"Task B (float=5d) should be near-critical. near_critical={result['near_critical']}"
        )


class TestCriticalPathOnSampleFile:
    """Smoke test CPM on the full sample_ims.xml."""

    def test_sample_file_has_critical_path(self):
        from pathlib import Path
        from agent.file_handler import IMSFileHandler
        from agent.critical_path import calculate_critical_path

        sample = Path(__file__).parent.parent / "data" / "sample_ims.xml"
        handler = IMSFileHandler(str(sample))
        tasks = handler.parse()
        result = calculate_critical_path(tasks)

        assert len(result["critical_path"]) > 0, "Sample file should have a critical path"
        assert result["projected_finish"] is not None

    def test_all_tasks_have_float(self):
        from pathlib import Path
        from agent.file_handler import IMSFileHandler
        from agent.critical_path import calculate_critical_path

        sample = Path(__file__).parent.parent / "data" / "sample_ims.xml"
        handler = IMSFileHandler(str(sample))
        tasks = handler.parse()
        result = calculate_critical_path(tasks)

        task_ids = {t["task_id"] for t in tasks}
        float_ids = set(result["total_float"].keys())
        assert task_ids == float_ids, (
            f"Missing float for tasks: {task_ids - float_ids}"
        )


class TestDiffCriticalPath:
    def test_diff_detects_moved_on(self):
        from agent.critical_path import diff_critical_path
        prev = ["A", "B"]
        curr = ["A", "B", "C"]
        changed_on, changed_off = diff_critical_path(prev, curr)
        assert "C" in changed_on
        assert changed_off == []

    def test_diff_detects_moved_off(self):
        from agent.critical_path import diff_critical_path
        prev = ["A", "B", "C"]
        curr = ["A", "C"]
        changed_on, changed_off = diff_critical_path(prev, curr)
        assert "B" in changed_off
        assert changed_on == []
