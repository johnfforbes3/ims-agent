"""
Context builder — loads dashboard state and cycle history, assembles
targeted context slices for Q&A retrieval.

Design: the full dashboard state is ~20-50 KB of structured JSON.
Rather than a vector store, we load the state file and select the most
relevant sections based on detected query intent.  This is fast, always
fresh (no stale index), and requires no additional infrastructure.

For Phase 5, swap _load_state() with a Chroma/pgvector retriever when
rolling history across hundreds of cycles needs to be searched.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_STATE_FILE = Path(os.getenv("DASHBOARD_STATE_FILE", "data/dashboard_state.json"))
_HISTORY_FILE = Path(os.getenv("CYCLE_HISTORY_FILE", "data/cycle_history.json"))


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("critical_path",   [r"critical path", r"critical\b", r"cp\b"]),
    ("milestone",       [r"milestone", r"probability", r"prob.*hit", r"p50", r"p80", r"p95",
                         r"on.?time", r"PDR", r"CDR", r"TRR", r"SAT", r"SRR"]),
    ("cam_status",      [r"\bcam\b", r"cost account", r"who.*behind", r"behind.*who",
                         r"[A-Z][a-z]+ [A-Z][a-z]+.*behind", r"responded"]),
    ("risks",           [r"risk", r"top risk", r"biggest risk", r"concern"]),
    ("changes",         [r"change", r"since last", r"different", r"delta", r"new.*this cycle"]),
    ("float",           [r"float", r"slack\b", r"days.*left", r"near.?critical"]),
    ("blocker",         [r"block", r"why.*behind", r"reason.*behind", r"what.*stopping"]),
    ("actions",         [r"focus", r"should.*do", r"recommend", r"action", r"priority",
                         r"this week", r"today"]),
    ("health",          [r"health", r"status", r"overall", r"summary", r"how.*doing"]),
]


def detect_intent(question: str) -> list[str]:
    """Return list of matched intent keys (ordered, most specific first)."""
    q = question.lower()
    matched = []
    for intent, patterns in _INTENT_PATTERNS:
        if any(re.search(p, q) for p in patterns):
            matched.append(intent)
    return matched or ["health"]


# ---------------------------------------------------------------------------
# State loading
# ---------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    if not _STATE_FILE.exists():
        logger.warning("action=state_missing path=%s", _STATE_FILE)
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("action=state_load_error error=%s", exc)
        return {}


def load_history() -> list[dict]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def build_context(question: str) -> str:
    """
    Assemble a focused context string for the Q&A engine.

    Selects sections from dashboard state based on detected intent.
    Always includes the health header and last-updated timestamp.
    """
    state = load_state()
    if not state:
        return "No schedule data is available. A cycle must be run before questions can be answered."

    intents = detect_intent(question)
    logger.info("action=context_build intents=%s question=%r", intents, question[:80])

    sections: list[str] = []

    # Always include header
    sections.append(
        f"Schedule Health: {state.get('schedule_health', 'UNKNOWN')}  "
        f"(Last updated: {state.get('last_updated', 'unknown')}  "
        f"Cycle: {state.get('cycle_id', 'unknown')})"
    )

    if "health" in intents or not intents:
        narrative = state.get("narrative", "")
        if narrative:
            sections.append("\n--- NARRATIVE ---\n" + narrative[:1200])

    if "critical_path" in intents:
        cp_ids = state.get("critical_path_task_ids", [])
        sections.append(
            f"\n--- CRITICAL PATH ---\n"
            f"Tasks on critical path ({len(cp_ids)}): {', '.join(str(i) for i in cp_ids)}"
        )

    if "milestone" in intents or "critical_path" in intents:
        milestones = state.get("milestones", [])
        if milestones:
            lines = ["\n--- MILESTONE SRA RESULTS ---"]
            for m in milestones:
                lines.append(
                    f"  {m.get('milestone_name', m.get('task_id'))}: "
                    f"baseline={m.get('baseline_date')}, "
                    f"P50={m.get('p50_date')}, P80={m.get('p80_date')}, "
                    f"P95={m.get('p95_date')}, "
                    f"prob_on_time={m.get('prob_on_baseline', 0):.1%}, "
                    f"risk={m.get('risk_level')}"
                )
            sections.append("\n".join(lines))

    if "risks" in intents or "health" in intents:
        top_risks = state.get("top_risks", "")
        if top_risks:
            sections.append("\n--- TOP RISKS ---\n" + top_risks[:1500])

    if "actions" in intents or "health" in intents:
        actions = state.get("recommended_actions", "")
        if actions:
            sections.append("\n--- RECOMMENDED ACTIONS ---\n" + actions[:1200])

    if "cam_status" in intents:
        cam_resp = state.get("cam_response_status", {})
        if cam_resp:
            lines = ["\n--- CAM RESPONSE STATUS ---"]
            for cam, data in cam_resp.items():
                lines.append(
                    f"  {cam}: responded={data.get('responded')}, "
                    f"attempts={data.get('attempts')}, "
                    f"outcome={data.get('last_outcome')}"
                )
            sections.append("\n".join(lines))

    if "blocker" in intents or "cam_status" in intents or "float" in intents:
        tasks_behind = state.get("tasks_behind", [])
        if tasks_behind:
            lines = [f"\n--- TASKS BEHIND WITH BLOCKERS ({len(tasks_behind)}) ---"]
            for t in tasks_behind[:15]:
                lines.append(
                    f"  Task {t.get('task_id')} [{t.get('cam_name')}] "
                    f"{t.get('percent_complete')}% complete — "
                    f"{(t.get('blocker') or '')[:120]}"
                )
            sections.append("\n".join(lines))

    if "changes" in intents:
        history = load_history()
        if len(history) >= 2:
            prev = history[-2]
            curr = history[-1]
            lines = [
                "\n--- CYCLE HISTORY (last 2) ---",
                f"  Current  ({curr.get('cycle_id')}): health={curr.get('schedule_health')}, "
                f"cams={curr.get('cams_responded')}/{curr.get('cams_total')}",
                f"  Previous ({prev.get('cycle_id')}): health={prev.get('schedule_health')}, "
                f"cams={prev.get('cams_responded')}/{prev.get('cams_total')}",
            ]
            sections.append("\n".join(lines))
        full_history = load_history()
        if full_history:
            health_trend = [f"{h.get('cycle_id', '')[:8]}: {h.get('schedule_health')}"
                            for h in full_history[-5:]]
            sections.append("\n--- HEALTH TREND (last 5 cycles) ---\n  " + "  ".join(health_trend))

    return "\n".join(sections)
