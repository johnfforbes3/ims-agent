"""
DCMA 14-Point Assessment — schedule health checks for defense program IMS.

The Defense Contract Management Agency (DCMA) evaluates IMS health using a
14-point schedule quality assessment.  This module implements all 14 checks
that can be derived from MSPDI schedule data.

Phase 9.3: DCMA 14-Point Assessment Engine

References:
  DCMA 14-Point Schedule Assessment Guide (2012, updated 2018)
  DoD Earned Value Management Implementation Guide (EVMIG)

DCMA Check Definitions implemented here:
  1.  Logic            — Tasks missing predecessors or successors
  2.  Leads            — Negative lag on any predecessor link (lead time)
  3.  Lags             — Excessive positive lag (> LAG_THRESHOLD workdays)
  4.  Relationship Types — Use of SF (Start-to-Finish) relationships
  5.  Hard Constraints  — Tasks with ALAP, MSO, or MFO constraints
  6.  High Float        — Total float > HIGH_FLOAT_THRESHOLD workdays
  7.  Negative Float    — Any task with negative total float
  8.  High Duration     — Tasks with duration > HIGH_DURATION_THRESHOLD workdays
  9.  Invalid Dates     — Tasks with actual start/finish beyond planned dates
                          (proxy: 100% complete but finish date in the future)
  10. Resources         — Tasks with no CAM/resource assigned
  11. Missed Milestones — Milestone past baseline finish with 0% complete
  12. Critical Path     — Critical path integrity (CPM-based float consistency)
  13. BEI               — Baseline Execution Index < 0.95
  14. Summary Tasks     — Tasks with zero duration that are not milestones
                          (proxy check; pure summary rows skew EVM)

Each check returns:
  - name: str           — Human-readable check name
  - check_id: int       — Check number 1–14
  - passed: bool        — True if the check passes (no violations)
  - violations: int     — Number of violations found
  - threshold: str      — The acceptance criterion
  - flagged_tasks: list — Up to 10 example task names/IDs that triggered the check
  - note: str           — Contextual note
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Configurable thresholds
_HIGH_FLOAT_DAYS = float(os.getenv("DCMA_HIGH_FLOAT_DAYS", "44"))
_HIGH_DURATION_DAYS = float(os.getenv("DCMA_HIGH_DURATION_DAYS", "44"))
_LAG_THRESHOLD_DAYS = float(os.getenv("DCMA_LAG_THRESHOLD_DAYS", "5"))
_BEI_THRESHOLD = float(os.getenv("DCMA_BEI_THRESHOLD", "0.95"))
_TOTAL_FLOAT_ACCEPTABLE_PCT = float(os.getenv("DCMA_FLOAT_PCT_THRESHOLD", "0.05"))
_HARD_CONSTRAINT_ACCEPTABLE_PCT = float(os.getenv("DCMA_CONSTRAINT_PCT_THRESHOLD", "0.05"))

# Tenths of a minute per workday (8h × 60min × 10)
_TENTHS_PER_DAY = 4800


def run_assessment(
    tasks: list[dict[str, Any]],
    cp_result: dict[str, Any] | None = None,
    reference_date: datetime | None = None,
) -> dict[str, Any]:
    """
    Run all 14 DCMA checks against a parsed task list.

    Args:
        tasks: Full parsed task list from IMSFileHandler.parse().
        cp_result: Optional CPM result dict (for check 12).
        reference_date: Data date for date-based checks; defaults to UTC now.

    Returns:
        Dict with:
            checks:     list of 14 check result dicts
            score:      number of checks that passed (0–14)
            score_pct:  pass percentage (0.0–100.0)
            health:     "GREEN" (≥11/14), "YELLOW" (8–10), "RED" (<8)
            summary:    human-readable one-liner
            computed_at: ISO string
    """
    ref = reference_date or datetime.now(timezone.utc)
    work_tasks = [t for t in tasks if not t.get("is_milestone")]
    milestone_tasks = [t for t in tasks if t.get("is_milestone")]

    checks = [
        _check_01_logic(work_tasks, milestone_tasks, tasks),
        _check_02_leads(work_tasks),
        _check_03_lags(work_tasks),
        _check_04_relationship_types(work_tasks),
        _check_05_hard_constraints(work_tasks),
        _check_06_high_float(work_tasks),
        _check_07_negative_float(work_tasks),
        _check_08_high_duration(work_tasks),
        _check_09_invalid_dates(tasks, ref),
        _check_10_resources(work_tasks),
        _check_11_missed_milestones(milestone_tasks, ref),
        _check_12_critical_path_integrity(tasks, cp_result),
        _check_13_bei(work_tasks, ref),
        _check_14_summary_tasks(work_tasks),
    ]

    passed = sum(1 for c in checks if c["passed"])
    score_pct = round(passed / len(checks) * 100, 1)
    health = _score_health(passed)

    return {
        "checks": checks,
        "score": passed,
        "total_checks": len(checks),
        "score_pct": score_pct,
        "health": health,
        "summary": f"{passed}/{len(checks)} checks passed — {health}",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "high_float_days": _HIGH_FLOAT_DAYS,
            "high_duration_days": _HIGH_DURATION_DAYS,
            "lag_threshold_days": _LAG_THRESHOLD_DAYS,
            "bei_threshold": _BEI_THRESHOLD,
        },
    }


# ---------------------------------------------------------------------------
# Individual checks (1–14)
# ---------------------------------------------------------------------------


def _check_01_logic(
    work_tasks: list[dict],
    milestone_tasks: list[dict],
    all_tasks: list[dict],
) -> dict:
    """
    Check 1 — Logic: Tasks missing predecessor or successor links.

    DCMA threshold: ≤5% of tasks missing logic.
    Exception: the first task in a program may have no predecessor; the last
    may have no successor.  We flag tasks with NEITHER predecessor NOR successor
    (orphan tasks) as the most serious case, plus tasks missing one side.
    """
    all_ids = {t["task_id"] for t in all_tasks}
    # Build a reverse map: task_id → set of tasks that list it as predecessor
    successor_map: dict[str, set] = {t["task_id"]: set() for t in all_tasks}
    for t in all_tasks:
        for pred_id in t.get("predecessors", []):
            if pred_id in successor_map:
                successor_map[pred_id].add(t["task_id"])

    missing_pred = []
    missing_succ = []
    orphans = []
    for t in work_tasks:
        preds = t.get("predecessors", [])
        succs = successor_map.get(t["task_id"], set())
        has_pred = bool(preds)
        has_succ = bool(succs)
        if not has_pred:
            missing_pred.append(t)
        if not has_succ:
            missing_succ.append(t)
        if not has_pred and not has_succ:
            orphans.append(t)

    # DCMA counts violations as tasks missing BOTH predecessor AND successor
    # (orphan tasks).  Endpoint tasks (network start/end) are acceptable.
    violations = len(orphans)
    flagged = _flag_sample(orphans)
    total = len(work_tasks) or 1
    pct = violations / total

    return _make_check(
        check_id=1,
        name="Logic (Missing Predecessors/Successors)",
        passed=pct <= 0.05,
        violations=violations,
        threshold="≤5% of tasks with no predecessor AND no successor (orphans)",
        flagged_tasks=flagged,
        note=f"{len(missing_pred)} missing predecessor, {len(missing_succ)} missing successor, "
             f"{violations} orphans ({pct:.1%} of work tasks)",
    )


def _check_02_leads(work_tasks: list[dict]) -> dict:
    """Check 2 — Leads: Negative lag (lead time) on predecessor links."""
    flagged_tasks = []
    for t in work_tasks:
        for link in t.get("predecessor_links", []):
            if link.get("lag_tenths_min", 0) < 0:
                flagged_tasks.append(t)
                break

    return _make_check(
        check_id=2,
        name="Leads (Negative Lag)",
        passed=len(flagged_tasks) == 0,
        violations=len(flagged_tasks),
        threshold="0 tasks with negative lag (lead time)",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with lead constraints",
    )


def _check_03_lags(work_tasks: list[dict]) -> dict:
    """Check 3 — Lags: Excessive positive lag on predecessor links."""
    threshold_tenths = _LAG_THRESHOLD_DAYS * _TENTHS_PER_DAY
    flagged_tasks = []
    for t in work_tasks:
        for link in t.get("predecessor_links", []):
            if link.get("lag_tenths_min", 0) > threshold_tenths:
                flagged_tasks.append(t)
                break

    total = len(work_tasks) or 1
    pct = len(flagged_tasks) / total

    return _make_check(
        check_id=3,
        name="Lags (Excessive Positive Lag)",
        passed=pct <= 0.05,
        violations=len(flagged_tasks),
        threshold=f"≤5% of tasks with lag > {_LAG_THRESHOLD_DAYS:.0f} workdays",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with excessive lag ({pct:.1%})",
    )


def _check_04_relationship_types(work_tasks: list[dict]) -> dict:
    """Check 4 — Relationship Types: SF (Start-to-Finish) relationships are rare."""
    # SF = type 2 in MSPDI
    flagged_tasks = []
    for t in work_tasks:
        for link in t.get("predecessor_links", []):
            if link.get("type") == 2:  # SF
                flagged_tasks.append(t)
                break

    return _make_check(
        check_id=4,
        name="Relationship Types (SF Links)",
        passed=len(flagged_tasks) == 0,
        violations=len(flagged_tasks),
        threshold="0 Start-to-Finish (SF) relationships",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with SF predecessor relationship",
    )


def _check_05_hard_constraints(work_tasks: list[dict]) -> dict:
    """Check 5 — Hard Constraints: ALAP, MSO, MFO constraint types."""
    flagged_tasks = [t for t in work_tasks if t.get("has_hard_constraint")]
    total = len(work_tasks) or 1
    pct = len(flagged_tasks) / total

    return _make_check(
        check_id=5,
        name="Hard Constraints",
        passed=pct <= _HARD_CONSTRAINT_ACCEPTABLE_PCT,
        violations=len(flagged_tasks),
        threshold=f"≤{_HARD_CONSTRAINT_ACCEPTABLE_PCT:.0%} of tasks with hard constraints",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with hard date constraints ({pct:.1%})",
    )


def _check_06_high_float(work_tasks: list[dict]) -> dict:
    """Check 6 — High Float: Total float > HIGH_FLOAT_DAYS workdays."""
    flagged_tasks = [
        t for t in work_tasks
        if t.get("total_float_days") is not None
        and t["total_float_days"] > _HIGH_FLOAT_DAYS
    ]
    # Tasks without total_float_days data are excluded (can't assess)
    assessable = [t for t in work_tasks if t.get("total_float_days") is not None]
    total = len(assessable) or 1
    pct = len(flagged_tasks) / total

    return _make_check(
        check_id=6,
        name="High Float",
        passed=pct <= _TOTAL_FLOAT_ACCEPTABLE_PCT,
        violations=len(flagged_tasks),
        threshold=f"≤{_TOTAL_FLOAT_ACCEPTABLE_PCT:.0%} of tasks with float > {_HIGH_FLOAT_DAYS:.0f} workdays",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with high float (>{_HIGH_FLOAT_DAYS:.0f}d) "
             f"of {len(assessable)} assessable tasks",
    )


def _check_07_negative_float(work_tasks: list[dict]) -> dict:
    """Check 7 — Negative Float: Any task with negative total float."""
    flagged_tasks = [
        t for t in work_tasks
        if t.get("total_float_days") is not None
        and t["total_float_days"] < 0
    ]

    return _make_check(
        check_id=7,
        name="Negative Float",
        passed=len(flagged_tasks) == 0,
        violations=len(flagged_tasks),
        threshold="0 tasks with negative total float",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with negative total float",
    )


def _check_08_high_duration(work_tasks: list[dict]) -> dict:
    """Check 8 — High Duration: Tasks > HIGH_DURATION_DAYS workdays."""
    flagged_tasks = [
        t for t in work_tasks
        if (t.get("duration_days") or 0) > _HIGH_DURATION_DAYS
    ]
    total = len(work_tasks) or 1
    pct = len(flagged_tasks) / total

    return _make_check(
        check_id=8,
        name="High Duration",
        passed=pct <= 0.05,
        violations=len(flagged_tasks),
        threshold=f"≤5% of tasks with duration > {_HIGH_DURATION_DAYS:.0f} workdays",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with duration > {_HIGH_DURATION_DAYS:.0f}d ({pct:.1%})",
    )


def _check_09_invalid_dates(all_tasks: list[dict], ref: datetime) -> dict:
    """
    Check 9 — Invalid Dates.

    Proxy checks:
    a) Task is 100% complete but finish date is in the future (dates inconsistent).
    b) Task has 0% complete but finish date is in the past by more than 30 days
       (missed without being marked complete).
    """
    ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
    flagged_tasks = []
    for t in all_tasks:
        if t.get("is_milestone"):
            continue
        finish = t.get("finish")
        if not finish:
            continue
        finish_naive = finish.replace(tzinfo=None) if finish.tzinfo else finish
        pct = t.get("percent_complete", 0)

        # Complete but finish in future
        if pct == 100 and finish_naive > ref_naive:
            flagged_tasks.append(t)
            continue
        # Zero progress but finish 30+ days in the past
        if pct == 0 and (ref_naive - finish_naive).days > 30:
            flagged_tasks.append(t)

    return _make_check(
        check_id=9,
        name="Invalid Dates",
        passed=len(flagged_tasks) == 0,
        violations=len(flagged_tasks),
        threshold="0 tasks with date/progress inconsistencies",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) with suspect date/progress combinations",
    )


def _check_10_resources(work_tasks: list[dict]) -> dict:
    """Check 10 — Resources: Tasks with no assigned CAM/resource."""
    flagged_tasks = [
        t for t in work_tasks
        if not t.get("cam") or t.get("cam") == "Unassigned"
    ]
    total = len(work_tasks) or 1
    pct = len(flagged_tasks) / total

    return _make_check(
        check_id=10,
        name="Resources (Unassigned Tasks)",
        passed=pct <= 0.05,
        violations=len(flagged_tasks),
        threshold="≤5% of tasks without an assigned CAM/resource",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} task(s) unassigned ({pct:.1%})",
    )


def _check_11_missed_milestones(milestone_tasks: list[dict], ref: datetime) -> dict:
    """Check 11 — Missed Baseline Milestones: Milestones past baseline finish with 0%."""
    ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
    flagged_tasks = []
    for t in milestone_tasks:
        bf = t.get("baseline_finish")
        if not bf:
            continue
        bf_naive = bf.replace(tzinfo=None) if bf.tzinfo else bf
        if bf_naive < ref_naive and t.get("percent_complete", 0) == 0:
            flagged_tasks.append(t)

    return _make_check(
        check_id=11,
        name="Missed Baseline Milestones",
        passed=len(flagged_tasks) == 0,
        violations=len(flagged_tasks),
        threshold="0 milestones past baseline finish date with 0% complete",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} milestone(s) past baseline without completion",
    )


def _check_12_critical_path_integrity(
    tasks: list[dict],
    cp_result: dict | None,
) -> dict:
    """
    Check 12 — Critical Path Integrity.

    Verifies the critical path is non-empty and represents a plausible
    fraction of the total task list (5%–80%).  An empty critical path
    (no float=0 path) or a critical path that is >80% of all tasks
    usually indicates a logic error (all tasks constrained or dangling).
    """
    if not cp_result:
        return _make_check(
            check_id=12,
            name="Critical Path Integrity",
            passed=False,
            violations=1,
            threshold="Non-empty critical path representing 5%–80% of tasks",
            flagged_tasks=[],
            note="No CPM result provided — check skipped",
        )

    cp_ids = cp_result.get("critical_path", [])
    total = len(tasks) or 1
    cp_pct = len(cp_ids) / total

    passed = len(cp_ids) > 0 and 0.05 <= cp_pct <= 0.80

    return _make_check(
        check_id=12,
        name="Critical Path Integrity",
        passed=passed,
        violations=0 if passed else 1,
        threshold="Critical path = 5%–80% of all tasks",
        flagged_tasks=[],
        note=f"Critical path: {len(cp_ids)} tasks ({cp_pct:.1%} of schedule)",
    )


def _check_13_bei(work_tasks: list[dict], ref: datetime) -> dict:
    """
    Check 13 — Baseline Execution Index (BEI).

    BEI = tasks_with_actual_start / tasks_that_should_have_started
    DCMA threshold: BEI ≥ 0.95
    """
    ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
    should_have_started = [
        t for t in work_tasks
        if t.get("start") and _to_naive(t["start"]) <= ref_naive
    ]
    if not should_have_started:
        return _make_check(
            check_id=13,
            name="Baseline Execution Index (BEI)",
            passed=True,
            violations=0,
            threshold=f"BEI ≥ {_BEI_THRESHOLD:.2f}",
            flagged_tasks=[],
            note="No tasks scheduled to start yet — BEI not applicable",
        )

    actually_started = [
        t for t in should_have_started
        if (t.get("percent_complete") or 0) > 0
    ]
    bei = len(actually_started) / len(should_have_started)
    not_started = [t for t in should_have_started if (t.get("percent_complete") or 0) == 0]

    return _make_check(
        check_id=13,
        name="Baseline Execution Index (BEI)",
        passed=bei >= _BEI_THRESHOLD,
        violations=len(not_started),
        threshold=f"BEI ≥ {_BEI_THRESHOLD:.2f}",
        flagged_tasks=_flag_sample(not_started),
        note=f"BEI = {bei:.3f} ({len(actually_started)}/{len(should_have_started)} tasks started)",
    )


def _check_14_summary_tasks(work_tasks: list[dict]) -> dict:
    """
    Check 14 — Summary / Zero-Duration Non-Milestone Tasks.

    Tasks with zero duration that are not milestones are likely summary rows
    that inflate task counts and distort EVM metrics.
    """
    flagged_tasks = [
        t for t in work_tasks
        if (t.get("duration_days") or 0) == 0
    ]
    total = len(work_tasks) or 1
    pct = len(flagged_tasks) / total

    return _make_check(
        check_id=14,
        name="Summary Tasks (Zero-Duration Non-Milestones)",
        passed=pct <= 0.05,
        violations=len(flagged_tasks),
        threshold="≤5% of work tasks with zero duration",
        flagged_tasks=_flag_sample(flagged_tasks),
        note=f"{len(flagged_tasks)} zero-duration work task(s) ({pct:.1%})",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check(
    check_id: int,
    name: str,
    passed: bool,
    violations: int,
    threshold: str,
    flagged_tasks: list[str],
    note: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "name": name,
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
        "violations": violations,
        "threshold": threshold,
        "flagged_tasks": flagged_tasks,
        "note": note,
    }


def _flag_sample(tasks: list[dict], max_items: int = 10) -> list[str]:
    """Return up to max_items task identifiers for the violation report."""
    seen = []
    seen_ids = set()
    for t in tasks:
        tid = t.get("task_id", "")
        if tid not in seen_ids:
            name = t.get("name", "")
            seen.append(f"[{tid}] {name}" if name else f"[{tid}]")
            seen_ids.add(tid)
        if len(seen) >= max_items:
            break
    return seen


def _to_naive(dt: Any) -> datetime:
    """Strip tzinfo so comparisons with naive datetimes are safe."""
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None)
    return dt


def _score_health(passed: int) -> str:
    """GREEN ≥ 11/14, YELLOW 8–10, RED < 8."""
    if passed >= 11:
        return "GREEN"
    if passed >= 8:
        return "YELLOW"
    return "RED"
