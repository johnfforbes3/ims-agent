"""
Dashboard server — FastAPI + Jinja2 HTML dashboard for IMS Agent.

Serves:
  GET /            → HTML dashboard (auto-refreshes every 60s)
  GET /health      → health check (unauthenticated; used by Docker/load balancers)
  GET /metrics     → in-memory metrics snapshot (requires API key)
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


async def _require_api_key(api_key: str = Security(_api_key_header)) -> None:
    """Dependency: enforce X-API-Key when DASHBOARD_API_KEY is configured."""
    if not _API_KEY:
        return  # auth disabled in local dev mode
    if api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def _require_admin_key(
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

@app.get("/health")
async def health():
    """Unauthenticated health check — used by Docker, load balancers, and uptime monitors."""
    from agent.cycle_runner import CycleRunner
    state_exists = Path(_STATE_FILE).exists()
    return JSONResponse({
        "status": "healthy",
        "uptime_seconds": round(time.monotonic() - _START_TIME),
        "cycle_active": CycleRunner.is_active(),
        "state_file_present": state_exists,
        "auth_enabled": bool(_API_KEY),
    })


@app.get("/metrics", dependencies=[Depends(_require_api_key)])
async def api_metrics():
    """In-memory agent metrics snapshot (cycles, QA queries, duration)."""
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


@app.get("/api/status", dependencies=[Depends(_require_api_key)])
async def api_status():
    from agent.cycle_runner import CycleRunner
    return JSONResponse({"cycle_active": CycleRunner.is_active()})


@app.post("/api/trigger", dependencies=[Depends(_require_admin_key)])
async def api_trigger():
    """Admin: fire a cycle immediately in a background thread."""
    from agent.cycle_runner import CycleRunner
    if CycleRunner.is_active():
        raise HTTPException(status_code=409, detail="A cycle is already running")
    runner = CycleRunner(ims_path=_IMS_PATH)
    thread = threading.Thread(target=runner.run, daemon=True, name="manual_cycle")
    thread.start()
    logger.info("action=manual_trigger_api")
    return JSONResponse({"status": "triggered", "message": "Cycle started in background"})


@app.post("/api/admin/purge", dependencies=[Depends(_require_admin_key)])
async def api_admin_purge():
    """Admin: delete cycle status JSONs and IMS snapshots older than the retention window."""
    from agent.cycle_runner import CycleRunner
    deleted = CycleRunner.purge_old_data()
    logger.info("action=manual_purge deleted=%s", deleted)
    return JSONResponse({"status": "ok", "deleted": deleted})


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
        user_email    = from_obj.get("email", "") or from_obj.get("userPrincipalName", "")
        message_text  = (body.get("text") or "").strip()
        service_url   = body.get("serviceUrl", "")
        conversation  = body.get("conversation", {})
        conversation_id = conversation.get("id", "")
        activity_id   = body.get("id", "")

        if not message_text or not user_id:
            return JSONResponse({"status": "ok"})

        logger.info(
            "action=bot_message_received user=%s text_len=%d",
            user_id[:8] + "...", len(message_text),
        )

        from agent.voice.teams_chat_connector import (
            ChatInterviewManager, _bf_reply, _bf_typing,
        )

        manager = ChatInterviewManager.get()
        session = manager.get_or_start_session(user_id, user_email)

        if session is None:
            _bf_reply(
                service_url, conversation_id, activity_id,
                "Hi! I'm the ATLAS Scheduler. No interview is currently scheduled. "
                "You'll receive a message when it's time for your status check.",
            )
            return JSONResponse({"status": "ok"})

        # Store connection details for proactive use
        session.service_url    = service_url
        session.conversation_id = conversation_id

        if not session.started:
            # First contact — send the opening greeting
            greeting = session.start()
            _bf_reply(service_url, conversation_id, activity_id, greeting)
            logger.info("action=interview_started cam=%s user=%s", session.cam_name, user_id[:8])
        else:
            # Subsequent messages — show typing indicator, process, reply
            _bf_typing(service_url, conversation_id)
            next_msg = session.process(message_text)
            if next_msg:
                _bf_reply(service_url, conversation_id, activity_id, next_msg)
            if session.is_done:
                manager.remove_session(user_id)
                logger.info("action=interview_complete cam=%s user=%s", session.cam_name, user_id[:8])

        return JSONResponse({"status": "ok"})

    except Exception as exc:
        logger.error("action=bot_message_error error=%s", exc, exc_info=True)
        return JSONResponse({"status": "error", "detail": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    uvicorn.run(app, host=host, port=port or _PORT, log_level="warning")
