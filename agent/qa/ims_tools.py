"""
IMS Schedule Tools — callable tool handlers for the Q&A engine.

Each tool parses the live IMS XML and returns structured JSON so the
LLM can answer questions that require raw schedule data (float, dependencies,
task details) rather than just the synthesized dashboard state.

Tools are designed for Anthropic tool_use (function calling).  The tool
definitions (TOOL_SCHEMAS) are passed to the API; the dispatcher
(call_tool) executes whichever tool the model requests.

All handlers are read-only — no writes to the IMS file.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_IMS_PATH = os.getenv("IMS_FILE_PATH", "data/sample_ims.xml")


# ---------------------------------------------------------------------------
# Lazy-loaded schedule cache (process-scoped, refreshed per Q&A session start)
# ---------------------------------------------------------------------------

_task_cache: list[dict] | None = None
_cp_cache: dict | None = None


def _get_tasks() -> list[dict]:
    global _task_cache
    if _task_cache is None:
        from agent.file_handler import IMSFileHandler
        _task_cache = IMSFileHandler(_IMS_PATH).parse()
        logger.info("action=ims_tools_loaded tasks=%d", len(_task_cache))
    return _task_cache


def _get_cp() -> dict:
    global _cp_cache
    if _cp_cache is None:
        from agent.critical_path import calculate_critical_path
        _cp_cache = calculate_critical_path(_get_tasks())
    return _cp_cache


def invalidate_cache() -> None:
    """Call after a cycle completes so the next query re-reads the IMS."""
    global _task_cache, _cp_cache
    _task_cache = None
    _cp_cache = None


def _fmt_date(d) -> str:
    if d is None:
        return "N/A"
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _task_summary(t: dict, float_val: float | None = None) -> dict:
    """Return a serialisable summary of a task dict."""
    result = {
        "task_id": t["task_id"],
        "name": t["name"],
        "cam": t.get("cam", "Unassigned"),
        "percent_complete": t.get("percent_complete", 0),
        "start": _fmt_date(t.get("start")),
        "finish": _fmt_date(t.get("finish")),
        "baseline_start": _fmt_date(t.get("baseline_start")),
        "baseline_finish": _fmt_date(t.get("baseline_finish")),
        "duration_days": round(t.get("duration_days", 0), 1),
        "is_milestone": t.get("is_milestone", False),
        "predecessors": t.get("predecessors", []),
        "notes": (t.get("notes") or "")[:300],
    }
    if float_val is not None:
        result["total_float_days"] = round(float_val, 1)
    return result


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def get_task(task_id: str) -> str:
    """Return full details for a single task including float."""
    tasks = _get_tasks()
    cp = _get_cp()
    t = next((x for x in tasks if x["task_id"] == task_id), None)
    if t is None:
        return json.dumps({"error": f"Task ID '{task_id}' not found in the schedule."})
    float_val = cp["total_float"].get(task_id)
    is_critical = task_id in cp["critical_path"]
    result = _task_summary(t, float_val)
    result["is_critical"] = is_critical
    result["near_critical"] = task_id in cp.get("near_critical", [])
    return json.dumps(result)


def search_tasks(query: str) -> str:
    """Fuzzy-search tasks by name or CAM name; return up to 10 matches."""
    tasks = _get_tasks()
    cp = _get_cp()
    q = query.lower()
    matches = [
        t for t in tasks
        if q in t["name"].lower() or q in (t.get("cam") or "").lower()
    ][:10]
    if not matches:
        return json.dumps({"results": [], "message": f"No tasks found matching '{query}'."})
    return json.dumps({
        "results": [
            _task_summary(t, cp["total_float"].get(t["task_id"]))
            for t in matches
        ],
        "count": len(matches),
    })


def get_critical_path() -> str:
    """Return the ordered critical path with task names, dates, and float."""
    tasks = _get_tasks()
    cp = _get_cp()
    task_map = {t["task_id"]: t for t in tasks}
    cp_tasks = [
        {
            **_task_summary(task_map[tid], cp["total_float"].get(tid, 0)),
            "is_critical": True,
        }
        for tid in cp["critical_path"]
        if tid in task_map
    ]
    return json.dumps({
        "critical_path_tasks": cp_tasks,
        "count": len(cp_tasks),
        "projected_finish": _fmt_date(cp.get("projected_finish")),
    })


def get_tasks_by_cam(cam_name: str) -> str:
    """Return all tasks owned by a CAM with current status and float."""
    tasks = _get_tasks()
    cp = _get_cp()
    q = cam_name.lower()
    cam_tasks = [t for t in tasks if q in (t.get("cam") or "").lower()]
    if not cam_tasks:
        return json.dumps({"error": f"No tasks found for CAM '{cam_name}'."})
    return json.dumps({
        "cam": cam_tasks[0].get("cam", cam_name),
        "task_count": len(cam_tasks),
        "tasks": [
            _task_summary(t, cp["total_float"].get(t["task_id"]))
            for t in cam_tasks
        ],
    })


def get_float(task_id: str) -> str:
    """Return total float and near-critical flag for a specific task."""
    tasks = _get_tasks()
    cp = _get_cp()
    t = next((x for x in tasks if x["task_id"] == task_id), None)
    if t is None:
        return json.dumps({"error": f"Task ID '{task_id}' not found."})
    float_val = cp["total_float"].get(task_id)
    return json.dumps({
        "task_id": task_id,
        "name": t["name"],
        "total_float_days": round(float_val, 1) if float_val is not None else None,
        "is_critical": task_id in cp["critical_path"],
        "near_critical": task_id in cp.get("near_critical", []),
    })


def get_dependencies(task_id: str) -> str:
    """Return predecessor and successor task IDs and names for a task."""
    tasks = _get_tasks()
    task_map = {t["task_id"]: t for t in tasks}
    t = task_map.get(task_id)
    if t is None:
        return json.dumps({"error": f"Task ID '{task_id}' not found."})

    predecessors = [
        {"task_id": pid, "name": task_map[pid]["name"] if pid in task_map else "Unknown"}
        for pid in t.get("predecessors", [])
    ]
    successors = [
        {
            "task_id": s["task_id"],
            "name": s["name"],
        }
        for s in tasks
        if task_id in s.get("predecessors", [])
    ]
    return json.dumps({
        "task_id": task_id,
        "name": t["name"],
        "predecessors": predecessors,
        "successors": successors,
    })


def get_milestones() -> str:
    """Return all milestone tasks with baseline and forecast dates."""
    tasks = _get_tasks()
    cp = _get_cp()
    milestones = [t for t in tasks if t.get("is_milestone")]
    return json.dumps({
        "milestones": [
            _task_summary(t, cp["total_float"].get(t["task_id"]))
            for t in milestones
        ],
        "count": len(milestones),
    })


def get_behind_tasks(threshold_pct: float = 0.0) -> str:
    """Return tasks whose actual % complete is below expected progress by at least threshold_pct points."""
    from datetime import datetime as dt
    tasks = _get_tasks()
    cp = _get_cp()
    now = dt.now()
    behind = []
    for t in tasks:
        if t.get("is_milestone"):
            continue
        start = t.get("start")
        finish = t.get("finish")
        if not start or not finish:
            continue
        total = (finish - start).total_seconds()
        if total <= 0:
            continue
        elapsed = (now - start).total_seconds()
        expected = max(0, min(100, int(elapsed / total * 100)))
        actual = t.get("percent_complete", 0)
        gap = expected - actual
        if gap >= threshold_pct:
            entry = _task_summary(t, cp["total_float"].get(t["task_id"]))
            entry["expected_pct"] = expected
            entry["variance_pct"] = gap
            behind.append(entry)

    behind.sort(key=lambda x: x["variance_pct"], reverse=True)
    return json.dumps({
        "behind_tasks": behind[:20],
        "count": len(behind),
        "threshold_pct": threshold_pct,
    })


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "get_task": lambda args: get_task(args["task_id"]),
    "search_tasks": lambda args: search_tasks(args["query"]),
    "get_critical_path": lambda args: get_critical_path(),
    "get_tasks_by_cam": lambda args: get_tasks_by_cam(args["cam_name"]),
    "get_float": lambda args: get_float(args["task_id"]),
    "get_dependencies": lambda args: get_dependencies(args["task_id"]),
    "get_milestones": lambda args: get_milestones(),
    "get_behind_tasks": lambda args: get_behind_tasks(float(args.get("threshold_pct", 0))),
}


def call_tool(name: str, args: dict) -> str:
    """Execute a tool by name and return its JSON result string."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(args)
        logger.info("action=tool_call tool=%s args=%s", name, list(args.keys()))
        return result
    except Exception as exc:
        logger.error("action=tool_error tool=%s error=%s", name, exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Anthropic tool_use schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_task",
        "description": (
            "Look up full details for a specific task by its task ID. "
            "Returns name, CAM, percent complete, start/finish dates, baseline dates, "
            "duration, predecessors, total float, and whether it is on the critical path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID (e.g. '3', '21')"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "search_tasks",
        "description": (
            "Search for tasks by name or CAM name. Use this when the user references a task "
            "by name (e.g. 'SE-03', 'ICDs', 'PDR Package') or asks about a specific CAM's tasks. "
            "Returns up to 10 matching tasks with key fields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Task name fragment or CAM name to search for"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_critical_path",
        "description": (
            "Return the full ordered critical path with task names, start/finish dates, "
            "CAM assignments, and float values. Use this for detailed critical path questions."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_tasks_by_cam",
        "description": (
            "Return all tasks assigned to a specific CAM with their current status, "
            "percent complete, dates, and float. Use for questions about a specific person's workload."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cam_name": {"type": "string", "description": "Full or partial CAM name (e.g. 'Alice', 'Bob Martinez')"},
            },
            "required": ["cam_name"],
        },
    },
    {
        "name": "get_float",
        "description": (
            "Return the total float (schedule slack) in days for a specific task. "
            "Also indicates whether the task is critical or near-critical."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_dependencies",
        "description": (
            "Return the predecessor and successor tasks for a given task ID. "
            "Use this for dependency chain questions like 'what blocks X' or 'what does X feed into'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_milestones",
        "description": (
            "Return all program milestones with baseline and forecast dates. "
            "Use for milestone-specific questions that need exact dates from the schedule."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_behind_tasks",
        "description": (
            "Return tasks that are behind their expected progress, sorted by variance. "
            "Optionally filter by minimum gap between expected and actual percent complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold_pct": {
                    "type": "number",
                    "description": "Minimum variance in percentage points to include (default 0 = all behind tasks)",
                },
            },
            "required": [],
        },
    },
]
