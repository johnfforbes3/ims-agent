"""
Teams Chat Interview Demo Runner.

Registers a CAM interview session with ChatInterviewManager, starts the
FastAPI server (which hosts /bot/messages), and prints a Teams deep link
for the CAM to open the chat. The interview runs as a back-and-forth Teams
conversation — no audio required.

Usage (via main.py):
    python main.py --demo-chat --cam "Alice Nguyen"

    # If you want to target a specific user's Teams account:
    python main.py --demo-chat --cam "Alice Nguyen" --cam-email alice@company.com

What the CAM sees in Teams:
    [ATLAS Scheduler]  "Hey Alice, it's the ATLAS program scheduler..."
    [Alice]            "Hi, yeah go ahead"
    [ATLAS Scheduler]  "Task 1 of 8: ICD Development. Last at 55% — what's current?"
    [Alice]            "We're at about 60%, but still waiting on RF specs..."
    ... (full interview) ...
    [ATLAS Scheduler]  "Thanks, I've got everything I need. Have a great day!"

After the interview completes, extracted data and IMS impact analysis are printed.
"""

import logging
import os
import sys
import time
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_RST  = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_RED  = "\033[91m"
_DIM  = "\033[2m"


def _hdr(text: str) -> None:
    print(f"\n{_BOLD}{text}{_RST}")


def _status(text: str) -> None:
    print(f"  {_GREEN}{text}{_RST}")


def _err(text: str) -> None:
    print(f"  {_RED}ERROR: {text}{_RST}", file=sys.stderr)


def _divider(char: str = "-", width: int = 62) -> None:
    print(f"{_DIM}{char * width}{_RST}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_chat_demo(
    cam_name: str,
    ims_path: str,
    cam_email: str = "",
) -> None:
    """
    Register a Teams chat interview for cam_name and wait for it to complete.

    Args:
        cam_name:  CAM persona to interview (must exist in the IMS).
        ims_path:  Path to the IMS XML file.
        cam_email: Optional Teams UPN/email to target a specific user.
                   If omitted, the first person to message the bot gets
                   the interview (good for demos where you play the CAM).
    """
    from agent.file_handler import IMSFileHandler
    from agent.voice.teams_chat_connector import (
        ChatInterviewSession,
        ChatInterviewManager,
    )

    # ── Header ───────────────────────────────────────────────────────────────
    print(f"\n{_BOLD}{'=' * 62}{_RST}")
    print(f"{_BOLD}  IMS Agent - Teams Chat Interview Demo{_RST}")
    print(f"{_BOLD}{'=' * 62}{_RST}")
    print(f"  CAM            {cam_name}")
    print(f"  IMS file       {ims_path}")
    if cam_email:
        print(f"  Target email   {cam_email}")
    else:
        print(f"  Target         first user to message the bot")
    print(f"{_BOLD}{'=' * 62}{_RST}")

    # ── Load IMS ─────────────────────────────────────────────────────────────
    _hdr("Loading IMS schedule...")
    if not Path(ims_path).exists():
        _err(f"IMS file not found: {ims_path}")
        sys.exit(1)

    handler = IMSFileHandler(ims_path)
    tasks = handler.parse()
    all_cam_tasks = [
        t for t in tasks
        if t.get("cam") == cam_name and not t.get("is_milestone")
    ]
    cam_tasks = [t for t in all_cam_tasks if t.get("percent_complete", 0) < 100]

    if not cam_tasks:
        _err(f"No pending tasks for {cam_name} in {ims_path}")
        sys.exit(1)

    _status(
        f"Loaded {len(tasks)} total tasks — {len(cam_tasks)} to review for {cam_name}"
    )

    # ── Register interview session ────────────────────────────────────────────
    session = ChatInterviewSession(cam_name, cam_tasks, all_tasks=tasks)
    manager = ChatInterviewManager.get()

    if cam_email:
        manager.register_by_email(cam_email, session)
        _status(f"Session registered for {cam_email}")
    else:
        manager.register_wildcard(session)
        _status("Session registered — waiting for first user to message the bot")

    # ── Print Teams deep link ────────────────────────────────────────────────
    app_id = os.getenv("TEAMS_BOT_APP_ID", "")
    if not app_id:
        _err("TEAMS_BOT_APP_ID is not set in .env")
        sys.exit(1)

    teams_link = f"https://teams.microsoft.com/l/chat/0/0?users=28:{app_id}"

    _hdr("Ready. Open this link to start the chat interview:")
    print(f"\n  {_CYAN}{_BOLD}{teams_link}{_RST}\n")
    print(f"  (or search for 'ATLAS Scheduler' in Teams -> Apps -> message it)")
    print(f"\n  Send any message to kick off the interview.")
    _divider()

    # ── Wait for interview to complete ────────────────────────────────────────
    completed = session.done.wait(timeout=3600)

    _divider()
    if completed:
        _status(f"Interview complete for {cam_name}!")
        _show_results(session.agent, tasks, ims_path)
    else:
        _err("Interview timed out after 60 minutes without completing.")


# ---------------------------------------------------------------------------
# Results display (shared with demo_interview)
# ---------------------------------------------------------------------------

def _show_results(agent: "Any", tasks: list, ims_path: str) -> None:
    """Print extracted cam_inputs and run a what-if IMS impact analysis."""
    import shutil
    import tempfile
    from typing import Any

    results = agent.results
    captured = [r for r in results if r.status == "captured"]
    no_resp  = [r for r in results if r.status == "no_response"]
    cam_inputs = [r.to_cam_input_dict() for r in captured]

    print()
    _hdr(f"EXTRACTED CAM DATA  ({len(captured)} captured  /  {len(no_resp)} no-response)")
    _divider()
    for inp in cam_inputs:
        pct = f"{inp['percent_complete']:>3}%"
        blocker = f"  BLOCKER: {inp['blocker'][:52]}" if inp["blocker"] else ""
        risk    = f"  {_RED}RISK{_RST}" if inp["risk_flag"] else ""
        print(f"  Task {inp['task_id']:>3}  {pct}{blocker}{risk}")
    for r in no_resp:
        print(f"  Task {r.task_id:>3}   --  (no response)")

    if not cam_inputs:
        print("  (no data captured)")
        return

    _hdr("IMS IMPACT ANALYSIS  (what-if — original file unchanged)")
    _divider()

    tmp_path: str | None = None
    try:
        from agent.critical_path import calculate_critical_path
        from agent.file_handler import IMSFileHandler
        from agent.sra_runner import SRARunner

        before_tasks = IMSFileHandler(ims_path).parse()
        cp_before = calculate_critical_path(before_tasks)
        sra_before = SRARunner(before_tasks).run()

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            tmp_path = f.name
        shutil.copy(ims_path, tmp_path)

        after_handler = IMSFileHandler(tmp_path)
        after_handler.apply_updates(cam_inputs)
        after_tasks = after_handler.parse()
        cp_after  = calculate_critical_path(after_tasks)
        sra_after = SRARunner(after_tasks).run()

        _print_cp_diff(cp_before, cp_after)
        _print_sra_comparison(sra_before, sra_after)

    except Exception as exc:
        logger.error("action=impact_analysis_error error=%s", exc, exc_info=True)
        print(f"  (impact analysis failed: {exc})")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    print()
    _divider("=")
    _status("Demo complete. The IMS file was NOT modified.")
    _divider("=")


def _print_cp_diff(cp_before: dict, cp_after: dict) -> None:
    old_ids = set(cp_before.get("critical_path", []))
    new_ids = set(cp_after.get("critical_path", []))
    added   = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)

    print(f"\n  Critical Path  ({len(old_ids)} tasks before -> {len(new_ids)} after)")
    if added:
        print(f"    {_RED}+ Added:   {', '.join(added)}{_RST}")
    if removed:
        print(f"    {_GREEN}- Removed: {', '.join(removed)}{_RST}")
    if not added and not removed:
        print(f"    No change ({len(new_ids)} tasks remain on critical path)")


def _print_sra_comparison(sra_before: dict, sra_after: dict) -> None:
    before_ms = {m["task_id"]: m for m in sra_before.get("milestones", [])}
    after_ms  = {m["task_id"]: m for m in sra_after.get("milestones",  [])}
    if not after_ms:
        return

    print(f"\n  Milestone Probabilities (chance of hitting baseline date)")
    for tid, after in after_ms.items():
        before  = before_ms.get(tid, {})
        p_before = before.get("prob_on_baseline", 0.0)
        p_after  = after.get("prob_on_baseline", 0.0)
        delta    = p_after - p_before
        name     = after.get("milestone_name", tid)[:32]

        color = _GREEN if p_after >= 0.75 else (_RED if p_after < 0.50 else "\033[93m")
        if abs(delta) < 0.005:
            delta_str = "(no change)"
        elif delta > 0:
            delta_str = f"{_GREEN}(+{delta:.0%}){_RST}"
        else:
            delta_str = f"{_RED}({delta:.0%}){_RST}"
        print(f"    {color}{name:<34}{p_after:>5.0%}{_RST}  {delta_str}")
