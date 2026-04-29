"""
Schedule validator — checks CAM inputs before writing to the IMS.

Rules (all configurable via env vars):
  1. No backwards movement: percent_complete cannot decrease without explanation.
  2. No large jump: percent_complete cannot increase >50 points in one cycle.
  3. Coverage: all non-milestone tasks in each CAM's scope must have a response.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_MAX_JUMP_PCT = int(os.getenv("VALIDATION_MAX_JUMP_PCT", "50"))


def _allow_backwards() -> bool:
    """Re-read env var at call time so runtime changes (os.environ, monkeypatch) take effect."""
    return os.getenv("VALIDATION_ALLOW_BACKWARDS", "false").lower() == "true"


@dataclass
class ValidationFailure:
    task_id: str
    cam_name: str
    rule: str
    detail: str


@dataclass
class ValidationResult:
    passed: bool
    failures: list[ValidationFailure] = field(default_factory=list)
    warnings: list[ValidationFailure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failures": [
                {"task_id": f.task_id, "cam_name": f.cam_name,
                 "rule": f.rule, "detail": f.detail}
                for f in self.failures
            ],
            "warnings": [
                {"task_id": w.task_id, "cam_name": w.cam_name,
                 "rule": w.rule, "detail": w.detail}
                for w in self.warnings
            ],
        }


class ScheduleValidator:
    """Validates CAM inputs before writing to the IMS."""

    def validate(
        self,
        cam_inputs: list[dict[str, Any]],
        current_tasks: list[dict[str, Any]],
    ) -> ValidationResult:
        """
        Run all validation rules against the proposed inputs.

        Failures block the update (unless human override).
        Warnings are logged and surfaced but do not block.
        """
        failures: list[ValidationFailure] = []
        warnings: list[ValidationFailure] = []

        current_by_id = {t["task_id"]: t for t in current_tasks}

        for inp in cam_inputs:
            task_id = inp["task_id"]
            cam_name = inp.get("cam_name", "")
            new_pct = inp.get("percent_complete")

            if new_pct is None:
                continue  # no_response — not a validation failure

            current = current_by_id.get(task_id)
            if current is None:
                warnings.append(ValidationFailure(
                    task_id=task_id, cam_name=cam_name,
                    rule="unknown_task",
                    detail=f"Task {task_id} not found in current schedule",
                ))
                continue

            prev_pct = current.get("percent_complete", 0)

            if not _allow_backwards() and new_pct < prev_pct:
                failures.append(ValidationFailure(
                    task_id=task_id, cam_name=cam_name,
                    rule="backwards_movement",
                    detail=(
                        f"Percent decreased {prev_pct}% → {new_pct}% "
                        "with no explanation provided"
                    ),
                ))
            elif new_pct - prev_pct > _MAX_JUMP_PCT:
                warnings.append(ValidationFailure(
                    task_id=task_id, cam_name=cam_name,
                    rule="large_jump",
                    detail=(
                        f"Percent jumped {new_pct - prev_pct} points "
                        f"({prev_pct}% → {new_pct}%) in one cycle"
                    ),
                ))

        # Coverage check: every non-milestone task in each CAM's scope needs a response
        responded_ids = {inp["task_id"] for inp in cam_inputs}
        cam_scope: dict[str, set[str]] = {}
        for t in current_tasks:
            if not t.get("is_milestone"):
                cam = t.get("cam", "Unassigned")
                cam_scope.setdefault(cam, set()).add(t["task_id"])

        for cam, task_ids in cam_scope.items():
            for tid in sorted(task_ids - responded_ids):
                warnings.append(ValidationFailure(
                    task_id=tid, cam_name=cam,
                    rule="missing_response",
                    detail=f"No response captured for {tid} from {cam}",
                ))

        result = ValidationResult(
            passed=len(failures) == 0,
            failures=failures,
            warnings=warnings,
        )
        logger.info(
            "action=validation_complete passed=%s failures=%d warnings=%d",
            result.passed, len(failures), len(warnings),
        )
        return result
