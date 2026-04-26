"""
Interview orchestrator — runs CAM interviews for a full cycle.

Supports sequential or parallel (ThreadPoolExecutor) execution.
Tracks completion rate against a configurable threshold and returns
a completion report for the cycle runner.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = int(os.getenv("INTERVIEW_MAX_CONCURRENT", "3"))
_COMPLETION_THRESHOLD = float(os.getenv("INTERVIEW_COMPLETION_THRESHOLD", "0.80"))
_TERMINAL_STATES = {"complete", "aborted", "no_response"}
_MAX_TURNS = 60


class InterviewOrchestrator:
    """
    Manages CAM interviews across a full reporting cycle.

    Args:
        directory: CAMDirectory instance (already loaded from IMS).
        personas: Dict of {cam_name: CAMPersona} from build_atlas_personas().
        parallel: If True, run interviews concurrently up to INTERVIEW_MAX_CONCURRENT.
    """

    def __init__(
        self,
        directory: Any,
        personas: dict[str, Any],
        parallel: bool = True,
    ) -> None:
        self._directory = directory
        self._personas = personas
        self._parallel = parallel

    def run(
        self, tasks: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Interview all available CAMs and return (cam_inputs, completion_report).

        completion_report keys:
            total, responded, threshold, threshold_met, skipped, failed
        """
        cam_records = self._directory.get_all_cams()
        cam_work: list[tuple[str, list[dict], Any]] = []

        for rec in cam_records:
            persona = self._personas.get(rec.name)
            if persona is None:
                logger.warning("action=no_persona cam=%s skipping", rec.name)
                continue
            cam_tasks = [
                t for t in self._directory.get_tasks_for_cam(rec.name, tasks)
                if not t.get("is_milestone")
            ]
            if not cam_tasks:
                continue
            cam_work.append((rec.name, cam_tasks, persona))

        all_inputs: list[dict] = []
        responded: list[str] = []
        failed: list[str] = []

        if self._parallel and len(cam_work) > 1:
            all_inputs, responded, failed = self._run_parallel(cam_work)
        else:
            all_inputs, responded, failed = self._run_sequential(cam_work)

        total = len(cam_work)
        all_cam_names = {c[0] for c in cam_work}
        skipped = [r.name for r in cam_records if r.name not in all_cam_names]

        completion_report = {
            "total": total,
            "responded": len(responded),
            "threshold": _COMPLETION_THRESHOLD,
            "threshold_met": total == 0 or (len(responded) / total) >= _COMPLETION_THRESHOLD,
            "skipped": skipped,
            "failed": failed,
        }

        logger.info(
            "action=orchestration_complete total=%d responded=%d threshold_met=%s",
            total, len(responded), completion_report["threshold_met"],
        )
        return all_inputs, completion_report

    # ------------------------------------------------------------------
    # Internal runners
    # ------------------------------------------------------------------

    def _run_sequential(
        self, cam_work: list[tuple]
    ) -> tuple[list[dict], list[str], list[str]]:
        all_inputs, responded, failed = [], [], []
        for cam_name, cam_tasks, persona in cam_work:
            result = self._interview_one(cam_name, cam_tasks, persona)
            if result is not None:
                all_inputs.extend(result)
                responded.append(cam_name)
            else:
                failed.append(cam_name)
        return all_inputs, responded, failed

    def _run_parallel(
        self, cam_work: list[tuple]
    ) -> tuple[list[dict], list[str], list[str]]:
        all_inputs, responded, failed = [], [], []
        workers = min(_MAX_CONCURRENT, len(cam_work))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._interview_one, cam_name, cam_tasks, persona): cam_name
                for cam_name, cam_tasks, persona in cam_work
            }
            for future in as_completed(futures):
                cam_name = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        all_inputs.extend(result)
                        responded.append(cam_name)
                    else:
                        failed.append(cam_name)
                except Exception as exc:
                    logger.error(
                        "action=interview_exception cam=%s error=%s", cam_name, exc
                    )
                    failed.append(cam_name)
        return all_inputs, responded, failed

    def _interview_one(
        self,
        cam_name: str,
        cam_tasks: list[dict],
        persona: Any,
    ) -> list[dict] | None:
        from agent.voice.interview_agent import InterviewAgent
        from agent.voice.cam_simulator import CAMSimulator

        simulator = CAMSimulator(persona)
        agent = InterviewAgent(cam_name, cam_tasks)

        turn = agent.start()
        turns_taken = 0

        while agent.state.value not in _TERMINAL_STATES and turns_taken < _MAX_TURNS:
            cam_response = simulator.respond(turn.text)
            turn = agent.process(cam_response)
            turns_taken += 1

        if turns_taken >= _MAX_TURNS:
            logger.warning("action=interview_safety_limit cam=%s", cam_name)

        result_dicts = [r.to_cam_input_dict() for r in agent.results]
        transcript = [{"speaker": t.speaker, "text": t.text} for t in agent.transcript]

        outcome = "completed" if result_dicts else "no_answer"
        self._directory.record_attempt(
            cam_name, outcome,
            transcript=transcript,
            structured_data=result_dicts,
        )
        logger.info(
            "action=interview_done cam=%s state=%s tasks=%d",
            cam_name, agent.state.value, len(result_dicts),
        )
        return result_dicts if result_dicts else None
