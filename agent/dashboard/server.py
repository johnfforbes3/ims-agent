"""
Dashboard server — FastAPI + Jinja2 HTML dashboard for IMS Agent.

Serves:
  GET /            → HTML dashboard (auto-refreshes every 60s)
  GET /health      → health check (unauthenticated; includes last_cycle_age_seconds, deadman_alert)
  GET /metrics     → in-memory metrics snapshot (requires API key); ?format=prometheus for Prometheus scraping
  GET /api/state   → current dashboard state JSON
  GET /api/history → cycle history JSON
  POST /api/trigger → admin: manually fire a cycle (async, returns immediately)
  GET /api/status  → is a cycle currently running?
  POST /api/ask    → Phase 4 Q&A: answer a natural language question (rate-limited)
  POST /api/admin/purge → admin: delete cycle data older than retention window

Authentication:
  DASHBOARD_API_KEY  — required on all /api/* read routes.  Empty = auth disabled (dev).
  DASHBOARD_ADMIN_KEY — required for write/admin routes (/api/trigger, /api/admin/purge).
                        Falls back to DASHBOARD_API_KEY when not set.
  Both keys are sent via X-API-Key / X-Admin-Key headers respectively.
"""

import collections
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_STATE_FILE = os.getenv("DASHBOARD_STATE_FILE", "data/dashboard_state.json")
_HISTORY_FILE = os.getenv("CYCLE_HISTORY_FILE", "data/cycle_history.json")
_PORT = int(os.getenv("DASHBOARD_PORT", "9000"))
_IMS_PATH = os.getenv("IMS_FILE_PATH", "data/sample_ims.xml")
_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
_ADMIN_KEY = os.getenv("DASHBOARD_ADMIN_KEY", "")
_QA_RATE_LIMIT = int(os.getenv("QA_RATE_LIMIT_PER_HOUR", "60"))

_START_TIME = time.monotonic()

app = FastAPI(title="IMS Agent Dashboard", docs_url=None, redoc_url=None)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def _require_api_key(
    request: Request,
    api_key: str = Security(_api_key_header),
) -> None:
    """Dependency: enforce X-API-Key when DASHBOARD_API_KEY is configured."""
    if not _API_KEY:
        return  # auth disabled in local dev mode
    if api_key != _API_KEY:
        logger.warning(
            "action=audit_auth_failure route=%s ip=%s reason=invalid_api_key",
            request.url.path,
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def _require_admin_key(
    request: Request,
    x_admin_key: str = Security(_admin_key_header),
    x_api_key: str = Security(_api_key_header),
) -> None:
    """Dependency: enforce admin key for write/admin operations.

    Effective admin key is DASHBOARD_ADMIN_KEY when set, falling back to
    DASHBOARD_API_KEY.  If neither is configured (dev mode), allows all.
    """
    if not _API_KEY and not _ADMIN_KEY:
        return  # dev mode — no keys configured
    effective = _ADMIN_KEY if _ADMIN_KEY else _API_KEY
    if x_admin_key == effective or x_api_key == effective:
        return
    logger.warning(
        "action=audit_auth_failure route=%s ip=%s reason=invalid_admin_key",
        request.url.path,
        request.client.host if request.client else "unknown",
    )
    raise HTTPException(status_code=401, detail="Admin key required")


# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per client IP)
# ---------------------------------------------------------------------------

_rate_limiter: dict[str, list[float]] = collections.defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the IP exceeds QA_RATE_LIMIT_PER_HOUR requests in the rolling hour."""
    if _QA_RATE_LIMIT <= 0:
        return
    now = time.monotonic()
    with _rate_lock:
        cutoff = now - 3600.0
        _rate_limiter[ip] = [t for t in _rate_limiter[ip] if t > cutoff]
        if len(_rate_limiter[ip]) >= _QA_RATE_LIMIT:
            logger.warning("action=audit_rate_limit_exceeded ip=%s limit=%d", ip, _QA_RATE_LIMIT)
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        _rate_limiter[ip].append(now)


_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _deadman_period_seconds() -> int:
    """Return 2× the configured schedule period in seconds.

    Used by the dead man's switch: if no successful cycle has completed within
    this window, ``GET /health`` includes ``deadman_alert: true``.

    Derived from ``SCHEDULE_CRON`` (weekly default → 2 weeks) or the simpler
    ``DEADMAN_PERIOD_HOURS`` override for non-cron deployments.
    """
    override = os.getenv("DEADMAN_PERIOD_HOURS", "")
    if override:
        try:
            return int(float(override) * 3600)
        except ValueError:
            pass
    # Default: weekly cron → 2 weeks = 336 hours
    cron = os.getenv("SCHEDULE_CRON", "0 6 * * 1")
    # Simple heuristic: count spaces-separated fields; all standard crons are weekly
    # until we have a full cron parser. 2 × 7 days is the safe default.
    return 14 * 24 * 3600  # 2 weeks


@app.get("/health")
async def health():
    """
    Unauthenticated health check — used by Docker, load balancers, and uptime monitors.

    Phase 6.1 additions:
    - last_cycle_age_seconds  — seconds since the last successful cycle completed
    - deadman_alert           — True when no cycle has completed within 2 × SCHEDULE_PERIOD
    - ims_last_write_at       — ISO timestamp of the last IMS write (from dashboard state)
    """
    import datetime as dt
    from agent.cycle_runner import CycleRunner
    from agent.metrics import snapshot as _metrics_snapshot

    state_exists = Path(_STATE_FILE).exists()
    metrics = _metrics_snapshot()

    # last_cycle_age_seconds
    last_completed_at = metrics.get("last_cycle_completed_at")
    last_cycle_age_seconds: int | None = None
    deadman_alert = False
    if last_completed_at:
        try:
            last_ts = dt.datetime.fromisoformat(last_completed_at)
            now = dt.datetime.now(dt.timezone.utc)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=dt.timezone.utc)
            age = round((now - last_ts).total_seconds())
            last_cycle_age_seconds = age
            deadman_alert = age > _deadman_period_seconds()
        except (ValueError, TypeError):
            pass
    elif metrics.get("cycles_completed", 0) == 0:
        # No cycle has ever completed in this process — not yet a dead man alert
        # (the agent may have just started up)
        deadman_alert = False

    # ims_last_write_at from dashboard state
    ims_last_write_at: str | None = None
    state = _load_json(_STATE_FILE) or {}
    ims_last_write_at = state.get("completed_at") or state.get("started_at")

    return JSONResponse({
        "status": "healthy",
        "uptime_seconds": round(time.monotonic() - _START_TIME),
        "cycle_active": CycleRunner.is_active(),
        "state_file_present": state_exists,
        "auth_enabled": bool(_API_KEY),
        "last_cycle_age_seconds": last_cycle_age_seconds,
        "deadman_alert": deadman_alert,
        "ims_last_write_at": ims_last_write_at,
    })


@app.get("/metrics", dependencies=[Depends(_require_api_key)])
async def api_metrics(format: str = "json"):
    """
    In-memory agent metrics snapshot.

    Query params:
        format=json        — JSON object (default)
        format=prometheus  — Prometheus text exposition format (text/plain; version=0.0.4)
    """
    if format.lower() == "prometheus":
        from agent.metrics import prometheus_text
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            prometheus_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    from agent.metrics import snapshot
    return JSONResponse(snapshot())


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    state = _load_json(_STATE_FILE) or {}
    history = _load_json(_HISTORY_FILE) or []
    return templates.TemplateResponse(
        request,
        "index.html",
        {"state": state, "history": history},
    )


@app.get("/api/state", dependencies=[Depends(_require_api_key)])
async def api_state():
    state = _load_json(_STATE_FILE)
    if state is None:
        return JSONResponse({"error": "No cycle data yet"}, status_code=404)
    return JSONResponse(state)


@app.get("/api/history", dependencies=[Depends(_require_api_key)])
async def api_history():
    return JSONResponse(_load_json(_HISTORY_FILE) or [])


@app.get("/api/diff/{cycle_id}", dependencies=[Depends(_require_api_key)])
async def api_diff(cycle_id: str):
    """
    Phase 6.5 — Return the IMS field-change diff for a completed cycle.

    Diff file is written by CycleRunner._run_inner() after apply_updates() succeeds.
    Returns a list of change dicts, one per (task, field) pair that changed.
    """
    from agent.ims_diff import load_diff
    diff = load_diff(cycle_id)
    if diff is None:
        return JSONResponse(
            {"error": f"No diff found for cycle {cycle_id}"},
            status_code=404,
        )
    return JSONResponse(diff)


@app.get("/api/changes", dependencies=[Depends(_require_api_key)])
async def api_changes(
    from_cycle: str | None = None,
    to_cycle: str | None = None,
    format: str = "json",
):
    """
    7.4.2 — Cumulative change report across a range of cycles.

    Query params:
        from_cycle  (optional) earliest cycle ID to include; defaults to the
                    oldest diff file in data/ims_exports/
        to_cycle    (optional) latest cycle ID to include; defaults to the newest
        format      "json" (default) or "csv"
    """
    from agent.ims_diff import merge_diffs
    import glob as _glob

    exports_dir = os.path.join(os.getenv("DATA_DIR", "data"), "ims_exports")

    # Determine from/to defaults from available diff files
    diff_files = sorted(_glob.glob(os.path.join(exports_dir, "*_diff.json")))
    if not diff_files:
        return JSONResponse({"error": "No diff files found"}, status_code=404)

    all_ids = [os.path.basename(f)[: -len("_diff.json")] for f in diff_files]
    resolved_from = from_cycle or all_ids[0]
    resolved_to = to_cycle or all_ids[-1]

    merged = merge_diffs(resolved_from, resolved_to)

    if format.lower() == "csv":
        import io
        import csv as _csv
        buf = io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=[
            "task_id", "task_name", "cam_name", "field",
            "old_value", "new_value", "hop_count", "contributing_cycle_ids",
        ])
        writer.writeheader()
        for row in merged:
            row["contributing_cycle_ids"] = "|".join(row.get("contributing_cycle_ids", []))
            writer.writerow(row)
        from starlette.responses import PlainTextResponse
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=changes.csv"},
        )

    return JSONResponse({
        "from_cycle": resolved_from,
        "to_cycle": resolved_to,
        "total_changes": len(merged),
        "changes": merged,
    })


@app.get("/api/baseline-drift", dependencies=[Depends(_require_api_key)])
async def api_baseline_drift():
    """
    7.4.3 — Baseline drift report.

    Compares the current IMS task list (from dashboard_state.json) against
    the baseline snapshot identified by BASELINE_CYCLE_ID env var, or the
    oldest available snapshot in data/ims_exports/.

    Returns per-task slip in calendar days, pct-complete delta, tasks
    added/removed since baseline, and milestones slipped > BASELINE_DRIFT_ALERT_DAYS.
    """
    from agent.ims_diff import compute_baseline_drift
    from agent.qa.context_builder import load_state

    state = load_state()
    # Use milestones + tasks_behind as a proxy for current task list; combine
    # them into minimal task dicts with the fields compute_baseline_drift needs.
    milestones = state.get("milestones", [])
    tasks_behind = state.get("tasks_behind", [])

    current_tasks: list[dict] = []
    seen: set[str] = set()
    for m in milestones:
        tid = str(m.get("task_id", ""))
        if tid and tid not in seen:
            seen.add(tid)
            current_tasks.append({
                "task_id": tid,
                "name": m.get("milestone_name", tid),
                "cam": "",
                "finish": m.get("p50_date"),
                "baseline_finish": m.get("baseline_date"),
                "percent_complete": 100 if m.get("prob_on_baseline", 0) >= 1.0 else 0,
                "is_milestone": True,
            })
    for t in tasks_behind:
        tid = str(t.get("task_id", ""))
        if tid and tid not in seen:
            seen.add(tid)
            current_tasks.append({
                "task_id": tid,
                "name": t.get("task_name", tid),
                "cam": t.get("cam_name", ""),
                "finish": None,
                "baseline_finish": None,
                "percent_complete": t.get("percent_complete", 0),
                "is_milestone": False,
            })

    result = compute_baseline_drift(current_tasks)
    return JSONResponse(result)


@app.get("/api/status", dependencies=[Depends(_require_api_key)])
async def api_status():
    from agent.cycle_runner import CycleRunner
    return JSONResponse({"cycle_active": CycleRunner.is_active()})


@app.post("/api/trigger", dependencies=[Depends(_require_admin_key)])
async def api_trigger(request: Request):
    """Admin: fire a cycle immediately in a background thread."""
    from agent.cycle_runner import CycleRunner
    if CycleRunner.is_active():
        raise HTTPException(status_code=409, detail="A cycle is already running")
    runner = CycleRunner(ims_path=_IMS_PATH, mode=os.getenv("CALL_TRANSPORT", "simulated"))
    thread = threading.Thread(target=runner.run, daemon=True, name="manual_cycle")
    thread.start()
    logger.info(
        "action=audit_admin_trigger ip=%s transport=%s",
        request.client.host if request.client else "unknown",
        os.getenv("CALL_TRANSPORT", "simulated"),
    )
    return JSONResponse({"status": "triggered", "message": "Cycle started in background"})


@app.post("/api/admin/purge", dependencies=[Depends(_require_admin_key)])
async def api_admin_purge(request: Request):
    """Admin: delete cycle status JSONs and IMS snapshots older than the retention window."""
    from agent.cycle_runner import CycleRunner
    deleted = CycleRunner.purge_old_data()
    logger.info(
        "action=audit_admin_purge ip=%s deleted=%s",
        request.client.host if request.client else "unknown",
        deleted,
    )
    return JSONResponse({"status": "ok", "deleted": deleted})


# ---------------------------------------------------------------------------
# Approval gate endpoints (human-in-the-loop for risky schedule changes)
# ---------------------------------------------------------------------------

@app.get("/api/approvals", dependencies=[Depends(_require_api_key)])
async def api_list_approvals():
    """List all pending IMS write approvals awaiting PM review."""
    from agent.approval_store import list_all
    return JSONResponse(list_all())


class _ApprovalDecision(BaseModel):
    reason: str = ""
    approver: str = ""


@app.post("/api/approvals/{cycle_id}/approve", dependencies=[Depends(_require_admin_key)])
async def api_approve(
    cycle_id: str,
    request: Request,
    body: _ApprovalDecision = _ApprovalDecision(),
):
    """
    Approve a held IMS write.

    Applies the pending cam_inputs to the authoritative IMS file and runs
    post-approval analysis (CPM + SRA + synthesis + report).
    """
    from agent.approval_store import load_pending
    record = load_pending(cycle_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No pending approval for cycle {cycle_id}")
    if record.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Cycle {cycle_id} is already {record['status']}")

    approver = body.approver or "dashboard"
    logger.info(
        "action=audit_admin_approve cycle=%s approver=%s ip=%s",
        cycle_id, approver,
        request.client.host if request.client else "unknown",
    )

    # Apply in a background thread so the HTTP response returns immediately.
    # apply_approved() owns the mark_approved() call — don't call it here.
    def _apply():
        from agent.cycle_runner import CycleRunner
        result = CycleRunner.apply_approved(cycle_id, approver=approver)
        logger.info("action=approval_applied_complete cycle=%s result=%s", cycle_id, result)

    thread = threading.Thread(target=_apply, daemon=True, name=f"approval_{cycle_id}")
    thread.start()

    return JSONResponse({
        "status": "accepted",
        "message": f"Approval recorded for cycle {cycle_id}. Applying updates in background.",
    })


@app.post("/api/approvals/{cycle_id}/reject", dependencies=[Depends(_require_admin_key)])
async def api_reject(cycle_id: str, body: _ApprovalDecision = _ApprovalDecision()):
    """Reject a held IMS write — discards the pending cam_inputs."""
    from agent.approval_store import mark_rejected, load_pending
    record = load_pending(cycle_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No pending approval for cycle {cycle_id}")
    if record.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Cycle {cycle_id} is already {record['status']}")

    mark_rejected(cycle_id, reason=body.reason, approver=body.approver or "dashboard")
    logger.info("action=rejection_api cycle=%s reason=%s", cycle_id, body.reason)
    return JSONResponse({"status": "rejected", "cycle_id": cycle_id})


class _AskRequest(BaseModel):
    question: str


@app.post("/api/ask", dependencies=[Depends(_require_api_key)])
async def api_ask(request: Request, body: _AskRequest):
    """Phase 4 Q&A — answer a natural language question about the schedule."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="question too long (max 500 chars)")
    try:
        from agent.qa.qa_engine import QAEngine
        response = QAEngine().ask(question)
        return JSONResponse(response.to_dict())
    except Exception as exc:
        logger.error("action=qa_error error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# ACS Call Automation webhook (Tier 3 — Teams interview demo)
# ---------------------------------------------------------------------------

@app.post("/acs/callback")
async def acs_callback(request: Request):
    """
    Receives Azure Communication Services Call Automation CloudEvents.

    ACS sends HTTP POST requests to this endpoint for each call lifecycle event
    (CallConnected, PlayCompleted, PlayFailed, CallDisconnected, etc.).
    Events are routed to the ACSEventBus so the interview loop thread can
    synchronise with call state changes.

    This route is unauthenticated — ACS does not support custom auth headers
    on callbacks. Restrict access at the network/reverse-proxy layer in production.
    """
    try:
        body = await request.json()
        from agent.acs_event_handler import event_bus
        # ACS sends an array of CloudEvent objects
        events = body if isinstance(body, list) else [body]
        for event in events:
            event_type = event.get("type", "")
            data = event.get("data", {})
            if event_type:
                event_bus.handle(event_type, data)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.error("action=acs_callback_error error=%s", exc, exc_info=True)
        # Always return 200 to ACS — a non-2xx causes it to retry
        return JSONResponse({"status": "error", "detail": str(exc)})


# ---------------------------------------------------------------------------
# Microsoft Graph Communications API — callback + audio serving
# ---------------------------------------------------------------------------

# Module-level reference updated by demo_interview when TeamsGraphConnector is used
_graph_connector: "Any" = None


@app.post("/graph/callback")
async def graph_callback(request: Request):
    """
    Receives Microsoft Graph Communications API call-state notifications.

    Handles:
      - Subscription validation (echo validationToken back as plain text)
      - Call state changes: established → CallConnected, terminated → CallDisconnected
      - PlayPrompt completion → PlayCompleted / PlayFailed
    """
    from fastapi.responses import PlainTextResponse

    # Subscription validation handshake
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info("action=graph_validation token=%s", validation_token[:20])
        return PlainTextResponse(content=validation_token, status_code=200)

    try:
        body = await request.json()
        from agent.acs_event_handler import event_bus
        logger.debug("action=graph_callback body=%s", str(body)[:300])

        notifications = body.get("value", []) if isinstance(body, dict) else []
        if not notifications:
            notifications = [body]

        import re as _re
        for note in notifications:
            resource_data = note.get("resourceData", {})
            # Graph sometimes sends resourceData as a list; normalise to dict
            if isinstance(resource_data, list):
                resource_data = resource_data[0] if resource_data else {}

            resource = note.get("resource", "")
            change_type = note.get("changeType", "")

            # Extract call ID from resource path: /communications/calls/{id}/...
            # Using regex so we get the call segment, not a trailing operation segment.
            _m = _re.search(r"/calls/([^/]+)", resource)
            if _m:
                call_id = _m.group(1)
            elif isinstance(resource_data, dict):
                call_id = resource_data.get("id", "") or resource.rstrip("/").split("/")[-1]
            else:
                call_id = resource.rstrip("/").split("/")[-1]

            call_state = resource_data.get("state", "") if isinstance(resource_data, dict) else ""
            op_status  = resource_data.get("status", "") if isinstance(resource_data, dict) else ""
            odata_type = resource_data.get("@odata.type", "") if isinstance(resource_data, dict) else ""

            logger.info(
                "action=graph_event call_id=%s state=%s op_status=%s odata=%s",
                call_id, call_state, op_status, odata_type
            )

            odata_lower = odata_type.lower()

            # Call state changes  (#microsoft.graph.call)
            if "operation" not in odata_lower and "call" in odata_lower:
                if call_state in ("established", "connected"):
                    event_bus.handle("Microsoft.Communication.CallConnected",
                                     {"callConnectionId": call_id})
                elif call_state in ("terminated", "disconnected") or change_type == "deleted":
                    event_bus.handle("Microsoft.Communication.CallDisconnected",
                                     {"callConnectionId": call_id})

            # PlayPrompt / comms operation completion
            # Matches: #microsoft.graph.playPromptOperation, #microsoft.graph.commsOperation, etc.
            elif "operation" in odata_lower or "playprompt" in resource.lower():
                if op_status == "completed":
                    event_bus.handle("Microsoft.Communication.PlayCompleted",
                                     {"callConnectionId": call_id})
                elif op_status in ("failed", "timedOut"):
                    event_bus.handle("Microsoft.Communication.PlayFailed",
                                     {"callConnectionId": call_id})

        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.error("action=graph_callback_error error=%s", exc, exc_info=True)
        return JSONResponse({"status": "error", "detail": str(exc)})


@app.get("/graph/audio/{audio_id}")
async def graph_serve_audio(audio_id: str):
    """
    Serve a single-use WAV audio clip for Graph playPrompt.

    TeamsGraphConnector stores the WAV bytes here keyed by UUID; Graph fetches
    this URL during playPrompt and plays the audio into the Teams meeting.
    """
    from fastapi import HTTPException
    from fastapi.responses import Response as FastAPIResponse
    global _graph_connector
    if _graph_connector is None or audio_id not in _graph_connector.audio_cache:
        raise HTTPException(status_code=404, detail="Audio not found")
    wav = _graph_connector.audio_cache.pop(audio_id)   # serve once and discard
    return FastAPIResponse(content=wav, media_type="audio/wav")


# ---------------------------------------------------------------------------
# Bot Framework chat endpoint — Teams text interviews
# ---------------------------------------------------------------------------

@app.post("/bot/messages")
async def bot_messages(request: Request):
    """
    Bot Framework messaging endpoint.

    Teams delivers incoming chat messages from CAMs here as JSON Activity
    objects. We process each message through the ChatInterviewManager and
    reply with the next interview question.

    Auth: Bot Framework signs requests with a JWT. In dev we skip full
    validation; in production add botbuilder-core for proper verification.

    Configure in Azure Bot Service → Configuration → Messaging endpoint:
        https://<ngrok-url>/bot/messages
    """
    try:
        body = await request.json()
        activity_type = body.get("type", "")

        # Ignore non-message activities (conversationUpdate, typing, etc.)
        if activity_type != "message":
            return JSONResponse({"status": "ok"})

        from_obj      = body.get("from", {})
        user_id       = from_obj.get("id", "")
        aad_object_id = from_obj.get("aadObjectId", "")
        user_email    = from_obj.get("email", "") or from_obj.get("userPrincipalName", "")
        message_text  = (body.get("text") or "").strip()
        service_url   = body.get("serviceUrl", "")
        conversation  = body.get("conversation", {})
        conversation_id = conversation.get("id", "")
        activity_id   = body.get("id", "")

        if not message_text or not user_id:
            return JSONResponse({"status": "ok"})

        # If email not in activity, resolve via aadObjectId against identity map
        if not user_email and aad_object_id:
            try:
                from agent.cam_identity import load_identity_map
                from agent.voice.teams_chat_connector import load_cam_sessions as _lcs
                _sessions = _lcs()
                for _email, _sdata in _sessions.items():
                    # cam_sessions user_id is "29:{aad_object_id}"
                    if _sdata.get("user_id", "").endswith(aad_object_id):
                        user_email = _email
                        break
                if not user_email:
                    for _name, _info in load_identity_map().items():
                        _email = _info.get("email", "")
                        if _email and aad_object_id.lower() in user_id.lower():
                            user_email = _email
                            break
            except Exception:
                pass

        logger.info(
            "action=bot_message_received user=%s text_len=%d",
            user_id[:8] + "...", len(message_text),
        )

        from agent.voice.teams_chat_connector import (
            ChatInterviewManager, _bf_reply, _bf_typing, save_cam_session,
        )

        manager = ChatInterviewManager.get()
        session = manager.get_or_start_session(user_id, user_email)

        if session is None:
            # Persist contact info for future proactive cycles even outside an interview
            if user_email and service_url:
                try:
                    save_cam_session(user_email, user_id, service_url, conversation_id)
                    logger.info("action=cam_session_saved_idle email=%s", user_email)
                except Exception as _e:
                    logger.debug("action=session_persist_failed error=%s", _e)
            _bf_reply(
                service_url, conversation_id, activity_id,
                "Hey! No status check scheduled right now — I'll reach out when it's time. "
                "You're all set until then!",
            )
            return JSONResponse({"status": "ok"})

        # Store connection details for this session and persist for future proactive use
        session.service_url     = service_url
        session.conversation_id = conversation_id
        session.user_id         = user_id

        # Persist the CAM's Teams contact details so future cycles can initiate proactively
        if user_email:
            try:
                save_cam_session(user_email, user_id, service_url, conversation_id)
            except Exception as _e:
                logger.debug("action=session_persist_failed error=%s", _e)

        if not session.started:
            # First contact — send the opening greeting
            greeting = session.start()
            _bf_reply(service_url, conversation_id, activity_id, greeting)
            logger.info("action=interview_started cam=%s user=%s", session.cam_name, user_id[:8])
        else:
            _bf_typing(service_url, conversation_id)
            if session.is_done:
                # Interview already finished — handle final wrap-up message gracefully
                if session.is_in_grace_period():
                    ack = session.accept_final_message(message_text)
                    _bf_reply(service_url, conversation_id, activity_id, ack)
                    logger.info("action=grace_reply_sent cam=%s", session.cam_name)
                else:
                    # Grace period expired — clean up and let the default "no interview" path
                    # handle any further messages
                    manager.remove_session(user_id)
                    logger.info("action=interview_complete cam=%s user=%s", session.cam_name, user_id[:8])
                    first_name = session.cam_name.split()[0]
                    _bf_reply(
                        service_url, conversation_id, activity_id,
                        f"Hey {first_name} — I think we already wrapped up earlier. "
                        f"You're all set! I'll be in touch for the next cycle.",
                    )
            else:
                # Normal mid-interview message
                next_msg = session.process(message_text)
                if next_msg:
                    _bf_reply(service_url, conversation_id, activity_id, next_msg)
                if session.is_done:
                    logger.info("action=interview_complete cam=%s user=%s", session.cam_name, user_id[:8])
                    # Keep session alive for grace period — do NOT remove yet

        return JSONResponse({"status": "ok"})

    except Exception as exc:
        logger.error("action=bot_message_error error=%s", exc, exc_info=True)
        return JSONResponse({"status": "error", "detail": str(exc)})


# ---------------------------------------------------------------------------
# Internal relay endpoint — GraphCAMResponder → ChatInterviewSession
# ---------------------------------------------------------------------------

@app.post("/internal/cam_message")
async def internal_cam_message(request: Request):
    """
    Relay a CAM response from GraphCAMResponder to the active interview session.

    GraphCAMResponder calls this after posting the user's reply to Teams so
    the interview engine can generate and deliver the next question via
    Bot Framework REST without needing a real BF webhook.

    Body: {"email": "alice@...", "text": "response text"}
    """
    try:
        body = await request.json()
        email = (body.get("email") or "").lower()
        text = (body.get("text") or "").strip()

        if not email or not text:
            return JSONResponse({"status": "ignored"})

        from agent.voice.teams_chat_connector import (
            ChatInterviewManager, _bf_send, _bf_typing,
        )
        manager = ChatInterviewManager.get()
        session = manager.get_session_by_email(email)

        if session is None:
            logger.debug("action=relay_no_session email=%s", email)
            return JSONResponse({"status": "no_session"})

        logger.info("action=relay_received email=%s text_len=%d", email, len(text))

        if session.service_url and session.conversation_id:
            _bf_typing(session.service_url, session.conversation_id)

        if session.is_done:
            # Interview already finished — check grace period
            if session.is_in_grace_period():
                ack = session.accept_final_message(text)
                if ack and session.service_url and session.conversation_id:
                    _bf_send(session.service_url, session.conversation_id, ack)
                logger.info("action=relay_grace_period_ack email=%s", email)
            else:
                # Grace window expired — remove stale session
                manager.remove_session_by_email(email)
                logger.info("action=relay_stale_session_removed email=%s", email)
            return JSONResponse({"status": "ok"})

        next_msg = session.process(text)

        if next_msg and session.service_url and session.conversation_id:
            _bf_send(session.service_url, session.conversation_id, next_msg)
            logger.info("action=relay_question_sent email=%s", email)

        if session.is_done:
            logger.info("action=relay_interview_complete email=%s", email)
            # Keep session alive for grace period; it will be cleaned up when
            # the grace window expires on the next message or explicit removal.

        return JSONResponse({"status": "ok"})

    except Exception as exc:
        logger.error("action=relay_error error=%s", exc, exc_info=True)
        return JSONResponse({"status": "error", "detail": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    uvicorn.run(app, host=host, port=port or _PORT, log_level="warning")
