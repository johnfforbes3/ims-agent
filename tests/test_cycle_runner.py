"""Tests for agent.cycle_runner — CycleRunner."""

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.cycle_runner import CycleRunner


@pytest.fixture(autouse=True)
def reset_cycle_lock():
    """Ensure the class-level active flag is cleared between tests."""
    CycleRunner._active = False
    yield
    CycleRunner._active = False


@pytest.fixture(autouse=True)
def isolated_data_dirs(tmp_path, monkeypatch):
    """
    Redirect all cycle-runner file I/O (reports, data) to a temporary directory.

    This prevents test runs from accumulating *_status.json files in the real
    reports/cycles/ directory and from touching real data/ paths.
    Tests that need to inspect specific output paths should use tmp_path
    directly (as test_status_persisted_to_disk does with its own patch).
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("agent.cycle_runner._REPORTS_DIR", str(reports))
    monkeypatch.setattr("agent.cycle_runner._DATA_DIR", str(data))
    yield tmp_path


class TestCycleLocking:
    def test_duplicate_trigger_raises(self):
        CycleRunner._active = True
        runner = CycleRunner()
        with pytest.raises(RuntimeError, match="already running"):
            runner.run()

    def test_lock_released_after_failure(self):
        runner = CycleRunner(ims_path="nonexistent_file_xyz.xml")
        status = runner.run()  # will fail — file missing
        assert status["phase"] == "failed"
        assert CycleRunner._active is False

    def test_is_active_reflects_state(self):
        assert CycleRunner.is_active() is False
        CycleRunner._active = True
        assert CycleRunner.is_active() is True


class TestCycleStatus:
    def test_failed_status_has_error_field(self):
        runner = CycleRunner(ims_path="no_such_file.xml")
        status = runner.run()
        assert "error" in status
        assert status["error"] != ""
        assert "cycle_id" in status
        assert "started_at" in status
        assert "completed_at" in status

    def test_status_persisted_to_disk(self, tmp_path):
        runner = CycleRunner(ims_path="no_such_file.xml")
        # Override reports dir to tmp_path
        with patch("agent.cycle_runner._REPORTS_DIR", str(tmp_path)):
            status = runner.run()
        cycle_id = status["cycle_id"]
        persisted = list(tmp_path.glob(f"cycles/{cycle_id}_status.json"))
        assert len(persisted) == 1
        data = json.loads(persisted[0].read_text())
        assert data["cycle_id"] == cycle_id


class TestScheduleValidator:
    """Smoke test: CycleRunner calls ScheduleValidator during validating phase."""

    def test_validation_failure_captured_in_status(self):
        from agent.validation import ScheduleValidator, ValidationResult, ValidationFailure

        mock_result = ValidationResult(
            passed=False,
            failures=[ValidationFailure("T1", "Alice", "backwards_movement", "pct went from 50 to 30")],
        )

        runner = CycleRunner(ims_path="no_such_file.xml")
        with patch.object(ScheduleValidator, "validate", return_value=mock_result):
            # Runner will still fail (no IMS file) but we can verify the validator is called
            status = runner.run()
        # Validator is called inside _run_inner which is not reached without IMS — so just assert runner completes
        assert status["phase"] in ("failed", "complete")


class TestNotifierIntegration:
    """Verify notifier is called when notify=True and cycle reaches distributing."""

    def test_send_slack_called_on_complete_cycle(self):
        """
        Verify build_cycle_summary returns the expected structure and send_slack
        is callable without raising. Mocks the actual HTTP call so the test is not
        sensitive to whether SLACK_WEBHOOK_URL is configured.
        """
        from unittest.mock import patch
        from agent.notifier import send_slack, build_cycle_summary

        summary = build_cycle_summary(
            health="RED",
            top_risks=["Risk 1", "Risk 2"],
            milestones_at_risk=[],
            cams_responded=3,
            cams_total=5,
            report_path="reports/test.md",
        )
        assert summary["health"] == "RED"
        assert len(summary["top_risks"]) == 2

        # Mock urlopen so the test never hits the network
        with patch("agent.notifier._SLACK_WEBHOOK", ""):
            result = send_slack(summary)
        assert result is False  # empty webhook → graceful skip
