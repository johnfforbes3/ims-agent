"""
Audit log — Phase 16 productionization.

Append-only SQLite table that records every sensitive action taken via the
dashboard API: cycle triggers, kill-switch, baseline approve/reject, admin
purges, auth token issuance.  Each row captures who/when/where/what/why so a
program office has the immutable trail required for CPR Format-5 traceability.

Schema (in ims.db, table audit_log):
  id              INTEGER  PRIMARY KEY autoincrement
  timestamp_utc   TEXT     NOT NULL  (ISO 8601)
  action          TEXT     NOT NULL  (e.g. "cycle.trigger", "approval.approve")
  actor_user      TEXT               (X-User-Email header, or "anonymous")
  actor_ip        TEXT
  actor_key_tier  TEXT               ("admin" | "read" | "anonymous")
  target          TEXT               (e.g. cycle_id, approval_id)
  outcome         TEXT     NOT NULL  ("success" | "failure")
  detail          TEXT               (JSON blob, optional context)

The actor_user is read from the X-User-Email request header (set by the
calling client — in production this would come from SSO; for now it's a
best-effort attribution).  Rows are immutable; updates are not permitted.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_DB_PATH = os.getenv("IMS_DB_PATH", "data/ims.db")
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB_PATH, timeout=10, isolation_level=None)  # autocommit
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc   TEXT NOT NULL,
                action          TEXT NOT NULL,
                actor_user      TEXT,
                actor_ip        TEXT,
                actor_key_tier  TEXT,
                target          TEXT,
                outcome         TEXT NOT NULL,
                detail          TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp_utc DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(actor_user)")


def log(
    action: str,
    *,
    actor_user: Optional[str] = None,
    actor_ip: Optional[str] = None,
    actor_key_tier: Optional[str] = None,
    target: Optional[str] = None,
    outcome: str = "success",
    detail: Any = None,
) -> int:
    """Append a row to audit_log.  Returns the row id."""
    _ensure_schema()
    detail_blob = None
    if detail is not None:
        try:
            detail_blob = json.dumps(detail, default=str)[:4096]
        except Exception:
            detail_blob = str(detail)[:4096]
    ts = datetime.now(timezone.utc).isoformat()
    with _lock, _conn() as c:
        cur = c.execute(
            """
            INSERT INTO audit_log
              (timestamp_utc, action, actor_user, actor_ip, actor_key_tier,
               target, outcome, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, action, actor_user or "anonymous", actor_ip, actor_key_tier,
             target, outcome, detail_blob),
        )
        return int(cur.lastrowid)


def query(
    *,
    limit: int = 200,
    action: Optional[str] = None,
    actor_user: Optional[str] = None,
    target: Optional[str] = None,
    since: Optional[str] = None,
) -> list[dict]:
    """Return recent audit rows.  Newest first.  Limit capped at 1000."""
    _ensure_schema()
    limit = max(1, min(int(limit or 200), 1000))
    where = []
    params: list[Any] = []
    if action:
        where.append("action = ?")
        params.append(action)
    if actor_user:
        where.append("actor_user = ?")
        params.append(actor_user)
    if target:
        where.append("target = ?")
        params.append(target)
    if since:
        where.append("timestamp_utc >= ?")
        params.append(since)
    sql = "SELECT * FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def actor_from_request(request) -> dict:
    """Extract identity metadata from a FastAPI Request.

    Reads:
      - X-User-Email header (best-effort attribution in lieu of SSO)
      - X-API-Key / X-Admin-Key / Authorization headers (for tier)
      - client.host (for IP)

    Returns dict with keys: actor_user, actor_ip, actor_key_tier.
    """
    ip = "unknown"
    try:
        ip = request.client.host if request.client else "unknown"
    except Exception:
        pass
    headers = getattr(request, "headers", {}) or {}
    user = headers.get("x-user-email") or headers.get("X-User-Email") or "anonymous"

    tier = "anonymous"
    if headers.get("x-admin-key") or headers.get("X-Admin-Key"):
        tier = "admin"
    elif headers.get("x-api-key") or headers.get("X-API-Key"):
        tier = "read"
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        # JWT — we don't decode here; the dependency already validated tier.
        # Caller can pass actor_key_tier explicitly when JWT tier is known.
        tier = tier if tier != "anonymous" else "jwt"

    return {"actor_user": user, "actor_ip": ip, "actor_key_tier": tier}
