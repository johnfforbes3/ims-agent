"""
Interview Agent — conversation state machine for CAM status interviews.

Drives the structured interview conversation:
  GREETING → TASK_INTRO → AWAITING_PCT → [AWAITING_BLOCKER →
  AWAITING_RISK_FLAG → AWAITING_RISK_DESC] → CONFIRM → CLOSING → COMPLETE

NLU is handled by an LLM classifier (_classify_cam_response) so the agent
can understand natural, detailed human responses rather than just keywords.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = int(os.getenv("INTERVIEW_RESPONSE_TIMEOUT_SEC", "15"))
_MAX_RETRIES = int(os.getenv("INTERVIEW_MAX_RETRIES", "3"))

# Words / phrases that map to "I don't know yet"
_UNKNOWN_PHRASES = {
    "i don't know", "i dont know", "not sure", "unclear", "unknown",
    "haven't checked", "haven't looked", "need to check", "i'll have to check",
    "not available", "tbd", "to be determined",
}

# Words / phrases indicating the CAM believes they already completed this interview
_ALREADY_DONE_PHRASES = {
    "already did", "already done", "already answered", "just answered",
    "just did this", "we already", "did this already", "done this already",
    "already went through", "just went through", "already completed",
    "we covered this", "we did this", "did this last",
}

# Words / phrases that map to affirmative
_YES_PHRASES = {"yes", "yeah", "yep", "yup", "sure", "correct",
                "affirmative", "absolutely", "definitely", "that's right",
                "thats right", "confirmed", "confirm", "ok", "okay",
                "ready", "go ahead", "sure thing", "no problem"}

# Words / phrases that map to negative
_NO_PHRASES = {"no", "nope", "negative", "not really", "i don't think so",
               "i dont think so", "no risk", "no blocker", "none", "nothing"}


class InterviewState(Enum):
    """States in the CAM interview state machine."""
    GREETING = "greeting"
    TASK_INTRO = "task_intro"
    AWAITING_PCT = "awaiting_pct"
    AWAITING_EAC_DATE = "awaiting_eac_date"
    AWAITING_BLOCKER = "awaiting_blocker"
    AWAITING_RISK_FLAG = "awaiting_risk_flag"
    AWAITING_RISK_DESC = "awaiting_risk_desc"
    CONFIRM = "confirm"
    CLOSING = "closing"
    COMPLETE = "complete"
    NO_RESPONSE = "no_response"
    ABORTED = "aborted"


@dataclass
class TaskResult:
    """Status captured for a single task during an interview."""
    task_id: str
    cam_name: str
    percent_complete: int | None
    blocker: str
    risk_flag: bool
    risk_description: str
    status: str                  # "captured" | "no_response" | "skipped"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    eac_date: str | None = None  # ISO "YYYY-MM-DD" projected completion, or None
    eac_uncertain: bool = False  # True when CAM said "I don't know" → use linear SRA

    def to_cam_input_dict(self) -> dict[str, Any]:
        """Convert to the Phase 1 CAM input dict format."""
        return {
            "task_id": self.task_id,
            "cam_name": self.cam_name,
            "percent_complete": self.percent_complete or 0,
            "blocker": self.blocker,
            "risk_flag": self.risk_flag,
            "risk_description": self.risk_description,
            "timestamp": self.timestamp,
            "eac_date": self.eac_date,
            "eac_uncertain": self.eac_uncertain,
        }


@dataclass
class AgentTurn:
    """A single turn produced by the interview agent."""
    text: str                    # What the agent should say / speak
    state: InterviewState        # New state after this turn
    task_result: TaskResult | None = None   # Set when a task is finalised


@dataclass
class ConversationTurn:
    """A record of one full exchange (agent → CAM) for the transcript."""
    speaker: str                 # "agent" | "cam"
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class InterviewAgent:
    """
    Stateful conversation agent that interviews a single CAM.

    Usage:
        agent = InterviewAgent(cam_name, tasks, expected_pcts)
        # First turn — greeting
        turn = agent.start()
        speak(turn.text)
        # Main loop
        while agent.state not in (InterviewState.COMPLETE, InterviewState.ABORTED):
            utterance = listen()           # STT or simulator
            turn = agent.process(utterance)
            speak(turn.text)
        results = agent.results           # list[TaskResult]
        transcript = agent.transcript     # list[ConversationTurn]
    """

    def __init__(
        self,
        cam_name: str,
        tasks: list[dict[str, Any]],
        expected_pcts: dict[str, int] | None = None,
        all_tasks: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Args:
            cam_name: The CAM's name (used in prompts).
            tasks: List of task dicts (from IMSFileHandler.parse()) for this CAM.
            expected_pcts: Optional dict of task_id → expected_pct. If not
                           provided, calculated from elapsed time.
            all_tasks: Full task list including milestones (for milestone name lookup).
        """
        self._cam_name = cam_name
        self._tasks = [t for t in tasks if not t.get("is_milestone")]
        self._milestones = [t for t in (all_tasks or tasks) if t.get("is_milestone")]
        self._expected_pcts = expected_pcts or {}
        self._task_index = 0
        self._retry_count = 0
        self._confirm_retry_count = 0
        self._state = InterviewState.GREETING
        self._results: list[TaskResult] = []
        self._transcript: list[ConversationTurn] = []
        # Working state for the current task
        self._current_pct: int | None = None
        self._current_blocker: str = ""
        self._current_risk_flag: bool = False
        self._current_risk_desc: str = ""
        self._current_eac_date: str | None = None
        self._current_eac_uncertain: bool = False
        # Track milestones already asked about — stores the risk answer so behind-schedule
        # tasks reuse the same YES/NO rather than re-asking or auto-flagging True
        self._flagged_milestones: dict[str, bool] = {}
        # Count of consecutive NO answers per milestone — once a milestone has been
        # denied ≥ 2 times in this session, stop asking about it (avoids the "you've
        # asked me this 6 times" UX problem when many tasks share the same milestone).
        self._milestone_no_count: dict[str, int] = {}
        # Last confirmation message text — stored so correction prompts have full context
        self._last_confirmation_text: str = ""
        # Pending one-liner to prepend to the next task intro when the CAM asks a question
        # that ATLAS can't answer mid-interview (e.g. schedule dates, CPM detail).
        self._cam_question_note: str = ""
        logger.info("action=interview_init cam=%s tasks=%d", cam_name, len(self._tasks))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> InterviewState:
        return self._state

    @property
    def results(self) -> list[TaskResult]:
        return list(self._results)

    @property
    def transcript(self) -> list[ConversationTurn]:
        return list(self._transcript)

    def start(self) -> AgentTurn:
        """Generate the opening greeting turn."""
        import random
        n = len(self._tasks)
        first_name = self._cam_name.split()[0]
        item_word = "thing" if n == 1 else "things"
        greetings = [
            f"Hey {first_name}, it's ATLAS — quick schedule check-in. Got {n} {item_word} to run through with you. Free for a few?",
            f"Hey {first_name}! ATLAS here — doing a quick status check. {n} {item_word} on my list. Good time?",
            f"Hey {first_name} — ATLAS scheduler. Just need to run through {n} {item_word} real quick. Got a minute?",
        ]
        text = random.choice(greetings)
        self._state = InterviewState.GREETING
        return self._agent_turn(text, InterviewState.GREETING)

    def process(self, utterance: str) -> AgentTurn:
        """
        Process a CAM utterance and return the next agent turn.

        Args:
            utterance: Raw text from STT or CAM simulator.

        Returns:
            AgentTurn with the agent's response text and new state.
        """
        self._cam_turn(utterance)
        normalised = utterance.strip().lower()

        dispatch = {
            InterviewState.GREETING:            self._handle_greeting,
            InterviewState.TASK_INTRO:          self._handle_task_intro,
            InterviewState.AWAITING_PCT:        self._handle_pct,
            InterviewState.AWAITING_EAC_DATE:   self._handle_eac_date,
            InterviewState.AWAITING_BLOCKER:    self._handle_blocker,
            InterviewState.AWAITING_RISK_FLAG:  self._handle_risk_flag,
            InterviewState.AWAITING_RISK_DESC:  self._handle_risk_desc,
            InterviewState.CONFIRM:             self._handle_confirm,
            InterviewState.CLOSING:             self._handle_closing,
        }
        handler = dispatch.get(self._state)
        if handler is None:
            return self._agent_turn("Thank you, the interview is complete.", self._state)
        return handler(normalised, utterance)

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_greeting(self, norm: str, raw: str) -> AgentTurn:
        # Detect "we already did this" — handle gracefully rather than re-running
        if any(phrase in norm for phrase in _ALREADY_DONE_PHRASES):
            first_name = self._cam_name.split()[0]
            return self._agent_turn(
                f"Oh got it, {first_name} — looks like we may have crossed wires on my end. "
                f"I'll check my notes. If anything changes just shoot me a message!",
                InterviewState.ABORTED,
            )
        # Only abort on unambiguous refusal — "no problem, I'm ready" should proceed
        if _is_negative(norm) and not _is_affirmative(norm):
            return self._agent_turn(
                "No worries — I'll check back later. Have a good one!",
                InterviewState.ABORTED,
            )
        return self._introduce_current_task()

    def _handle_task_intro(self, norm: str, raw: str) -> AgentTurn:
        """Task intro is just a transition state — any response starts the PCT question."""
        return self._ask_pct()

    def _handle_pct(self, norm: str, raw: str) -> AgentTurn:
        task = self._current_task
        expected = self._get_expected_pct()
        classification = _classify_cam_response(
            state="percent",
            question=f"You're showing {task['percent_complete']}% on {_spoken_task_name(task['name'])} — where does it stand now?",
            response=raw,
            task_name=_spoken_task_name(task["name"]),
            expected_pct=expected,
            conversation_history=self._transcript,
        )

        if classification.get("unknown"):
            return self._flag_no_response_and_advance(
                "Got it — I'll flag that task for follow-up and move on."
            )

        pct = classification.get("percent")
        if pct is None:
            self._retry_count += 1
            if self._retry_count >= _MAX_RETRIES:
                return self._flag_no_response_and_advance(
                    "No worries — I'll flag that one for follow-up and keep moving."
                )
            import random
            retries = [
                f"Hmm, didn't catch a number there — what percent would you put {_spoken_task_name(task['name'])} at?",
                f"Sorry, missed the percentage on that one. Where's {_spoken_task_name(task['name'])} at, roughly?",
            ]
            return self._agent_turn(random.choice(retries), InterviewState.AWAITING_PCT)

        self._retry_count = 0
        self._current_pct = pct
        logger.info("action=pct_captured cam=%s task=%s pct=%d expected=%d",
                    self._cam_name, task["task_id"], pct, expected)

        # If the CAM already described the blocker in their answer, capture it
        if classification.get("blocker_mentioned") and classification.get("blocker_text"):
            self._current_blocker = classification["blocker_text"]
            logger.info("action=blocker_auto_captured cam=%s task=%s",
                        self._cam_name, task["task_id"])

        if classification.get("cam_question"):
            self._cam_question_note = _cam_question_ack()

        # For in-progress tasks (1–99%) ask for a projected completion date before
        # continuing to the blocker / risk questions.  0% (not started) and 100%
        # (complete) skip this step — there is no meaningful forecast to collect.
        if 1 <= pct <= 99:
            return self._ask_eac_date()

        # 0% — not started, fall straight through to blocker / risk path below
        if pct < expected - 10:
            milestone_hint = self._nearest_milestone_name()
            if self._current_blocker:
                if self._flagged_milestones.get(milestone_hint) is True:
                    self._current_risk_flag = False
                    return self._finalise_task_and_advance(pct)
                if self._milestone_no_count.get(milestone_hint, 0) >= 2:
                    self._current_risk_flag = False
                    return self._finalise_task_and_advance(pct)
                return self._agent_turn(
                    f"Got it — noted that blocker. Could that put {milestone_hint} at risk?",
                    InterviewState.AWAITING_RISK_FLAG,
                )
            return self._agent_turn(
                f"Got it, {pct}%. What's the main thing holding that up?",
                InterviewState.AWAITING_BLOCKER,
            )

        # On track (and pct is 0 or 100)
        if self._current_blocker:
            milestone_hint = self._nearest_milestone_name()
            if self._flagged_milestones.get(milestone_hint) is True:
                self._current_risk_flag = False
                return self._finalise_task_and_advance(self._current_pct)
            if self._milestone_no_count.get(milestone_hint, 0) >= 2:
                self._current_risk_flag = False
                return self._finalise_task_and_advance(self._current_pct)
            return self._agent_turn(
                f"Got it — noted that blocker. Could that put {milestone_hint} at risk?",
                InterviewState.AWAITING_RISK_FLAG,
            )

        # On track, no blocker (pct 100 falls here most often) — finalise
        return self._finalise_task_and_advance(pct)

    def _ask_eac_date(self) -> AgentTurn:
        """Ask the CAM for their projected completion date for the current task."""
        import random
        task = self._current_task
        pct = self._current_pct or 0
        expected = self._get_expected_pct()
        planned_finish = task.get("finish")
        spoken_name = _spoken_task_name(task["name"])

        if planned_finish:
            if hasattr(planned_finish, "strftime"):
                # Cross-platform: strip leading zeros manually
                planned_str = f"{planned_finish.month}/{planned_finish.day}"
            else:
                planned_str = str(planned_finish)[:10]
        else:
            planned_str = None

        behind = pct < expected - 10

        if behind:
            if planned_str:
                options = [
                    f"Got it, {pct}%. The plan had that done by {planned_str} — when do you think you'll wrap it up?",
                    f"Got it. Planned finish was {planned_str} — what's your forecast now?",
                    f"Got it, {pct}%. Given where you are, when do you see {spoken_name} finishing?",
                ]
            else:
                options = [
                    f"Got it, {pct}%. When do you think you'll have that wrapped up?",
                    f"Got it. What's your best estimate for finishing {spoken_name}?",
                    f"Got it, {pct}%. When do you see that one completing?",
                ]
        else:
            if planned_str:
                options = [
                    f"Got it, {pct}%. Still on track to finish by {planned_str}?",
                    f"Got it. The plan has that done by {planned_str} — still looking good?",
                    f"Good — still expecting to wrap {spoken_name} up by {planned_str}?",
                ]
            else:
                options = [
                    f"Got it, {pct}%. Still on track to hit your planned finish?",
                    f"Got it. Any change to your expected finish date for that one?",
                    f"Good — still looking on track for your planned completion?",
                ]

        text = random.choice(options)
        return self._agent_turn(text, InterviewState.AWAITING_EAC_DATE)

    def _handle_eac_date(self, norm: str, raw: str) -> AgentTurn:
        """Handle CAM's response to the EAC date question, then continue to blocker/risk."""
        task = self._current_task
        planned_finish = task.get("finish")
        planned_str = (
            planned_finish.strftime("%Y-%m-%d")
            if planned_finish and hasattr(planned_finish, "strftime")
            else None
        )

        eac_date, eac_uncertain = _classify_eac_date(
            response=raw,
            planned_finish_iso=planned_str,
            conversation_history=self._transcript,
        )
        self._current_eac_date = eac_date
        self._current_eac_uncertain = eac_uncertain

        if eac_date:
            logger.info("action=eac_date_captured cam=%s task=%s eac=%s",
                        self._cam_name, task["task_id"], eac_date)
        elif eac_uncertain:
            logger.info("action=eac_date_uncertain cam=%s task=%s",
                        self._cam_name, task["task_id"])

        # Now run the blocker / risk decision that _handle_pct() deferred to here
        pct = self._current_pct or 0
        expected = self._get_expected_pct()
        milestone_hint = self._nearest_milestone_name()

        if pct < expected - 10:  # Behind schedule
            if self._current_blocker:
                if self._flagged_milestones.get(milestone_hint) is True:
                    self._current_risk_flag = False
                    return self._finalise_task_and_advance(pct)
                if self._milestone_no_count.get(milestone_hint, 0) >= 2:
                    self._current_risk_flag = False
                    return self._finalise_task_and_advance(pct)
                return self._agent_turn(
                    f"Got it — noted that blocker. Could that put {milestone_hint} at risk?",
                    InterviewState.AWAITING_RISK_FLAG,
                )
            return self._agent_turn(
                "What's the main thing holding that up?",
                InterviewState.AWAITING_BLOCKER,
            )

        # On track percentage-wise
        if self._current_blocker:
            if self._flagged_milestones.get(milestone_hint) is True:
                self._current_risk_flag = False
                return self._finalise_task_and_advance(pct)
            if self._milestone_no_count.get(milestone_hint, 0) >= 2:
                self._current_risk_flag = False
                return self._finalise_task_and_advance(pct)
            return self._agent_turn(
                f"Got it — noted that blocker. Could that put {milestone_hint} at risk?",
                InterviewState.AWAITING_RISK_FLAG,
            )

        # On track, no blocker — finalise
        return self._finalise_task_and_advance(pct)

    def _handle_blocker(self, norm: str, raw: str) -> AgentTurn:
        classification = _classify_cam_response(
            state="blocker",
            question="What's the main thing holding that up?",
            response=raw,
            task_name=_spoken_task_name(self._current_task["name"]),
            expected_pct=self._get_expected_pct(),
            conversation_history=self._transcript,
        )
        self._current_blocker = classification.get("blocker_text") or raw.strip()
        if classification.get("cam_question"):
            self._cam_question_note = _cam_question_ack()
        milestone_hint = self._nearest_milestone_name()
        # Skip the risk question if the milestone is already confirmed AT RISK or denied ≥ 2×.
        # When at risk: default this task's risk_flag=False — milestone risk is already
        # captured from the task that triggered it; auto-flagging every subsequent blocked
        # task True causes a flood of corrections in CONFIRM.
        if self._flagged_milestones.get(milestone_hint) is True:
            self._current_risk_flag = False
            return self._finalise_task_and_advance(self._current_pct)
        if self._milestone_no_count.get(milestone_hint, 0) >= 2:
            self._current_risk_flag = False
            return self._finalise_task_and_advance(self._current_pct)
        return self._agent_turn(
            f"Got it. Could that put {milestone_hint} at risk?",
            InterviewState.AWAITING_RISK_FLAG,
        )

    def _handle_risk_flag(self, norm: str, raw: str) -> AgentTurn:
        milestone = self._nearest_milestone_name()

        classification = _classify_cam_response(
            state="risk_flag",
            question=f"Could that put {milestone} at risk?",
            response=raw,
            task_name=_spoken_task_name(self._current_task["name"]),
            expected_pct=self._get_expected_pct(),
            conversation_history=self._transcript,
        )

        if classification.get("cam_question"):
            self._cam_question_note = _cam_question_ack()

        is_risk = classification["sentiment"] == "affirmative"
        # Record this milestone's risk answer — behind-schedule tasks that hit the same
        # milestone later reuse this answer (True/False) instead of re-asking
        self._flagged_milestones[milestone] = is_risk
        if not is_risk:
            self._milestone_no_count[milestone] = self._milestone_no_count.get(milestone, 0) + 1
            if self._milestone_no_count[milestone] >= 2:
                logger.info(
                    "action=milestone_no_threshold_reached milestone=%s no_count=%d"
                    " — will skip risk question for subsequent tasks",
                    milestone, self._milestone_no_count[milestone],
                )

        if is_risk:
            self._current_risk_flag = True
            return self._agent_turn(
                "What would it take to clear that?",
                InterviewState.AWAITING_RISK_DESC,
            )
        self._current_risk_flag = False
        return self._finalise_task_and_advance(self._current_pct)

    def _handle_risk_desc(self, norm: str, raw: str) -> AgentTurn:
        self._current_risk_desc = raw.strip()
        return self._finalise_task_and_advance(self._current_pct)

    def _handle_confirm(self, norm: str, raw: str) -> AgentTurn:
        # Keyword pre-check: detect correction language that the LLM classifier
        # might misread as "affirmative" (e.g., "Almost — one correction on the
        # risk side" looks partially affirmative but is actually a correction).
        # When these phrases are detected, attempt correction extraction directly
        # rather than trusting the general sentiment classifier.
        _CORRECTION_PHRASES = (
            "correction", "one thing", "almost", "not quite", "close but",
            "except", "actually,", "worth flagging", "need to flag", "missed",
            "also flagged", "not complete", "one more", "before we close",
            "one small", "slight", "slight issue", "minor issue",
        )
        raw_lower = raw.lower()
        correction_language_detected = any(ph in raw_lower for ph in _CORRECTION_PHRASES)

        if correction_language_detected and self._confirm_retry_count < 2:
            applied_corrections = self._extract_and_apply_correction(raw)
            if applied_corrections:
                self._confirm_retry_count += 1
                logger.info(
                    "action=confirm_correction_applied cam=%s retry=%d (keyword-triggered)",
                    self._cam_name, self._confirm_retry_count,
                )
                flags_changed = any(c.get("field") == "risk_flag" for c in applied_corrections)
                return self._re_request_confirmation(flags_changed=flags_changed)
            # Extraction found nothing — correction keyword was likely incidental
            # (e.g. "actually, that's all correct"). Fall through to normal classification.
            logger.debug(
                "action=confirm_keyword_false_positive cam=%s raw=%r",
                self._cam_name, raw[:80],
            )

        classification = _classify_cam_response(
            state="confirm",
            question="Does all that sound right?",
            response=raw,
            task_name="",
            expected_pct=0,
            conversation_history=self._transcript,
        )
        sentiment = classification["sentiment"]

        if sentiment in ("affirmative", "unclear"):
            return self._close_interview()

        # Negative — check for an inline correction (percent value or task ID mentioned)
        has_correction = (
            classification.get("percent") is not None
            or bool(re.search(r"\b[A-Za-z]{2,4}-\d{2}\b", raw))
        )
        if has_correction:
            # Attempt to extract, apply, and re-confirm the correction with full context
            applied_corrections = self._extract_and_apply_correction(raw)
            if applied_corrections and self._confirm_retry_count < 2:
                self._confirm_retry_count += 1
                logger.info("action=confirm_correction_applied cam=%s retry=%d",
                            self._cam_name, self._confirm_retry_count)
                # Detect whether any risk_flag fields actually changed, so the
                # re-confirmation can use the right opener (flag change vs notes update)
                flags_changed = any(
                    c.get("field") == "risk_flag" for c in applied_corrections
                )
                return self._re_request_confirmation(flags_changed=flags_changed)
            # Couldn't extract specific correction or retry cap hit — close gracefully
            logger.info("action=confirm_correction_noted cam=%s correction=%r closing",
                        self._cam_name, raw[:120])
            return self._close_interview_noted()

        if self._confirm_retry_count < 2:
            self._confirm_retry_count += 1
            return self._agent_turn(
                "Sure — which task needs fixing and what should the number be?",
                InterviewState.CONFIRM,
            )

        logger.warning("action=confirm_retry_limit cam=%s closing without confirmed correction",
                       self._cam_name)
        return self._close_interview()

    def _handle_closing(self, norm: str, raw: str) -> AgentTurn:
        return self._agent_turn(
            "Sounds good — talk soon!",
            InterviewState.COMPLETE,
        )

    # ------------------------------------------------------------------
    # Correction helpers
    # ------------------------------------------------------------------

    def _extract_and_apply_correction(self, raw: str) -> list[dict]:
        """Use LLM with full conversation context to extract and apply a CAM correction.

        Returns the list of applied corrections (empty list on failure or no changes).
        Falls back gracefully (returns []) if the LLM call fails — the caller
        will then close the interview gracefully rather than re-confirming.
        """
        task_summary = _format_task_results(self._results, self._tasks)
        history = _format_transcript_for_llm(self._transcript, max_turns=24)
        confirmation = self._last_confirmation_text or "Does all that sound right?"

        try:
            from agent.llm_interface import LLMInterface
            llm = LLMInterface()
            prompt = _CONFIRM_CORRECTION_PROMPT.format(
                history=history,
                task_summary=task_summary,
                confirmation=confirmation,
                response=raw,
            )
            raw_resp = llm.ask(prompt, context="").strip()
            if raw_resp.startswith("```"):
                raw_resp = re.sub(r"^```[a-z]*\n?", "", raw_resp)
                raw_resp = re.sub(r"\n?```$", "", raw_resp)
            raw_resp = raw_resp.strip()
            # Primary parse — try as-is
            try:
                result = json.loads(raw_resp)
            except json.JSONDecodeError:
                # LLM sometimes appends explanation after the JSON object.
                # Extract the outermost {...} block and retry.
                m = re.search(r'\{.*\}', raw_resp, re.DOTALL)
                if not m:
                    raise
                result = json.loads(m.group(0))

            corrections = result.get("corrections", [])
            if not corrections:
                return []

            # Build a lookup from name-prefix (e.g. "AI-07") to numeric task ID
            # so corrections referencing "AI-07" can match result with task_id="62"
            name_prefix_to_id: dict[str, str] = {}
            for t in self._tasks:
                name = t.get("name", "")
                m = re.match(r'^([A-Za-z]{2,4}-\d{2,3})\b', name)
                if m:
                    name_prefix_to_id[m.group(1).upper()] = str(t["task_id"]).upper()

            applied: list[dict] = []
            for correction in corrections:
                raw_id = str(correction.get("task_id", "")).strip()
                # Resolve name-prefix aliases (e.g. "AI-07" → "62")
                task_id = name_prefix_to_id.get(raw_id.upper(), raw_id.upper())
                field = str(correction.get("field", ""))
                new_value = correction.get("new_value")

                for res in self._results:
                    if res.task_id.upper() == task_id:
                        if field == "percent_complete" and isinstance(new_value, (int, float)):
                            old_val = res.percent_complete
                            res.percent_complete = int(new_value)
                            logger.info("action=correction_applied task=%s field=pct %s→%s",
                                        task_id, old_val, int(new_value))
                            applied.append({"task_id": task_id, "field": field})
                        elif field == "risk_flag" and isinstance(new_value, bool):
                            old_val = res.risk_flag
                            res.risk_flag = new_value
                            logger.info("action=correction_applied task=%s field=risk_flag %s→%s",
                                        task_id, old_val, new_value)
                            applied.append({"task_id": task_id, "field": field})
                        elif field == "risk_description" and isinstance(new_value, str):
                            res.risk_description = new_value
                            logger.info("action=correction_applied task=%s field=risk_desc updated", task_id)
                            applied.append({"task_id": task_id, "field": field})
                        elif field == "blocker" and isinstance(new_value, str):
                            res.blocker = new_value
                            logger.info("action=correction_applied task=%s field=blocker updated", task_id)
                            applied.append({"task_id": task_id, "field": field})
                        elif field == "eac_date" and isinstance(new_value, str):
                            res.eac_date = new_value
                            logger.info("action=correction_applied task=%s field=eac_date updated", task_id)
                            applied.append({"task_id": task_id, "field": field})
                        break

            if applied:
                logger.info("action=corrections_total cam=%s applied=%d", self._cam_name, len(applied))
            return applied

        except Exception as exc:
            logger.warning("action=correction_extract_failed cam=%s error=%s", self._cam_name, exc)
            return []

    def _re_request_confirmation(self, flags_changed: bool = True) -> AgentTurn:
        """Re-render the confirmation summary after corrections have been applied.

        Args:
            flags_changed: True if risk_flag fields changed (not just risk_desc/blocker).
                           When False, the opener acknowledges notes were updated rather
                           than implying the flag list itself changed.
        """
        all_risks = [r for r in self._results if r.risk_flag]

        # Build name map: numeric task_id → short task code (e.g. "AI-07"), falling
        # back to spoken name if no code prefix is present.
        def _short_name(task_id: str) -> str:
            for t in self._tasks:
                if str(t["task_id"]) == str(task_id):
                    name = t.get("name", "")
                    m = re.match(r'^([A-Za-z]{2,4}-\d{2,3})\b', name)
                    if m:
                        return m.group(1)   # e.g. "AI-07"
                    return _spoken_task_name(name)
            return str(task_id)

        if flags_changed:
            opener = "Got it — updated."
        else:
            opener = "Got it — I've updated my notes on that."

        parts: list[str] = [opener]
        if all_risks:
            count = len(all_risks)
            if count > 10:
                # Too many to name — use count only
                parts.append(f"I now have {count} tasks flagged as schedule risks.")
            else:
                # List all of them explicitly so the CAM can verify each one
                risk_names = _natural_list([_short_name(r.task_id) for r in all_risks])
                if flags_changed:
                    parts.append(f"I now have {risk_names} flagged as schedule risks.")
                else:
                    parts.append(f"The flagged risks are still {risk_names}.")
        else:
            parts.append("Clean — no risk flags now.")
        parts.append("Does that look right?")

        text = " ".join(parts)
        self._last_confirmation_text = text
        return self._agent_turn(text, InterviewState.CONFIRM)

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    def _introduce_current_task(self, prev_pct: int | None = None) -> AgentTurn:
        if self._task_index >= len(self._tasks):
            return self._close_interview()
        task = self._current_task
        self._reset_task_state()
        last_pct = task["percent_complete"]
        idx = self._task_index
        n = len(self._tasks)

        spoken_name = _spoken_task_name(task["name"])
        if idx == 0:
            opener = f"Alright, let's start with {spoken_name}."
        elif idx == n - 1:
            opener = f"Last one — {spoken_name}."
        else:
            opener = f"Next up, {spoken_name}."

        # Pending acknowledgment of a CAM question takes priority over pct ack
        if self._cam_question_note:
            ack_prefix = self._cam_question_note
            self._cam_question_note = ""
        elif prev_pct is not None:
            ack_prefix = _pct_ack(prev_pct) + " "
        else:
            ack_prefix = ""

        # Vary "You're showing X% on that" so it doesn't feel like a rote template
        import random as _random
        if last_pct == 0:
            pct_phrase = _random.choice([
                "That one's at zero in the schedule — where does it stand?",
                "Schedule's showing zero on that — what's the status?",
                "Zero in the plan — any movement on that?",
                "That one's at zero in the IMS — what's the situation?",
                "Still showing zero — where does it stand?",
            ])
        elif last_pct == 100:
            pct_phrase = _random.choice([
                "You're showing 100% — is that wrapped up?",
                "Schedule shows that one complete — still good?",
                "That's at 100 in the IMS — confirmed done?",
            ])
        else:
            pct_phrase = f"You're showing {last_pct}% — where does it stand now?"

        text = f"{ack_prefix}{opener} {pct_phrase}"
        return self._agent_turn(text, InterviewState.AWAITING_PCT)

    def _ask_pct(self) -> AgentTurn:
        task = self._current_task
        return self._agent_turn(
            f"Where does {_spoken_task_name(task['name'])} stand percentage-wise?",
            InterviewState.AWAITING_PCT,
        )

    def _finalise_task_and_advance(self, pct: int | None) -> AgentTurn:
        result = TaskResult(
            task_id=self._current_task["task_id"],
            cam_name=self._cam_name,
            percent_complete=pct,
            blocker=self._current_blocker,
            risk_flag=self._current_risk_flag,
            risk_description=self._current_risk_desc,
            status="captured",
            eac_date=self._current_eac_date,
            eac_uncertain=self._current_eac_uncertain,
        )
        self._results.append(result)
        logger.info("action=task_captured cam=%s task_id=%s pct=%s risk=%s",
                    self._cam_name, result.task_id, result.percent_complete,
                    result.risk_flag)
        self._task_index += 1
        if self._task_index >= len(self._tasks):
            return self._request_confirmation()
        # Pass prev_pct so _introduce_current_task can prepend a brief natural ack
        return self._introduce_current_task(prev_pct=pct)

    def _flag_no_response_and_advance(self, text: str) -> AgentTurn:
        result = TaskResult(
            task_id=self._current_task["task_id"],
            cam_name=self._cam_name,
            percent_complete=None,
            blocker="",
            risk_flag=False,
            risk_description="",
            status="no_response",
        )
        self._results.append(result)
        logger.info("action=task_no_response cam=%s task_id=%s",
                    self._cam_name, result.task_id)
        self._task_index += 1
        if self._task_index >= len(self._tasks):
            # Last task — still show the confirmation summary so the CAM can
            # review what was captured (rather than jumping straight to close).
            confirm_turn = self._request_confirmation()
            return self._agent_turn(text + " " + confirm_turn.text, confirm_turn.state)
        advance_turn = self._introduce_current_task()
        return self._agent_turn(text + " " + advance_turn.text, advance_turn.state)

    def _request_confirmation(self) -> AgentTurn:
        n = len(self._results)
        all_risks = [r for r in self._results if r.risk_flag]
        no_resp = [r for r in self._results if r.status == "no_response"]

        # Build short names (task code like "AI-07") for listing risks
        def _code_name(task_id: str) -> str:
            for t in self._tasks:
                if str(t["task_id"]) == str(task_id):
                    name = t.get("name", "")
                    m = re.match(r'^([A-Za-z]{2,4}-\d{2,3})\b', name)
                    if m:
                        return m.group(1)
                    return _spoken_task_name(name)
            return str(task_id)

        parts: list[str] = [f"Alright, I think I've got all {n} of your tasks."]
        if all_risks:
            count = len(all_risks)
            if count >= n:
                # Every task is a schedule risk — common shared-blocker scenario
                parts.append(f"All {n} are flagged as schedule risks.")
            elif count > 10:
                # Too many to name individually — use count only
                parts.append(f"I'm flagging {count} tasks as schedule risks.")
            else:
                # List all flagged tasks explicitly so the CAM can verify each one
                risk_names = _natural_list([_code_name(r.task_id) for r in all_risks])
                parts.append(f"I'm flagging {risk_names} as schedule risks.")
        else:
            # No risk flags — call it out so the CAM can push back if they disagree
            # Mention any tasks with active blockers even if not flagged as risks
            blocked = [r for r in self._results if r.blocker and r.status == "captured"]
            if blocked:
                parts.append("No schedule risks flagged — though I've noted a couple of blockers.")
            else:
                parts.append("Clean — no risk flags today.")
        if no_resp:
            parts.append(f"I'll mark {len(no_resp)} item{'s' if len(no_resp) != 1 else ''} for follow-up.")

        parts.append("Does all that sound right?")
        text = " ".join(parts)
        self._last_confirmation_text = text
        return self._agent_turn(text, InterviewState.CONFIRM)

    def _is_material_risk(self, result: TaskResult) -> bool:
        """True only if the task is both risk-flagged AND materially behind schedule (>10 pts gap)."""
        if not result.risk_flag or result.percent_complete is None:
            return False
        task = next((t for t in self._tasks if t["task_id"] == result.task_id), None)
        if task is None:
            return True
        expected = self._expected_pcts.get(result.task_id, _calc_expected_pct(task))
        return result.percent_complete < expected - 15

    def _close_interview(self) -> AgentTurn:
        import random
        first_name = self._cam_name.split()[0]
        closes = [
            f"Perfect — thanks {first_name}, I'll get those in. Have a good one!",
            f"Got it, {first_name} — I'll update the schedule. Appreciate it!",
            f"Great, {first_name} — all set on my end. Talk soon!",
            f"Thanks {first_name}, that's everything I need. Have a good rest of your day!",
        ]
        return self._agent_turn(random.choice(closes), InterviewState.COMPLETE)

    def _close_interview_noted(self) -> AgentTurn:
        """Close gracefully when corrections were logged but not fully reconciled.

        Used when the CAM's dispute couldn't be fully applied (e.g. requesting date
        fields the agent doesn't hold) or when the correction retry limit was reached.
        Acknowledges the feedback rather than claiming 'all set'.
        """
        import random
        first_name = self._cam_name.split()[0]
        closes = [
            f"Noted, {first_name} — I'll flag that for the PM team to follow up. Thanks for the detail!",
            f"Got it, {first_name} — I've logged your feedback for review. The team will come back to you on the specifics.",
            f"Understood, {first_name} — I'll make sure that gets flagged. Appreciate you pushing on it!",
        ]
        return self._agent_turn(random.choice(closes), InterviewState.COMPLETE)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @property
    def _current_task(self) -> dict[str, Any]:
        return self._tasks[self._task_index]

    def _reset_task_state(self) -> None:
        self._current_pct = None
        self._current_blocker = ""
        self._current_risk_flag = False
        self._current_risk_desc = ""
        self._current_eac_date = None
        self._current_eac_uncertain = False
        self._retry_count = 0

    def _get_expected_pct(self) -> int:
        tid = self._current_task["task_id"]
        if tid in self._expected_pcts:
            return self._expected_pcts[tid]
        return _calc_expected_pct(self._current_task)

    def _nearest_milestone_name(self) -> str:
        """Return the most relevant upcoming milestone name for the current task.

        Picks the nearest milestone whose date is AT OR AFTER the current task's
        own finish date.  This prevents the logically incorrect question "Could
        this put Milestone X at risk?" when the task is actually scheduled to
        complete AFTER Milestone X.

        Example: a documentation task finishing 2026-06-10 gets "System Accepted"
        (2026-06-25), not "Network and Security Hardened" (2026-06-03).

        Falls back to the globally-nearest upcoming milestone if no milestone
        falls after the task's finish, or the task has no finish date.

        Strips IMS prefixes ("MILESTONE: ", "MILESTONE - ") and parenthetical
        abbreviations so the name reads naturally in chat.
        """
        from datetime import datetime
        now = datetime.now()

        # Use the current task's finish date as the lower bound so we never
        # ask about a milestone that is already past when this task completes.
        task_finish = self._current_task.get("finish") if self._tasks else None
        lower_bound = task_finish if task_finish and task_finish > now else now

        upcoming = [
            t for t in self._milestones
            if t.get("finish") and t["finish"] >= lower_bound
        ]
        # If no milestones fall on or after the task finish, fall back to
        # any future milestone (edge case: task is already overdue).
        if not upcoming:
            upcoming = [t for t in self._milestones if t.get("finish") and t["finish"] >= now]

        if upcoming:
            nearest = min(upcoming, key=lambda t: t["finish"])
            name = nearest.get("name", "")
            # Strip "MILESTONE: " / "MILESTONE - " IMS prefix
            name = re.sub(r'^MILESTONE[:\s\-]+\s*', '', name, flags=re.IGNORECASE).strip()
            # Shorten "PDR - Preliminary Design Review" → "PDR"
            short = name.split(" - ")[0].split(" – ")[0].strip()
            # Strip trailing parenthetical abbreviations like " (PDR)"
            short = re.sub(r'\s*\([A-Z][A-Za-z0-9& /,\-]+\)\s*$', '', short).strip()
            return short or "the next milestone"
        return "the next milestone"

    def _agent_turn(self, text: str, new_state: InterviewState) -> AgentTurn:
        self._state = new_state
        self._transcript.append(ConversationTurn(speaker="agent", text=text))
        logger.debug("action=agent_turn state=%s text=%r", new_state.value, text[:60])
        return AgentTurn(text=text, state=new_state)

    def _cam_turn(self, text: str) -> None:
        self._transcript.append(ConversationTurn(speaker="cam", text=text))
        logger.debug("action=cam_turn text=%r", text[:60])


# ---------------------------------------------------------------------------
# NLU helpers
# ---------------------------------------------------------------------------

def _extract_percent(text: str) -> int | None:
    """Extract a percent value from a natural-language utterance.

    Prioritises explicit '%' markers so task IDs like 'SE-03' don't get
    mistakenly captured as '3%'.
    """
    # Priority 1: explicit percent sign "60%", "60 %", "60 percent"
    for pat in (
        r"\b(\d{1,3})\s*%",
        r"\b(\d{1,3})\s+percent\b",
    ):
        m = re.search(pat, text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                return val

    # Priority 2: contextual bare number after common phrases
    m = re.search(
        r"\b(?:at|is|are|around|about|roughly|approximately|currently|say|saying|"
        r"maybe|probably|estimate|think|guess)\s+(\d{1,3})\b",
        text,
    )
    if m:
        val = int(m.group(1))
        if 0 <= val <= 100:
            return val

    # Priority 3: word numbers (zero / ten / ... / hundred)
    # Also explicitly handle "hasn't started" / "nothing started" phrases → 0%
    word_map = {
        "three quarters": 75, "three-quarters": 75,
        "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "hundred": 100, "half": 50, "quarter": 25,
        # Explicit "not started" patterns → 0
        "hasn't started": 0, "haven't started": 0, "not started": 0,
        "nothing started": 0, "nothing has started": 0, "hasn't been started": 0,
        "nothing starts on it": 0, "can't start on it": 0, "cannot start on it": 0,
        "no progress": 0, "zero progress": 0, "can't start": 0, "nothing to report": 0,
        "not kicked off": 0, "not been kicked off": 0, "hasn't kicked off": 0,
    }
    for phrase, val in sorted(word_map.items(), key=lambda x: -len(x[0])):
        if phrase in text:
            return val

    # Priority 4: bare integer not preceded by a task-ID pattern (letter(s)-digit)
    # e.g. "75" or "I'd say 60" after the context check above didn't match
    candidates = re.findall(r"(?<![A-Za-z]-)\b(\d{1,3})\b", text)
    for c in candidates:
        val = int(c)
        if 0 <= val <= 100:
            return val
    return None


def _phrase_in(phrase: str, text: str) -> bool:
    """Return True if `phrase` appears as whole words in `text`."""
    return bool(re.search(r"\b" + re.escape(phrase) + r"\b", text))


def _is_affirmative(text: str) -> bool:
    return any(_phrase_in(p, text) for p in _YES_PHRASES)


def _is_negative(text: str) -> bool:
    return any(_phrase_in(p, text) for p in _NO_PHRASES)


def _is_unknown(text: str) -> bool:
    return any(_phrase_in(p, text) for p in _UNKNOWN_PHRASES)


_BLOCKER_KEYWORDS = {
    "waiting on", "waiting for", "blocked", "blocking", "held up", "holding",
    "can't start", "cannot start", "haven't received", "pending", "dependency",
    "depends on", "need the", "needs the", "need to receive",
    "still need", "before i can", "until we get", "until i get",
    # Broader patterns the CAM frequently uses
    "tied to", "contingent on", "gated on", "gated by",
    "once the", "once we get", "once i get", "once i have",
    "can't finalize", "cannot finalize", "can't close", "cannot close",
    "can't proceed", "cannot proceed", "can't progress", "cannot progress",
    "holding off", "on hold", "not going to move",
    "require", "requires", "required before", "need to receive",
    "without the", "without those", "without confirmed",
    "same root cause", "same dependency", "same blocker",
}


def _contains_blocker_mention(text: str) -> bool:
    """Return True if the utterance already describes a blocker."""
    low = text.lower()
    return any(kw in low for kw in _BLOCKER_KEYWORDS)


def _spoken_task_name(raw_name: str) -> str:
    """Strip ID prefixes and parenthetical abbreviations for TTS readability.

    'SE-03 Interface Control Documents (ICDs)' → 'Interface Control Documents'
    'HW-01 Antenna Design' → 'Antenna Design'
    """
    import re as _re
    # Strip leading ID prefix like "SE-03 " or "HW-01 "
    name = _re.sub(r"^[A-Z]{2,4}-\d+\s+", "", raw_name)
    # Strip trailing parenthetical abbreviations like " (ICDs)" or " (PDR)"
    name = _re.sub(r"\s*\([A-Z][A-Za-z0-9& /,-]+\)\s*$", "", name)
    return name.strip() or raw_name


def _natural_list(items: list[str]) -> str:
    """Join a list of items in natural spoken English: 'A', 'A and B', 'A, B, and C'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _pct_ack(pct: int) -> str:
    """Return a brief, varied natural acknowledgment for an on-track percent capture.

    Used to bridge the gap between capturing a task's percent and introducing
    the next task — avoids the abrupt jump that makes the bot feel robotic.
    """
    import random
    if pct == 100:
        options = ["Done —", "Complete —", "Nice, wrapped up —", "Got it, done —"]
    elif pct >= 85:
        options = ["Almost there —", "Nearly done —", "Good progress —", "Solid —"]
    elif pct >= 60:
        options = ["Good —", "Alright —", "Solid —", "Good progress —"]
    elif pct > 0:
        options = ["Got it —", "Okay —", "Copy that —", "Noted —", "Got that —"]
    else:
        # 0% — more variety since many tasks may be at zero
        options = ["Got it —", "Okay —", "Copy that —", "Noted —",
                   "Got that —", "Understood —", "Roger that —", "Copy —"]
    return random.choice(options)


def _cam_question_ack() -> str:
    """Return a brief, natural one-liner acknowledging that the CAM asked a question
    ATLAS can't answer mid-interview (e.g. planned finish dates, CPM detail).

    Used as a prefix on the next task intro so the CAM doesn't feel ignored.
    """
    import random
    options = [
        "Good question — I'll flag that for follow-up. ",
        "I don't have the schedule detail queued up here — I'll note that. ",
        "I'll flag that for the PM to loop back on. ",
        "Noted — I'll make sure that gets followed up on. ",
        "Good point — I'll make a note of that. ",
    ]
    return random.choice(options)


def _calc_expected_pct(task: dict[str, Any]) -> int:
    """Estimate expected percent complete from elapsed time."""
    from datetime import datetime
    start = task.get("start")
    finish = task.get("finish")
    if not start or not finish:
        return 0
    now = datetime.now()
    total = (finish - start).total_seconds()
    if total <= 0:
        return 100
    elapsed = (now - start).total_seconds()
    return max(0, min(100, int(elapsed / total * 100)))


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

def _format_transcript_for_llm(
    transcript: list[ConversationTurn], max_turns: int = 16
) -> str:
    """Format recent transcript turns as a readable conversation string for LLM context."""
    if not transcript:
        return "(no prior conversation)"
    recent = transcript[-max_turns:]
    lines = []
    for turn in recent:
        prefix = "ATLAS:" if turn.speaker == "agent" else "CAM:"
        lines.append(f"{prefix} {turn.text}")
    return "\n".join(lines)


def _format_task_results(results: list[TaskResult], tasks: list[dict]) -> str:
    """Format captured task results as a readable summary for LLM correction prompts."""
    if not results:
        return "(no tasks captured yet)"
    name_map = {t["task_id"]: t["name"] for t in tasks}
    lines = []
    for r in results:
        name = name_map.get(r.task_id, r.task_id)
        risk_str = "RISK FLAGGED" if r.risk_flag else "no risk"
        line = f"  {r.task_id} ({name}): {r.percent_complete}% complete, {risk_str}"
        if r.blocker:
            line += f", blocker: {r.blocker[:80]}"
        if r.eac_date:
            line += f", forecast: {r.eac_date}"
        elif r.eac_uncertain:
            line += ", forecast: uncertain"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM-based classifier — replaces keyword matching for NLU
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
You are the NLU layer for ATLAS, an automated program schedule interview agent.
The agent just asked a question and received this response from a program engineer (CAM).
Extract the key facts and return them as a JSON object — nothing else.

RECENT CONVERSATION (for context):
{history}

CURRENT TURN:
State: {state}
Task being discussed: {task_name}
Expected progress: ~{expected_pct}%
Agent asked: {question}
CAM responded: {response}

Return ONLY a JSON object with these fields:
{{
  "percent": <integer 0-100 — the completion percentage the CAM reported for THIS task, or null if not stated>,
  "blocker_mentioned": <true if the CAM described anything blocking or delaying this task>,
  "blocker_text": <one-sentence summary of the blocker, or "" if none>,
  "sentiment": "affirmative" | "negative" | "unclear" — whether the CAM said yes/no to the question asked,
  "unknown": <true if the CAM said they don't know or can't answer>,
  "key_insight": <one sentence capturing the most important thing the CAM said>,
  "cam_question": <true if the CAM is asking ATLAS a question about schedule, dates, dependencies, data, or anything ATLAS would need to look up — i.e. they expect an answer back>
}}

Important rules:
- For "percent": only capture the percentage the CAM is reporting for the task being asked about.
  Ignore any other task percentages mentioned in passing (e.g. "SE-06 is only at 10%").
  If the CAM says the task hasn't started, nothing has started on it, or no progress yet
  (e.g. "hasn't started", "nothing started", "not started", "zero progress", "nothing started
  on it", "can't start yet"), that means percent=0 — do NOT return null for those cases.
  Only return null if the CAM genuinely cannot give any completion estimate.
- For "sentiment": base this on whether the CAM affirmed or denied what was specifically asked.
  If the CAM gave a nuanced answer that leans yes, use "affirmative".
  If they pushed back or said no, use "negative". If truly ambiguous, "unclear".
  IMPORTANT for state="awaiting_risk_flag": the question asks if something "puts [milestone] at risk."
  If the CAM confirms the task IS a schedule risk — using any phrasing like "is a schedule risk",
  "live schedule risk", "puts the project at risk", "holds up delivery", "blocks the program",
  "will delay", or similar — treat that as AFFIRMATIVE. Do not mark it negative just because
  the CAM names a different milestone or downstream task; they may be describing the same risk
  in their own terms. Mark it negative only if they clearly say the task does NOT create
  schedule risk (e.g. "no", "not a risk", "won't delay anything", "just a sequencing issue").
- For "blocker_mentioned": true if the CAM mentioned anything that is preventing, delaying,
  blocking, or holding up progress — even if phrased indirectly.
- Use the conversation history to understand references to prior context (e.g. "that task"
  or corrections referencing previously discussed items).
- For "cam_question": set true only when the CAM is directly asking ATLAS something that
  requires a schedule-data lookup to answer (e.g. "what's the planned finish date?",
  "who owns SE-04?", "why is that task behind?"). Do NOT set true when the CAM is just
  providing information, expressing uncertainty, or making a statement."""


_CONFIRM_CORRECTION_PROMPT = """\
You are ATLAS, reviewing a CAM's response to a schedule status confirmation.

FULL CONVERSATION (most recent turns):
{history}

TASKS CAPTURED SO FAR:
{task_summary}

CONFIRMATION MESSAGE ATLAS SENT:
{confirmation}

CAM'S RESPONSE:
{response}

The CAM appears to be correcting or disputing something. Analyze what they want changed.
Return ONLY a JSON object:
{{
  "sentiment": "affirmative" | "negative" | "unclear",
  "has_correction": <true if the CAM is correcting specific captured data>,
  "corrections": [
    {{
      "task_id": "<task ID exactly as it appears in the conversation, e.g. AI-07, SE-03, NET-11>",
      "field": "percent_complete" | "risk_flag" | "risk_description" | "blocker" | "eac_date",
      "new_value": <corrected value — integer for percent_complete, boolean for risk_flag, ISO date string for eac_date, string for others>,
      "note": "<one sentence description of what changed>"
    }}
  ]
}}

Rules:
- If the CAM affirms (yes, looks good, correct, that's right), sentiment="affirmative", has_correction=false, corrections=[]
- If the CAM says "no" or "wrong" without specifying what to fix, sentiment="negative", has_correction=false, corrections=[]
- If the CAM corrects a specific task's data, set has_correction=true and list each change
- If the CAM says task X should be flagged INSTEAD of task Y (e.g. "AI-12 isn't a risk, NET-11 is"):
    add TWO corrections — one to unflag the wrong task, one to flag the right task:
    {{"task_id": "AI-12", "field": "risk_flag", "new_value": false, "note": "CAM says AI-12 is not a risk"}},
    {{"task_id": "NET-11", "field": "risk_flag", "new_value": true, "note": "CAM says NET-11 is the real risk"}}
- If the CAM says a task IS a risk that wasn't captured: add one correction with risk_flag=true for that task
- If the CAM says a task is NOT a risk that was captured: add one correction with risk_flag=false for that task
- Only include corrections for tasks actually mentioned by the CAM in their response
- Use the exact task ID format from the conversation (e.g. "AI-07", "NET-11" — not "AI7", "ai-07", or bare numbers)
- Task IDs in this program use the format: 2-4 letters, hyphen, 2-3 digits (e.g. AI-07, NET-11, SE-03, DOC-08)
- Do not invent corrections — only extract what the CAM explicitly stated"""


_EAC_DATE_PROMPT = """\
You are the NLU layer for ATLAS, an automated program schedule interview agent.
The agent just asked a CAM (Control Account Manager) when they expect to finish a task.
Extract the projected completion date from their response and return a JSON object.

Today's date: {today}
Planned (baseline) finish date for this task: {planned_finish}

RECENT CONVERSATION:
{history}

CAM'S RESPONSE:
{response}

Return ONLY a JSON object:
{{
  "eac_date": "<ISO date YYYY-MM-DD, or null>",
  "eac_uncertain": <true if the CAM cannot give any estimate>
}}

Rules:
- If the CAM gives an explicit date (e.g. "May 15th", "end of June", "around the 20th"),
  convert it to ISO format YYYY-MM-DD relative to today ({today}).
- If the CAM says "end of [month]", use the last calendar day of that month.
- If the CAM says "next week" or "in two weeks", count from today.
- If the CAM says they are on track, on schedule, or confirms the planned date is still good,
  return the planned finish as the eac_date: "{planned_finish}".
- If the CAM says they don't know, aren't sure, can't say, or need to check, set
  eac_uncertain=true and eac_date=null.
- If the planned finish is null/unknown and the CAM says "on track", return eac_date=null, eac_uncertain=false.
- Never invent a date the CAM did not describe — if truly unclear, set eac_uncertain=true."""


def _classify_eac_date(
    response: str,
    planned_finish_iso: str | None,
    conversation_history: list | None = None,
) -> tuple[str | None, bool]:
    """Use an LLM to extract a projected completion date from a CAM utterance.

    Returns:
        (eac_date, eac_uncertain)
        eac_date:     ISO string "YYYY-MM-DD" or None
        eac_uncertain: True when the CAM said they don't know
    """
    try:
        from agent.llm_interface import LLMInterface
        llm = LLMInterface()
        today_str = datetime.now().strftime("%Y-%m-%d")
        history_str = _format_transcript_for_llm(conversation_history or [], max_turns=8)
        prompt = _EAC_DATE_PROMPT.format(
            today=today_str,
            planned_finish=planned_finish_iso or "unknown",
            history=history_str,
            response=response,
        )
        raw = llm.ask(prompt, context="").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw.strip())
        eac_date = result.get("eac_date") or None
        eac_uncertain = bool(result.get("eac_uncertain", False))
        # Validate ISO format if a date was returned
        if eac_date:
            datetime.strptime(eac_date, "%Y-%m-%d")
        logger.debug("action=eac_date_classify eac_date=%s uncertain=%s", eac_date, eac_uncertain)
        return eac_date, eac_uncertain
    except Exception as exc:
        logger.warning("action=eac_date_classify_failed error=%s — defaulting uncertain", exc)
        # Safe fallback: treat as uncertain so SRA uses linear estimate
        return None, True


def _classify_cam_response(
    state: str,
    question: str,
    response: str,
    task_name: str,
    expected_pct: int,
    conversation_history: list[ConversationTurn] | None = None,
) -> dict[str, Any]:
    """Use an LLM to classify a CAM's natural-language response.

    Returns a dict with keys: percent, blocker_mentioned, blocker_text,
    sentiment, unknown, key_insight.
    Falls back to safe defaults if the LLM call fails.

    Args:
        conversation_history: Full transcript so far. Passed to the LLM so it
            can understand references to prior context and corrections.
    """
    try:
        from agent.llm_interface import LLMInterface
        llm = LLMInterface()
        history_str = _format_transcript_for_llm(conversation_history or [], max_turns=12)
        prompt = _CLASSIFY_PROMPT.format(
            history=history_str,
            state=state,
            task_name=task_name or "(not specified)",
            expected_pct=expected_pct,
            question=question,
            response=response,
        )
        raw = llm.ask(prompt, context="").strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw)
        logger.debug("action=classify state=%s percent=%s blocker=%s sentiment=%s",
                     state, result.get("percent"), result.get("blocker_mentioned"),
                     result.get("sentiment"))
        return result
    except Exception as exc:
        logger.warning("action=classify_failed state=%s error=%s — falling back to regex", state, exc)
        # Graceful fallback: use the old keyword-based helpers
        pct = _extract_percent(response.lower())
        blocker = _contains_blocker_mention(response)
        sentiment = (
            "affirmative" if _is_affirmative(response.lower())
            else "negative" if _is_negative(response.lower())
            else "unclear"
        )
        return {
            "percent": pct,
            "blocker_mentioned": blocker,
            "blocker_text": response.strip() if blocker else "",
            "sentiment": sentiment,
            "unknown": _is_unknown(response.lower()),
            "key_insight": "",
            "cam_question": False,
        }
