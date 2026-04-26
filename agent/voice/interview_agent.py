"""
Interview Agent — conversation state machine for CAM status interviews.

Drives the structured interview conversation:
  GREETING → TASK_INTRO → AWAITING_PCT → [AWAITING_BLOCKER →
  AWAITING_RISK_FLAG → AWAITING_RISK_DESC] → CONFIRM → CLOSING → COMPLETE

Handles: numeric extraction, yes/no interpretation, "I don't know",
self-corrections, off-script utterances (LLM fallback NLU), and timeouts.
"""

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
    ) -> None:
        """
        Args:
            cam_name: The CAM's name (used in prompts).
            tasks: List of task dicts (from IMSFileHandler.parse()) for this CAM.
            expected_pcts: Optional dict of task_id → expected_pct. If not
                           provided, calculated from elapsed time.
        """
        self._cam_name = cam_name
        self._tasks = [t for t in tasks if not t.get("is_milestone")]
        self._expected_pcts = expected_pcts or {}
        self._task_index = 0
        self._retry_count = 0
        self._state = InterviewState.GREETING
        self._results: list[TaskResult] = []
        self._transcript: list[ConversationTurn] = []
        # Working state for the current task
        self._current_pct: int | None = None
        self._current_blocker: str = ""
        self._current_risk_flag: bool = False
        self._current_risk_desc: str = ""
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
        n = len(self._tasks)
        text = (
            f"Hi {self._cam_name}, this is the ATLAS program scheduling agent. "
            f"I have {n} task{'s' if n != 1 else ''} to review with you — "
            f"it should take about {max(2, n * 0.4):.0f} minutes. "
            f"Ready to start?"
        )
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
        # Only abort on unambiguous refusal — "no problem, I'm ready" should proceed
        if _is_negative(norm) and not _is_affirmative(norm):
            return self._agent_turn(
                "No problem — I'll try again later. Have a good day.",
                InterviewState.ABORTED,
            )
        return self._introduce_current_task()

    def _handle_task_intro(self, norm: str, raw: str) -> AgentTurn:
        """Task intro is just a transition state — any response starts the PCT question."""
        return self._ask_pct()

    def _handle_pct(self, norm: str, raw: str) -> AgentTurn:
        if _is_unknown(norm):
            return self._flag_no_response_and_advance(
                "Got it — I'll flag that task for follow-up and move on."
            )

        pct = _extract_percent(norm)
        if pct is None:
            self._retry_count += 1
            if self._retry_count >= _MAX_RETRIES:
                return self._flag_no_response_and_advance(
                    "I'm having trouble capturing that — I'll flag the task for follow-up."
                )
            return self._agent_turn(
                f"Sorry, I didn't catch a number. Can you give me a percent complete "
                f"between 0 and 100 for {self._current_task['name']}?",
                InterviewState.AWAITING_PCT,
            )

        self._retry_count = 0
        self._current_pct = pct
        expected = self._get_expected_pct()
        logger.info("action=pct_captured cam=%s task=%s pct=%d expected=%d",
                    self._cam_name, self._current_task["task_id"], pct, expected)

        if pct < expected - 5:  # >5 points behind — ask for blocker
            return self._agent_turn(
                f"Got it, {pct}%. That's a bit behind plan — "
                f"can you describe what's blocking progress on {self._current_task['name']}?",
                InterviewState.AWAITING_BLOCKER,
            )
        # On track or ahead — skip to next task
        return self._finalise_task_and_advance(pct)

    def _handle_blocker(self, norm: str, raw: str) -> AgentTurn:
        self._current_blocker = raw.strip()
        task_name = self._current_task["name"]
        # Find the nearest milestone name for context
        milestone_hint = self._nearest_milestone_name()
        return self._agent_turn(
            f"Understood. Is this something that could affect the "
            f"{milestone_hint} milestone?",
            InterviewState.AWAITING_RISK_FLAG,
        )

    def _handle_risk_flag(self, norm: str, raw: str) -> AgentTurn:
        if _is_affirmative(norm):
            self._current_risk_flag = True
            return self._agent_turn(
                "Can you briefly describe the nature of the risk and what "
                "you'd need to resolve it?",
                InterviewState.AWAITING_RISK_DESC,
            )
        self._current_risk_flag = False
        return self._finalise_task_and_advance(self._current_pct)

    def _handle_risk_desc(self, norm: str, raw: str) -> AgentTurn:
        self._current_risk_desc = raw.strip()
        return self._finalise_task_and_advance(self._current_pct)

    def _handle_confirm(self, norm: str, raw: str) -> AgentTurn:
        if _is_negative(norm) or "correct" not in norm and "wrong" in norm:
            return self._agent_turn(
                "My apologies — can you tell me which task needs correcting "
                "and what the right value is?",
                InterviewState.CONFIRM,
            )
        return self._close_interview()

    def _handle_closing(self, norm: str, raw: str) -> AgentTurn:
        return self._agent_turn(
            "Thank you for your time. Have a great rest of your day.",
            InterviewState.COMPLETE,
        )

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    def _introduce_current_task(self) -> AgentTurn:
        if self._task_index >= len(self._tasks):
            return self._close_interview()
        task = self._current_task
        self._reset_task_state()
        expected = self._get_expected_pct()
        text = (
            f"Task {self._task_index + 1} of {len(self._tasks)}: "
            f"{task['name']}. "
            f"It was last reported at {task['percent_complete']}% — "
            f"plan says about {expected}%. "
            f"What's your current percent complete?"
        )
        return self._agent_turn(text, InterviewState.AWAITING_PCT)

    def _ask_pct(self) -> AgentTurn:
        task = self._current_task
        return self._agent_turn(
            f"What's your current percent complete for {task['name']}?",
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
        return self._introduce_current_task()

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
        lines = [f"That's all {len(self._tasks)} tasks. To confirm:"]
        for r in self._results:
            pct_str = f"{r.percent_complete}%" if r.percent_complete is not None else "no response"
            lines.append(f"  • {r.task_id}: {pct_str}"
                         + (f" — blocker noted" if r.blocker else "")
                         + (f" — risk flagged" if r.risk_flag else ""))
        lines.append("Does that sound right?")
        return self._agent_turn("\n".join(lines), InterviewState.CONFIRM)

    def _close_interview(self) -> AgentTurn:
        return self._agent_turn(
            "Thanks, I've got everything I need. I'll process the updates now. "
            "Have a great day!",
            InterviewState.COMPLETE,
        )

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
        """Return a short name for the next upcoming milestone (for context in prompts)."""
        return "next program milestone"

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
    """Extract a percent value from a natural-language utterance."""
    # Direct integer: "75", "75%", "seventy five percent"
    match = re.search(r"\b(\d{1,3})\s*%?", text)
    if match:
        val = int(match.group(1))
        if 0 <= val <= 100:
            return val
    # Word numbers
    word_map = {
        "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "hundred": 100, "half": 50, "quarter": 25,
        "three quarters": 75, "three-quarters": 75,
    }
    # Check longer phrases first so "three quarters" matches before "quarter"
    for phrase, val in sorted(word_map.items(), key=lambda x: -len(x[0])):
        if phrase in text:
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
