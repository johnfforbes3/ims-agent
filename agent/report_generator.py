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
        cycle_id: str | None = None,
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
            cycle_id: Optional cycle ID used to load the IMS diff summary
                      (7.4.6). When omitted, the diff section is skipped.

        Returns:
            Path to the saved report file.
        """
        if report_date is None:
            report_date = datetime.now()

        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = _REPORTS_DIR / f"{report_date.strftime('%Y-%m-%d')}_ims_report.md"

        content = self._build_report(
            tasks, cp_result, sra_result, cam_inputs, synthesis, report_date,
            cycle_id=cycle_id,
        )

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
        cycle_id: str | None = None,
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
        blocker_details: list[tuple[str, str]] = []  # (task_name, full_blocker) for appendix
        if behind:
            sections.append("| CAM | Task | Actual % | Expected % | CAM Forecast | Δ Days | Blocker |")
            sections.append("|---|---|---|---|---|---|---|")
            for t in sorted(behind, key=lambda x: _expected_pct(x) - x["percent_complete"], reverse=True):
                cam_input = cam_map.get(str(t["task_id"]), {})
                blocker = cam_input.get("blocker", "") or ""
                exp = _expected_pct(t)
                # Prefer the CAM-reported percentage when it differs from the IMS value.
                # This happens when the CAM corrects a stale IMS entry during the interview
                # (e.g., IMS shows 85% but CAM says the actual is 60%).  The cam_input's
                # percent_complete comes directly from the interview capture.
                cam_pct = cam_input.get("percent_complete")
                actual_pct = cam_pct if cam_pct is not None else t["percent_complete"]
                # EAC date and slippage columns
                eac_date_str = cam_input.get("eac_date")
                eac_uncertain = cam_input.get("eac_uncertain", False)
                if eac_date_str:
                    forecast_cell = eac_date_str
                    baseline_finish = t.get("finish")
                    if baseline_finish:
                        try:
                            eac_dt = datetime.strptime(eac_date_str, "%Y-%m-%d")
                            slip = int((eac_dt - baseline_finish).days)
                            if slip > 0:
                                delta_cell = f"+{slip}d"
                            elif slip < 0:
                                delta_cell = f"{slip}d"
                            else:
                                delta_cell = "0d"
                        except (ValueError, TypeError):
                            delta_cell = "—"
                    else:
                        delta_cell = "—"
                elif eac_uncertain:
                    forecast_cell = "uncertain"
                    delta_cell = "—"
                else:
                    forecast_cell = "—"
                    delta_cell = "—"
                # TD-007: Truncate to first sentence or 120 chars in table cell.
                # The full text is collected for the appendix below.
                cell_blocker, was_truncated = _truncate_blocker(blocker)
                if was_truncated:
                    blocker_details.append((t["name"], blocker))
                sections.append(
                    f"| {t['cam']} | {t['name']} | {actual_pct}% | "
                    f"~{exp}% | {forecast_cell} | {delta_cell} | {cell_blocker} |"
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

        # --- Blocker Details Appendix (TD-007) ---
        if blocker_details:
            sections.append("---")
            sections.append("")
            sections.append("## Blocker Details")
            sections.append("")
            sections.append("_Full blocker descriptions for tasks truncated in the table above._")
            sections.append("")
            for task_name, full_blocker in blocker_details:
                sections.append(f"**{task_name}:** {full_blocker}")
                sections.append("")

        # --- IMS Diff Summary (7.4.6) ---
        if cycle_id:
            diff_section = self._build_diff_summary(cycle_id)
            if diff_section:
                sections.append("---")
                sections.append("")
                sections.extend(diff_section)

        # --- Baseline Drift Alert (7.4.6) ---
        drift_section = self._build_baseline_drift_alert(tasks)
        if drift_section:
            sections.append("---")
            sections.append("")
            sections.extend(drift_section)

        # --- Footer ---
        sections.append("---")
        sections.append("")
        sections.append(f"_Report generated by IMS Agent on {report_date.strftime('%Y-%m-%d %H:%M')}._")

        return "\n".join(sections)

    def _build_diff_summary(self, cycle_id: str) -> list[str]:
        """Build the IMS Diff Summary section for a specific cycle (7.4.6).

        Returns an empty list when no diff file is available for this cycle.
        """
        try:
            from agent.ims_diff import load_diff
        except ImportError:
            return []

        changes = load_diff(cycle_id)
        if not changes:
            return []

        total = len(changes)
        shown = changes[:5]
        lines: list[str] = [
            "## IMS Diff Summary",
            "",
            f"**{total} field change(s) recorded this cycle.**"
            + (f" _(showing first 5)_" if total > 5 else ""),
            "",
            "| Task | CAM | Field | Old | New |",
            "|---|---|---|---|---|",
        ]
        for ch in shown:
            lines.append(
                f"| {ch.get('task_name', ch['task_id'])} | {ch.get('cam_name', '—')} "
                f"| {ch['field']} | {ch.get('old_value', '—')} | {ch.get('new_value', '—')} |"
            )
        if total > 5:
            lines.append(f"| _(+{total - 5} more — see full diff at `/api/diff/{cycle_id}`)_ | | | | |")
        lines.append("")
        return lines

    def _build_baseline_drift_alert(self, tasks: list[dict[str, Any]]) -> list[str]:
        """Build the Baseline Drift Alert section when any milestone slipped > threshold (7.4.6).

        Returns an empty list when no baseline snapshot is available or no milestones slipped.
        """
        try:
            from agent.ims_diff import compute_baseline_drift
        except ImportError:
            return []

        result = compute_baseline_drift(tasks)
        slipped = result.get("milestones_slipped", [])
        if not slipped:
            return []

        threshold = int(os.getenv("BASELINE_DRIFT_ALERT_DAYS", "14"))
        lines: list[str] = [
            "## Baseline Drift Alert",
            "",
            f"**{len(slipped)} milestone(s) have slipped ≥ {threshold} days from baseline.**",
            "",
            "| Milestone | Baseline Finish | Current Projected | Slip (days) |",
            "|---|---|---|---|",
        ]
        for m in slipped:
            lines.append(
                f"| {m['name']} | {m.get('baseline_finish', '—')} "
                f"| {m.get('current_finish', '—')} | **{m.get('finish_slip_days', '?')}** |"
            )
        lines.append("")
        return lines


def _truncate_blocker(text: str, max_len: int = 120) -> tuple[str, bool]:
    """Return (cell_text, was_truncated) for a blocker description.

    Truncates to the first sentence boundary or ``max_len`` characters,
    whichever comes first.  Appends ``*`` when truncated so the reader
    knows to check the Blocker Details appendix (TD-007).
    """
    if not text:
        return ("", False)
    # Try to cut at first sentence boundary within max_len
    for sep in (". ", "! ", "? "):
        idx = text.find(sep)
        if 0 < idx < max_len:
            return (text[: idx + 1] + "*", True)
    if len(text) <= max_len:
        return (text, False)
    return (text[:max_len].rstrip() + "…*", True)


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
