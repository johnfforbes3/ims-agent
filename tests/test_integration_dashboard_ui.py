"""
Comprehensive element-by-element dashboard UI tests.

Verifies every visible panel, card, button, table, element ID, text label, data
value, and JavaScript API-path reference in agent/dashboard/templates/index.html
against the realistic state fixture used throughout the smoke-test suite.

Structure mirrors the dashboard layout:
  ✓ Page structure (HTML document validity)
  ✓ Header  — logo, title, subtitle, countdown, trigger button
  ✓ Health banner  — class, emoji, label, cycle_id rendered in meta
  ✓ Validation alerts — hidden when validation_holds=[]
  ✓ KPI cards  — all four labels + sub-labels + rendered values
  ✓ Milestone Risk Summary — heading, column headers, PDR/CDR names,
                              dates, probabilities, risk badges
  ✓ CAM Response Status  — heading, table id, column headers,
                            all 5 CAM names, Responded/No-Response
  ✓ Top Risks — heading, content present
  ✓ Tasks Behind Schedule — heading, empty-state message
  ✓ Critical Path — heading with count, task chips, float label
  ✓ Schedule Health History — heading
  ✓ Q&A Chat Widget — heading, all 8 chip labels, element IDs, buttons
  ✓ Cycle In Progress card  — element IDs (hidden by default)
  ✓ What Changed (diff) panel — id, title, element IDs
  ✓ Change History panel  — id, title, element IDs (from/to inputs, csv link)
  ✓ Baseline Drift panel  — id, title, element IDs
  ✓ Executive Briefing button — button text, description, onclick reference
  ✓ EVM panel  — id, title, element IDs (health badge, status, cards, table)
  ✓ DCMA 14-Point panel  — id, title, element IDs (score badge, scorecard, table)
  ✓ Variance Narrative panel  — id, CPR Format 5 label, element IDs
  ✓ Portfolio panel  — id, title, element IDs (at-risk badge, tiles)
  ✓ Live Interview Listen-In panel  — id, title, all button labels,
                                      dropdown, speaking indicator,
                                      autoplay toggle, volume slider,
                                      transcript container, empty state
  ✓ JavaScript API paths  — every fetch/EventSource URL in the page JS
"""

import json

import pytest
from fastapi.testclient import TestClient

# Phase 15 — these tests target the Phase 12/12.1/14 monolithic dashboard
# layout (index.html with server-rendered element IDs).  The Phase 15
# React rebuild injects IDs client-side, so these element-by-element
# assertions don't apply to the live `/` route.  They remain valid as a
# regression suite for the preserved legacy template — enable with
# `pytest -m legacy` or `IMS_LEGACY_DASHBOARD=1`.
pytestmark = pytest.mark.legacy


# ---------------------------------------------------------------------------
# Shared state fixture (identical to test_integration_api_smoke._STATE)
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
    "cam_status": {
        "Alice Nguyen":  {"responded": True,  "tasks_updated": 6,  "blockers": 1},
        "Bob Martinez":  {"responded": False, "tasks_updated": 0,  "blockers": 0},
        "Carol Smith":   {"responded": True,  "tasks_updated": 7,  "blockers": 0},
        "David Lee":     {"responded": True,  "tasks_updated": 7,  "blockers": 0},
        "Eva Johnson":   {"responded": True,  "tasks_updated": 15, "blockers": 2},
    },
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
            {"id": "01", "name": "Logic", "passed": True,  "pct": 0.0, "threshold_pct": 5.0, "violations": 0, "flagged": []},
            {"id": "02", "name": "Leads", "passed": True,  "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "03", "name": "Lags",  "passed": False, "pct": 8.0, "threshold_pct": 5.0, "violations": 7, "flagged": ["SE-04"]},
            {"id": "04", "name": "FS relationships", "passed": True, "pct": 85.0, "threshold_pct": 90.0, "violations": 0, "flagged": []},
            {"id": "05", "name": "Hard constraints",  "passed": False, "pct": 6.0, "threshold_pct": 5.0, "violations": 5, "flagged": ["PROG-01"]},
            {"id": "06", "name": "High float",         "passed": True,  "pct": 2.0, "threshold_pct": 5.0, "violations": 2, "flagged": []},
            {"id": "07", "name": "Negative float",     "passed": True,  "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "08", "name": "High duration",      "passed": True,  "pct": 3.0, "threshold_pct": 5.0, "violations": 3, "flagged": []},
            {"id": "09", "name": "Invalid dates",      "passed": True,  "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "10", "name": "Resources",          "passed": True,  "pct": 0.0, "threshold_pct": 5.0, "violations": 0, "flagged": []},
            {"id": "11", "name": "Missed baseline",    "passed": False, "pct": 10.0, "threshold_pct": 5.0, "violations": 9, "flagged": []},
            {"id": "12", "name": "Critical path",      "passed": True,  "pct": 15.0, "threshold_pct": 30.0, "violations": 0, "flagged": []},
            {"id": "13", "name": "BEI",                "passed": True,  "pct": 0.0, "threshold_pct": 0.0, "violations": 0, "flagged": []},
            {"id": "14", "name": "Summary tasks in logic", "passed": False, "pct": 4.0, "threshold_pct": 0.0, "violations": 4, "flagged": []},
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
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def dash_client(tmp_path, monkeypatch):
    """Dashboard test client backed by the full realistic state fixture."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(_STATE), encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")
    monkeypatch.setenv("DASHBOARD_STATE_FILE", str(state_file))
    monkeypatch.setenv("PORTFOLIO_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("CALL_TRANSPORT", "simulated")
    import importlib
    import agent.dashboard.server as srv
    importlib.reload(srv)
    srv._STATE_FILE = str(state_file)
    srv._REPORTS_DIR = str(tmp_path)
    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture()
def dash_html(dash_client):
    """Concatenated HTML + linked static CSS/JS for parity assertions.

    Phase 12 — Dashboard was refactored from a single inline-script index.html
    into base.html + 3 tab partials + external CSS/JS files.  String
    assertions across the fixture now scan HTML *and* the linked assets so
    tests can keep their current shape (`"foo" in dash_html`) regardless of
    whether ``foo`` lives in the HTML or in /static/js/dashboard-core.js.
    """
    html = dash_client.get("/").text
    parts = [html]
    # Pick up every <link rel="stylesheet"> and <script src="..."> reference
    import re as _re
    for url in _re.findall(r'href="(/static/[^"]+)"', html):
        try: parts.append(dash_client.get(url).text)
        except Exception: pass
    for url in _re.findall(r'<script src="(/static/[^"]+)"', html):
        try: parts.append(dash_client.get(url).text)
        except Exception: pass
    return "\n".join(parts)


# ===========================================================================
# Page structure
# ===========================================================================

class TestPageStructure:
    def test_200(self, dash_client):
        assert dash_client.get("/").status_code == 200

    def test_content_type_is_html(self, dash_client):
        ct = dash_client.get("/").headers.get("content-type", "")
        assert "text/html" in ct

    def test_has_doctype(self, dash_html):
        assert "<!doctype html" in dash_html.lower() or "<html" in dash_html.lower()

    def test_has_closing_html_tag(self, dash_html):
        assert "</html>" in dash_html.lower()

    def test_has_head_element(self, dash_html):
        assert "<head>" in dash_html.lower() or "<head " in dash_html.lower()

    def test_has_body_element(self, dash_html):
        assert "<body>" in dash_html.lower() or "<body " in dash_html.lower()

    def test_has_closing_body_tag(self, dash_html):
        assert "</body>" in dash_html.lower()

    def test_has_closing_script_tag(self, dash_html):
        assert "</script>" in dash_html


# ===========================================================================
# Header
# ===========================================================================

class TestDashboardHeader:
    def test_logo_text(self, dash_html):
        assert "IMS" in dash_html

    def test_page_title(self, dash_html):
        assert "IMS Agent" in dash_html

    def test_schedule_dashboard_label(self, dash_html):
        # Phase 12 rename: "IMS Agent — Schedule Dashboard" → "IMS Command Center"
        assert "IMS Command Center" in dash_html

    def test_atlas_program_subtitle(self, dash_html):
        assert "ATLAS Program" in dash_html

    def test_ai_agent_server_rack_subtitle(self, dash_html):
        assert "AI Agent Server Rack" in dash_html

    def test_refresh_badge_present(self, dash_html):
        assert "Refresh in" in dash_html

    def test_countdown_element_id(self, dash_html):
        assert 'id="countdown"' in dash_html

    def test_countdown_initial_value(self, dash_html):
        assert ">60<" in dash_html

    def test_trigger_button_id(self, dash_html):
        assert 'id="trigger-btn"' in dash_html

    def test_trigger_button_label(self, dash_html):
        assert "Trigger Cycle" in dash_html

    def test_trigger_button_onclick(self, dash_html):
        assert "triggerCycle()" in dash_html

    def test_trigger_button_has_primary_class(self, dash_html):
        assert "btn-primary" in dash_html


# ===========================================================================
# Health Banner
# ===========================================================================

class TestHealthBanner:
    def test_health_banner_element_present(self, dash_html):
        assert "health-banner" in dash_html

    def test_health_banner_has_yellow_class(self, dash_html):
        # _STATE has schedule_health = "YELLOW"
        assert "health-banner YELLOW" in dash_html

    def test_health_label_yellow(self, dash_html):
        assert "health-label" in dash_html
        assert ">YELLOW<" in dash_html

    def test_yellow_emoji_rendered(self, dash_html):
        assert "🟡" in dash_html

    def test_health_meta_contains_cycle_id(self, dash_html):
        assert "20260507T100000Z" in dash_html

    def test_health_meta_contains_cycle_label(self, dash_html):
        assert "Cycle " in dash_html

    def test_health_meta_contains_last_updated_label(self, dash_html):
        assert "Last updated" in dash_html

    def test_health_dot_element(self, dash_html):
        assert "health-dot" in dash_html


# ===========================================================================
# Validation Alerts (empty → panel hidden)
# ===========================================================================

class TestValidationAlerts:
    def test_alert_panel_absent_when_no_holds(self, dash_html):
        # validation_holds=[] → the <details class="alert-panel"> block is not rendered.
        # Note: "Validation Alerts" appears in an HTML comment, so we check for
        # the specific rendered "hold(s) flagged" text that only appears when holds>0.
        assert "hold(s) flagged" not in dash_html

    def test_alert_panel_shows_when_holds_exist(self, tmp_path, monkeypatch):
        state_with_holds = dict(_STATE)
        state_with_holds["validation_holds"] = [
            {"task_id": "SE-99", "cam_name": "Test CAM",
             "rule": "BACKWARDS_MOVEMENT", "detail": "pct went 80→60"}
        ]
        sf = tmp_path / "state_holds.json"
        sf.write_text(json.dumps(state_with_holds), encoding="utf-8")
        monkeypatch.setenv("DASHBOARD_API_KEY", "")
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(sf))
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        import importlib, agent.dashboard.server as srv
        importlib.reload(srv)
        srv._STATE_FILE = str(sf)
        client = TestClient(srv.app, raise_server_exceptions=False)
        html = client.get("/").text
        assert "Validation Alerts" in html
        assert "1 hold(s)" in html
        assert "SE-99" in html
        assert "Test CAM" in html

    def test_alert_table_columns(self, tmp_path, monkeypatch):
        state_with_holds = dict(_STATE)
        state_with_holds["validation_holds"] = [
            {"task_id": "T01", "cam_name": "Alice", "rule": "RULE_X", "detail": "detail text"}
        ]
        sf = tmp_path / "state_h2.json"
        sf.write_text(json.dumps(state_with_holds), encoding="utf-8")
        monkeypatch.setenv("DASHBOARD_API_KEY", "")
        monkeypatch.setenv("DASHBOARD_STATE_FILE", str(sf))
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
        import importlib, agent.dashboard.server as srv
        importlib.reload(srv)
        srv._STATE_FILE = str(sf)
        client = TestClient(srv.app, raise_server_exceptions=False)
        html = client.get("/").text
        for col in ("Task", "CAM", "Rule", "Detail"):
            assert f"<th>{col}</th>" in html, f"Alert table missing column: {col}"


# ===========================================================================
# KPI Cards
# ===========================================================================

class TestKPICards:
    def test_cams_responded_label(self, dash_html):
        assert "CAMs Responded" in dash_html

    def test_cams_responded_sub_label(self, dash_html):
        assert "This cycle" in dash_html

    def test_high_risk_milestones_label(self, dash_html):
        assert "HIGH Risk Milestones" in dash_html

    def test_high_risk_milestones_sub_label(self, dash_html):
        assert "milestones" in dash_html

    def test_tasks_behind_blocker_label(self, dash_html):
        assert "Tasks Behind w/ Blocker" in dash_html

    def test_tasks_behind_sub_label(self, dash_html):
        assert "Active blockers" in dash_html

    def test_critical_path_tasks_label(self, dash_html):
        assert "Critical Path Tasks" in dash_html

    def test_zero_float_sub_label(self, dash_html):
        assert "Zero float" in dash_html

    def test_kpi_grid_present(self, dash_html):
        assert "kpi-grid" in dash_html

    def test_kpi_card_present(self, dash_html):
        assert "kpi-card" in dash_html

    def test_critical_path_count_3(self, dash_html):
        # _STATE has 3 critical path task IDs → KPI value = "3"
        assert ">3<" in dash_html

    def test_high_risk_milestone_count_1(self, dash_html):
        # PDR is HIGH → 1 HIGH risk milestone → KPI = "1"
        # (value appears as ">1<" in the kpi-value div)
        assert ">1<" in dash_html


# ===========================================================================
# Milestone Risk Summary
# ===========================================================================

class TestMilestoneRiskSummary:
    def test_heading(self, dash_html):
        assert "Milestone Risk Summary" in dash_html

    def test_column_milestone(self, dash_html):
        assert "<th>Milestone</th>" in dash_html

    def test_column_baseline(self, dash_html):
        assert "<th>Baseline</th>" in dash_html

    def test_column_p50(self, dash_html):
        assert "<th>P50</th>" in dash_html

    def test_column_p95(self, dash_html):
        assert "<th>P95</th>" in dash_html

    def test_column_on_time(self, dash_html):
        assert "<th>On-Time</th>" in dash_html

    def test_column_risk(self, dash_html):
        assert "<th>Risk</th>" in dash_html

    def test_pdr_milestone_name(self, dash_html):
        assert ">PDR<" in dash_html

    def test_cdr_milestone_name(self, dash_html):
        assert ">CDR<" in dash_html

    def test_pdr_baseline_date(self, dash_html):
        assert "2026-06-15" in dash_html

    def test_cdr_baseline_date(self, dash_html):
        assert "2026-08-20" in dash_html

    def test_pdr_p50_date(self, dash_html):
        assert "2026-06-20" in dash_html

    def test_cdr_p50_date(self, dash_html):
        assert "2026-08-22" in dash_html

    def test_pdr_p95_date(self, dash_html):
        assert "2026-07-05" in dash_html

    def test_cdr_p95_date(self, dash_html):
        assert "2026-09-04" in dash_html

    def test_pdr_on_time_probability(self, dash_html):
        # 0.35 * 100 = 35%
        assert "35%" in dash_html

    def test_cdr_on_time_probability(self, dash_html):
        # 0.90 * 100 = 90%
        assert "90%" in dash_html

    def test_high_badge(self, dash_html):
        assert "badge-HIGH" in dash_html

    def test_low_badge(self, dash_html):
        assert "badge-LOW" in dash_html

    def test_risk_badge_text_high(self, dash_html):
        assert ">HIGH<" in dash_html

    def test_risk_badge_text_low(self, dash_html):
        assert ">LOW<" in dash_html


# ===========================================================================
# CAM Response Status
# ===========================================================================

class TestCAMResponseStatus:
    def test_heading(self, dash_html):
        assert "CAM Response Status" in dash_html

    def test_table_id(self, dash_html):
        assert 'id="cam-status-table"' in dash_html

    def test_column_cam(self, dash_html):
        assert "<th>CAM</th>" in dash_html

    def test_column_status(self, dash_html):
        assert "<th>Status</th>" in dash_html

    def test_column_attempts(self, dash_html):
        assert "<th>Attempts</th>" in dash_html

    def test_column_outcome(self, dash_html):
        assert "<th>Outcome</th>" in dash_html

    def test_alice_nguyen_present(self, dash_html):
        assert "Alice Nguyen" in dash_html

    def test_bob_martinez_present(self, dash_html):
        assert "Bob Martinez" in dash_html

    def test_carol_smith_present(self, dash_html):
        assert "Carol Smith" in dash_html

    def test_david_lee_present(self, dash_html):
        assert "David Lee" in dash_html

    def test_eva_johnson_present(self, dash_html):
        assert "Eva Johnson" in dash_html

    def test_responded_status_text(self, dash_html):
        assert "Responded" in dash_html

    def test_no_response_status_text(self, dash_html):
        assert "No Response" in dash_html

    def test_data_cam_attribute_alice(self, dash_html):
        assert 'data-cam="Alice Nguyen"' in dash_html

    def test_data_cam_attribute_bob(self, dash_html):
        assert 'data-cam="Bob Martinez"' in dash_html

    def test_outcome_completed(self, dash_html):
        assert "completed" in dash_html

    def test_outcome_no_answer(self, dash_html):
        assert "no_answer" in dash_html

    def test_dot_ok_class(self, dash_html):
        assert "dot-ok" in dash_html

    def test_dot_miss_class(self, dash_html):
        assert "dot-miss" in dash_html


# ===========================================================================
# Top Risks
# ===========================================================================

class TestTopRisks:
    def test_heading(self, dash_html):
        assert ">Top Risks<" in dash_html

    def test_risks_text_class(self, dash_html):
        assert "risks-text" in dash_html

    def test_risk_content_vendor_delay(self, dash_html):
        # From _STATE["top_risks"][0]
        assert "vendor delay" in dash_html

    def test_risk_content_se04(self, dash_html):
        assert "SE-04" in dash_html

    def test_risk_content_firewall(self, dash_html):
        assert "firewall" in dash_html


# ===========================================================================
# Tasks Behind Schedule
# ===========================================================================

class TestTasksBehindSchedule:
    def test_heading(self, dash_html):
        assert "Tasks Behind Schedule" in dash_html

    def test_with_blockers_in_heading(self, dash_html):
        assert "Blockers" in dash_html or "blockers" in dash_html

    def test_empty_state_no_tasks_behind(self, dash_html):
        # _STATE has no 'tasks_behind' key (uses 'tasks_behind_with_blockers')
        # → template renders empty state message
        assert "No behind-schedule tasks with blockers" in dash_html


# ===========================================================================
# Critical Path
# ===========================================================================

class TestCriticalPath:
    def test_heading_with_count(self, dash_html):
        assert "Critical Path Task IDs" in dash_html
        assert "3 tasks" in dash_html

    def test_zero_days_float(self, dash_html):
        assert "0 days float" in dash_html

    def test_chip_se01(self, dash_html):
        assert ">SE-01<" in dash_html

    def test_chip_se04(self, dash_html):
        assert ">SE-04<" in dash_html

    def test_chip_int02(self, dash_html):
        assert ">INT-02<" in dash_html

    def test_chip_class(self, dash_html):
        assert 'class="chip"' in dash_html


# ===========================================================================
# Schedule Health History
# ===========================================================================

class TestHealthHistory:
    def test_heading(self, dash_html):
        assert "Schedule Health History" in dash_html

    def test_last_n_cycles_label(self, dash_html):
        # Phase 12: heading became "Schedule Health History — Trend"; the
        # detailed-history details element keeps "last N cycles" wording.
        assert "cycles" in dash_html.lower()


# ===========================================================================
# Q&A Chat Widget
# ===========================================================================

class TestQAChatWidget:
    def test_heading(self, dash_html):
        assert "Ask the IMS Agent" in dash_html

    def test_chat_chip_class(self, dash_html):
        assert "chat-chip" in dash_html

    def test_chip_critical_path(self, dash_html):
        assert "Critical path?" in dash_html

    def test_chip_top_risks(self, dash_html):
        assert "Top risks?" in dash_html

    def test_chip_focus_this_week(self, dash_html):
        assert "Focus this week?" in dash_html

    def test_chip_terminal_milestone(self, dash_html):
        assert "Terminal milestone?" in dash_html

    def test_chip_alice_nguyen(self, dash_html):
        assert "Alice Nguyen?" in dash_html

    def test_chip_changes_this_cycle(self, dash_html):
        assert "Changes this cycle?" in dash_html

    def test_chip_schedule_health(self, dash_html):
        assert "Schedule health?" in dash_html

    def test_chip_pm_actions(self, dash_html):
        assert "PM actions?" in dash_html

    def test_chat_messages_id(self, dash_html):
        assert 'id="chat-messages"' in dash_html

    def test_chat_input_id(self, dash_html):
        assert 'id="chat-input"' in dash_html

    def test_chat_input_placeholder(self, dash_html):
        assert "probability of hitting CDR" in dash_html

    def test_chat_input_maxlength(self, dash_html):
        assert "maxlength" in dash_html

    def test_ask_button_id(self, dash_html):
        assert 'id="chat-send-btn"' in dash_html

    def test_ask_button_label(self, dash_html):
        assert ">Ask<" in dash_html

    def test_clear_chat_button(self, dash_html):
        assert "clearChat()" in dash_html

    def test_send_chat_js_function(self, dash_html):
        assert "sendChat()" in dash_html

    def test_initial_assistant_message(self, dash_html):
        assert "Ask me anything about the schedule" in dash_html


# ===========================================================================
# Cycle In Progress Card (hidden by default when no active cycle)
# ===========================================================================

class TestCycleInProgressCard:
    def test_card_id_present(self, dash_html):
        assert 'id="cycle-progress-card"' in dash_html

    def test_card_hidden_by_default(self, dash_html):
        # When no active cycle (_STATE has no current_cycle), card is hidden
        assert "display:none" in dash_html

    def test_phase_span_id(self, dash_html):
        assert 'id="cp-phase"' in dash_html

    def test_cycle_span_id(self, dash_html):
        assert 'id="cp-cycle"' in dash_html

    def test_cams_span_id(self, dash_html):
        assert 'id="cp-cams"' in dash_html

    def test_cam_progress_id(self, dash_html):
        assert 'id="cp-cam-progress"' in dash_html

    def test_cycle_in_progress_heading(self, dash_html):
        assert "Cycle In Progress" in dash_html


# ===========================================================================
# What Changed — IMS Diff Viewer Panel
# ===========================================================================

class TestWhatChangedPanel:
    def test_panel_id(self, dash_html):
        assert 'id="what-changed-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "What Changed" in dash_html

    def test_ims_diff_viewer_label(self, dash_html):
        assert "IMS Diff Viewer" in dash_html

    def test_icon_present(self, dash_html):
        assert "🔄" in dash_html

    def test_diff_count_badge_id(self, dash_html):
        assert 'id="diff-count-badge"' in dash_html

    def test_diff_cycle_input_id(self, dash_html):
        assert 'id="diff-cycle-input"' in dash_html

    def test_diff_cycle_input_has_value(self, dash_html):
        # value="{{ state.get('cycle_id', '') }}"
        assert 'value="20260507T100000Z"' in dash_html

    def test_diff_status_id(self, dash_html):
        assert 'id="diff-status"' in dash_html

    def test_diff_table_container_id(self, dash_html):
        assert 'id="diff-table-container"' in dash_html

    def test_load_diff_button(self, dash_html):
        assert "loadDiff()" in dash_html

    def test_cycle_id_placeholder(self, dash_html):
        assert "20260505T004516Z" in dash_html


# ===========================================================================
# Change History — Cumulative Diff Panel
# ===========================================================================

class TestChangeHistoryPanel:
    def test_panel_id(self, dash_html):
        assert 'id="change-history-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "Change History" in dash_html

    def test_cumulative_diff_label(self, dash_html):
        assert "Cumulative Diff" in dash_html

    def test_icon_present(self, dash_html):
        assert "📋" in dash_html

    def test_ch_count_badge_id(self, dash_html):
        assert 'id="ch-count-badge"' in dash_html

    def test_ch_from_input_id(self, dash_html):
        assert 'id="ch-from"' in dash_html

    def test_ch_to_input_id(self, dash_html):
        assert 'id="ch-to"' in dash_html

    def test_ch_status_id(self, dash_html):
        assert 'id="ch-status"' in dash_html

    def test_ch_table_container_id(self, dash_html):
        assert 'id="ch-table-container"' in dash_html

    def test_ch_csv_link_id(self, dash_html):
        assert 'id="ch-csv-link"' in dash_html

    def test_from_label(self, dash_html):
        assert ">From:<" in dash_html

    def test_to_label(self, dash_html):
        assert ">To:<" in dash_html

    def test_load_changes_button(self, dash_html):
        assert "loadChanges()" in dash_html

    def test_csv_download_label(self, dash_html):
        assert "CSV" in dash_html


# ===========================================================================
# Baseline Drift Report Panel
# ===========================================================================

class TestBaselineDriftPanel:
    def test_panel_id(self, dash_html):
        assert 'id="baseline-drift-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "Baseline Drift Report" in dash_html

    def test_icon_present(self, dash_html):
        assert "📐" in dash_html

    def test_bd_count_badge_id(self, dash_html):
        assert 'id="bd-count-badge"' in dash_html

    def test_bd_status_id(self, dash_html):
        assert 'id="bd-status"' in dash_html

    def test_bd_table_container_id(self, dash_html):
        assert 'id="bd-table-container"' in dash_html

    def test_load_baseline_drift_button(self, dash_html):
        assert "loadBaselineDrift()" in dash_html


# ===========================================================================
# Executive Briefing Button
# ===========================================================================

class TestExecutiveBriefingButton:
    def test_button_label(self, dash_html):
        assert "Generate Executive Briefing" in dash_html

    def test_clipboard_icon(self, dash_html):
        assert "📋" in dash_html

    def test_open_briefing_onclick(self, dash_html):
        assert "openBriefing()" in dash_html

    def test_one_click_brief_description(self, dash_html):
        # Phase 12: rephrased to "One-click HTML report:" on the PM tab card.
        assert "One-click" in dash_html

    def test_evm_in_description(self, dash_html):
        assert "EVM" in dash_html

    def test_dcma_in_description(self, dash_html):
        assert "DCMA" in dash_html

    def test_milestones_in_description(self, dash_html):
        assert "milestones" in dash_html

    def test_variance_in_description(self, dash_html):
        assert "variance" in dash_html


# ===========================================================================
# EVM Panel
# ===========================================================================

class TestEVMPanel:
    def test_panel_id(self, dash_html):
        assert 'id="evm-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "Earned Value Metrics" in dash_html

    def test_evm_abbreviation(self, dash_html):
        assert "EVM" in dash_html

    def test_icon_present(self, dash_html):
        assert "📊" in dash_html

    def test_evm_health_badge_id(self, dash_html):
        assert 'id="evm-health-badge"' in dash_html

    def test_evm_status_id(self, dash_html):
        assert 'id="evm-status"' in dash_html

    def test_evm_program_cards_id(self, dash_html):
        assert 'id="evm-program-cards"' in dash_html

    def test_evm_cam_table_id(self, dash_html):
        assert 'id="evm-cam-table"' in dash_html

    def test_refresh_button(self, dash_html):
        assert "loadEvm()" in dash_html

    def test_panel_chevron(self, dash_html):
        assert "panel-chevron" in dash_html


# ===========================================================================
# DCMA 14-Point Assessment Panel
# ===========================================================================

class TestDCMAPanel:
    def test_panel_id(self, dash_html):
        assert 'id="dcma-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "DCMA 14-Point Assessment" in dash_html

    def test_icon_present(self, dash_html):
        assert "✅" in dash_html

    def test_dcma_score_badge_id(self, dash_html):
        assert 'id="dcma-score-badge"' in dash_html

    def test_dcma_status_id(self, dash_html):
        assert 'id="dcma-status"' in dash_html

    def test_dcma_scorecard_id(self, dash_html):
        assert 'id="dcma-scorecard"' in dash_html

    def test_dcma_checks_table_id(self, dash_html):
        assert 'id="dcma-checks-table"' in dash_html

    def test_refresh_button(self, dash_html):
        assert "loadDcma()" in dash_html


# ===========================================================================
# Variance Analysis Narrative Panel
# ===========================================================================

class TestVariancePanel:
    def test_panel_id(self, dash_html):
        assert 'id="variance-panel"' in dash_html

    def test_panel_title_variance(self, dash_html):
        assert "Variance" in dash_html

    def test_schedule_variance_label(self, dash_html):
        assert "Schedule Variance Narrative" in dash_html

    def test_cpr_format_5_label(self, dash_html):
        assert "CPR Format 5" in dash_html

    def test_icon_present(self, dash_html):
        assert "📝" in dash_html

    def test_variance_status_id(self, dash_html):
        assert 'id="variance-status"' in dash_html

    def test_variance_text_id(self, dash_html):
        assert 'id="variance-text"' in dash_html

    def test_refresh_button(self, dash_html):
        assert "loadVariance()" in dash_html

    def test_default_variance_placeholder(self, dash_html):
        assert "No variance narrative yet" in dash_html


# ===========================================================================
# Portfolio View Panel
# ===========================================================================

class TestPortfolioPanel:
    def test_panel_id(self, dash_html):
        assert 'id="portfolio-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "Portfolio View" in dash_html

    def test_icon_present(self, dash_html):
        assert "🗂️" in dash_html

    def test_portfolio_at_risk_badge_id(self, dash_html):
        assert 'id="portfolio-at-risk-badge"' in dash_html

    def test_portfolio_status_id(self, dash_html):
        assert 'id="portfolio-status"' in dash_html

    def test_portfolio_tiles_id(self, dash_html):
        assert 'id="portfolio-tiles"' in dash_html

    def test_refresh_button(self, dash_html):
        assert "loadPortfolio()" in dash_html


# ===========================================================================
# Live Interview Listen-In Panel
# ===========================================================================

class TestListenInPanel:
    def test_panel_id(self, dash_html):
        assert 'id="listenin-panel"' in dash_html

    def test_panel_title(self, dash_html):
        assert "Live Interview Listen-In" in dash_html

    def test_icon_present(self, dash_html):
        assert "🎙️" in dash_html

    def test_listenin_session_badge_id(self, dash_html):
        assert 'id="listenin-session-badge"' in dash_html

    def test_listenin_sessions_id(self, dash_html):
        assert 'id="listenin-sessions"' in dash_html

    def test_no_active_interviews_idle_pill(self, dash_html):
        assert "No active interviews" in dash_html

    def test_connect_button_id(self, dash_html):
        assert 'id="listenin-connect-btn"' in dash_html

    def test_connect_button_label(self, dash_html):
        assert "▶ Connect" in dash_html

    def test_connect_button_onclick(self, dash_html):
        assert "listenInConnect()" in dash_html

    def test_disconnect_button_id(self, dash_html):
        assert 'id="listenin-disconnect-btn"' in dash_html

    def test_disconnect_button_label(self, dash_html):
        assert "■ Disconnect" in dash_html

    def test_disconnect_button_onclick(self, dash_html):
        assert "listenInDisconnect()" in dash_html

    def test_clear_button(self, dash_html):
        assert "listenInClear()" in dash_html

    def test_cam_select_id(self, dash_html):
        assert 'id="listenin-cam-select"' in dash_html

    def test_cam_select_onchange(self, dash_html):
        assert "listenInFilterChange()" in dash_html

    def test_all_interviews_default_option(self, dash_html):
        assert "All interviews" in dash_html

    def test_listenin_status_id(self, dash_html):
        assert 'id="listenin-status"' in dash_html

    def test_not_connected_default_status(self, dash_html):
        assert "Not connected" in dash_html

    def test_autoplay_checkbox_id(self, dash_html):
        assert 'id="listenin-autoplay"' in dash_html

    def test_autoplay_checked_by_default(self, dash_html):
        assert 'id="listenin-autoplay" checked' in dash_html

    def test_autoplay_label(self, dash_html):
        assert "Auto-play audio" in dash_html

    def test_volume_range_id(self, dash_html):
        assert 'id="listenin-volume"' in dash_html

    def test_volume_range_min_max(self, dash_html):
        assert 'min="0"' in dash_html
        assert 'max="1"' in dash_html

    def test_volume_icon(self, dash_html):
        assert "🔊" in dash_html

    def test_speaking_row_id(self, dash_html):
        assert 'id="listenin-speaking-row"' in dash_html

    def test_speaking_name_id(self, dash_html):
        assert 'id="speaking-name"' in dash_html

    def test_atlas_speaking_label(self, dash_html):
        assert "ATLAS" in dash_html

    def test_speaking_bars_class(self, dash_html):
        assert "speaking-bars" in dash_html

    def test_transcript_container_id(self, dash_html):
        assert 'id="listenin-transcript"' in dash_html

    def test_transcript_empty_state_id(self, dash_html):
        assert 'id="listenin-empty"' in dash_html

    def test_transcript_empty_state_text(self, dash_html):
        assert "Opens automatically" in dash_html

    def test_transcript_cam_side_description(self, dash_html):
        assert "ATLAS questions appear on the left" in dash_html

    def test_auto_connect_on_panel_open(self, dash_html):
        assert "auto-connect" in dash_html or "listenInConnect" in dash_html


# ===========================================================================
# JavaScript API path references
# ===========================================================================

class TestJSAPIPaths:
    def test_api_status_path(self, dash_html):
        assert "/api/status" in dash_html

    def test_api_state_path(self, dash_html):
        assert "/api/state" in dash_html

    def test_api_trigger_path(self, dash_html):
        assert "/api/trigger" in dash_html

    def test_api_trigger_force_param(self, dash_html):
        assert "/api/trigger?force=true" in dash_html

    def test_api_diff_path(self, dash_html):
        assert "/api/diff/" in dash_html

    def test_api_diff_latest_path(self, dash_html):
        assert "/api/diff/latest" in dash_html

    def test_api_changes_path(self, dash_html):
        assert "/api/changes" in dash_html

    def test_api_baseline_drift_path(self, dash_html):
        assert "/api/baseline-drift" in dash_html

    def test_api_evm_path(self, dash_html):
        assert "/api/evm" in dash_html

    def test_api_dcma_path(self, dash_html):
        assert "/api/dcma" in dash_html

    def test_api_variance_path(self, dash_html):
        assert "/api/variance" in dash_html

    def test_api_briefing_path(self, dash_html):
        assert "/api/briefing" in dash_html

    def test_api_portfolio_path(self, dash_html):
        assert "/api/portfolio" in dash_html

    def test_api_interview_sessions_path(self, dash_html):
        assert "/api/interview-sessions" in dash_html

    def test_api_interview_recent_path(self, dash_html):
        assert "/api/interview-recent" in dash_html

    def test_api_interview_stream_path(self, dash_html):
        assert "/api/interview-stream" in dash_html

    def test_api_interview_audio_path(self, dash_html):
        assert "/api/interview-audio/" in dash_html

    def test_api_ask_path(self, dash_html):
        assert "/api/ask" in dash_html

    def test_fetch_function_used(self, dash_html):
        assert "fetch(" in dash_html

    def test_eventsource_used(self, dash_html):
        assert "EventSource" in dash_html


# ===========================================================================
# JavaScript utility functions present
# ===========================================================================

class TestJSFunctions:
    def test_escape_html_function(self, dash_html):
        assert "escapeHtml" in dash_html

    def test_render_diff_table_function(self, dash_html):
        assert "_renderDiffTable" in dash_html

    def test_load_diff_function(self, dash_html):
        assert "loadDiff" in dash_html

    def test_load_changes_function(self, dash_html):
        assert "loadChanges" in dash_html

    def test_load_baseline_drift_function(self, dash_html):
        assert "loadBaselineDrift" in dash_html

    def test_load_evm_function(self, dash_html):
        assert "loadEvm" in dash_html

    def test_load_dcma_function(self, dash_html):
        assert "loadDcma" in dash_html

    def test_load_variance_function(self, dash_html):
        assert "loadVariance" in dash_html

    def test_open_briefing_function(self, dash_html):
        assert "openBriefing" in dash_html

    def test_load_portfolio_function(self, dash_html):
        assert "loadPortfolio" in dash_html

    def test_trigger_cycle_function(self, dash_html):
        assert "triggerCycle" in dash_html

    def test_update_cycle_card_function(self, dash_html):
        assert "_updateCycleCard" in dash_html

    def test_refresh_listenin_sessions_function(self, dash_html):
        assert "_refreshListeninSessions" in dash_html

    def test_auth_headers_function(self, dash_html):
        assert "_authHeaders" in dash_html

    def test_auto_init_panels_function(self, dash_html):
        assert "autoInitPanels" in dash_html

    def test_poll_function(self, dash_html):
        assert "_poll" in dash_html

    def test_set_interval_used(self, dash_html):
        assert "setInterval" in dash_html

    def test_domcontentloaded_handler(self, dash_html):
        assert "DOMContentLoaded" in dash_html


# ===========================================================================
# CSS classes present in the template
# ===========================================================================

class TestCSSClasses:
    def test_container_class(self, dash_html):
        assert 'class="container"' in dash_html

    def test_card_class(self, dash_html):
        assert 'class="card"' in dash_html

    def test_grid_2_class(self, dash_html):
        assert "grid-2" in dash_html

    def test_panel_class(self, dash_html):
        assert '"panel"' in dash_html or "class=\"panel " in dash_html

    def test_panel_body_class(self, dash_html):
        assert "panel-body" in dash_html

    def test_panel_controls_class(self, dash_html):
        assert "panel-controls" in dash_html

    def test_panel_icon_class(self, dash_html):
        assert "panel-icon" in dash_html

    def test_panel_chevron_class(self, dash_html):
        assert "panel-chevron" in dash_html

    def test_history_row_class(self, dash_html):
        assert "history-row" in dash_html or "No cycle history yet" in dash_html

    def test_chip_class(self, dash_html):
        assert 'class="chip"' in dash_html

    def test_badge_class(self, dash_html):
        assert "badge" in dash_html

    def test_btn_class(self, dash_html):
        assert 'class="btn' in dash_html

    def test_btn_primary_class(self, dash_html):
        assert "btn-primary" in dash_html

    def test_btn_ghost_class(self, dash_html):
        assert "btn-ghost" in dash_html

    def test_btn_sm_class(self, dash_html):
        assert "btn-sm" in dash_html

    def test_progress_card_class(self, dash_html):
        assert "progress-card" in dash_html

    def test_listenin_bubble_class(self, dash_html):
        assert "listenin-bubble" in dash_html

    def test_listenin_transcript_class(self, dash_html):
        assert "listenin-transcript" in dash_html

    def test_listenin_controls_class(self, dash_html):
        assert "listenin-controls" in dash_html
