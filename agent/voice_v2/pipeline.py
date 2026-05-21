"""
Voice agent v2 pipeline orchestrator — Phase 17.

Wires the 5 components in the article's chained pipeline:
    transcript (from STT or text-input) → input_guard → state_machine →
    LLM (OpenAI) → output_guard → TTS (ElevenLabs)

The pipeline is INTENTIONALLY agnostic to the transport layer. Both the
web tester (WebSocket from browser mic) and the Teams voice-message
bridge call `process_transcript(...)` and get back an OrchestratedTurn
that knows everything about what happened.

Public entry points:
    Pipeline.start_session(cycle_id, cam_email, ...) -> Session
    session.process_audio_bytes(audio_bytes, filename)        -> OrchestratedTurn
    session.process_transcript(transcript)                    -> OrchestratedTurn
    session.replay_with_transcript(transcript, state_before)  -> OrchestratedTurn

Session state:
    Each Session holds one StateContext, manages state transitions, and
    appends one TurnLogEntry per turn. Sessions are cheap; create one per
    CAM per cycle.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent.voice_v2 import guards, judge, llm_openai, small_talk, stt_openai, tts, turn_log
from agent.voice_v2.state_machine import (
    ESCALATION_PHRASE,
    State,
    StateContext,
    allowed_tools,
    next_state,
    safety_transition_triggered,
    system_prompt,
)

logger = logging.getLogger(__name__)

_DRY_RUN = os.getenv("VOICE_AGENT_V2_DRY", "").lower() in ("1", "true", "yes")
_PENDING_DIR = Path(os.getenv("PENDING_CAM_INPUTS_DIR", "data/pending_cam_inputs"))


@dataclass
class OrchestratedTurn:
    """Everything that happened during one round-trip."""
    transcript: str
    state_before: State
    state_after: State
    reply_text: str
    audio_bytes: Optional[bytes] = None
    audio_first_byte_ms: int = 0
    audio_total_ms: int = 0
    voice_id: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    input_guard: guards.GuardResult = field(default_factory=guards.GuardResult)
    output_guard: guards.GuardResult = field(default_factory=guards.GuardResult)
    llm_cost_usd: float = 0.0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_first_token_ms: int = 0
    llm_total_ms: int = 0
    turn_id: str = ""
    error: Optional[str] = None


class Session:
    """One CAM × one cycle. Holds StateContext + conversation history."""

    def __init__(
        self,
        cycle_id: str,
        cam_email: str,
        cam_name: str,
        cam_tasks: list[dict],
        transport: str = "web_tester",
    ):
        self.cycle_id = cycle_id
        self.cam_email = cam_email
        self.cam_name = cam_name
        self.transport = transport
        self.ctx = StateContext(
            state=State.GREETING,
            cam_email=cam_email,
            cam_name=cam_name,
            cam_tasks=list(cam_tasks),
        )
        # Rolling chat history (article §11 #5: sliding window to prevent bloat)
        self._history: list[dict] = []
        self._max_history_turns = int(os.getenv("VOICE_AGENT_V2_HISTORY_TURNS", "10"))
        # Per-session turn counter — used by the LLM-as-judge sampler.
        self._turn_counter = 0
        # Phase 17 iter 3 — session persistence so a CAM can resume across
        # server restarts. Auto-loaded at start; persisted on every turn end.
        self._maybe_resume_session()

    # ---------- session persistence (Phase 17 iter 3) ----------

    def _session_path(self) -> Path:
        safe = (self.cam_email or self.cam_name or "unknown").replace("@", "_at_").replace(".", "_")
        return Path(os.getenv("VOICE_SESSION_DIR", "data/voice_sessions")) / f"{self.cycle_id}_{safe}.json"

    def _maybe_resume_session(self) -> None:
        """Load saved StateContext + history from prior session if it exists."""
        p = self._session_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self.ctx.state = State(data["state"])
            self.ctx.current_task_idx = int(data.get("current_task_idx", 0))
            self.ctx.proposed_updates = dict(data.get("proposed_updates", {}))
            self._history = list(data.get("history", []))
            self._turn_counter = int(data.get("turn_counter", 0))
            logger.info(
                "action=voice_session_resumed cam=%s state=%s history_turns=%d",
                self.cam_email, self.ctx.state.value, len(self._history),
            )
        except Exception as exc:
            logger.warning("action=voice_session_resume_failed error=%s", exc)

    def _persist_session(self) -> None:
        """Atomically write current session state. Called at end of every turn."""
        p = self._session_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cycle_id": self.cycle_id,
            "cam_email": self.cam_email,
            "cam_name": self.cam_name,
            "state": self.ctx.state.value,
            "current_task_idx": self.ctx.current_task_idx,
            "proposed_updates": self.ctx.proposed_updates,
            "history": self._history,
            "turn_counter": self._turn_counter,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        try:
            os.replace(tmp, p)
        except OSError as exc:
            logger.debug("action=voice_session_persist_failed error=%s", exc)

    # ---------- transcript-in / audio-in entry points ----------

    def process_audio_bytes(
        self,
        audio_bytes: bytes,
        filename: str = "audio.webm",
    ) -> OrchestratedTurn:
        """Full path: STT → guards → LLM → guards → TTS. Used by web tester."""
        try:
            stt = stt_openai.transcribe_bytes(audio_bytes, filename=filename)
            transcript = stt.text
        except Exception as exc:
            logger.error("action=pipeline_stt_failed error=%s", exc)
            return self._failed_turn(str(exc), state_before=self.ctx.state)
        return self._process_inner(
            transcript=transcript,
            audio_in_ms=int(stt.duration_seconds * 1000),
            stt_first_partial_ms=stt.latency_ms,
            stt_final_ms=stt.latency_ms,
        )

    def process_transcript(self, transcript: str) -> OrchestratedTurn:
        """Skip STT. Used for unit tests + eval set + Teams text-only fallback."""
        return self._process_inner(transcript=transcript)

    def replay_with_transcript(self, transcript: str, state_before: Optional[str] = None) -> OrchestratedTurn:
        """Replay endpoint helper — temporarily override state_before."""
        original_state = self.ctx.state
        if state_before:
            try:
                self.ctx.state = State(state_before)
            except ValueError:
                pass
        try:
            return self._process_inner(transcript=transcript)
        finally:
            self.ctx.state = original_state

    # ---------- core orchestration ----------

    def _process_inner(
        self,
        transcript: str,
        audio_in_ms: int = 0,
        stt_first_partial_ms: int = 0,
        stt_final_ms: int = 0,
    ) -> OrchestratedTurn:
        state_before = self.ctx.state

        with turn_log.TurnRecorder(
            cycle_id=self.cycle_id,
            cam_email=self.cam_email,
            cam_name=self.cam_name,
            transport=self.transport,
        ) as entry:
            entry.state_before = state_before.value
            entry.audio_in_ms = audio_in_ms
            entry.stt_first_partial_ms = stt_first_partial_ms
            entry.stt_final_ms = stt_final_ms
            entry.stt_transcript = transcript
            entry.dry_run = _DRY_RUN

            # 1. INPUT GUARD
            cleaned, in_guard = guards.apply_input_guard(transcript)
            entry.input_guard = {
                "passed": in_guard.passed,
                "categories": in_guard.categories,
                "rewrites": in_guard.rewrites,
            }
            if not in_guard.passed:
                # Blocked input — speak the replacement and bail out of this turn
                reply_text = in_guard.replacement or ESCALATION_PHRASE
                tts_result = self._safe_tts(reply_text)
                entry.llm_text_out = reply_text
                entry.tts_first_audio_ms = tts_result.first_audio_ms
                entry.tts_full_audio_ms = tts_result.total_ms
                entry.tts_voice_id = tts_result.voice_id
                entry.state_after = state_before.value  # stay in same state
                return OrchestratedTurn(
                    transcript=transcript,
                    state_before=state_before,
                    state_after=state_before,
                    reply_text=reply_text,
                    audio_bytes=tts_result.audio_bytes,
                    audio_first_byte_ms=tts_result.first_audio_ms,
                    audio_total_ms=tts_result.total_ms,
                    voice_id=tts_result.voice_id,
                    input_guard=in_guard,
                    turn_id=entry.turn_id,
                )

            # 1.5 SMALL-TALK GATE — Phase 17 iteration 2.
            # Article §11 #6: "Build the small-talk gate before you build
            # retrieval. 'Hi' is the cheapest 200ms win in the system."
            # For GREETING state with a simple "Hi" / "Alice here." / etc.,
            # skip the LLM entirely and use a deterministic reply.
            if state_before == State.GREETING and small_talk.is_small_talk_greeting(cleaned):
                reply_text = small_talk.greeting_reply(
                    cam_first_name=self.cam_name,
                    task_count=len(self.ctx.cam_tasks),
                )
                tts_result = self._safe_tts(reply_text)
                new_state = State.OPEN_QUESTION
                self.ctx.state = new_state
                entry.state_after = new_state.value
                entry.llm_model = "small_talk_gate"
                entry.llm_text_out = reply_text
                if tts_result:
                    entry.tts_first_audio_ms = tts_result.first_audio_ms
                    entry.tts_full_audio_ms = tts_result.total_ms
                    entry.tts_voice_id = tts_result.voice_id
                self._history.append({"role": "user",      "content": cleaned})
                self._history.append({"role": "assistant", "content": reply_text})
                return OrchestratedTurn(
                    transcript=transcript,
                    state_before=state_before,
                    state_after=new_state,
                    reply_text=reply_text,
                    audio_bytes=tts_result.audio_bytes if tts_result else None,
                    audio_first_byte_ms=entry.tts_first_audio_ms,
                    audio_total_ms=entry.tts_full_audio_ms,
                    voice_id=tts_result.voice_id if tts_result else "",
                    input_guard=in_guard,
                    turn_id=entry.turn_id,
                )

            # And for OPEN_QUESTION turns that are just "OK ready", deterministic too.
            if state_before == State.OPEN_QUESTION and small_talk.is_ready_acknowledgment(cleaned):
                first_task = self.ctx.cam_tasks[0] if self.ctx.cam_tasks else None
                if first_task:
                    reply_text = small_talk.open_question_reply(first_task.get("name", "your first task"))
                    tts_result = self._safe_tts(reply_text)
                    new_state = State.TASK_BY_TASK_LOOP
                    self.ctx.state = new_state
                    entry.state_after = new_state.value
                    entry.llm_model = "small_talk_gate"
                    entry.llm_text_out = reply_text
                    if tts_result:
                        entry.tts_first_audio_ms = tts_result.first_audio_ms
                        entry.tts_full_audio_ms = tts_result.total_ms
                        entry.tts_voice_id = tts_result.voice_id
                    self._history.append({"role": "user",      "content": cleaned})
                    self._history.append({"role": "assistant", "content": reply_text})
                    return OrchestratedTurn(
                        transcript=transcript,
                        state_before=state_before,
                        state_after=new_state,
                        reply_text=reply_text,
                        audio_bytes=tts_result.audio_bytes if tts_result else None,
                        audio_first_byte_ms=entry.tts_first_audio_ms,
                        audio_total_ms=entry.tts_full_audio_ms,
                        voice_id=tts_result.voice_id if tts_result else "",
                        input_guard=in_guard,
                        turn_id=entry.turn_id,
                    )

            # 2. LLM CALL (with state-scoped tools)
            messages = self._build_messages(state_before, cleaned)
            tools = allowed_tools(state_before)
            model = self._choose_model(state_before, cleaned)
            entry.llm_model = model

            try:
                result = llm_openai.chat(
                    messages=messages,
                    model=model,
                    tools=tools,
                    max_tokens=300,
                    temperature=0.3,
                )
            except llm_openai.SpendCapExceeded as exc:
                # Hard stop — fail fast, do not retry
                logger.error("action=pipeline_spend_cap_exceeded %s", exc)
                entry.error = str(exc)
                tts_result = self._safe_tts(ESCALATION_PHRASE)
                entry.llm_text_out = ESCALATION_PHRASE
                entry.tts_voice_id = tts_result.voice_id
                entry.state_after = state_before.value
                return OrchestratedTurn(
                    transcript=transcript,
                    state_before=state_before,
                    state_after=state_before,
                    reply_text=ESCALATION_PHRASE,
                    audio_bytes=tts_result.audio_bytes,
                    voice_id=tts_result.voice_id,
                    turn_id=entry.turn_id,
                    error=str(exc),
                )

            entry.llm_first_token_ms = result.first_token_ms
            entry.llm_full_response_ms = result.total_ms
            entry.llm_input_tokens = result.input_tokens
            entry.llm_output_tokens = result.output_tokens
            entry.llm_cost_usd = result.cost_usd
            entry.llm_tool_calls = result.tool_calls
            entry.llm_text_out = result.text

            # 3. TOOL CALL DISPATCH — update StateContext from tool calls
            self._dispatch_tool_calls(result.tool_calls, state_before)

            # 4. STATE TRANSITION
            new_state = next_state(state_before, result.tool_calls, cleaned, self.ctx)
            self.ctx.state = new_state
            entry.state_after = new_state.value

            # 5. OUTPUT GUARD
            valid_task_ids = [str(t["task_id"]) for t in self.ctx.cam_tasks]
            sanitized, out_guard = guards.apply_output_guard(
                result.text, valid_task_ids=valid_task_ids,
            )
            entry.output_guard = {
                "passed": out_guard.passed,
                "categories": out_guard.categories,
                "rewrites": out_guard.rewrites,
            }
            reply_text = sanitized

            # If the LLM produced no text but only tool calls, give it one
            # acknowledgment phrase so we don't hand silence to TTS
            if not reply_text.strip() and result.tool_calls:
                reply_text = "Got it."

            # 6. TTS — only synthesize when we have text to say
            tts_result = self._safe_tts(reply_text) if reply_text.strip() else None
            if tts_result:
                entry.tts_first_audio_ms = tts_result.first_audio_ms
                entry.tts_full_audio_ms = tts_result.total_ms
                entry.tts_voice_id = tts_result.voice_id
                audio_bytes = tts_result.audio_bytes
                voice_id = tts_result.voice_id
            else:
                audio_bytes = None
                voice_id = ""

            # 7. Update rolling history (sliding window)
            self._history.append({"role": "user",      "content": cleaned})
            self._history.append({"role": "assistant", "content": reply_text})
            self._history = self._history[-(self._max_history_turns * 2):]

            # 8. Side effect: terminal write to pending_cam_inputs.
            # Triggered by ANY of:
            #   (a) write_pending_cam_inputs tool (legacy explicit COMMIT path)
            #   (b) confirm_all tool (collapsed CONFIRM_BLOCK→WRAPUP path)
            #   (c) Python safety transition CONFIRM_BLOCK→WRAPUP from user's
            #       clear "yes" / "correct" / "looks good" without LLM tool call
            # Each triggers the same write.
            terminal_names = {"write_pending_cam_inputs", "confirm_all"}
            should_write = (
                any(tc.get("name") in terminal_names for tc in result.tool_calls)
                or safety_transition_triggered(state_before, new_state, result.tool_calls)
            )
            if should_write and self.ctx.proposed_updates:
                self._write_pending_inputs()
                # Override reply text when safety fired so user hears the close
                if safety_transition_triggered(state_before, new_state, result.tool_calls):
                    if not reply_text or "Updates submitted" not in reply_text:
                        reply_text = (
                            "Updates submitted to your PM for approval. "
                            "Talk to you next cycle."
                        )
                        # Re-synthesize TTS for the override
                        tts_result = self._safe_tts(reply_text)
                        if tts_result:
                            audio_bytes = tts_result.audio_bytes
                            voice_id = tts_result.voice_id
                            entry.tts_first_audio_ms = tts_result.first_audio_ms
                            entry.tts_full_audio_ms = tts_result.total_ms
                            entry.tts_voice_id = tts_result.voice_id

            # 9. JUDGE (async — Phase 17 iter 3). Article §11 #9: every Nth
            # turn, fire a tiny LLM-as-judge call in the background to score
            # groundedness / naturalness / brevity / answered-correctly.
            # Cost: ~$0.0001 per judge. We don't block the pipeline on this.
            self._turn_counter += 1
            if judge.should_judge(self._turn_counter):
                judge.judge_turn_async(
                    cycle_id=self.cycle_id,
                    turn_id=entry.turn_id,
                    transcript=cleaned,
                    reply_text=reply_text,
                    tool_calls=result.tool_calls,
                    cam_tasks=self.ctx.cam_tasks,
                )

            # 10. PERSIST SESSION — survives process restart so a CAM can resume.
            self._persist_session()

            return OrchestratedTurn(
                transcript=transcript,
                state_before=state_before,
                state_after=new_state,
                reply_text=reply_text,
                audio_bytes=audio_bytes,
                audio_first_byte_ms=entry.tts_first_audio_ms,
                audio_total_ms=entry.tts_full_audio_ms,
                voice_id=voice_id,
                tool_calls=result.tool_calls,
                input_guard=in_guard,
                output_guard=out_guard,
                llm_cost_usd=result.cost_usd,
                llm_input_tokens=result.input_tokens,
                llm_output_tokens=result.output_tokens,
                llm_first_token_ms=result.first_token_ms,
                llm_total_ms=result.total_ms,
                turn_id=entry.turn_id,
            )

    # ---------- helpers ----------

    def _build_messages(self, state: State, transcript: str) -> list[dict]:
        msgs = [
            {"role": "system", "content": system_prompt(state, self.ctx)},
        ]
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": transcript})
        return msgs

    def _choose_model(self, state: State, transcript: str) -> str:
        """Article §4: small fast model for normal turns, big for hard ones.

        CONFIRM_BLOCK and ESCALATE are the high-stakes turns; everything else
        is a fast turn.
        """
        if state in (State.CONFIRM_BLOCK, State.ESCALATE):
            return os.getenv("VOICE_AGENT_V2_HARD_MODEL", "gpt-4o")
        return os.getenv("VOICE_AGENT_V2_MODEL", "gpt-4o-mini")

    def _safe_tts(self, text: str) -> tts.TTSResult:
        """Call TTS but never let it block the turn — return empty audio on failure."""
        try:
            voice_id = tts.voice_for_cam(self.cam_name, self.cam_email)
            return tts.synthesize(text, voice_id=voice_id)
        except Exception as exc:
            logger.error("action=pipeline_tts_failed error=%s", exc)
            return tts.TTSResult(audio_bytes=b"", voice_id="", char_count=0)

    def _dispatch_tool_calls(self, tool_calls: list[dict], state_before: State) -> None:
        """Update StateContext from tool calls. PURE STATE MUTATION — no side effects."""
        cur_task = self.ctx.current_task
        cur_tid = str(cur_task["task_id"]) if cur_task else None

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args", {})

            if name == "propose_percent_complete":
                tid = str(args.get("task_id") or cur_tid or "")
                pct = args.get("percent_complete")
                if tid and isinstance(pct, int) and 0 <= pct <= 100:
                    upd = self.ctx.proposed_updates.setdefault(tid, {})
                    upd["percent_complete"] = pct

            elif name == "capture_blocker":
                tid = str(args.get("task_id") or cur_tid or "")
                if tid:
                    upd = self.ctx.proposed_updates.setdefault(tid, {})
                    upd["blocker_text"] = args.get("blocker_text", "")

            elif name == "capture_risk":
                tid = str(args.get("task_id") or cur_tid or "")
                if tid:
                    upd = self.ctx.proposed_updates.setdefault(tid, {})
                    upd["risk_flag"] = bool(args.get("risk_flag", False))
                    upd["risk_description"] = args.get("risk_description", "")

            # move_to_next_task / ready_for_confirmation / confirm_all /
            # reject_all / edit_one / write_pending_cam_inputs are handled
            # by next_state() in the state machine (no context mutation here
            # beyond the index bump in move_to_next_task, which next_state
            # also handles).

    def _write_pending_inputs(self) -> Path:
        """Terminal side-effect: persist proposed updates to pending_cam_inputs.

        Article §3 + Phase 16 governance: this does NOT write to the IMS
        directly — it stages updates for the PM approval gate. In dry-run
        mode, the file is still written but marked dry_run:true.
        """
        cycle_dir = _PENDING_DIR / self.cycle_id
        cycle_dir.mkdir(parents=True, exist_ok=True)
        safe_email = self.cam_email.replace("@", "_at_").replace(".", "_")
        path = cycle_dir / f"{safe_email or self.cam_name or 'unknown'}.json"
        payload = {
            "cycle_id": self.cycle_id,
            "cam_email": self.cam_email,
            "cam_name": self.cam_name,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": _DRY_RUN,
            "source": "voice_agent_v2",
            "updates": [
                {
                    "task_id": tid,
                    "percent_complete": upd.get("percent_complete"),
                    "blocker": upd.get("blocker_text", ""),
                    "risk_flag": upd.get("risk_flag", False),
                    "risk_description": upd.get("risk_description", ""),
                }
                for tid, upd in self.ctx.proposed_updates.items()
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(
            "action=pending_cam_inputs_written path=%s updates=%d dry_run=%s",
            path, len(payload["updates"]), _DRY_RUN,
        )
        return path

    def _failed_turn(self, error: str, state_before: State) -> OrchestratedTurn:
        return OrchestratedTurn(
            transcript="",
            state_before=state_before,
            state_after=state_before,
            reply_text=ESCALATION_PHRASE,
            error=error,
        )


# ──────────────────────────────────────────────────────────────────────────
# Pipeline-level helpers
# ──────────────────────────────────────────────────────────────────────────


def start_session(
    cycle_id: str,
    cam_email: str,
    cam_name: str,
    cam_tasks: list[dict],
    transport: str = "web_tester",
) -> Session:
    """Factory for a new Session. Caller manages lifecycle."""
    return Session(
        cycle_id=cycle_id,
        cam_email=cam_email,
        cam_name=cam_name,
        cam_tasks=cam_tasks,
        transport=transport,
    )
