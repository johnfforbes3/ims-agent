"""
Deterministic schedule health scoring.

Computes RED / YELLOW / GREEN from SRA probabilities and CPM float — no LLM
decision required.  Addresses TD-001: health label was previously LLM-generated
and could vary between runs on identical data.

Thresholds (all configurable via env vars):
  SRA_HIGH_RISK_THRESHOLD   — prob_on_baseline below this → HIGH risk milestone
  SRA_MEDIUM_RISK_THRESHOLD — prob between HIGH and this → MEDIUM risk milestone
  HEALTH_RED_HIGH_MS_FRAC   — fraction of milestones that must be HIGH to force RED
                              (default 0.5 — more than half HIGH → RED)
"""

import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_HIGH_THRESHOLD = float(os.getenv("SRA_HIGH_RISK_THRESHOLD", "0.50"))
_MEDIUM_THRESHOLD = float(os.getenv("SRA_MEDIUM_RISK_THRESHOLD", "0.75"))
_RED_HIGH_MS_FRAC = float(os.getenv("HEALTH_RED_HIGH_MS_FRAC", "0.50"))


def compute_health(
    sra_results: list[dict],
    cp_result: dict,
    tasks: list[dict],
) -> tuple[str, str]:
    """
    Return (health, rationale) where health is "GREEN", "YELLOW", or "RED".

    RED — any of:
      • More than HEALTH_RED_HIGH_MS_FRAC of milestones are HIGH risk
      • At least one HIGH-risk milestone AND at least one critical-path task behind

    YELLOW — any of (absent RED):
      • Any milestone is HIGH risk
      • More than 2 milestones are MEDIUM risk
      • Any critical-path task is behind schedule

    GREEN — none of the above.
    """
    high_risk = [m for m in sra_results if m.get("risk_level") == "HIGH"]
    medium_risk = [m for m in sra_results if m.get("risk_level") == "MEDIUM"]

    cp_ids = set(cp_result.get("critical_path", []))
    cp_tasks_behind = [
        t for t in tasks
        if t["task_id"] in cp_ids
        and not t.get("is_milestone")
        and _is_behind(t)
    ]

    total_ms = len(sra_results)

    # ── RED ──────────────────────────────────────────────────────────────────
    if total_ms > 0 and len(high_risk) / total_ms > _RED_HIGH_MS_FRAC:
        names = ", ".join(m["milestone_name"] for m in high_risk[:2])
        return (
            "RED",
            f"Majority of milestones at HIGH risk ({len(high_risk)}/{total_ms}): {names}",
        )

    if high_risk and cp_tasks_behind:
        ms_name = high_risk[0]["milestone_name"]
        task_name = cp_tasks_behind[0]["name"]
        return (
            "RED",
            f"HIGH-risk milestone '{ms_name}' combined with critical-path slippage on '{task_name}'",
        )

    # ── YELLOW ───────────────────────────────────────────────────────────────
    if high_risk:
        ms_name = high_risk[0]["milestone_name"]
        prob = high_risk[0].get("prob_on_baseline", 0)
        return (
            "YELLOW",
            f"Milestone '{ms_name}' has {prob:.0%} probability of on-time completion "
            f"(threshold {_HIGH_THRESHOLD:.0%})",
        )

    if len(medium_risk) > 2:
        return (
            "YELLOW",
            f"{len(medium_risk)} milestones at MEDIUM risk",
        )

    if cp_tasks_behind:
        task_name = cp_tasks_behind[0]["name"]
        return (
            "YELLOW",
            f"Critical-path task '{task_name}' is behind schedule",
        )

    # ── GREEN ─────────────────────────────────────────────────────────────────
    return (
        "GREEN",
        "All milestones at acceptable risk and critical path on track",
    )


def _is_behind(task: dict) -> bool:
    """True if a task's actual percent_complete is below the time-elapsed expectation."""
    start = task.get("start")
    finish = task.get("finish")
    if not start or not finish:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    total = (finish - start).total_seconds()
    if total <= 0:
        return False
    elapsed = max(0.0, min((now - start).total_seconds(), total))
    expected = round(elapsed / total * 100)
    return task.get("percent_complete", 0) < expected
