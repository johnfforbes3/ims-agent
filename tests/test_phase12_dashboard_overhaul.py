"""
Phase 12 — IMS Command Center 3-Tab Dashboard Overhaul tests.

Targeted coverage of the work delivered in Phase 12:

* Tab navigation (3 buttons, hash routing IDs, default-active state)
* New base.html template structure (header, tab nav, 3 tab panels)
* Static asset mount (/static/css, /static/js, /static/vendor)
* Chart.js v4 vendored locally (not CDN)
* New API endpoints: /api/evm/history, /api/health/history
* Chart canvas elements present in each tab partial
* Demo mode route (/?demo=1) returns populated dashboard
* Light/dark theme toggle hook (data-theme attribute)
* Print stylesheet (@media print rules)
* Chart PNG export buttons
* Keyboard shortcut registration (Ctrl/Cmd+1/2/3)
* IMS_LEGACY_DASHBOARD env-flag rollback path

These tests use the same dash_client fixture as test_integration_dashboard_ui
(reload + temp state file pattern).
"""

import json
import re
from pathlib import Path

# Phase 15 — see conftest.py for full explanation. These Phase 12 tests
# assert against the monolithic dashboard HTML that the Phase 15 React
# rebuild replaced. They remain valid for the preserved legacy template;
# enable with `pytest -m legacy` or `IMS_LEGACY_DASHBOARD=1`.
import pytest as _pt
pytestmark = _pt.mark.legacy

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    # Phase 12: ensure new dashboard is rendered (not the legacy fallback)
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
# 1. Tab navigation structure
# ===========================================================================


class TestTabNavigation:
    def test_three_tab_buttons(self, html):
        assert html.count('class="tab-btn') == 3

    def test_metrics_tab_button(self, html):
        assert 'data-tab="metrics"' in html
        assert "IMS Metrics" in html

    def test_pm_tab_button(self, html):
        assert 'data-tab="pm"' in html
        assert "PM Dashboard" in html

    def test_atlas_tab_button(self, html):
        assert 'data-tab="atlas"' in html
        assert "ATLAS Agent Control" in html

    def test_three_tab_panels(self, html):
        assert html.count('class="tab-panel') == 3

    def test_metrics_tab_panel(self, html):
        assert 'class="tab-panel active" data-tab="metrics"' in html

    def test_pm_tab_panel(self, html):
        assert 'data-tab="pm"' in html

    def test_atlas_tab_panel(self, html):
        assert 'data-tab="atlas"' in html

    def test_metrics_active_by_default(self, html):
        # Look for "tab-panel active" near the metrics data-tab
        m = re.search(r'class="tab-panel\s+active"\s+data-tab="metrics"', html)
        assert m is not None

    def test_pm_panel_not_active_by_default(self, html):
        # PM panel must not have "active" class at initial render
        m = re.search(r'class="tab-panel"\s+data-tab="pm"', html)
        assert m is not None

    def test_switch_tab_function_referenced(self, html):
        assert "switchTab(" in html

    def test_role_tablist(self, html):
        assert 'role="tablist"' in html


# ===========================================================================
# 2. Static asset mount
# ===========================================================================


class TestStaticAssets:
    @pytest.mark.parametrize("path", [
        "/static/css/dashboard.css",
        "/static/js/dashboard-core.js",
        "/static/js/metrics-tab.js",
        "/static/js/pm-tab.js",
        "/static/js/atlas-tab.js",
        "/static/vendor/chart.umd.min.js",
    ])
    def test_static_asset_serves_200(self, dash_client, path):
        r = dash_client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        assert len(r.content) > 0, f"{path} returned empty body"

    def test_chart_js_is_v4(self, dash_client):
        """Vendored Chart.js must be v4.x."""
        body = dash_client.get("/static/vendor/chart.umd.min.js").text
        assert "Chart.js v4" in body[:500], "Expected Chart.js v4.x header in vendored bundle"

    def test_chart_js_local_not_cdn(self, html):
        """Phase 12 ITAR concern — Chart.js must load from /static, not a CDN."""
        assert 'src="/static/vendor/chart.umd.min.js"' in html
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html


# ===========================================================================
# 3. New API endpoints
# ===========================================================================


class TestEvmHistoryEndpoint:
    def test_returns_200(self, dash_client):
        r = dash_client.get("/api/evm/history")
        assert r.status_code == 200

    def test_default_n_24(self, dash_client):
        r = dash_client.get("/api/evm/history")
        assert "history" in r.json()

    def test_response_shape(self, dash_client):
        body = dash_client.get("/api/evm/history?n=24").json()
        assert isinstance(body, dict)
        assert "history" in body and "n" in body
        assert isinstance(body["history"], list)

    def test_n_capped_at_100(self, dash_client):
        body = dash_client.get("/api/evm/history?n=999").json()
        assert body["n"] <= 100

    def test_n_minimum_1(self, dash_client):
        body = dash_client.get("/api/evm/history?n=0").json()
        assert "history" in body  # graceful handling


class TestHealthHistoryEndpoint:
    def test_returns_200(self, dash_client):
        r = dash_client.get("/api/health/history")
        assert r.status_code == 200

    def test_response_shape(self, dash_client):
        body = dash_client.get("/api/health/history?n=24").json()
        assert "history" in body and "n" in body
        assert isinstance(body["history"], list)

    def test_n_capped_at_100(self, dash_client):
        body = dash_client.get("/api/health/history?n=999").json()
        assert body["n"] <= 100


# ===========================================================================
# 4. Chart canvas presence (each tab has its expected charts)
# ===========================================================================


class TestChartCanvasPresence:
    """Every tab partial must declare its <canvas id="…"> elements so
    Chart.js can mount instances."""

    def test_milestone_donut_canvas(self, html):
        assert 'id="milestone-donut"' in html

    def test_dcma_bar_chart_canvas(self, html):
        assert 'id="dcma-bar-chart"' in html

    def test_evm_sparklines_container(self, html):
        assert 'id="evm-sparklines"' in html

    def test_health_history_chart_canvas(self, html):
        assert 'id="health-history-chart"' in html

    def test_portfolio_donut_canvas(self, html):
        assert 'id="portfolio-donut"' in html

    def test_baseline_drift_chart_canvas(self, html):
        assert 'id="baseline-drift-chart"' in html

    def test_chart_container_class(self, html):
        assert "chart-container" in html


# ===========================================================================
# 5. Demo mode route (/?demo=1)
# ===========================================================================


class TestDemoMode:
    def test_demo_mode_returns_200(self, dash_client):
        r = dash_client.get("/?demo=1")
        assert r.status_code == 200

    def test_demo_mode_renders_dashboard(self, dash_client):
        r = dash_client.get("/?demo=1")
        assert "IMS Command Center" in r.text

    def test_demo_mode_has_milestones(self, dash_client):
        """Demo mode must inject realistic milestone data so the donut populates."""
        r = dash_client.get("/?demo=1")
        # The injected demo state should include milestone names recognisable in the HTML
        assert "PDR" in r.text or "CDR" in r.text

    def test_demo_mode_does_not_persist_to_state_file(self, dash_client, tmp_path):
        """Demo-mode injection must not write to the real state.json."""
        before = (tmp_path / "state.json").read_text()
        dash_client.get("/?demo=1")
        after = (tmp_path / "state.json").read_text()
        assert before == after


# ===========================================================================
# 6. Light / dark theme toggle
# ===========================================================================


class TestThemeToggle:
    def test_theme_toggle_button_present(self, html):
        assert 'id="theme-toggle"' in html

    def test_theme_attribute_on_html(self, html):
        # The <html> tag should carry a data-theme attribute (for CSS hooks)
        assert 'data-theme=' in html

    def test_theme_css_has_light_palette(self, dash_client):
        css = dash_client.get("/static/css/dashboard.css").text
        # Phase 12 light mode adds [data-theme="light"] selectors
        assert '[data-theme="light"]' in css


# ===========================================================================
# 7. Print stylesheet (@media print)
# ===========================================================================


class TestPrintStylesheet:
    def test_print_media_query_present(self, dash_client):
        css = dash_client.get("/static/css/dashboard.css").text
        assert "@media print" in css

    def test_print_hides_tab_nav(self, dash_client):
        css = dash_client.get("/static/css/dashboard.css").text
        # The print block should hide .tab-nav so all tabs cascade onto pages.
        # Look at everything inside @media print { ... } and confirm a rule
        # for .tab-nav that sets display:none.
        print_block = css.split("@media print", 1)[1]
        assert ".tab-nav" in print_block, "@media print must reference .tab-nav"
        # Find the .tab-nav rule and confirm display:none nearby
        idx = print_block.find(".tab-nav")
        nearby = print_block[idx:idx + 200]
        assert "display" in nearby and "none" in nearby

    def test_print_shows_all_tabs(self, dash_client):
        css = dash_client.get("/static/css/dashboard.css").text
        # @media print should override .tab-panel display:none default
        assert "@media print" in css
        # quick check that the print block references tab-panel
        assert "tab-panel" in css.split("@media print", 1)[1]


# ===========================================================================
# 8. Chart export as PNG
# ===========================================================================


class TestChartPngExport:
    def test_export_helper_in_dashboard_core(self, dash_client):
        js = dash_client.get("/static/js/dashboard-core.js").text
        assert "exportChart" in js or "downloadChart" in js

    def test_uses_chart_to_base64(self, dash_client):
        js = dash_client.get("/static/js/dashboard-core.js").text
        assert "toBase64Image" in js


# ===========================================================================
# 9. Keyboard shortcuts (Ctrl/Cmd+1/2/3)
# ===========================================================================


class TestKeyboardShortcuts:
    def test_keydown_listener_in_core(self, dash_client):
        js = dash_client.get("/static/js/dashboard-core.js").text
        assert "keydown" in js

    def test_shortcut_handles_digit_keys(self, dash_client):
        """Switch to tabs via Ctrl/Cmd+1/2/3."""
        js = dash_client.get("/static/js/dashboard-core.js").text
        # Check that the handler references digit keys + a modifier
        assert ("'1'" in js or '"1"' in js or "Digit1" in js)
        assert "ctrlKey" in js or "metaKey" in js


# ===========================================================================
# 10. JSDoc presence
# ===========================================================================


class TestCodeQuality:
    @pytest.mark.parametrize("path", [
        "/static/js/dashboard-core.js",
        "/static/js/metrics-tab.js",
        "/static/js/pm-tab.js",
        "/static/js/atlas-tab.js",
    ])
    def test_module_has_header_comment(self, dash_client, path):
        body = dash_client.get(path).text
        # File must open with a /* ... */ banner
        assert body.lstrip().startswith("/*"), f"{path} missing header comment"

    @pytest.mark.parametrize("path", [
        "/static/js/dashboard-core.js",
        "/static/js/metrics-tab.js",
        "/static/js/pm-tab.js",
        "/static/js/atlas-tab.js",
    ])
    def test_module_has_at_least_one_function(self, dash_client, path):
        body = dash_client.get(path).text
        assert "function " in body, f"{path} missing any function declaration"


# ===========================================================================
# 11. IMS_LEGACY_DASHBOARD rollback flag
# ===========================================================================


class TestLegacyRollback:
    def test_legacy_flag_renders_index_html(self, tmp_path, monkeypatch):
        """Setting IMS_LEGACY_DASHBOARD=1 falls back to the original
        monolithic index.html (preserved for 2-week soak)."""
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
        # Legacy template has no tab-nav
        assert "tab-nav" not in html
        assert "IMS Agent — Schedule Dashboard" in html  # old title
