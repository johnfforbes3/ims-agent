"""
Tests for agent/variance_analyst.py — Variance Analysis Narrative Generator.

Phase 9.4: Variance Analysis Narratives
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest
from agent.variance_analyst import (
    generate_variance_narrative,
    _build_variance_summary,
    _build_context,
    _fallback_narrative,
)

REF_DATE = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_evm(spi=0.92, sv=-3.0, sv_pct=-8.0, bac=100.0, bcwp=46.0, bcws=50.0,
              eac=108.7, vac=-8.7, completion_pct=46.0, bei=0.88):
    return {
        "program": {
            "spi": spi,
            "sv": sv,
            "sv_pct": sv_pct,
            "bac": bac,
            "bcwp": bcwp,
            "bcws": bcws,
            "eac": eac,
            "vac": vac,
            "completion_pct": completion_pct,
            "bei": bei,
        },
        "by_cam": {
            "Alice": {"spi": 0.90, "sv": -2.0, "bac": 50.0},
            "Bob": {"spi": 0.95, "sv": -1.0, "bac": 50.0},
        },
    }


def _make_cam_inputs(with_blocker=True, with_risk=True):
    inputs = []
    if with_blocker:
        inputs.append({
            "task_id": "5",
            "cam_name": "Alice",
            "percent_complete": 40,
            "blocker": "Waiting for vendor delivery of avionics components",
            "risk_flag": False,
            "risk_description": "",
        })
    if with_risk:
        inputs.append({
            "task_id": "7",
            "cam_name": "Bob",
            "percent_complete": 60,
            "blocker": "",
            "risk_flag": True,
            "risk_description": "Integration complexity higher than planned",
        })
    return inputs


def _make_tasks(count=10):
    now = REF_DATE
    tasks = []
    for i in range(count):
        tasks.append({
            "task_id": str(i),
            "name": f"Task {i}",
            "cam": "Alice" if i % 2 == 0 else "Bob",
            "duration_days": 5.0,
            "percent_complete": 50,
            "start": now - timedelta(days=5),
            "finish": now + timedelta(days=5),
            "is_milestone": False,
        })
    return tasks


# ---------------------------------------------------------------------------
# generate_variance_narrative
# ---------------------------------------------------------------------------


class TestGenerateVarianceNarrative:
    def test_returns_expected_keys(self):
        with patch("agent.variance_analyst.LLMInterface") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ask.return_value = "This is the variance narrative."
            mock_llm_cls.return_value = mock_llm

            result = generate_variance_narrative(
                tasks=_make_tasks(),
                cam_inputs=_make_cam_inputs(),
                evm_summary=_make_evm(),
                cycle_id="20260506T120000Z",
            )

        assert "narrative" in result
        assert "variance_summary" in result
        assert "generated_at" in result
        assert "cycle_id" in result

    def test_narrative_populated_from_llm(self):
        with patch("agent.variance_analyst.LLMInterface") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ask.return_value = "Program is behind schedule due to vendor delays."
            mock_llm_cls.return_value = mock_llm

            result = generate_variance_narrative(
                tasks=_make_tasks(),
                cam_inputs=_make_cam_inputs(),
                evm_summary=_make_evm(),
                cycle_id="test-cycle",
            )

        assert result["narrative"] == "Program is behind schedule due to vendor delays."

    def test_llm_failure_falls_back_gracefully(self):
        with patch("agent.variance_analyst.LLMInterface") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ask.side_effect = RuntimeError("LLM unavailable")
            mock_llm_cls.return_value = mock_llm

            result = generate_variance_narrative(
                tasks=_make_tasks(),
                cam_inputs=_make_cam_inputs(),
                evm_summary=_make_evm(),
                cycle_id="test-cycle",
            )

        # Fallback narrative should be returned
        assert result["narrative"]
        assert len(result["narrative"]) > 10

    def test_cycle_id_in_result(self):
        with patch("agent.variance_analyst.LLMInterface") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ask.return_value = "Narrative text."
            mock_llm_cls.return_value = mock_llm

            result = generate_variance_narrative(
                tasks=[], cam_inputs=[], evm_summary=_make_evm(), cycle_id="ABC123"
            )

        assert result["cycle_id"] == "ABC123"

    def test_variance_summary_includes_spi(self):
        with patch("agent.variance_analyst.LLMInterface") as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ask.return_value = "text"
            mock_llm_cls.return_value = mock_llm

            result = generate_variance_narrative(
                tasks=_make_tasks(),
                cam_inputs=_make_cam_inputs(),
                evm_summary=_make_evm(spi=0.85),
                cycle_id="test",
            )

        assert result["variance_summary"]["spi"] == 0.85


# ---------------------------------------------------------------------------
# _build_variance_summary
# ---------------------------------------------------------------------------


class TestBuildVarianceSummary:
    def test_returns_spi_from_evm(self):
        summary = _build_variance_summary(
            tasks=_make_tasks(),
            cam_inputs=_make_cam_inputs(),
            evm_summary=_make_evm(spi=0.91),
            dcma_result=None,
        )
        assert summary["spi"] == 0.91

    def test_blocker_count_correct(self):
        summary = _build_variance_summary(
            tasks=_make_tasks(),
            cam_inputs=_make_cam_inputs(with_blocker=True, with_risk=False),
            evm_summary=_make_evm(),
            dcma_result=None,
        )
        assert summary["blocker_count"] == 1

    def test_risk_flag_count_correct(self):
        summary = _build_variance_summary(
            tasks=_make_tasks(),
            cam_inputs=_make_cam_inputs(with_blocker=False, with_risk=True),
            evm_summary=_make_evm(),
            dcma_result=None,
        )
        assert summary["risk_flag_count"] == 1

    def test_worst_cams_sorted_by_spi(self):
        evm = _make_evm()
        evm["by_cam"] = {
            "Alice": {"spi": 0.70},
            "Bob": {"spi": 0.95},
            "Carol": {"spi": 0.80},
        }
        summary = _build_variance_summary(_make_tasks(), [], evm, None)
        spis = [c["spi"] for c in summary["worst_performing_cams"]]
        assert spis == sorted(spis)  # ascending (worst first)

    def test_dcma_score_included(self):
        dcma = {"score": 10, "total_checks": 14, "health": "YELLOW"}
        summary = _build_variance_summary(_make_tasks(), [], _make_evm(), dcma)
        assert summary["dcma_score"] == "10/14"
        assert summary["dcma_health"] == "YELLOW"

    def test_empty_cam_inputs(self):
        summary = _build_variance_summary(_make_tasks(), [], _make_evm(), None)
        assert summary["blocker_count"] == 0
        assert summary["risk_flag_count"] == 0


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_context_contains_spi(self):
        vs = {
            "spi": 0.88, "sv_work_days": -5.0, "sv_pct": -10.0,
            "bac_work_days": 100.0, "bcwp_work_days": 40.0, "bcws_work_days": 45.0,
            "eac_work_days": 113.6, "vac_work_days": -13.6,
            "program_completion_pct": 40.0, "bei": 0.90,
            "worst_performing_cams": [], "blockers": [], "risks": [],
            "dcma_score": None, "dcma_health": None,
        }
        context = _build_context(vs, [], None)
        assert "0.88" in context

    def test_blockers_in_context(self):
        vs = {
            "spi": 1.0, "sv_work_days": 0, "sv_pct": 0,
            "bac_work_days": 100, "bcwp_work_days": 50, "bcws_work_days": 50,
            "eac_work_days": 100, "vac_work_days": 0,
            "program_completion_pct": 50, "bei": 1.0,
            "worst_performing_cams": [],
            "blockers": [{"cam": "Alice", "task_id": "5", "detail": "Waiting for hardware"}],
            "risks": [],
            "dcma_score": None, "dcma_health": None,
        }
        context = _build_context(vs, [], None)
        assert "Waiting for hardware" in context

    def test_ims_diff_changes_in_context(self):
        vs = {
            "spi": 1.0, "sv_work_days": 0, "sv_pct": 0,
            "bac_work_days": 100, "bcwp_work_days": 50, "bcws_work_days": 50,
            "eac_work_days": 100, "vac_work_days": 0,
            "program_completion_pct": 50, "bei": 1.0,
            "worst_performing_cams": [], "blockers": [], "risks": [],
            "dcma_score": None, "dcma_health": None,
        }
        diff = {"changes": [
            {"task_name": "Integration Test", "cam": "Alice",
             "old_percent_complete": 30, "new_percent_complete": 50}
        ]}
        context = _build_context(vs, [], diff)
        assert "Integration Test" in context
        assert "30%" in context


# ---------------------------------------------------------------------------
# _fallback_narrative
# ---------------------------------------------------------------------------


class TestFallbackNarrative:
    def test_behind_schedule_says_behind(self):
        summary = {
            "spi": 0.88, "sv_work_days": -4.0, "program_completion_pct": 35.0,
            "blocker_count": 2
        }
        text = _fallback_narrative(summary)
        assert "behind" in text.lower()

    def test_ahead_of_schedule(self):
        summary = {
            "spi": 1.10, "sv_work_days": 3.0, "program_completion_pct": 55.0,
            "blocker_count": 0
        }
        text = _fallback_narrative(summary)
        assert "ahead" in text.lower()

    def test_none_spi_returns_graceful(self):
        summary = {"spi": None, "sv_work_days": 0, "program_completion_pct": 25.0, "blocker_count": 0}
        text = _fallback_narrative(summary)
        assert "insufficient" in text.lower() or "25" in text
