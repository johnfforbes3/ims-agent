"""
Cycle heartbeat — Phase 16 productionization.

A small persistent state file that the cycle runner writes to at the start of
each phase, plus periodically while a long-running phase (e.g. INTERVIEW) is
underway.  External health checks read this file to detect stalled cycles
even if the runner process has crashed.

State file: data/cycle_heartbeat.json
{
  "cycle_id":        "20260517T104629Z",
  "phase":           "interview",
  "started_at":      "2026-05-17T10:46:29Z",
  "last_heartbeat":  "2026-05-17T11:02:15Z",
  "ttl_seconds":     1800,
  "process_id":      12345,
  "host":            "DESKTOP-XXX"
}

A cycle is considered STALLED when:
  - heartbeat file exists, AND
  - now - last_heartbeat > ttl_seconds

The dashboard /health endpoint exposes this so ops can be notified.
"""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_PATH = os.getenv("CYCLE_HEARTBEAT_FILE", "data/cycle_heartbeat.json")
_DEFAULT_TTL = int(os.getenv("CYCLE_HEARTBEAT_TTL_SECONDS", "1800"))  # 30 min


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path() -> Path:
    return Path(_DEFAULT_PATH)


def start(cycle_id: str, phase: str = "initiated", ttl_seconds: int = _DEFAULT_TTL) -> None:
    """Mark a cycle as started.  Overwrites any prior heartbeat."""
    state = {
        "cycle_id": cycle_id,
        "phase": phase,
        "started_at": _now_iso(),
        "last_heartbeat": _now_iso(),
        "ttl_seconds": ttl_seconds,
        "process_id": os.getpid(),
        "host": socket.gethostname(),
    }
    _write(state)


def beat(phase: Optional[str] = None) -> None:
    """Update the heartbeat timestamp.  Optionally update the phase label."""
    state = read() or {}
    state["last_heartbeat"] = _now_iso()
    if phase is not None:
        state["phase"] = phase
    if "ttl_seconds" not in state:
        state["ttl_seconds"] = _DEFAULT_TTL
    _write(state)


def clear() -> None:
    """Remove the heartbeat file (call on graceful cycle completion)."""
    p = _path()
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


def read() -> Optional[dict]:
    p = _path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_stalled(now_ts: Optional[float] = None) -> tuple[bool, Optional[dict]]:
    """Return (stalled, state).  stalled=False when no heartbeat file exists."""
    state = read()
    if not state:
        return False, None
    last = state.get("last_heartbeat", "")
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False, state
    now = datetime.fromtimestamp(now_ts, tz=timezone.utc) if now_ts else datetime.now(timezone.utc)
    age = (now - last_dt).total_seconds()
    ttl = float(state.get("ttl_seconds") or _DEFAULT_TTL)
    return age > ttl, {**state, "age_seconds": round(age, 1)}


def _write(state: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    # Same Windows OneDrive retry pattern as cycle_runner
    for attempt in range(3):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.1 * (2 ** attempt))
