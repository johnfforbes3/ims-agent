"""
[DEPRECATED in Phase 17.4 — see docs/PHASE-17-INTEGRATION-PLAN.md]
Reply generation is now performed by `InterviewAgent` directly. This
module is kept for reference / rollback only.

Deterministic conversation drivers — Phase 17 iter 9.

The single biggest source of "stuck" conversations was the LLM's reply text
being generated under the OLD state's prompt while the state machine
transitioned to a NEW state. Concretely: the LLM in OPEN_QUESTION says
"Got it" + calls start_task_loop → state advances to TASK_BY_TASK_LOOP, but
the user only hears "Got it" with no follow-up question. Dead end.

The fix: when a state transition occurs OR when the agent enters a state
where the next action is mechanically obvious (ask the next missing field
about the current task), generate the reply text DETERMINISTICALLY from a
template, ignoring whatever the LLM said.

This is the article's "state machine is the safety rail" pattern applied
to OUTPUT (not just to state transitions). The LLM is great at extraction;
it's mediocre at threading state-aware questions across multiple turns in
a single conversation. So we take that responsibility back.

The templates here are intentionally narrow, voice-friendly, and never
have markdown.
"""

from __future__ import annotations

from typing import Optional

from agent.voice_v2.state_machine import State, StateContext


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _ack_for(transcript: str) -> str:
    """Short acknowledgment phrase to lead the reply. Keep it 2-3 words max."""
    if not transcript:
        return "Got it."
    t = transcript.lower().strip()
    # Don't sound robotic on a yes/no answer
    if t in ("yes", "yeah", "yep", "yes.", "yeah."):
        return "Great."
    if t in ("no", "nope", "no.", "nope."):
        return "Understood."
    if any(w in t for w in ("ok", "okay", "ready", "sure", "you lead")):
        return ""  # let the template lead with the actual question
    if any(w in t for w in ("blocker", "blocked", "stuck", "delay", "vendor")):
        return "Got it."
    if "risk" in t or "concern" in t or "slip" in t:
        return "Understood."
    return "Got it."


def _task_name(ctx: StateContext, idx: Optional[int] = None) -> str:
    """Return the task name at the given index, or current_task by default."""
    i = ctx.current_task_idx if idx is None else idx
    if 0 <= i < len(ctx.cam_tasks):
        return ctx.cam_tasks[i].get("name") or f"task {i+1}"
    return "your task"


def _percent_phrase(pct) -> str:
    """Convert an integer percent to a spoken phrase. TTS handles digits OK
    but spelling is sometimes clearer for short numbers."""
    if pct is None:
        return ""
    return f"{pct} percent"


# ──────────────────────────────────────────────────────────────────────────
# Per-state templates
# ──────────────────────────────────────────────────────────────────────────


def reply_for_state(state: State, ctx: StateContext,
                    transcript: str = "",
                    just_entered: bool = False,
                    fields_captured_this_turn: Optional[list[str]] = None) -> Optional[str]:
    """Generate the deterministic reply for the given state.

    Args:
        state:          the state we are now IN (after any transition)
        ctx:            the StateContext
        transcript:     the CAM's most recent utterance (for ack tone)
        just_entered:   True if this turn caused entry into this state
        fields_captured_this_turn: list of field names captured by this turn's
                                   router/LLM extraction (used to vary the ack)

    Returns:
        The reply text to use, or None to fall through to the LLM's reply.

    Returns None when the LLM's reply is the right thing (e.g. natural
    conversation that doesn't need a state-driven question). Returns a
    concrete string when we need to force a specific question.
    """
    fields_captured_this_turn = fields_captured_this_turn or []

    if state == State.GREETING:
        # Small-talk gate normally handles this; if we're still here, hand off
        return None

    if state == State.OPEN_QUESTION:
        # If we JUST entered this state from a small-talk greeting reply,
        # the user has acknowledged readiness. Ask the open question.
        if just_entered:
            return (
                f"Great. Let's start with {_task_name(ctx, 0)}. "
                f"What's your current percent complete?"
            )
        # Otherwise we're still here because the LLM hasn't called
        # start_task_loop yet. Don't override.
        return None

    if state == State.TASK_BY_TASK_LOOP:
        cur = ctx.current_task
        if not cur:
            return "I think we covered everything. Ready to confirm?"
        tid = str(cur["task_id"])
        cur_name = cur.get("name") or f"task {ctx.current_task_idx + 1}"
        upd = ctx.proposed_updates.get(tid, {})
        missing = ctx.next_missing_field(tid)
        ack = _ack_for(transcript)

        # If this turn captured percent and the next thing to ask is blocker
        if "percent_complete" in fields_captured_this_turn and missing == "blocker_text":
            pct = upd.get("percent_complete")
            return f"{ack} {_percent_phrase(pct)} on {cur_name}. Any blockers on this task?".strip()

        # If this turn captured blocker and the next thing to ask is risk
        if "blocker_text" in fields_captured_this_turn and missing == "risk_flag":
            return f"{ack} Any risks I should flag for {cur_name}?".strip()

        # If this turn captured risk and the task is now complete
        # (move to next task OR ready for confirm)
        if "risk_flag" in fields_captured_this_turn and missing is None:
            # All fields captured — did we just advance to next task?
            if ctx.current_task_idx < len(ctx.cam_tasks) - 1:
                next_name = _task_name(ctx, ctx.current_task_idx + 1)
                return (
                    f"{ack} Moving on to {next_name}. "
                    f"What's your current percent complete?"
                ).strip()
            # Last task complete — system will transition to CONFIRM_BLOCK
            # on the next turn (auto-advance in next_state). Let CONFIRM_BLOCK
            # handle the read-back.
            return f"{ack} That's everything. Let me read back what I have."

        # No fields captured this turn — figure out what to ask.
        # If we're entering a fresh task, ask for percent first.
        if missing == "percent_complete":
            # Either just entered this task (just_entered=True) or LLM
            # didn't extract a percent the CAM mentioned. Re-ask.
            if just_entered:
                return f"Now {cur_name}. What's your current percent complete?"
            return f"What's your current percent complete on {cur_name}?"

        if missing == "blocker_text":
            return f"Any blockers on {cur_name}?"

        if missing == "risk_flag":
            return f"Any risks I should flag for {cur_name}?"

        # Defensive fallback
        return f"What else can you tell me about {cur_name}?"

    if state == State.CONFIRM_BLOCK:
        if just_entered:
            # First turn in CONFIRM_BLOCK — read back the proposed updates
            ordered_ids = [
                str(t["task_id"]) for t in ctx.cam_tasks
                if str(t["task_id"]) in ctx.proposed_updates
            ]
            parts = []
            for tid in ordered_ids:
                upd = ctx.proposed_updates[tid]
                name = next(
                    (t["name"] for t in ctx.cam_tasks if str(t["task_id"]) == tid),
                    tid,
                )
                pct = upd.get("percent_complete")
                blocker = upd.get("blocker_text", "")
                risk = upd.get("risk_flag", False)
                bits = []
                if pct is not None:
                    bits.append(f"{pct} percent complete")
                if blocker:
                    bits.append(f"blocker {blocker}")
                elif "blocker_text" in upd:
                    bits.append("no blocker")
                if risk:
                    risk_desc = upd.get("risk_description") or "noted"
                    bits.append(f"risk: {risk_desc}")
                elif "risk_flag" in upd:
                    bits.append("no risk")
                parts.append(f"{name}, {', '.join(bits)}")
            if parts:
                body = "; ".join(parts)
                return (
                    f"OK. I have: {body}. Is that all correct?"
                )
            return "I have your updates ready. Is everything correct?"
        # Subsequent turns in CONFIRM_BLOCK — LLM handles yes/no/edit nuance
        return None

    if state == State.WRAPUP:
        if just_entered:
            return (
                "Updates submitted to your PM for approval. "
                "Talk to you next cycle."
            )
        return None

    if state == State.ESCALATE:
        from agent.voice_v2.state_machine import ESCALATION_PHRASE
        return ESCALATION_PHRASE

    return None
