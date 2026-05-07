"""
EVM Engine — Earned Value Management metrics from schedule data.

Computes schedule-based EVM metrics using task duration-days as the budget
unit (work-days proxy for BAC).  When actual cost data is not available,
this engine provides schedule performance metrics (SPI, SV) and derives
cost performance proxies where noted.

Phase 9.2 additions:
  - Program-level: BAC, BCWP, BCWS, SPI, SV, SV%, EAC (SPI-derived), VAC
  - Control-account (CAM) level: same metrics, grouped by CAM
  - Per-task breakdown for detailed drill-down
  - Designed to be called from CycleRunner after IMS parse; stored in dashboard state

EVM Formulae used:
  BAC  = Σ duration_days (Budget at Completion — planned total work)
  BCWP = Σ duration_days × (pct_complete / 100)  (Earned Value)
  BCWS = Σ duration_days × planned_pct  (Planned Value — time-phased)
  SPI  = BCWP / BCWS   (Schedule Performance Index; >1 = ahead, <1 = behind)
  SV   = BCWP - BCWS   (Schedule Variance in work-days)
  SV%  = SV / BCWS × 100
  EAC  = BAC / SPI     (Estimate at Completion — SPI-derived when no ACWP)
  VAC  = BAC - EAC     (Variance at Completion; positive = under-runs)
  TCPI = (BAC - BCWP) / (EAC - BCWP)  (To-Complete Performance Index)
  BEI  = tasks_with_actual_start / tasks_that_should_have_started
         (Baseline Execution Index — DCMA metric)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def compute_evm(
    tasks: list[dict[str, Any]],
    reference_date: datetime | None = None,
) -> dict[str, Any]:
    """
    Compute EVM metrics from a parsed task list.

    Args:
        tasks: Full parsed task list from IMSFileHandler.parse().
               Non-milestone tasks only contribute to EVM metrics.
        reference_date: The "data date" for BCWS computation.
                        Defaults to UTC now.

    Returns:
        Dict with keys:
            program:     Program-level EVM summary dict.
            by_cam:      Dict of cam_name → CAM-level EVM summary dict.
            task_detail: List of per-task EVM dicts for drill-down.
            computed_at: ISO 8601 string of computation time.
            data_unit:   "work-days" (the budget unit used).
            reference_date: ISO 8601 string of the data date used.
    """
    ref = reference_date or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    work_tasks = [t for t in tasks if not t.get("is_milestone")]

    task_detail: list[dict[str, Any]] = []
    by_cam: dict[str, list[dict[str, Any]]] = {}

    for t in work_tasks:
        row = _compute_task_evm(t, ref)
        task_detail.append(row)
        cam = t.get("cam", "Unassigned") or "Unassigned"
        by_cam.setdefault(cam, []).append(row)

    program = _aggregate(task_detail, label="PROGRAM")
    bei = _compute_bei(work_tasks, ref)
    program["bei"] = bei

    cam_summaries: dict[str, Any] = {}
    for cam_name, rows in by_cam.items():
        cam_summaries[cam_name] = _aggregate(rows, label=cam_name)

    return {
        "program": program,
        "by_cam": cam_summaries,
        "task_detail": task_detail,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "data_unit": "work-days",
        "reference_date": ref.isoformat(),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_task_evm(task: dict[str, Any], ref: datetime) -> dict[str, Any]:
    """Compute EVM for a single task."""
    bac = float(task.get("duration_days") or 0.0)
    pct = float(task.get("percent_complete") or 0) / 100.0
    bcwp = bac * pct

    planned_pct = _planned_pct(task, ref)
    bcws = bac * planned_pct

    return {
        "task_id": task["task_id"],
        "name": task.get("name", ""),
        "cam": task.get("cam", "Unassigned"),
        "bac": round(bac, 2),
        "bcwp": round(bcwp, 2),
        "bcws": round(bcws, 2),
        "sv": round(bcwp - bcws, 2),
        "planned_pct": round(planned_pct * 100, 1),
        "actual_pct": round(pct * 100, 1),
    }


def _planned_pct(task: dict[str, Any], ref: datetime) -> float:
    """
    Compute the planned percent complete at the reference date.

    Uses the scheduled start/finish.  For tasks not yet begun (ref < start),
    returns 0.  For tasks whose planned finish is in the past, returns 1.0.
    """
    start = task.get("start")
    finish = task.get("finish")
    if not start or not finish:
        return 0.0

    # Normalise timezone
    start_dt = _ensure_utc(start)
    finish_dt = _ensure_utc(finish)
    ref_dt = _ensure_utc(ref)

    if ref_dt < start_dt:
        return 0.0
    if ref_dt >= finish_dt:
        return 1.0

    total = (finish_dt - start_dt).total_seconds()
    if total <= 0:
        return 1.0
    elapsed = (ref_dt - start_dt).total_seconds()
    return max(0.0, min(1.0, elapsed / total))


def _ensure_utc(dt: Any) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    raise TypeError(f"Expected datetime, got {type(dt)}")


def _aggregate(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """Aggregate per-task EVM rows into a summary dict."""
    bac = sum(r["bac"] for r in rows)
    bcwp = sum(r["bcwp"] for r in rows)
    bcws = sum(r["bcws"] for r in rows)
    sv = bcwp - bcws

    spi = round(bcwp / bcws, 3) if bcws > 0 else None
    sv_pct = round(sv / bcws * 100, 1) if bcws > 0 else None

    # EAC derived from SPI when no actual cost data available
    if spi and spi > 0:
        eac = bac / spi
        vac = bac - eac
        # TCPI to complete within EAC
        remaining_budget = eac - bcwp
        remaining_work = bac - bcwp
        tcpi = round(remaining_work / remaining_budget, 3) if remaining_budget > 0 else None
    else:
        eac = bac  # assume no slippage if SPI unknown
        vac = 0.0
        tcpi = None

    # Overall completion percentage
    completion_pct = round(bcwp / bac * 100, 1) if bac > 0 else 0.0

    return {
        "label": label,
        "task_count": len(rows),
        "bac": round(bac, 2),
        "bcwp": round(bcwp, 2),
        "bcws": round(bcws, 2),
        "sv": round(sv, 2),
        "sv_pct": sv_pct,
        "spi": spi,
        "eac": round(eac, 2),
        "vac": round(vac, 2),
        "tcpi": tcpi,
        "completion_pct": completion_pct,
        "health": _spi_health(spi),
    }


def _compute_bei(work_tasks: list[dict[str, Any]], ref: datetime) -> float | None:
    """
    Compute the Baseline Execution Index (BEI).

    BEI = tasks_with_actual_start / tasks_that_should_have_started_by_ref_date

    A task "should have started" when its planned start is <= ref date.
    A task "has actually started" when percent_complete > 0.

    BEI close to 1.0 means the program is executing on plan.
    BEI < 0.95 is a DCMA concern.
    """
    should_have_started = [
        t for t in work_tasks
        if t.get("start") and _ensure_utc(t["start"]) <= _ensure_utc(ref)
    ]
    if not should_have_started:
        return None

    actually_started = [
        t for t in should_have_started
        if (t.get("percent_complete") or 0) > 0
    ]
    return round(len(actually_started) / len(should_have_started), 3)


def _spi_health(spi: float | None) -> str:
    """Return a RED/YELLOW/GREEN label for SPI."""
    if spi is None:
        return "UNKNOWN"
    if spi >= 0.95:
        return "GREEN"
    if spi >= 0.85:
        return "YELLOW"
    return "RED"
