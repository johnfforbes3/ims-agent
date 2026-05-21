"""
CAM interview state machine — Phase 17.

Article §4 + §11 #3: "Move to a real state machine the day the system prompt
crosses 300 words. Do not try to encode a state machine in prose."

The existing Phase 12 `interview_agent.py` encodes the interview flow as
prose in a Claude system prompt. That works for text turns but the article
warns it falls apart in voice context — the LLM will invent a `commit_baseline`
call while still in the greeting phase, narrate actions it didn't perform,
etc. Voice latency makes the failures painful (you don't notice until the
CAM is mid-confused-reply 4 seconds later).

This module encodes the same flow as a real FSM. Each state has:
    - a `system_prompt_addendum` that the LLM sees ONLY when in that state
    - an `allowed_tools` list — physically absent from the OpenAI call when
      not in this state (the LLM literally cannot call them)
    - a transition function `next_state(state, tool_calls, transcript)`

Article quote: "The state machine is the safety rail, not the system prompt."

States:
    GREETING            — agent greets, asks if CAM is ready to start
    OPEN_QUESTION       — "what would you like to update first?" (freeform)
    TASK_BY_TASK_LOOP   — iterate over CAM's tasks, ask % complete + blockers
    CONFIRM_BLOCK       — read back all proposed updates, await yes/no
    COMMIT              — write to pending_cam_inputs (still gated by PM approval)
    WRAPUP              — graceful close
    ESCALATE            — terminal; hardcoded escalation phrase

Tool scoping (Python-enforced, NOT prompt-enforced):
    GREETING            → []  (only natural language)
    OPEN_QUESTION       → [start_task_loop]
    TASK_BY_TASK_LOOP   → [propose_percent_complete, capture_blocker,
                           capture_risk, move_to_next_task,
                           ready_for_confirmation]
    CONFIRM_BLOCK       → [confirm_all, reject_all, edit_one]
    COMMIT              → [write_pending_cam_inputs]  (terminal action)
    WRAPUP              → []
    ESCALATE            → []

The actual function-call shapes are defined in `tool_specs()`. The orchestrator
in pipeline.py reads `allowed_tools(state)` to build the OpenAI tools array for
each call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class State(str, Enum):
    GREETING = "GREETING"
    OPEN_QUESTION = "OPEN_QUESTION"
    TASK_BY_TASK_LOOP = "TASK_BY_TASK_LOOP"
    CONFIRM_BLOCK = "CONFIRM_BLOCK"
    COMMIT = "COMMIT"
    WRAPUP = "WRAPUP"
    ESCALATE = "ESCALATE"


# ──────────────────────────────────────────────────────────────────────────
# Tool specifications — passed to OpenAI Chat Completions as `tools`.
# Each tool is a function the LLM can call when in a state that allows it.
# ──────────────────────────────────────────────────────────────────────────


def tool_specs() -> dict[str, dict]:
    """Return the full library of tool specs. Used by `allowed_tools()` to slice per state."""
    return {
        "start_task_loop": {
            "name": "start_task_loop",
            "description": (
                "Begin walking through the CAM's tasks one at a time. Call this "
                "after the CAM has greeted you and indicated they are ready to "
                "give status. Do not call this in the GREETING state."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        "propose_percent_complete": {
            "name": "propose_percent_complete",
            "description": (
                "The CAM has stated a percent-complete value for the current task. "
                "Extract it from their speech and propose it. Do NOT commit yet — "
                "this only stages the value. The CAM must confirm in CONFIRM_BLOCK "
                "before anything is written. Spoken 'fifty percent' → 50."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "IMS task ID."},
                    "percent_complete": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["task_id", "percent_complete"],
                "additionalProperties": False,
            },
        },
        "capture_blocker": {
            "name": "capture_blocker",
            "description": (
                "The CAM has described a blocker. Capture the text verbatim, "
                "do not paraphrase. Empty string allowed if CAM says no blocker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "blocker_text": {"type": "string"},
                },
                "required": ["task_id", "blocker_text"],
                "additionalProperties": False,
            },
        },
        "capture_risk": {
            "name": "capture_risk",
            "description": (
                "The CAM has flagged a risk. Capture flag + description. "
                "risk_flag is true when CAM uses words like 'risk', 'concern', "
                "'worried about', or volunteers a forward-looking issue."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "risk_flag": {"type": "boolean"},
                    "risk_description": {"type": "string"},
                },
                "required": ["task_id", "risk_flag", "risk_description"],
                "additionalProperties": False,
            },
        },
        "move_to_next_task": {
            "name": "move_to_next_task",
            "description": (
                "All updates captured for the current task. Move pointer to the "
                "next task in the CAM's task list. Caller will pass the new task "
                "context in the next system message."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        "ready_for_confirmation": {
            "name": "ready_for_confirmation",
            "description": (
                "All tasks have been covered. Transition to CONFIRM_BLOCK where "
                "the agent will read back the full set of proposed updates and "
                "ask the CAM to confirm yes/no."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        "confirm_all": {
            "name": "confirm_all",
            "description": (
                "CAM has explicitly confirmed all proposed updates are correct. "
                "Transitions to COMMIT. Do not call this on partial confirmation "
                "or hesitation — that is edit_one."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        "reject_all": {
            "name": "reject_all",
            "description": (
                "CAM has rejected the proposed updates. Transitions to ESCALATE "
                "so a human PM can re-run the interview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "edit_one": {
            "name": "edit_one",
            "description": (
                "CAM wants to change one specific value before committing. "
                "Return to TASK_BY_TASK_LOOP scoped to that one task_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        },
        "write_pending_cam_inputs": {
            "name": "write_pending_cam_inputs",
            "description": (
                "Write the confirmed updates to data/pending_cam_inputs/. "
                "TERMINAL ACTION. The PM approval gate (Phase 16) still controls "
                "whether these reach the IMS. In dry-run mode (VOICE_AGENT_V2_DRY) "
                "the file is still written but marked dry_run:true."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# State definitions
# ──────────────────────────────────────────────────────────────────────────


# Tools allowed per state — physically scoped (LLM cannot see others)
_ALLOWED_BY_STATE: dict[State, list[str]] = {
    State.GREETING:          [],
    State.OPEN_QUESTION:     ["start_task_loop"],
    State.TASK_BY_TASK_LOOP: [
        "propose_percent_complete", "capture_blocker", "capture_risk",
        "move_to_next_task", "ready_for_confirmation",
    ],
    State.CONFIRM_BLOCK:     ["confirm_all", "reject_all", "edit_one"],
    State.COMMIT:            ["write_pending_cam_inputs"],
    State.WRAPUP:            [],
    State.ESCALATE:          [],
}


# Per-state system prompt addendum. Article §4 conversation rules:
# short sentences, mirror the user, one question per turn, spell numbers,
# never markdown or asterisks (TTS will speak them).
_PROMPT_BY_STATE: dict[State, str] = {
    State.GREETING: (
        "You are ATLAS, an automated assistant collecting weekly schedule "
        "status from a Cost Account Manager. You are speaking on a voice "
        "call. Keep replies SHORT (one or two sentences). Greet the CAM by "
        "name, briefly explain you'll be asking about their tasks, and ask "
        "if now is a good time. ONE QUESTION PER TURN. No markdown, no "
        "asterisks, no bullets — your text is read aloud. Spell numbers as "
        "words (say 'three' not '3') and spell IDs like 'A-Eye-zero-seven' "
        "with NATO phonetic for letters. Mirror the CAM's language."
    ),
    State.OPEN_QUESTION: (
        "The CAM is ready to give status. Ask an open question to let them "
        "lead — for example 'Which task would you like to update first?' "
        "Then call start_task_loop. ONE QUESTION PER TURN. SHORT REPLIES."
    ),
    State.TASK_BY_TASK_LOOP: (
        "Drive a structured task-by-task status interview. ONE question per "
        "turn. NO markdown. NO bullets. Short sentences."
        "\n\n"
        "TOOL CALLS — CRITICAL RULES:"
        "\n  • Only call capture_blocker if THIS turn's user message actually "
        "    mentions a blocker (or says 'no blocker' / similar). Do NOT call "
        "    it just because the prompt shows blocker_text as MISSING."
        "\n  • Only call capture_risk if THIS turn's user message actually "
        "    mentions a risk (or says 'no risk' / similar). Do NOT call it "
        "    speculatively."
        "\n  • Only call propose_percent_complete if THIS turn's message "
        "    contains a percent value (digit or word)."
        "\n  • NEVER invent values for fields the CAM didn't talk about."
        "\n\n"
        "VALUE EXTRACTION RULES:"
        "\n  • Percent: 'sixty' → 60, 'about half' → 50, 'mostly done' → 80, "
        "    'just started' → 10, 'not started' → 0. Range 0-100."
        "\n  • Blocker: verbatim text (no paraphrasing). 'No blocker' → \"\". "
        "\n  • Risk: risk_flag=true with verbatim risk_description, OR "
        "    risk_flag=false with description=\"\" for 'no risk'."
        "\n\n"
        "WHAT TO SAY (your reply text — but the system will OVERRIDE this "
        "with a template-driven question when state changes or fields are "
        "captured this turn, so don't overthink the text):"
        "\n  • If the CAM gave a value, briefly acknowledge it and ask for "
        "    the next missing field. Example: 'Got it, sixty percent. Any "
        "    blockers on this task?'"
        "\n  • If the CAM said something off-topic, briefly redirect: "
        "    'Got it. What's your percent complete on [task]?'"
        "\n\n"
        "DO NOT call ready_for_confirmation. The state machine advances "
        "automatically when all three fields are captured for the LAST task. "
        "If you accidentally do call it early, the system will ignore it.\n"
    ),
    State.CONFIRM_BLOCK: (
        "All updates are captured. The proposed updates are in the system "
        "message below. On the FIRST turn in this state, read them back to "
        "the CAM concisely: 'I have task one at sixty percent with blocker "
        "vendor delay, task two at thirty percent no blocker. Is that "
        "correct?' Then WAIT for the CAM's response. "
        "TOOL CALL RULES (call EVERY turn after read-back):"
        "\n  • CAM says 'yes' / 'correct' / 'right' / 'looks good' / "
        "    'confirm' / 'that's right' → call confirm_all in the same turn "
        "    AND say exactly: 'Updates submitted to your PM for approval. "
        "    Talk to you next cycle.' The write happens automatically."
        "\n  • CAM says 'no, change X' / 'wait, task one should be' → call "
        "    edit_one with the specific task_id."
        "\n  • CAM rejects everything ('no it's all wrong', 'start over') → "
        "    call reject_all with a brief reason."
        "ONE QUESTION PER TURN. NO MARKDOWN."
    ),
    State.COMMIT: (
        "Write the updates. Say one short sentence: 'Updates submitted to "
        "your PM for approval. Talk to you next cycle.' Then call "
        "write_pending_cam_inputs."
    ),
    State.WRAPUP: (
        "The interview is complete. Say one short goodbye. No tool calls."
    ),
    State.ESCALATE: (
        "Something has gone wrong or the CAM rejected the updates. Say the "
        "exact escalation phrase: 'I want to make sure I give you accurate "
        "information. Let me flag this for your PM and we will follow up.' "
        "Then stop. No tool calls."
    ),
}


@dataclass
class StateContext:
    """Snapshot of conversation state. The pipeline maintains one per CAM session."""

    state: State = State.GREETING
    cam_email: str = ""
    cam_name: str = ""
    cam_tasks: list[dict] = field(default_factory=list)
    current_task_idx: int = 0
    proposed_updates: dict[str, dict] = field(default_factory=dict)  # {task_id: {...}}
    # Phase 17 iter 11 — tasks the user explicitly chose to skip without
    # giving every field. These don't block all_tasks_complete().
    skipped_task_ids: set = field(default_factory=set)

    @property
    def current_task(self) -> Optional[dict]:
        if 0 <= self.current_task_idx < len(self.cam_tasks):
            return self.cam_tasks[self.current_task_idx]
        return None

    # Phase 17 iter 7 — per-task field completion tracking.
    # Each task needs THREE fields captured before we can move on:
    #   - percent_complete (a number 0-100)
    #   - blocker_text (any string including empty "" meaning explicit "no blocker")
    #   - risk_flag (boolean set, even if False)
    # The pipeline checks `field_captured()` after every tool dispatch and
    # auto-advances when all three are set.

    def field_captured(self, task_id: str, field_name: str) -> bool:
        """True iff a specific field has been explicitly captured for this task."""
        upd = self.proposed_updates.get(str(task_id), {})
        if field_name == "percent_complete":
            return upd.get("percent_complete") is not None
        if field_name == "blocker_text":
            # Even empty string counts — that's an explicit "no blocker"
            return "blocker_text" in upd
        if field_name == "risk_flag":
            return "risk_flag" in upd
        return False

    def task_complete(self, task_id: str) -> bool:
        """True iff all three required fields are captured for this task."""
        return (
            self.field_captured(task_id, "percent_complete")
            and self.field_captured(task_id, "blocker_text")
            and self.field_captured(task_id, "risk_flag")
        )

    def next_missing_field(self, task_id: str) -> Optional[str]:
        """Return the next field we still need from the CAM for this task.
        None when all three are captured."""
        for f in ("percent_complete", "blocker_text", "risk_flag"):
            if not self.field_captured(task_id, f):
                return f
        return None

    def all_tasks_complete(self) -> bool:
        """True iff every CAM task has all three fields captured OR was
        explicitly skipped by the user (iter 11)."""
        if not self.cam_tasks:
            return False
        return all(
            self.task_complete(str(t["task_id"]))
            or str(t["task_id"]) in self.skipped_task_ids
            for t in self.cam_tasks
        )


def allowed_tools(state: State, ctx: Optional[StateContext] = None) -> list[dict]:
    """Return the OpenAI tools array for the given state. Scoped — others are absent.

    Phase 17 iter 7 — for TASK_BY_TASK_LOOP, also gate `ready_for_confirmation`
    so the LLM can't end the interview prematurely. The tool only appears when
    we're on the last task AND all three fields are captured for it.
    """
    specs = tool_specs()
    names = list(_ALLOWED_BY_STATE.get(state, []))
    if state == State.TASK_BY_TASK_LOOP and ctx is not None:
        is_last = ctx.cam_tasks and ctx.current_task_idx == len(ctx.cam_tasks) - 1
        last_complete = (
            is_last
            and ctx.current_task
            and ctx.task_complete(str(ctx.current_task["task_id"]))
        )
        if not last_complete and "ready_for_confirmation" in names:
            names.remove("ready_for_confirmation")
    return [specs[name] for name in names if name in specs]


def system_prompt(state: State, ctx: StateContext) -> str:
    """Build the full system prompt for the given state + context."""
    base = _PROMPT_BY_STATE.get(state, "")
    if state == State.GREETING:
        base += (
            f"\n\nCAM NAME: {ctx.cam_name}\n"
            f"NUMBER OF TASKS TO COVER: {len(ctx.cam_tasks)}\n"
        )
    if state == State.TASK_BY_TASK_LOOP and ctx.current_task:
        t = ctx.current_task
        tid = str(t.get("task_id", "?"))
        total = len(ctx.cam_tasks)
        is_last = ctx.current_task_idx == total - 1
        # Phase 17 iter 7 — explicit per-task field state injected into prompt
        cur_upd = ctx.proposed_updates.get(tid, {})
        pct_state = (
            f"CAPTURED: {cur_upd['percent_complete']}%"
            if "percent_complete" in cur_upd else "MISSING — ask first"
        )
        blocker_state = (
            f"CAPTURED: {cur_upd.get('blocker_text', '')!r}"
            if "blocker_text" in cur_upd else "MISSING — ask after percent"
        )
        risk_state = (
            f"CAPTURED: risk={cur_upd.get('risk_flag', False)} "
            f"desc={cur_upd.get('risk_description', '')!r}"
            if "risk_flag" in cur_upd else "MISSING — ask after blocker"
        )
        next_task_name = ""
        if not is_last:
            try:
                next_task_name = ctx.cam_tasks[ctx.current_task_idx + 1].get("name", "next task")
            except Exception:
                next_task_name = "next task"
        next_field = ctx.next_missing_field(tid)
        base += (
            f"\n\nCURRENT TASK CONTEXT (task {ctx.current_task_idx + 1} of {total}):\n"
            f"  task_id: {tid}\n"
            f"  name:    {t.get('name', '?')}\n"
            f"  current percent_complete (per IMS): {t.get('percent_complete', 0)}\n"
            f"  baseline finish: {t.get('baseline_finish', '?')}\n"
            f"  IS_LAST_TASK: {is_last}\n"
            f"\n"
            f"FIELD STATE for current task {tid}:\n"
            f"  percent_complete: {pct_state}\n"
            f"  blocker_text:     {blocker_state}\n"
            f"  risk_flag:        {risk_state}\n"
            f"  NEXT MISSING FIELD: {next_field or '(all captured)'}\n"
        )
        if next_field is None and not is_last:
            base += (
                f"\nALL THREE FIELDS CAPTURED for task {tid}. In your next "
                f"reply you MUST: (a) call move_to_next_task, (b) briefly "
                f"acknowledge, (c) ask the percent question for the next "
                f"task '{next_task_name}'.\n"
            )
        elif next_field is None and is_last:
            base += (
                "\nALL THREE FIELDS CAPTURED for the LAST task. Call "
                "ready_for_confirmation now and acknowledge you're moving to "
                "confirmation.\n"
            )
    if state == State.CONFIRM_BLOCK and ctx.proposed_updates:
        lines = []
        # Iterate in cam_tasks order so the readback matches the order the
        # CAM gave them. dict iteration order is insertion order in Python
        # 3.7+ but explicit order is clearer + ordered-by-task is what users expect.
        ordered_ids = [str(t["task_id"]) for t in ctx.cam_tasks if str(t["task_id"]) in ctx.proposed_updates]
        for tid in ordered_ids:
            upd = ctx.proposed_updates[tid]
            tname = next((t["name"] for t in ctx.cam_tasks if str(t["task_id"]) == str(tid)), tid)
            blocker = upd.get("blocker_text", "")
            blocker_str = "no blocker" if not blocker else f"blocker {blocker!r}"
            risk_flag = upd.get("risk_flag", False)
            risk_str = "no risk" if not risk_flag else (
                f"risk {upd.get('risk_description', '')!r}"
            )
            lines.append(
                f"  - {tname} (task_id {tid}): "
                f"{upd.get('percent_complete', 'no change')}% complete · "
                f"{blocker_str} · {risk_str}"
            )
        base += (
            "\n\nPROPOSED UPDATES TO READ BACK (you MUST mention each task by "
            "name AND only the facts shown below — do NOT invent blockers, "
            "do NOT carry a blocker from one task onto another):\n"
            + "\n".join(lines)
        )
    return base


# Phase 17.1 — Python safety transitions for clear user signals.
#
# Baseline eval (V0) showed the LLM correctly extracts data into tool calls
# (33/39 tools-pass) but fails to call the advancing tool (ready_for_confirmation
# / confirm_all) on the same turn the user signals they're done. Result: only
# 6/39 conversations completed cleanly.
#
# Fix: when the LLM didn't advance but the user transcript contains clear
# advance-signals AND the StateContext shows we have enough data captured to
# warrant advancing, the state machine auto-advances. The article's "state
# machine is the safety rail" applies in BOTH directions — refuse bad transitions
# AND apply obvious-but-missed transitions. This is intent detection over LLM
# output, NOT data parsing, so it doesn't violate the article's "Python is the
# parser" rule (which is about data extraction).

_DONE_PHRASES = (
    "that's everything", "that's it", "that's all", "that is all",
    "that is everything", "all done", "we're done", "we are done",
    "nothing else", "no more tasks", "no more", "finished", "i'm done",
    "i am done", "go to confirmation", "ready to confirm",
    "let's wrap", "let us wrap", "wrap it up", "ready for confirmation",
)
# Standalone single-word "done" signals — checked separately so we don't
# false-positive on "I'm done with task one" (which means "next task").
_DONE_STANDALONE = (
    "done", "finished", "complete", "stop", "next", "wrap",
)
_YES_PHRASES = (
    "yes", "yeah", "yep", "correct", "that's right", "that is right",
    "looks good", "looks right", "looks correct", "confirmed", "confirm",
    "all good", "go ahead", "proceed", "approved", "approve",
    "sounds good", "perfect", "right",
)
# Negative — explicit reject in CONFIRM_BLOCK
_NO_PHRASES = (
    "no, it's wrong", "no it's wrong", "no that's wrong", "start over",
    "redo it", "redo this", "scrap that", "abort", "cancel",
)
# Edit signals — partial reject
_EDIT_PHRASES = (
    "wait", "change", "actually", "let me fix", "let me change",
    "correction", "not quite", "wrong on",
)


def _transcript_matches(transcript: str, phrases: tuple[str, ...]) -> bool:
    """Substring + word-boundary lite match. Case-insensitive, strips punctuation."""
    if not transcript:
        return False
    t = transcript.lower().strip()
    # Strip leading/trailing punctuation that interferes with substring matching
    t = t.strip(".,!?;:'\"")
    return any(p in t for p in phrases)


def _is_standalone_done(transcript: str) -> bool:
    """True iff the transcript is a single 'done'/'finished'/'next' word.

    Separate from _DONE_PHRASES because we don't want to treat 'done with task one'
    as the full-conversation-done signal — that means 'next task'.
    """
    if not transcript:
        return False
    t = transcript.lower().strip().strip(".,!?;:'\"")
    words = t.split()
    return len(words) <= 2 and any(w in _DONE_STANDALONE for w in words)


def _has_enough_data_to_confirm(ctx: Optional[StateContext]) -> bool:
    """True when at least one task has a captured update (any field).

    Stricter heuristics (every task has percent_complete + blocker) over-fit
    the happy path. We accept any captured update — the CONFIRM_BLOCK turn
    will read everything back, and the user can correct anything missing.
    """
    if not ctx or not ctx.proposed_updates:
        return False
    return len(ctx.proposed_updates) >= 1


def next_state(
    current: State,
    tool_calls: list[dict],
    transcript: str = "",
    ctx: Optional[StateContext] = None,
) -> State:
    """Pure function: compute the next state given the current state + LLM output.

    Transitions in priority order:
      1. Explicit LLM tool call (primary)
      2. Python safety transition on clear user signal (V1 — eval feedback)
      3. Stay in current state
    """
    called_names = {tc.get("name") for tc in (tool_calls or [])}

    if current == State.GREETING:
        if transcript:
            return State.OPEN_QUESTION
        return State.GREETING

    if current == State.OPEN_QUESTION:
        if "start_task_loop" in called_names:
            return State.TASK_BY_TASK_LOOP
        # SAFETY: user is giving status content directly, skip the "what would
        # you like to update?" loop and go to task processing.
        # Two triggers — either:
        #   (a) >= 4 words (richer than a simple greeting), OR
        #   (b) contains a status keyword regardless of length
        if transcript:
            t_lower = transcript.lower()
            status_keywords = (
                "task", "percent", "blocker", "risk", "complete",
                "behind", "ahead", "done", "finished", "stuck",
            )
            if len(transcript.split()) >= 4 or any(k in t_lower for k in status_keywords):
                return State.TASK_BY_TASK_LOOP
        return State.OPEN_QUESTION

    if current == State.TASK_BY_TASK_LOOP:
        if "ready_for_confirmation" in called_names:
            # Only honor the LLM's call when all tasks are actually complete.
            # Otherwise treat as a mistake and stay put — prompt + tool scoping
            # should have prevented this but defense-in-depth.
            if ctx and ctx.all_tasks_complete():
                return State.CONFIRM_BLOCK
            # Else stay in loop — don't let early ready_for_confirmation
            # collapse the interview.
            return State.TASK_BY_TASK_LOOP

        # Phase 17 iter 11 — explicit user-driven "move on" signal. ONLY fires
        # on SHORT standalone utterances that are clearly intent to advance,
        # not when "next task" appears INSIDE a longer factual statement.
        # Iter 8 had a critical bug: "Task two is at thirty percent" was
        # parsed as "user wants to move to task two" because of substring
        # match. The state machine then jumped an extra task ahead.
        wants_move = False
        if transcript:
            t = transcript.lower().strip().strip(".,!?;:'\"")
            word_count = len(t.split())
            # ONLY trigger on short utterances (<=6 words) AND only on
            # phrases that have no factual content (no percent, no "is at",
            # no "blocker", no "risk")
            has_factual_content = any(k in t for k in (
                "percent", "%", "blocker", "risk", "is at", "is now",
                "complete", "done", "started", "delay", "vendor",
            ))
            if word_count <= 6 and not has_factual_content:
                move_on_phrases = (
                    "move on", "next task", "next one", "go to next",
                    "skip this", "skip that", "let's move", "move to the next",
                    "move on please", "move to next", "skip ahead",
                )
                wants_move = any(p in t for p in move_on_phrases)
        if wants_move and ctx and ctx.current_task_idx < len(ctx.cam_tasks) - 1:
            ctx.current_task_idx += 1
            return State.TASK_BY_TASK_LOOP

        # Phase 17 iter 7 — auto-advance the per-task pointer when the current
        # task has all three fields captured. This fires WHETHER OR NOT the LLM
        # remembered to call move_to_next_task. Safety rail.
        if ctx and ctx.current_task:
            cur_tid = str(ctx.current_task["task_id"])
            if ctx.task_complete(cur_tid):
                if ctx.current_task_idx < len(ctx.cam_tasks) - 1:
                    ctx.current_task_idx += 1
                elif ctx.all_tasks_complete():
                    return State.CONFIRM_BLOCK
        # Honor explicit move_to_next_task too (LLM-driven), but ONLY when the
        # current task actually has data. The LLM occasionally calls this
        # tool by mistake on the first turn of a task (before any fields are
        # captured) which would skip the task entirely. Defense-in-depth:
        # the auto-advance above already fires when task_complete; this
        # branch only catches the explicit LLM-driven case for partial-task
        # advancement (>= percent_complete captured).
        if "move_to_next_task" in called_names and ctx and ctx.current_task:
            cur_tid = str(ctx.current_task["task_id"])
            has_any_data = bool(ctx.proposed_updates.get(cur_tid, {}))
            if has_any_data and ctx.current_task_idx < len(ctx.cam_tasks) - 1:
                ctx.current_task_idx += 1
            elif has_any_data and ctx.all_tasks_complete():
                return State.CONFIRM_BLOCK
        # SAFETY: user clearly signaled "done" with whole-conversation
        # finality AND every task has all fields → advance.
        done_signal = (
            _transcript_matches(transcript, _DONE_PHRASES)
            or _is_standalone_done(transcript)
        )
        if done_signal and ctx and ctx.all_tasks_complete():
            return State.CONFIRM_BLOCK
        # Phase 17 iter 8 — done signal AND we're past the last task: just
        # advance regardless of per-field completeness. User said they're done.
        if done_signal and ctx and ctx.current_task_idx >= len(ctx.cam_tasks) - 1:
            return State.CONFIRM_BLOCK
        return State.TASK_BY_TASK_LOOP

    if current == State.CONFIRM_BLOCK:
        if "confirm_all" in called_names:
            return State.WRAPUP
        if "reject_all" in called_names:
            return State.ESCALATE
        if "edit_one" in called_names:
            return State.TASK_BY_TASK_LOOP
        # SAFETY: explicit edit signal — go back to task loop
        if _transcript_matches(transcript, _EDIT_PHRASES):
            return State.TASK_BY_TASK_LOOP
        # SAFETY: explicit no — escalate
        if _transcript_matches(transcript, _NO_PHRASES):
            return State.ESCALATE
        # SAFETY: clear affirmative AND no negative — advance to WRAPUP.
        # Order matters: check negatives first so "no, change task one" goes
        # to TASK_BY_TASK_LOOP via _EDIT_PHRASES above, not WRAPUP.
        if _transcript_matches(transcript, _YES_PHRASES):
            return State.WRAPUP
        return State.CONFIRM_BLOCK

    if current == State.COMMIT:
        if "write_pending_cam_inputs" in called_names:
            return State.WRAPUP
        return State.WRAPUP

    return current  # WRAPUP / ESCALATE are terminal


def safety_transition_triggered(
    current: State,
    new: State,
    tool_calls: list[dict],
) -> bool:
    """True when the transition was forced by a safety rule, not the LLM.

    Used by the pipeline to fire the write_pending_cam_inputs side-effect
    when a safety transition advanced past CONFIRM_BLOCK without the LLM
    calling confirm_all.
    """
    called_names = {tc.get("name") for tc in (tool_calls or [])}
    if current == State.CONFIRM_BLOCK and new == State.WRAPUP:
        return "confirm_all" not in called_names
    return False


# Hardcoded escalation phrase — article §5. Never let the LLM improvise this.
ESCALATION_PHRASE = (
    "I want to make sure I give you accurate information. "
    "Let me flag this for your PM and we will follow up."
)
