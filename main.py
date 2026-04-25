"""
IMS Agent — Phase 1 entry point.

Run with: python main.py [--ims-file PATH]

Executes the full Phase 1 pipeline:
  parse → CAM input → schedule update → critical path → SRA → synthesis → report
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging setup — must happen before any agent imports
# ---------------------------------------------------------------------------

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOGS_DIR = Path(os.getenv("LOGS_DIR", "logs"))
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s action=%(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOGS_DIR / "ims_agent.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Parse arguments and run the Phase 1 pipeline."""
    parser = argparse.ArgumentParser(description="IMS Agent — Phase 1")
    parser.add_argument(
        "--ims-file",
        default=os.getenv("IMS_FILE_PATH", "data/sample_ims.xml"),
        help="Path to the MSPDI XML schedule file",
    )
    args = parser.parse_args()

    ims_path = Path(args.ims_file)
    if not ims_path.exists():
        logger.error("ims_file_not_found path=%s", ims_path)
        print(f"\nERROR: IMS file not found: {ims_path}")
        print("Place a MSPDI XML file at that path, or set IMS_FILE_PATH in .env\n")
        sys.exit(1)

    logger.info("pipeline_start ims_file=%s", ims_path)

    from agent.file_handler import IMSFileHandler
    from agent.cam_input import run_simulated_cam_input, validate_cam_inputs
    from agent.critical_path import calculate_critical_path
    from agent.sra_runner import SRARunner
    from agent.llm_interface import LLMInterface
    from agent.report_generator import ReportGenerator

    # 1. Parse
    handler = IMSFileHandler(str(ims_path))
    tasks = handler.parse()
    logger.info("parsed task_count=%d", len(tasks))

    # 2. Simulated CAM input
    cam_inputs = run_simulated_cam_input(tasks)
    errors = validate_cam_inputs(cam_inputs)
    if errors:
        for e in errors:
            logger.warning("validation_error %s", e)
            print(f"  WARNING: {e}")

    # 3. Schedule update
    if cam_inputs:
        handler.apply_updates(cam_inputs)
        tasks = handler.parse()

    # 4. Critical path
    cp_result = calculate_critical_path(tasks)
    logger.info(
        "critical_path_complete cp_length=%d projected_finish=%s",
        len(cp_result["critical_path"]),
        cp_result.get("projected_finish"),
    )

    # 5. SRA
    sra = SRARunner(tasks)
    sra_result = sra.run()

    # 6. LLM synthesis
    llm = LLMInterface()
    synthesis = llm.synthesize(tasks, cp_result, sra_result, cam_inputs)

    # 7. Report
    rg = ReportGenerator()
    report_path = rg.generate(tasks, cp_result, sra_result, cam_inputs, synthesis)

    print(f"\n✓ Report saved to: {report_path}\n")
    logger.info("pipeline_complete report=%s", report_path)


if __name__ == "__main__":
    main()
