"""
Variance Analyst — LLM-backed schedule variance analysis and narrative generation.

Phase 9.4: Variance Analysis Narratives

Defense programs submit monthly Cost Performance Reports (CPR / IPMR) that
include narrative explanations of schedule and cost variances.  Writing these
narratives is one of the most labor-intensive PMO tasks — typically 2–4 hours
per month per program.

This module auto-generates variance analysis narratives by combining:
  - EVM metrics (SV, SPI, BEI from evm_engine)
  - IMS diff (what changed since last cycle from ims_diff)
  - CAM interview data (reported blockers and risk flags)
  - DCMA assessment results (schedule quality context)

Output is structured in the standard CPR Format 5 style:
  1. Summary of variance (numerical)
  2. Root cause explanation (from CAM inputs + diff)
  3. Impact to downstream work
  4. Recovery/corrective action plan
  5. New estimate (EAC narrative)

The LLM call uses the existing llm_interface.ask() with a specialized system
prompt so the output is professional, grounded in data, and free of hedging.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Module-level import so tests can patch agent.variance_analyst.LLMInterface
try:
    from agent.llm_interface import LLMInterface
except Exception:  # pragma: no cover
    LLMInterface = None  # type: ignore[assignment,misc]

_VARIANCE_SYSTEM_PROMPT = """You are a senior program control analyst writing a CPR (Cost Performance Report) \
Schedule Variance narrative for a defense program.

Your narrative must be:
- Professional and factual — grounded ONLY in the data provided
- Written in past tense for what happened, future tense for recovery actions
- Specific: cite work package names, CAM names, and percentages where available
- Concise: 3–5 paragraphs total, no bullet points, no markdown
- Structured: (1) variance summary, (2) root cause, (3) downstream impact, (4) recovery plan, (5) revised estimate

Do NOT invent data, names, or values not present in the input.
Do NOT use markdown formatting (no asterisks, headers, or bullet points).
Write plain paragraphs only."""


def generate_variance_narrative(
    tasks: list[dict[str, Any]],
    cam_inputs: list[dict[str, Any]],
    evm_summary: dict[str, Any],
    cycle_id: str,
    dcma_result: dict[str, Any] | None = None,
    ims_diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate a CPR-style schedule variance narrative.

    Args:
        tasks: Parsed task list (post-update).
        cam_inputs: CAM interview results for this cycle.
        evm_summary: Output from evm_engine.compute_evm().
        cycle_id: Current cycle identifier for logging.
        dcma_result: Optional DCMA assessment output.
        ims_diff: Optional IMS diff output (what changed).

    Returns:
        Dict with:
            narrative: str — The generated variance narrative (plain text)
            variance_summary: dict — Key variance metrics used as context
            generated_at: str — ISO timestamp
            cycle_id: str
    """
    variance_summary = _build_variance_summary(tasks, cam_inputs, evm_summary, dcma_result)
    context = _build_context(variance_summary, cam_inputs, ims_diff)

    question = (
        "Based on the schedule performance data provided, write a CPR Format 5 "
        "Schedule Variance narrative. Follow the system prompt format exactly."
    )

    try:
        llm = LLMInterface()
        narrative = llm.ask(question, context=context, system=_VARIANCE_SYSTEM_PROMPT)
        logger.info("action=variance_narrative_generated cycle=%s tokens_approx=%d",
                    cycle_id, len(narrative))
    except Exception as exc:
        logger.warning("action=variance_narrative_failed cycle=%s error=%s", cycle_id, exc)
        # Fallback: return a data-driven summary without LLM prose
        narrative = _fallback_narrative(variance_summary)

    return {
        "narrative": narrative,
        "variance_summary": variance_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cycle_id": cycle_id,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_variance_summary(
    tasks: list[dict],
    cam_inputs: list[dict],
    evm_summary: dict,
    dcma_result: dict | None,
) -> dict[str, Any]:
    """Extract key variance metrics for the prompt context."""
    program = evm_summary.get("program", {})
    spi = program.get("spi")
    sv = program.get("sv", 0.0)
    sv_pct = program.get("sv_pct")
    bac = program.get("bac", 0.0)
    bcwp = program.get("bcwp", 0.0)
    bcws = program.get("bcws", 0.0)
    eac = program.get("eac", bac)
    vac = program.get("vac", 0.0)
    completion_pct = program.get("completion_pct", 0.0)
    bei = program.get("bei")

    # Worst-performing CAMs by SPI
    cam_summaries = evm_summary.get("by_cam", {})
    worst_cams = sorted(
        [(name, data) for name, data in cam_summaries.items() if data.get("spi") is not None],
        key=lambda x: x[1]["spi"],
    )[:3]

    # CAM-reported blockers
    blockers = [
        {"cam": inp.get("cam_name", ""), "task_id": inp.get("task_id", ""), "detail": inp.get("blocker", "")}
        for inp in cam_inputs
        if inp.get("blocker")
    ]

    # Risk flags
    risks = [
        {"cam": inp.get("cam_name", ""), "task_id": inp.get("task_id", ""), "desc": inp.get("risk_description", "")}
        for inp in cam_inputs
        if inp.get("risk_flag")
    ]

    # DCMA context
    dcma_score = None
    dcma_health = None
    if dcma_result:
        dcma_score = f"{dcma_result.get('score', '?')}/{dcma_result.get('total_checks', 14)}"
        dcma_health = dcma_result.get("health", "")

    return {
        "spi": spi,
        "sv_work_days": round(sv, 2),
        "sv_pct": sv_pct,
        "bac_work_days": round(bac, 2),
        "bcwp_work_days": round(bcwp, 2),
        "bcws_work_days": round(bcws, 2),
        "eac_work_days": round(eac, 2),
        "vac_work_days": round(vac, 2),
        "program_completion_pct": completion_pct,
        "bei": bei,
        "worst_performing_cams": [
            {"cam": name, "spi": data["spi"], "sv_days": data.get("sv", 0)}
            for name, data in worst_cams
        ],
        "blocker_count": len(blockers),
        "risk_flag_count": len(risks),
        "blockers": blockers[:5],
        "risks": risks[:5],
        "dcma_score": dcma_score,
        "dcma_health": dcma_health,
        "total_tasks": len([t for t in tasks if not t.get("is_milestone")]),
    }


def _build_context(
    variance_summary: dict,
    cam_inputs: list[dict],
    ims_diff: dict | None,
) -> str:
    """Serialize variance context into a plain-text prompt string."""
    lines = [
        "=== SCHEDULE VARIANCE ANALYSIS DATA ===",
        "",
        "--- EARNED VALUE METRICS (Schedule-Based) ---",
        f"Program SPI: {variance_summary.get('spi', 'N/A')}",
        f"Schedule Variance (SV): {variance_summary.get('sv_work_days', 0)} work-days",
        f"SV%: {variance_summary.get('sv_pct', 'N/A')}%",
        f"BAC (Budget at Completion): {variance_summary.get('bac_work_days', 0)} work-days",
        f"BCWP (Earned Value): {variance_summary.get('bcwp_work_days', 0)} work-days",
        f"BCWS (Planned Value): {variance_summary.get('bcws_work_days', 0)} work-days",
        f"EAC (Estimate at Completion): {variance_summary.get('eac_work_days', 0)} work-days",
        f"VAC (Variance at Completion): {variance_summary.get('vac_work_days', 0)} work-days",
        f"Program Completion: {variance_summary.get('program_completion_pct', 0)}%",
        f"BEI (Baseline Execution Index): {variance_summary.get('bei', 'N/A')}",
        "",
    ]

    # Worst-performing control accounts
    worst = variance_summary.get("worst_performing_cams", [])
    if worst:
        lines.append("--- WORST-PERFORMING CONTROL ACCOUNTS ---")
        for cam in worst:
            lines.append(f"  {cam['cam']}: SPI={cam['spi']}, SV={cam['sv_days']} days")
        lines.append("")

    # Blockers
    blockers = variance_summary.get("blockers", [])
    if blockers:
        lines.append("--- CAM-REPORTED BLOCKERS ---")
        for b in blockers:
            lines.append(f"  [{b['cam']} / Task {b['task_id']}]: {b['detail']}")
        lines.append("")

    # Risk flags
    risks = variance_summary.get("risks", [])
    if risks:
        lines.append("--- CAM-FLAGGED RISKS ---")
        for r in risks:
            lines.append(f"  [{r['cam']} / Task {r['task_id']}]: {r['desc']}")
        lines.append("")

    # IMS diff (what changed)
    if ims_diff:
        changes = ims_diff.get("changes", [])
        if changes:
            lines.append("--- IMS CHANGES THIS CYCLE ---")
            for ch in changes[:10]:
                task_name = ch.get("task_name", ch.get("task_id", ""))
                old_pct = ch.get("old_percent_complete", "?")
                new_pct = ch.get("new_percent_complete", "?")
                cam = ch.get("cam", "")
                lines.append(f"  {task_name} ({cam}): {old_pct}% → {new_pct}%")
            lines.append("")

    # DCMA context
    dcma_score = variance_summary.get("dcma_score")
    if dcma_score:
        lines.append("--- SCHEDULE QUALITY (DCMA) ---")
        lines.append(f"  DCMA Score: {dcma_score} — {variance_summary.get('dcma_health', '')}")
        lines.append("")

    return "\n".join(lines)


def _fallback_narrative(variance_summary: dict) -> str:
    """Generate a data-driven fallback when the LLM call fails."""
    spi = variance_summary.get("spi")
    sv = variance_summary.get("sv_work_days", 0)
    completion = variance_summary.get("program_completion_pct", 0)
    blockers = variance_summary.get("blocker_count", 0)

    if spi is None:
        return (
            f"Program is {completion:.1f}% complete. Schedule performance data is "
            f"insufficient to compute SPI this cycle."
        )

    direction = "behind" if sv < 0 else "ahead of"
    severity = "significantly " if abs(sv) > 5 else ""
    return (
        f"The program is {severity}{direction} schedule with an SPI of {spi:.3f} "
        f"and a schedule variance of {abs(sv):.1f} work-days {direction} plan. "
        f"Program completion stands at {completion:.1f}%. "
        f"{blockers} CAM(s) reported blockers this cycle. "
        f"LLM narrative generation was unavailable; this is a data summary only."
    )
