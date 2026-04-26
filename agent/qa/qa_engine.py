"""
Q&A engine — answers natural language questions about the IMS schedule.

Flow:
  1. Detect intent from the question
  2. Build a focused context slice from the latest dashboard state
  3. Call LLM with grounding instructions (no hallucination)
  4. Return answer with source citation (which cycle the data is from)

All answers are grounded in the current dashboard state.  The engine
never fabricates task names, dates, or numeric values.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Queries that can be answered directly from state without an LLM call
_DIRECT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"schedule health|overall health|status", re.I), "health"),
    (re.compile(r"top risks?|biggest risks?", re.I), "top_risks"),
    (re.compile(r"recommended actions?|what should i do|focus.*this week|this week.*focus", re.I), "recommended_actions"),
    (re.compile(r"critical path tasks?", re.I), "critical_path"),
]


@dataclass
class QAResponse:
    answer: str
    source_cycle: str = ""
    intent: list[str] = field(default_factory=list)
    direct: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "source_cycle": self.source_cycle,
            "intent": self.intent,
            "direct": self.direct,
        }


class QAEngine:
    """
    Answers PM questions about the current IMS schedule state.

    Simple questions (health, top risks, critical path) are answered
    directly from the state without an LLM call.  Complex questions
    (why is X behind, what changed, what should I focus on) route
    through the LLM with the relevant context slice.
    """

    def ask(self, question: str) -> QAResponse:
        """
        Answer a natural language question about the schedule.

        Args:
            question: The PM's question in plain English.

        Returns:
            QAResponse with the answer and source citation.
        """
        from agent.qa.context_builder import build_context, detect_intent, load_state
        from agent.llm_interface import LLMInterface

        state = load_state()
        if not state:
            return QAResponse(
                answer="No schedule data is available yet. Run a cycle first.",
                source_cycle="",
            )

        cycle_id = state.get("cycle_id", "unknown")
        intents = detect_intent(question)

        # Try direct answer first (no LLM call needed)
        direct_answer = self._try_direct(question, state)
        if direct_answer:
            logger.info("action=qa_direct question=%r", question[:80])
            from agent.metrics import increment
            increment("qa_queries_total")
            increment("qa_queries_direct")
            return QAResponse(
                answer=direct_answer,
                source_cycle=cycle_id,
                intent=intents,
                direct=True,
            )

        # Build context and call LLM with tool-use support
        context = build_context(question)
        llm = LLMInterface()

        grounded_question = (
            f"{question}\n\n"
            f"Answer using the schedule data provided above AND any IMS schedule tools "
            f"available to you. Use tools to look up specific task details, float values, "
            f"dependencies, or CAM workloads that are not already in the context. "
            f"Cite specific task IDs, CAM names, dates, and probabilities. "
            f"If the data does not contain enough information to answer, say so explicitly."
        )

        from agent.qa.ims_tools import TOOL_SCHEMAS
        logger.info("action=qa_llm question=%r intents=%s tools=%d", question[:80], intents, len(TOOL_SCHEMAS))
        answer = llm.ask_with_tools(grounded_question, context, TOOL_SCHEMAS)

        from agent.metrics import increment
        increment("qa_queries_total")
        increment("qa_queries_llm")

        return QAResponse(
            answer=answer,
            source_cycle=cycle_id,
            intent=intents,
            direct=False,
        )

    # ------------------------------------------------------------------
    # Direct answers (no LLM)
    # ------------------------------------------------------------------

    def _try_direct(self, question: str, state: dict) -> str | None:
        """Return a direct answer if the question maps to a known state field."""
        for pattern, field_key in _DIRECT_PATTERNS:
            if pattern.search(question):
                return self._format_direct(field_key, state)
        return None

    def _format_direct(self, field_key: str, state: dict) -> str | None:
        health = state.get("schedule_health", "UNKNOWN")
        cycle_id = state.get("cycle_id", "")

        if field_key == "health":
            narrative = state.get("narrative", "")
            first_para = narrative.split("\n\n")[0] if narrative else ""
            return (
                f"Schedule health is **{health}** (cycle {cycle_id}).\n\n"
                + (first_para if first_para else "")
            )

        if field_key == "top_risks":
            risks = state.get("top_risks", "")
            if not risks:
                return "No risks recorded in the current cycle."
            return f"**Top Risks** (cycle {cycle_id}):\n\n{risks}"

        if field_key == "recommended_actions":
            actions = state.get("recommended_actions", "")
            if not actions:
                return "No recommended actions recorded in the current cycle."
            return f"**Recommended Actions** (cycle {cycle_id}):\n\n{actions}"

        if field_key == "critical_path":
            cp_ids = state.get("critical_path_task_ids", [])
            if not cp_ids:
                return "No critical path data available."
            return (
                f"**Critical Path** — {len(cp_ids)} tasks (cycle {cycle_id}):\n\n"
                + ", ".join(str(i) for i in cp_ids)
            )

        return None
