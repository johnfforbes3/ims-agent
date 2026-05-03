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


# ---------------------------------------------------------------------------
# Task snapshots  (7.4.3 — baseline drift support)
# ---------------------------------------------------------------------------

_SNAPSHOT_FIELDS = ("task_id", "name", "cam", "finish", "baseline_finish",
                    "percent_complete", "is_milestone")


def save_snapshot(cycle_id: str, tasks: list[dict[str, Any]]) -> None:
    """Persist a stripped task snapshot alongside the cycle diff.

    Writes ``data/ims_exports/{cycle_id}_snapshot.json`` with the fields
    needed for baseline-drift comparison (finish date, pct complete, etc.).
    Called by ``cycle_runner`` immediately after ``generate_diff()``.
    """
    exports_dir = Path(_EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = exports_dir / f"{cycle_id}_snapshot.json"

    def _ser(val: Any) -> Any:
        return val.isoformat() if hasattr(val, "isoformat") else val

    stripped = [
        {k: _ser(t.get(k)) for k in _SNAPSHOT_FIELDS}
        for t in tasks
    ]
    try:
        out.write_text(json.dumps(stripped, indent=2, default=str), encoding="utf-8")
        logger.info("action=snapshot_saved cycle=%s tasks=%d path=%s",
                    cycle_id, len(stripped), out)
    except OSError as exc:
        logger.error("action=snapshot_write_failed path=%s error=%s", out, exc)


def load_snapshot(cycle_id: str) -> list[dict[str, Any]] | None:
    """Load a task snapshot written by ``save_snapshot()``.

    Returns the list of task dicts, or ``None`` if the file does not exist.
    """
    path = Path(_EXPORTS_DIR) / f"{cycle_id}_snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("action=snapshot_load_failed path=%s error=%s", path, exc)
        return None


def list_snapshot_cycle_ids() -> list[str]:
    """Return sorted list of cycle IDs that have a snapshot file."""
    exports_dir = Path(_EXPORTS_DIR)
    if not exports_dir.exists():
        return []
    ids = []
    for f in exports_dir.iterdir():
        if f.name.endswith("_snapshot.json"):
            ids.append(f.name[: -len("_snapshot.json")])
    return sorted(ids)


# ---------------------------------------------------------------------------
# Cumulative change report  (7.4.2)
# ---------------------------------------------------------------------------

def merge_diffs(
    from_cycle: str,
    to_cycle: str,
) -> list[dict[str, Any]]:
    """Merge all per-cycle diff files between ``from_cycle`` and ``to_cycle``.

    Loads every ``{cycle_id}_diff.json`` in ``data/ims_exports/`` where
    ``from_cycle <= cycle_id <= to_cycle`` (lexicographic, which matches the
    timestamp-based cycle ID format ``YYYYMMDDTHHMMSSZ``).

    For each (task_id, field) pair the merge tracks:
    - ``old_value``       — value from the earliest cycle that changed it
    - ``new_value``       — value from the latest cycle that changed it
    - ``hop_count``       — number of intermediate changes
    - ``contributing_cycle_ids`` — sorted list of cycle IDs where this pair changed

    Returns a flat list of merged change dicts, sorted by task_id then field.
    """
    exports_dir = Path(_EXPORTS_DIR)
    if not exports_dir.exists():
        return []

    # Collect all diff files in the requested range
    diff_files: list[tuple[str, Path]] = []
    for f in exports_dir.iterdir():
        if not f.name.endswith("_diff.json"):
            continue
        cid = f.name[: -len("_diff.json")]
        if from_cycle <= cid <= to_cycle:
            diff_files.append((cid, f))
    diff_files.sort(key=lambda x: x[0])  # chronological order

    if not diff_files:
        return []

    # key: (task_id, field) → accumulated change record
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for cid, fpath in diff_files:
        try:
            changes = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("action=merge_diffs_skip path=%s error=%s", fpath, exc)
            continue

        for ch in changes:
            key = (ch["task_id"], ch["field"])
            if key not in merged:
                merged[key] = {
                    "task_id": ch["task_id"],
                    "task_name": ch.get("task_name", ch["task_id"]),
                    "cam_name": ch.get("cam_name", "Unknown"),
                    "field": ch["field"],
                    "old_value": ch.get("old_value"),
                    "new_value": ch.get("new_value"),
                    "hop_count": 1,
                    "contributing_cycle_ids": [cid],
                }
            else:
                rec = merged[key]
                rec["new_value"] = ch.get("new_value")   # always latest value
                rec["hop_count"] += 1
                rec["contributing_cycle_ids"].append(cid)

    result = sorted(merged.values(), key=lambda r: (r["task_id"], r["field"]))
    logger.info("action=merge_diffs from=%s to=%s merged=%d", from_cycle, to_cycle, len(result))
    return result


# ---------------------------------------------------------------------------
# Baseline drift report  (7.4.3)
# ---------------------------------------------------------------------------

def compute_baseline_drift(
    current_tasks: list[dict[str, Any]],
    baseline_cycle_id: str | None = None,
) -> dict[str, Any]:
    """Compare ``current_tasks`` against a saved baseline snapshot.

    The baseline is identified by ``baseline_cycle_id`` (or the
    ``BASELINE_CYCLE_ID`` env var).  If neither is set, the oldest available
    snapshot in ``data/ims_exports/`` is used.

    Args:
        current_tasks: Current parsed task list (from ``IMSFileHandler.parse()``
                       or from ``dashboard_state.json``).
        baseline_cycle_id: Optional explicit baseline cycle ID.

    Returns:
        A dict with keys:
        - ``baseline_cycle_id`` — the cycle ID used as baseline
        - ``task_drift``        — list of per-task drift dicts (task_id, name,
                                   cam, finish_slip_days, pct_delta)
        - ``tasks_added``       — task_ids present in current but not baseline
        - ``tasks_removed``     — task_ids present in baseline but not current
        - ``milestones_slipped``— list of milestone dicts slipped > threshold days
    """
    # Resolve baseline cycle ID
    if not baseline_cycle_id:
        baseline_cycle_id = os.getenv("BASELINE_CYCLE_ID", "")
    if not baseline_cycle_id:
        ids = list_snapshot_cycle_ids()
        baseline_cycle_id = ids[0] if ids else ""

    if not baseline_cycle_id:
        return {
            "baseline_cycle_id": None,
            "task_drift": [],
            "tasks_added": [],
            "tasks_removed": [],
            "milestones_slipped": [],
            "error": "No baseline snapshot available",
        }

    baseline = load_snapshot(baseline_cycle_id)
    if baseline is None:
        return {
            "baseline_cycle_id": baseline_cycle_id,
            "task_drift": [],
            "tasks_added": [],
            "tasks_removed": [],
            "milestones_slipped": [],
            "error": f"Baseline snapshot not found for cycle {baseline_cycle_id}",
        }

    baseline_by_id = {t["task_id"]: t for t in baseline}
    current_by_id = {t["task_id"]: t for t in current_tasks}

    tasks_added = sorted(set(current_by_id) - set(baseline_by_id))
    tasks_removed = sorted(set(baseline_by_id) - set(current_by_id))

    task_drift: list[dict[str, Any]] = []
    milestones_slipped: list[dict[str, Any]] = []
    slip_threshold_days = int(os.getenv("BASELINE_DRIFT_ALERT_DAYS", "14"))

    for tid, base_task in baseline_by_id.items():
        curr_task = current_by_id.get(tid)
        if not curr_task:
            continue

        # Finish date slip
        base_finish = base_task.get("finish") or base_task.get("baseline_finish")
        curr_finish = curr_task.get("finish") or curr_task.get("baseline_finish")
        slip_days: float | None = None
        if base_finish and curr_finish:
            try:
                from datetime import datetime as _dt
                b_dt = _dt.fromisoformat(base_finish) if isinstance(base_finish, str) else base_finish
                c_dt = _dt.fromisoformat(curr_finish) if isinstance(curr_finish, str) else curr_finish
                slip_days = (c_dt - b_dt).days
            except Exception:
                slip_days = None

        pct_delta = (
            (curr_task.get("percent_complete") or 0)
            - (base_task.get("percent_complete") or 0)
        )

        if slip_days or pct_delta:
            drift_entry: dict[str, Any] = {
                "task_id": tid,
                "name": curr_task.get("name", tid),
                "cam": curr_task.get("cam", "Unknown"),
                "finish_slip_days": slip_days,
                "pct_delta": pct_delta,
                "is_milestone": bool(curr_task.get("is_milestone")),
                "baseline_finish": base_finish,
                "current_finish": curr_finish,
            }
            task_drift.append(drift_entry)

            if curr_task.get("is_milestone") and slip_days and slip_days >= slip_threshold_days:
                milestones_slipped.append(drift_entry)

    task_drift.sort(key=lambda r: (-(r.get("finish_slip_days") or 0), r["task_id"]))
    milestones_slipped.sort(key=lambda r: -(r.get("finish_slip_days") or 0))

    logger.info(
        "action=baseline_drift_computed baseline=%s drifted=%d added=%d removed=%d slipped_ms=%d",
        baseline_cycle_id, len(task_drift), len(tasks_added), len(tasks_removed),
        len(milestones_slipped),
    )
    return {
        "baseline_cycle_id": baseline_cycle_id,
        "task_drift": task_drift,
        "tasks_added": tasks_added,
        "tasks_removed": tasks_removed,
        "milestones_slipped": milestones_slipped,
    }
