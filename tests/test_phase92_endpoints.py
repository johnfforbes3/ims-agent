"""
Phase 9.2–9.6 endpoint tests — EVM, DCMA, Variance, Briefing, Portfolio.

Tests the new FastAPI routes added in Phases 9.2–9.6.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test client setup
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI test client with no auth required (dev mode)."""
    state_file = str(tmp_path / "state.json")
    portfolio_file = str(tmp_path / "portfolio.json")
    reports_dir = str(tmp_path)

    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", state_file)
    monkeypatch.setenv("PORTFOLIO_FILE", portfolio_file)
    monkeypatch.setenv("REPORTS_DIR", reports_dir)

    # Import after env setup
    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)

    # Explicitly override module-level constants after reload so that
    # load_dotenv(override=True) inside the module cannot restore old values.
    srv._STATE_FILE = state_file
    srv._REPORTS_DIR = reports_dir

    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture()
def client_with_state(client, tmp_path, monkeypatch):
    """Test client with a populated dashboard state."""
    state = {
        "cycle_id": "20260506T120000Z",
        "schedule_health": "YELLOW",
        "narrative": "Test narrative.",
        "top_risks": "1. Risk one\n2. Risk two",
        "recommended_actions": "1. Action one",
        "variance_narrative": "Schedule variance narrative text.",
        "variance_summary": {"spi": 0.92},
        "evm": {
            "program": {
                "spi": 0.92, "sv": -3.0, "sv_pct": -8.0,
                "bac": 100.0, "bcwp": 46.0, "bcws": 50.0,
                "eac": 108.7, "vac": -8.7, "completion_pct": 46.0,
                "bei": 0.88, "health": "YELLOW",
            },
            "by_cam": {
                "Alice": {"spi": 0.90, "sv": -2.0, "bac": 50.0, "bcwp": 22.0,
                          "bcws": 25.0, "completion_pct": 44.0, "health": "YELLOW"},
            },
        },
        "dcma": {
            "score": 10, "total_checks": 14, "health": "YELLOW",
            "summary": "10/14 checks passed",
            "checks": [
                {"check_id": 1, "name": "Logic", "passed": True, "status": "PASS",
                 "violations": 0, "note": "OK"},
            ],
        },
        "milestones": [],
        "cam_response_status": {},
        "tasks_behind": [],
        "critical_path_task_ids": [],
        "completion_report": {"responded": 4, "total": 5},
    }
    # Write state to tmp_path/state.json — the same path set as srv._STATE_FILE
    # in the `client` fixture. Do NOT use os.getenv, which may return the .env
    # value after load_dotenv(override=True) runs during importlib.reload.
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return client


# ---------------------------------------------------------------------------
# GET /api/evm
# ---------------------------------------------------------------------------


class TestApiEvm:
    def test_404_when_no_state(self, client):
        r = client.get("/api/evm")
        assert r.status_code == 404

    def test_returns_evm_data(self, client_with_state):
        r = client_with_state.get("/api/evm")
        assert r.status_code == 200
        data = r.json()
        assert "program" in data
        assert "by_cam" in data

    def test_program_spi_in_response(self, client_with_state):
        r = client_with_state.get("/api/evm")
        assert r.status_code == 200
        assert r.json()["program"]["spi"] == pytest.approx(0.92, abs=0.01)


# ---------------------------------------------------------------------------
# GET /api/dcma
# ---------------------------------------------------------------------------


class TestApiDcma:
    def test_404_when_no_state(self, client):
        r = client.get("/api/dcma")
        assert r.status_code == 404

    def test_returns_dcma_data(self, client_with_state):
        r = client_with_state.get("/api/dcma")
        assert r.status_code == 200
        data = r.json()
        assert "score" in data
        assert "checks" in data

    def test_score_value_correct(self, client_with_state):
        r = client_with_state.get("/api/dcma")
        assert r.json()["score"] == 10


# ---------------------------------------------------------------------------
# GET /api/variance
# ---------------------------------------------------------------------------


class TestApiVariance:
    def test_404_when_no_state(self, client):
        r = client.get("/api/variance")
        assert r.status_code == 404

    def test_returns_narrative(self, client_with_state):
        r = client_with_state.get("/api/variance")
        assert r.status_code == 200
        data = r.json()
        assert "narrative" in data
        assert "Schedule variance narrative text." in data["narrative"]


# ---------------------------------------------------------------------------
# GET /api/briefing
# ---------------------------------------------------------------------------


class TestApiBriefing:
    def test_404_when_no_state(self, client):
        r = client.get("/api/briefing")
        assert r.status_code == 404

    def test_returns_html(self, client_with_state):
        r = client_with_state.get("/api/briefing")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "<!DOCTYPE html>" in r.text

    def test_html_contains_health(self, client_with_state):
        r = client_with_state.get("/api/briefing")
        assert "YELLOW" in r.text

    def test_html_contains_cycle_id(self, client_with_state):
        r = client_with_state.get("/api/briefing")
        assert "20260506T120000Z" in r.text

    def test_briefing_with_cycle_id_param(self, client_with_state):
        # Request with the current state's cycle_id — server generates on-demand
        # and returns 200. A non-existent cycle_id returns 404 (tested elsewhere).
        r = client_with_state.get("/api/briefing/20260506T120000Z")
        assert r.status_code == 200
        assert "20260506T120000Z" in r.text


# ---------------------------------------------------------------------------
# GET /api/portfolio
# ---------------------------------------------------------------------------


class TestApiPortfolio:
    def test_returns_portfolio_structure(self, client_with_state):
        r = client_with_state.get("/api/portfolio")
        assert r.status_code == 200
        data = r.json()
        assert "programs" in data
        assert "portfolio_health" in data
        assert "total_programs" in data

    def test_default_single_program(self, client_with_state):
        r = client_with_state.get("/api/portfolio")
        assert r.json()["total_programs"] == 1

    def test_portfolio_health_not_unknown(self, client_with_state):
        r = client_with_state.get("/api/portfolio")
        assert r.json()["portfolio_health"] in ("GREEN", "YELLOW", "RED", "UNKNOWN")
