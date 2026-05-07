"""
Portfolio Manager — multi-program health aggregation.

Phase 9.6: Portfolio View

A VP of Programs needs a single pane showing health across all active programs
simultaneously, so they can quickly triage which ones need attention.

This module:
  1. Discovers registered program entries from data/portfolio.json
  2. Reads the latest dashboard state for each program
  3. Aggregates health, EVM, DCMA, and milestone risk into a portfolio summary
  4. Exposes the result via GET /api/portfolio on the dashboard

Portfolio registry format (data/portfolio.json):
  [
    {
      "program_id": "ims-1",
      "name": "AI Agent Server Rack",
      "state_file": "data/dashboard_state.json",
      "description": "Primary development program"
    },
    ...
  ]

If no portfolio.json exists, the current program is treated as a
single-entry portfolio using the default dashboard_state.json.

API: GET /api/portfolio → returns portfolio summary JSON
Dashboard: Portfolio tab showing program health tiles
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_DATA_DIR = "data"
_PORTFOLIO_FILE = os.getenv("PORTFOLIO_FILE", "data/portfolio.json")
_DEFAULT_STATE_FILE = os.getenv("DASHBOARD_STATE_FILE", "data/dashboard_state.json")
_DEFAULT_PROGRAM_NAME = os.getenv("PROGRAM_NAME", "IMS Program")


def _portfolio_file() -> str:
    """Return the current portfolio file path, reading env at call time."""
    return os.getenv("PORTFOLIO_FILE", _PORTFOLIO_FILE)


def _default_state_file() -> str:
    """Return the current default state file path, reading env at call time."""
    return os.getenv("DASHBOARD_STATE_FILE", _DEFAULT_STATE_FILE)


def get_portfolio() -> dict[str, Any]:
    """
    Build the portfolio summary from all registered programs.

    Returns:
        Dict with:
            programs:     list of program summary dicts (one per program)
            portfolio_health: aggregate health ("RED" if any RED, etc.)
            total_programs: int
            programs_at_risk: int (RED or YELLOW)
            computed_at: ISO string
    """
    programs = _load_program_list()
    summaries = [_build_program_summary(p) for p in programs]

    # Aggregate portfolio-level health
    health_levels = [s["health"] for s in summaries]
    portfolio_health = _aggregate_health(health_levels)

    at_risk = sum(1 for h in health_levels if h in ("RED", "YELLOW"))

    return {
        "programs": summaries,
        "portfolio_health": portfolio_health,
        "total_programs": len(summaries),
        "programs_at_risk": at_risk,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def register_program(
    program_id: str,
    name: str,
    state_file: str,
    description: str = "",
) -> bool:
    """
    Add or update a program in the portfolio registry.

    Args:
        program_id: Unique identifier (e.g., "prog-001").
        name: Human-readable program name.
        state_file: Path to the program's dashboard_state.json.
        description: Optional description.

    Returns:
        True if saved successfully.
    """
    portfolio_path = Path(_portfolio_file())
    programs = _load_raw_program_list()

    # Update or append
    for p in programs:
        if p["program_id"] == program_id:
            p["name"] = name
            p["state_file"] = state_file
            p["description"] = description
            break
    else:
        programs.append({
            "program_id": program_id,
            "name": name,
            "state_file": state_file,
            "description": description,
        })

    portfolio_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        portfolio_path.write_text(json.dumps(programs, indent=2), encoding="utf-8")
        logger.info("action=portfolio_register program_id=%s", program_id)
        return True
    except Exception as exc:
        logger.error("action=portfolio_register_failed error=%s", exc)
        return False


def deregister_program(program_id: str) -> bool:
    """Remove a program from the portfolio registry."""
    portfolio_path = Path(_portfolio_file())
    programs = _load_raw_program_list()
    original_count = len(programs)
    programs = [p for p in programs if p["program_id"] != program_id]
    if len(programs) == original_count:
        return False  # not found
    try:
        portfolio_path.write_text(json.dumps(programs, indent=2), encoding="utf-8")
        return True
    except Exception as exc:
        logger.error("action=portfolio_deregister_failed error=%s", exc)
        return False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_raw_program_list() -> list[dict]:
    """Load raw program entries from portfolio.json."""
    portfolio_path = Path(_portfolio_file())
    if portfolio_path.exists():
        try:
            return json.loads(portfolio_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _load_program_list() -> list[dict]:
    """
    Load program list; falls back to a single default entry if empty.
    """
    programs = _load_raw_program_list()
    if not programs:
        programs = [{
            "program_id": "default",
            "name": _DEFAULT_PROGRAM_NAME,
            "state_file": _DEFAULT_STATE_FILE,
            "description": "Primary program",
        }]
    return programs


def _build_program_summary(program_entry: dict) -> dict[str, Any]:
    """
    Build a summary dict for a single program from its dashboard state file.
    """
    state_file = program_entry.get("state_file", _DEFAULT_STATE_FILE)
    state = _load_state(state_file)

    program_id = program_entry.get("program_id", "unknown")
    name = program_entry.get("name", "Unknown Program")
    description = program_entry.get("description", "")

    # Core health
    health = state.get("schedule_health", "UNKNOWN")
    cycle_id = state.get("cycle_id", "")
    last_updated = state.get("last_updated", "")

    # EVM quick metrics
    evm = state.get("evm", {})
    program_evm = evm.get("program", {})
    spi = program_evm.get("spi")
    completion_pct = program_evm.get("completion_pct", 0.0)
    bei = program_evm.get("bei")
    sv = program_evm.get("sv", 0.0)

    # DCMA score
    dcma = state.get("dcma", {})
    dcma_score = dcma.get("score")
    dcma_total = dcma.get("total_checks", 14)
    dcma_health = dcma.get("health", "")

    # Milestone risk
    milestones = state.get("milestones", [])
    high_risk_ms = [m for m in milestones if m.get("risk_level") == "HIGH"]
    medium_risk_ms = [m for m in milestones if m.get("risk_level") == "MEDIUM"]

    # CAM response rate
    completion_report = state.get("completion_report", {})
    cam_responded = completion_report.get("responded", 0)
    cam_total = completion_report.get("total", 0)
    cam_rate = f"{cam_responded}/{cam_total}" if cam_total else "N/A"

    # Top risks (first line only for tile)
    top_risks = state.get("top_risks", "")
    top_risk_preview = (top_risks.split("\n")[0][:120]) if top_risks else ""

    # Staleness — flag if last_updated is old
    is_stale = False
    if last_updated:
        try:
            from datetime import timedelta
            lu = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - lu).total_seconds() / 3600
            is_stale = age_hours > 168  # stale after 7 days
        except Exception:
            pass

    return {
        "program_id": program_id,
        "name": name,
        "description": description,
        "health": health,
        "cycle_id": cycle_id,
        "last_updated": last_updated,
        "is_stale": is_stale,
        "is_active": bool(state),  # False if state file not found
        "spi": spi,
        "completion_pct": completion_pct,
        "bei": bei,
        "sv_days": sv,
        "dcma_score": f"{dcma_score}/{dcma_total}" if dcma_score is not None else None,
        "dcma_health": dcma_health,
        "milestones_high_risk": len(high_risk_ms),
        "milestones_medium_risk": len(medium_risk_ms),
        "cam_response_rate": cam_rate,
        "top_risk_preview": top_risk_preview,
        "state_file": state_file,
    }


def _load_state(state_file: str) -> dict[str, Any]:
    """Load a dashboard state JSON file."""
    path = Path(state_file)
    if not path.exists():
        logger.debug("action=portfolio_state_missing path=%s", state_file)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("action=portfolio_state_load_failed path=%s error=%s", state_file, exc)
        return {}


def _aggregate_health(health_levels: list[str]) -> str:
    """
    Aggregate multiple health labels into a single portfolio health.

    Any RED → RED. All GREEN → GREEN. Otherwise YELLOW.
    """
    if not health_levels:
        return "UNKNOWN"
    if "RED" in health_levels:
        return "RED"
    if all(h == "GREEN" for h in health_levels):
        return "GREEN"
    return "YELLOW"
