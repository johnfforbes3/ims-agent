"""
LLM-as-judge — Phase 17 iteration 3.

Article §11 #9: "Run an async LLM judge on every 50th call. Score on
groundedness, relevance, brevity. Pipe it to a dashboard. The drift
is real."

Our cycle cadence is weekly (5 CAMs × ~10 turns = 50 turns / cycle), so
"every 50th turn" = once per cycle. We do every 5th turn instead to get a
useful signal on the small per-cycle volume. Cost: ~$0.0001/judge call ×
10/cycle = $0.001/cycle. Negligible.

A judge produces four yes/no scores:
    answered_correctly  — did the agent actually address what the CAM said?
    stayed_grounded     — did the agent only use info from the CAM's task list?
    sounded_natural     — would this read OK out loud (no markdown / lists / asterisks)?
    appropriately_brief — is the reply <= 3 sentences for non-confirmation turns?

Judge runs ASYNC (fire-and-forget) so it doesn't block the user-facing
pipeline. Scores append to data/voice_judge/{cycle_id}.jsonl alongside
the turn log.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_JUDGE_DIR = Path(os.getenv("VOICE_JUDGE_DIR", "data/voice_judge"))
_SAMPLE_EVERY_N = int(os.getenv("VOICE_AGENT_V2_JUDGE_EVERY", "5"))


@dataclass
class JudgeScores:
    turn_id: str
    answered_correctly: bool
    stayed_grounded: bool
    sounded_natural: bool
    appropriately_brief: bool
    overall_pass: bool
    explanation: str = ""
    cost_usd: float = 0.0


_JUDGE_SYSTEM = (
    "You are a quality judge for a voice agent collecting weekly schedule "
    "status from project managers. You score one turn at a time on four "
    "yes/no criteria. Reply with VALID JSON ONLY, no markdown."
)


def _build_judge_prompt(transcript: str, reply_text: str, tool_calls: list[dict],
                        cam_tasks: list[dict]) -> str:
    task_summary = ", ".join(
        f"#{t.get('task_id')}={t.get('name')}" for t in (cam_tasks or [])[:6]
    ) or "(no task context)"
    tool_summary = (
        ", ".join(f"{tc.get('name')}({json.dumps(tc.get('args', {}))})"
                  for tc in (tool_calls or []))
        or "(no tools called)"
    )
    return (
        "Evaluate the agent's reply on four criteria. Reply with JSON object "
        'with keys: answered_correctly (bool), stayed_grounded (bool), '
        'sounded_natural (bool), appropriately_brief (bool), explanation '
        "(string, 1 sentence).\n\n"
        f"CAM_TASKS: {task_summary}\n"
        f"CAM_SAID: {transcript!r}\n"
        f"AGENT_REPLY: {reply_text!r}\n"
        f"TOOLS_CALLED: {tool_summary}\n\n"
        "Criteria:\n"
        "  answered_correctly: did the agent actually address what the CAM "
        "said (not redirect or repeat a stale question)?\n"
        "  stayed_grounded: did the agent only reference task IDs/names from "
        "CAM_TASKS (no invented tasks)?\n"
        "  sounded_natural: would this read OK out loud — no markdown, no "
        "asterisks, no bullet lists, no overly long sentences?\n"
        "  appropriately_brief: 3 sentences or fewer (unless reading back "
        "confirmations)?\n"
        "Return JSON only. Example:\n"
        '  {"answered_correctly": true, "stayed_grounded": true, '
        '"sounded_natural": true, "appropriately_brief": true, '
        '"explanation": "Got the percent and acknowledged."}'
    )


def should_judge(turn_seq: int) -> bool:
    """True iff this turn should be sampled for judging."""
    return _SAMPLE_EVERY_N > 0 and turn_seq > 0 and (turn_seq % _SAMPLE_EVERY_N == 0)


def judge_turn_async(
    cycle_id: str,
    turn_id: str,
    transcript: str,
    reply_text: str,
    tool_calls: list[dict],
    cam_tasks: list[dict],
) -> threading.Thread:
    """Fire-and-forget judge call. Returns the thread for cleanup/testing."""
    def _run():
        try:
            scores = _judge_turn(turn_id, transcript, reply_text, tool_calls, cam_tasks)
            _append(cycle_id, scores)
        except Exception as exc:
            logger.warning("action=voice_v2_judge_error error=%s", exc)

    t = threading.Thread(target=_run, daemon=True, name=f"voice_judge_{turn_id}")
    t.start()
    return t


def _judge_turn(turn_id: str, transcript: str, reply_text: str,
                tool_calls: list[dict], cam_tasks: list[dict]) -> JudgeScores:
    from agent.voice_v2 import llm_openai
    # Use the cheap model for judging — gpt-4o-mini is plenty
    result = llm_openai.chat(
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": _build_judge_prompt(
                transcript, reply_text, tool_calls, cam_tasks
            )},
        ],
        model="gpt-4o-mini",
        max_tokens=200,
        temperature=0.0,
        seed=42,
    )
    text = (result.text or "").strip()
    # Strip code fences if the LLM ignored "no markdown"
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        data = json.loads(text)
    except Exception:
        data = {"answered_correctly": False, "stayed_grounded": False,
                "sounded_natural": False, "appropriately_brief": False,
                "explanation": f"judge_parse_error: {text[:120]}"}
    return JudgeScores(
        turn_id=turn_id,
        answered_correctly=bool(data.get("answered_correctly", False)),
        stayed_grounded=bool(data.get("stayed_grounded", False)),
        sounded_natural=bool(data.get("sounded_natural", False)),
        appropriately_brief=bool(data.get("appropriately_brief", False)),
        overall_pass=all([
            data.get("answered_correctly"),
            data.get("stayed_grounded"),
            data.get("sounded_natural"),
            data.get("appropriately_brief"),
        ]),
        explanation=str(data.get("explanation", ""))[:240],
        cost_usd=result.cost_usd,
    )


def _append(cycle_id: str, scores: JudgeScores) -> None:
    _JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    p = _JUDGE_DIR / f"{cycle_id}.jsonl"
    line = json.dumps({
        "turn_id": scores.turn_id,
        "answered_correctly": scores.answered_correctly,
        "stayed_grounded": scores.stayed_grounded,
        "sounded_natural": scores.sounded_natural,
        "appropriately_brief": scores.appropriately_brief,
        "overall_pass": scores.overall_pass,
        "explanation": scores.explanation,
        "cost_usd": scores.cost_usd,
    }) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line)


def cycle_summary(cycle_id: str) -> Optional[dict]:
    """Aggregate judge scores for a cycle. Returns None when no scores."""
    p = _JUDGE_DIR / f"{cycle_id}.jsonl"
    if not p.exists():
        return None
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return None
    n = len(rows)
    return {
        "cycle_id": cycle_id,
        "judged_turns": n,
        "answered_correctly_pct": round(sum(r["answered_correctly"] for r in rows) / n * 100, 1),
        "stayed_grounded_pct":    round(sum(r["stayed_grounded"]    for r in rows) / n * 100, 1),
        "sounded_natural_pct":    round(sum(r["sounded_natural"]    for r in rows) / n * 100, 1),
        "appropriately_brief_pct": round(sum(r["appropriately_brief"] for r in rows) / n * 100, 1),
        "overall_pass_pct":       round(sum(r["overall_pass"]       for r in rows) / n * 100, 1),
        "total_judge_cost_usd":   round(sum(r.get("cost_usd", 0)    for r in rows), 6),
    }
