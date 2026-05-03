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
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_STATE_FILE = Path(os.getenv("DASHBOARD_STATE_FILE", "data/dashboard_state.json"))
_HISTORY_FILE = Path(os.getenv("CYCLE_HISTORY_FILE", "data/cycle_history.json"))

# TD-016: 30-second TTL cache for load_state() / load_history().
# Invalidated early when the underlying file's mtime changes.
_STATE_CACHE: dict[str, Any] | None = None
_STATE_CACHE_AT: float = 0.0       # time.monotonic() when cache was filled
_STATE_CACHE_MTIME: float = 0.0    # st_mtime when cache was filled
_HISTORY_CACHE: list[dict] | None = None
_HISTORY_CACHE_AT: float = 0.0
_HISTORY_CACHE_MTIME: float = 0.0
_CACHE_TTL_S: float = 30.0


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
    """Load dashboard state, using a 30-second TTL cache (TD-016).

    The cache is invalidated early when ``dashboard_state.json``'s mtime
    changes — so a freshly completed cycle is always visible within one poll.
    """
    global _STATE_CACHE, _STATE_CACHE_AT, _STATE_CACHE_MTIME
    if not _STATE_FILE.exists():
        logger.warning("action=state_missing path=%s", _STATE_FILE)
        return {}
    try:
        mtime = _STATE_FILE.stat().st_mtime
        now = time.monotonic()
        if (
            _STATE_CACHE is not None
            and mtime == _STATE_CACHE_MTIME
            and (now - _STATE_CACHE_AT) < _CACHE_TTL_S
        ):
            return _STATE_CACHE
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        _STATE_CACHE = data
        _STATE_CACHE_AT = now
        _STATE_CACHE_MTIME = mtime
        logger.debug("action=state_cache_miss path=%s", _STATE_FILE)
        return data
    except Exception as exc:
        logger.error("action=state_load_error error=%s", exc)
        return {}


def load_history() -> list[dict]:
    """Load cycle history, using a 30-second TTL cache (TD-016)."""
    global _HISTORY_CACHE, _HISTORY_CACHE_AT, _HISTORY_CACHE_MTIME
    if not _HISTORY_FILE.exists():
        return []
    try:
        mtime = _HISTORY_FILE.stat().st_mtime
        now = time.monotonic()
        if (
            _HISTORY_CACHE is not None
            and mtime == _HISTORY_CACHE_MTIME
            and (now - _HISTORY_CACHE_AT) < _CACHE_TTL_S
        ):
            return _HISTORY_CACHE
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        _HISTORY_CACHE = data
        _HISTORY_CACHE_AT = now
        _HISTORY_CACHE_MTIME = mtime
        return data
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
