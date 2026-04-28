"""
CycleRunner — orchestrates one full IMS Agent status cycle.

Cycle flow:
  INITIATED    → snapshot IMS, parse tasks, build CAM directory
  INTERVIEWING → InterviewOrchestrator (simulated) or ChatInterviewManager (teams_chat)
  VALIDATING   → ScheduleValidator checks inputs
                   • Warnings  → proceed, flag in status
                   • Failures  → hold IMS write, save to approval_store, notify PM
  UPDATING     → apply inputs to IMS (only when no failures or explicitly approved)
  ANALYZING    → CPM → SRA (Monte Carlo) → deterministic health → LLM synthesis
  DISTRIBUTING → report, dashboard state, Slack + email
  COMPLETE     → persist cycle status, release lock

approval_required == True means the IMS write was held for PM approval.
The PM approves via POST /api/approvals/{cycle_id}/approve on the dashboard,
which calls CycleRunner.apply_approved(cycle_id) to write and re-analyse.
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
_IMS_EXPORTS_DIR = os.getenv("IMS_EXPORTS_DIR", "data/ims_exports")
_IMS_MASTER_DIR = os.getenv("IMS_MASTER_DIR", "data/ims_master")
_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))
# Teams chat interview timeout in seconds (default 90 min per CAM)
_TEAMS_INTERVIEW_TIMEOUT = int(os.getenv("TEAMS_INTERVIEW_TIMEOUT_SEC", "5400"))


class CycleRunner:
    """
    Runs one full IMS Agent status cycle.

    Args:
        ims_path:  Path to the IMS XML file. Defaults to IMS_FILE_PATH env var.
        simulated: Deprecated alias for mode="simulated". Ignored when mode is set.
        notify:    Whether to send Slack/email notifications.
        mode:      "simulated" — CAMSimulator (default)
                   "teams_chat" — proactive Teams Chat Bot interviews
    """

    _lock = threading.Lock()
    _active = False

    def __init__(
        self,
        ims_path: str | None = None,
        simulated: bool = True,
        notify: bool = True,
        mode: str = "simulated",
    ) -> None:
        self._ims_path = ims_path or _IMS_PATH
        self._notify = notify
        # Accept legacy `simulated` kwarg
        if not simulated and mode == "simulated":
            mode = "teams_acs"
        self._mode = mode

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
            "approval_required": False,
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

    @staticmethod
    def _export_ims_snapshot(cycle_id: str, ims_path: str) -> str:
        """Copy the updated IMS XML to ims_exports/ and produce a timestamped
        .mpp in ims_master/ (the single source of truth for the program team).

        Master folder always holds exactly ONE .mpp file whose name encodes
        the update timestamp, e.g. ``IMS_2026-04-28_1014Z.mpp``.  The
        previous file is deleted before the new one is written so the folder
        is never ambiguous.

        Returns the path of the versioned XML copy.
        """
        from agent.mpp_converter import is_available, xml_to_master, master_extension

        # ── XML exports (versioned + latest) ──────────────────────────
        exports_dir = Path(_IMS_EXPORTS_DIR)
        exports_dir.mkdir(parents=True, exist_ok=True)
        src = Path(ims_path)
        versioned_xml = exports_dir / f"{cycle_id}_ims.xml"
        shutil.copy2(src, versioned_xml)
        shutil.copy2(src, exports_dir / "latest_ims.xml")
        logger.info("action=ims_xml_exported cycle=%s path=%s", cycle_id, versioned_xml)

        # ── Master file (timestamped, replaces previous) ───────────────
        # COM backend  → writes IMS_2026-04-28_1014z.mpp  (native MS Project binary)
        # MPXJ backend → writes IMS_2026-04-28_1014z.xml  (MSPDI XML, openable by MS Project)
        master_dir = Path(_IMS_MASTER_DIR)
        master_dir.mkdir(parents=True, exist_ok=True)

        if is_available():
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%Mz")
            ext = master_extension()                          # ".mpp" or ".xml"
            new_master = master_dir / f"IMS_{ts}{ext}"
            versioned_master = exports_dir / f"{cycle_id}_ims{ext}"

            try:
                actual_path = xml_to_master(str(src), str(new_master))
                actual = Path(actual_path)
                shutil.copy2(actual, versioned_master)
                shutil.copy2(actual, exports_dir / f"latest_ims{actual.suffix}")
                logger.info("action=master_exported cycle=%s master=%s", cycle_id, actual.name)

                # Remove all old master files (.mpp and .xml) to keep folder unambiguous
                for old in list(master_dir.glob("*.mpp")) + list(master_dir.glob("*.xml")):
                    if old != actual:
                        try:
                            old.unlink()
                            logger.info("action=master_old_removed path=%s", old)
                        except OSError as exc:
                            logger.warning("action=master_remove_failed path=%s error=%s", old, exc)
            except Exception as exc:
                logger.error("action=master_export_failed cycle=%s error=%s", cycle_id, exc)
        else:
            logger.warning(
                "action=master_skip reason=no_backend_available cycle=%s — XML only", cycle_id
            )

        return str(versioned_xml)

    @classmethod
    def apply_approved(cls, cycle_id: str, approver: str = "dashboard") -> dict[str, Any]:
        """
        Apply previously-held CAM inputs after PM approval and re-run analysis.

        Called by POST /api/approvals/{cycle_id}/approve on the dashboard.
        Returns a new status dict for the approval-triggered cycle.
        """
        from agent.approval_store import load_pending, mark_approved
        from agent.file_handler import IMSFileHandler
        from agent.critical_path import calculate_critical_path
        from agent.sra_runner import SRARunner
        from agent.llm_interface import LLMInterface
        from agent.report_generator import ReportGenerator
        from agent.schedule_health import compute_health
        from agent.notifier import build_cycle_summary, send_slack, send_email
        from agent.voice_briefing import generate_briefing

        record = load_pending(cycle_id)
        if not record or record.get("status") != "pending":
            return {"error": f"No pending approval for cycle {cycle_id}"}

        ims_path = record.get("ims_path", _IMS_PATH)
        cam_inputs = record["cam_inputs"]

        mark_approved(cycle_id, approver=approver)

        handler = IMSFileHandler(ims_path)
        handler.parse()  # prime the tree
        handler.apply_updates(cam_inputs)
        tasks_updated = handler.parse()
        cls._export_ims_snapshot(cycle_id, ims_path)

        cp_result = calculate_critical_path(tasks_updated)
        sra_results = SRARunner(tasks_updated, seed=None).run()
        health, rationale = compute_health(sra_results, cp_result, tasks_updated)

        llm = LLMInterface()
        synthesis = llm.synthesize(
            tasks_updated, cp_result, sra_results, cam_inputs,
            schedule_health=health, health_rationale=rationale,
        )

        rg = ReportGenerator()
        report_path = rg.generate(
            tasks_updated, cp_result, sra_results, cam_inputs, synthesis
        )

        logger.info(
            "action=approval_applied cycle=%s health=%s report=%s",
            cycle_id, health, report_path,
        )
        return {
            "cycle_id": cycle_id,
            "phase": "complete",
            "schedule_health": health,
            "report_path": report_path,
            "approval_applied": True,
        }

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run_inner(self, cycle_id: str, status: dict) -> dict:
        from agent.file_handler import IMSFileHandler
        from agent.cam_directory import CAMDirectory
        from agent.interview_orchestrator import InterviewOrchestrator
        from agent.validation import ScheduleValidator
        from agent.critical_path import calculate_critical_path
        from agent.sra_runner import SRARunner
        from agent.llm_interface import LLMInterface
        from agent.report_generator import ReportGenerator
        from agent.notifier import build_cycle_summary, send_slack, send_email
        from agent.voice_briefing import generate_briefing
        from agent.schedule_health import compute_health

        # ── 1. Parse IMS ──────────────────────────────────────────────
        # If a master file exists, load it into the working XML so the agent
        # always starts from the program team's authoritative file.
        # .mpp  → mpp_to_xml converts it via COM or MPXJ
        # .xml  → already MSPDI format, copy directly
        from agent.mpp_converter import is_available as mpp_ok, mpp_to_xml, find_latest_master
        master_file = find_latest_master(_IMS_MASTER_DIR)
        if master_file:
            if master_file.suffix.lower() == ".mpp" and mpp_ok():
                try:
                    mpp_to_xml(str(master_file), self._ims_path)
                    logger.info(
                        "action=mpp_ingested cycle=%s src=%s dst=%s",
                        cycle_id, master_file.name, self._ims_path,
                    )
                except Exception as exc:
                    logger.error(
                        "action=mpp_ingest_failed cycle=%s error=%s — falling back to existing XML",
                        cycle_id, exc,
                    )
            elif master_file.suffix.lower() == ".xml":
                shutil.copy2(master_file, self._ims_path)
                logger.info(
                    "action=xml_master_ingested cycle=%s src=%s dst=%s",
                    cycle_id, master_file.name, self._ims_path,
                )

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

        if self._mode == "teams_chat":
            all_cam_inputs, completion_report = self._run_teams_chat_interviews(
                tasks, directory, cycle_id
            )
        else:
            from agent.voice.cam_simulator import build_atlas_personas
            personas = build_atlas_personas(tasks)
            orchestrator = InterviewOrchestrator(
                directory, personas,
                parallel=False,  # sequential in simulated mode (API rate limits)
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

        holds_dicts = [
            {"task_id": f.task_id, "cam_name": f.cam_name,
             "rule": f.rule, "detail": f.detail}
            for f in val_result.failures
        ]
        warn_dicts = [
            {"task_id": w.task_id, "cam_name": w.cam_name,
             "rule": w.rule, "detail": w.detail}
            for w in val_result.warnings
        ]
        status["validation_holds"] = holds_dicts
        status["validation_warnings"] = warn_dicts

        if holds_dicts:
            logger.warning(
                "action=validation_failures cycle=%s count=%d — holding IMS write for approval",
                cycle_id, len(holds_dicts),
            )

        # ── 6. UPDATING ───────────────────────────────────────────────
        status["phase"] = "updating"
        self._write_phase(status)

        if holds_dicts:
            # Hard failures present — hold the IMS write, require PM approval
            from agent.approval_store import save_pending
            approval_path = save_pending(
                cycle_id, all_cam_inputs, holds_dicts, self._ims_path
            )
            status["approval_required"] = True
            status["approval_path"] = str(approval_path)
            logger.info(
                "action=ims_write_held cycle=%s approval_path=%s", cycle_id, approval_path
            )
            # Analyse against the current (unmodified) IMS so the PM sees the picture
            tasks_for_analysis = tasks
        else:
            handler.apply_updates(all_cam_inputs)
            tasks_for_analysis = handler.parse()
            CycleRunner._export_ims_snapshot(cycle_id, self._ims_path)
            logger.info("action=ims_updated cycle=%s", cycle_id)

        # ── 7. ANALYZING ──────────────────────────────────────────────
        status["phase"] = "analyzing"
        self._write_phase(status)

        cp_result = calculate_critical_path(tasks_for_analysis)
        logger.info(
            "action=cpm_done cycle=%s critical=%d",
            cycle_id, len(cp_result.get("critical_path", [])),
        )

        sra_results = SRARunner(tasks_for_analysis, seed=None).run()
        logger.info("action=sra_done cycle=%s milestones=%d", cycle_id, len(sra_results))

        # Deterministic health — no LLM flip-flopping
        health, health_rationale = compute_health(sra_results, cp_result, tasks_for_analysis)
        status["schedule_health"] = health
        logger.info("action=health_computed cycle=%s health=%s rationale=%s", cycle_id, health, health_rationale)

        llm = LLMInterface()
        synthesis = llm.synthesize(
            tasks_for_analysis, cp_result, sra_results, all_cam_inputs,
            schedule_health=health,
            health_rationale=health_rationale,
        )
        logger.info("action=synthesis_done cycle=%s", cycle_id)

        # ── 8. DISTRIBUTING ───────────────────────────────────────────
        status["phase"] = "distributing"
        self._write_phase(status)

        rg = ReportGenerator()
        report_path = rg.generate(
            tasks_for_analysis, cp_result, sra_results, all_cam_inputs, synthesis
        )
        status["report_path"] = report_path
        logger.info("action=report_generated cycle=%s path=%s", cycle_id, report_path)

        self._update_dashboard_state(
            cycle_id, health, tasks_for_analysis, cp_result,
            sra_results, synthesis, all_cam_inputs, directory,
            completion_report, report_path, status,
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

            if status.get("approval_required"):
                self._notify_approval_required(cycle_id, holds_dicts)

        status["phase"] = "complete" if not status.get("approval_required") else "awaiting_approval"
        logger.info(
            "action=cycle_complete cycle=%s health=%s report=%s approval_required=%s",
            cycle_id, health, report_path, status.get("approval_required"),
        )
        return status

    # ------------------------------------------------------------------
    # Teams Chat interview mode
    # ------------------------------------------------------------------

    def _run_teams_chat_interviews(
        self,
        tasks: list[dict],
        directory: Any,
        cycle_id: str,
    ) -> tuple[list[dict], dict]:
        """
        Proactively start a Teams Chat interview for every CAM that has a
        stored session (serviceUrl + userId from a previous reactive contact).

        CAMs without a stored session fall back to the CAM simulator so the
        cycle always completes.
        """
        from agent.voice.teams_chat_connector import (
            ChatInterviewManager,
            ChatInterviewSession,
        )
        from agent.voice.cam_simulator import build_atlas_personas
        from agent.interview_orchestrator import InterviewOrchestrator
        import threading

        manager = ChatInterviewManager.get()
        all_tasks_non_ms = [t for t in tasks if not t.get("is_milestone")]

        sessions_started: list[ChatInterviewSession] = []
        cams_no_session: list[str] = []

        from agent.cam_identity import get_cam_email, is_auto_respond
        from agent.voice.teams_chat_connector import load_cam_sessions, _bf_send

        cam_sessions = load_cam_sessions()

        for cam_record in directory.get_all_cams():
            cam_name = cam_record.name if hasattr(cam_record, "name") else cam_record.get("name", "")
            cam_email = get_cam_email(cam_name).lower()

            cam_tasks = [
                t for t in all_tasks_non_ms
                if t.get("cam") == cam_name and t.get("percent_complete", 0) < 100
            ]
            if not cam_tasks:
                continue

            if cam_email and is_auto_respond(cam_name):
                stored = cam_sessions.get(cam_email, {})
                conv_id = stored.get("conversation_id", "")
                service_url = stored.get("service_url", "https://smba.trafficmanager.net/amer/")

                if not conv_id:
                    logger.warning(
                        "action=teams_chat_fallback cam=%s reason=no_conversation_id", cam_name
                    )
                    cams_no_session.append(cam_name)
                    continue

                # Create session pre-started so relay endpoint can drive it
                session = ChatInterviewSession(cam_name, cam_tasks, all_tasks=tasks, email=cam_email)
                session.service_url = service_url
                session.conversation_id = conv_id
                manager.register_by_email(cam_email, session)

                # Send opening greeting directly via Bot Framework REST
                greeting = session.start()
                ok = _bf_send(service_url, conv_id, greeting)
                if ok:
                    logger.info("action=proactive_greeting_sent cam=%s conv=%s", cam_name, conv_id[:20])
                else:
                    logger.warning("action=proactive_greeting_failed cam=%s", cam_name)

                sessions_started.append(session)
                continue

            cams_no_session.append(cam_name)
            logger.info(
                "action=teams_chat_fallback cam=%s reason=no_stored_session", cam_name
            )

        # Wait for all proactive sessions to complete
        all_cam_inputs: list[dict] = []
        responded = 0

        for session in sessions_started:
            completed = session.done.wait(timeout=_TEAMS_INTERVIEW_TIMEOUT)
            if completed:
                inputs = session.get_cam_inputs()
                all_cam_inputs.extend(inputs)
                responded += 1
                directory.record_attempt(session.cam_name, "completed")
                logger.info("action=teams_session_complete cam=%s inputs=%d", session.cam_name, len(inputs))
            else:
                directory.record_attempt(session.cam_name, "no_answer")
                logger.warning(
                    "action=teams_interview_timeout cam=%s timeout_sec=%d",
                    session.cam_name, _TEAMS_INTERVIEW_TIMEOUT,
                )

        # Simulator fallback for CAMs without stored sessions
        if cams_no_session:
            personas = build_atlas_personas(tasks)
            fallback_directory = directory.__class__()
            # Build a filtered directory with only the fallback CAMs
            fallback_directory.load_from_ims(tasks)
            # Filter to only the cams that need simulator
            from agent.interview_orchestrator import InterviewOrchestrator
            orchestrator = InterviewOrchestrator(fallback_directory, personas, parallel=False)
            sim_inputs, sim_report = orchestrator.run(tasks)
            # Filter to only the fallback CAM inputs
            fallback_inputs = [
                inp for inp in sim_inputs
                if inp.get("cam_name") in cams_no_session
            ]
            all_cam_inputs.extend(fallback_inputs)
            responded += len(set(inp.get("cam_name") for inp in fallback_inputs))

        total_cams = len(directory.get_all_cams())
        threshold_met = (responded / total_cams) >= _COMPLETION_THRESHOLD if total_cams else False

        completion_report = {
            "responded": responded,
            "total": total_cams,
            "threshold_met": threshold_met,
        }
        return all_cam_inputs, completion_report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify_approval_required(self, cycle_id: str, holds: list[dict]) -> None:
        """Send a Slack/email alert that the IMS write is held pending approval."""
        from agent.notifier import send_slack, send_email
        hold_lines = "\n".join(f"  • {h['rule']}: {h['detail']}" for h in holds[:5])
        dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:9000")
        msg = (
            f"*IMS Write Held — Approval Required*\n"
            f"Cycle `{cycle_id}` detected validation failures that require PM review "
            f"before writing to the schedule:\n{hold_lines}\n\n"
            f"Approve or reject at: {dashboard_url}/api/approvals"
        )
        summary = {"health": "HELD", "top_risks": [msg], "cams_responded": 0, "cams_total": 0}
        send_slack(summary)
        send_email(summary)

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
            import tempfile, os as _os
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
            _os.replace(tmp, path)
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
        status: dict,
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
            # Surface validation holds so the dashboard can show an alert panel
            "validation_holds": status.get("validation_holds", []),
            "validation_warnings": status.get("validation_warnings", []),
            "approval_required": status.get("approval_required", False),
            "ims_master_dir": str(Path(_IMS_MASTER_DIR).resolve()),
            "ims_exports_dir": str(Path(_IMS_EXPORTS_DIR).resolve()),
            "latest_ims_path": str((Path(_IMS_EXPORTS_DIR) / "latest_ims.xml").resolve()),
        }

        import os as _os
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        _os.replace(tmp, state_path)

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
            "approval_required": status.get("approval_required", False),
        })
        tmp_h = history_path.with_suffix(".tmp")
        tmp_h.write_text(json.dumps(history[-52:], indent=2), encoding="utf-8")
        _os.replace(tmp_h, history_path)
        logger.info("action=dashboard_updated cycle=%s", cycle_id)

    def _persist_status(self, status: dict) -> None:
        status_dir = Path(_REPORTS_DIR) / "cycles"
        status_dir.mkdir(parents=True, exist_ok=True)
        path = status_dir / f"{status['cycle_id']}_status.json"
        path.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
        logger.info("action=cycle_status_persisted path=%s", path)

    @staticmethod
    def purge_old_data(retention_days: int = _RETENTION_DAYS) -> dict[str, int]:
        """Delete cycle status JSONs and IMS snapshots older than retention_days."""
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
