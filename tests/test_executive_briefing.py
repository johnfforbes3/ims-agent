"""
Tests for agent/executive_briefing.py — Executive Briefing Generator.

Phase 9.5: Executive Briefing Generator
"""

import os
import tempfile
import pytest
from unittest.mock import patch
from agent.executive_briefing import (
    generate_briefing,
    _build_html,
    _evm_kpi_cards,
    _dcma_section,
    _milestone_table,
    _cam_status_table,
    _esc,
    _save_briefing,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_state():
    return {
        "cycle_id": "20260506T120000Z",
        "schedule_health": "YELLOW",
        "narrative": "The program is slightly behind schedule.",
        "top_risks": "1. Vendor delays\n2. Integration complexity",
        "recommended_actions": "1. Expedite vendor deliveries\n2. Add integration resources",
        "variance_narrative": "This cycle shows a schedule variance of -3 work-days.",
        "variance_summary": {"spi": 0.92, "sv_work_days": -3.0},
        "evm": {
            "program": {
                "spi": 0.92, "sv": -3.0, "sv_pct": -8.0,
                "bac": 100.0, "bcwp": 46.0, "bcws": 50.0,
                "eac": 108.7, "vac": -8.7, "completion_pct": 46.0, "bei": 0.88,
            },
            "by_cam": {
                "Alice": {"spi": 0.90, "sv": -2.0, "bac": 50.0, "bcwp": 22.0,
                          "bcws": 25.0, "completion_pct": 44.0, "health": "YELLOW"},
                "Bob": {"spi": 0.94, "sv": -1.0, "bac": 50.0, "bcwp": 24.0,
                        "bcws": 25.0, "completion_pct": 48.0, "health": "GREEN"},
            },
        },
        "dcma": {
            "score": 10, "total_checks": 14, "health": "YELLOW",
            "summary": "10/14 checks passed — YELLOW",
            "checks": [
                {"check_id": 1, "name": "Logic", "passed": True, "status": "PASS",
                 "violations": 0, "note": "All tasks have logic links"},
                {"check_id": 2, "name": "Leads", "passed": False, "status": "FAIL",
                 "violations": 2, "note": "2 tasks with negative lag"},
            ],
        },
        "milestones": [
            {"milestone_name": "CDR", "baseline_date": "2026-06-01",
             "p50_date": "2026-06-08", "p80_date": "2026-06-15",
             "p95_date": "2026-06-22", "prob_on_baseline": 0.72, "risk_level": "MEDIUM"},
        ],
        "cam_response_status": {
            "Alice": {"responded": True, "attempts": 1, "last_outcome": "completed"},
            "Bob": {"responded": False, "attempts": 2, "last_outcome": "no_answer"},
        },
        "tasks_behind": [
            {"task_id": "5", "cam_name": "Alice", "percent_complete": 40,
             "blocker": "Waiting for hardware"},
        ],
        "critical_path_task_ids": ["3", "7", "12", "15"],
        "completion_report": {"responded": 4, "total": 5},
    }


# ---------------------------------------------------------------------------
# generate_briefing
# ---------------------------------------------------------------------------


class TestGenerateBriefing:
    def test_returns_html_string(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state(), cycle_id="test-001")
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html

    def test_contains_health_label(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state())
        assert "YELLOW" in html

    def test_contains_cycle_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        state = _minimal_state()
        html = generate_briefing(state, cycle_id="CYCLE-XYZ")
        assert "CYCLE-XYZ" in html

    def test_saves_file_to_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        generate_briefing(_minimal_state(), cycle_id="save-test")
        briefing_file = tmp_path / "briefings" / "save-test_briefing.html"
        assert briefing_file.exists()

    def test_empty_state_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing({}, cycle_id="empty")
        assert "<!DOCTYPE html>" in html

    def test_spi_value_in_html(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state())
        assert "0.920" in html  # SPI formatted to 3 decimal places

    def test_dcma_checks_in_html(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state())
        assert "10/14" in html

    def test_milestone_table_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state())
        assert "CDR" in html

    def test_variance_narrative_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state())
        assert "schedule variance" in html.lower()

    def test_cam_status_table_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        html = generate_briefing(_minimal_state())
        assert "Alice" in html
        assert "Bob" in html


# ---------------------------------------------------------------------------
# _evm_kpi_cards
# ---------------------------------------------------------------------------


class TestEvmKpiCards:
    def test_returns_html_with_spi(self):
        program = {"spi": 0.95, "sv": 0.0, "completion_pct": 50.0,
                   "bei": 1.0, "bac": 100.0, "eac": 100.0, "vac": 0.0, "bcwp": 50.0}
        html = _evm_kpi_cards(program)
        assert "0.950" in html

    def test_behind_schedule_shows_red(self):
        program = {"spi": 0.80, "sv": -5.0, "completion_pct": 40.0,
                   "bei": 0.80, "bac": 100.0, "eac": 125.0, "vac": -25.0, "bcwp": 40.0}
        html = _evm_kpi_cards(program)
        assert "red" in html

    def test_empty_program_does_not_raise(self):
        html = _evm_kpi_cards({})
        assert "N/A" in html


# ---------------------------------------------------------------------------
# _dcma_section
# ---------------------------------------------------------------------------


class TestDcmaSection:
    def test_no_dcma_returns_fallback(self):
        html = _dcma_section({})
        assert "not available" in html.lower()

    def test_score_shown(self):
        dcma = {"score": 11, "total_checks": 14, "health": "GREEN",
                "summary": "11/14 — GREEN", "checks": []}
        html = _dcma_section(dcma)
        assert "11/14" in html

    def test_failed_check_shows_fail_class(self):
        dcma = {
            "score": 10, "total_checks": 14, "health": "YELLOW",
            "summary": "10/14", "checks": [
                {"check_id": 2, "name": "Leads", "passed": False, "status": "FAIL",
                 "violations": 2, "note": "2 leads"},
            ],
        }
        html = _dcma_section(dcma)
        assert "fail" in html.lower()


# ---------------------------------------------------------------------------
# _milestone_table
# ---------------------------------------------------------------------------


class TestMilestoneTable:
    def test_empty_returns_fallback(self):
        html = _milestone_table([])
        assert "not available" in html.lower()

    def test_milestone_name_shown(self):
        ms = [{"milestone_name": "PDR", "baseline_date": "2026-04-01",
               "p50_date": "2026-04-05", "p80_date": "2026-04-10",
               "p95_date": "2026-04-15", "prob_on_baseline": 0.85, "risk_level": "LOW"}]
        html = _milestone_table(ms)
        assert "PDR" in html

    def test_high_risk_gets_red_class(self):
        ms = [{"milestone_name": "CDR", "baseline_date": "2026-06-01",
               "p50_date": "2026-07-01", "p80_date": "2026-07-15",
               "p95_date": "2026-07-30", "prob_on_baseline": 0.30, "risk_level": "HIGH"}]
        html = _milestone_table(ms)
        assert "high" in html.lower()


# ---------------------------------------------------------------------------
# _cam_status_table
# ---------------------------------------------------------------------------


class TestCamStatusTable:
    def test_empty_returns_fallback(self):
        html = _cam_status_table({})
        assert "not available" in html.lower()

    def test_responded_cam_shown_with_checkmark(self):
        status = {"Alice": {"responded": True, "attempts": 1, "last_outcome": "completed"}}
        html = _cam_status_table(status)
        assert "Alice" in html
        assert "✓" in html

    def test_non_responding_cam_shown(self):
        status = {"Bob": {"responded": False, "attempts": 3, "last_outcome": "no_answer"}}
        html = _cam_status_table(status)
        assert "✗" in html


# ---------------------------------------------------------------------------
# _esc
# ---------------------------------------------------------------------------


class TestEsc:
    def test_escapes_angle_brackets(self):
        assert _esc("<script>") == "&lt;script&gt;"

    def test_escapes_ampersand(self):
        assert _esc("A&B") == "A&amp;B"

    def test_escapes_quotes(self):
        assert _esc('"hello"') == "&quot;hello&quot;"

    def test_plain_text_unchanged(self):
        assert _esc("Hello world") == "Hello world"
