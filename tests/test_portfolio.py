"""
Tests for agent/portfolio.py — Portfolio View / Multi-Program Aggregation.

Phase 9.6: Portfolio View
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from agent.portfolio import (
    get_portfolio,
    register_program,
    deregister_program,
    _build_program_summary,
    _aggregate_health,
    _load_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_state(health="GREEN", spi=1.02, completion=55.0, cycle_id="C1"):
    return {
        "schedule_health": health,
        "cycle_id": cycle_id,
        "last_updated": "2026-05-06T12:00:00+00:00",
        "evm": {
            "program": {
                "spi": spi, "sv": 1.0, "completion_pct": completion,
                "bei": 0.97, "bac": 100.0, "bcwp": 55.0, "bcws": 53.0,
                "eac": 98.0, "vac": 2.0,
            }
        },
        "dcma": {"score": 11, "total_checks": 14, "health": "GREEN"},
        "milestones": [
            {"milestone_name": "CDR", "risk_level": "LOW", "prob_on_baseline": 0.90},
        ],
        "completion_report": {"responded": 4, "total": 5},
        "top_risks": "1. Integration risk\n2. Resource availability",
    }


# ---------------------------------------------------------------------------
# _aggregate_health
# ---------------------------------------------------------------------------


class TestAggregateHealth:
    def test_all_green(self):
        assert _aggregate_health(["GREEN", "GREEN", "GREEN"]) == "GREEN"

    def test_any_red(self):
        assert _aggregate_health(["GREEN", "RED", "YELLOW"]) == "RED"

    def test_mixed_no_red(self):
        assert _aggregate_health(["GREEN", "YELLOW"]) == "YELLOW"

    def test_empty_returns_unknown(self):
        assert _aggregate_health([]) == "UNKNOWN"

    def test_single_yellow(self):
        assert _aggregate_health(["YELLOW"]) == "YELLOW"


# ---------------------------------------------------------------------------
# _load_state
# ---------------------------------------------------------------------------


class TestLoadState:
    def test_existing_file_loaded(self, tmp_path):
        state = {"schedule_health": "GREEN", "cycle_id": "test"}
        f = tmp_path / "state.json"
        f.write_text(json.dumps(state), encoding="utf-8")
        result = _load_state(str(f))
        assert result["schedule_health"] == "GREEN"

    def test_missing_file_returns_empty(self, tmp_path):
        result = _load_state(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{bad json}", encoding="utf-8")
        result = _load_state(str(f))
        assert result == {}


# ---------------------------------------------------------------------------
# _build_program_summary
# ---------------------------------------------------------------------------


class TestBuildProgramSummary:
    def test_returns_expected_keys(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(_make_state()), encoding="utf-8")
        entry = {"program_id": "p1", "name": "Prog A", "state_file": str(state_file)}
        summary = _build_program_summary(entry)
        assert "program_id" in summary
        assert "name" in summary
        assert "health" in summary
        assert "spi" in summary
        assert "dcma_score" in summary

    def test_health_from_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(_make_state(health="RED")), encoding="utf-8")
        entry = {"program_id": "p1", "name": "Prog A", "state_file": str(state_file)}
        summary = _build_program_summary(entry)
        assert summary["health"] == "RED"

    def test_missing_state_returns_unknown_health(self, tmp_path):
        entry = {
            "program_id": "p99", "name": "Missing",
            "state_file": str(tmp_path / "noexist.json")
        }
        summary = _build_program_summary(entry)
        assert summary["health"] == "UNKNOWN"
        assert summary["is_active"] is False

    def test_spi_populated(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(_make_state(spi=0.88)), encoding="utf-8")
        entry = {"program_id": "p1", "name": "Prog A", "state_file": str(state_file)}
        summary = _build_program_summary(entry)
        assert summary["spi"] == pytest.approx(0.88, abs=0.01)

    def test_dcma_score_formatted(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(_make_state()), encoding="utf-8")
        entry = {"program_id": "p1", "name": "Prog A", "state_file": str(state_file)}
        summary = _build_program_summary(entry)
        assert summary["dcma_score"] == "11/14"

    def test_high_risk_milestones_counted(self, tmp_path):
        state = _make_state()
        state["milestones"] = [
            {"milestone_name": "M1", "risk_level": "HIGH"},
            {"milestone_name": "M2", "risk_level": "HIGH"},
            {"milestone_name": "M3", "risk_level": "LOW"},
        ]
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        entry = {"program_id": "p1", "name": "Prog A", "state_file": str(state_file)}
        summary = _build_program_summary(entry)
        assert summary["milestones_high_risk"] == 2

    def test_top_risk_preview_truncated(self, tmp_path):
        state = _make_state()
        state["top_risks"] = "1. " + "A" * 200 + "\n2. Risk two"
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        entry = {"program_id": "p1", "name": "Prog A", "state_file": str(state_file)}
        summary = _build_program_summary(entry)
        assert len(summary["top_risk_preview"]) <= 120


# ---------------------------------------------------------------------------
# get_portfolio
# ---------------------------------------------------------------------------


class TestGetPortfolio:
    def test_returns_expected_keys(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(tmp_path / "state.json"))
        # Create a state file
        (tmp_path / "state.json").write_text(json.dumps(_make_state()), encoding="utf-8")
        result = get_portfolio()
        assert "programs" in result
        assert "portfolio_health" in result
        assert "total_programs" in result
        assert "programs_at_risk" in result

    def test_default_single_program_when_no_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "noportfolio.json"))
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(tmp_path / "state.json"))
        (tmp_path / "state.json").write_text(json.dumps(_make_state(health="GREEN")), encoding="utf-8")
        result = get_portfolio()
        assert result["total_programs"] == 1

    def test_portfolio_health_reflects_worst_program(self, tmp_path, monkeypatch):
        # Two programs: one GREEN, one RED → portfolio RED
        state1 = tmp_path / "state1.json"
        state2 = tmp_path / "state2.json"
        state1.write_text(json.dumps(_make_state(health="GREEN")), encoding="utf-8")
        state2.write_text(json.dumps(_make_state(health="RED")), encoding="utf-8")

        portfolio = [
            {"program_id": "p1", "name": "Alpha", "state_file": str(state1)},
            {"program_id": "p2", "name": "Beta", "state_file": str(state2)},
        ]
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps(portfolio), encoding="utf-8")

        monkeypatch.setenv("PORTFOLIO_FILE", str(pf))
        result = get_portfolio()
        assert result["portfolio_health"] == "RED"

    def test_programs_at_risk_count(self, tmp_path, monkeypatch):
        state1 = tmp_path / "s1.json"
        state2 = tmp_path / "s2.json"
        state3 = tmp_path / "s3.json"
        state1.write_text(json.dumps(_make_state(health="RED")), encoding="utf-8")
        state2.write_text(json.dumps(_make_state(health="YELLOW")), encoding="utf-8")
        state3.write_text(json.dumps(_make_state(health="GREEN")), encoding="utf-8")
        portfolio = [
            {"program_id": "p1", "name": "A", "state_file": str(state1)},
            {"program_id": "p2", "name": "B", "state_file": str(state2)},
            {"program_id": "p3", "name": "C", "state_file": str(state3)},
        ]
        pf = tmp_path / "pf.json"
        pf.write_text(json.dumps(portfolio), encoding="utf-8")
        monkeypatch.setenv("PORTFOLIO_FILE", str(pf))
        result = get_portfolio()
        assert result["programs_at_risk"] == 2


# ---------------------------------------------------------------------------
# register_program / deregister_program
# ---------------------------------------------------------------------------


class TestRegisterDeregister:
    def test_register_creates_entry(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        monkeypatch.setenv("PORTFOLIO_FILE", str(pf))
        ok = register_program("prog-1", "Test Prog", "data/state.json", "desc")
        assert ok
        data = json.loads(pf.read_text())
        assert any(p["program_id"] == "prog-1" for p in data)

    def test_register_updates_existing(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps([{"program_id": "p1", "name": "Old Name",
                                    "state_file": "x", "description": ""}]))
        monkeypatch.setenv("PORTFOLIO_FILE", str(pf))
        register_program("p1", "New Name", "x", "")
        data = json.loads(pf.read_text())
        assert data[0]["name"] == "New Name"
        assert len(data) == 1

    def test_deregister_removes_entry(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps([{"program_id": "p1", "name": "A", "state_file": "x", "description": ""}]))
        monkeypatch.setenv("PORTFOLIO_FILE", str(pf))
        ok = deregister_program("p1")
        assert ok
        data = json.loads(pf.read_text())
        assert data == []

    def test_deregister_not_found_returns_false(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps([]))
        monkeypatch.setenv("PORTFOLIO_FILE", str(pf))
        ok = deregister_program("nonexistent")
        assert not ok
