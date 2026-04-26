"""
Dashboard server — FastAPI + Jinja2 HTML dashboard for IMS Agent.

Serves:
  GET /            → HTML dashboard (auto-refreshes every 60s)
  GET /health      → health check (unauthenticated; used by Docker/load balancers)
  GET /api/state   → current dashboard state JSON
  GET /api/history → cycle history JSON
  POST /api/trigger → admin: manually fire a cycle (async, returns immediately)
  GET /api/status  → is a cycle currently running?
  POST /api/ask    → Phase 4 Q&A: answer a natural language question

Authentication:
  Set DASHBOARD_API_KEY in .env to require X-API-Key header on all /api/* routes.
  If DASHBOARD_API_KEY is empty (default), auth is disabled (local dev mode).
"""

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
_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
_IMS_PATH = os.getenv("IMS_FILE_PATH", "data/sample_ims.xml")
_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

_START_TIME = time.monotonic()

app = FastAPI(title="IMS Agent Dashboard", docs_url=None, redoc_url=None)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _require_api_key(api_key: str = Security(_api_key_header)) -> None:
    """Dependency: enforce X-API-Key when DASHBOARD_API_KEY is configured."""
    if not _API_KEY:
        return  # auth disabled in local dev mode
    if api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

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


@app.post("/api/trigger", dependencies=[Depends(_require_api_key)])
async def api_trigger():
    """Admin override: fire a cycle immediately in a background thread."""
    from agent.cycle_runner import CycleRunner
    if CycleRunner.is_active():
        raise HTTPException(status_code=409, detail="A cycle is already running")
    runner = CycleRunner(ims_path=_IMS_PATH)
    thread = threading.Thread(target=runner.run, daemon=True, name="manual_cycle")
    thread.start()
    logger.info("action=manual_trigger_api")
    return JSONResponse({"status": "triggered", "message": "Cycle started in background"})


class _AskRequest(BaseModel):
    question: str


@app.post("/api/ask", dependencies=[Depends(_require_api_key)])
async def api_ask(body: _AskRequest):
    """Phase 4 Q&A — answer a natural language question about the schedule."""
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
# Entry point
# ---------------------------------------------------------------------------

def serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    uvicorn.run(app, host=host, port=port or _PORT, log_level="warning")
