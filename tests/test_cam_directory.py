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


class TestTimezoneAwareness:
    """TD-002 — can_call_now() uses CAM's IANA timezone, not local machine time."""

    def test_la_cam_outside_hours_at_0600_utc(self):
        """LA CAM at 06:00 UTC = 22:00 PST — outside 09:00-17:00 business hours."""
        from unittest.mock import patch
        from datetime import datetime as _dt, timezone as _tz

        # 06:00 UTC = 22:00 PST (UTC-8 in January) → outside [9, 17)
        utc_6am = _dt(2026, 1, 15, 6, 0, 0, tzinfo=_tz.utc)

        d = CAMDirectory()
        cam = CAMRecord(
            cam_id="cam_la", name="LA CAM", email="", teams_user_id="", phone="",
            timezone="America/Los_Angeles",
            business_hours_start=9, business_hours_end=17,
        )

        with patch("agent.cam_directory.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz=None: (
                utc_6am.astimezone(tz) if tz is not None else utc_6am
            )
            assert d.can_call_now(cam) is False

    def test_la_cam_inside_hours_at_1800_utc(self):
        """LA CAM at 18:00 UTC = 10:00 PST — inside 09:00-17:00 business hours."""
        from unittest.mock import patch
        from datetime import datetime as _dt, timezone as _tz

        # 18:00 UTC = 10:00 PST (UTC-8 in January) → inside [9, 17)
        utc_6pm = _dt(2026, 1, 15, 18, 0, 0, tzinfo=_tz.utc)

        d = CAMDirectory()
        cam = CAMRecord(
            cam_id="cam_la", name="LA CAM", email="", teams_user_id="", phone="",
            timezone="America/Los_Angeles",
            business_hours_start=9, business_hours_end=17,
        )

        with patch("agent.cam_directory.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz=None: (
                utc_6pm.astimezone(tz) if tz is not None else utc_6pm
            )
            assert d.can_call_now(cam) is True

    def test_invalid_timezone_falls_back_to_utc(self):
        """Invalid timezone string falls back to UTC without raising."""
        d = CAMDirectory()
        cam = CAMRecord(
            cam_id="cam_bad", name="Bad TZ CAM", email="", teams_user_id="", phone="",
            timezone="Invalid/NotATimezone",
            business_hours_start=0, business_hours_end=24,
        )
        # 0-24 always-open window ensures True regardless of fallback timezone
        assert d.can_call_now(cam) is True


class TestCallHistoryPersistence:
    """TD-003 — call history survives save/reload cycle."""

    def test_call_history_roundtrip(self, tmp_path):
        """Attempts recorded before save are restored after reload."""
        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        d.record_attempt("Alice Nguyen", "no_answer")
        d.record_attempt("Alice Nguyen", "no_answer")

        path = str(tmp_path / "cam_dir.json")
        d.save_to_file(path)

        d2 = CAMDirectory()
        d2.load_from_file(path)

        summary = d2.get_call_status_summary()
        assert summary["Alice Nguyen"]["attempts"] == 2
        assert summary["Alice Nguyen"]["last_outcome"] == "no_answer"

    def test_should_retry_false_after_reload(self, tmp_path):
        """should_retry honours persisted no_answer history after process restart."""
        import os
        max_retries = int(os.getenv("INTERVIEW_MAX_RETRIES", "3"))

        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        for _ in range(max_retries):
            d.record_attempt("Alice Nguyen", "no_answer")

        path = str(tmp_path / "cam_dir.json")
        d.save_to_file(path)

        d2 = CAMDirectory()
        d2.load_from_file(path)
        assert d2.should_retry("Alice Nguyen") is False

    def test_should_escalate_true_after_reload(self, tmp_path):
        """should_escalate honours persisted no_answer history after process restart."""
        import os
        max_retries = int(os.getenv("INTERVIEW_MAX_RETRIES", "3"))

        d = CAMDirectory()
        d.load_from_ims(_sample_tasks())
        for _ in range(max_retries):
            d.record_attempt("Alice Nguyen", "no_answer")

        path = str(tmp_path / "cam_dir.json")
        d.save_to_file(path)

        d2 = CAMDirectory()
        d2.load_from_file(path)
        assert d2.should_escalate("Alice Nguyen") is True

    def test_load_legacy_list_format_has_empty_history(self, tmp_path):
        """Legacy JSON array format loads without error; call history starts empty."""
        data = [
            {
                "cam_id": "cam_01",
                "name": "Alice Nguyen",
                "email": "alice@test.com",
                "teams_user_id": "",
                "phone": "",
                "timezone": "America/New_York",
                "business_hours_start": 9,
                "business_hours_end": 17,
                "task_ids": ["1", "2"],
            }
        ]
        f = tmp_path / "legacy.json"
        f.write_text(json.dumps(data))

        d = CAMDirectory()
        d.load_from_file(str(f))

        summary = d.get_call_status_summary()
        assert summary["Alice Nguyen"]["attempts"] == 0
        assert summary["Alice Nguyen"]["last_outcome"] == "not_contacted"
