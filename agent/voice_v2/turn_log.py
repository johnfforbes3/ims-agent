"""
Voice agent turn log — Phase 17.

Article §11 #1 — "Build the turn log schema on day one, not week four. The
replay endpoint is the most valuable tool I built and I built it after I
needed it."

Every turn writes one row to `data/voice_turns/{cycle_id}.jsonl`. The schema
is intentionally flat (no nested optional objects beyond two levels) so
`jq`-style ad-hoc queries work directly against the file.

A turn is a complete user-speak → agent-respond round-trip. We log
component-level latencies so we can spot bottlenecks during the article's
weekly review loop.

Schema (see TurnLogEntry dataclass):
    turn_id              — globally-unique, format: {cycle_id}-{seq:04d}
    cycle_id             — IMS cycle ID this turn belongs to
    cam_email            — CAM identity
    cam_name
    state_before / _after — state machine transitions (article §4)
    audio_in_ms          — duration of CAM's spoken input
    stt_first_partial_ms — time from first audio chunk to first STT word
    stt_final_ms         — total STT processing time
    stt_transcript       — final transcribed text
    end_of_turn_signal   — "semantic" (model) | "silence" (fallback)
    input_guard          — {passed, categories, redactions}
    llm_provider         — "openai"
    llm_model            — "gpt-4o-mini" or "gpt-4o"
    llm_first_token_ms
    llm_full_response_ms
    llm_text_out
    llm_tool_calls       — [{name, args}, ...] — empty list when none
    llm_input_tokens / llm_output_tokens / llm_cost_usd  — for spend tracking
    output_guard         — {passed, categories, rewrites}
    tts_first_audio_ms
    tts_full_audio_ms
    tts_voice_id
    end_to_end_ms        — total turn latency for the article's L1 metric
    transport            — "web_tester" | "teams_voice_msg" | "test_eval"
    dry_run              — True when VOICE_AGENT_V2_DRY=true (no IMS write)
    error                — populated on failure; None otherwise

REPLAY:
    `replay_turn(turn_id, pipeline)` re-runs the turn's transcript through
    the **current** state machine + LLM + guard config, returning a new
    TurnLogEntry. Used by `POST /api/voice/replay/{turn_id}` to A/B test
    config changes against last week's actual conversations.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_TURN_DIR = Path(os.getenv("VOICE_TURN_LOG_DIR", "data/voice_turns"))
_TURN_DIR.mkdir(parents=True, exist_ok=True)
_seq_lock = threading.Lock()
_seq_counters: dict[str, int] = {}


def _next_seq(cycle_id: str) -> int:
    """Monotonic per-cycle sequence counter. Thread-safe."""
    with _seq_lock:
        n = _seq_counters.get(cycle_id, 0) + 1
        _seq_counters[cycle_id] = n
        return n


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GuardResult:
    passed: bool = True
    categories: list[str] = field(default_factory=list)
    rewrites: list[str] = field(default_factory=list)


@dataclass
class TurnLogEntry:
    """One round-trip of a voice conversation."""

    # Identity
    turn_id: str
    cycle_id: str
    cam_email: str = ""
    cam_name: str = ""
    timestamp_utc: str = field(default_factory=_now_iso)

    # State machine
    state_before: str = ""
    state_after: str = ""

    # STT
    audio_in_ms: int = 0
    stt_first_partial_ms: int = 0
    stt_final_ms: int = 0
    stt_transcript: str = ""
    end_of_turn_signal: str = "silence"

    # Guards
    input_guard: dict = field(default_factory=lambda: asdict(GuardResult()))

    # LLM
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_first_token_ms: int = 0
    llm_full_response_ms: int = 0
    llm_text_out: str = ""
    llm_tool_calls: list[dict] = field(default_factory=list)
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_usd: float = 0.0

    output_guard: dict = field(default_factory=lambda: asdict(GuardResult()))

    # TTS
    tts_first_audio_ms: int = 0
    tts_full_audio_ms: int = 0
    tts_voice_id: str = ""

    # Roll-up
    end_to_end_ms: int = 0
    transport: str = ""
    dry_run: bool = False
    error: Optional[str] = None


def new_turn(cycle_id: str, cam_email: str = "", cam_name: str = "",
             transport: str = "web_tester") -> TurnLogEntry:
    """Allocate a new turn with a unique id. Caller mutates and then `append()`s."""
    seq = _next_seq(cycle_id)
    return TurnLogEntry(
        turn_id=f"{cycle_id}-{seq:04d}",
        cycle_id=cycle_id,
        cam_email=cam_email,
        cam_name=cam_name,
        transport=transport,
    )


def append(entry: TurnLogEntry) -> Path:
    """Atomically append one JSONL row to the cycle's log file."""
    _TURN_DIR.mkdir(parents=True, exist_ok=True)
    path = _TURN_DIR / f"{entry.cycle_id}.jsonl"
    line = json.dumps(asdict(entry), default=str) + "\n"
    # Append is atomic in Python on Windows + POSIX for small lines; no extra lock needed.
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
    return path


def read_cycle(cycle_id: str) -> list[TurnLogEntry]:
    """Load all turns for a cycle. Newest last (file order = chronological)."""
    path = _TURN_DIR / f"{cycle_id}.jsonl"
    if not path.exists():
        return []
    out: list[TurnLogEntry] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(TurnLogEntry(**d))
            except Exception:
                # Skip malformed rows rather than crash the whole read
                continue
    return out


def find_turn(turn_id: str) -> Optional[TurnLogEntry]:
    """Locate one turn by id. Walks every log file; cheap enough for our cycle counts."""
    if "-" not in turn_id:
        return None
    cycle_id = turn_id.rsplit("-", 1)[0]
    for entry in read_cycle(cycle_id):
        if entry.turn_id == turn_id:
            return entry
    # Fallback: scan all cycle files (slow path)
    for path in _TURN_DIR.glob("*.jsonl"):
        for entry in read_cycle(path.stem):
            if entry.turn_id == turn_id:
                return entry
    return None


def replay_turn(turn_id: str, pipeline) -> Optional[TurnLogEntry]:
    """Re-run a logged turn against the current pipeline config.

    `pipeline` must expose `.process_transcript(transcript, cam_email,
    cam_name, state_before) -> TurnLogEntry` — the pipeline orchestrator
    implements this interface.

    Useful for: "did my prompt change to the COMMIT state actually improve
    the LLM's confirmation reply?" Replay the same transcript against the
    new config; compare the two TurnLogEntry rows side-by-side.
    """
    original = find_turn(turn_id)
    if not original:
        return None
    return pipeline.process_transcript(
        transcript=original.stt_transcript,
        cam_email=original.cam_email,
        cam_name=original.cam_name,
        state_before=original.state_before,
    )


# Convenience: a context-manager-style turn helper that auto-appends on close.
class TurnRecorder:
    """Use as `with TurnRecorder(cycle_id, ...) as turn: turn.stt_transcript = ...`.

    On `__exit__`, the turn is appended. If an exception was raised, the
    `error` field is populated with the exception text before append.
    """

    def __init__(self, cycle_id: str, **kwargs):
        self.entry = new_turn(cycle_id, **kwargs)
        self._t0 = 0.0

    def __enter__(self) -> TurnLogEntry:
        self._t0 = time.monotonic()
        return self.entry

    def __exit__(self, exc_type, exc, tb) -> None:
        self.entry.end_to_end_ms = round((time.monotonic() - self._t0) * 1000)
        if exc is not None:
            self.entry.error = f"{exc_type.__name__}: {exc}"
        append(self.entry)
        return None
