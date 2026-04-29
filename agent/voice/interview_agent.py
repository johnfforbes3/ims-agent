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
        # Track milestones already flagged — don't ask the same risk question twice
        self._flagged_milestones: set[str] = set()
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
            InterviewState.GREETING:           self._handle_greeting,
            InterviewState.TASK_INTRO:         self._handle_task_intro,
            InterviewState.AWAITING_PCT:       self._handle_pct,
            InterviewState.AWAITING_BLOCKER:   self._handle_blocker,
            InterviewState.AWAITING_RISK_FLAG: self._handle_risk_flag,
            InterviewState.AWAITING_RISK_DESC: self._handle_risk_desc,
            InterviewState.CONFIRM:            self._handle_confirm,
            InterviewState.CLOSING:            self._handle_closing,
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

        if pct < expected - 10:  # Meaningfully behind schedule
            milestone_hint = self._nearest_milestone_name()
            if self._current_blocker:
                # Blocker already captured — go straight to risk question (or skip if seen)
                if milestone_hint in self._flagged_milestones:
                    self._current_risk_flag = True
                    return self._finalise_task_and_advance(pct)
                return self._agent_turn(
                    f"Got it, {pct}%. Could that put {milestone_hint} at risk?",
                    InterviewState.AWAITING_RISK_FLAG,
                )
            return self._agent_turn(
                f"Got it, {pct}%. What's the main thing holding that up?",
                InterviewState.AWAITING_BLOCKER,
            )
        # On track — finalise without asking follow-up
        return self._finalise_task_and_advance(pct)

    def _handle_blocker(self, norm: str, raw: str) -> AgentTurn:
        classification = _classify_cam_response(
            state="blocker",
            question="What's the main thing holding that up?",
            response=raw,
            task_name=_spoken_task_name(self._current_task["name"]),
            expected_pct=self._get_expected_pct(),
        )
        self._current_blocker = classification.get("blocker_text") or raw.strip()
        milestone_hint = self._nearest_milestone_name()
        if milestone_hint in self._flagged_milestones:
            self._current_risk_flag = True
            return self._finalise_task_and_advance(self._current_pct)
        return self._agent_turn(
            f"Got it. Could that put {milestone_hint} at risk?",
            InterviewState.AWAITING_RISK_FLAG,
        )

    def _handle_risk_flag(self, norm: str, raw: str) -> AgentTurn:
        # Always mark this milestone as seen — never ask the same risk question twice
        milestone = self._nearest_milestone_name()
        self._flagged_milestones.add(milestone)

        classification = _classify_cam_response(
            state="risk_flag",
            question=f"Could that put {milestone} at risk?",
            response=raw,
            task_name=_spoken_task_name(self._current_task["name"]),
            expected_pct=self._get_expected_pct(),
        )

        if classification["sentiment"] == "affirmative":
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
        classification = _classify_cam_response(
            state="confirm",
            question="Does all that sound right?",
            response=raw,
            task_name="",
            expected_pct=0,
        )
        sentiment = classification["sentiment"]

        if sentiment in ("affirmative", "unclear"):
            return self._close_interview()

        # Negative — check for an inline correction
        has_correction = (
            classification.get("percent") is not None
            or bool(re.search(r"\b[A-Za-z]{2}-\d{2}\b", raw))
        )
        if has_correction:
            logger.info("action=confirm_correction_noted cam=%s correction=%r closing",
                        self._cam_name, raw[:120])
            return self._close_interview()

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

        # Prepend a brief natural ack when transitioning from a completed task
        ack_prefix = ""
        if prev_pct is not None:
            ack_prefix = _pct_ack(prev_pct) + " "

        text = f"{ack_prefix}{opener} You're showing {last_pct}% on that — where does it stand now?"
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
            full_text = text + " " + self._close_interview().text
            return self._agent_turn(full_text, InterviewState.COMPLETE)
        advance_turn = self._introduce_current_task()
        return self._agent_turn(text + " " + advance_turn.text, advance_turn.state)

    def _request_confirmation(self) -> AgentTurn:
        n = len(self._results)
        all_risks = [r for r in self._results if r.risk_flag]
        # Only name tasks that are materially behind schedule (> 10 pts gap)
        material_risks = [r for r in all_risks if self._is_material_risk(r)]
        no_resp = [r for r in self._results if r.status == "no_response"]

        task_name_map = {t["task_id"]: _spoken_task_name(t["name"]) for t in self._tasks}

        parts: list[str] = [f"Alright, I think I've got all {n} of your tasks."]
        if material_risks:
            risk_names = _natural_list([task_name_map.get(r.task_id, r.task_id) for r in material_risks[:2]])
            parts.append(f"I'm flagging {risk_names} as a schedule risk.")
        elif all_risks:
            count = len(all_risks)
            parts.append(f"I'm noting {count} schedule risk{'s' if count > 1 else ''} for your review.")
        if no_resp:
            parts.append(f"I'll mark {len(no_resp)} item{'s' if len(no_resp) != 1 else ''} for follow-up.")

        parts.append("Does all that sound right?")
        return self._agent_turn(" ".join(parts), InterviewState.CONFIRM)

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
        self._retry_count = 0

    def _get_expected_pct(self) -> int:
        tid = self._current_task["task_id"]
        if tid in self._expected_pcts:
            return self._expected_pcts[tid]
        return _calc_expected_pct(self._current_task)

    def _nearest_milestone_name(self) -> str:
        """Return the next upcoming milestone name, or a generic fallback."""
        from datetime import datetime
        now = datetime.now()
        upcoming = [
            t for t in self._milestones
            if t.get("finish") and t["finish"] >= now
        ]
        if upcoming:
            nearest = min(upcoming, key=lambda t: t["finish"])
            name = nearest.get("name", "")
            # Shorten "PDR - Preliminary Design Review" → "PDR"
            short = name.split(" - ")[0].split(" – ")[0].strip()
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
    word_map = {
        "three quarters": 75, "three-quarters": 75,
        "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "hundred": 100, "half": 50, "quarter": 25,
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
        options = ["Done —", "Complete —", "Nice, wrapped up —"]
    elif pct >= 85:
        options = ["Almost there —", "Nearly done —", "Good progress —"]
    elif pct >= 60:
        options = ["Good —", "Alright —", "Solid —"]
    else:
        options = ["Got it —", "Okay —", "Copy that —"]
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
# LLM-based classifier — replaces keyword matching for NLU
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
You are the NLU layer for an automated program schedule interview agent.
The agent just asked a question and received this response from a program engineer (CAM).
Extract the key facts and return them as a JSON object — nothing else.

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
  "key_insight": <one sentence capturing the most important thing the CAM said>
}}

Important rules:
- For "percent": only capture the percentage the CAM is reporting for the task being asked about.
  Ignore any other task percentages mentioned in passing (e.g. "SE-06 is only at 10%").
- For "sentiment": base this on whether the CAM affirmed or denied what was specifically asked.
  If the CAM gave a nuanced answer that leans yes, use "affirmative".
  If they pushed back or said no, use "negative". If truly ambiguous, "unclear".
- For "blocker_mentioned": true if the CAM mentioned anything that is preventing, delaying,
  blocking, or holding up progress — even if phrased indirectly."""


def _classify_cam_response(
    state: str,
    question: str,
    response: str,
    task_name: str,
    expected_pct: int,
) -> dict[str, Any]:
    """Use an LLM to classify a CAM's natural-language response.

    Returns a dict with keys: percent, blocker_mentioned, blocker_text,
    sentiment, unknown, key_insight.
    Falls back to safe defaults if the LLM call fails.
    """
    try:
        from agent.llm_interface import LLMInterface
        llm = LLMInterface()
        prompt = _CLASSIFY_PROMPT.format(
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
        }
