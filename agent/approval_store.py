"""
Approval store — persists pending IMS write requests that failed validation.

When a cycle detects backwards movement or other hard validation failures it
writes the proposed cam_inputs here instead of applying them to the IMS.
A PM approves or rejects via the dashboard API.  On approval the pending
inputs are applied to the IMS and a post-approval analysis cycle runs.

File layout:
    data/pending_approvals/<cycle_id>.json
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_APPROVAL_DIR = Path(os.getenv("DATA_DIR", "data")) / "pending_approvals"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_pending(
    cycle_id: str,
    cam_inputs: list[dict],
    validation_failures: list[dict],
    ims_path: str,
) -> Path:
    """Persist cam_inputs that failed validation; return the file path."""
    _APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "cycle_id": cycle_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "ims_path": str(ims_path),
        "cam_inputs": cam_inputs,
        "validation_failures": validation_failures,
    }
    path = _APPROVAL_DIR / f"{cycle_id}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    logger.info("action=approval_saved cycle=%s failures=%d", cycle_id, len(validation_failures))
    return path


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_pending(cycle_id: str) -> dict | None:
    path = _APPROVAL_DIR / f"{cycle_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_pending() -> list[dict]:
    """Return all records with status == 'pending', sorted newest-first."""
    if not _APPROVAL_DIR.exists():
        return []
    results = []
    for f in sorted(_APPROVAL_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == "pending":
                results.append(data)
        except Exception:
            pass
    return results


def list_all() -> list[dict]:
    """Return all approval records regardless of status, sorted newest-first."""
    if not _APPROVAL_DIR.exists():
        return []
    results = []
    for f in sorted(_APPROVAL_DIR.glob("*.json"), reverse=True):
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

def mark_approved(cycle_id: str, approver: str = "") -> bool:
    """Mark a pending record as approved. Returns False if not found."""
    path = _APPROVAL_DIR / f"{cycle_id}.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "approved"
    data["decided_at"] = datetime.now(timezone.utc).isoformat()
    data["approver"] = approver
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("action=approval_approved cycle=%s approver=%s", cycle_id, approver)
    return True


def mark_rejected(cycle_id: str, reason: str = "", approver: str = "") -> bool:
    """Mark a pending record as rejected. Returns False if not found."""
    path = _APPROVAL_DIR / f"{cycle_id}.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "rejected"
    data["decided_at"] = datetime.now(timezone.utc).isoformat()
    data["rejection_reason"] = reason
    data["approver"] = approver
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("action=approval_rejected cycle=%s reason=%s", cycle_id, reason)
    return True
