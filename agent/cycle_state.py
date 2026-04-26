"""Cycle state definitions shared across Phase 3 modules."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CyclePhase(Enum):
    IDLE = "idle"
    INITIATED = "initiated"
    INTERVIEWING = "interviewing"
    VALIDATING = "validating"
    UPDATING = "updating"
    ANALYZING = "analyzing"
    DISTRIBUTING = "distributing"
    COMPLETE = "complete"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class CycleStatus:
    cycle_id: str
    phase: CyclePhase = CyclePhase.IDLE
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cams_total: int = 0
    cams_responded: int = 0
    tasks_captured: int = 0
    report_path: str = ""
    schedule_health: str = ""
    error: str = ""
    validation_holds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cams_total": self.cams_total,
            "cams_responded": self.cams_responded,
            "tasks_captured": self.tasks_captured,
            "report_path": self.report_path,
            "schedule_health": self.schedule_health,
            "error": self.error,
            "validation_holds": self.validation_holds,
        }
