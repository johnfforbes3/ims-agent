"""
CycleRunner — orchestrates one full IMS Agent status cycle.

Cycle flow:
  INITIATED  → snapshot IMS, parse tasks, build CAM directory
  INTERVIEWING → InterviewOrchestrator runs all CAM interviews
  VALIDATING  → ScheduleValidator checks inputs; logs holds but does not block
  UPDATING    → apply inputs to IMS file
  ANALYZING   → CPM → SRA (Monte Carlo) → LLM synthesis
  DISTRIBUTING → report, dashboard state, Slack + email
  COMPLETE    → persist cycle status, release lock

A threading.Lock prevents duplicate cycles within the same process.
"""

import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_IMS_PATH = os.getenv("IMS_FILE_PATH", "data/sample_ims.xml")
_REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
_DATA_DIR = "data"
_DASHBOARD_STATE_FILE = os.getenv("DASHBOARD_STATE_FILE", "data/dashboard_state.json")
_CYCLE_HISTORY_FILE = os.getenv("CYCLE_HISTORY_FILE", "data/cycle_history.json")
_COMPLETION_THRESHOLD = float(os.getenv("INTERVIEW_COMPLETION_THRESHOLD", "0.80"))
_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))


class CycleRunner:
    """
    Runs one full IMS Agent status cycle.

    Args:
        ims_path: Path to the IMS XML file. Defaults to IMS_FILE_PATH env var.
        simulated: True → use CAMSimulator; False → use TeamsACSConnector (Phase 3+).
    """

    _lock = threading.Lock()
    _active = False

    def __init__(
        self,
        ims_path: str | None = None,
        simulated: bool = True,
        notify: bool = True,
    ) -> None:
        self._ims_path = ims_path or _IMS_PATH
        self._simulated = simulated
        self._notify = notify

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """
        Execute one full cycle. Thread-safe; raises RuntimeError on duplicate.

        Returns a status dict with cycle_id, phase, health, report_path, etc.
        """
        with CycleRunner._lock:
            if CycleRunner._active:
                raise RuntimeError(
                    "A cycle is already running. Ignoring duplicate trigger."
                )
            CycleRunner._active = True

        cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        status: dict[str, Any] = {
            "cycle_id": cycle_id,
            "phase": "initiated",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "cams_total": 0,
            "cams_responded": 0,
            "tasks_captured": 0,
            "report_path": "",
            "schedule_health": "",
            "error": "",
            "validation_holds": [],
        }

        start_time = datetime.now(timezone.utc)
        try:
            status = self._run_inner(cycle_id, status)
            from agent.metrics import increment, set_value
            duration = round((datetime.now(timezone.utc) - start_time).total_seconds())
            increment("cycles_completed")
            set_value("last_cycle_id", cycle_id)
            set_value("last_cycle_duration_seconds", duration)
        except Exception as exc:
            logger.error(
                "action=cycle_failed cycle_id=%s error=%s", cycle_id, exc, exc_info=True
            )
            status["phase"] = "failed"
            status["error"] = str(exc)
            from agent.metrics import increment
            increment("cycles_failed")
        finally:
            status["completed_at"] = datetime.now(timezone.utc).isoformat()
            self._persist_status(status)
            self._purge_old_data(_RETENTION_DAYS)
            with CycleRunner._lock:
                CycleRunner._active = False

        return status

    @classmethod
    def is_active(cls) -> bool:
        return cls._active

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run_inner(self, cycle_id: str, status: dict) -> dict:
        from agent.file_handler import IMSFileHandler
        from agent.cam_directory import CAMDirectory
        from agent.voice.cam_simulator import build_atlas_personas
        from agent.interview_orchestrator import InterviewOrchestrator
        from agent.validation import ScheduleValidator
        from agent.critical_path import calculate_critical_path
        from agent.sra_runner import SRARunner
        from agent.llm_interface import LLMInterface
        from agent.report_generator import ReportGenerator
        from agent.notifier import build_cycle_summary, send_slack, send_email
        from agent.voice_briefing import generate_briefing

        # ── 1. Parse IMS ──────────────────────────────────────────────
        handler = IMSFileHandler(self._ims_path)
        tasks = handler.parse()
        logger.info("action=ims_parsed cycle=%s tasks=%d", cycle_id, len(tasks))

        # ── 2. Snapshot IMS before any writes ─────────────────────────
        self._snapshot_ims(cycle_id)

        # ── 3. CAM directory ──────────────────────────────────────────
        directory = CAMDirectory()
        directory.load_from_ims(tasks)
        cam_records = directory.get_all_cams()
        status["cams_total"] = len(cam_records)

        # ── 4. INTERVIEWING ───────────────────────────────────────────
        status["phase"] = "interviewing"
        self._write_phase(status)

        personas = build_atlas_personas(tasks)
        orchestrator = InterviewOrchestrator(
            directory, personas,
            parallel=not self._simulated,  # sequential in simulated mode (API rate limits)
        )
        all_cam_inputs, completion_report = orchestrator.run(tasks)

        status["cams_responded"] = completion_report["responded"]
        status["tasks_captured"] = len(all_cam_inputs)

        if not completion_report["threshold_met"]:
            logger.warning(
                "action=threshold_not_met cycle=%s responded=%d/%d",
                cycle_id, completion_report["responded"], completion_report["total"],
            )

        # Fall back to IMS baseline values if no inputs captured
        if not all_cam_inputs:
            logger.warning("action=no_cam_inputs cycle=%s using_baseline", cycle_id)
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
                for t in tasks if not t.get("is_milestone")
            ]

        # ── 5. VALIDATING ─────────────────────────────────────────────
        status["phase"] = "validating"
        self._write_phase(status)

        validator = ScheduleValidator()
        val_result = validator.validate(all_cam_inputs, tasks)
        if not val_result.passed:
            holds = [f.detail for f in val_result.failures]
            status["validation_holds"] = holds
            logger.warning(
                "action=validation_holds cycle=%s count=%d", cycle_id, len(holds)
            )
            # Log but do not block — human can audit the persisted status

        # ── 6. UPDATING ───────────────────────────────────────────────
        status["phase"] = "updating"
        self._write_phase(status)

        handler.apply_updates(all_cam_inputs)
        tasks_updated = handler.parse()
        logger.info("action=ims_updated cycle=%s", cycle_id)

        # ── 7. ANALYZING ──────────────────────────────────────────────
        status["phase"] = "analyzing"
        self._write_phase(status)

        cp_result = calculate_critical_path(tasks_updated)
        logger.info(
            "action=cpm_done cycle=%s critical=%d",
            cycle_id, len(cp_result.get("critical_path", [])),
        )

        sra = SRARunner(tasks_updated, seed=None)
        sra_results = sra.run()
        logger.info("action=sra_done cycle=%s milestones=%d", cycle_id, len(sra_results))

        llm = LLMInterface()
        synthesis = llm.synthesize(tasks_updated, cp_result, sra_results, all_cam_inputs)
        health = synthesis.get("schedule_health", "UNKNOWN")
        status["schedule_health"] = health
        logger.info("action=synthesis_done cycle=%s health=%s", cycle_id, health)

        # ── 8. DISTRIBUTING ───────────────────────────────────────────
        status["phase"] = "distributing"
        self._write_phase(status)

        rg = ReportGenerator()
        report_path = rg.generate(
            tasks_updated, cp_result, sra_results, all_cam_inputs, synthesis
        )
        status["report_path"] = report_path
        logger.info("action=report_generated cycle=%s path=%s", cycle_id, report_path)

        self._update_dashboard_state(
            cycle_id, health, tasks_updated, cp_result,
            sra_results, synthesis, all_cam_inputs, directory,
            completion_report, report_path,
        )

        if self._notify:
            top_risks_text = synthesis.get("top_risks", "")
            top_risks_list = [
                line.lstrip("0123456789. ").strip()
                for line in top_risks_text.splitlines()
                if line.strip()
            ][:3]
            milestones_at_risk = [
                m for m in sra_results
                if m.get("risk_level") in ("HIGH", "MEDIUM")
            ]
            briefing_path = generate_briefing(synthesis, cycle_id)
            summary = build_cycle_summary(
                health=health,
                top_risks=top_risks_list,
                milestones_at_risk=milestones_at_risk,
                cams_responded=completion_report["responded"],
                cams_total=completion_report["total"],
                report_path=report_path,
                briefing_path=briefing_path,
            )
            send_slack(summary)
            send_email(summary)

        status["phase"] = "complete"
        logger.info(
            "action=cycle_complete cycle=%s health=%s report=%s",
            cycle_id, health, report_path,
        )
        return status

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _snapshot_ims(self, cycle_id: str) -> None:
        src = Path(self._ims_path)
        if not src.exists():
            return
        snap_dir = Path(_DATA_DIR) / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        dest = snap_dir / f"{cycle_id}_{src.name}"
        shutil.copy2(src, dest)
        logger.info("action=ims_snapshot cycle=%s dest=%s", cycle_id, dest)

    def _write_phase(self, status: dict) -> None:
        """Write current phase to dashboard state so the UI shows live progress."""
        path = Path(_DASHBOARD_STATE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: dict = {}
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
            existing["current_cycle"] = status
            path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.warning("action=phase_write_error error=%s", exc)

    def _update_dashboard_state(
        self,
        cycle_id: str,
        health: str,
        tasks: list,
        cp_result: dict,
        sra_results: list,
        synthesis: dict,
        cam_inputs: list,
        directory: Any,
        completion_report: dict,
        report_path: str,
    ) -> None:
        state_path = Path(_DASHBOARD_STATE_FILE)
        history_path = Path(_CYCLE_HISTORY_FILE)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        tasks_behind = [
            {
                "task_id": inp["task_id"],
                "cam_name": inp.get("cam_name", ""),
                "percent_complete": inp.get("percent_complete"),
                "blocker": (inp.get("blocker") or "")[:120],
            }
            for inp in cam_inputs
            if inp.get("percent_complete") is not None and inp.get("blocker")
        ]

        call_status = directory.get_call_status_summary()

        state = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "cycle_id": cycle_id,
            "schedule_health": health,
            "critical_path_task_ids": cp_result.get("critical_path", []),
            "milestones": sra_results,
            "top_risks": synthesis.get("top_risks", ""),
            "recommended_actions": synthesis.get("recommended_actions", ""),
            "narrative": synthesis.get("narrative", ""),
            "tasks_behind": tasks_behind,
            "cam_response_status": {
                cam: {
                    "responded": data.get("completed", False),
                    "attempts": data.get("attempts", 0),
                    "last_outcome": data.get("last_outcome", ""),
                }
                for cam, data in call_status.items()
            },
            "completion_report": completion_report,
            "report_path": report_path,
        }

        state_path.write_text(
            json.dumps(state, indent=2, default=str), encoding="utf-8"
        )

        # Append to rolling history (keep 1 year = 52 weekly cycles)
        history: list = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append({
            "cycle_id": cycle_id,
            "timestamp": state["last_updated"],
            "schedule_health": health,
            "cams_responded": completion_report["responded"],
            "cams_total": completion_report["total"],
        })
        history_path.write_text(
            json.dumps(history[-52:], indent=2), encoding="utf-8"
        )
        logger.info("action=dashboard_updated cycle=%s", cycle_id)

    def _persist_status(self, status: dict) -> None:
        status_dir = Path(_REPORTS_DIR) / "cycles"
        status_dir.mkdir(parents=True, exist_ok=True)
        path = status_dir / f"{status['cycle_id']}_status.json"
        path.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
        logger.info("action=cycle_status_persisted path=%s", path)

    @staticmethod
    def purge_old_data(retention_days: int = _RETENTION_DAYS) -> dict[str, int]:
        """Delete cycle status JSONs and IMS snapshots older than retention_days.

        Returns counts of deleted files per category.
        """
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted = {"cycle_status": 0, "snapshots": 0}

        status_dir = Path(_REPORTS_DIR) / "cycles"
        if status_dir.exists():
            for f in status_dir.glob("*_status.json"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink()
                    deleted["cycle_status"] += 1

        snap_dir = Path(_DATA_DIR) / "snapshots"
        if snap_dir.exists():
            for f in snap_dir.glob("*.xml"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink()
                    deleted["snapshots"] += 1

        if any(deleted.values()):
            logger.info("action=data_purge retention_days=%d deleted=%s", retention_days, deleted)
        return deleted

    def _purge_old_data(self, retention_days: int) -> None:
        try:
            CycleRunner.purge_old_data(retention_days)
        except Exception as exc:
            logger.warning("action=purge_error error=%s", exc)
