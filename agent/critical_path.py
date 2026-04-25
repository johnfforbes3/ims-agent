"""
Critical path analysis — forward/backward pass CPM implementation.

Computes critical path, total float, and near-critical tasks for a
parsed IMS task list.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_NEAR_CRITICAL_DAYS = int(os.getenv("NEAR_CRITICAL_FLOAT_DAYS", "5"))


def calculate_critical_path(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Run the Critical Path Method (CPM) on the task list.

    Args:
        tasks: Parsed task list from IMSFileHandler.parse().

    Returns:
        Dict with keys:
            critical_path: list of task_ids on the critical path
            total_float: dict of task_id → float in days
            near_critical: list of task_ids with float <= NEAR_CRITICAL_FLOAT_DAYS
            changed_on: list of task_ids that moved onto the critical path
            changed_off: list of task_ids that moved off the critical path
            projected_finish: datetime of the latest critical-path task finish
    """
    if not tasks:
        return _empty_result()

    task_map = {t["task_id"]: t for t in tasks}
    order = _topological_sort(tasks)

    # Forward pass — compute Early Start (ES) and Early Finish (EF)
    es: dict[str, datetime] = {}
    ef: dict[str, datetime] = {}

    project_start = _earliest_start(tasks)

    for tid in order:
        task = task_map[tid]
        duration = timedelta(days=max(task["duration_days"], 0))
        preds = task.get("predecessors", [])

        if not preds:
            es[tid] = project_start
        else:
            pred_efs = [ef[p] for p in preds if p in ef]
            es[tid] = max(pred_efs) if pred_efs else project_start

        ef[tid] = es[tid] + duration

    # Project finish = latest EF
    project_finish = max(ef.values()) if ef else project_start

    # Backward pass — compute Late Finish (LF) and Late Start (LS)
    lf: dict[str, datetime] = {}
    ls: dict[str, datetime] = {}

    for tid in reversed(order):
        task = task_map[tid]
        duration = timedelta(days=max(task["duration_days"], 0))
        successors = _find_successors(tid, tasks)

        if not successors:
            lf[tid] = project_finish
        else:
            succ_ls = [ls[s] for s in successors if s in ls]
            lf[tid] = min(succ_ls) if succ_ls else project_finish

        ls[tid] = lf[tid] - duration

    # Total float = LF - EF (in days)
    total_float: dict[str, float] = {}
    for tid in order:
        delta = lf[tid] - ef[tid]
        total_float[tid] = delta.total_seconds() / 86400.0

    # Critical path = tasks with float ≈ 0
    critical_path = [tid for tid, f in total_float.items() if abs(f) < 0.5]
    near_critical = [
        tid for tid, f in total_float.items()
        if 0.5 <= f <= _NEAR_CRITICAL_DAYS and tid not in critical_path
    ]

    logger.info(
        "action=cpm_complete tasks=%d critical=%d near_critical=%d",
        len(tasks),
        len(critical_path),
        len(near_critical),
    )

    return {
        "critical_path": critical_path,
        "total_float": total_float,
        "near_critical": near_critical,
        "changed_on": [],   # populated by diffing against prior result in Phase 3
        "changed_off": [],
        "projected_finish": project_finish,
    }


def diff_critical_path(
    previous: list[str], current: list[str]
) -> tuple[list[str], list[str]]:
    """
    Compare two critical path task-id lists and return what changed.

    Args:
        previous: Critical path task IDs from the prior analysis.
        current: Critical path task IDs from the current analysis.

    Returns:
        (changed_on, changed_off) — task IDs that moved onto or off the CP.
    """
    prev_set = set(previous)
    curr_set = set(current)
    changed_on = list(curr_set - prev_set)
    changed_off = list(prev_set - curr_set)
    return changed_on, changed_off


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _topological_sort(tasks: list[dict[str, Any]]) -> list[str]:
    """
    Return task IDs in topological order (predecessors before successors).

    Uses Kahn's algorithm. Cycles are broken by insertion order.
    """
    task_ids = [t["task_id"] for t in tasks]
    pred_map: dict[str, list[str]] = {t["task_id"]: list(t.get("predecessors", [])) for t in tasks}

    # Only keep predecessors that exist in the task list
    valid_ids = set(task_ids)
    pred_map = {k: [p for p in v if p in valid_ids] for k, v in pred_map.items()}

    in_degree: dict[str, int] = {tid: len(preds) for tid, preds in pred_map.items()}
    successor_map: dict[str, list[str]] = {tid: [] for tid in task_ids}
    for tid, preds in pred_map.items():
        for p in preds:
            successor_map[p].append(tid)

    queue = [tid for tid in task_ids if in_degree[tid] == 0]
    result: list[str] = []

    while queue:
        tid = queue.pop(0)
        result.append(tid)
        for s in successor_map[tid]:
            in_degree[s] -= 1
            if in_degree[s] == 0:
                queue.append(s)

    # Any remaining tasks (cycle victims) appended at end
    remaining = [tid for tid in task_ids if tid not in set(result)]
    result.extend(remaining)
    return result


def _find_successors(task_id: str, tasks: list[dict[str, Any]]) -> list[str]:
    """Return task IDs that list task_id as a predecessor."""
    return [t["task_id"] for t in tasks if task_id in t.get("predecessors", [])]


def _earliest_start(tasks: list[dict[str, Any]]) -> datetime:
    """Return the earliest start date across all tasks."""
    dates = [t["start"] for t in tasks if t.get("start")]
    return min(dates) if dates else datetime.now()


def _empty_result() -> dict[str, Any]:
    """Return an empty CPM result."""
    return {
        "critical_path": [],
        "total_float": {},
        "near_critical": [],
        "changed_on": [],
        "changed_off": [],
        "projected_finish": None,
    }
