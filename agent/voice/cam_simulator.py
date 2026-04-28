"""
CAM Simulator — Claude-powered simulation of CAM voice responses.

Used in Phase 2 simulation mode (CALL_TRANSPORT=simulated) to generate
realistic spoken responses from each CAM during a test interview cycle.

Each simulated CAM is given:
  - A persona (name, role, communication style)
  - Their task context (what they're responsible for, current state)
  - Pre-seeded blockers and risks (to exercise the interview logic)

The simulator produces natural language responses as if the CAM were
speaking on a phone call — not too formal, realistic defense-contractor
engineer vernacular.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)


_SIMULATOR_SYSTEM_PROMPT = """You are roleplaying as a defense program engineer on a \
phone call with an automated scheduling agent doing a quick status check.

Speak naturally, the way an experienced engineer would on a work call. \
You can give context, mention upstream dependencies, and explain your reasoning. \
No Markdown — plain speech only. No bold, no bullets, no headers. \
Keep your answers reasonably focused on what was asked, but don't artificially \
shorten them if the situation genuinely warrants detail."""


@dataclass
class CAMPersona:
    """Persona definition for a simulated CAM."""
    cam_name: str
    role: str
    communication_style: str
    task_context: list[dict[str, Any]]           # Their tasks with current state
    seeded_blockers: dict[str, str] = field(default_factory=dict)   # task_id → blocker
    seeded_risks: dict[str, str] = field(default_factory=dict)      # task_id → risk desc
    seeded_pcts: dict[str, int] = field(default_factory=dict)       # task_id → override pct


# Default personas for the ATLAS program CAMs
ATLAS_PERSONAS: dict[str, CAMPersona] = {}   # Populated by build_atlas_personas()


def build_atlas_personas(tasks: list[dict[str, Any]]) -> dict[str, CAMPersona]:
    """Build the five ATLAS CAM personas from the parsed task list."""
    by_cam: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        cam = t.get("cam", "Unassigned")
        by_cam.setdefault(cam, []).append(t)

    personas: dict[str, CAMPersona] = {}

    if "Alice Nguyen" in by_cam:
        personas["Alice Nguyen"] = CAMPersona(
            cam_name="Alice Nguyen",
            role="Systems Engineering lead",
            communication_style="Precise and technical. Reports clearly but tends to "
                                "mention upstream dependencies unprompted.",
            task_context=by_cam["Alice Nguyen"],
            seeded_blockers={
                "3": "Still waiting on the final RF specs from HW before I can close "
                     "out ICD sections 4 through 6.",
                "8": "Can't start until the ICDs are approved — that's the input I need.",
            },
            seeded_risks={
                "3": "If we don't get the RF specs by end of next week, PDR slips at "
                     "least two weeks.",
            },
            seeded_pcts={"3": 60, "8": 0, "5": 40},
        )

    if "Bob Martinez" in by_cam:
        personas["Bob Martinez"] = CAMPersona(
            cam_name="Bob Martinez",
            role="Hardware Development lead",
            communication_style="Straightforward. Gets to the point. Mentions resource "
                                "issues when directly asked about blockers.",
            task_context=by_cam["Bob Martinez"],
            seeded_blockers={
                "11": "Our simulation runs are taking longer than planned — we've got a "
                      "tool license contention issue on the lab cluster.",
                "12": "One of my key engineers is out on medical leave for about three "
                      "weeks. I've got partial coverage but we're moving slower.",
                "14": "I need the updated antenna aperture requirements from Alice's ICD "
                      "before I can finalize the design.",
            },
            seeded_risks={
                "11": "If I can't get the simulation done by early May, HW-05 fab start "
                      "slips and that pushes the whole hardware acceptance chain.",
                "14": "The antenna design is on the longest hardware path. If it slips "
                      "three weeks, we won't hit the hardware acceptance date.",
            },
            seeded_pcts={"11": 75, "12": 55, "14": 45},
        )

    if "Carol Smith" in by_cam:
        personas["Carol Smith"] = CAMPersona(
            cam_name="Carol Smith",
            role="Software Development lead",
            communication_style="Upbeat and concise. Tends to report status efficiently. "
                                "SW is generally ahead of plan.",
            task_context=by_cam["Carol Smith"],
            seeded_blockers={},
            seeded_risks={},
            seeded_pcts={"22": 70, "23": 30, "24": 20, "26": 15},
        )

    if "David Lee" in by_cam:
        personas["David Lee"] = CAMPersona(
            cam_name="David Lee",
            role="Integration and Test lead",
            communication_style="Methodical. Focused on readiness. Asks clarifying "
                                "questions back if he doesn't understand the context.",
            task_context=by_cam["David Lee"],
            seeded_blockers={},
            seeded_risks={},
            seeded_pcts={},
        )

    if "Eva Johnson" in by_cam:
        personas["Eva Johnson"] = CAMPersona(
            cam_name="Eva Johnson",
            role="Program Management",
            communication_style="Professional and efficient. Short answers. Always "
                                "confirms before hanging up.",
            task_context=by_cam["Eva Johnson"],
            seeded_blockers={},
            seeded_risks={},
            seeded_pcts={"43": 28, "44": 28, "46": 25},
        )

    return personas


class CAMSimulator:
    """
    Simulates a CAM's spoken responses during an interview.

    Uses Claude to generate realistic natural-language responses
    based on the CAM's persona, tasks, and seeded blocker/risk data.
    """

    def __init__(self, persona: CAMPersona) -> None:
        """
        Args:
            persona: The CAMPersona definition for this simulated CAM.
        """
        from agent.llm_interface import LLMInterface
        self._persona = persona
        self._llm = LLMInterface()
        self._conversation_history: list[dict[str, str]] = []
        logger.info("action=simulator_init cam=%s", persona.cam_name)

    def respond(self, agent_utterance: str) -> str:
        """
        Generate a simulated CAM response to an agent utterance.

        Args:
            agent_utterance: What the agent just said.

        Returns:
            The simulated CAM's spoken response as a string.
        """
        self._conversation_history.append(
            {"role": "user", "content": agent_utterance}
        )
        context = self._build_context()
        full_prompt = f"{context}\n\nAgent just said: {agent_utterance!r}\n\nRespond as {self._persona.cam_name}:"

        response = self._llm.ask(full_prompt, context="")
        # Strip any prefixes like "Carol Smith: " that Claude might add
        clean = response.strip()
        for prefix in [f"{self._persona.cam_name}:", "CAM:", "Response:"]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()

        self._conversation_history.append(
            {"role": "assistant", "content": clean}
        )
        logger.info("action=simulator_respond cam=%s input=%r output=%r",
                    self._persona.cam_name,
                    agent_utterance[:50],
                    clean[:80])
        return clean

    def _build_context(self) -> str:
        """Build the full context prompt for Claude."""
        p = self._persona

        task_lines = []
        for t in p.task_context:
            if t.get("is_milestone"):
                continue
            pct = p.seeded_pcts.get(t["task_id"], t["percent_complete"])
            if pct >= 100:
                continue  # Skip completed tasks — agent won't ask about them
            blocker = p.seeded_blockers.get(t["task_id"], "")
            risk = p.seeded_risks.get(t["task_id"], "")
            line = f"  - {t['name']}: {pct}% complete"
            if blocker:
                line += f" | BLOCKER: {blocker}"
            if risk:
                line += f" | RISK: {risk}"
            task_lines.append(line)

        history_lines = []
        for turn in self._conversation_history:
            role = "Agent" if turn["role"] == "user" else p.cam_name
            history_lines.append(f"{role}: {turn['content']}")

        return (
            f"You are: {p.cam_name}, {p.role}\n"
            f"Communication style: {p.communication_style}\n\n"
            f"Your task status right now:\n" + "\n".join(task_lines) + "\n\n"
            + (f"Conversation so far:\n" + "\n".join(history_lines) + "\n\n"
               if history_lines else "")
            + "Important: if you have already explained a blocker or root cause "
              "earlier in this conversation, do not re-explain it in full. "
              "Reference it briefly (e.g. 'same RF spec issue I mentioned') "
              "and move on.\n\n"
        )
