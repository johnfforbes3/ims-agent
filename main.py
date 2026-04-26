"""
IMS Agent — unified entry point.

Modes (mutually exclusive):
  python main.py                   Phase 1: interactive CAM input pipeline
  python main.py --serve           Phase 3: dashboard server only (port 8080)
  python main.py --schedule        Phase 3: scheduler + dashboard (full production mode)
  python main.py --trigger         Phase 3: fire one cycle now, then exit
  python main.py --demo            Phase 2: simulated voice interviews (run_phase2_demo)

Phase 4 Q&A is always available when --serve or --schedule is active:
  Dashboard chat widget: http://localhost:8080 (chat panel at bottom)
  Slack slash command:   /ims <question>  (requires SLACK_APP_TOKEN + SLACK_BOT_TOKEN)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure all relative paths (data/, reports/, logs/) resolve correctly
# regardless of the working directory the caller used to invoke this script.
import os as _os
_os.chdir(Path(__file__).parent)

load_dotenv()

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOGS_DIR = Path(os.getenv("LOGS_DIR", "logs"))
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOGS_DIR / "ims_agent.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode handlers
# ---------------------------------------------------------------------------

def _run_phase1(ims_path: str) -> None:
    from agent.file_handler import IMSFileHandler
    from agent.cam_input import run_simulated_cam_input, validate_cam_inputs
    from agent.critical_path import calculate_critical_path
    from agent.sra_runner import SRARunner
    from agent.llm_interface import LLMInterface
    from agent.report_generator import ReportGenerator

    handler = IMSFileHandler(ims_path)
    tasks = handler.parse()
    logger.info("action=parsed tasks=%d", len(tasks))

    cam_inputs = run_simulated_cam_input(tasks)
    for e in validate_cam_inputs(cam_inputs):
        logger.warning("action=validation_warning msg=%s", e)

    if cam_inputs:
        handler.apply_updates(cam_inputs)
        tasks = handler.parse()

    cp_result = calculate_critical_path(tasks)
    sra_result = SRARunner(tasks).run()
    synthesis = LLMInterface().synthesize(tasks, cp_result, sra_result, cam_inputs)
    report_path = ReportGenerator().generate(tasks, cp_result, sra_result, cam_inputs, synthesis)

    print(f"\nReport saved to: {report_path}\n")
    logger.info("action=pipeline_complete report=%s", report_path)


def _run_demo() -> None:
    import run_phase2_demo
    run_phase2_demo.main()


def _run_trigger(ims_path: str) -> None:
    from agent.cycle_runner import CycleRunner
    print("Triggering one full cycle...")
    runner = CycleRunner(ims_path=ims_path)
    status = runner.run()
    print(f"\nCycle complete — health: {status['schedule_health']}")
    print(f"Report: {status['report_path']}")
    if status.get("error"):
        print(f"ERROR: {status['error']}")
        sys.exit(1)


def _run_serve() -> None:
    from agent.dashboard.server import serve
    from agent.slack_command import start as start_slack
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"Dashboard running at http://localhost:{port}")
    start_slack()  # no-op if tokens not configured
    serve()


def _run_schedule(ims_path: str) -> None:
    """Full production mode: scheduler + dashboard server on main thread."""
    from agent.cycle_runner import CycleRunner
    from agent.scheduler import CycleScheduler
    from agent.dashboard.server import serve
    from agent.slack_command import start as start_slack

    runner = CycleRunner(ims_path=ims_path)
    scheduler = CycleScheduler(cycle_fn=runner.run)
    scheduler.start()
    start_slack()  # no-op if tokens not configured

    cron = os.getenv("SCHEDULE_CRON", "0 6 * * 1")
    tz = os.getenv("SCHEDULE_TIMEZONE", "America/New_York")
    next_run = scheduler.next_run_time
    print(f"Scheduler started — cron='{cron}' tz={tz}")
    print(f"Next cycle: {next_run.isoformat() if next_run else 'N/A'}")

    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"Dashboard: http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")

    try:
        serve()  # blocks on main thread (uvicorn)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        print("\nScheduler stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="IMS Agent")
    parser.add_argument("--ims-file", default=os.getenv("IMS_FILE_PATH", "data/sample_ims.xml"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--serve", action="store_true", help="Start dashboard server only")
    group.add_argument("--schedule", action="store_true", help="Start scheduler + dashboard (production)")
    group.add_argument("--trigger", action="store_true", help="Run one cycle now and exit")
    group.add_argument("--demo", action="store_true", help="Run Phase 2 simulated interview demo")
    args = parser.parse_args()

    ims_path = args.ims_file

    if args.serve:
        _run_serve()
    elif args.schedule:
        _run_schedule(ims_path)
    elif args.trigger:
        _run_trigger(ims_path)
    elif args.demo:
        _run_demo()
    else:
        if not Path(ims_path).exists():
            print(f"\nERROR: IMS file not found: {ims_path}")
            sys.exit(1)
        _run_phase1(ims_path)


if __name__ == "__main__":
    main()
