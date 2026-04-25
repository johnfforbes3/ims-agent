"""
Demo runner — Phase 1 end-to-end pipeline with pre-built CAM inputs.

Bypasses the interactive CLI (main.py) so the full pipeline can run
non-interactively. Uses realistic CAM status data for the ATLAS program.

Run with: python run_demo.py
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Resolve .env relative to this script so it works regardless of CWD
load_dotenv(Path(__file__).parent / ".env", override=True)

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
# Pre-built CAM inputs — realistic status for ATLAS radar program, 2026-04-25
# Covers tasks that are active or recently completed.
# Behind-schedule tasks include blocker and risk data.
# ---------------------------------------------------------------------------

_TS = datetime.now().isoformat()

CAM_INPUTS = [
    # --- Alice Nguyen (Systems Engineering) ---
    # SE-02 System Design Document: expected ~77%, reporting 85% (ahead)
    {"task_id": "2",  "cam_name": "Alice Nguyen", "percent_complete": 85,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SE-03 ICDs: expected ~82%, reporting 60% (behind — waiting on HW inputs)
    {"task_id": "3",  "cam_name": "Alice Nguyen", "percent_complete": 60,
     "blocker": "Waiting on final HW-01 RF specs from Bob Martinez before ICD sections 4-6 can be drafted.",
     "risk_flag": True,
     "risk_description": "ICD delay will push SE-05 RTM and SE-06 PDR package. Estimate 2-week slip to PDR if not resolved by 2026-05-01.",
     "timestamp": _TS},
    # SE-05 RTM: expected ~8%, reporting 40% (ahead)
    {"task_id": "5",  "cam_name": "Alice Nguyen", "percent_complete": 40,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SE-06 PDR Package: just started, 10% (on track)
    {"task_id": "6",  "cam_name": "Alice Nguyen", "percent_complete": 10,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SE-07 System Safety: 5% (on track — just kicked off)
    {"task_id": "7",  "cam_name": "Alice Nguyen", "percent_complete": 5,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SE-08 Reliability: 0% — task just started but SE-03 dependency is slipping
    {"task_id": "8",  "cam_name": "Alice Nguyen", "percent_complete": 0,
     "blocker": "Cannot begin until ICDs section 4 is approved (blocked on SE-03).",
     "risk_flag": True,
     "risk_description": "Reliability analysis start may slip 2 weeks, affecting SE-09 CDR Package.",
     "timestamp": _TS},

    # --- Bob Martinez (Hardware Development) ---
    # HW-01 RF Front End Design: expected ~82%, reporting 75% (slightly behind)
    {"task_id": "11", "cam_name": "Bob Martinez", "percent_complete": 75,
     "blocker": "RF simulation runs taking longer than planned — tools license contention on the lab cluster.",
     "risk_flag": True,
     "risk_description": "If simulation not done by 2026-05-02, HW-05 fabrication start slips, which pushes HW-08 unit testing and the hardware acceptance date.",
     "timestamp": _TS},
    # HW-02 Signal Processing Board: expected ~76%, reporting 55% (behind)
    {"task_id": "12", "cam_name": "Bob Martinez", "percent_complete": 55,
     "blocker": "Key engineer on medical leave for 3 weeks. Partial coverage arranged but pace is slower.",
     "risk_flag": True,
     "risk_description": "Board design at risk of not completing before HW-06 fab window. Could slip CDR if board is not ready for CDR package review.",
     "timestamp": _TS},
    # HW-04 Antenna Array Design: expected ~73%, reporting 45% (behind)
    {"task_id": "14", "cam_name": "Bob Martinez", "percent_complete": 45,
     "blocker": "Waiting on updated antenna aperture requirements from SE-03 ICD. Cannot finalize design without confirmed specs.",
     "risk_flag": True,
     "risk_description": "Antenna design is on the longest hardware path. A 3-week slip here delays HW-07 fabrication (480h task) and pushes hardware acceptance past 2026-10-02 baseline.",
     "timestamp": _TS},
    # HW-05, 16, 17: not started (correct, predecessors not complete)
    {"task_id": "15", "cam_name": "Bob Martinez", "percent_complete": 0,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    {"task_id": "16", "cam_name": "Bob Martinez", "percent_complete": 0,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},

    # --- Carol Smith (Software Development) ---
    # SW-02 Architecture: expected ~55%, reporting 70% (ahead — good news)
    {"task_id": "22", "cam_name": "Carol Smith", "percent_complete": 70,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SW-03 Signal Processing Algorithms: expected ~15%, reporting 30% (ahead)
    {"task_id": "23", "cam_name": "Carol Smith", "percent_complete": 30,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SW-04 Tracking Algorithm: expected ~12%, reporting 20% (on track)
    {"task_id": "24", "cam_name": "Carol Smith", "percent_complete": 20,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # SW-06 Database: expected ~5%, reporting 15% (ahead)
    {"task_id": "26", "cam_name": "Carol Smith", "percent_complete": 15,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},

    # --- David Lee (Integration & Test) ---
    # IT-01 Integration Test Plan: 0% (correct, predecessor not done)
    {"task_id": "31", "cam_name": "David Lee", "percent_complete": 0,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},

    # --- Eva Johnson (Program Management) ---
    # PM-03 Monthly Status: expected ~28%, reporting 28% (on track)
    {"task_id": "43", "cam_name": "Eva Johnson", "percent_complete": 28,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # PM-04 EVM: expected ~28%, reporting 28% (on track)
    {"task_id": "44", "cam_name": "Eva Johnson", "percent_complete": 28,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
    # PM-06 Subcontractor Mgmt: expected ~15%, reporting 25% (ahead)
    {"task_id": "46", "cam_name": "Eva Johnson", "percent_complete": 25,
     "blocker": "", "risk_flag": False, "risk_description": "", "timestamp": _TS},
]


def main() -> None:
    """Run the full Phase 1 pipeline with pre-built CAM inputs."""
    from agent.file_handler import IMSFileHandler
    from agent.cam_input import validate_cam_inputs
    from agent.critical_path import calculate_critical_path
    from agent.sra_runner import SRARunner
    from agent.llm_interface import LLMInterface
    from agent.report_generator import ReportGenerator

    ims_path = os.getenv("IMS_FILE_PATH", "data/sample_ims.xml")
    logger.info("Demo pipeline starting — ims_file=%s", ims_path)

    # 1. Parse
    handler = IMSFileHandler(ims_path)
    tasks = handler.parse()
    logger.info("Parsed %d tasks", len(tasks))

    # 2. Validate pre-built CAM inputs
    errors = validate_cam_inputs(CAM_INPUTS)
    if errors:
        for e in errors:
            logger.error("CAM input validation error: %s", e)
        sys.exit(1)
    logger.info("CAM inputs validated — %d updates", len(CAM_INPUTS))

    # 3. Apply updates
    handler.apply_updates(CAM_INPUTS)
    tasks = handler.parse()
    logger.info("Schedule updated and re-parsed")

    # 4. Critical path
    cp_result = calculate_critical_path(tasks)
    logger.info("Critical path: %d tasks, projected finish: %s",
                len(cp_result["critical_path"]), cp_result.get("projected_finish"))

    # 5. SRA
    sra = SRARunner(tasks, seed=42)
    sra_result = sra.run()
    high_risk = [r for r in sra_result if r["risk_level"] == "HIGH"]
    logger.info("SRA complete — %d milestones, %d HIGH risk", len(sra_result), len(high_risk))

    # 6. LLM synthesis
    logger.info("Calling Claude claude-sonnet-4-6 for synthesis...")
    llm = LLMInterface()
    synthesis = llm.synthesize(tasks, cp_result, sra_result, CAM_INPUTS)
    logger.info("Synthesis complete — health=%s", synthesis.get("schedule_health", "?"))

    # 7. Report
    rg = ReportGenerator()
    report_path = rg.generate(tasks, cp_result, sra_result, CAM_INPUTS, synthesis)

    print(f"\n{'='*60}")
    print(f"  IMS Agent — Phase 1 Demo Complete")
    print(f"{'='*60}")
    print(f"  Report: {report_path}")
    print(f"  Health: {synthesis.get('schedule_health', 'UNKNOWN')}")
    print(f"  Critical path tasks: {len(cp_result['critical_path'])}")
    print(f"  HIGH-risk milestones: {len(high_risk)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
