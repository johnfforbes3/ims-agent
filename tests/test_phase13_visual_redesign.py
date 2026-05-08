"""
Phase 13 — Visual Command Center Redesign tests.

Locks in the new app-shell layout, left sidebar navigation, top search bar,
right widget panel, light-theme default, and design-token-driven CSS.

Coverage:
  * App shell structure (sidebar | topbar | main | rightbar)
  * Sidebar brand, nav, theme switch in footer
  * Topbar search input, profile avatar, notification bell, trigger CTA
  * Right widget panel cards (cycle status, active interviews, recent cycles)
  * Design tokens (CSS custom properties for color/spacing/radius)
  * Light theme as default (data-theme="light" on <html>)
  * Hero trend chart canvas on metrics tab
  * Inter web font load
  * Phase 12 + 12.1 features still wired (tab routing, charts, demo, etc.)
"""

import json
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


@pytest.fixture()
def css(dash_client):
    return dash_client.get("/static/css/dashboard.css").text


# ===========================================================================
# 1. App-shell layout
# ===========================================================================


class TestAppShell:
    def test_app_shell_present(self, html):
        assert 'class="app-shell"' in html

    def test_app_sidebar_present(self, html):
        assert 'class="app-sidebar"' in html

    def test_app_topbar_present(self, html):
        assert 'class="app-topbar"' in html

    def test_app_main_present(self, html):
        assert 'class="app-main"' in html

    def test_app_rightbar_present(self, html):
        assert 'class="app-rightbar"' in html

    def test_grid_layout_in_css(self, css):
        # The app-shell uses CSS grid for the 3-column layout
        assert ".app-shell" in css
        assert "grid-template-areas" in css


# ===========================================================================
# 2. Left sidebar
# ===========================================================================


class TestSidebar:
    def test_sidebar_brand(self, html):
        assert 'class="sidebar-brand"' in html

    def test_sidebar_brand_name_command_center(self, html):
        # Brand text should still read "Command Center"
        assert "Command Center" in html

    def test_sidebar_has_three_nav_buttons(self, html):
        # The sidebar nav holds the 3 tab buttons
        assert html.count('data-tab="metrics"') >= 1
        assert html.count('data-tab="pm"') >= 1
        assert html.count('data-tab="atlas"') >= 1

    def test_sidebar_section_label(self, html):
        assert 'class="sidebar-section-label"' in html

    def test_sidebar_link_class(self, html):
        assert 'class="tab-btn sidebar-link' in html or 'class="sidebar-link' in html

    def test_sidebar_quick_actions(self, html):
        # Demo Mode link + Executive Briefing in sidebar
        assert "Demo Mode" in html
        assert "Executive Briefing" in html

    def test_sidebar_theme_switch_segment(self, html):
        assert 'id="theme-light"' in html
        assert 'id="theme-dark"' in html

    def test_sidebar_attribution(self, html):
        assert 'class="sidebar-attribution"' in html

    def test_sidebar_role_navigation(self, html):
        assert 'role="navigation"' in html


# ===========================================================================
# 3. Top bar
# ===========================================================================


class TestTopbar:
    def test_search_input_present(self, html):
        assert 'class="topbar-search"' in html
        assert 'id="topbar-search-input"' in html

    def test_search_placeholder(self, html):
        assert 'placeholder="Search' in html

    def test_search_keyboard_hint(self, html):
        assert "topbar-search-hint" in html

    def test_notification_bell(self, html):
        assert "topbar-icon-btn" in html
        assert "🔔" in html

    def test_profile_avatar(self, html):
        assert 'class="topbar-profile"' in html

    def test_trigger_cycle_button(self, html):
        # Still in topbar but now styled as primary CTA
        assert 'id="trigger-btn"' in html
        assert "Trigger Cycle" in html

    def test_countdown_in_topbar(self, html):
        # The polling countdown lives in the topbar refresh chip
        assert 'id="countdown"' in html
        assert "topbar-refresh" in html


# ===========================================================================
# 4. Right widget panel
# ===========================================================================


class TestRightbar:
    def test_rightbar_card_class(self, html):
        assert 'class="rightbar-card"' in html

    def test_cycle_status_card(self, html):
        assert "Cycle Status" in html

    def test_active_interviews_card(self, html):
        assert "Active Interviews" in html

    def test_recent_cycles_card(self, html):
        assert "Recent Cycles" in html

    def test_rightbar_stat_class(self, html):
        assert "rightbar-stat" in html


# ===========================================================================
# 5. Design system / tokens
# ===========================================================================


class TestDesignTokens:
    def test_css_custom_properties_root(self, css):
        # All design tokens live under :root { --bg-app: …, … }
        assert ":root" in css
        assert "--bg-app:" in css
        assert "--text-primary:" in css
        assert "--accent:" in css
        assert "--border-subtle:" in css

    def test_typography_scale(self, css):
        for var in ["--fs-xs", "--fs-base", "--fs-lg", "--fs-xl", "--fs-2xl", "--fs-3xl"]:
            assert var in css, f"Missing typography token {var}"

    def test_spacing_scale(self, css):
        for var in ["--sp-1", "--sp-2", "--sp-4", "--sp-6", "--sp-8"]:
            assert var in css, f"Missing spacing token {var}"

    def test_radius_tokens(self, css):
        for var in ["--r-sm", "--r-md", "--r-lg", "--r-pill"]:
            assert var in css, f"Missing radius token {var}"

    def test_inter_font_loaded(self, html):
        # Phase 13 ships Inter via Google Fonts
        assert "fonts.googleapis.com" in html
        assert "Inter" in html

    def test_health_palette_tokens(self, css):
        for var in ["--hp-red", "--hp-yellow", "--hp-green"]:
            assert var in css


# ===========================================================================
# 6. Theme defaults (light by default; dark via data-theme)
# ===========================================================================


class TestThemeDefaults:
    def test_html_has_data_theme_light(self, html):
        # Phase 13: light is the default; dark is the alternate
        assert 'data-theme="light"' in html

    def test_dark_theme_overrides_in_css(self, css):
        assert '[data-theme="dark"]' in css

    def test_set_theme_function_exists(self, dash_client):
        js = dash_client.get("/static/js/dashboard-core.js").text
        assert "function setTheme" in js


# ===========================================================================
# 7. Hero trend chart on metrics tab
# ===========================================================================


class TestMetricsHeroTrend:
    def test_hero_trend_canvas(self, html):
        assert 'id="metrics-trend-hero"' in html

    def test_trend_hero_section(self, html):
        assert "trend-hero" in html

    def test_kpi_grid_six_columns_default(self, html):
        # The hero KPI strip should not be limited to kpi-3 by default
        assert 'class="kpi-grid"' in html

    def test_trend_period_selector(self, html):
        # 24C / 12C / 6C selector on the trend chart
        assert "trend-period" in html

    def test_render_hero_trend_function(self, dash_client):
        js = dash_client.get("/static/js/metrics-tab.js").text
        assert "_renderHeroTrend" in js


# ===========================================================================
# 8. Phase 12 features still wired (regression guard)
# ===========================================================================


class TestPhase12RegressionGuard:
    def test_three_tab_buttons_still_present(self, html):
        # Class string "tab-btn" should appear at least 3 times (the 3 tabs)
        assert html.count('class="tab-btn') >= 3

    def test_three_tab_panels_still_present(self, html):
        assert html.count('class="tab-panel') == 3

    def test_metrics_active_by_default(self, html):
        assert 'class="tab-panel active" data-tab="metrics"' in html

    def test_chart_canvases_still_present(self, html):
        for cid in ["milestone-donut", "dcma-bar-chart", "evm-sparklines",
                    "health-history-chart", "portfolio-donut", "baseline-drift-chart"]:
            assert cid in html, f"Missing canvas/container id: {cid}"

    def test_demo_mode_still_works(self, dash_client):
        r = dash_client.get("/?demo=1")
        assert r.status_code == 200
        assert "IMS Command Center" in r.text

    def test_legacy_rollback_still_works(self, tmp_path, monkeypatch):
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
        assert "app-shell" not in html
        assert "IMS Agent — Schedule Dashboard" in html
