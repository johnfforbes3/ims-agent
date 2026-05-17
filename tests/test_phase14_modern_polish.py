"""
Phase 14 — Modern Polish Pass tests.

Locks in the visual polish layer added on top of Phase 12 / 12.1:

  14.1  Glassmorphism cards (backdrop-filter blur)
        Animated gradient body background
  14.2  Conic-gradient progress rings (.progress-ring utility)
        Animated KPI number counters (data-target attribute)
  14.3  Skeleton loaders (.skeleton / .skel-line / .skel-block)
        View Transitions API hook on tab switch
  14.4  Hover micro-interactions (transforms + transitions)
        Aurora gradient strip below header
  14.5  Chart.js global animation tuning (easeOutQuart entry)

These tests verify that every CSS rule and JS helper is present in the
served assets.  No layout/structural change is asserted — Phase 14 is
purely additive on top of Phase 12.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Phase 15 — see conftest.py. Phase 14 tests assert against the Phase 12
# dashboard CSS (now the legacy template). Skipped by default; enable
# with `pytest -m legacy` or `IMS_LEGACY_DASHBOARD=1`.
pytestmark = pytest.mark.legacy


_MIN_STATE = {
    "cycle_id": "20260508T120000Z",
    "timestamp": "2026-05-08T12:00:00Z",
    "schedule_health": "YELLOW",
    "last_updated": "2026-05-08T12:00:00Z",
    "milestones": [
        {"milestone_name": "PDR", "baseline_date": "2026-06-15",
         "p50_date": "2026-06-20", "p95_date": "2026-07-05",
         "prob_on_baseline": 0.35, "risk_level": "HIGH"},
        {"milestone_name": "CDR", "baseline_date": "2026-09-01",
         "p50_date": "2026-09-05", "p95_date": "2026-09-22",
         "prob_on_baseline": 0.55, "risk_level": "MEDIUM"},
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


@pytest.fixture()
def core_js(dash_client):
    return dash_client.get("/static/js/dashboard-core.js").text


@pytest.fixture()
def metrics_js(dash_client):
    return dash_client.get("/static/js/metrics-tab.js").text


# ===========================================================================
# 14.1 — Glassmorphism + animated gradient
# ===========================================================================


class TestGlassmorphism:
    def test_backdrop_filter_on_cards(self, css):
        # Cards (kpi-card / .card / .panel etc.) must use backdrop-filter
        assert "backdrop-filter:" in css

    def test_webkit_backdrop_filter_fallback(self, css):
        # Safari/iOS fallback prefix
        assert "-webkit-backdrop-filter" in css

    def test_animated_body_gradient_keyframes(self, css):
        assert "@keyframes phase14-bg-pan" in css

    def test_aurora_strip_keyframes(self, css):
        assert "@keyframes phase14-aurora" in css

    def test_card_glass_inset_highlight(self, css):
        # Polished aluminum: 1px white inset highlight on top edge
        assert "inset 0 1px 0 rgba(255, 255, 255" in css

    def test_reduced_motion_disables_bg_animation(self, css):
        # @media (prefers-reduced-motion: reduce) must zero out animation
        assert "prefers-reduced-motion: reduce" in css


# ===========================================================================
# 14.2 — Conic progress rings + animated KPI counters
# ===========================================================================


class TestProgressRings:
    def test_progress_ring_class_in_css(self, css):
        assert ".progress-ring" in css

    def test_progress_ring_uses_conic_gradient(self, css):
        # The ring is a conic-gradient with --pct custom property
        assert "conic-gradient" in css
        assert "--pct" in css

    def test_progress_ring_severity_modifiers(self, css):
        for mod in [".progress-ring.danger", ".progress-ring.warning",
                    ".progress-ring.ok", ".progress-ring.accent"]:
            assert mod in css, f"Missing severity modifier: {mod}"

    def test_progress_ring_size_variant(self, css):
        assert ".progress-ring.size-lg" in css

    def test_progress_ring_used_in_metrics_tab(self, html):
        # The HIGH Risk Milestones tile in metrics has a ring
        assert 'class="progress-ring' in html
        assert "kpi-with-ring" in html

    def test_progress_ring_used_in_atlas_tab(self, html):
        # ATLAS CAMs Responded tile also has a ring
        # (Both rings present on a single page; just confirm count >= 2)
        assert html.count('class="progress-ring') >= 2


class TestAnimatedCounters:
    def test_animate_number_function_in_core_js(self, core_js):
        assert "function animateNumber(" in core_js

    def test_animate_all_kpi_counters_function(self, core_js):
        assert "_animateAllKpiCounters" in core_js

    def test_easeoutquart_easing_used(self, core_js):
        # 1 - Math.pow(1 - t, 4) is easeOutQuart
        assert "Math.pow(1 - t, 4)" in core_js

    def test_kpi_value_uses_tabular_nums(self, css):
        # tabular-nums prevents digits from reflowing during count-up
        assert "tabular-nums" in css

    def test_kpi_tiles_have_data_target(self, html):
        # At least one .kpi-value carries data-target="…"
        assert "data-target=" in html

    def test_set_progress_ring_function(self, core_js):
        assert "function setProgressRing(" in core_js


# ===========================================================================
# 14.3 — Skeleton loaders + View Transitions API
# ===========================================================================


class TestSkeletonLoaders:
    def test_skeleton_class_in_css(self, css):
        assert ".skeleton" in css
        assert ".skel-line" in css
        assert ".skel-block" in css

    def test_shimmer_keyframes(self, css):
        assert "@keyframes phase14-shimmer" in css

    def test_skeleton_uses_linear_gradient_sweep(self, css):
        # 200% background-size with linear-gradient is the shimmer trick
        assert "200% 100%" in css

    def test_mark_skeleton_helper(self, core_js):
        assert "function markSkeleton(" in core_js

    def test_clear_skeleton_helper(self, core_js):
        assert "function clearSkeleton(" in core_js


class TestViewTransitions:
    def test_view_transition_supports_query(self, css):
        # The block is wrapped in @supports (view-transition-name: none)
        assert "@supports (view-transition-name" in css

    def test_view_transition_in_out_keyframes(self, css):
        assert "@keyframes phase14-vt-out" in css
        assert "@keyframes phase14-vt-in" in css

    def test_tab_content_transition_name(self, css):
        assert "view-transition-name: tab-content" in css

    def test_activate_tab_uses_start_view_transition(self, core_js):
        assert "document.startViewTransition" in core_js

    def test_view_transition_respects_reduced_motion(self, core_js):
        # The wrapper checks prefers-reduced-motion before opting in
        assert "prefers-reduced-motion: reduce" in core_js


# ===========================================================================
# 14.4 — Hover micro-interactions
# ===========================================================================


class TestMicroInteractions:
    def test_card_hover_translate_y(self, css):
        # .kpi-card:hover and .card:hover should translateY(-2px)
        assert "translateY(-2px)" in css

    def test_btn_active_press_animation(self, css):
        # .btn:active translates down 1px for tactile press
        assert ".btn:active" in css

    def test_chip_hover_lift(self, css):
        assert "translateY(-1px)" in css

    def test_tab_btn_gradient_underline(self, css):
        # New gradient-underline pattern via ::after
        assert ".tab-btn::after" in css
        assert "linear-gradient(90deg, #1f6feb" in css

    def test_btn_primary_gradient_sheen(self, css):
        assert "linear-gradient(135deg, #1f6feb" in css

    def test_logo_hover_rotation(self, css):
        # .header-logo:hover rotates -3deg + scale 1.05
        assert ".header-logo:hover" in css
        assert "rotate(-3deg)" in css

    def test_progress_card_breathe_animation(self, css):
        assert "@keyframes phase14-breathe" in css


# ===========================================================================
# 14.5 — Chart.js animation tuning
# ===========================================================================


class TestChartAnimationTuning:
    def test_chart_defaults_animation_block(self, metrics_js):
        # We set Chart.defaults.animation = { duration, easing }
        assert "Chart.defaults.animation" in metrics_js
        assert "easeOutQuart" in metrics_js

    def test_chart_global_font_set(self, metrics_js):
        assert "Chart.defaults.font.family" in metrics_js

    def test_chart_tooltip_polish(self, metrics_js):
        # Rounded corners + caretSize on the global tooltip defaults
        assert "cornerRadius:" in metrics_js
        assert "caretSize:" in metrics_js

    def test_chart_line_polish_defaults(self, metrics_js):
        # Thicker lines + smooth tension by default
        assert "Chart.defaults.elements.line.borderWidth" in metrics_js
        assert "Chart.defaults.elements.line.tension" in metrics_js

    def test_chart_bar_border_radius(self, metrics_js):
        assert "Chart.defaults.elements.bar.borderRadius" in metrics_js

    def test_chart_container_fadeup_animation(self, css):
        assert "@keyframes phase14-fadeup" in css


# ===========================================================================
# Regression guard — Phase 12 / 12.1 features still wired
# ===========================================================================


class TestPhase12RegressionGuard:
    def test_three_tabs_still_present(self, html):
        assert html.count('class="tab-btn') == 3

    def test_three_tab_panels_still_present(self, html):
        assert html.count('class="tab-panel') == 3

    def test_chart_canvases_still_present(self, html):
        for cid in ["milestone-donut", "dcma-bar-chart", "evm-sparklines",
                    "health-history-chart", "portfolio-donut", "baseline-drift-chart"]:
            assert cid in html, f"Missing canvas/container id: {cid}"

    def test_demo_mode_still_works(self, dash_client):
        r = dash_client.get("/?demo=1")
        assert r.status_code == 200
        assert "IMS Command Center" in r.text

    def test_theme_toggle_still_present(self, html):
        assert 'id="theme-toggle"' in html

    def test_keyboard_shortcuts_still_wired(self, core_js):
        # Phase 12.1 — Ctrl/Cmd + 1/2/3 + L
        assert "ctrlKey" in core_js or "metaKey" in core_js
