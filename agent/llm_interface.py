"""
LLM interface — single entry point for all Anthropic SDK calls.

All Claude API usage in the IMS Agent goes through this module.
Nothing else imports anthropic directly.
"""

import logging
import os
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

_SYSTEM_PROMPT = """You are an expert program management analyst specializing in defense program \
Integrated Master Schedule (IMS) analysis. You help program managers understand schedule health, \
identify risks, and prioritize actions.

Your responses must be grounded exclusively in the schedule data, SRA results, and CAM inputs \
provided in the user message. Do not invent task names, dates, durations, or numeric values \
that are not present in the data. If you cannot answer a question from the provided data, \
say so explicitly rather than guessing.

Be concise, specific, and actionable. Your audience is a program manager who needs to make \
decisions quickly."""


class LLMInterface:
    """Wraps the Anthropic SDK for all IMS Agent LLM calls."""

    def __init__(self) -> None:
        """Initialize the Anthropic client from the environment API key."""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY is not set in the environment.")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = _MODEL
        logger.info("action=llm_init model=%s", self._model)

    def synthesize(
        self,
        tasks: list[dict[str, Any]],
        cp_result: dict[str, Any],
        sra_result: list[dict[str, Any]],
        cam_inputs: list[dict[str, Any]],
    ) -> dict[str, str]:
        """
        Synthesize schedule intelligence from parsed data.

        Args:
            tasks: Full parsed task list from the updated schedule.
            cp_result: Critical path analysis result dict.
            sra_result: List of SRA results per milestone.
            cam_inputs: List of CAM status inputs.

        Returns:
            Dict with keys: narrative, top_risks, recommended_actions, schedule_health.
        """
        prompt = _build_synthesis_prompt(tasks, cp_result, sra_result, cam_inputs)
        logger.info("action=llm_call type=synthesis model=%s", self._model)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        logger.info("action=llm_response type=synthesis tokens=%d", response.usage.output_tokens)

        return _parse_synthesis_response(raw)

    def ask(self, question: str, context: str) -> str:
        """
        Answer a free-form question grounded in the provided schedule context.

        Args:
            question: The PM's natural language question.
            context: Serialized schedule context to ground the answer.

        Returns:
            The model's answer as a string.
        """
        logger.info("action=llm_call type=qa model=%s", self._model)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Schedule context:\n{context}\n\nQuestion: {question}",
                }
            ],
        )
        raw = response.content[0].text
        logger.info("action=llm_response type=qa tokens=%d", response.usage.output_tokens)
        return raw

    def ask_with_tools(
        self,
        question: str,
        context: str,
        tools: list[dict],
        max_rounds: int = 5,
    ) -> str:
        """
        Answer a question using Anthropic tool_use (function calling).

        The model may call IMS schedule tools to query live data (float,
        dependencies, task details).  Executes the agentic loop up to
        max_rounds times before returning the final text answer.

        Args:
            question: The PM's natural language question (with grounding instructions).
            context: Serialized schedule context from the dashboard state.
            tools: List of Anthropic tool_use JSON schemas.
            max_rounds: Maximum number of tool-call rounds before giving up.

        Returns:
            The model's final text answer as a string.
        """
        from agent.qa.ims_tools import call_tool

        messages: list[dict] = [
            {
                "role": "user",
                "content": f"Schedule context:\n{context}\n\nQuestion: {question}",
            }
        ]

        logger.info("action=llm_call type=qa_tools model=%s", self._model)

        for round_num in range(max_rounds):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                logger.info(
                    "action=llm_response type=qa_tools rounds=%d tokens=%d",
                    round_num + 1,
                    response.usage.output_tokens,
                )
                return "\n".join(text_parts)

            if response.stop_reason != "tool_use":
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                logger.warning(
                    "action=qa_tools_unexpected_stop stop_reason=%s", response.stop_reason
                )
                return "\n".join(text_parts) if text_parts else "Unable to answer the question."

            # Execute all tool calls in this round
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info("action=tool_dispatch name=%s", block.name)
                    result = call_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            # Append assistant turn and tool results for the next round
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        logger.warning("action=qa_tools_max_rounds rounds=%d", max_rounds)
        return "Unable to complete the analysis within the allowed number of steps."


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_synthesis_prompt(
    tasks: list[dict[str, Any]],
    cp_result: dict[str, Any],
    sra_result: list[dict[str, Any]],
    cam_inputs: list[dict[str, Any]],
) -> str:
    """Build the synthesis prompt from structured data."""
    behind = [
        t for t in tasks
        if t.get("percent_complete", 0) < _expected_pct(t)
    ]

    blockers = [c for c in cam_inputs if c.get("blocker")]
    risks_flagged = [c for c in cam_inputs if c.get("risk_flag")]

    cp_names = [t["name"] for t in tasks if t["task_id"] in cp_result.get("critical_path", [])]

    high_risk_milestones = [
        r for r in sra_result
        if r.get("risk_level") == "HIGH"
    ]

    lines = [
        "=== SCHEDULE DATA FOR SYNTHESIS ===",
        "",
        f"Total tasks: {len(tasks)}",
        f"Tasks behind schedule: {len(behind)}",
        f"CAMs with blockers reported: {len(blockers)}",
        f"CAMs with risks flagged: {len(risks_flagged)}",
        "",
        "--- CRITICAL PATH ---",
        f"Tasks on critical path: {len(cp_names)}",
    ]
    for name in cp_names[:10]:
        lines.append(f"  - {name}")
    if len(cp_names) > 10:
        lines.append(f"  ... and {len(cp_names) - 10} more")

    lines += [
        "",
        "--- HIGH-RISK MILESTONES (from SRA) ---",
    ]
    for m in high_risk_milestones[:5]:
        lines.append(
            f"  - {m['milestone_name']}: baseline {m.get('baseline_date', 'N/A')}, "
            f"P50={m.get('p50_date', 'N/A')}, P80={m.get('p80_date', 'N/A')}, "
            f"P95={m.get('p95_date', 'N/A')}, "
            f"prob_on_time={m.get('prob_on_baseline', 0):.0%}"
        )

    lines += [
        "",
        "--- CAM-REPORTED BLOCKERS ---",
    ]
    for b in blockers[:5]:
        lines.append(f"  - {b['cam_name']} / Task {b['task_id']}: {b['blocker']}")

    lines += [
        "",
        "--- CAM-FLAGGED RISKS ---",
    ]
    for r in risks_flagged[:5]:
        lines.append(f"  - {r['cam_name']} / Task {r['task_id']}: {r.get('risk_description', '')}")

    lines += [
        "",
        "--- TASKS BEHIND SCHEDULE ---",
    ]
    for t in behind[:10]:
        exp = _expected_pct(t)
        lines.append(
            f"  - [{t['cam']}] {t['name']}: actual {t['percent_complete']}% vs "
            f"expected ~{exp}%"
        )

    lines += [
        "",
        "=== INSTRUCTIONS ===",
        "Based ONLY on the data above, provide:",
        "1. SCHEDULE_HEALTH: one word (GREEN / YELLOW / RED) with a one-sentence rationale",
        "2. NARRATIVE: 2-3 paragraph executive summary of schedule health",
        "3. TOP_RISKS: numbered list of top 5 risks (cite specific tasks/milestones/CAMs)",
        "4. RECOMMENDED_ACTIONS: numbered list of 3-5 specific actions for the PM this week",
        "",
        "Use exactly these section headers.",
    ]

    return "\n".join(lines)


def _parse_synthesis_response(raw: str) -> dict[str, str]:
    """
    Extract structured sections from the LLM synthesis response.

    Handles both plain headers (SCHEDULE_HEALTH: RED) and markdown-prefixed
    headers (## SCHEDULE_HEALTH: RED) since Claude may use either form.
    """
    import re

    sections: dict[str, str] = {
        "schedule_health": "",
        "narrative": "",
        "top_risks": "",
        "recommended_actions": "",
        "raw": raw,
    }
    current: str | None = None
    buffer: list[str] = []

    key_map = {
        "SCHEDULE_HEALTH": "schedule_health",
        "NARRATIVE": "narrative",
        "TOP_RISKS": "top_risks",
        "RECOMMENDED_ACTIONS": "recommended_actions",
    }

    # Strip markdown heading markers and horizontal rules for matching
    _header_re = re.compile(r"^#+\s*")
    _hr_re = re.compile(r"^-{3,}$")

    for line in raw.splitlines():
        stripped = line.strip()
        # Normalise: strip leading '#' chars for header matching
        normalised = _header_re.sub("", stripped).strip()

        if _hr_re.match(stripped):
            # Horizontal rule — skip but don't break current section
            continue

        matched = False
        for header, key in key_map.items():
            if normalised.upper().startswith(header):
                if current and buffer:
                    sections[current] = "\n".join(buffer).strip()
                current = key
                # Grab any inline content after the header (e.g., "SCHEDULE_HEALTH: RED")
                rest = normalised[len(header):].lstrip(":— ").strip()
                buffer = [rest] if rest else []
                matched = True
                break

        if not matched and current:
            buffer.append(line)

    if current and buffer:
        sections[current] = "\n".join(buffer).strip()

    # If SCHEDULE_HEALTH contains a full paragraph, extract just the first word/token
    health_raw = sections.get("schedule_health", "")
    first_word = health_raw.split()[0].rstrip(".,;:").upper() if health_raw.split() else ""
    if first_word in ("RED", "YELLOW", "GREEN"):
        sections["schedule_health"] = first_word

    return sections


def _expected_pct(task: dict[str, Any]) -> int:
    """Estimate expected percent complete based on elapsed time vs total duration."""
    from datetime import datetime, timezone
    start = task.get("start")
    finish = task.get("finish")
    if not start or not finish:
        return 0
    now = datetime.now()
    total = (finish - start).total_seconds()
    if total <= 0:
        return 100
    elapsed = (now - start).total_seconds()
    pct = max(0, min(100, int(elapsed / total * 100)))
    return pct
