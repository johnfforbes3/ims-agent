"""
Report generator — produces structured Markdown IMS status reports.

Combines critical path results, SRA output, CAM inputs, and LLM synthesis
into a single Markdown report saved to the /reports/ directory.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))


class ReportGenerator:
    """Generates Markdown IMS status reports."""

    def generate(
        self,
        tasks: list[dict[str, Any]],
        cp_result: dict[str, Any],
        sra_result: list[dict[str, Any]],
        cam_inputs: list[dict[str, Any]],
        synthesis: dict[str, str],
        report_date: datetime | None = None,
    ) -> str:
        """
        Generate a full Phase 1 IMS status report and save it to /reports/.

        Args:
            tasks: Updated parsed task list.
            cp_result: Critical path analysis result.
            sra_result: SRA results per milestone.
            cam_inputs: CAM status inputs.
            synthesis: LLM synthesis dict (keys: schedule_health, narrative,
                       top_risks, recommended_actions).
            report_date: Report date; defaults to today.

        Returns:
            Path to the saved report file.
        """
        if report_date is None:
            report_date = datetime.now()

        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = _REPORTS_DIR / f"{report_date.strftime('%Y-%m-%d')}_ims_report.md"

        content = self._build_report(tasks, cp_result, sra_result, cam_inputs, synthesis, report_date)

        filename.write_text(content, encoding="utf-8")
        logger.info("action=report_saved path=%s", filename)
        return str(filename)

    def _build_report(
        self,
        tasks: list[dict[str, Any]],
        cp_result: dict[str, Any],
        sra_result: list[dict[str, Any]],
        cam_inputs: list[dict[str, Any]],
        synthesis: dict[str, str],
        report_date: datetime,
    ) -> str:
        """Build the full Markdown report string."""
        health = synthesis.get("schedule_health", "UNKNOWN").strip().upper()
        health_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(health, "⚪")

        sections: list[str] = []

        # --- Header ---
        sections.append(f"# IMS Status Report — {report_date.strftime('%Y-%m-%d')}")
        sections.append(f"**Generated:** {report_date.strftime('%Y-%m-%d %H:%M')}  ")
        sections.append(f"**Reporting Period:** {report_date.strftime('%Y-%m-%d')}  ")
        sections.append(f"**Overall Schedule Health:** {health_emoji} **{health}**")
        sections.append("")

        # --- Executive Summary ---
        sections.append("---")
        sections.append("")
        sections.append("## Executive Summary")
        sections.append("")
        sections.append(synthesis.get("narrative", "_No narrative generated._"))
        sections.append("")

        # --- Critical Path ---
        sections.append("---")
        sections.append("")
        sections.append("## Critical Path")
        sections.append("")
        cp_ids = set(cp_result.get("critical_path", []))
        cp_tasks = [t for t in tasks if t["task_id"] in cp_ids]
        if cp_tasks:
            sections.append(f"**{len(cp_tasks)} tasks on the critical path.**")
            sections.append("")
            sections.append("| Task | Start | Finish | % Complete |")
            sections.append("|---|---|---|---|")
            for t in cp_tasks:
                sections.append(
                    f"| {t['name']} | {_fmt_dt(t.get('start'))} | "
                    f"{_fmt_dt(t.get('finish'))} | {t['percent_complete']}% |"
                )
        else:
            sections.append("_Critical path not calculated or no tasks on critical path._")
        sections.append("")

        # --- Near-Critical Tasks ---
        near_critical_float = int(os.getenv("NEAR_CRITICAL_FLOAT_DAYS", "5"))
        floats = cp_result.get("total_float", {})
        near_critical = [
            (tid, f) for tid, f in floats.items()
            if 0 < f <= near_critical_float and tid not in cp_ids
        ]
        if near_critical:
            sections.append(f"**Near-Critical Tasks** (float ≤ {near_critical_float} days):")
            sections.append("")
            sections.append("| Task | Float (days) |")
            sections.append("|---|---|")
            task_map = {t["task_id"]: t for t in tasks}
            for tid, f in sorted(near_critical, key=lambda x: x[1]):
                name = task_map.get(tid, {}).get("name", tid)
                sections.append(f"| {name} | {f:.1f} |")
            sections.append("")

        # --- Milestones at Risk ---
        sections.append("---")
        sections.append("")
        sections.append("## Milestone Risk Summary")
        sections.append("")
        if sra_result:
            sections.append("| Milestone | Baseline | P50 | P80 | P95 | Prob On Time | Risk |")
            sections.append("|---|---|---|---|---|---|---|")
            for m in sorted(sra_result, key=lambda x: x.get("prob_on_baseline", 1)):
                risk_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(m["risk_level"], "")
                sections.append(
                    f"| {m['milestone_name']} | {m['baseline_date']} | "
                    f"{m['p50_date']} | {m['p80_date']} | {m['p95_date']} | "
                    f"{m.get('prob_on_baseline', 0):.0%} | {risk_icon} {m['risk_level']} |"
                )
        else:
            sections.append("_No milestones found in the schedule._")
        sections.append("")

        # --- Top 5 Risks ---
        sections.append("---")
        sections.append("")
        sections.append("## Top 5 Risks")
        sections.append("")
        sections.append(synthesis.get("top_risks", "_No risk synthesis generated._"))
        sections.append("")

        # --- Tasks Behind Schedule ---
        sections.append("---")
        sections.append("")
        sections.append("## Tasks Behind Schedule")
        sections.append("")
        cam_map = {str(c["task_id"]): c for c in cam_inputs}
        behind = [
            t for t in tasks
            if t.get("percent_complete", 0) < _expected_pct(t) and not t.get("is_milestone")
        ]
        if behind:
            sections.append("| CAM | Task | Actual % | Expected % | Blocker |")
            sections.append("|---|---|---|---|---|")
            for t in sorted(behind, key=lambda x: _expected_pct(x) - x["percent_complete"], reverse=True):
                cam_input = cam_map.get(str(t["task_id"]), {})
                blocker = cam_input.get("blocker", "") or ""
                exp = _expected_pct(t)
                sections.append(
                    f"| {t['cam']} | {t['name']} | {t['percent_complete']}% | "
                    f"~{exp}% | {blocker[:60]} |"
                )
        else:
            sections.append("_No tasks behind schedule._")
        sections.append("")

        # --- Recommended Actions ---
        sections.append("---")
        sections.append("")
        sections.append("## Recommended Actions for PM")
        sections.append("")
        sections.append(synthesis.get("recommended_actions", "_No recommendations generated._"))
        sections.append("")

        # --- Footer ---
        sections.append("---")
        sections.append("")
        sections.append(f"_Report generated by IMS Agent on {report_date.strftime('%Y-%m-%d %H:%M')}._")

        return "\n".join(sections)


def _fmt_dt(dt: Any) -> str:
    """Format a datetime or None as YYYY-MM-DD."""
    if dt is None:
        return "N/A"
    try:
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(dt)


def _expected_pct(task: dict[str, Any]) -> int:
    """Estimate expected percent complete based on elapsed time."""
    start = task.get("start")
    finish = task.get("finish")
    if not start or not finish:
        return 0
    now = datetime.now()
    total = (finish - start).total_seconds()
    if total <= 0:
        return 100
    elapsed = (now - start).total_seconds()
    return max(0, min(100, int(elapsed / total * 100)))
