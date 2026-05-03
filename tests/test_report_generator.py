"""
Tests for agent.report_generator — Markdown report generation.

Covers 1.8 checklist items:
- Report contains all required sections
- No missing data placeholders when data is provided
- Report file is saved to the correct path
"""

import os
from datetime import datetime
from pathlib import Path
import pytest


_REPORT_DATE = datetime(2026, 4, 25, 9, 0, 0)

_REQUIRED_SECTIONS = [
    "## Executive Summary",
    "## Critical Path",
    "## Milestone Risk Summary",
    "## Top 5 Risks",
    "## Tasks Behind Schedule",
    "## Recommended Actions for PM",
]


def _sample_tasks():
    from datetime import timedelta
    base = datetime(2026, 1, 5)
    return [
        {
            "task_id": "1", "name": "Task Alpha", "start": base,
            "finish": base + timedelta(days=20), "percent_complete": 100,
            "predecessors": [], "cam": "Alice Nguyen", "is_milestone": False,
            "duration_days": 20, "baseline_start": base,
            "baseline_finish": base + timedelta(days=20), "notes": "",
        },
        {
            "task_id": "2", "name": "Task Beta", "start": base + timedelta(days=20),
            "finish": base + timedelta(days=40), "percent_complete": 30,
            "predecessors": ["1"], "cam": "Bob Martinez", "is_milestone": False,
            "duration_days": 20, "baseline_start": base + timedelta(days=20),
            "baseline_finish": base + timedelta(days=40), "notes": "",
        },
    ]


def _sample_cp_result():
    return {
        "critical_path": ["1", "2"],
        "total_float": {"1": 0.0, "2": 0.0},
        "near_critical": [],
        "changed_on": [],
        "changed_off": [],
        "projected_finish": datetime(2026, 2, 14),
    }


def _sample_sra():
    return [
        {
            "task_id": "M1",
            "milestone_name": "PDR Complete",
            "baseline_date": "2026-05-29",
            "p50_date": "2026-06-05",
            "p80_date": "2026-06-12",
            "p95_date": "2026-06-19",
            "prob_on_baseline": 0.38,
            "risk_level": "HIGH",
        }
    ]


def _sample_cam_inputs():
    return [
        {
            "task_id": "2",
            "cam_name": "Bob Martinez",
            "percent_complete": 30,
            "blocker": "Waiting on parts",
            "risk_flag": True,
            "risk_description": "Supplier delay",
            "timestamp": "2026-04-25T09:00:00",
        }
    ]


def _sample_synthesis():
    return {
        "schedule_health": "YELLOW",
        "narrative": "The program is progressing with some concerns.\n\nTask Beta is behind schedule.",
        "top_risks": "1. Supplier delay affecting Task Beta\n2. PDR milestone at risk",
        "recommended_actions": "1. Expedite parts order\n2. Schedule PDR risk review",
        "raw": "",
    }


class TestReportGenerator:
    def test_all_required_sections_present(self, tmp_path):
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _sample_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE
        )

        content = Path(report_path).read_text(encoding="utf-8")
        for section in _REQUIRED_SECTIONS:
            assert section in content, f"Missing required section: {section!r}"

    def test_report_saved_to_correct_path(self, tmp_path):
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _sample_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE
        )

        expected_name = "2026-04-25_ims_report.md"
        assert Path(report_path).name == expected_name
        assert Path(report_path).exists()

    def test_schedule_health_in_report(self, tmp_path):
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _sample_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE
        )
        content = Path(report_path).read_text(encoding="utf-8")
        assert "YELLOW" in content

    def test_report_contains_milestone_data(self, tmp_path):
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _sample_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE
        )
        content = Path(report_path).read_text(encoding="utf-8")
        assert "PDR Complete" in content
        assert "HIGH" in content

    def test_report_contains_blocker(self, tmp_path):
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _sample_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE
        )
        content = Path(report_path).read_text(encoding="utf-8")
        assert "Waiting on parts" in content


# ---------------------------------------------------------------------------
# TD-007 — _truncate_blocker helper (unit tests)
# ---------------------------------------------------------------------------

class TestTruncateBlockerHelper:
    """Direct tests for the _truncate_blocker helper function."""

    def test_empty_string_returns_unchanged(self):
        from agent.report_generator import _truncate_blocker
        assert _truncate_blocker("") == ("", False)

    def test_short_string_not_truncated(self):
        from agent.report_generator import _truncate_blocker
        text = "Waiting on parts"
        result, was_truncated = _truncate_blocker(text)
        assert result == text
        assert was_truncated is False

    def test_sentence_boundary_truncation(self):
        from agent.report_generator import _truncate_blocker
        text = "First sentence. " + "x" * 200
        result, was_truncated = _truncate_blocker(text)
        assert was_truncated is True
        assert result == "First sentence.*"

    def test_exclamation_boundary_truncation(self):
        from agent.report_generator import _truncate_blocker
        text = "Critical failure! " + "y" * 200
        result, was_truncated = _truncate_blocker(text)
        assert was_truncated is True
        assert result == "Critical failure!*"

    def test_hard_truncation_when_no_sentence_boundary(self):
        from agent.report_generator import _truncate_blocker
        text = "x" * 200
        result, was_truncated = _truncate_blocker(text, max_len=120)
        assert was_truncated is True
        assert result.endswith("…*")
        # 120 source chars + "…" (1 char) + "*" (1 char) = 122
        assert len(result) <= 122

    def test_exactly_max_len_not_truncated(self):
        from agent.report_generator import _truncate_blocker
        text = "x" * 120
        result, was_truncated = _truncate_blocker(text, max_len=120)
        assert result == text
        assert was_truncated is False


# ---------------------------------------------------------------------------
# TD-007 — integration: blockers in generated report
# ---------------------------------------------------------------------------

def _long_blocker_cam_inputs():
    """CAM input with a blocker long enough to trigger truncation."""
    return [
        {
            "task_id": "2",
            "cam_name": "Bob Martinez",
            "percent_complete": 30,
            "blocker": "x" * 200,
            "risk_flag": False,
            "risk_description": "",
            "timestamp": "2026-04-25T09:00:00",
        }
    ]


def _sentence_blocker_cam_inputs():
    """CAM input with a blocker that has a sentence boundary mid-way."""
    return [
        {
            "task_id": "2",
            "cam_name": "Bob Martinez",
            "percent_complete": 30,
            "blocker": "First sentence. " + "Much longer explanation " * 10,
            "risk_flag": False,
            "risk_description": "",
            "timestamp": "2026-04-25T09:00:00",
        }
    ]


class TestBlockerTruncationIntegration:
    """TD-007 — blocker truncation and appendix in generated reports."""

    def test_long_blocker_creates_appendix_section(self, tmp_path):
        """A blocker > 120 chars with no sentence boundary creates a Blocker Details appendix."""
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _long_blocker_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE,
        )
        content = Path(report_path).read_text(encoding="utf-8")
        assert "## Blocker Details" in content

    def test_full_blocker_text_appears_in_appendix(self, tmp_path):
        """The complete blocker text appears somewhere in the report (inside the appendix)."""
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        inputs = _sentence_blocker_cam_inputs()
        full_blocker = inputs[0]["blocker"]

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            inputs, _sample_synthesis(), report_date=_REPORT_DATE,
        )
        content = Path(report_path).read_text(encoding="utf-8")
        assert full_blocker in content

    def test_short_blocker_produces_no_appendix(self, tmp_path):
        """A short blocker (≤120 chars) does not create a Blocker Details appendix."""
        from agent.report_generator import ReportGenerator
        import os
        os.environ["REPORTS_DIR"] = str(tmp_path)

        rg = ReportGenerator()
        report_path = rg.generate(
            _sample_tasks(), _sample_cp_result(), _sample_sra(),
            _sample_cam_inputs(), _sample_synthesis(), report_date=_REPORT_DATE,
        )
        content = Path(report_path).read_text(encoding="utf-8")
        assert "## Blocker Details" not in content
        assert "Waiting on parts" in content
