"""
Phase 15 — Dashboard rebuild from zip tests.

The Phase 15 dashboard is a React 18 + Babel-Standalone single-page app
mounted at `/`.  Because all interactive content is rendered CLIENT-SIDE,
pytest cannot directly assert on rendered DOM (that would require Selenium /
Playwright).  Instead, this suite verifies:

  1. SHELL    — base.html serves the React mount point with our vendored
                react / react-dom / babel script tags and ALL 7 atlas
                source files referenced in the correct order.
  2. VENDOR   — every vendored dep (React, React-DOM, Babel, IBM Plex CSS,
                woff2 fonts) returns 200.
  3. SOURCES  — every /static/atlas/*.{js,jsx,css} file serves 200 and
                contains the expected component name / export.
  4. DATA     — data.js exposes the expected mock globals; api.js wires
                up the documented endpoint contracts.
  5. ROLLBACK — IMS_LEGACY_DASHBOARD=1 still serves the original Phase 12
                monolithic index.html.
  6. AGENT    — every /api/* endpoint relied on by the React app still
                returns the expected shape (regression guard — protects
                against backend drift).

Live React rendering / interaction coverage lives in the manual E2E
procedure in TEST_RESULTS.md and is exercised via the Chrome MCP during
phase wrap-up.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_MIN_STATE = {
    "cycle_id": "20260508T120000Z",
    "timestamp": "2026-05-08T12:00:00Z",
    "schedule_health": "YELLOW",
    "last_updated": "2026-05-08T12:00:00Z",
    "milestones": [
        {"milestone_name": "PDR", "baseline_date": "2026-06-15",
         "p50_date": "2026-06-20", "p95_date": "2026-07-05",
         "prob_on_baseline": 0.35, "risk_level": "HIGH"},
    ],
    "completion_report": {"responded": 3, "total": 5},
    "critical_path_task_ids": ["SE-01", "SE-04"],
    "tasks_behind": [],
    "validation_holds": [],
    "cam_response_status": {},
}


@pytest.fixture()
def dash_client(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(_MIN_STATE), encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", str(state_file))
    monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("CALL_TRANSPORT", "simulated")
    monkeypatch.delenv("IMS_LEGACY_DASHBOARD", raising=False)
    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)
    srv._STATE_FILE = str(state_file)
    srv._REPORTS_DIR = str(tmp_path)
    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture()
def html(dash_client):
    return dash_client.get("/").text


# ===========================================================================
# 1. SHELL — React mount point + script tag order
# ===========================================================================


class TestReactShell:
    def test_returns_200(self, dash_client):
        assert dash_client.get("/").status_code == 200

    def test_doctype_html5(self, html):
        assert html.lstrip().lower().startswith("<!doctype html>")

    def test_title_atlas_console(self, html):
        assert "<title>ATLAS · IMS Agent Console</title>" in html

    def test_root_mount_div(self, html):
        assert '<div id="root">' in html

    def test_data_theme_preset_inline(self, html):
        # The inline <script> sets data-theme to avoid FOUC
        assert 'document.documentElement.setAttribute("data-theme"' in html

    def test_react_script_present(self, html):
        assert "/static/vendor/react.production.min.js" in html

    def test_react_dom_script_present(self, html):
        assert "/static/vendor/react-dom.production.min.js" in html

    def test_babel_script_present(self, html):
        assert "/static/vendor/babel.min.js" in html

    def test_ibm_plex_css_linked(self, html):
        assert "/static/vendor/ibm-plex.css" in html

    def test_atlas_styles_linked(self, html):
        assert "/static/atlas/styles.css" in html

    @pytest.mark.parametrize("src", [
        "/static/atlas/data.js",
        "/static/atlas/api.js",          # Phase 15.4 hydration shim
        "/static/atlas/components.jsx",
        "/static/atlas/charts.jsx",
        "/static/atlas/IMSStats.jsx",
        "/static/atlas/PMPortal.jsx",
        "/static/atlas/AgentControls.jsx",
        "/static/atlas/app.jsx",
    ])
    def test_atlas_source_referenced(self, html, src):
        assert src in html, f"base.html must <script src='{src}'>"

    def test_script_load_order(self, html):
        # data.js must come BEFORE api.js, both before app.jsx
        i_data = html.find("/static/atlas/data.js")
        i_api  = html.find("/static/atlas/api.js")
        i_app  = html.find("/static/atlas/app.jsx")
        assert 0 < i_data < i_api < i_app, "data.js → api.js → app.jsx ordering required"

    def test_server_state_injection(self, html):
        # window.__IMS injection lets React skip an initial fetch.
        # Keys are JS-literal style (unquoted), values are JSON via tojson.
        assert "window.__IMS" in html
        assert "cycle_id:" in html
        assert "milestones:" in html
        assert "history:" in html


# ===========================================================================
# 2. VENDORED ASSETS
# ===========================================================================


class TestVendoredAssets:
    @pytest.mark.parametrize("path,must_contain", [
        ("/static/vendor/react.production.min.js",     "React"),
        ("/static/vendor/react-dom.production.min.js", "ReactDOM"),
        ("/static/vendor/babel.min.js",                "Babel"),
        ("/static/vendor/ibm-plex.css",                "IBM Plex"),
    ])
    def test_vendor_asset_serves(self, dash_client, path, must_contain):
        r = dash_client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        assert len(r.content) > 0
        assert must_contain in r.text, f"{path} missing signature '{must_contain}'"

    def test_react_is_production_build(self, dash_client):
        # Production React bundle is ~10 KB; development is ~1 MB
        size = len(dash_client.get("/static/vendor/react.production.min.js").content)
        assert 1000 < size < 50000, f"React bundle size {size} not in production range"

    def test_babel_is_full_standalone(self, dash_client):
        # Babel Standalone is ~3 MB
        size = len(dash_client.get("/static/vendor/babel.min.js").content)
        assert size > 1_000_000, f"Babel bundle suspiciously small ({size} bytes)"

    @pytest.mark.parametrize("idx", range(11))
    def test_ibm_plex_font_serves(self, dash_client, idx):
        r = dash_client.get(f"/static/vendor/fonts/ibm-plex-latin-{idx}.woff2")
        assert r.status_code == 200, f"Font #{idx} missing"
        assert r.content[:4] == b"wOF2", f"Font #{idx} not valid woff2"

    def test_ibm_plex_css_references_local_fonts(self, dash_client):
        css = dash_client.get("/static/vendor/ibm-plex.css").text
        # Must use rewritten /static/vendor/fonts/ paths, NOT gstatic.com
        assert "/static/vendor/fonts/" in css
        assert "fonts.gstatic.com" not in css, "CSS must not leak Google Fonts URLs"

    def test_no_cdn_in_html(self, html):
        # Phase 15.1 contract: zero external CDN dependencies
        assert "unpkg.com" not in html
        assert "cdn.jsdelivr.net" not in html
        assert "fonts.googleapis.com" not in html


# ===========================================================================
# 3. ATLAS SOURCES — each module serves + carries expected exports
# ===========================================================================


class TestAtlasSources:
    def test_styles_css_serves(self, dash_client):
        css = dash_client.get("/static/atlas/styles.css").text
        for token in [":root", "--bg", "--accent", "--ok", "--warn", "--bad",
                      ".panel", ".kpi", ".ticker", ".tbl", ".btn"]:
            assert token in css, f"styles.css missing {token}"

    def test_app_jsx_serves(self, dash_client):
        src = dash_client.get("/static/atlas/app.jsx").text
        assert "function App(" in src
        assert "ReactDOM.createRoot" in src
        assert "useTab" in src
        assert "useTheme" in src
        # Phase 15.6 — FORCE CYCLE wires to /api/trigger
        assert "/api/trigger" in src

    def test_components_jsx_exports(self, dash_client):
        src = dash_client.get("/static/atlas/components.jsx").text
        for fn in ["Panel", "Pill", "Seg", "RYG", "KPITile", "Sparkline", "Ticker"]:
            assert f"function {fn}(" in src, f"components.jsx missing {fn}"

    def test_charts_jsx_exports(self, dash_client):
        src = dash_client.get("/static/atlas/charts.jsx").text
        for fn in ["SummaryScheduleGantt", "SRAProbChart", "LineChart"]:
            assert f"function {fn}(" in src, f"charts.jsx missing {fn}"

    def test_imsstats_jsx_exports_tab(self, dash_client):
        src = dash_client.get("/static/atlas/IMSStats.jsx").text
        assert "function IMSStatsTab(" in src
        assert "window.BEI_HIST" in src
        assert "DCMA" in src

    def test_pmportal_jsx_exports_tab(self, dash_client):
        src = dash_client.get("/static/atlas/PMPortal.jsx").text
        assert "function PMPortalTab(" in src
        assert "TOP_RISKS_PROSE" in src
        assert "BriefingModal" in src

    def test_agentcontrols_jsx_exports_tab(self, dash_client):
        src = dash_client.get("/static/atlas/AgentControls.jsx").text
        assert "function AgentControlsTab(" in src
        # Phase 15.5 SSE wiring
        assert "/api/interview-stream" in src
        assert "/api/interview-recent" in src
        # Phase 15.6 trigger button
        assert "/api/trigger?force=true" in src


# ===========================================================================
# 4. DATA + API hydration layer
# ===========================================================================


class TestDataAndApiLayer:
    def test_data_js_globals(self, dash_client):
        src = dash_client.get("/static/atlas/data.js").text
        for name in ["BEI_HIST", "SFA_HIST", "HRM_HIST", "EVM_KPIS",
                     "CAMS", "DCMA14", "HEALTH_HISTORY", "DIFF_ROWS",
                     "CUM_DIFF", "DRIFT_ROWS", "INTERVIEW_SCRIPT",
                     "SCHED_CURRENT", "SCHED_PRIOR", "SRA",
                     "TOP_RISKS_PROSE", "PM_ACTIONS_PROSE", "CYCLE_PHASES"]:
            assert name in src, f"data.js missing global {name}"

    def test_data_js_window_export(self, dash_client):
        src = dash_client.get("/static/atlas/data.js").text
        # All globals exported to window via Object.assign
        assert "Object.assign(window," in src

    def test_api_js_hydration_function(self, dash_client):
        src = dash_client.get("/static/atlas/api.js").text
        assert "hydrate" in src
        assert "window.__IMS_HYDRATE" in src
        # Wires every endpoint we need
        for path in ["/api/state", "/api/evm/history", "/api/health/history",
                     "/api/diff/latest", "/api/changes", "/api/baseline-drift"]:
            assert path in src, f"api.js does not call {path}"

    def test_api_js_overrides_window_globals(self, dash_client):
        src = dash_client.get("/static/atlas/api.js").text
        for name in ["BEI_HIST", "SFA_HIST", "HEALTH_HISTORY",
                     "EVM_KPIS", "CAMS", "DCMA14", "TOP_RISKS_PROSE",
                     "PM_ACTIONS_PROSE", "DIFF_ROWS", "CUM_DIFF", "DRIFT_ROWS"]:
            assert f"window.{name}" in src, f"api.js never writes window.{name}"

    def test_app_jsx_awaits_hydrate(self, dash_client):
        src = dash_client.get("/static/atlas/app.jsx").text
        # Phase 15.4 — ReactDOM.createRoot is gated on __IMS_HYDRATE
        assert "__IMS_HYDRATE" in src


# ===========================================================================
# 5. AGENT API REGRESSION GUARD (Phase 15 contract: backend unchanged)
# ===========================================================================


class TestAgentApiRegression:
    def test_api_state_returns_200(self, dash_client):
        assert dash_client.get("/api/state").status_code == 200

    def test_api_status(self, dash_client):
        r = dash_client.get("/api/status")
        assert r.status_code == 200
        assert "cycle_active" in r.json()

    def test_api_health(self, dash_client):
        r = dash_client.get("/health")
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"

    def test_api_evm_history(self, dash_client):
        r = dash_client.get("/api/evm/history?n=24")
        assert r.status_code == 200
        body = r.json()
        assert "history" in body and "n" in body

    def test_api_health_history(self, dash_client):
        r = dash_client.get("/api/health/history?n=24")
        assert r.status_code == 200
        body = r.json()
        assert "history" in body and "n" in body

    @pytest.mark.parametrize("path", [
        "/api/diff/latest",
        "/api/changes",
        "/api/baseline-drift",
        "/api/interview-sessions",
        "/api/interview-recent",
    ])
    def test_api_endpoint_reachable(self, dash_client, path):
        # Must return 200 (with data) or 404 (no data yet) — both are valid
        r = dash_client.get(path)
        assert r.status_code in (200, 404), f"{path} returned {r.status_code}"


# ===========================================================================
# 6. ROLLBACK PATH — IMS_LEGACY_DASHBOARD=1 still serves the old layout
# ===========================================================================


class TestLegacyRollback:
    def test_legacy_flag_renders_index_html(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(_MIN_STATE), encoding="utf-8")
        monkeypatch.setenv("DASHBOARD_API_KEY", "")
        monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(state_file))
        monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        monkeypatch.setenv("CALL_TRANSPORT", "simulated")
        monkeypatch.setenv("IMS_LEGACY_DASHBOARD", "1")
        import importlib
        import agent.dashboard.server as srv
        importlib.reload(srv)
        srv._STATE_FILE = str(state_file)
        srv._REPORTS_DIR = str(tmp_path)
        client = TestClient(srv.app, raise_server_exceptions=False)
        html = client.get("/").text
        # Legacy template has no react root mount
        assert '<div id="root">' not in html
        # Legacy title from the original Phase 12 monolithic template
        assert "IMS Agent — Schedule Dashboard" in html or "IMS Agent Dashboard" in html

    def test_phase14_base_legacy_html_preserved(self):
        # base.legacy.html is the Phase 14 layout, kept as a safety net
        p = Path(__file__).parent.parent / "agent" / "dashboard" / "templates" / "base.legacy.html"
        assert p.exists(), "Phase 14 base.html must be preserved as base.legacy.html"
        text = p.read_text(encoding="utf-8")
        assert "app-shell" not in text  # Phase 14 wasn't the app-shell layout
        assert "IMS Command Center" in text or "tab-nav" in text
