"""
Phase 7.4 platform-enhancement tests.

Covers:
  - TD-009: CAM Simulator rate limiting (SIMULATOR_CALL_DELAY_MS)
  - TD-016: Q&A context builder TTL cache (load_state / load_history)
  - 7.4.6: Cycle report IMS Diff Summary and Baseline Drift Alert sections
"""

import json
import os
import time
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# TD-009 — CAM Simulator rate limiting
# ---------------------------------------------------------------------------

class TestSimulatorRateLimit:
    """TD-009 — SIMULATOR_CALL_DELAY_MS applies a sleep between API calls."""

    def test_sleep_called_with_configured_delay(self, monkeypatch):
        """time.sleep is called with SIMULATOR_CALL_DELAY_MS / 1000 on each respond()."""
        monkeypatch.setenv("SIMULATOR_CALL_DELAY_MS", "300")

        from agent.voice.cam_simulator import CAMPersona, CAMSimulator

        persona = CAMPersona(
            cam_name="Test CAM",
            role="Test Engineer",
            communication_style="direct",
            task_context=[],
        )

        with patch("agent.voice.cam_simulator.time.sleep") as mock_sleep, \
             patch("agent.voice.cam_simulator._call_delay_s", return_value=0.3), \
             patch("agent.llm_interface.LLMInterface") as mock_llm_cls:
            mock_llm_cls.return_value.ask.return_value = "Looks good."
            session = CAMSimulator(persona)
            session.respond("How is task progress?")

        mock_sleep.assert_called_once_with(0.3)

    def test_zero_delay_skips_sleep(self, monkeypatch):
        """time.sleep is NOT called when delay is 0."""
        monkeypatch.setenv("SIMULATOR_CALL_DELAY_MS", "0")

        from agent.voice.cam_simulator import CAMPersona, CAMSimulator

        persona = CAMPersona(
            cam_name="Fast CAM",
            role="Engineer",
            communication_style="direct",
            task_context=[],
        )

        with patch("agent.voice.cam_simulator.time.sleep") as mock_sleep, \
             patch("agent.voice.cam_simulator._call_delay_s", return_value=0.0), \
             patch("agent.llm_interface.LLMInterface") as mock_llm_cls:
            mock_llm_cls.return_value.ask.return_value = "Done."
            session = CAMSimulator(persona)
            session.respond("Status update?")

        mock_sleep.assert_not_called()

    def test_call_delay_reads_env_at_call_time(self, monkeypatch):
        """_call_delay_s() reads the env var at call time (hot-reload)."""
        monkeypatch.setenv("SIMULATOR_CALL_DELAY_MS", "500")
        from agent.voice.cam_simulator import _call_delay_s
        assert _call_delay_s() == pytest.approx(0.5)

        monkeypatch.setenv("SIMULATOR_CALL_DELAY_MS", "100")
        assert _call_delay_s() == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# TD-016 — Q&A context builder TTL cache
# ---------------------------------------------------------------------------

class TestContextBuilderCache:
    """TD-016 — load_state() and load_history() use a 30s TTL cache."""

    def _reset_cache(self):
        """Reset all cache globals between tests."""
        import agent.qa.context_builder as cb
        cb._STATE_CACHE = None
        cb._STATE_CACHE_AT = 0.0
        cb._STATE_CACHE_MTIME = 0.0
        cb._HISTORY_CACHE = None
        cb._HISTORY_CACHE_AT = 0.0
        cb._HISTORY_CACHE_MTIME = 0.0

    def test_second_call_within_ttl_does_not_reread(self, tmp_path, monkeypatch):
        """Two load_state() calls within TTL result in only one JSON parse (cache hit)."""
        state_file = tmp_path / "dashboard_state.json"
        state_file.write_text(json.dumps({"schedule_health": "GREEN"}), encoding="utf-8")

        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(state_file))
        self._reset_cache()

        import agent.qa.context_builder as cb
        cb._STATE_FILE = state_file
        cb._CACHE_TTL_S = 30.0

        # Wrap json.loads to count how many times the file is actually parsed.
        # A cache hit skips the read_text + json.loads path entirely.
        with patch("agent.qa.context_builder.json.loads", wraps=json.loads) as mock_loads:
            cb.load_state()
            cb.load_state()  # second call within TTL — should return cached value

        assert mock_loads.call_count == 1, (
            f"Expected 1 JSON parse for 2 calls within TTL, got {mock_loads.call_count}"
        )

    def test_cache_invalidated_on_mtime_change(self, tmp_path, monkeypatch):
        """Cache is invalidated when the file's mtime changes."""
        state_file = tmp_path / "dashboard_state.json"
        state_file.write_text(json.dumps({"schedule_health": "RED"}), encoding="utf-8")

        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(state_file))
        self._reset_cache()

        import agent.qa.context_builder as cb
        cb._STATE_FILE = state_file
        cb._CACHE_TTL_S = 30.0

        result1 = cb.load_state()
        assert result1.get("schedule_health") == "RED"

        # Simulate file update (new mtime)
        time.sleep(0.05)
        state_file.write_text(json.dumps({"schedule_health": "GREEN"}), encoding="utf-8")

        result2 = cb.load_state()
        assert result2.get("schedule_health") == "GREEN"

    def test_missing_state_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """load_state() returns {} when the file does not exist."""
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(tmp_path / "missing.json"))
        self._reset_cache()

        import agent.qa.context_builder as cb
        cb._STATE_FILE = tmp_path / "missing.json"

        assert cb.load_state() == {}


# ---------------------------------------------------------------------------
# 7.4.6 — Cycle report: IMS Diff Summary and Baseline Drift Alert
# ---------------------------------------------------------------------------

_REPORT_DATE = datetime(2026, 5, 3, 9, 0, 0)


def _sample_tasks_rg():
    base = datetime(2026, 1, 5)
    return [
        {"task_id": "1", "name": "Task Alpha", "start": base,
         "finish": base + timedelta(days=20), "percent_complete": 100,
         "predecessors": [], "cam": "Alice Nguyen", "is_milestone": False,
         "duration_days": 20, "baseline_start": base,
         "baseline_finish": base + timedelta(days=20), "notes": ""},
        {"task_id": "2", "name": "Task Beta", "start": base + timedelta(days=20),
         "finish": base + timedelta(days=40), "percent_complete": 30,
         "predecessors": ["1"], "cam": "Bob Martinez", "is_milestone": False,
         "duration_days": 20, "baseline_start": base + timedelta(days=20),
         "baseline_finish": base + timedelta(days=40), "notes": ""},
    ]


def _sample_cp():
    return {"critical_path": ["1"], "total_float": {"1": 0.0, "2": 5.0},
            "near_critical": [], "changed_on": [], "changed_off": [],
            "projected_finish": datetime(2026, 2, 14)}


def _sample_sra():
    return [{"task_id": "M1", "milestone_name": "PDR Complete",
             "baseline_date": "2026-05-29", "p50_date": "2026-06-05",
             "p80_date": "2026-06-12", "p95_date": "2026-06-19",
             "prob_on_baseline": 0.38, "risk_level": "HIGH"}]


def _sample_cam_inputs():
    return [{"task_id": "2", "cam_name": "Bob Martinez", "percent_complete": 30,
             "blocker": "Waiting on parts", "risk_flag": False,
             "risk_description": "", "timestamp": "2026-04-25T09:00:00"}]


def _sample_synthesis():
    return {"schedule_health": "YELLOW",
            "narrative": "Program progressing.", "top_risks": "1. Supplier delay",
            "recommended_actions": "1. Expedite parts", "raw": ""}


class TestReportDiffSummary:
    """7.4.6 — IMS Diff Summary section in cycle report."""

    def test_diff_summary_present_when_diff_file_exists(self, tmp_path, monkeypatch):
        """Report contains '## IMS Diff Summary' when a diff file is present for the cycle."""
        from agent.report_generator import ReportGenerator
        os.environ["REPORTS_DIR"] = str(tmp_path)

        # Write a fake diff file
        exports = tmp_path / "ims_exports"
        exports.mkdir()
        cycle_id = "20260503T090000Z"
        diff = [{"task_id": "2", "task_name": "Task Beta", "cam_name": "Bob",
                 "field": "percent_complete", "old_value": 20, "new_value": 30,
                 "cycle_id": cycle_id}]
        (exports / f"{cycle_id}_diff.json").write_text(json.dumps(diff))

        with patch("agent.ims_diff._EXPORTS_DIR", str(exports)):
            rg = ReportGenerator()
            report_path = rg.generate(
                _sample_tasks_rg(), _sample_cp(), _sample_sra(),
                _sample_cam_inputs(), _sample_synthesis(),
                report_date=_REPORT_DATE, cycle_id=cycle_id,
            )

        content = Path(report_path).read_text(encoding="utf-8")
        assert "## IMS Diff Summary" in content
        assert "Task Beta" in content

    def test_diff_summary_absent_when_no_diff_file(self, tmp_path, monkeypatch):
        """Report has no diff summary section when no diff file exists for the cycle."""
        from agent.report_generator import ReportGenerator
        os.environ["REPORTS_DIR"] = str(tmp_path)

        exports = tmp_path / "ims_exports"
        exports.mkdir()

        with patch("agent.ims_diff._EXPORTS_DIR", str(exports)):
            rg = ReportGenerator()
            report_path = rg.generate(
                _sample_tasks_rg(), _sample_cp(), _sample_sra(),
                _sample_cam_inputs(), _sample_synthesis(),
                report_date=_REPORT_DATE, cycle_id="NOSUCHCYCLE",
            )

        content = Path(report_path).read_text(encoding="utf-8")
        assert "## IMS Diff Summary" not in content

    def test_baseline_drift_alert_absent_when_no_baseline(self, tmp_path, monkeypatch):
        """Report has no baseline drift section when no snapshot is available."""
        from agent.report_generator import ReportGenerator
        os.environ["REPORTS_DIR"] = str(tmp_path)
        monkeypatch.setenv("BASELINE_CYCLE_ID", "")

        exports = tmp_path / "ims_exports"
        exports.mkdir()

        with patch("agent.ims_diff._EXPORTS_DIR", str(exports)):
            rg = ReportGenerator()
            report_path = rg.generate(
                _sample_tasks_rg(), _sample_cp(), _sample_sra(),
                _sample_cam_inputs(), _sample_synthesis(),
                report_date=_REPORT_DATE,
            )

        content = Path(report_path).read_text(encoding="utf-8")
        assert "## Baseline Drift Alert" not in content
