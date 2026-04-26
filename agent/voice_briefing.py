"""
Voice briefing — generates a 1-2 minute PM audio briefing after each cycle.

Flow:
  1. LLM generates a spoken briefing script from the synthesis output
  2. ElevenLabs TTS converts the script to an MP3 file
  3. The file path is returned so the cycle runner can attach it to notifications

The briefing is intentionally concise: health, top 2 risks, single recommended action.
Approximate runtime: 60-90 seconds of audio.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
_BRIEFING_ENABLED = os.getenv("VOICE_BRIEFING_ENABLED", "false").lower() == "true"


def generate_briefing(synthesis: dict[str, Any], cycle_id: str) -> str | None:
    """
    Generate a voice briefing MP3 for the PM.

    Args:
        synthesis: LLM synthesis dict (schedule_health, narrative, top_risks,
                   recommended_actions).
        cycle_id:  Cycle ID string for the output filename.

    Returns:
        Path to the generated MP3 file, or None if disabled / TTS unavailable.
    """
    if not _BRIEFING_ENABLED:
        logger.info("action=briefing_skip reason=disabled")
        return None

    script = _build_script(synthesis)
    if not script:
        return None

    audio_path = _synthesize(script, cycle_id)
    return audio_path


def _build_script(synthesis: dict[str, Any]) -> str:
    """Ask the LLM to write a concise spoken briefing from the synthesis."""
    try:
        from agent.llm_interface import LLMInterface
    except ImportError:
        return ""

    health = synthesis.get("schedule_health", "UNKNOWN")
    top_risks = synthesis.get("top_risks", "")
    actions = synthesis.get("recommended_actions", "")

    prompt = (
        f"Write a spoken voice briefing for a program manager. "
        f"Maximum 150 words. Use plain conversational language — no bullet points, "
        f"no markdown, no section headers. Just natural spoken sentences.\n\n"
        f"Schedule health: {health}\n\n"
        f"Top risks summary:\n{top_risks[:600]}\n\n"
        f"Recommended actions:\n{actions[:400]}\n\n"
        f"Start with: 'This is your IMS Agent briefing for {datetime.now().strftime('%B %d')}.' "
        f"End with a single clear action the PM should take today."
    )

    try:
        llm = LLMInterface()
        script = llm.ask(prompt, context="")
        logger.info("action=briefing_script_generated words=%d", len(script.split()))
        return script.strip()
    except Exception as exc:
        logger.error("action=briefing_script_error error=%s", exc)
        return ""


def _synthesize(script: str, cycle_id: str) -> str | None:
    """Convert the script to audio using ElevenLabs TTS."""
    try:
        from agent.voice.tts_engine import build_tts_engine
    except ImportError:
        logger.warning("action=briefing_tts_unavailable")
        return None

    briefings_dir = _REPORTS_DIR / "briefings"
    briefings_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(briefings_dir / f"{cycle_id}_briefing.mp3")

    try:
        engine = build_tts_engine()
        engine.synthesize_to_file(script, out_path)
        logger.info("action=briefing_generated path=%s", out_path)
        return out_path
    except Exception as exc:
        logger.error("action=briefing_tts_error error=%s", exc)
        return None
