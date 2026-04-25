"""
Tests for agent.file_handler — IMS XML parsing and write-back.

Covers 1.2 checklist items:
- Parsed task count matches expected
- No data loss (all fields present)
- CAM grouping: every task assigned to exactly one CAM
- Written values match input values when re-parsed (1.4)
"""

import os
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

import pytest

# Point at the sample file relative to this test file
_SAMPLE = Path(__file__).parent.parent / "data" / "sample_ims.xml"

# Expected counts from sample_ims.xml
_EXPECTED_TASK_COUNT = 57   # UIDs 1-57 (UID 0 is project summary, excluded)
_EXPECTED_CAM_COUNT = 5
_EXPECTED_MILESTONE_COUNT = 7


def _load_handler(path: str | Path = _SAMPLE):
    from agent.file_handler import IMSFileHandler
    return IMSFileHandler(str(path))


# ---------------------------------------------------------------------------
# 1.2 — Parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_task_count(self):
        """Parsed task count matches expected (57 work tasks)."""
        handler = _load_handler()
        tasks = handler.parse()
        assert len(tasks) == _EXPECTED_TASK_COUNT, (
            f"Expected {_EXPECTED_TASK_COUNT} tasks, got {len(tasks)}"
        )

    def test_no_data_loss_required_fields(self):
        """Every task has the required fields with non-None values."""
        handler = _load_handler()
        tasks = handler.parse()
        required = ["task_id", "name", "start", "finish", "percent_complete",
                    "predecessors", "cam", "duration_days"]
        for task in tasks:
            for field in required:
                assert field in task, f"Task {task.get('task_id')} missing field '{field}'"
                assert task[field] is not None, (
                    f"Task {task.get('task_id')} field '{field}' is None"
                )

    def test_percent_complete_range(self):
        """All percent_complete values are in [0, 100]."""
        handler = _load_handler()
        tasks = handler.parse()
        for task in tasks:
            pct = task["percent_complete"]
            assert 0 <= pct <= 100, (
                f"Task {task['task_id']} has invalid percent_complete={pct}"
            )

    def test_cam_grouping_every_task_has_exactly_one_cam(self):
        """Every task is assigned to exactly one CAM (not 'Unassigned' for non-summary tasks)."""
        handler = _load_handler()
        tasks = handler.parse()
        for task in tasks:
            assert task["cam"] != "Unassigned", (
                f"Task {task['task_id']} ({task['name']}) has no CAM assignment"
            )

    def test_cam_count(self):
        """Exactly 5 unique CAMs are present."""
        handler = _load_handler()
        tasks = handler.parse()
        cams = {t["cam"] for t in tasks}
        assert len(cams) == _EXPECTED_CAM_COUNT, f"Expected 5 CAMs, got {len(cams)}: {cams}"

    def test_milestone_count(self):
        """Exactly 7 milestones are present."""
        handler = _load_handler()
        tasks = handler.parse()
        milestones = [t for t in tasks if t.get("is_milestone")]
        assert len(milestones) == _EXPECTED_MILESTONE_COUNT, (
            f"Expected {_EXPECTED_MILESTONE_COUNT} milestones, got {len(milestones)}"
        )

    def test_start_finish_are_datetimes(self):
        """Start and finish fields are datetime objects."""
        handler = _load_handler()
        tasks = handler.parse()
        for task in tasks:
            assert isinstance(task["start"], datetime), (
                f"Task {task['task_id']} start is not datetime: {task['start']!r}"
            )
            assert isinstance(task["finish"], datetime), (
                f"Task {task['task_id']} finish is not datetime: {task['finish']!r}"
            )

    def test_predecessor_links(self):
        """At least one task has predecessors (dependency chain exists)."""
        handler = _load_handler()
        tasks = handler.parse()
        tasks_with_preds = [t for t in tasks if t["predecessors"]]
        assert len(tasks_with_preds) > 0, "No tasks have predecessors"

    def test_project_summary_excluded(self):
        """UID 0 (project summary task) is not included in parsed results."""
        handler = _load_handler()
        tasks = handler.parse()
        uid_zero = [t for t in tasks if t["task_id"] == "0"]
        assert len(uid_zero) == 0, "UID 0 (project summary) should be excluded"

    def test_file_not_found_raises(self):
        """FileNotFoundError raised for a missing file."""
        from agent.file_handler import IMSFileHandler
        with pytest.raises(FileNotFoundError):
            handler = IMSFileHandler("nonexistent_path/missing.xml")
            handler.parse()


# ---------------------------------------------------------------------------
# 1.4 — Write-back: written values match input when re-parsed
# ---------------------------------------------------------------------------

class TestWriteback:
    def test_percent_complete_roundtrip(self, tmp_path):
        """Written percent-complete values match inputs when file is re-parsed."""
        import shutil
        from agent.file_handler import IMSFileHandler
        from datetime import datetime

        # Copy sample to temp dir
        tmp_file = tmp_path / "ims_test.xml"
        shutil.copy(_SAMPLE, tmp_file)

        handler = IMSFileHandler(str(tmp_file))
        tasks = handler.parse()

        # Build updates for first 5 non-milestone tasks
        work_tasks = [t for t in tasks if not t.get("is_milestone")][:5]
        updates = [
            {
                "task_id": t["task_id"],
                "cam_name": t["cam"],
                "percent_complete": (t["percent_complete"] + 10) % 101,
                "blocker": "",
                "risk_flag": False,
                "risk_description": "",
                "timestamp": datetime.now().isoformat(),
            }
            for t in work_tasks
        ]

        handler.apply_updates(updates)

        # Re-parse the updated file
        updated_handler = IMSFileHandler(str(handler.file_path))
        updated_tasks = updated_handler.parse()
        updated_map = {t["task_id"]: t for t in updated_tasks}

        for update in updates:
            tid = str(update["task_id"])
            actual_pct = updated_map[tid]["percent_complete"]
            assert actual_pct == update["percent_complete"], (
                f"Task {tid}: expected pct={update['percent_complete']}, got {actual_pct}"
            )

    def test_notes_written_for_blocker(self, tmp_path):
        """Blocker text is written to the Notes field."""
        import shutil
        from agent.file_handler import IMSFileHandler
        from datetime import datetime

        tmp_file = tmp_path / "ims_notes_test.xml"
        shutil.copy(_SAMPLE, tmp_file)

        handler = IMSFileHandler(str(tmp_file))
        tasks = handler.parse()
        target = [t for t in tasks if not t.get("is_milestone")][0]

        updates = [{
            "task_id": target["task_id"],
            "cam_name": target["cam"],
            "percent_complete": 50,
            "blocker": "Waiting on vendor delivery",
            "risk_flag": False,
            "risk_description": "",
            "timestamp": datetime.now().isoformat(),
        }]
        handler.apply_updates(updates)

        updated_handler = IMSFileHandler(str(handler.file_path))
        updated_tasks = updated_handler.parse()
        updated_map = {t["task_id"]: t for t in updated_tasks}

        notes = updated_map[str(target["task_id"])].get("notes", "")
        assert "Waiting on vendor delivery" in notes, (
            f"Expected blocker in notes, got: {notes!r}"
        )
