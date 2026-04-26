"""
CAM Directory — registry, scheduling logic, and call status tracking.

Manages:
  - CAM contact information (name, Teams ID, email, timezone)
  - Task assignments derived from the IMS
  - Call history: attempts, outcomes, retry logic
  - Scheduling: business hours check, retry intervals, escalation rules
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_DIRECTORY_PATH = os.getenv("CAM_DIRECTORY_PATH", "data/cam_directory.json")
_MAX_RETRIES = int(os.getenv("INTERVIEW_MAX_RETRIES", "3"))
_RETRY_INTERVAL_HOURS = 2


@dataclass
class CAMRecord:
    """Contact and assignment record for a single CAM."""
    cam_id: str
    name: str
    email: str
    teams_user_id: str
    phone: str
    timezone: str                    # IANA timezone name, e.g. "America/New_York"
    business_hours_start: int = 9    # Hour (24h), local time
    business_hours_end: int = 17
    task_ids: list[str] = field(default_factory=list)


@dataclass
class CallRecord:
    """Record of a single call attempt."""
    cam_id: str
    attempt_number: int
    timestamp: str
    outcome: str           # "answered" | "no_answer" | "completed" | "escalated"
    transcript: list[dict[str, str]] = field(default_factory=list)
    structured_data: list[dict[str, Any]] = field(default_factory=list)


class CAMDirectory:
    """
    Registry of all CAMs for a program cycle.

    Loaded either from a JSON file (cam_directory.json) or derived
    automatically from the parsed IMS task list.
    """

    def __init__(self) -> None:
        self._cams: dict[str, CAMRecord] = {}
        self._call_history: dict[str, list[CallRecord]] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_file(self, path: str | None = None) -> None:
        """
        Load CAM records from a JSON file.

        Args:
            path: Path to cam_directory.json. Defaults to CAM_DIRECTORY_PATH env var.
        """
        p = Path(path or _DIRECTORY_PATH)
        if not p.exists():
            raise FileNotFoundError(f"CAM directory file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        for entry in data:
            rec = CAMRecord(
                cam_id=entry["cam_id"],
                name=entry["name"],
                email=entry.get("email", ""),
                teams_user_id=entry.get("teams_user_id", ""),
                phone=entry.get("phone", ""),
                timezone=entry.get("timezone", "America/New_York"),
                business_hours_start=entry.get("business_hours_start", 9),
                business_hours_end=entry.get("business_hours_end", 17),
                task_ids=entry.get("task_ids", []),
            )
            self._cams[rec.name] = rec
        logger.info("action=directory_loaded source=file cams=%d", len(self._cams))

    def load_from_ims(self, tasks: list[dict[str, Any]]) -> None:
        """
        Derive CAM records from the parsed IMS task list.

        Creates a minimal CAMRecord for each unique CAM name found in tasks.
        Contact details (email, Teams ID, phone) are left blank and can be
        populated later from cam_directory.json.

        Args:
            tasks: Parsed task list from IMSFileHandler.parse().
        """
        cam_tasks: dict[str, list[str]] = {}
        for t in tasks:
            cam = t.get("cam", "Unassigned")
            if cam != "Unassigned":
                cam_tasks.setdefault(cam, []).append(t["task_id"])

        for idx, (cam_name, task_ids) in enumerate(sorted(cam_tasks.items())):
            slug = cam_name.lower().replace(" ", "_")
            rec = CAMRecord(
                cam_id=f"cam_{idx+1:02d}_{slug}",
                name=cam_name,
                email=f"{slug}@example.com",
                teams_user_id="",
                phone="",
                timezone="America/New_York",
                task_ids=task_ids,
            )
            self._cams[cam_name] = rec

        logger.info("action=directory_loaded source=ims cams=%d", len(self._cams))

    def save_to_file(self, path: str | None = None) -> str:
        """Persist the current directory to JSON."""
        p = Path(path or _DIRECTORY_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "cam_id": r.cam_id,
                "name": r.name,
                "email": r.email,
                "teams_user_id": r.teams_user_id,
                "phone": r.phone,
                "timezone": r.timezone,
                "business_hours_start": r.business_hours_start,
                "business_hours_end": r.business_hours_end,
                "task_ids": r.task_ids,
            }
            for r in self._cams.values()
        ]
        p.write_text(json.dumps(records, indent=2), encoding="utf-8")
        logger.info("action=directory_saved path=%s", p)
        return str(p)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_cam(self, name: str) -> CAMRecord:
        """Return a CAMRecord by name. Raises KeyError if not found."""
        if name not in self._cams:
            raise KeyError(f"CAM '{name}' not found in directory.")
        return self._cams[name]

    def get_all_cams(self) -> list[CAMRecord]:
        """Return all CAM records."""
        return list(self._cams.values())

    def get_tasks_for_cam(
        self, cam_name: str, all_tasks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return the subset of tasks assigned to this CAM."""
        rec = self.get_cam(cam_name)
        id_set = set(rec.task_ids)
        return [t for t in all_tasks if t["task_id"] in id_set]

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def can_call_now(self, cam: CAMRecord) -> bool:
        """
        Return True if the current time is within the CAM's business hours.

        Uses UTC + a fixed offset approximation since pytz may not be installed.
        For production, replace with proper timezone handling.
        """
        now_hour = datetime.now().hour  # local machine time
        return cam.business_hours_start <= now_hour < cam.business_hours_end

    def should_retry(self, cam_name: str) -> bool:
        """Return True if this CAM has retries remaining and enough time has passed."""
        history = self._call_history.get(cam_name, [])
        incomplete = [r for r in history if r.outcome == "no_answer"]
        if len(incomplete) >= _MAX_RETRIES:
            return False
        if not incomplete:
            return True
        last_attempt_ts = incomplete[-1].timestamp
        last_dt = datetime.fromisoformat(last_attempt_ts)
        hours_since = (datetime.now() - last_dt).total_seconds() / 3600
        return hours_since >= _RETRY_INTERVAL_HOURS

    def should_escalate(self, cam_name: str) -> bool:
        """Return True if retry limit is exhausted without a completed call."""
        history = self._call_history.get(cam_name, [])
        completed = any(r.outcome == "completed" for r in history)
        if completed:
            return False
        no_answers = sum(1 for r in history if r.outcome == "no_answer")
        return no_answers >= _MAX_RETRIES

    # ------------------------------------------------------------------
    # Call history
    # ------------------------------------------------------------------

    def record_attempt(
        self,
        cam_name: str,
        outcome: str,
        transcript: list[dict[str, str]] | None = None,
        structured_data: list[dict[str, Any]] | None = None,
    ) -> CallRecord:
        """
        Record the outcome of a call attempt.

        Args:
            cam_name: The CAM's name.
            outcome: "answered" | "no_answer" | "completed" | "escalated"
            transcript: Optional conversation transcript.
            structured_data: Optional extracted structured data.

        Returns:
            The created CallRecord.
        """
        history = self._call_history.setdefault(cam_name, [])
        record = CallRecord(
            cam_id=self._cams[cam_name].cam_id if cam_name in self._cams else cam_name,
            attempt_number=len(history) + 1,
            timestamp=datetime.now().isoformat(),
            outcome=outcome,
            transcript=transcript or [],
            structured_data=structured_data or [],
        )
        history.append(record)
        logger.info("action=call_recorded cam=%s attempt=%d outcome=%s",
                    cam_name, record.attempt_number, outcome)
        return record

    def get_call_status_summary(self) -> dict[str, dict[str, Any]]:
        """Return a per-CAM status summary for the current cycle."""
        summary: dict[str, dict[str, Any]] = {}
        for cam_name in self._cams:
            history = self._call_history.get(cam_name, [])
            last = history[-1] if history else None
            summary[cam_name] = {
                "attempts": len(history),
                "last_outcome": last.outcome if last else "not_contacted",
                "completed": any(r.outcome == "completed" for r in history),
                "escalated": self.should_escalate(cam_name),
            }
        return summary
