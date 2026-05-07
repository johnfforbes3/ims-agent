"""
IMS file handler — reads and writes MSPDI XML schedule files.

Handles parsing Microsoft Project Data Interchange (MSPDI) XML files into
Python data structures, and writing updated percent-complete values and
CAM notes back to the XML.
"""

import logging
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# MSPDI XML namespace
_NS = "http://schemas.microsoft.com/project"
_NSM = {"msp": _NS}


def _tag(local: str) -> str:
    """Return a fully-qualified MSPDI tag name."""
    return f"{{{_NS}}}{local}"


class IMSFileHandler:
    """Parses and updates an MSPDI XML schedule file."""

    def __init__(self, file_path: str) -> None:
        """
        Args:
            file_path: Path to the MSPDI XML file.
        """
        self.file_path = Path(file_path)
        self._tree: ET.ElementTree | None = None
        self._root: ET.Element | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self) -> list[dict[str, Any]]:
        """
        Parse the MSPDI XML file and return a list of task dicts.

        Each dict contains:
            task_id, name, start, finish, percent_complete,
            predecessors, cam, baseline_start, baseline_finish, duration_days
        """
        self._load()
        tasks_el = self._root.find(_tag("Tasks"))
        if tasks_el is None:
            logger.warning("action=parse_warning msg=no_Tasks_element")
            return []

        resources = self._parse_resources()
        assignments = self._parse_assignments()

        tasks: list[dict[str, Any]] = []
        for task_el in tasks_el.findall(_tag("Task")):
            task = self._parse_task(task_el, resources, assignments)
            if task is not None:
                tasks.append(task)

        logger.info("action=parse_complete file=%s task_count=%d", self.file_path, len(tasks))
        return tasks

    def apply_updates(self, cam_inputs: list[dict[str, Any]]) -> None:
        """
        Write CAM-provided percent-complete values and notes back to the XML.

        Args:
            cam_inputs: List of dicts from the CAM input stage, each containing
                        task_id, percent_complete, blocker, risk_flag,
                        risk_description, timestamp.
        """
        if not cam_inputs:
            logger.info("action=apply_updates msg=no_updates_provided")
            return

        self._load()
        updates_by_id = {str(c["task_id"]): c for c in cam_inputs}
        tasks_el = self._root.find(_tag("Tasks"))

        for task_el in tasks_el.findall(_tag("Task")):
            uid_el = task_el.find(_tag("UID"))
            if uid_el is None:
                continue
            task_id = uid_el.text
            if task_id not in updates_by_id:
                continue

            update = updates_by_id[task_id]
            old_pct = self._get_text(task_el, "PercentComplete", "0")

            # Write percent complete
            pct_el = task_el.find(_tag("PercentComplete"))
            if pct_el is None:
                pct_el = ET.SubElement(task_el, _tag("PercentComplete"))
            pct_el.text = str(update["percent_complete"])

            # Write notes
            notes_parts = []
            if update.get("blocker"):
                notes_parts.append(f"BLOCKER: {update['blocker']}")
            if update.get("risk_flag"):
                notes_parts.append(f"RISK: {update.get('risk_description', 'flagged')}")
            if notes_parts:
                notes_el = task_el.find(_tag("Notes"))
                if notes_el is None:
                    notes_el = ET.SubElement(task_el, _tag("Notes"))
                notes_el.text = " | ".join(notes_parts)

            logger.info(
                "action=task_updated task_id=%s field=PercentComplete "
                "old_value=%s new_value=%s timestamp=%s",
                task_id,
                old_pct,
                update["percent_complete"],
                update.get("timestamp", ""),
            )

        # Write to a temp file then atomically replace the authoritative IMS file.
        # os.replace is atomic on POSIX and atomic on Windows when src/dst share a volume.
        # This keeps the original path as the single source of truth across all cycles.
        import os
        tmp_path = self.file_path.with_suffix(".tmp")
        self._tree.write(str(tmp_path), xml_declaration=True, encoding="utf-8")
        os.replace(tmp_path, self.file_path)
        # Reset the parsed tree so the next parse() re-reads the updated file
        self._tree = None
        self._root = None
        logger.info("action=file_written path=%s", self.file_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load the XML tree if not already loaded."""
        if self._tree is not None:
            return
        if not self.file_path.exists():
            raise FileNotFoundError(f"IMS file not found: {self.file_path}")
        ET.register_namespace("", _NS)
        try:
            self._tree = ET.parse(str(self.file_path))
        except ET.ParseError as exc:
            # §11.2 — surface a clear, actionable message instead of a raw traceback.
            # The raw ET.ParseError includes a line/column reference which we preserve.
            raise ValueError(
                f"IMS file is not valid XML and cannot be parsed: {self.file_path}\n"
                f"  XML error: {exc}\n"
                f"  Check that the file is a valid MSPDI export and is not corrupted."
            ) from exc
        self._root = self._tree.getroot()
        logger.info("action=file_loaded path=%s", self.file_path)

    def _parse_resources(self) -> dict[str, str]:
        """Return a mapping of resource UID → resource Name."""
        resources_el = self._root.find(_tag("Resources"))
        if resources_el is None:
            return {}
        return {
            self._get_text(r, "UID"): self._get_text(r, "Name")
            for r in resources_el.findall(_tag("Resource"))
        }

    def _parse_assignments(self) -> dict[str, str]:
        """Return a mapping of task UID → resource Name (CAM)."""
        assignments_el = self._root.find(_tag("Assignments"))
        if assignments_el is None:
            return {}
        resources = self._parse_resources()
        result: dict[str, str] = {}
        for a in assignments_el.findall(_tag("Assignment")):
            task_uid = self._get_text(a, "TaskUID")
            res_uid = self._get_text(a, "ResourceUID")
            if task_uid and res_uid and res_uid in resources:
                result[task_uid] = resources[res_uid]
        return result

    def _parse_task(
        self,
        task_el: ET.Element,
        resources: dict[str, str],
        assignments: dict[str, str],
    ) -> dict[str, Any] | None:
        """Parse a single Task element into a dict."""
        uid = self._get_text(task_el, "UID")
        if not uid or uid == "0":
            return None  # Skip the project summary task (UID=0)

        name = self._get_text(task_el, "Name", "")
        start = self._parse_date(self._get_text(task_el, "Start"))
        finish = self._parse_date(self._get_text(task_el, "Finish"))
        baseline_start = self._parse_date(self._get_text(task_el, "BaselineStart"))
        baseline_finish = self._parse_date(self._get_text(task_el, "BaselineFinish"))
        pct_complete = int(self._get_text(task_el, "PercentComplete", "0"))
        is_milestone = self._get_text(task_el, "Milestone", "0") == "1"
        notes = self._get_text(task_el, "Notes", "")

        # Duration in days (PT8H0M0S format or stored as minutes)
        duration_days = self._parse_duration_days(self._get_text(task_el, "Duration", "PT0H0M0S"))

        # Optional three-point estimates for beta-PERT SRA (Phase 8.3).
        # These are non-standard MSPDI fields written by some risk-analysis tools
        # or custom MS Project exports.  When absent (the common case), both are
        # None and SRARunner falls back to the ±10 % triangular distribution.
        _opt_str = self._get_text(task_el, "OptimisticDuration", "")
        _pess_str = self._get_text(task_el, "PessimisticDuration", "")
        duration_opt: float | None = self._parse_duration_days(_opt_str) if _opt_str else None
        duration_pess: float | None = self._parse_duration_days(_pess_str) if _pess_str else None

        # Predecessors — legacy list[str] preserved for backward compatibility
        predecessors: list[str] = []
        # Phase 9.3 — detailed predecessor link metadata (lag, type) for DCMA
        predecessor_links: list[dict] = []
        pred_link_el = task_el.find(_tag("PredecessorLink"))
        if pred_link_el is not None:
            for pl in task_el.findall(_tag("PredecessorLink")):
                pred_uid = self._get_text(pl, "PredecessorUID")
                if pred_uid:
                    predecessors.append(pred_uid)
                    # Type: 0=FF, 1=FS (default), 2=SF, 3=SS
                    link_type = int(self._get_text(pl, "Type", "1"))
                    # LinkLag stored in tenths of minutes; negative = lead
                    link_lag_raw = int(self._get_text(pl, "LinkLag", "0"))
                    predecessor_links.append({
                        "predecessor_uid": pred_uid,
                        "type": link_type,
                        "lag_tenths_min": link_lag_raw,
                    })

        # Phase 9.3 — constraint type for DCMA hard-constraint check
        # MSPDI ConstraintType: 0=ASAP(ok), 1=ALAP(hard), 2=MSO(hard),
        # 3=MFNO(ok), 4=MFO(hard), 5=MSO(hard), 6=SNL(ok), 7=FNL(ok)
        _HARD_CONSTRAINTS = {1, 2, 4, 5}  # ALAP, MSO, MFO, MSNLT
        constraint_type_raw = int(self._get_text(task_el, "ConstraintType", "0"))
        has_hard_constraint = constraint_type_raw in _HARD_CONSTRAINTS

        # Phase 9.3 — total float from MSPDI (stored in tenths of a minute)
        # 480 min/day × 10 = 4800 tenths-of-minutes per workday
        _TENTHS_MIN_PER_DAY = 4800
        total_slack_raw = self._get_text(task_el, "TotalSlack", "")
        total_float_days: float | None = None
        if total_slack_raw:
            try:
                total_float_days = int(total_slack_raw) / _TENTHS_MIN_PER_DAY
            except (ValueError, ZeroDivisionError):
                pass

        cam = assignments.get(uid, "Unassigned")

        return {
            "task_id": uid,
            "name": name,
            "start": start,
            "finish": finish,
            "baseline_start": baseline_start,
            "baseline_finish": baseline_finish,
            "percent_complete": pct_complete,
            "predecessors": predecessors,
            # Phase 9.3 additions
            "predecessor_links": predecessor_links,
            "has_hard_constraint": has_hard_constraint,
            "constraint_type": constraint_type_raw,
            "total_float_days": total_float_days,
            "cam": cam,
            "is_milestone": is_milestone,
            "duration_days": duration_days,
            "duration_opt": duration_opt,
            "duration_pess": duration_pess,
            "notes": notes,
        }

    @staticmethod
    def _get_text(el: ET.Element, local: str, default: str = "") -> str:
        """Get text content of a child element by local name."""
        child = el.find(_tag(local))
        return child.text if child is not None and child.text else default

    @staticmethod
    def _parse_date(value: str) -> datetime | None:
        """Parse an MSPDI date string (ISO 8601) into a datetime."""
        if not value:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_duration_days(value: str) -> float:
        """
        Parse an MSPDI duration string (e.g., 'PT40H0M0S') into calendar days.

        Assumes an 8-hour workday.
        """
        if not value or value == "PT0H0M0S":
            return 0.0
        try:
            # Format: PT<hours>H<minutes>M<seconds>S
            import re
            match = re.match(r"PT(\d+(?:\.\d+)?)H(\d+)M(\d+)S", value)
            if match:
                hours = float(match.group(1))
                return hours / 8.0
        except Exception:
            pass
        return 0.0
