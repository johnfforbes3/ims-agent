"""
Transcript extractor — LLM-based structured data extraction from interview transcripts.

After each CAM interview, the full conversation transcript is passed to Claude
to extract per-task structured data in the Phase 1 CAM input format.

This is a post-processing step that supplements the real-time state machine;
it catches data the state machine may have missed and provides a second
extraction pass for quality assurance.
"""

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """You are a data extraction assistant for defense program \
schedule management. You will be given a transcript of a voice interview between a \
scheduling agent and a Cost Account Manager (CAM), along with the list of tasks that \
were discussed.

Your job is to extract structured status data for each task mentioned in the transcript. \
Return ONLY a valid JSON array — no prose, no markdown, just the JSON.

Each element in the array must have exactly these fields:
  task_id        (string — the task UID)
  cam_name       (string — the CAM's name)
  percent_complete (integer 0-100, or null if not mentioned)
  blocker        (string — description of blocker, or "" if none)
  risk_flag      (boolean — true if the CAM flagged a risk)
  risk_description (string — risk description, or "" if none)
  status         (string — "captured" | "no_response" | "skipped")

Rules:
- Only include tasks that appear in the provided task list.
- If a task was not discussed, do not include it.
- If the CAM said "I don't know" or similar, set status="no_response" and percent_complete=null.
- If the CAM mentioned a blocker or risk, capture it verbatim.
- Do not invent data. Only extract what is explicitly stated in the transcript.
- percent_complete must be an integer or null — never a string or float.
"""


class TranscriptExtractor:
    """Extracts structured CAM input data from interview transcripts using Claude."""

    def __init__(self) -> None:
        from agent.llm_interface import LLMInterface
        self._llm = LLMInterface()
        logger.info("action=extractor_init")

    def extract(
        self,
        cam_name: str,
        transcript_turns: list[dict[str, str]],
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Extract structured task status from a conversation transcript.

        Args:
            cam_name: The CAM's name.
            transcript_turns: List of {"speaker": "agent"|"cam", "text": "..."}.
            tasks: The task list that was discussed (from IMSFileHandler.parse()).

        Returns:
            List of CAM input dicts matching the Phase 1 format.
            Any extraction failures are logged; the list may be partial.
        """
        if not transcript_turns:
            logger.warning("action=extract_skip reason=empty_transcript cam=%s", cam_name)
            return []

        prompt = self._build_prompt(cam_name, transcript_turns, tasks)
        logger.info("action=extract_start cam=%s tasks=%d", cam_name, len(tasks))

        try:
            raw = self._llm.ask(prompt, context="")
            extracted = self._parse_json(raw)
            validated = self._validate(extracted, cam_name)
            logger.info("action=extract_done cam=%s extracted=%d validated=%d",
                        cam_name, len(extracted), len(validated))
            return validated
        except Exception as exc:
            logger.error("action=extract_error cam=%s error=%s", cam_name, exc)
            return []

    def _build_prompt(
        self,
        cam_name: str,
        turns: list[dict[str, str]],
        tasks: list[dict[str, Any]],
    ) -> str:
        """Build the extraction prompt."""
        task_lines = "\n".join(
            f"  - task_id={t['task_id']}: {t['name']} (current: {t['percent_complete']}%)"
            for t in tasks
        )
        transcript_lines = "\n".join(
            f"{turn['speaker'].upper()}: {turn['text']}"
            for turn in turns
        )
        return (
            f"CAM NAME: {cam_name}\n\n"
            f"TASKS DISCUSSED:\n{task_lines}\n\n"
            f"TRANSCRIPT:\n{transcript_lines}\n\n"
            f"Extract the status data for each task discussed. "
            f"Return only a JSON array."
        )

    def _parse_json(self, raw: str) -> list[dict[str, Any]]:
        """Parse JSON from the LLM response, stripping markdown fences if present."""
        text = raw.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()
        return json.loads(text)

    def _validate(
        self, items: list[dict[str, Any]], cam_name: str
    ) -> list[dict[str, Any]]:
        """Validate extracted items and flag problems."""
        from agent.cam_input import validate_cam_inputs
        from datetime import datetime

        clean: list[dict[str, Any]] = []
        for item in items:
            # Ensure required fields exist
            item.setdefault("cam_name", cam_name)
            item.setdefault("blocker", "")
            item.setdefault("risk_flag", False)
            item.setdefault("risk_description", "")
            item.setdefault("status", "captured")
            item.setdefault("timestamp", datetime.now().isoformat())

            # Coerce percent_complete
            pct = item.get("percent_complete")
            if pct is not None:
                try:
                    item["percent_complete"] = int(pct)
                except (TypeError, ValueError):
                    logger.warning("action=extract_coerce_fail task_id=%s pct=%r",
                                   item.get("task_id"), pct)
                    item["percent_complete"] = None

            errors = validate_cam_inputs([item])
            if errors:
                logger.warning("action=extract_validation_fail task_id=%s errors=%s",
                               item.get("task_id"), errors)
                item["_extraction_warnings"] = errors
            clean.append(item)

        return clean
