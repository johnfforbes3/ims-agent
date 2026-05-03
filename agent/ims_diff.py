"""
IMS Diff Generator — Phase 6.5.

Compares two snapshots of the task list (before and after CAM updates)
and produces a structured diff file at:

    data/ims_exports/{cycle_id}_diff.json

Each entry in the diff describes one field change on one task, including the
responsible CAM name and the reason for the change.

The diff file is written by ``cycle_runner._run_inner()`` immediately after
``handler.apply_updates()`` succeeds, and is served at:

    GET /api/diff/{cycle_id}

on the dashboard server.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = os.getenv("DATA_DIR", "data")
_EXPORTS_DIR = os.path.join(_DATA_DIR, "ims_exports")

# Fields that we diff between the before/after snapshots
_DIFFABLE_FIELDS = ("percent_complete", "start", "finish")


def generate_diff(
    tasks_before: list[dict[str, Any]],
    tasks_after: list[dict[str, Any]],
    cam_inputs: list[dict[str, Any]],
    cycle_id: str,
    *,
    write_file: bool = True,
) -> list[dict[str, Any]]:
    """
    Generate a structured diff between two task snapshots.

    Args:
        tasks_before:  Parsed task list BEFORE ``apply_updates()`` was called.
        tasks_after:   Parsed task list AFTER ``apply_updates()`` was called.
        cam_inputs:    CAM input records for this cycle (used to look up cam_name).
        cycle_id:      Cycle identifier (e.g. ``"20260503T060000Z"``).
        write_file:    When True, write the diff to
                       ``data/ims_exports/{cycle_id}_diff.json``.

    Returns:
        List of change dicts, one per (task, field) pair that changed.
    """
    # Index tasks by task_id for O(1) lookup
    before_by_id: dict[str, dict] = {t["task_id"]: t for t in tasks_before}
    after_by_id: dict[str, dict] = {t["task_id"]: t for t in tasks_after}

    # Index cam_inputs by task_id for cam_name lookup
    cam_by_task: dict[str, str] = {
        c["task_id"]: c.get("cam_name", "Unknown")
        for c in cam_inputs
    }

    changes: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for task_id, before in before_by_id.items():
        after = after_by_id.get(task_id)
        if not after:
            continue  # task removed — unusual; skip

        cam_name = cam_by_task.get(task_id, before.get("cam", "Unknown"))
        task_name = before.get("name", task_id)

        for field in _DIFFABLE_FIELDS:
            old_val = before.get(field)
            new_val = after.get(field)

            # Normalise datetime objects to ISO string for JSON serialisation
            if hasattr(old_val, "isoformat"):
                old_val = old_val.isoformat()
            if hasattr(new_val, "isoformat"):
                new_val = new_val.isoformat()

            if old_val != new_val:
                changes.append({
                    "task_id": task_id,
                    "task_name": task_name,
                    "cam_name": cam_name,
                    "field": field,
                    "old_value": old_val,
                    "new_value": new_val,
                    "change_reason": "CAM update via ATLAS Scheduler",
                    "cycle_id": cycle_id,
                    "timestamp": now_iso,
                })

    logger.info(
        "action=ims_diff_generated cycle=%s changes=%d",
        cycle_id, len(changes),
    )

    if write_file:
        _write_diff_file(cycle_id, changes)

    return changes


def _write_diff_file(cycle_id: str, changes: list[dict[str, Any]]) -> None:
    """Write the diff to ``data/ims_exports/{cycle_id}_diff.json``."""
    exports_dir = Path(_EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = exports_dir / f"{cycle_id}_diff.json"
    try:
        out.write_text(json.dumps(changes, indent=2, default=str), encoding="utf-8")
        logger.info("action=ims_diff_written path=%s", out)
    except OSError as exc:
        logger.error("action=ims_diff_write_failed path=%s error=%s", out, exc)
    _write_diff_markdown(cycle_id, changes)


def _write_diff_markdown(cycle_id: str, changes: list[dict[str, Any]]) -> None:
    """Write a human-readable Markdown diff table to ``data/ims_exports/{cycle_id}_diff.md``.

    Suitable for program review email attachment or dashboard display.
    """
    exports_dir = Path(_EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = exports_dir / f"{cycle_id}_diff.md"
    header = datetime.now(timezone.utc).isoformat()
    lines = [
        f"# IMS Change Report — Cycle {cycle_id}",
        "",
        f"**Generated:** {header}  ",
        f"**Total changes:** {len(changes)}  ",
        f"**Source:** ATLAS Scheduler",
        "",
        "| Task ID | Task Name | CAM | Field | Old Value | New Value | Reason |",
        "|---------|-----------|-----|-------|-----------|-----------|--------|",
    ]
    for c in changes:
        lines.append(
            f"| {c['task_id']} | {c['task_name']} | {c['cam_name']} "
            f"| {c['field']} | {c.get('old_value', '')} | {c.get('new_value', '')} "
            f"| {c['change_reason']} |"
        )
    if not changes:
        lines.append("| — | *No changes detected* | — | — | — | — | — |")
    lines.append("")
    try:
        out.write_text("\n".join(lines), encoding="utf-8")
        logger.info("action=ims_diff_md_written path=%s", out)
    except OSError as exc:
        logger.error("action=ims_diff_md_write_failed path=%s error=%s", out, exc)


def load_diff(cycle_id: str) -> list[dict[str, Any]] | None:
    """
    Load a previously written diff file from disk.

    Returns:
        The diff as a list of change dicts, or ``None`` if the file does not exist.
    """
    path = Path(_EXPORTS_DIR) / f"{cycle_id}_diff.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("action=ims_diff_load_failed path=%s error=%s", path, exc)
        return None
