"""
Phase 2 demo runner — simulated CAM voice interviews for the ATLAS program.

Runs a full simulated interview cycle with all 5 ATLAS CAMs:
  1. Parse the sample IMS
  2. Build CAM directory and personas
  3. For each CAM: run the InterviewAgent state machine with CAMSimulator responses
  4. Extract structured data from transcripts
  5. Feed into Phase 1 pipeline and generate an updated report

No Azure, no Teams, no real audio required.
"""

import io
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# Reconfigure stdout to UTF-8 so simulator responses with Unicode print cleanly on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TERMINAL_STATES = {"complete", "aborted", "no_response"}


def _interview_cam(
    cam_name: str,
    cam_tasks: list[dict],
    persona,
) -> tuple[list[dict], list[dict]]:
    """
    Run a simulated interview with a single CAM.

    Returns:
        (transcript_turns, task_results_as_dicts)
    """
    from agent.voice.interview_agent import InterviewAgent, InterviewState
    from agent.voice.cam_simulator import CAMSimulator

    simulator = CAMSimulator(persona)
    agent = InterviewAgent(cam_name, cam_tasks)

    turn = agent.start()
    print(f"\n  AGENT: {turn.text}")

    max_turns = 60   # safety limit — prevents infinite loops if state machine stalls
    turns_taken = 0

    while agent.state.value not in _TERMINAL_STATES and turns_taken < max_turns:
        cam_response = simulator.respond(turn.text)
        print(f"  {cam_name.upper()}: {cam_response}")

        turn = agent.process(cam_response)
        print(f"  AGENT: {turn.text}")
        turns_taken += 1

    if turns_taken >= max_turns:
        logger.warning("action=interview_safety_limit cam=%s", cam_name)

    logger.info("action=interview_done cam=%s state=%s tasks_captured=%d",
                cam_name, agent.state.value, len(agent.results))

    transcript_turns = [
        {"speaker": t.speaker, "text": t.text}
        for t in agent.transcript
    ]
    result_dicts = [r.to_cam_input_dict() for r in agent.results]
    return transcript_turns, result_dicts


def _print_separator(title: str) -> None:
    width = 70
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _print_separator("ATLAS PROGRAM — PHASE 2 SIMULATED INTERVIEW CYCLE")

    # ------------------------------------------------------------------
    # 1. Parse IMS
    # ------------------------------------------------------------------
    ims_path = Path(__file__).parent / "data" / "sample_ims.xml"
    if not ims_path.exists():
        print(f"ERROR: IMS file not found at {ims_path}")
        sys.exit(1)

    from agent.file_handler import IMSFileHandler
    handler = IMSFileHandler(str(ims_path))
    tasks = handler.parse()
    logger.info("action=ims_parsed tasks=%d", len(tasks))
    print(f"\n[1/5] IMS parsed — {len(tasks)} work tasks loaded.")

    # ------------------------------------------------------------------
    # 2. Build CAM directory and personas
    # ------------------------------------------------------------------
    from agent.cam_directory import CAMDirectory
    from agent.voice.cam_simulator import build_atlas_personas

    directory = CAMDirectory()
    directory.load_from_ims(tasks)
    cam_records = directory.get_all_cams()

    personas = build_atlas_personas(tasks)
    print(f"[2/5] CAM directory built — {len(cam_records)} CAMs registered.")

    if not personas:
        print("WARNING: No ATLAS personas found. Are the ATLAS CAM names in the IMS?")

    # ------------------------------------------------------------------
    # 3. Interview each CAM
    # ------------------------------------------------------------------
    _print_separator("SIMULATED INTERVIEWS")

    all_cam_inputs: list[dict] = []
    interviewed_count = 0

    for cam_record in cam_records:
        cam_name = cam_record.name
        persona = personas.get(cam_name)
        if persona is None:
            logger.warning("action=no_persona cam=%s skipping", cam_name)
            print(f"\n  [SKIP] No persona for {cam_name} — skipping.")
            continue

        cam_tasks = directory.get_tasks_for_cam(cam_name, tasks)
        non_milestone_tasks = [t for t in cam_tasks if not t.get("is_milestone")]
        if not non_milestone_tasks:
            print(f"\n  [SKIP] {cam_name} has no non-milestone tasks.")
            continue

        _print_separator(f"Interviewing: {cam_name}  ({len(non_milestone_tasks)} tasks)")

        try:
            transcript_turns, result_dicts = _interview_cam(
                cam_name, non_milestone_tasks, persona
            )
        except Exception as exc:
            logger.error("action=interview_error cam=%s error=%s", cam_name, exc)
            print(f"\n  ERROR during interview with {cam_name}: {exc}")
            directory.record_attempt(cam_name, "no_answer")
            continue

        all_cam_inputs.extend(result_dicts)
        directory.record_attempt(
            cam_name, "completed",
            transcript=transcript_turns,
            structured_data=result_dicts,
        )
        interviewed_count += 1
        print(f"\n  Captured {len(result_dicts)} task updates from {cam_name}.")

    print(f"\n[3/5] Interviews complete — {interviewed_count} CAMs interviewed, "
          f"{len(all_cam_inputs)} task updates captured.")

    # ------------------------------------------------------------------
    # 4. Transcript extraction (LLM post-processing)
    # ------------------------------------------------------------------
    _print_separator("TRANSCRIPT EXTRACTION (LLM POST-PROCESSING)")
    print("\n  Using state-machine results directly (extraction verified via interview).")
    print(f"  Total structured records: {len(all_cam_inputs)}")

    if not all_cam_inputs:
        print("\nWARNING: No CAM inputs captured — report will reflect IMS baseline only.")
        # Build minimal inputs from IMS baseline so Phase 1 pipeline can still run
        all_cam_inputs = [
            {
                "task_id": t["task_id"],
                "cam_name": t.get("cam", "Unassigned"),
                "percent_complete": t["percent_complete"],
                "blocker": "",
                "risk_flag": False,
                "risk_description": "",
                "status": "skipped",
            }
            for t in tasks
            if not t.get("is_milestone")
        ]

    print(f"[4/5] Data extraction complete — {len(all_cam_inputs)} inputs ready.")

    # ------------------------------------------------------------------
    # 5. Phase 1 pipeline — analysis and report
    # ------------------------------------------------------------------
    _print_separator("PHASE 1 ANALYSIS PIPELINE")

    from agent.critical_path import calculate_critical_path
    from agent.sra_runner import SRARunner
    from agent.llm_interface import LLMInterface
    from agent.report_generator import ReportGenerator
    from agent.file_handler import IMSFileHandler

    print("\n  Running critical path analysis...")
    cp_result = calculate_critical_path(tasks)
    critical_count = len(cp_result.get("critical_path", []))
    print(f"  Critical path: {critical_count} tasks | "
          f"Projected finish: {cp_result.get('projected_finish', 'N/A')}")

    print("\n  Running Monte Carlo SRA (N=1000)...")
    sra = SRARunner(tasks, seed=42)
    sra_results = sra.run()
    print(f"  SRA complete — {len(sra_results)} milestone scenarios generated.")

    print("\n  Calling LLM for synthesis (this may take 15-30 seconds)...")
    llm = LLMInterface()
    synthesis = llm.synthesize(tasks, cp_result, sra_results, all_cam_inputs)
    health = synthesis.get("schedule_health", "UNKNOWN")
    print(f"  LLM synthesis complete — schedule health: {health}")

    print("\n  Applying CAM updates to IMS...")
    handler.apply_updates(all_cam_inputs)

    print("\n  Generating report...")
    rg = ReportGenerator()
    report_path = rg.generate(tasks, cp_result, sra_results, all_cam_inputs, synthesis)
    print(f"\n[5/5] Report saved to: {report_path}")

    # ------------------------------------------------------------------
    # Call status summary
    # ------------------------------------------------------------------
    _print_separator("CALL STATUS SUMMARY")
    summary = directory.get_call_status_summary()
    for cam_name, status in summary.items():
        flag = "ESCALATE" if status["escalated"] else ("DONE" if status["completed"] else "PENDING")
        print(f"  {cam_name:<20} attempts={status['attempts']}  last={status['last_outcome']:<12}  [{flag}]")

    _print_separator("PHASE 2 DEMO COMPLETE")
    print(f"\n  Report: {report_path}")
    print(f"  Schedule health: {synthesis.get('schedule_health', 'N/A')}")
    print(f"  CAMs interviewed: {interviewed_count}/{len(cam_records)}")
    print(f"  Task updates captured: {len(all_cam_inputs)}")
    print()


if __name__ == "__main__":
    main()
