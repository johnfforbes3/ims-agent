"""
Web tester transport — Phase 17.

FastAPI WebSocket bridge for the `/voice/test` browser page. The browser
captures mic audio via getUserMedia, posts it as binary frames over the
WebSocket; we run STT → pipeline → TTS and send back text + audio.

Wire protocol (server → client):
    {"type":"hello","cycle_id":"...","cams":[{"email","name","tasks":[...]}]}
    {"type":"state","state":"GREETING|OPEN_QUESTION|..."}
    {"type":"transcript","text":"..."}             — what STT heard
    {"type":"reply_text","text":"..."}             — what the agent says
    {"type":"reply_audio","mime":"audio/mpeg","b64":"..."}
    {"type":"tool","name":"...","args":{...}}
    {"type":"turn_summary","turn_id":"...","cost_usd":0.001,...}
    {"type":"error","detail":"..."}

Wire protocol (client → server):
    {"type":"select_cam","email":"alice@program.mil"}
    {"type":"audio","mime":"audio/webm","b64":"..."}    — full utterance after VAD
    {"type":"text","text":"..."}                        — text input fallback
    {"type":"reset"}                                    — start a new session
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.voice_v2 import pipeline
from agent.voice_v2.state_machine import State

logger = logging.getLogger(__name__)

_CAM_DIRECTORY_PATH = os.getenv("CAM_DIRECTORY_PATH", "data/cam_identity_map.json")


def _load_test_cams() -> list[dict]:
    """Build the CAM dropdown list. Pulls from cam_identity_map + dashboard state.

    Each CAM gets a small dummy task list so the interview has something to
    walk through. For real-cycle testing, the cycle_runner would supply real
    task data; for the tester we synthesize representative samples.
    """
    cams: list[dict] = []

    # Try real cam_identity_map first
    p = Path(_CAM_DIRECTORY_PATH)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            # cam_identity_map shape: {email: {name, teams_user_id, ...}}
            for email, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("display_name") or email
                cams.append({"email": email, "name": name, "tasks": _sample_tasks_for(name)})
        except Exception as exc:
            logger.warning("action=cam_dir_load_failed error=%s", exc)

    # Fallback: hardcoded test set
    if not cams:
        cams = [
            {"email": "alice@program.mil",  "name": "Alice Nguyen",  "tasks": _sample_tasks_for("Alice")},
            {"email": "bob@program.mil",    "name": "Bob Carter",    "tasks": _sample_tasks_for("Bob")},
            {"email": "carol@program.mil",  "name": "Carol Diaz",    "tasks": _sample_tasks_for("Carol")},
            {"email": "david@program.mil",  "name": "David Patel",   "tasks": _sample_tasks_for("David")},
            {"email": "eva@program.mil",    "name": "Eva Martinez",  "tasks": _sample_tasks_for("Eva")},
        ]

    return cams


def _sample_tasks_for(name: str) -> list[dict]:
    """Synthesized but consistent (hashable on name) test tasks."""
    h = sum(ord(c) for c in name)
    return [
        {"task_id": str(1 + h % 7),  "name": "Power subsystem design",      "percent_complete": 50 + h % 30, "baseline_finish": "2026-06-15"},
        {"task_id": str(10 + h % 5), "name": "Thermal qualification",       "percent_complete": 30 + h % 40, "baseline_finish": "2026-07-20"},
        {"task_id": str(20 + h % 3), "name": "Integration & test readiness", "percent_complete": 10 + h % 25, "baseline_finish": "2026-09-01"},
    ]


def _new_cycle_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def serve_websocket(websocket) -> None:
    """Main WebSocket handler. Caller wraps this in a FastAPI route.

    Lifecycle: accept → send hello → loop until client closes. One Session
    is created per `select_cam` message; resetting closes the old session
    and starts fresh.
    """
    await websocket.accept()
    cams = _load_test_cams()
    cycle_id = _new_cycle_id()

    await websocket.send_text(json.dumps({
        "type": "hello",
        "cycle_id": cycle_id,
        "cams": [{"email": c["email"], "name": c["name"]} for c in cams],
    }))

    session: Optional[pipeline.Session] = None
    selected_cam: Optional[dict] = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "detail": "bad JSON"}))
                continue

            msg_type = msg.get("type")

            if msg_type == "select_cam":
                email = msg.get("email")
                selected_cam = next((c for c in cams if c["email"] == email), None)
                if not selected_cam:
                    await websocket.send_text(json.dumps({
                        "type": "error", "detail": f"unknown CAM: {email}",
                    }))
                    continue
                session = pipeline.start_session(
                    cycle_id=cycle_id,
                    cam_email=selected_cam["email"],
                    cam_name=selected_cam["name"],
                    cam_tasks=selected_cam["tasks"],
                    transport="web_tester",
                )
                await websocket.send_text(json.dumps({
                    "type": "session_started",
                    "cam": {"email": selected_cam["email"], "name": selected_cam["name"]},
                    "tasks": selected_cam["tasks"],
                    "state": session.ctx.state.value,
                }))
                continue

            if msg_type == "reset":
                session = None
                selected_cam = None
                cycle_id = _new_cycle_id()
                await websocket.send_text(json.dumps({
                    "type": "reset_ack", "cycle_id": cycle_id,
                }))
                continue

            if not session:
                await websocket.send_text(json.dumps({
                    "type": "error", "detail": "no CAM selected — send select_cam first",
                }))
                continue

            if msg_type == "audio":
                b64 = msg.get("b64", "")
                mime = msg.get("mime", "audio/webm")
                if not b64:
                    await websocket.send_text(json.dumps({"type": "error", "detail": "empty audio"}))
                    continue
                audio_bytes = base64.b64decode(b64)
                # Pick a filename extension that matches the MIME so Whisper detects format
                ext = "webm" if "webm" in mime else "wav" if "wav" in mime else "mp3"
                filename = f"utt.{ext}"
                turn = session.process_audio_bytes(audio_bytes, filename=filename)
                await _emit_turn(websocket, turn)
                continue

            if msg_type == "text":
                text = (msg.get("text") or "").strip()
                if not text:
                    await websocket.send_text(json.dumps({"type": "error", "detail": "empty text"}))
                    continue
                turn = session.process_transcript(text)
                await _emit_turn(websocket, turn, transcript_echo=text)
                continue

            await websocket.send_text(json.dumps({
                "type": "error", "detail": f"unknown msg type: {msg_type}",
            }))
    except Exception as exc:
        logger.error("action=ws_handler_error error=%s", exc, exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "detail": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _emit_turn(websocket, turn: pipeline.OrchestratedTurn,
                     transcript_echo: Optional[str] = None) -> None:
    """Serialize an OrchestratedTurn into WS frames."""
    # Transcript first so the UI shows what we heard
    if transcript_echo is not None:
        await websocket.send_text(json.dumps({"type": "transcript", "text": transcript_echo}))
    elif turn.transcript:
        await websocket.send_text(json.dumps({"type": "transcript", "text": turn.transcript}))

    # Tool calls (informational — UI shows them in a side panel)
    for tc in (turn.tool_calls or []):
        await websocket.send_text(json.dumps({
            "type": "tool", "name": tc.get("name"), "args": tc.get("args", {}),
        }))

    # State update
    await websocket.send_text(json.dumps({
        "type": "state",
        "state": turn.state_after.value,
        "previous": turn.state_before.value,
    }))

    # Agent's reply text
    if turn.reply_text:
        await websocket.send_text(json.dumps({
            "type": "reply_text", "text": turn.reply_text,
        }))

    # Audio (base64) — only when we have bytes
    if turn.audio_bytes:
        await websocket.send_text(json.dumps({
            "type": "reply_audio",
            "mime": "audio/mpeg",
            "b64": base64.b64encode(turn.audio_bytes).decode("ascii"),
            "voice": turn.voice_id,
        }))

    # Turn summary (cost, latency, etc.) — for the metrics panel
    await websocket.send_text(json.dumps({
        "type": "turn_summary",
        "turn_id": turn.turn_id,
        "llm_cost_usd": turn.llm_cost_usd,
        "llm_first_token_ms": turn.llm_first_token_ms,
        "llm_total_ms": turn.llm_total_ms,
        "tts_first_audio_ms": turn.audio_first_byte_ms,
        "input_guard": {
            "passed": turn.input_guard.passed,
            "categories": turn.input_guard.categories,
        },
        "output_guard": {
            "passed": turn.output_guard.passed,
            "categories": turn.output_guard.categories,
        },
        "error": turn.error,
    }))
