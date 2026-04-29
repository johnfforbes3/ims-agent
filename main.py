"""
IMS Agent — unified entry point.

Modes (mutually exclusive):
  python main.py                   Phase 1: interactive CAM input pipeline
  python main.py --serve           Phase 3: dashboard server only (port 9000)
  python main.py --schedule        Phase 3: scheduler + dashboard (full production mode)
  python main.py --trigger         Phase 3: fire one cycle now, then exit
  python main.py --demo            Phase 2: simulated voice interviews (run_phase2_demo)
  python main.py --demo-interview  Tier 3: live Teams interview demo via Azure ACS
    --meeting-url <url>              Teams meeting join URL (required)
    --callback-url <url>             Public HTTPS URL for ACS webhooks (required)
    --cam <name>                     CAM to interview (default: "Alice Nguyen")

Phase 4 Q&A is always available when --serve or --schedule is active:
  Dashboard chat widget: http://localhost:9000 (chat panel at bottom)
  Slack slash command:   /ims <question>  (requires SLACK_APP_TOKEN + SLACK_BOT_TOKEN)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Force UTF-8 + line-buffered output so Unicode chars don't crash on Windows
# cp1252 terminals, and so print() output isn't lost when stdout is redirected.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from dotenv import load_dotenv

# Ensure all relative paths (data/, reports/, logs/) resolve correctly
# regardless of the working directory the caller used to invoke this script.
import os as _os
_os.chdir(Path(__file__).parent)

load_dotenv()

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()  # "text" or "json"
_LOGS_DIR = Path(os.getenv("LOGS_DIR", "logs"))
_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _make_formatter() -> logging.Formatter:
    if _LOG_FORMAT == "json":
        import json as _json

        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return _json.dumps({
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                    **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
                })

        return _JsonFormatter()
    return logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")


_formatter = _make_formatter()
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_formatter)
_file_handler = logging.FileHandler(_LOGS_DIR / "ims_agent.log", encoding="utf-8")
_file_handler.setFormatter(_formatter)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    handlers=[_stream_handler, _file_handler],
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
    mode = os.getenv("CALL_TRANSPORT", "simulated")
    print(f"Triggering one full cycle...  (mode={mode})")
    runner = CycleRunner(ims_path=ims_path, mode=mode)
    status = runner.run()
    print(f"\nCycle complete — health: {status['schedule_health']}")
    print(f"Report: {status['report_path']}")
    if status.get("error"):
        print(f"ERROR: {status['error']}")
        sys.exit(1)


def _run_serve() -> None:
    from agent.dashboard.server import serve
    from agent.slack_command import start as start_slack
    port = int(os.getenv("DASHBOARD_PORT", "9000"))
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

    port = int(os.getenv("DASHBOARD_PORT", "9000"))
    print(f"Dashboard: http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")

    try:
        serve()  # blocks on main thread (uvicorn)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        print("\nScheduler stopped.")


def _run_demo_interview(
    meeting_url: str,
    cam_name: str,
    ims_path: str,
    callback_url: str,
) -> None:
    """
    Tier 3 — live Teams interview demo.

    Starts the FastAPI callback server in a background thread (to receive ACS
    webhook events), then runs the interview on the main thread. The server
    shuts down automatically when the interview completes.
    """
    import threading
    import time
    import uvicorn
    from agent.dashboard.server import app
    from agent.demo_interview import run_demo

    port = int(os.getenv("DASHBOARD_PORT", "9000"))

    # Start the ACS callback server in a daemon thread
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait up to 5 s for uvicorn to report ready
    deadline = time.monotonic() + 5.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)

    print(f"  ACS callback server ready on port {port}")
    print(f"  Webhook path: {callback_url.rstrip('/')}/acs/callback\n")

    try:
        run_demo(meeting_url, cam_name, ims_path, callback_url)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


def _run_init_mpp(ims_path: str) -> None:
    """One-time seed: convert the working XML → a timestamped master in data/ims_master/.

    COM available  → writes IMS_<ts>.mpp  (native MS Project binary)
    MPXJ fallback  → writes IMS_<ts>.xml  (MSPDI XML, openable by MS Project)
    """
    from datetime import datetime, timezone
    from pathlib import Path
    from agent.mpp_converter import is_available, xml_to_master, master_extension, diagnose

    status = diagnose()
    print(f"\nBackend status:\n{status}\n")
    if not is_available():
        print("ERROR: No conversion backend is available (neither COM nor MPXJ).")
        sys.exit(1)

    master_dir = Path(os.getenv("IMS_MASTER_DIR", "data/ims_master"))
    master_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%Mz")
    ext = master_extension()                     # ".mpp" or ".xml"
    out = master_dir / f"IMS_{ts}{ext}"

    print(f"Converting {ims_path} → {out} ...")
    actual = xml_to_master(ims_path, str(out))
    print(f"Done.  Master IMS folder: {master_dir.resolve()}")
    print(f"File:                     {Path(actual).name}")


def _run_demo_chat(
    cam_name: str,
    ims_path: str,
    cam_email: str = "",
) -> None:
    """
    Tier 3 — Teams chat interview demo.

    Starts the FastAPI server (hosts /bot/messages) in a background thread,
    registers the interview session, then blocks until the interview completes.
    """
    import threading
    import time
    import uvicorn
    from agent.dashboard.server import app
    from agent.demo_chat import run_chat_demo

    port = int(os.getenv("DASHBOARD_PORT", "9000"))

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    deadline = time.monotonic() + 5.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)

    print(f"  Bot messaging server ready on port {port}")
    print(f"  /bot/messages endpoint active")

    # Auto-detect ngrok URL and update Azure Bot Service messaging endpoint
    from agent.ngrok_updater import auto_update_from_ngrok
    auto_update_from_ngrok(port=port)
    print()

    try:
        run_chat_demo(cam_name=cam_name, ims_path=ims_path, cam_email=cam_email)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="IMS Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ims-file",
        default=os.getenv("IMS_FILE_PATH", "data/sample_ims.xml"),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--serve", action="store_true",
                       help="Start dashboard server only")
    group.add_argument("--schedule", action="store_true",
                       help="Start scheduler + dashboard (production)")
    group.add_argument("--trigger", action="store_true",
                       help="Run one cycle now and exit")
    group.add_argument("--demo", action="store_true",
                       help="Run Phase 2 simulated interview demo")
    group.add_argument("--demo-interview", action="store_true",
                       help="Tier 3: join a Teams meeting and run a live voice interview")
    group.add_argument("--demo-chat", action="store_true",
                       help="Tier 3: conduct a CAM status interview via Teams chat messages")
    group.add_argument("--cam-responder", action="store_true",
                       help="Start Graph API auto-responders for all configured fake CAM accounts")
    group.add_argument("--init-mpp", action="store_true",
                       help="One-time: convert data/sample_ims.xml → data/ims_master/ as a "
                            "timestamped .mpp to seed the master IMS folder")

    # --demo-interview arguments
    parser.add_argument("--meeting-url", default="",
                        help="Teams meeting join URL (required for --demo-interview)")
    parser.add_argument("--callback-url", default="",
                        help="Public HTTPS URL for Bot Framework webhooks, e.g. https://xxxx.ngrok.io "
                             "(required for --demo-interview)")
    parser.add_argument("--cam", default="Alice Nguyen",
                        help='CAM name to interview (default: "Alice Nguyen")')
    parser.add_argument("--cam-email", default="",
                        help="Teams UPN/email of the CAM (optional for --demo-chat; "
                             "omit to assign interview to first user who messages the bot)")

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
    elif args.demo_interview:
        if not args.meeting_url:
            print("ERROR: --meeting-url is required for --demo-interview")
            print("  Example: --meeting-url 'https://teams.microsoft.com/l/meetup-join/...'")
            sys.exit(1)
        if not args.callback_url:
            print("ERROR: --callback-url is required for --demo-interview")
            print("  Start ngrok:  ngrok http 9000")
            print("  Then use:     --callback-url https://xxxx.ngrok.io")
            sys.exit(1)
        _run_demo_interview(
            meeting_url=args.meeting_url,
            cam_name=args.cam,
            ims_path=ims_path,
            callback_url=args.callback_url,
        )
    elif args.demo_chat:
        _run_demo_chat(
            cam_name=args.cam,
            ims_path=ims_path,
            cam_email=args.cam_email,
        )
    elif args.init_mpp:
        _run_init_mpp(ims_path)
    elif args.cam_responder:
        from agent.graph_cam_responder import run_cam_responder
        explicit_cam = next((a.split("=")[1] for a in sys.argv if a.startswith("--cam=")), None)
        if explicit_cam is None and "--cam" in sys.argv:
            idx = sys.argv.index("--cam")
            explicit_cam = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        run_cam_responder(cam_filter=explicit_cam or "", ims_path=ims_path)
    else:
        if not Path(ims_path).exists():
            print(f"\nERROR: IMS file not found: {ims_path}")
            sys.exit(1)
        _run_phase1(ims_path)


if __name__ == "__main__":
    main()
