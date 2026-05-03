"""
Tests for agent.ims_diff — Phase 7.4 additions.

Covers:
  - save_snapshot / load_snapshot  (7.4.3)
  - merge_diffs (TestCumulativeDiff — 7.4.2)
  - compute_baseline_drift (TestBaselineDrift — 7.4.3)
"""

import json
import os
import pytest
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tasks(n=3, *, start_day=5, finish_day=25, pct=50):
    """Return a minimal task list for snapshot/drift tests."""
    base = datetime(2026, 1, 1)
    return [
        {
            "task_id": str(i),
            "name": f"Task {i}",
            "cam": "Alice Nguyen",
            "start": base + timedelta(days=start_day),
            "finish": base + timedelta(days=finish_day),
            "baseline_finish": base + timedelta(days=finish_day),
            "percent_complete": pct,
            "is_milestone": i == n,     # last task is milestone
        }
        for i in range(1, n + 1)
    ]


def _write_diff_file(exports_dir, cycle_id, changes):
    """Write a minimal diff JSON to tmp exports dir."""
    path = os.path.join(exports_dir, f"{cycle_id}_diff.json")
    with open(path, "w") as f:
        json.dump(changes, f)


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------

class TestSnapshot:
    """save_snapshot / load_snapshot round-trip (7.4.3)."""

    def test_save_and_reload_snapshot(self, tmp_path, monkeypatch):
        """Snapshot is written and reloaded with correct field values."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        # Reload module-level _EXPORTS_DIR after env change
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        tasks = _make_tasks(3)
        m.save_snapshot("20260101T000000Z", tasks)
        loaded = m.load_snapshot("20260101T000000Z")

        assert loaded is not None
        assert len(loaded) == 3
        assert loaded[0]["task_id"] == "1"
        assert loaded[0]["percent_complete"] == 50

    def test_load_nonexistent_snapshot_returns_none(self, tmp_path, monkeypatch):
        """load_snapshot returns None when no file exists."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        result = m.load_snapshot("NOSUCHCYCLE")
        assert result is None

    def test_list_snapshot_cycle_ids(self, tmp_path, monkeypatch):
        """list_snapshot_cycle_ids returns sorted IDs of written snapshots."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        tasks = _make_tasks(2)
        m.save_snapshot("20260101T000000Z", tasks)
        m.save_snapshot("20260102T000000Z", tasks)

        ids = m.list_snapshot_cycle_ids()
        assert ids == ["20260101T000000Z", "20260102T000000Z"]


# ---------------------------------------------------------------------------
# TestCumulativeDiff  (7.4.2)
# ---------------------------------------------------------------------------

class TestCumulativeDiff:
    """merge_diffs — cumulative change report across multiple cycles."""

    def test_merge_single_cycle(self, tmp_path, monkeypatch):
        """Merging a single cycle returns the same changes."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        exports = tmp_path / "ims_exports"
        exports.mkdir()
        changes = [
            {"task_id": "1", "task_name": "Task 1", "cam_name": "Alice",
             "field": "percent_complete", "old_value": 50, "new_value": 75,
             "cycle_id": "20260101T000000Z"},
        ]
        _write_diff_file(str(exports), "20260101T000000Z", changes)

        merged = m.merge_diffs("20260101T000000Z", "20260101T000000Z")
        assert len(merged) == 1
        assert merged[0]["task_id"] == "1"
        assert merged[0]["new_value"] == 75
        assert merged[0]["hop_count"] == 1
        assert "20260101T000000Z" in merged[0]["contributing_cycle_ids"]

    def test_merge_two_cycles_net_value(self, tmp_path, monkeypatch):
        """Merging two cycles produces the earliest old_value and latest new_value."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        exports = tmp_path / "ims_exports"
        exports.mkdir()
        cycle_a = [{"task_id": "1", "task_name": "Task 1", "cam_name": "Alice",
                    "field": "percent_complete", "old_value": 50, "new_value": 70,
                    "cycle_id": "20260101T000000Z"}]
        cycle_b = [{"task_id": "1", "task_name": "Task 1", "cam_name": "Alice",
                    "field": "percent_complete", "old_value": 70, "new_value": 90,
                    "cycle_id": "20260102T000000Z"}]
        _write_diff_file(str(exports), "20260101T000000Z", cycle_a)
        _write_diff_file(str(exports), "20260102T000000Z", cycle_b)

        merged = m.merge_diffs("20260101T000000Z", "20260102T000000Z")
        assert len(merged) == 1
        rec = merged[0]
        assert rec["old_value"] == 50       # from earliest cycle
        assert rec["new_value"] == 90       # from latest cycle
        assert rec["hop_count"] == 2

    def test_merge_hop_count_correct(self, tmp_path, monkeypatch):
        """hop_count reflects the number of times a field changed across cycles."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        exports = tmp_path / "ims_exports"
        exports.mkdir()
        for i, (old, new) in enumerate([(10, 30), (30, 60), (60, 100)]):
            cid = f"2026010{i+1}T000000Z"
            _write_diff_file(str(exports), cid, [
                {"task_id": "1", "task_name": "Task 1", "cam_name": "Alice",
                 "field": "percent_complete", "old_value": old, "new_value": new,
                 "cycle_id": cid}
            ])

        merged = m.merge_diffs("20260101T000000Z", "20260103T000000Z")
        assert merged[0]["hop_count"] == 3

    def test_merge_contributing_cycle_ids(self, tmp_path, monkeypatch):
        """contributing_cycle_ids lists every cycle where the field changed."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        exports = tmp_path / "ims_exports"
        exports.mkdir()
        for cid, new in [("20260101T000000Z", 40), ("20260102T000000Z", 80)]:
            _write_diff_file(str(exports), cid, [
                {"task_id": "2", "task_name": "Task 2", "cam_name": "Bob",
                 "field": "percent_complete", "old_value": 0, "new_value": new,
                 "cycle_id": cid}
            ])

        merged = m.merge_diffs("20260101T000000Z", "20260102T000000Z")
        ids = merged[0]["contributing_cycle_ids"]
        assert "20260101T000000Z" in ids
        assert "20260102T000000Z" in ids

    def test_merge_empty_range_returns_empty(self, tmp_path, monkeypatch):
        """merge_diffs returns an empty list when no files are in range."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        exports = tmp_path / "ims_exports"
        exports.mkdir()
        _write_diff_file(str(exports), "20260101T000000Z", [])

        merged = m.merge_diffs("20260110T000000Z", "20260115T000000Z")
        assert merged == []


# ---------------------------------------------------------------------------
# TestBaselineDrift  (7.4.3)
# ---------------------------------------------------------------------------

class TestBaselineDrift:
    """compute_baseline_drift — slip calculation vs baseline snapshot."""

    def _setup(self, tmp_path, monkeypatch, baseline_tasks, current_tasks):
        """Write a snapshot and return the drift result for comparison."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        (tmp_path / "ims_exports").mkdir(exist_ok=True)
        m.save_snapshot("BASELINE001", baseline_tasks)
        return m.compute_baseline_drift(current_tasks, baseline_cycle_id="BASELINE001"), m

    def test_no_slip_when_dates_unchanged(self, tmp_path, monkeypatch):
        """Tasks with identical finish dates produce zero slip."""
        base_tasks = _make_tasks(2, finish_day=30)
        curr_tasks = _make_tasks(2, finish_day=30)
        result, _ = self._setup(tmp_path, monkeypatch, base_tasks, curr_tasks)
        # percent_complete same, finish same → no drift entries
        slipped_ms = result.get("milestones_slipped", [])
        assert slipped_ms == []

    def test_slip_days_computed_correctly(self, tmp_path, monkeypatch):
        """A task that slipped 20 days appears with finish_slip_days=20."""
        base_tasks = _make_tasks(2, finish_day=30)
        curr_tasks = _make_tasks(2, finish_day=50)     # 20 days later
        result, _ = self._setup(tmp_path, monkeypatch, base_tasks, curr_tasks)
        task_drift = result.get("task_drift", [])
        # At least one task should show 20-day slip
        slips = [t["finish_slip_days"] for t in task_drift if t["finish_slip_days"] is not None]
        assert any(s == 20 for s in slips)

    def test_milestone_slipped_appears_in_alert_list(self, tmp_path, monkeypatch):
        """A milestone slipped ≥ 14 days appears in milestones_slipped."""
        monkeypatch.setenv("BASELINE_DRIFT_ALERT_DAYS", "14")
        base_tasks = _make_tasks(3, finish_day=30)
        curr_tasks = _make_tasks(3, finish_day=50)     # 20-day slip
        result, _ = self._setup(tmp_path, monkeypatch, base_tasks, curr_tasks)
        slipped = result.get("milestones_slipped", [])
        assert len(slipped) >= 1
        assert all(s["finish_slip_days"] >= 14 for s in slipped)

    def test_missing_baseline_snapshot_returns_error(self, tmp_path, monkeypatch):
        """compute_baseline_drift returns an error dict when no snapshot exists."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import importlib, agent.ims_diff as m
        importlib.reload(m)

        (tmp_path / "ims_exports").mkdir(exist_ok=True)
        result = m.compute_baseline_drift(_make_tasks(2), baseline_cycle_id="NOSUCHCYCLE")
        assert "error" in result
        assert result["task_drift"] == []

    def test_tasks_added_detected(self, tmp_path, monkeypatch):
        """Tasks present in current but not baseline appear in tasks_added."""
        base_tasks = _make_tasks(2)
        curr_tasks = _make_tasks(3)     # one extra task
        result, _ = self._setup(tmp_path, monkeypatch, base_tasks, curr_tasks)
        assert "3" in result.get("tasks_added", [])

    def test_tasks_removed_detected(self, tmp_path, monkeypatch):
        """Tasks present in baseline but not current appear in tasks_removed."""
        base_tasks = _make_tasks(3)
        curr_tasks = _make_tasks(2)     # task 3 removed
        result, _ = self._setup(tmp_path, monkeypatch, base_tasks, curr_tasks)
        assert "3" in result.get("tasks_removed", [])
