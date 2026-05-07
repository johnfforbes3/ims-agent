"""
Integration smoke tests: all API endpoints with a realistic state fixture.

Uses a state file that matches the schema a real completed cycle produces.
Verifies:
  ✓ GET /api/evm  — 200, correct top-level keys, SPI numeric
  ✓ GET /api/dcma — 200, score/health/checks present and valid
  ✓ GET /api/variance — 200, all 5 CPR sections present
  ✓ GET /api/briefing — 200 HTML, contains EVM table / DCMA score / CAM names
  ✓ GET /api/briefing/{cycle_id} — 200 for saved briefing; 404 for unknown ID
  ✓ GET /api/portfolio — 200 with correct shape
  ✓ POST /api/trigger — 200 "triggered"; 409 when already active
  ✓ GET /api/status — returns cycle_active bool
  ✓ GET / (dashboard HTML) — 200, contains all Phase 9 panel markers
  ✓ 404 responses when state file is absent or lacks the requested key
  ✓ Briefing saved to disk after GET /api/briefing
"""

import json
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Realistic state fixture
# ---------------------------------------------------------------------------

_STATE = {
    "cycle_id": "20260507T100000Z",
    "timestamp": "2026-05-07T10:00:00Z",
    "health": "YELLOW",
    "summary": "Schedule YELLOW. SPI=0.91. 3 tasks behind with blockers.",
    "top_risks": [
        "SE-04 hardware vendor delay (critical path impact)",
        "NET-12 firewall config blocked by approval process",
    ],
    "cams_responded": 4,
    "cams_total": 5,
    "tasks_behind_with_blockers": [
        {"task_id": "SE-04", "cam": "Alice Nguyen", "pct": 40,
         "blocker": "Vendor part delivery delayed 2 weeks"}
    ],
    "critical_path_task_ids": ["SE-01", "SE-04", "INT-02"],
    "project_float_days": 2.0,
    "milestones": [
        {
            "milestone_name": "PDR",
            "baseline_date": "2026-06-15",
            "p50_date": "2026-06-20",
            "p80_date": "2026-06-28",
            "p95_date": "2026-07-05",
            "prob_on_baseline": 0.35,
            "risk_level": "HIGH",
        },
        {
            "milestone_name": "CDR",
            "baseline_date": "2026-08-20",
            "p50_date": "2026-08-22",
            "p80_date": "2026-08-28",
            "p95_date": "2026-09-04",
            "prob_on_baseline": 0.90,
            "risk_level": "LOW",
        },
    ],
    "validation_holds": [],
    # Phase 10 clean API keys
    "cam_status": {
        "Alice Nguyen":  {"responded": True,  "tasks_updated": 6,  "blockers": 1},
        "Bob Martinez":  {"responded": False, "tasks_updated": 0,  "blockers": 0},
        "Carol Smith":   {"responded": True,  "tasks_updated": 7,  "blockers": 0},
        "David Lee":     {"responded": True,  "tasks_updated": 7,  "blockers": 0},
        "Eva Johnson":   {"responded": True,  "tasks_updated": 15, "blockers": 2},
    },
    # Legacy keys used by dashboard Jinja2 template
    "schedule_health": "YELLOW",
    "narrative": "Schedule YELLOW. SPI=0.91. 3 tasks behind with blockers.",
    "cam_response_status": {
        "Alice Nguyen":  {"responded": True,  "attempts": 1, "last_outcome": "completed"},
        "Bob Martinez":  {"responded": False, "attempts": 1, "last_outcome": "no_answer"},
        "Carol Smith":   {"responded": True,  "attempts": 1, "last_outcome": "completed"},
        "David Lee":     {"responded": True,  "attempts": 1, "last_outcome": "completed"},
        "Eva Johnson":   {"responded": True,  "attempts": 1, "last_outcome": "completed"},
    },
    "evm": {
        "as_of": "2026-05-07",
        "program": {
            "BAC": 500.0, "BCWP": 210.0, "BCWS": 230.0,
            "SPI": 0.913, "SV": -20.0, "SV_pct": -8.7,
            "EAC": 548.0, "VAC": -48.0, "TCPI": 1.08, "BEI": 0.95,
        },
        "by_cam": {
            "Alice Nguyen": {
                "BAC": 80.0, "BCWP": 68.0, "BCWS": 72.0,
                "SPI": 0.944, "SV": -4.0, "EAC": 84.7
            },
            "Carol Smith": {
                "BAC": 95.0, "BCWP": 40.0, "BCWS": 42.0,
                "SPI": 0.952, "SV": -2.0, "EAC": 99.8
            },
        },
        "task_detail": [],
    },
    "dcma": {
        "overall_health": "YELLOW",
        "score": 10,
        "max_score": 14,
        "as_of": "2026-05-07T10:00:00Z",
        "checks": [
            {"id": "01", "name": "Logic", "passed": True,
             "pct": 0.0, "threshold_pct": 5.0, "violations": 0, "flagged": []},
            {"id": "02", "name": "Leads", "passed": True,
             "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "03", "name": "Lags", "passed": False,
             "pct": 8.0, "threshold_pct": 5.0, "violations": 7, "flagged": ["SE-04"]},
            {"id": "04", "name": "FS relationships", "passed": True,
             "pct": 85.0, "threshold_pct": 90.0, "violations": 0, "flagged": []},
            {"id": "05", "name": "Hard constraints", "passed": False,
             "pct": 6.0, "threshold_pct": 5.0, "violations": 5, "flagged": ["PROG-01"]},
            {"id": "06", "name": "High float", "passed": True,
             "pct": 2.0, "threshold_pct": 5.0, "violations": 2, "flagged": []},
            {"id": "07", "name": "Negative float", "passed": True,
             "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "08", "name": "High duration", "passed": True,
             "pct": 3.0, "threshold_pct": 5.0, "violations": 3, "flagged": []},
            {"id": "09", "name": "Invalid dates", "passed": True,
             "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "10", "name": "Resources", "passed": True,
             "pct": 0.0, "threshold_pct": 5.0, "violations": 0, "flagged": []},
            {"id": "11", "name": "Missed baseline", "passed": False,
             "pct": 10.0, "threshold_pct": 5.0, "violations": 9, "flagged": []},
            {"id": "12", "name": "Critical path", "passed": True,
             "pct": 15.0, "threshold_pct": 30.0, "violations": 0, "flagged": []},
            {"id": "13", "name": "BEI", "passed": True,
             "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "14", "name": "Summary tasks in logic", "passed": False,
             "pct": 4.0, "threshold_pct": 0.0, "violations": 4, "flagged": []},
        ],
    },
    "variance": {
        "cycle_id": "20260507T100000Z",
        "generated_at": "2026-05-07T10:00:00Z",
        "sections": {
            "technical_performance": "Completed SE-01 and SE-02 this reporting period.",
            "schedule_variance": "SPI=0.91. SE-04 delayed due to vendor delivery issue.",
            "cost_variance": "No dollar-value data; duration proxy used.",
            "corrective_actions": "Alice will escalate vendor issue by EOW.",
            "forward_look": "PDR at risk if SE-04 not resolved within 5 business days.",
        },
    },
    "sra": {"p50_days": 5, "p80_days": 12, "p95_days": 22, "iterations": 1000},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def smoke_client(tmp_path, monkeypatch):
    """Server client backed by the realistic state fixture."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(_STATE), encoding="utf-8")
    portfolio_file = str(tmp_path / "portfolio.json")
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", str(state_file))
    monkeypatch.setenv("PORTFOLIO_FILE", portfolio_file)
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("CALL_TRANSPORT", "simulated")
    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)
    srv._STATE_FILE = str(state_file)
    srv._REPORTS_DIR = str(tmp_path)
    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture()
def empty_client(tmp_path, monkeypatch):
    """Server client with no state file — for 404 tests."""
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)
    srv._STATE_FILE = str(tmp_path / "missing.json")
    srv._REPORTS_DIR = str(tmp_path)
    return TestClient(srv.app, raise_server_exceptions=False)


# ===========================================================================
# GET /api/evm
# ===========================================================================

class TestEVMEndpoint:
    def test_200_with_state(self, smoke_client):
        assert smoke_client.get("/api/evm").status_code == 200

    def test_has_program_key(self, smoke_client):
        assert "program" in smoke_client.get("/api/evm").json()

    def test_has_by_cam_key(self, smoke_client):
        assert "by_cam" in smoke_client.get("/api/evm").json()

    def test_program_has_spi(self, smoke_client):
        assert "SPI" in smoke_client.get("/api/evm").json()["program"]

    def test_program_spi_is_float(self, smoke_client):
        spi = smoke_client.get("/api/evm").json()["program"]["SPI"]
        assert isinstance(spi, float)

    def test_program_has_all_evm_metrics(self, smoke_client):
        prog = smoke_client.get("/api/evm").json()["program"]
        for key in ("BAC", "BCWP", "BCWS", "SPI", "SV", "EAC", "VAC", "TCPI", "BEI"):
            assert key in prog, f"EVM program missing: {key}"

    def test_by_cam_entries_present(self, smoke_client):
        by_cam = smoke_client.get("/api/evm").json()["by_cam"]
        assert len(by_cam) >= 1

    def test_cam_name_present_in_by_cam(self, smoke_client):
        by_cam = smoke_client.get("/api/evm").json()["by_cam"]
        assert "Alice Nguyen" in by_cam

    def test_404_no_state_file(self, empty_client):
        assert empty_client.get("/api/evm").status_code == 404

    def test_404_state_missing_evm_key(self, tmp_path, monkeypatch):
        sf = tmp_path / "state.json"
        sf.write_text(json.dumps({"health": "GREEN", "cycle_id": "test"}), encoding="utf-8")
        monkeypatch.setenv("DASHBOARD_API_KEY", "")
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(sf))
        import importlib, agent.dashboard.server as srv
        importlib.reload(srv)
        srv._STATE_FILE = str(sf)
        client = TestClient(srv.app, raise_server_exceptions=False)
        assert client.get("/api/evm").status_code == 404


# ===========================================================================
# GET /api/dcma
# ===========================================================================

class TestDCMAEndpoint:
    def test_200_with_state(self, smoke_client):
        assert smoke_client.get("/api/dcma").status_code == 200

    def test_has_score(self, smoke_client):
        assert "score" in smoke_client.get("/api/dcma").json()

    def test_has_overall_health(self, smoke_client):
        assert "overall_health" in smoke_client.get("/api/dcma").json()

    def test_has_checks_list(self, smoke_client):
        checks = smoke_client.get("/api/dcma").json()["checks"]
        assert isinstance(checks, list)

    def test_score_is_int(self, smoke_client):
        assert isinstance(smoke_client.get("/api/dcma").json()["score"], int)

    def test_overall_health_valid_value(self, smoke_client):
        health = smoke_client.get("/api/dcma").json()["overall_health"]
        assert health in ("GREEN", "YELLOW", "RED")

    def test_14_checks_returned(self, smoke_client):
        checks = smoke_client.get("/api/dcma").json()["checks"]
        assert len(checks) == 14

    def test_each_check_has_required_fields(self, smoke_client):
        for chk in smoke_client.get("/api/dcma").json()["checks"]:
            for field in ("id", "name", "passed", "violations"):
                assert field in chk, f"Check missing field: {field}"

    def test_passed_is_bool(self, smoke_client):
        checks = smoke_client.get("/api/dcma").json()["checks"]
        for chk in checks:
            assert isinstance(chk["passed"], bool)

    def test_score_matches_passed_count(self, smoke_client):
        data = smoke_client.get("/api/dcma").json()
        passed_count = sum(1 for c in data["checks"] if c["passed"])
        assert data["score"] == passed_count

    def test_404_no_state_file(self, empty_client):
        assert empty_client.get("/api/dcma").status_code == 404

    def test_404_state_missing_dcma_key(self, tmp_path, monkeypatch):
        sf = tmp_path / "state.json"
        sf.write_text(json.dumps({"health": "GREEN"}), encoding="utf-8")
        monkeypatch.setenv("DASHBOARD_API_KEY", "")
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(sf))
        import importlib, agent.dashboard.server as srv
        importlib.reload(srv)
        srv._STATE_FILE = str(sf)
        client = TestClient(srv.app, raise_server_exceptions=False)
        assert client.get("/api/dcma").status_code == 404


# ===========================================================================
# GET /api/variance
# ===========================================================================

class TestVarianceEndpoint:
    def test_200_with_state(self, smoke_client):
        assert smoke_client.get("/api/variance").status_code == 200

    def test_has_sections(self, smoke_client):
        assert "sections" in smoke_client.get("/api/variance").json()

    def test_has_cycle_id(self, smoke_client):
        assert "cycle_id" in smoke_client.get("/api/variance").json()

    def test_all_five_sections_present(self, smoke_client):
        sections = smoke_client.get("/api/variance").json()["sections"]
        for key in ("technical_performance", "schedule_variance", "cost_variance",
                    "corrective_actions", "forward_look"):
            assert key in sections, f"Missing variance section: {key}"

    def test_sections_are_strings(self, smoke_client):
        sections = smoke_client.get("/api/variance").json()["sections"]
        for k, v in sections.items():
            assert isinstance(v, str), f"Section {k} is not a string"

    def test_sections_non_empty(self, smoke_client):
        sections = smoke_client.get("/api/variance").json()["sections"]
        for k, v in sections.items():
            assert len(v) > 0, f"Section {k} is empty"

    def test_404_no_state_file(self, empty_client):
        assert empty_client.get("/api/variance").status_code == 404


# ===========================================================================
# GET /api/briefing
# ===========================================================================

class TestBriefingEndpoint:
    def test_200_returns_html(self, smoke_client):
        resp = smoke_client.get("/api/briefing")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_is_complete_html_document(self, smoke_client):
        html = smoke_client.get("/api/briefing").text
        assert "<html" in html.lower() or "<!doctype html" in html.lower()
        assert "</html>" in html.lower()

    def test_contains_health_status(self, smoke_client):
        html = smoke_client.get("/api/briefing").text
        assert "YELLOW" in html

    def test_contains_cycle_id(self, smoke_client):
        html = smoke_client.get("/api/briefing").text
        assert "20260507T100000Z" in html

    def test_contains_evm_metrics(self, smoke_client):
        html = smoke_client.get("/api/briefing").text
        assert "SPI" in html
        assert "EAC" in html

    def test_contains_dcma_reference(self, smoke_client):
        html = smoke_client.get("/api/briefing").text
        assert "DCMA" in html or "14-Point" in html or "14 Point" in html

    def test_contains_cam_name(self, smoke_client):
        html = smoke_client.get("/api/briefing").text
        assert "Alice Nguyen" in html

    def test_briefing_saved_to_disk(self, smoke_client):
        # Read REPORTS_DIR from the env var that smoke_client fixture set via
        # monkeypatch — avoids the pytest quirk where a fixture's tmp_path and
        # the test method's tmp_path are different instances.
        import os as _os
        from pathlib import Path as _Path
        smoke_client.get("/api/briefing")
        briefings_dir = _Path(_os.environ["REPORTS_DIR"]) / "briefings"
        assert briefings_dir.exists(), "briefings/ directory not created"
        html_files = list(briefings_dir.glob("*_briefing.html"))
        assert len(html_files) >= 1, "No briefing HTML file saved to disk"

    def test_saved_file_contains_same_content(self, smoke_client):
        import os as _os
        from pathlib import Path as _Path
        smoke_client.get("/api/briefing").text
        briefings_dir = _Path(_os.environ["REPORTS_DIR"]) / "briefings"
        html_files = list(briefings_dir.glob("*_briefing.html"))
        assert len(html_files) >= 1, "Briefing file not saved"
        saved_html = html_files[0].read_text(encoding="utf-8")
        assert "YELLOW" in saved_html
        assert "SPI" in saved_html

    def test_retrieve_saved_briefing_by_cycle_id(self, smoke_client):
        import os as _os
        from pathlib import Path as _Path
        smoke_client.get("/api/briefing")  # generate and save
        briefings_dir = _Path(_os.environ["REPORTS_DIR"]) / "briefings"
        html_files = list(briefings_dir.glob("*_briefing.html"))
        assert len(html_files) >= 1
        cycle_id = html_files[0].stem.replace("_briefing", "")
        resp = smoke_client.get(f"/api/briefing/{cycle_id}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_404_for_unknown_cycle_id(self, smoke_client):
        assert smoke_client.get("/api/briefing/NONEXISTENT_XYZ_999").status_code == 404

    def test_404_no_state_file(self, empty_client):
        assert empty_client.get("/api/briefing").status_code == 404


# ===========================================================================
# GET /api/portfolio
# ===========================================================================

class TestPortfolioEndpoint:
    def test_200_with_empty_portfolio(self, smoke_client):
        resp = smoke_client.get("/api/portfolio")
        assert resp.status_code == 200

    def test_has_portfolio_health_key(self, smoke_client):
        data = smoke_client.get("/api/portfolio").json()
        assert "portfolio_health" in data

    def test_has_programs_key(self, smoke_client):
        data = smoke_client.get("/api/portfolio").json()
        assert "programs" in data

    def test_programs_is_list(self, smoke_client):
        data = smoke_client.get("/api/portfolio").json()
        assert isinstance(data["programs"], list)


# ===========================================================================
# POST /api/trigger
# ===========================================================================

class TestTriggerEndpoint:
    def test_returns_triggered(self, smoke_client):
        with patch("agent.cycle_runner.CycleRunner.run"):
            resp = smoke_client.post("/api/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "triggered"

    def test_returns_force_flag(self, smoke_client):
        with patch("agent.cycle_runner.CycleRunner.run"):
            resp = smoke_client.post("/api/trigger?force=true")
        assert resp.json()["force"] is True

    def test_409_when_already_active(self, smoke_client):
        with patch("agent.cycle_runner.CycleRunner.is_active", return_value=True):
            resp = smoke_client.post("/api/trigger")
        assert resp.status_code == 409

    def test_sets_cycle_active(self, smoke_client):
        """After trigger, /api/status must report cycle_active=True.

        We patch _run_inner (not run) so that CycleRunner.run() still executes
        its own '_active = True' guard before handing off to the inner pipeline.
        _persist_status and _purge_old_data are also patched so the finally
        block has no I/O side effects and _active = False is guaranteed to run.
        """
        started = threading.Event()
        hold = threading.Event()

        def slow_inner(self, cycle_id, status):
            started.set()
            hold.wait(timeout=3)
            return status

        with patch("agent.cycle_runner.CycleRunner._run_inner", slow_inner), \
             patch("agent.cycle_runner.CycleRunner._persist_status", lambda *_: None), \
             patch("agent.cycle_runner.CycleRunner._purge_old_data", lambda *_: None):
            smoke_client.post("/api/trigger")
            started.wait(timeout=2)
            resp = smoke_client.get("/api/status")
            hold.set()

        assert resp.json()["cycle_active"] is True

    def test_cycle_not_active_before_trigger(self, smoke_client):
        resp = smoke_client.get("/api/status")
        assert resp.json()["cycle_active"] is False


# ===========================================================================
# GET / — Dashboard HTML
# ===========================================================================

class TestDashboardHTML:
    def test_200(self, smoke_client):
        assert smoke_client.get("/").status_code == 200

    def test_is_html(self, smoke_client):
        ct = smoke_client.get("/").headers.get("content-type", "")
        assert "text/html" in ct

    def test_has_evm_panel(self, smoke_client):
        html = smoke_client.get("/").text
        assert "Earned Value" in html or "evm" in html.lower()

    def test_has_dcma_panel(self, smoke_client):
        html = smoke_client.get("/").text
        assert "DCMA" in html or "14-Point" in html

    def test_has_variance_panel(self, smoke_client):
        html = smoke_client.get("/").text
        assert "Variance" in html

    def test_has_portfolio_panel(self, smoke_client):
        html = smoke_client.get("/").text
        assert "Portfolio" in html

    def test_has_listen_in_panel(self, smoke_client):
        html = smoke_client.get("/").text
        assert "Listen" in html

    def test_has_generate_briefing_button(self, smoke_client):
        html = smoke_client.get("/").text
        assert "Briefing" in html

    def test_has_trigger_cycle_button(self, smoke_client):
        html = smoke_client.get("/").text
        assert "Trigger" in html

    def test_references_evm_api_path(self, smoke_client):
        html = smoke_client.get("/").text
        assert "/api/evm" in html

    def test_references_dcma_api_path(self, smoke_client):
        html = smoke_client.get("/").text
        assert "/api/dcma" in html

    def test_references_interview_sessions_path(self, smoke_client):
        """Dashboard JS must poll /api/interview-sessions for listen-in panel."""
        html = smoke_client.get("/").text
        assert "/api/interview-sessions" in html

    def test_references_interview_stream_path(self, smoke_client):
        """Dashboard JS must open SSE connection to /api/interview-stream."""
        html = smoke_client.get("/").text
        assert "/api/interview-stream" in html
