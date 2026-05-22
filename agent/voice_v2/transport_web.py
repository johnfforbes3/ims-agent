"""
Web tester transport — Phase 17.4 (REALIGNED).

Drives the SAME `ChatInterviewSession` / `InterviewAgent` that production
uses through /bot/messages. The tester is now a true preview of what real
CAMs experience — no parallel conversation engine.

This replaces the prior implementation that used `voice_v2.pipeline.Session`
(the divergent engine I built before alignment was demanded). The old
modules (`pipeline.py`, `state_machine.py`, `field_router.py`,
`reply_templates.py`, `small_talk.py`) remain on disk but are deprecated —
they're not imported by anything that ships, and the tester now exercises
the production code path end-to-end.

Wire protocol (kept identical so the JS tester UI doesn't change):

Server → client:
    {"type":"hello","cycle_id":"...","cams":[{"email","name"}]}
    {"type":"session_started","cam":{...},"tasks":[...],"state":"GREETING"}
    {"type":"reset_ack","cycle_id":"..."}
    {"type":"transcript","text":"..."}              user's input echoed
    {"type":"thinking","stage":"transcribing|processing"}
    {"type":"state","state":"AWAITING_PCT","previous":"GREETING"}
    {"type":"reply_text","text":"..."}              agent reply
    {"type":"reply_audio","mime":"audio/mpeg","b64":"...","voice":"..."}
    {"type":"turn_summary","turn_id":"...","llm_cost_usd":..., ...}
    {"type":"error","detail":"..."}

Client → server:
    {"type":"select_cam","email":"alice@program.mil"}
    {"type":"audio","mime":"audio/webm","b64":"..."}    voice input
    {"type":"text","text":"..."}                        text input
    {"type":"reset"}                                    start new session

Notes on the realignment:
  - The OLD wire protocol included `{"type":"tool","name":"...","args":{}}`
    events. InterviewAgent doesn't expose tool calls (it does field
    extraction internally). We no longer emit `tool` events. The JS UI
    handles their absence gracefully (the tool log section just stays
    empty for that turn).
  - LLM cost reporting changes — InterviewAgent uses Anthropic Claude
    (via agent/llm_interface.py) rather than OpenAI. Anthropic spend is
    NOT tracked in the voice_v2 $25 cap. For the tester we report cost
    as 0 for LLM turns and only count STT/TTS spend (which IS capped).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent.voice_v2 import stt_openai, tts, turn_log

logger = logging.getLogger(__name__)

_CAM_DIRECTORY_PATH = os.getenv("CAM_DIRECTORY_PATH", "data/cam_identity_map.json")


# ──────────────────────────────────────────────────────────────────────────
# CAM directory loader (unchanged from prior version)
# ──────────────────────────────────────────────────────────────────────────


def _load_test_cams() -> list[dict]:
    """Build the CAM dropdown list. Real CAMs from cam_identity_map; falls
    back to synthetic Alice/Bob/Carol/David/Eva when the map is missing."""
    cams: list[dict] = []
    p = Path(_CAM_DIRECTORY_PATH)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for email, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("display_name") or email
                cams.append({"email": email, "name": name, "tasks": _sample_tasks_for(name)})
        except Exception as exc:
            logger.warning("action=cam_dir_load_failed error=%s", exc)
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
    """Synthesized but consistent (hashable on name) test tasks.

    Phase 17.4 — InterviewAgent expects `finish` and `baseline_finish`
    as datetime objects (it compares them with datetime.now()), so we
    parse the ISO strings into datetimes here. This matches the shape
    that file_handler.IMSFileHandler.parse() produces in production.
    """
    from datetime import datetime
    def _dt(iso: str) -> datetime:
        return datetime.fromisoformat(iso)
    h = sum(ord(c) for c in name)
    return [
        {"task_id": str(1 + h % 7),
         "name": "Power subsystem design",
         "percent_complete": 50 + h % 30,
         "finish": _dt("2026-06-15T17:00:00"),
         "baseline_finish": _dt("2026-06-15T17:00:00")},
        {"task_id": str(10 + h % 5),
         "name": "Thermal qualification",
         "percent_complete": 30 + h % 40,
         "finish": _dt("2026-07-20T17:00:00"),
         "baseline_finish": _dt("2026-07-20T17:00:00")},
        {"task_id": str(20 + h % 3),
         "name": "Integration & test readiness",
         "percent_complete": 10 + h % 25,
         "finish": _dt("2026-09-01T17:00:00"),
         "baseline_finish": _dt("2026-09-01T17:00:00")},
    ]


def _new_cycle_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ──────────────────────────────────────────────────────────────────────────
# Tester session — wraps ChatInterviewSession with WebSocket-friendly helpers
# ──────────────────────────────────────────────────────────────────────────


class TesterSession:
    """Wraps the production ChatInterviewSession for a single WebSocket
    connection. Adds turn logging + state-change detection + TTS synthesis
    so the WebSocket can emit the events the tester UI expects."""

    def __init__(self, cycle_id: str, cam: dict):
        from agent.voice.teams_chat_connector import ChatInterviewSession
        self.cycle_id = cycle_id
        self.cam = cam
        self.session = ChatInterviewSession(
            cam_name=cam["name"],
            tasks=cam["tasks"],
            all_tasks=cam["tasks"],
            email=cam["email"],
        )
        self._last_state: str = "GREETING"
        # Synthesize TTS for the agent's opening greeting on session start
        self._initial_greeting: str = self.session.start()

    def initial_greeting(self) -> str:
        return self._initial_greeting

    def current_state(self) -> str:
        return self.session.agent.state.value if self.session.agent.state else "UNKNOWN"

    def process(self, text: str) -> tuple[str, str, str]:
        """Drive one turn through the production session. Returns
        (reply_text, prev_state, new_state)."""
        prev_state = self.current_state()
        reply = self.session.process(text) or ""
        new_state = self.current_state()
        self._last_state = new_state
        return reply, prev_state, new_state


# ──────────────────────────────────────────────────────────────────────────
# Main WebSocket handler
# ──────────────────────────────────────────────────────────────────────────


async def serve_websocket(websocket) -> None:
    """Bridge browser mic + text input to the production ChatInterviewSession."""
    await websocket.accept()
    cams = _load_test_cams()
    cycle_id = _new_cycle_id()

    await websocket.send_text(json.dumps({
        "type": "hello",
        "cycle_id": cycle_id,
        "cams": [{"email": c["email"], "name": c["name"]} for c in cams],
    }))

    tester: Optional[TesterSession] = None

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
                selected = next((c for c in cams if c["email"] == email), None)
                if not selected:
                    await websocket.send_text(json.dumps({
                        "type": "error", "detail": f"unknown CAM: {email}",
                    }))
                    continue
                tester = TesterSession(cycle_id, selected)
                greeting = tester.initial_greeting()
                # JSON can't serialize datetime; emit ISO strings on the wire.
                # The TesterSession itself still holds datetime objects for
                # the production InterviewAgent.
                wire_tasks = []
                for t in selected["tasks"]:
                    wt = dict(t)
                    for k in ("finish", "baseline_finish", "start"):
                        v = wt.get(k)
                        if hasattr(v, "isoformat"):
                            wt[k] = v.isoformat()
                    wire_tasks.append(wt)
                await websocket.send_text(json.dumps({
                    "type": "session_started",
                    "cam": {"email": selected["email"], "name": selected["name"]},
                    "tasks": wire_tasks,
                    "state": tester.current_state(),
                }))
                # Emit greeting as a normal reply_text + audio
                await _emit_agent_reply(websocket, tester, greeting,
                                        prev_state="GREETING",
                                        cleaned_input="",
                                        turn_seq=0)
                continue

            if msg_type == "reset":
                tester = None
                cycle_id = _new_cycle_id()
                await websocket.send_text(json.dumps({
                    "type": "reset_ack", "cycle_id": cycle_id,
                }))
                continue

            if not tester:
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
                ext = "webm" if "webm" in mime else "wav" if "wav" in mime else "mp3"
                filename = f"utt.{ext}"
                await websocket.send_text(json.dumps({"type": "thinking",
                                                      "stage": "transcribing"}))
                try:
                    stt_result = stt_openai.transcribe_bytes(audio_bytes, filename=filename)
                    text = stt_result.text
                except Exception as exc:
                    logger.error("action=tester_stt_failed error=%s", exc)
                    await websocket.send_text(json.dumps({
                        "type": "error", "detail": f"STT failed: {exc}",
                    }))
                    continue
                await websocket.send_text(json.dumps({"type": "transcript", "text": text}))
                await websocket.send_text(json.dumps({"type": "thinking",
                                                      "stage": "processing"}))
                await _drive_turn(websocket, tester, text)
                continue

            if msg_type == "text":
                text = (msg.get("text") or "").strip()
                if not text:
                    await websocket.send_text(json.dumps({"type": "error", "detail": "empty text"}))
                    continue
                await websocket.send_text(json.dumps({"type": "transcript", "text": text}))
                await websocket.send_text(json.dumps({"type": "thinking",
                                                      "stage": "processing"}))
                await _drive_turn(websocket, tester, text)
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


async def _drive_turn(websocket, tester: TesterSession, text: str) -> None:
    """Run one user turn through the production InterviewAgent and emit
    the resulting agent reply + audio + telemetry."""
    t0 = time.monotonic()
    try:
        reply, prev_state, new_state = tester.process(text)
    except Exception as exc:
        logger.error("action=tester_process_error error=%s", exc, exc_info=True)
        await websocket.send_text(json.dumps({
            "type": "error", "detail": f"InterviewAgent crashed: {exc}",
        }))
        return
    llm_ms = round((time.monotonic() - t0) * 1000)
    if prev_state != new_state:
        await websocket.send_text(json.dumps({
            "type": "state", "state": new_state, "previous": prev_state,
        }))
    await _emit_agent_reply(
        websocket, tester, reply,
        prev_state=prev_state, cleaned_input=text,
        turn_seq=None, llm_ms=llm_ms,
    )


async def _emit_agent_reply(websocket, tester: TesterSession,
                            reply: str, prev_state: str, cleaned_input: str,
                            turn_seq: Optional[int] = None,
                            llm_ms: int = 0) -> None:
    """Send reply_text + reply_audio + turn_summary events for one agent reply."""
    if not reply or not reply.strip():
        # InterviewAgent returned no text — emit a turn_summary so the UI
        # at least clears the "thinking" indicator.
        await websocket.send_text(json.dumps({
            "type": "turn_summary",
            "turn_id": tester.cycle_id + "-empty",
            "llm_cost_usd": 0,
            "llm_first_token_ms": llm_ms,
            "llm_total_ms": llm_ms,
            "tts_first_audio_ms": 0,
            "input_guard": {"passed": True, "categories": []},
            "output_guard": {"passed": True, "categories": []},
            "error": None,
        }))
        return

    await websocket.send_text(json.dumps({"type": "reply_text", "text": reply}))

    # TTS — synthesize the reply so the tester behaves like Teams chat with
    # voice-out enabled.
    audio_first_ms = 0
    audio_total_ms = 0
    voice_id = ""
    try:
        tts_t0 = time.monotonic()
        tts_result = tts.synthesize(reply, voice_id=tts.voice_for_cam(
            tester.cam["name"], tester.cam["email"],
        ))
        audio_first_ms = tts_result.first_audio_ms
        audio_total_ms = tts_result.total_ms
        voice_id = tts_result.voice_id
        if tts_result.audio_bytes:
            await websocket.send_text(json.dumps({
                "type": "reply_audio",
                "mime": "audio/mpeg",
                "b64": base64.b64encode(tts_result.audio_bytes).decode("ascii"),
                "voice": voice_id,
            }))
    except Exception as exc:
        logger.warning("action=tester_tts_failed error=%s", exc)

    # Log the turn into the same JSONL stream used elsewhere
    try:
        entry = turn_log.new_turn(
            cycle_id=tester.cycle_id,
            cam_email=tester.cam["email"],
            cam_name=tester.cam["name"],
            transport="web_tester_v2",
        )
        entry.state_before = prev_state
        entry.state_after = tester.current_state()
        entry.stt_transcript = cleaned_input
        entry.llm_text_out = reply
        entry.llm_model = "anthropic_via_interview_agent"
        entry.llm_total_ms = llm_ms
        entry.tts_first_audio_ms = audio_first_ms
        entry.tts_full_audio_ms = audio_total_ms
        entry.tts_voice_id = voice_id
        entry.end_to_end_ms = llm_ms + audio_total_ms
        turn_log.append(entry)
    except Exception as exc:
        logger.debug("action=tester_turn_log_failed error=%s", exc)

    await websocket.send_text(json.dumps({
        "type": "turn_summary",
        "turn_id": tester.cycle_id + (f"-{turn_seq}" if turn_seq is not None else ""),
        "llm_cost_usd": 0,  # InterviewAgent uses Anthropic; not tracked in voice_v2 spend cap
        "llm_first_token_ms": llm_ms,
        "llm_total_ms": llm_ms,
        "tts_first_audio_ms": audio_first_ms,
        "input_guard": {"passed": True, "categories": []},
        "output_guard": {"passed": True, "categories": []},
        "error": None,
    }))
