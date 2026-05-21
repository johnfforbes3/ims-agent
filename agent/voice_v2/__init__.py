"""
Phase 17 — Voice Agent v2 (chained pipeline: STT → State Machine → LLM → TTS).

Isolated from the existing Phase 12+ `agent/voice/` package so the legacy
text-only Teams chat path is untouched and the rollback is trivial:
delete this directory + flip `VOICE_AGENT_V2=false`.

Architecture follows the May 2026 voice agent article — chained pipeline,
explicit state machine, dual safety guards, turn log with replay, and a
spend cap circuit breaker.

Module loading order (each is independently testable):
    turn_log       — JSONL turn schema + replay (article #1 priority)
    llm_openai     — OpenAI Chat Completions w/ cost tracking + spend cap
    state_machine  — Explicit FSM with per-state tool scoping
    guards         — Input + output safety checks
    stt_openai     — Whisper API STT
    tts            — ElevenLabs streaming TTS (wraps existing engine)
    pipeline       — Orchestrator wiring everything together
    transport_web  — WebSocket bridge for /voice/test browser page
"""

__version__ = "17.0.0-dev"
