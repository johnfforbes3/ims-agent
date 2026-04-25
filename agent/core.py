"""
IMS Agent core orchestration module.

Coordinates the full Phase 1 pipeline:
parse → simulate CAM input → update schedule → critical path →
SRA → LLM synthesis → report generation.
"""

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def run_phase1_pipeline(ims_file_path: str) -> str:
    """
    Execute the full Phase 1 pipeline end-to-end.

    Args:
        ims_file_path: Path to the MSPDI XML file.

    Returns:
        Path to the generated report file.
    """
    from agent.file_handler import IMSFileHandler
    from agent.sra_runner import SRARunner
    from agent.report_generator import ReportGenerator
    from agent.llm_interface import LLMInterface

    logger.info("action=pipeline_start file=%s", ims_file_path)

    handler = IMSFileHandler(ims_file_path)
    tasks = handler.parse()
    logger.info("action=parse_complete task_count=%d", len(tasks))

    cam_inputs = _simulate_cam_input(tasks)
    logger.info("action=cam_input_complete cam_count=%d", len(cam_inputs))

    handler.apply_updates(cam_inputs)
    logger.info("action=schedule_updated")

    tasks_updated = handler.parse()
    cp_result = _calculate_critical_path(tasks_updated)
    logger.info("action=critical_path_complete path_length=%d", len(cp_result["critical_path"]))

    sra = SRARunner(tasks_updated)
    sra_result = sra.run()
    logger.info("action=sra_complete milestones=%d", len(sra_result))

    llm = LLMInterface()
    synthesis = llm.synthesize(tasks_updated, cp_result, sra_result, cam_inputs)
    logger.info("action=synthesis_complete")

    rg = ReportGenerator()
    report_path = rg.generate(tasks_updated, cp_result, sra_result, cam_inputs, synthesis)
    logger.info("action=report_generated path=%s", report_path)

    return report_path


def _simulate_cam_input(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Delegate to the interactive CAM input CLI."""
    from agent.cam_input import run_simulated_cam_input
    return run_simulated_cam_input(tasks)


def _calculate_critical_path(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Delegate to the CPM engine."""
    from agent.critical_path import calculate_critical_path
    return calculate_critical_path(tasks)
