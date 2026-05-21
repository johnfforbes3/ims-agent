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
        "You are walking through tasks one at a time. The current task "
        "context is in the most recent system message. EXTRACT EVERYTHING "
        "the CAM says into tool calls — don't wait for clean separation. If "
        "they give percent + blocker + risk in ONE utterance, call all three "
        "tool functions in the same turn. "
        "TOOL CALL RULES (call EVERY one that applies, in the same response):"
        "\n  • Percent stated (any form: '60', 'sixty percent', 'about half') → "
        "    propose_percent_complete with the extracted integer."
        "\n  • Blocker mentioned (any form: 'blocked by', 'waiting on', "
        "    'stuck on') → capture_blocker with verbatim text. If CAM said "
        "    'no blocker' explicitly, call capture_blocker with empty string."
        "\n  • Risk mentioned (any form: 'risk is', 'concerned about', "
        "    'might slip') → capture_risk with risk_flag=true. If CAM said "
        "    'no risk', call capture_risk with risk_flag=false."
        "\n  • CAM said 'next task' / 'move on' / 'next one' / 'task two' → "
        "    call move_to_next_task."
        "\n  • CAM said 'that's everything' / 'all done' / 'done' / 'that's "
        "    all' / 'finished' / 'no more' / 'we're good' → IMMEDIATELY call "
        "    ready_for_confirmation. Do not ask another task question."
        "\nNEVER paraphrase blockers — keep the CAM's exact wording. "
        "Use SHORT acknowledgment phrases ('got it', 'understood'). "
        "ONE QUESTION PER TURN."
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

    @property
    def current_task(self) -> Optional[dict]:
        if 0 <= self.current_task_idx < len(self.cam_tasks):
            return self.cam_tasks[self.current_task_idx]
        return None


def allowed_tools(state: State) -> list[dict]:
    """Return the OpenAI tools array for the given state. Scoped — others are absent."""
    specs = tool_specs()
    return [specs[name] for name in _ALLOWED_BY_STATE.get(state, []) if name in specs]


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
        total = len(ctx.cam_tasks)
        is_last = ctx.current_task_idx == total - 1
        base += (
            f"\n\nCURRENT TASK CONTEXT (task {ctx.current_task_idx + 1} of {total}):\n"
            f"  task_id: {t.get('task_id', '?')}\n"
            f"  name:    {t.get('name', '?')}\n"
            f"  current percent_complete (per IMS): {t.get('percent_complete', 0)}\n"
            f"  baseline finish: {t.get('baseline_finish', '?')}\n"
            f"  IS_LAST_TASK: {is_last}\n"
            f"\n"
            f"PROGRESS: covered {ctx.current_task_idx} / {total} tasks so far.\n"
            f"Updates captured so far: {list(ctx.proposed_updates.keys()) or 'none'}\n"
        )
        if is_last:
            base += (
                "\nThis is the LAST task. Once you've captured the percent/"
                "blocker/risk for it, OR when the CAM signals they're done "
                "('that's everything', 'all done', etc.), call "
                "ready_for_confirmation IMMEDIATELY.\n"
            )
    if state == State.CONFIRM_BLOCK and ctx.proposed_updates:
        lines = []
        for tid, upd in ctx.proposed_updates.items():
            tname = next((t["name"] for t in ctx.cam_tasks if str(t["task_id"]) == str(tid)), tid)
            lines.append(f"  - {tname}: {upd.get('percent_complete', 'no change')}% complete; "
                         f"blocker={upd.get('blocker_text', 'none')!r}; "
                         f"risk={upd.get('risk_flag', False)}")
        base += "\n\nPROPOSED UPDATES TO READ BACK:\n" + "\n".join(lines)
    return base


def next_state(
    current: State,
    tool_calls: list[dict],
    transcript: str = "",
    ctx: Optional[StateContext] = None,
) -> State:
    """Pure function: compute the next state given the current state + LLM output.

    The transition rules are encoded here, NOT in the prompt. This is the
    "safety rail" the article talks about: even if the LLM gets confused
    and tries to call write_pending_cam_inputs from the GREETING state,
    that tool isn't in `allowed_tools(GREETING)` so the call wouldn't have
    been generated. And if it ever IS generated (e.g. via prompt injection),
    this function refuses to transition.
    """
    called_names = {tc.get("name") for tc in (tool_calls or [])}

    if current == State.GREETING:
        # CAM acknowledged → move to open question. No tool call needed; we
        # transition on the next user turn after greeting.
        if transcript:
            return State.OPEN_QUESTION
        return State.GREETING

    if current == State.OPEN_QUESTION:
        if "start_task_loop" in called_names:
            return State.TASK_BY_TASK_LOOP
        return State.OPEN_QUESTION

    if current == State.TASK_BY_TASK_LOOP:
        if "ready_for_confirmation" in called_names:
            return State.CONFIRM_BLOCK
        if "move_to_next_task" in called_names and ctx:
            ctx.current_task_idx += 1
            if ctx.current_task_idx >= len(ctx.cam_tasks):
                return State.CONFIRM_BLOCK
        return State.TASK_BY_TASK_LOOP

    if current == State.CONFIRM_BLOCK:
        if "confirm_all" in called_names:
            # Auto-advance through COMMIT to WRAPUP — write_pending_cam_inputs
            # is a pure side-effect handled by the pipeline when it sees this
            # transition. Conversationally, the LLM's reply text on this same
            # turn IS the "updates submitted" goodbye, so the user hears one
            # smooth closing instead of waiting through an empty COMMIT turn.
            return State.WRAPUP
        if "reject_all" in called_names:
            return State.ESCALATE
        if "edit_one" in called_names:
            return State.TASK_BY_TASK_LOOP
        return State.CONFIRM_BLOCK

    if current == State.COMMIT:
        # Vestigial — kept so any LLM that DID call write_pending_cam_inputs
        # still advances correctly. Normal path skips COMMIT entirely.
        if "write_pending_cam_inputs" in called_names:
            return State.WRAPUP
        return State.WRAPUP  # auto-advance after one turn regardless

    return current  # WRAPUP / ESCALATE are terminal


# Hardcoded escalation phrase — article §5. Never let the LLM improvise this.
ESCALATION_PHRASE = (
    "I want to make sure I give you accurate information. "
    "Let me flag this for your PM and we will follow up."
)
