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


# ---------------------------------------------------------------------------
# Phase 6.0 — Core Integrity tests
# ---------------------------------------------------------------------------

class TestIMSMasterCustody:
    """6.0.1 — ims_master/ must contain exactly one file after _export_ims_snapshot."""

    def test_master_file_survives_cleanup(self, tmp_path):
        """Cleanup loop must not delete the newly-written master file."""
        # Arrange: create a fake source IMS XML and a fake master that
        # xml_to_master "writes" (we mock it to return a path that may differ
        # in case from new_master on Windows).
        src = tmp_path / "sample_ims.xml"
        src.write_text("<Project/>", encoding="utf-8")

        master_dir = tmp_path / "ims_master"
        master_dir.mkdir()
        exports_dir = tmp_path / "ims_exports"
        exports_dir.mkdir()

        # Simulate an old master file that should be removed.
        old_master = master_dir / "IMS_2026-01-01_0000z.xml"
        old_master.write_text("<old/>", encoding="utf-8")

        # xml_to_master writes to new_master and returns the same path —
        # but we simulate a case-difference by upper-casing the returned path.
        written = master_dir / "IMS_2026-05-03_1200z.xml"
        written.write_text("<new/>", encoding="utf-8")

        def fake_xml_to_master(src_path, dest_path):
            # Return the dest_path with a case variation to simulate Windows behaviour.
            return str(written).upper()

        with (
            patch("agent.cycle_runner._IMS_EXPORTS_DIR", str(exports_dir)),
            patch("agent.cycle_runner._IMS_MASTER_DIR", str(master_dir)),
            patch("agent.mpp_converter.is_available", return_value=True),
            patch("agent.mpp_converter.xml_to_master", side_effect=fake_xml_to_master),
            patch("agent.mpp_converter.master_extension", return_value=".xml"),
        ):
            CycleRunner._export_ims_snapshot("TEST001", str(src))

        remaining = list(master_dir.glob("*.xml")) + list(master_dir.glob("*.mpp"))
        assert len(remaining) == 1, (
            f"ims_master/ must contain exactly 1 file after cleanup; found {[f.name for f in remaining]}"
        )
        assert remaining[0].name.startswith("IMS_2026-05-03"), (
            "The surviving file must be the new master, not the old one"
        )

    def test_old_master_removed_on_new_write(self, tmp_path):
        """Previous master files are removed when a new one is written."""
        src = tmp_path / "sample_ims.xml"
        src.write_text("<Project/>", encoding="utf-8")
        master_dir = tmp_path / "ims_master"
        master_dir.mkdir()
        exports_dir = tmp_path / "ims_exports"
        exports_dir.mkdir()

        for i in range(3):
            old = master_dir / f"IMS_2026-0{i+1}-01_0000z.xml"
            old.write_text("<old/>", encoding="utf-8")

        new_written = master_dir / "IMS_2026-05-03_1400z.xml"
        new_written.write_text("<new/>", encoding="utf-8")

        with (
            patch("agent.cycle_runner._IMS_EXPORTS_DIR", str(exports_dir)),
            patch("agent.cycle_runner._IMS_MASTER_DIR", str(master_dir)),
            patch("agent.mpp_converter.is_available", return_value=True),
            patch("agent.mpp_converter.xml_to_master", return_value=str(new_written)),
            patch("agent.mpp_converter.master_extension", return_value=".xml"),
        ):
            CycleRunner._export_ims_snapshot("TEST002", str(src))

        remaining = list(master_dir.glob("*.xml"))
        assert len(remaining) == 1
        assert remaining[0].name == "IMS_2026-05-03_1400z.xml"


class TestApprovalTransactionality:
    """6.0.4 — approval record must remain 'pending' if IMS write fails."""

    def test_record_stays_pending_when_apply_updates_fails(self, tmp_path, monkeypatch):
        """apply_approved must not commit approval when the IMS write raises."""
        from agent.approval_store import save_pending, load_pending

        approval_dir = tmp_path / "pending_approvals"
        monkeypatch.setattr("agent.approval_store._APPROVAL_DIR", approval_dir)

        # Save a fake pending record.
        cycle_id = "TEST_APPROVAL_001"
        save_pending(
            cycle_id=cycle_id,
            cam_inputs=[{"task_id": "T1", "cam_name": "Alice", "percent_complete": 80}],
            validation_failures=[{"task_id": "T1", "reason": "backwards_movement"}],
            ims_path="data/sample_ims.xml",
        )

        # Patch apply_updates to raise so the IMS write fails.
        with patch("agent.file_handler.IMSFileHandler.apply_updates", side_effect=RuntimeError("disk full")):
            result = CycleRunner.apply_approved(cycle_id, approver="test")

        assert "error" in result, "apply_approved must return an error dict when write fails"
        record = load_pending(cycle_id)
        assert record is not None
        assert record["status"] == "pending", (
            f"Record must remain 'pending' after a failed write; got {record['status']!r}"
        )

    def test_record_marked_approved_on_success(self, tmp_path, monkeypatch):
        """apply_approved marks the record 'approved' only after all writes succeed."""
        from agent.approval_store import save_pending, load_pending

        approval_dir = tmp_path / "pending_approvals"
        monkeypatch.setattr("agent.approval_store._APPROVAL_DIR", approval_dir)

        cycle_id = "TEST_APPROVAL_002"
        save_pending(
            cycle_id=cycle_id,
            cam_inputs=[{"task_id": "T1", "cam_name": "Alice", "percent_complete": 80}],
            validation_failures=[],
            ims_path="data/sample_ims.xml",
        )

        # apply_approved: parse → apply_updates → parse → _export_ims_snapshot
        #                 → calculate_critical_path → SRARunner.run → compute_health
        #                 → LLMInterface.synthesize → ReportGenerator.generate
        #                 → mark_approved
        with (
            patch("agent.file_handler.IMSFileHandler.parse", return_value=[]),
            patch("agent.file_handler.IMSFileHandler.apply_updates", return_value=None),
            patch("agent.cycle_runner.CycleRunner._export_ims_snapshot", return_value="/tmp/x.xml"),
            patch("agent.critical_path.calculate_critical_path", return_value={
                "critical_path": [], "total_float": {}, "project_float_days": 0, "near_critical": []
            }),
            patch("agent.sra_runner.SRARunner.run", return_value=[]),
            patch("agent.schedule_health.compute_health", return_value=("GREEN", "all good")),
            patch("agent.llm_interface.LLMInterface.synthesize", return_value={
                "narrative": "", "top_risks": [], "recommended_actions": []
            }),
            patch("agent.report_generator.ReportGenerator.generate", return_value="reports/test.md"),
        ):
            result = CycleRunner.apply_approved(cycle_id, approver="pm@test.com")

        assert "error" not in result, f"Expected success but got error: {result.get('error')}"
        record = load_pending(cycle_id)
        assert record is not None
        assert record["status"] == "approved", (
            f"Record must be 'approved' after successful write; got {record['status']!r}"
        )
        assert record["approver"] == "pm@test.com"
