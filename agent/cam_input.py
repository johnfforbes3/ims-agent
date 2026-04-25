"""
Simulated CAM status input — CLI interface for Phase 1.

Walks through tasks grouped by CAM and collects percent-complete,
blocker, and risk information from the user via the terminal.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def run_simulated_cam_input(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Run the interactive CLI CAM input simulation for all status-due tasks.

    Args:
        tasks: Parsed task list from IMSFileHandler.parse().

    Returns:
        List of CAM input dicts, one per task that received an update.
    """
    status_due = [t for t in tasks if not t.get("is_milestone")]
    by_cam = _group_by_cam(status_due)

    all_inputs: list[dict[str, Any]] = []
    print("\n" + "=" * 60)
    print("  IMS Agent — Simulated CAM Status Input")
    print("=" * 60)
    print(f"  {len(by_cam)} CAM(s) | {len(status_due)} task(s) requiring status")
    print("=" * 60 + "\n")

    for cam_name, cam_tasks in sorted(by_cam.items()):
        print(f"\n>>> CAM: {cam_name} ({len(cam_tasks)} task(s))\n")
        for task in cam_tasks:
            result = _collect_task_input(cam_name, task)
            if result is not None:
                all_inputs.append(result)
                logger.info(
                    "action=cam_input_received cam=%s task_id=%s pct=%s risk=%s",
                    cam_name,
                    task["task_id"],
                    result["percent_complete"],
                    result["risk_flag"],
                )

    print("\n" + "=" * 60)
    print(f"  Input complete. {len(all_inputs)} task(s) updated.")
    print("=" * 60 + "\n")
    return all_inputs


def _collect_task_input(cam_name: str, task: dict[str, Any]) -> dict[str, Any] | None:
    """
    Prompt the user for status on a single task.

    Returns:
        Input dict or None if the user skips the task.
    """
    expected = _expected_pct(task)
    print(f"  Task [{task['task_id']}]: {task['name']}")
    print(f"  Current: {task['percent_complete']}%  |  Expected: ~{expected}%")

    # Percent complete
    while True:
        raw = input("  Actual percent complete (0-100, or ENTER to skip): ").strip()
        if raw == "":
            print("  [skipped]\n")
            return None
        if _is_valid_pct(raw):
            pct = int(raw)
            break
        print("  Invalid — enter a number between 0 and 100.")

    blocker = ""
    risk_flag = False
    risk_description = ""

    if pct < expected:
        print(f"  Task is behind (actual {pct}% vs expected ~{expected}%).")
        blocker = input("  What is blocking this task? (ENTER to skip): ").strip()
        risk_raw = input("  Flag as a risk? (y/n): ").strip().lower()
        if risk_raw == "y":
            risk_flag = True
            risk_description = input("  Describe the risk: ").strip()

    print()
    return {
        "task_id": task["task_id"],
        "cam_name": cam_name,
        "percent_complete": pct,
        "blocker": blocker,
        "risk_flag": risk_flag,
        "risk_description": risk_description,
        "timestamp": datetime.now().isoformat(),
    }


def validate_cam_inputs(inputs: list[dict[str, Any]]) -> list[str]:
    """
    Validate a list of CAM inputs against required fields and value ranges.

    Args:
        inputs: List of CAM input dicts.

    Returns:
        List of validation error messages. Empty list means all valid.
    """
    errors: list[str] = []
    for i, item in enumerate(inputs):
        prefix = f"Input[{i}] task_id={item.get('task_id', '?')}"
        pct = item.get("percent_complete")
        if pct is None:
            errors.append(f"{prefix}: missing percent_complete")
        elif not isinstance(pct, int) or not (0 <= pct <= 100):
            errors.append(f"{prefix}: percent_complete must be 0-100, got {pct!r}")
        if not item.get("cam_name"):
            errors.append(f"{prefix}: missing cam_name")
        if not item.get("task_id"):
            errors.append(f"{prefix}: missing task_id")
        if item.get("risk_flag") and not item.get("risk_description"):
            errors.append(f"{prefix}: risk_flag=True but no risk_description provided")
    return errors


def _group_by_cam(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group tasks by their CAM name."""
    result: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        cam = t.get("cam", "Unassigned")
        result.setdefault(cam, []).append(t)
    return result


def _is_valid_pct(value: str) -> bool:
    """Return True if value is an integer in 0-100."""
    try:
        n = int(value)
        return 0 <= n <= 100
    except ValueError:
        return False


def _expected_pct(task: dict[str, Any]) -> int:
    """Estimate expected percent complete based on elapsed time."""
    from datetime import datetime
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
