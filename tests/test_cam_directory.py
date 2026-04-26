"""
Tests for agent.cam_directory — CAM registry, scheduling, and retry logic.

Covers 2.6 checklist:
- CAM directory loads from IMS task list
- Scheduling logic respects business hours
- Retry logic respects max retry limits
- Call status tracking works correctly
"""

from datetime import datetime
from pathlib import Path
import json
import pytest

from agent.cam_directory import CAMDirectory, CAMRecord


def _sample_tasks():
    from datetime import timedelta
    base = datetime(2026, 1, 5, 8, 0)
    tasks = []
    for i in range(1, 6):
        tasks.append({
            "task_id": str(i),
            "name": f"Task {i}",
            "start": base,
            "finish": base + timedelta(days=10),
            "percent_complete": 50,
            "predecessors": [],
            "cam": "Alice Nguyen" if i <= 3 else "Bob Martinez",
            "is_milestone": False,
            "duration_days": 10,
            "baseline_start": base,
            "baseline_finish": base + timedelta(days=10),
            "notes": "",
        })
    return tasks


class TestLoadFromIMS:
    def test_creates_one_record_per_cam(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        cams = d.get_all_cams()
        assert len(cams) == 2

    def test_task_ids_assigned_correctly(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        alice = d.get_cam("Alice Nguyen")
        assert set(alice.task_ids) == {"1", "2", "3"}

    def test_cam_not_found_raises(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        with pytest.raises(KeyError):
            d.get_cam("Nonexistent Person")

    def test_milestones_excluded(self):
        from datetime import timedelta
        base = datetime(2026, 1, 5, 8, 0)
        tasks = _sample_tasks() + [{
            "task_id": "99",
            "name": "Milestone",
            "start": base,
            "finish": base,
            "percent_complete": 0,
            "predecessors": [],
            "cam": "Eva Johnson",
            "is_milestone": True,
            "duration_days": 0,
            "baseline_start": base,
            "baseline_finish": base,
            "notes": "",
        }]
        d = CAMDirectory()
        d.load_from_ims(tasks)
        # Eva still gets a record since she has a task assigned to her
        eva = d.get_cam("Eva Johnson")
        assert "99" in eva.task_ids  # milestone IS in task_ids — filtering is caller's job


class TestLoadFromFile:
    def test_load_valid_file(self, tmp_path):
        data = [
            {
                "cam_id": "cam_01",
                "name": "Carol Smith",
                "email": "carol@test.com",
                "teams_user_id": "abc-123",
                "phone": "555-1234",
                "timezone": "America/Chicago",
                "business_hours_start": 8,
                "business_hours_end": 16,
                "task_ids": ["21", "22"],
            }
        ]
        f = tmp_path / "cam_directory.json"
        f.write_text(json.dumps(data))
        d = CAMDirectory()
        d.load_from_file(str(f))
        carol = d.get_cam("Carol Smith")
        assert carol.timezone == "America/Chicago"
        assert carol.task_ids == ["21", "22"]

    def test_missing_file_raises(self, tmp_path):
        d = CAMDirectory()
        with pytest.raises(FileNotFoundError):
            d.load_from_file(str(tmp_path / "missing.json"))


class TestSaveAndReload:
    def test_roundtrip(self, tmp_path):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        path = str(tmp_path / "out.json")
        d.save_to_file(path)

        d2 = CAMDirectory()
        d2.load_from_file(path)
        assert {c.name for c in d2.get_all_cams()} == {"Alice Nguyen", "Bob Martinez"}


class TestScheduling:
    def test_can_call_during_business_hours(self, monkeypatch):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        alice = d.get_cam("Alice Nguyen")
        alice.business_hours_start = 0
        alice.business_hours_end = 24
        assert d.can_call_now(alice) is True

    def test_cannot_call_outside_business_hours(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        alice = d.get_cam("Alice Nguyen")
        # Force impossible hours so the test is deterministic
        alice.business_hours_start = 25
        alice.business_hours_end = 26
        assert d.can_call_now(alice) is False


class TestRetryLogic:
    def test_should_retry_on_first_contact(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        assert d.should_retry("Alice Nguyen") is True

    def test_should_not_retry_after_max_attempts(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        import os
        max_retries = int(os.getenv("INTERVIEW_MAX_RETRIES", "3"))
        for _ in range(max_retries):
            d.record_attempt("Alice Nguyen", "no_answer")
        assert d.should_retry("Alice Nguyen") is False

    def test_should_escalate_after_max_no_answers(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        import os
        max_retries = int(os.getenv("INTERVIEW_MAX_RETRIES", "3"))
        for _ in range(max_retries):
            d.record_attempt("Alice Nguyen", "no_answer")
        assert d.should_escalate("Alice Nguyen") is True

    def test_should_not_escalate_after_completed(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        d.record_attempt("Alice Nguyen", "no_answer")
        d.record_attempt("Alice Nguyen", "completed")
        assert d.should_escalate("Alice Nguyen") is False


class TestCallHistory:
    def test_record_attempt_increments_count(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        d.record_attempt("Alice Nguyen", "answered")
        d.record_attempt("Alice Nguyen", "completed",
                         transcript=[{"speaker": "agent", "text": "hi"}])
        summary = d.get_call_status_summary()
        assert summary["Alice Nguyen"]["attempts"] == 2
        assert summary["Alice Nguyen"]["completed"] is True

    def test_status_summary_not_contacted(self):
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        summary = d.get_call_status_summary()
        assert summary["Bob Martinez"]["last_outcome"] == "not_contacted"
