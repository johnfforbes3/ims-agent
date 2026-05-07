"""
Executive Briefing Generator — one-click HTML program health brief.

Phase 9.5: Executive Briefing Generator

Generates a polished, self-contained HTML briefing document suitable for:
  - Program management reviews (PMR)
  - Executive program reviews (EPR)
  - Customer program reviews (CPR)

The briefing aggregates all available data from a cycle into a single page:
  - Program health banner (GREEN/YELLOW/RED)
  - EVM scorecard (SPI, SV, BAC, BCWP, EAC, VAC, completion %)
  - DCMA 14-point scorecard (score, trend, failed checks)
  - Milestone risk table (P50/P80 dates vs baseline)
  - Top risks and recommended PM actions
  - CAM status table (who responded, what was flagged)
  - Variance narrative (auto-generated CPR Format 5 prose)
  - Critical path summary

Output is a self-contained HTML file — no external CSS/JS dependencies,
printable via browser print-to-PDF for immediate distribution.

API endpoint: GET /api/briefing/{cycle_id}
Dashboard: "Generate Briefing" button on the main dashboard
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
_STATE_FILE = os.getenv("DASHBOARD_STATE_FILE", "data/dashboard_state.json")


def generate_briefing(
    state: dict[str, Any],
    cycle_id: str | None = None,
    title: str = "Program Health Executive Brief",
) -> str:
    """
    Generate a self-contained HTML executive briefing.

    Args:
        state: Dashboard state dict (as stored in dashboard_state.json).
        cycle_id: Cycle identifier for the title and file name.
               Defaults to state["cycle_id"] if present.
        title: Briefing document title.

    Returns:
        HTML string — fully self-contained, suitable for browser rendering.
    """
    cid = cycle_id or state.get("cycle_id", "unknown")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Extract all sections
    health = state.get("schedule_health", "UNKNOWN")
    evm = state.get("evm", {})
    dcma = state.get("dcma", {})
    milestones = state.get("milestones", [])
    top_risks = state.get("top_risks", "")
    recommended_actions = state.get("recommended_actions", "")
    narrative = state.get("narrative", "")
    variance_narrative = state.get("variance_narrative", "")
    variance_summary = state.get("variance_summary", {})
    cam_status = state.get("cam_response_status", {})
    tasks_behind = state.get("tasks_behind", [])
    cp_ids = state.get("critical_path_task_ids", [])
    completion_report = state.get("completion_report", {})

    html = _build_html(
        title=title,
        cycle_id=cid,
        generated_at=generated_at,
        health=health,
        evm=evm,
        dcma=dcma,
        milestones=milestones,
        top_risks=top_risks,
        recommended_actions=recommended_actions,
        narrative=narrative,
        variance_narrative=variance_narrative,
        variance_summary=variance_summary,
        cam_status=cam_status,
        tasks_behind=tasks_behind,
        cp_ids=cp_ids,
        completion_report=completion_report,
    )

    # Persist to reports/briefings/
    _save_briefing(html, cid)
    return html


def load_state_for_cycle(cycle_id: str | None = None) -> dict[str, Any]:
    """
    Load dashboard state for briefing generation.

    Args:
        cycle_id: If provided, look for a cycle-specific state file.
                  Falls back to current dashboard_state.json.

    Returns:
        State dict, or empty dict if not found.
    """
    state_path = Path(_STATE_FILE)
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("action=briefing_state_load_failed error=%s", exc)
    return {}


def _save_briefing(html: str, cycle_id: str) -> Path:
    """Save briefing HTML to reports/briefings/ directory."""
    # Read env at call time so test monkeypatching of REPORTS_DIR works
    reports_dir = os.getenv("REPORTS_DIR", _REPORTS_DIR)
    briefings_dir = Path(reports_dir) / "briefings"
    briefings_dir.mkdir(parents=True, exist_ok=True)
    path = briefings_dir / f"{cycle_id}_briefing.html"
    path.write_text(html, encoding="utf-8")
    logger.info("action=briefing_saved path=%s", path)
    return path


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

_HEALTH_COLORS = {
    "GREEN":   ("#1a7f4b", "#d4f8e8"),
    "YELLOW":  ("#8a6200", "#fff8d6"),
    "RED":     ("#a0001a", "#ffd6de"),
    "UNKNOWN": ("#444444", "#eeeeee"),
}


def _build_html(
    title: str,
    cycle_id: str,
    generated_at: str,
    health: str,
    evm: dict,
    dcma: dict,
    milestones: list,
    top_risks: str,
    recommended_actions: str,
    narrative: str,
    variance_narrative: str,
    variance_summary: dict,
    cam_status: dict,
    tasks_behind: list,
    cp_ids: list,
    completion_report: dict,
) -> str:
    hfg, hbg = _HEALTH_COLORS.get(health, _HEALTH_COLORS["UNKNOWN"])
    program = evm.get("program", {})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{
    --health-fg: {hfg};
    --health-bg: {hbg};
    --accent: #1a4a8a;
    --border: #c8d0dc;
    --bg: #f6f8fa;
    --card: #ffffff;
    --text: #1c2333;
    --muted: #57606a;
    --green: #1a7f4b; --yellow: #8a6200; --red: #a0001a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: var(--bg);
          color: var(--text); font-size: 13px; }}
  .page {{ max-width: 1100px; margin: 0 auto; padding: 24px 20px; }}
  h1 {{ font-size: 20px; font-weight: 700; color: var(--accent); }}
  h2 {{ font-size: 14px; font-weight: 700; color: var(--accent);
        border-bottom: 2px solid var(--accent); padding-bottom: 4px;
        margin: 20px 0 10px; }}
  .meta {{ color: var(--muted); font-size: 11px; margin-top: 4px; }}
  /* Health banner */
  .health-banner {{
    background: var(--health-bg); color: var(--health-fg);
    border: 2px solid var(--health-fg); border-radius: 8px;
    padding: 16px 20px; margin: 16px 0;
    display: flex; align-items: center; gap: 16px;
  }}
  .health-label {{ font-size: 32px; font-weight: 900; letter-spacing: 1px; }}
  .health-text {{ font-size: 13px; }}
  /* KPI grid */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0; }}
  .kpi-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
               padding: 12px; text-align: center; }}
  .kpi-val {{ font-size: 22px; font-weight: 800; }}
  .kpi-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase;
                letter-spacing: 0.5px; margin-top: 2px; }}
  .green {{ color: var(--green); }} .yellow {{ color: var(--yellow); }}
  .red {{ color: var(--red); }} .neutral {{ color: var(--accent); }}
  /* Tables */
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0; }}
  th {{ background: var(--accent); color: #fff; padding: 6px 8px;
        text-align: left; font-weight: 600; }}
  td {{ padding: 5px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f0f4f8; }}
  .pass {{ color: var(--green); font-weight: 600; }}
  .fail {{ color: var(--red); font-weight: 600; }}
  /* DCMA scorecard */
  .dcma-score {{ font-size: 28px; font-weight: 800; }}
  .section-card {{ background: var(--card); border: 1px solid var(--border);
                   border-radius: 6px; padding: 14px; margin: 10px 0; }}
  /* Prose */
  .prose {{ line-height: 1.65; white-space: pre-wrap; font-size: 12px; }}
  /* Print */
  @media print {{
    body {{ background: white; }}
    .page {{ padding: 0; }}
    h2 {{ page-break-after: avoid; }}
    .section-card {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <h1>{_esc(title)}</h1>
  <div class="meta">Cycle: {_esc(cycle_id)} &nbsp;|&nbsp; Generated: {generated_at}
  {f"&nbsp;|&nbsp; CAMs responded: {completion_report.get('responded',0)}/{completion_report.get('total',0)}" if completion_report else ""}
  </div>

  <!-- Health Banner -->
  <div class="health-banner">
    <div class="health-label">{_esc(health)}</div>
    <div class="health-text">
      <strong>Overall Schedule Health</strong><br>
      {_esc(narrative[:300] + "…" if len(narrative) > 300 else narrative) if narrative else "No narrative available."}
    </div>
  </div>

  <!-- EVM KPI Cards -->
  <h2>Earned Value Metrics</h2>
  {_evm_kpi_cards(program)}

  <!-- EVM By CAM -->
  {_evm_by_cam_table(evm.get("by_cam", {}))}

  <!-- DCMA 14-Point Scorecard -->
  <h2>DCMA 14-Point Schedule Assessment</h2>
  {_dcma_section(dcma)}

  <!-- Milestone Risk Table -->
  <h2>Milestone Risk (Schedule Risk Analysis)</h2>
  {_milestone_table(milestones)}

  <!-- Top Risks -->
  <h2>Top Schedule Risks</h2>
  <div class="section-card prose">{_esc(top_risks) if top_risks else "No risks identified."}</div>

  <!-- Recommended Actions -->
  <h2>Recommended PM Actions</h2>
  <div class="section-card prose">{_esc(recommended_actions) if recommended_actions else "No actions identified."}</div>

  <!-- Variance Narrative -->
  {f'<h2>Schedule Variance Narrative (CPR Format 5)</h2><div class="section-card prose">{_esc(variance_narrative)}</div>' if variance_narrative else ""}

  <!-- CAM Status -->
  <h2>CAM Response Status</h2>
  {_cam_status_table(cam_status)}

  <!-- Tasks Behind -->
  {f'<h2>Tasks with Blockers ({len(tasks_behind)} reported)</h2>{_tasks_behind_table(tasks_behind)}' if tasks_behind else ""}

  <!-- Critical Path -->
  {f'<h2>Critical Path ({len(cp_ids)} tasks)</h2><div class="section-card"><p style="font-size:11px;color:var(--muted);">Critical path task IDs: {", ".join(str(x) for x in cp_ids[:20])}{"…" if len(cp_ids) > 20 else ""}</p></div>' if cp_ids else ""}

  <div class="meta" style="margin-top:24px;text-align:center;">
    Generated by IMS Agent &nbsp;|&nbsp; {generated_at} &nbsp;|&nbsp; Cycle {_esc(cycle_id)}
  </div>
</div>
</body>
</html>"""


def _evm_kpi_cards(program: dict) -> str:
    spi = program.get("spi")
    sv = program.get("sv", 0)
    completion = program.get("completion_pct", 0)
    bei = program.get("bei")
    eac = program.get("eac", 0)
    bac = program.get("bac", 0)
    vac = program.get("vac", 0)

    def _color(val, good_above=None, bad_below=None):
        if val is None:
            return "neutral"
        if bad_below is not None and val < bad_below:
            return "red"
        if good_above is not None and val >= good_above:
            return "green"
        return "yellow"

    spi_color = _color(spi, good_above=0.95, bad_below=0.85)
    sv_color = "green" if (sv or 0) >= 0 else ("yellow" if (sv or 0) > -3 else "red")
    vac_color = "green" if (vac or 0) >= 0 else "red"
    bei_color = _color(bei, good_above=0.95, bad_below=0.85)

    def _fmt(v, decimals=3):
        if v is None:
            return "N/A"
        return f"{v:.{decimals}f}"

    cards = [
        (f"SPI", _fmt(spi), spi_color, "Schedule Performance Index"),
        (f"SV", f"{_fmt(sv, 1)}d", sv_color, "Schedule Variance (work-days)"),
        (f"Completion", f"{_fmt(completion, 1)}%", "neutral", "Program % Complete"),
        (f"BEI", _fmt(bei), bei_color, "Baseline Execution Index"),
        (f"BAC", f"{_fmt(bac, 1)}d", "neutral", "Budget at Completion (work-days)"),
        (f"EAC", f"{_fmt(eac, 1)}d", "neutral", "Estimate at Completion"),
        (f"VAC", f"{_fmt(vac, 1)}d", vac_color, "Variance at Completion"),
        (f"BCWP", f"{_fmt(program.get('bcwp', 0), 1)}d", "neutral", "Earned Value"),
    ]

    html = '<div class="kpi-grid">'
    for label, val, color, tooltip in cards:
        html += f'''<div class="kpi-card" title="{_esc(tooltip)}">
      <div class="kpi-val {color}">{_esc(str(val))}</div>
      <div class="kpi-label">{_esc(label)}</div>
    </div>'''
    html += "</div>"
    return html


def _evm_by_cam_table(by_cam: dict) -> str:
    if not by_cam:
        return "<p><em>No CAM-level EVM data available.</em></p>"
    rows = sorted(by_cam.items(), key=lambda x: (x[1].get("spi") or 99))
    html = '<table><tr><th>CAM</th><th>BAC (days)</th><th>BCWP</th><th>BCWS</th>' \
           '<th>SPI</th><th>SV (days)</th><th>Completion %</th><th>Health</th></tr>'
    for cam, d in rows:
        spi = d.get("spi")
        health = d.get("health", "UNKNOWN")
        hcls = health.lower() if health in ("GREEN", "YELLOW", "RED") else "neutral"
        html += f"<tr><td><strong>{_esc(cam)}</strong></td>"
        html += f"<td>{d.get('bac', 0):.1f}</td>"
        html += f"<td>{d.get('bcwp', 0):.1f}</td>"
        html += f"<td>{d.get('bcws', 0):.1f}</td>"
        spi_str = f"{spi:.3f}" if spi is not None else "N/A"
        html += f"<td class='{hcls}'>{spi_str}</td>"
        html += f"<td>{d.get('sv', 0):.1f}</td>"
        html += f"<td>{d.get('completion_pct', 0):.1f}%</td>"
        html += f"<td class='{hcls}'><strong>{_esc(health)}</strong></td></tr>"
    html += "</table>"
    return html


def _dcma_section(dcma: dict) -> str:
    if not dcma:
        return "<p><em>DCMA assessment not available for this cycle.</em></p>"

    score = dcma.get("score", 0)
    total = dcma.get("total_checks", 14)
    health = dcma.get("health", "UNKNOWN")
    hcls = health.lower() if health in ("GREEN", "YELLOW", "RED") else "neutral"
    checks = dcma.get("checks", [])

    html = f'<div class="section-card">'
    html += f'<div style="display:flex;align-items:center;gap:20px;margin-bottom:12px;">'
    html += f'<div class="dcma-score {hcls}">{score}/{total}</div>'
    html += f'<div><strong class="{hcls}">{_esc(health)}</strong><br>'
    html += f'<span style="color:var(--muted);font-size:11px;">{_esc(dcma.get("summary", ""))}</span></div>'
    html += '</div>'

    if checks:
        html += '<table><tr><th>#</th><th>Check</th><th>Status</th><th>Violations</th><th>Note</th></tr>'
        for c in checks:
            status_cls = "pass" if c.get("passed") else "fail"
            html += f"<tr><td>{c.get('check_id', '')}</td>"
            html += f"<td>{_esc(c.get('name', ''))}</td>"
            html += f"<td class='{status_cls}'>{_esc(c.get('status', ''))}</td>"
            html += f"<td>{c.get('violations', 0)}</td>"
            html += f"<td>{_esc(c.get('note', ''))}</td></tr>"
        html += "</table>"

    html += "</div>"
    return html


def _milestone_table(milestones: list) -> str:
    if not milestones:
        return "<p><em>Milestone risk data not available for this cycle.</em></p>"
    html = ('<table><tr><th>Milestone</th><th>Baseline</th>'
            '<th>P50</th><th>P80</th><th>P95</th><th>Prob On-Time</th><th>Risk</th></tr>')
    for m in milestones:
        risk = m.get("risk_level", "LOW")
        rcls = risk.lower() if risk in ("HIGH", "MEDIUM") else "green"
        prob = m.get("prob_on_baseline", 1.0)
        html += f"<tr><td><strong>{_esc(m.get('milestone_name', ''))}</strong></td>"
        html += f"<td>{_esc(str(m.get('baseline_date', 'N/A')))}</td>"
        html += f"<td>{_esc(str(m.get('p50_date', 'N/A')))}</td>"
        html += f"<td>{_esc(str(m.get('p80_date', 'N/A')))}</td>"
        html += f"<td>{_esc(str(m.get('p95_date', 'N/A')))}</td>"
        html += f"<td>{prob:.0%}</td>"
        html += f"<td class='{rcls}'><strong>{_esc(risk)}</strong></td></tr>"
    html += "</table>"
    return html


def _cam_status_table(cam_status: dict) -> str:
    if not cam_status:
        return "<p><em>CAM response data not available for this cycle.</em></p>"
    html = '<table><tr><th>CAM</th><th>Responded</th><th>Attempts</th><th>Last Outcome</th></tr>'
    for cam, data in sorted(cam_status.items()):
        responded = data.get("responded", False)
        rcls = "pass" if responded else "fail"
        html += f"<tr><td><strong>{_esc(cam)}</strong></td>"
        html += f"<td class='{rcls}'>{'✓ Yes' if responded else '✗ No'}</td>"
        html += f"<td>{data.get('attempts', 0)}</td>"
        html += f"<td>{_esc(data.get('last_outcome', ''))}</td></tr>"
    html += "</table>"
    return html


def _tasks_behind_table(tasks_behind: list) -> str:
    if not tasks_behind:
        return ""
    html = '<table><tr><th>Task ID</th><th>CAM</th><th>% Complete</th><th>Blocker</th></tr>'
    for t in tasks_behind[:20]:
        html += f"<tr><td>{_esc(str(t.get('task_id', '')))}</td>"
        html += f"<td>{_esc(t.get('cam_name', ''))}</td>"
        html += f"<td>{t.get('percent_complete', 0)}%</td>"
        html += f"<td>{_esc((t.get('blocker') or '')[:120])}</td></tr>"
    html += "</table>"
    return html


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
