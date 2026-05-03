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
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# TD-009: inter-call delay to avoid hammering the Anthropic API.
# Read at call time so that changes to .env take effect without restart.
def _call_delay_s() -> float:
    """Return the configured inter-call delay in seconds (default 200 ms)."""
    return int(os.getenv("SIMULATOR_CALL_DELAY_MS", "200")) / 1000.0


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
            role="AI Stack lead",
            communication_style="Precise and technical. Reports clearly but tends to "
                                "mention upstream dependencies unprompted.",
            task_context=by_cam["Alice Nguyen"],
            seeded_blockers={
                # AI-07: Claude API gateway proxy (ID=62)
                "62": "The auth layer for the LLM gateway isn't settled yet — "
                      "security wants mutual TLS but that depends on the cert "
                      "infrastructure Carol is still standing up.",
                # AI-10: Model versioning tooling (ID=65)
                "65": "We're still debating between MLflow and a custom S3-backed "
                      "scheme — can't start implementation until that architecture "
                      "decision is signed off.",
            },
            seeded_risks={
                # AI-07 gateway is on the critical path to inference pipeline test
                "62": "If the API gateway isn't done by mid-May, Eva's end-to-end "
                      "inference test can't start — and that's on the acceptance "
                      "critical path.",
            },
            # AI-06=85%, AI-07=60%, AI-09=10%, AI-10=5%
            seeded_pcts={"61": 85, "62": 60, "64": 10, "65": 5},
        )

    if "Bob Martinez" in by_cam:
        # Bob's tasks are all complete — no in-progress work to seed
        personas["Bob Martinez"] = CAMPersona(
            cam_name="Bob Martinez",
            role="Hardware Development lead",
            communication_style="Straightforward. Gets to the point. Mentions resource "
                                "issues when directly asked about blockers.",
            task_context=by_cam.get("Bob Martinez", []),
            seeded_blockers={},
            seeded_risks={},
            seeded_pcts={},
        )

    if "Carol Smith" in by_cam:
        personas["Carol Smith"] = CAMPersona(
            cam_name="Carol Smith",
            role="Networking and Facilities lead",
            communication_style="Upbeat and concise. Tends to report status efficiently "
                                "but flags dependencies clearly.",
            task_context=by_cam["Carol Smith"],
            seeded_blockers={
                # NET-01: VLANs (ID=69)
                "69": "I'm waiting on David to finish the network topology doc — "
                      "I need those VLAN assignments locked before I can push config "
                      "to the switch.",
                # NET-04: WireGuard VPN (ID=72)
                "72": "VPN gateway setup depends on the TLS cert infrastructure, "
                      "and that's still at zero — so NET-04 is blocked behind NET-07.",
            },
            seeded_risks={
                # NET-01 is the upstream dependency for everything downstream
                "69": "VLANs are the foundation — firewall rules, VPN, load balancing "
                      "all stack behind it. If this slips more than a week we're "
                      "compressing the whole network config chain.",
            },
            # NET-01=20%, NET-02=5%, rest still at 0
            seeded_pcts={"69": 20, "70": 5},
        )

    if "David Lee" in by_cam:
        personas["David Lee"] = CAMPersona(
            cam_name="David Lee",
            role="Documentation and Integration lead",
            communication_style="Methodical. Focused on completeness. Asks clarifying "
                                "questions if context is unclear.",
            task_context=by_cam["David Lee"],
            seeded_blockers={
                # AI-11: Architecture doc (ID=66)
                "66": "I'm waiting on Alice to finalize the API contracts for the "
                      "orchestration layer before I can call the architecture doc done.",
            },
            seeded_risks={
                # DOC-08: Final review is the last gate (ID=92)
                "92": "Final documentation review is the acceptance gate. If the "
                      "individual docs aren't wrapped up two weeks out, this "
                      "compresses and we risk slipping sign-off.",
            },
            # AI-11=40%, DOC-01=15%, rest at 0
            seeded_pcts={"66": 40, "85": 15},
        )

    if "Eva Johnson" in by_cam:
        personas["Eva Johnson"] = CAMPersona(
            cam_name="Eva Johnson",
            role="Security and Test lead",
            communication_style="Professional and direct. Short, crisp answers. "
                                "Always confirms before wrapping up.",
            task_context=by_cam["Eva Johnson"],
            seeded_blockers={
                # NET-11: External pen test (ID=79)
                "79": "External red team isn't scheduled yet — vendor coordination "
                      "is taking longer than expected. We've got two firms in scope "
                      "but neither has confirmed dates.",
                # NET-09: Remediate findings (ID=77)
                "77": "Can't start remediation until the Nessus scan report is in "
                      "hand — NET-08 has to come first.",
            },
            seeded_risks={
                # Pen test is on the critical path to security sign-off
                "79": "If the pen test isn't done by end of May, NET-15 security "
                      "sign-off slips, and that holds up the entire program delivery.",
                # Security review is the final gate
                "83": "NET-15 is the final security gate. Any slip here blocks "
                      "acceptance — it's the last item before we can call the "
                      "program complete.",
            },
            # AI-08=10%, AI-12=25%, rest at 0
            seeded_pcts={"63": 10, "67": 25},
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

        # TD-009: throttle successive API calls to avoid rate limiting.
        delay = _call_delay_s()
        if delay > 0:
            time.sleep(delay)

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

        # List tasks that are explicitly flagged as schedule risks in seeded data
        seeded_risk_ids = set(p.seeded_risks.keys())

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
            + (f"Schedule risk guidance: Only the tasks explicitly marked '| RISK:' above "
               f"are true schedule risks from your perspective. When the agent asks whether "
               f"a task 'puts a milestone at risk', answer YES only for those tasks. "
               f"For all other tasks, answer no — a blocker or slow progress alone does not "
               f"make it a schedule risk unless it appears in your RISK list above.\n\n"
               if seeded_risk_ids else "")
        )
