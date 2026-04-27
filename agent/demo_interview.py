"""
Teams Interview Demo Runner.

Joins a live Microsoft Teams meeting via Azure ACS, then conducts a full
CAM status interview. Both the agent questions and the simulated CAM
responses are played as TTS audio into the call — anyone in the meeting
hears both sides of the conversation in real time.

Usage (via main.py):
    python main.py --demo-interview \\
        --meeting-url "https://teams.microsoft.com/l/meetup-join/..." \\
        --cam "Alice Nguyen" \\
        --callback-url "https://abcd1234.ngrok.io"

What participants hear in Teams:
    [Jenny / Agent]  "Hi Alice, this is the ATLAS program scheduling agent..."
    [Aria  / CAM  ]  "Hi, yeah, I'm ready."
    [Jenny / Agent]  "Task 1 of 8: ICD Development. Last at 55%—what's current?"
    [Aria  / CAM  ]  "We're at about 60%, but still waiting on RF specs..."
    ... (full interview) ...
    [Jenny / Agent]  "Thanks, I've got everything I need. Have a great day!"

After the call ends, a summary of extracted data and IMS impact is printed.
"""

import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from agent.voice.interview_agent import InterviewAgent

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Azure Neural TTS voices — override in .env
_AGENT_VOICE = os.getenv("AGENT_TTS_VOICE", "en-US-JennyNeural")
_CAM_VOICE = os.getenv("CAM_TTS_VOICE", "en-US-AriaNeural")
_PAUSE_SEC = float(os.getenv("DEMO_TURN_PAUSE_SEC", "0.4"))
_MAX_TURNS = int(os.getenv("DEMO_MAX_TURNS", "80"))

# Console colours (ANSI)
_RST = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[96m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_DIM = "\033[2m"


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _hdr(text: str) -> None:
    print(f"\n{_BOLD}{text}{_RST}")


def _status(text: str) -> None:
    print(f"  {_GREEN}{text}{_RST}")


def _warn(text: str) -> None:
    print(f"  {_RED}WARNING: {text}{_RST}")


def _err(text: str) -> None:
    print(f"  {_RED}ERROR: {text}{_RST}", file=sys.stderr)


def _agent_line(text: str) -> None:
    print(f"\n{_CYAN}{_BOLD}[AGENT]{_RST}  {_CYAN}{text}{_RST}")


def _cam_line(name: str, text: str) -> None:
    print(f"\n{_YELLOW}{_BOLD}[{name.upper()[:12]}]{_RST}  {_YELLOW}{text}{_RST}")


def _divider(char: str = "-", width: int = 62) -> None:
    print(f"{_DIM}{char * width}{_RST}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_demo(
    meeting_url: str,
    cam_name: str,
    ims_path: str,
    callback_url: str,
) -> None:
    """
    Run a live Teams interview demo. Blocks until the interview finishes.

    Args:
        meeting_url:  Full Teams meeting join URL.
        cam_name:     CAM persona to simulate (must exist in the IMS).
        ims_path:     Path to the IMS XML file.
        callback_url: Public HTTPS base URL receiving ACS events (e.g. ngrok URL).
    """
    from agent.acs_event_handler import event_bus
    from agent.file_handler import IMSFileHandler
    from agent.voice.cam_simulator import CAMSimulator, build_atlas_personas
    from agent.voice.interview_agent import InterviewAgent, InterviewState
    from agent.voice.teams_connector import (
        LocalElevenLabsConnector, TeamsACSConnector, TeamsGraphConnector,
    )

    # ── Header ──────────────────────────────────────────────────────────────
    print(f"\n{_BOLD}{'=' * 62}{_RST}")
    print(f"{_BOLD}  IMS Agent - Teams Interview Demo{_RST}")
    print(f"{_BOLD}{'=' * 62}{_RST}")
    print(f"  CAM            {cam_name}")
    print(f"  Meeting URL    {meeting_url[:52]}...")
    print(f"  Callback URL   {callback_url}")
    print(f"  Agent voice    {_AGENT_VOICE}")
    print(f"  CAM voice      {_CAM_VOICE}")
    print(f"{_BOLD}{'=' * 62}{_RST}")

    # ── Load IMS ─────────────────────────────────────────────────────────────
    _hdr("Loading IMS schedule...")
    if not Path(ims_path).exists():
        _err(f"IMS file not found: {ims_path}")
        sys.exit(1)

    handler = IMSFileHandler(ims_path)
    tasks = handler.parse()
    personas = build_atlas_personas(tasks)

    if cam_name not in personas:
        available = "  ".join(f'"{n}"' for n in personas)
        _err(f"CAM '{cam_name}' not found in IMS.\n  Available: {available}")
        sys.exit(1)

    persona = personas[cam_name]
    all_cam_tasks = [
        t for t in tasks
        if t.get("cam") == cam_name and not t.get("is_milestone")
    ]
    # Skip tasks already at 100% — no need to ask about completed work
    cam_tasks = [t for t in all_cam_tasks if t.get("percent_complete", 0) < 100]
    _status(
        f"Loaded {len(tasks)} total tasks — {len(all_cam_tasks)} assigned to {cam_name} "
        f"({len(cam_tasks)} to review, {len(all_cam_tasks) - len(cam_tasks)} already complete)"
    )

    # ── Connect to Teams / local audio ───────────────────────────────────────
    _hdr("Connecting...")
    event_bus.reset()

    connector = None
    call_id = None

    # Priority 1: Teams Graph Bot (if TEAMS_BOT_APP_ID is set)
    if os.getenv("TEAMS_BOT_APP_ID"):
        try:
            connector = TeamsGraphConnector()
            call_id = connector.join_meeting(meeting_url, callback_url)
            # Register with server so /graph/audio/<id> can serve audio clips
            import agent.dashboard.server as _srv
            _srv._graph_connector = connector
            _status(
                f"Teams Graph Bot joining as '{connector._BOT_DISPLAY_NAME}' — "
                f"waiting for call to establish (up to 60 s)"
            )
        except Exception as exc:
            _warn(f"TeamsGraphConnector failed: {exc}")
            connector = None

    # Priority 2: ACS (legacy — TeamsMeetingLocator not in SDK 1.5, kept for future)
    if connector is None and os.getenv("ACS_CONNECTION_STRING"):
        try:
            connector = TeamsACSConnector()
            call_id = connector.join_meeting(meeting_url, callback_url)
            _status("ACS connector joining Teams meeting")
        except Exception as exc:
            _warn(f"TeamsACSConnector failed: {exc}")
            connector = None

    # Priority 3: Local ElevenLabs audio (no Teams — audio plays through speakers)
    if connector is None:
        _status("No Teams bot credentials found — playing audio locally through speakers")
        _status("  Set TEAMS_BOT_APP_ID, TEAMS_BOT_APP_SECRET, TEAMS_TENANT_ID to join Teams")
        try:
            connector = LocalElevenLabsConnector()
            call_id = connector.join_meeting(meeting_url, callback_url)
        except (EnvironmentError, ImportError) as exc:
            _err(f"Local audio fallback failed: {exc}")
            sys.exit(1)

    is_graph = isinstance(connector, TeamsGraphConnector)
    is_acs   = isinstance(connector, TeamsACSConnector)
    is_local = isinstance(connector, LocalElevenLabsConnector)

    connect_timeout = 2 if is_local else 60
    if not event_bus.wait_for_connect(timeout=connect_timeout):
        if is_graph:
            _err(
                "Timed out waiting for Teams to accept the Graph bot.\n"
                "  • Verify TEAMS_BOT_APP_ID, TEAMS_BOT_APP_SECRET, TEAMS_TENANT_ID are correct\n"
                "  • Confirm Calls.JoinGroupCall.All permission has admin consent\n"
                "  • Verify callback URL is reachable (check ngrok at localhost:4040)\n"
                "  • Check the meeting lobby settings — set 'Who can bypass lobby?' to Everyone"
            )
        elif is_acs:
            _err(
                "Timed out waiting for Teams to accept the ACS call.\n"
                "  • Verify ACS_CONNECTION_STRING is correct\n"
                "  • Verify callback URL is reachable"
            )
        else:
            _err("Local audio connector failed to signal connection.")
        connector.end_call(call_id)
        sys.exit(1)

    confirmed_cid = event_bus.call_connection_id or call_id
    _status(f"Connected! (call_connection_id={confirmed_cid})")

    # ── speak() helper — play TTS + block until done ─────────────────────────
    def speak(text: str, voice: str) -> None:
        event_bus.arm_play()
        if is_graph:
            connector.play_text(confirmed_cid, text, voice=voice,
                                callback_url=callback_url)
        else:
            connector.play_text(confirmed_cid, text, voice=voice)
        completed = event_bus.wait_for_play(timeout=120)
        if not completed:
            logger.warning("action=play_timeout text=%r", text[:40])
        elif not event_bus.last_play_succeeded:
            logger.warning("action=play_failed text=%r", text[:40])
        time.sleep(_PAUSE_SEC)

    # ── Interview loop ────────────────────────────────────────────────────────
    print()
    _divider("-")
    _status("INTERVIEW START")
    _divider("-")

    agent = InterviewAgent(cam_name, cam_tasks, all_tasks=tasks)
    simulator = CAMSimulator(persona)
    terminal = {InterviewState.COMPLETE, InterviewState.ABORTED}
    turn_count = 0

    turn = agent.start()
    _agent_line(turn.text)
    speak(turn.text, _AGENT_VOICE)

    while agent.state not in terminal and turn_count < _MAX_TURNS:
        cam_response = simulator.respond(turn.text)
        _cam_line(cam_name, cam_response)
        speak(cam_response, _CAM_VOICE)

        turn = agent.process(cam_response)
        if turn.text:
            _agent_line(turn.text)
            speak(turn.text, _AGENT_VOICE)

        turn_count += 1

    _divider("-")
    _status(f"INTERVIEW COMPLETE  ({turn_count} turns, state={agent.state.value})")
    _divider("-")

    # ── Hang up ───────────────────────────────────────────────────────────────
    _hdr("Hanging up...")
    connector.end_call(confirmed_cid)
    event_bus.wait_for_disconnect(timeout=10)
    _status("Call ended.")

    # ── Results ───────────────────────────────────────────────────────────────
    _show_results(agent, tasks, ims_path)


# ---------------------------------------------------------------------------
# Post-interview results display
# ---------------------------------------------------------------------------

def _show_results(agent: "InterviewAgent", tasks: list, ims_path: str) -> None:
    """Print extracted cam_inputs and run a what-if IMS impact analysis."""
    results = agent.results
    captured = [r for r in results if r.status == "captured"]
    no_resp = [r for r in results if r.status == "no_response"]
    cam_inputs = [r.to_cam_input_dict() for r in captured]

    print()
    _hdr(f"EXTRACTED CAM DATA  ({len(captured)} captured  /  {len(no_resp)} no-response)")
    _divider()
    for inp in cam_inputs:
        pct = f"{inp['percent_complete']:>3}%"
        blocker = f"  BLOCKER: {inp['blocker'][:52]}" if inp["blocker"] else ""
        risk = f"  {_RED}RISK{_RST}" if inp["risk_flag"] else ""
        print(f"  Task {inp['task_id']:>3}  {pct}{blocker}{risk}")
    if no_resp:
        for r in no_resp:
            print(f"  Task {r.task_id:>3}   --  (no response)")

    if not cam_inputs:
        print("  (no data captured — cannot run impact analysis)")
        return

    # ── What-if analysis on a temp copy of the IMS ───────────────────────────
    _hdr("IMS IMPACT ANALYSIS  (what-if — original file unchanged)")
    _divider()

    tmp_path: str | None = None
    try:
        from agent.critical_path import calculate_critical_path
        from agent.file_handler import IMSFileHandler
        from agent.sra_runner import SRARunner

        # Baseline — parse original file
        before_tasks = IMSFileHandler(ims_path).parse()
        cp_before = calculate_critical_path(before_tasks)
        sra_before = SRARunner(before_tasks).run()

        # What-if — apply cam_inputs to a temp copy
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            tmp_path = f.name
        shutil.copy(ims_path, tmp_path)

        after_handler = IMSFileHandler(tmp_path)
        after_handler.apply_updates(cam_inputs)
        after_tasks = after_handler.parse()
        cp_after = calculate_critical_path(after_tasks)
        sra_after = SRARunner(after_tasks).run()

        _print_cp_diff(cp_before, cp_after)
        _print_sra_comparison(sra_before, sra_after)

    except Exception as exc:
        logger.error("action=impact_analysis_error error=%s", exc, exc_info=True)
        _warn(f"Impact analysis failed: {exc}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    print()
    _divider("=")
    _status("Demo complete. The IMS file was NOT modified.")
    _divider("=")


def _print_cp_diff(cp_before: dict, cp_after: dict) -> None:
    old_ids = {t.get("task_id") for t in cp_before.get("critical_path", [])}
    new_ids = {t.get("task_id") for t in cp_after.get("critical_path", [])}
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    unchanged = len(new_ids) - len(added)

    print(f"\n  Critical Path  ({len(old_ids)} tasks before → {len(new_ids)} after)")
    if added:
        print(f"    {_RED}+ Added:   {', '.join(added)}{_RST}")
    if removed:
        print(f"    {_GREEN}- Removed: {', '.join(removed)}{_RST}")
    if not added and not removed:
        print(f"    No change ({unchanged} tasks remain on critical path)")


def _print_sra_comparison(sra_before: dict, sra_after: dict) -> None:
    before_ms = {m["task_id"]: m for m in sra_before.get("milestones", [])}
    after_ms = {m["task_id"]: m for m in sra_after.get("milestones", [])}

    if not after_ms:
        return

    print(f"\n  Milestone Probabilities (chance of hitting baseline date)")
    for tid, after in after_ms.items():
        before = before_ms.get(tid, {})
        p_before = before.get("prob_on_baseline", 0.0)
        p_after = after.get("prob_on_baseline", 0.0)
        delta = p_after - p_before
        name = after.get("milestone_name", tid)[:32]

        if p_after >= 0.75:
            color = _GREEN
        elif p_after >= 0.50:
            color = _YELLOW
        else:
            color = _RED

        if abs(delta) < 0.005:
            delta_str = "(no change)"
        elif delta > 0:
            delta_str = f"{_GREEN}(+{delta:.0%}){_RST}"
        else:
            delta_str = f"{_RED}({delta:.0%}){_RST}"

        print(f"    {color}{name:<34}{p_after:>5.0%}{_RST}  {delta_str}")
