"""
OpenAI LLM wrapper for voice agent v2 — Phase 17.

Why a separate module from the existing `agent/llm_interface.py`:
    - The Phase 16 llm_interface.py is Anthropic-only (Claude). Mixing
      providers there would bloat its retry/circuit-breaker logic.
    - Voice agent v2 uses OpenAI exclusively (per user decision):
      gpt-4o-mini for normal turns, gpt-4o for variance-flagged turns.
    - We want a separate spend-cap circuit breaker (hard $USD cap) that's
      voice-only so a runaway loop here can't burn through the user's
      whole monthly budget. Article §7 in the productionization doc
      established the circuit-breaker pattern; this extends it.

Cost tracking:
    - Pricing constants below are the published OpenAI rates as of
      2026-05 (per million tokens). Update when OpenAI changes them.
    - Every call increments `voice_v2_spend.json` with the actual cost.
    - When cumulative spend > VOICE_AGENT_V2_MAX_SPEND_USD (default 25),
      every subsequent call raises SpendCapExceeded — fail fast, no retry.

Public surface:
    chat(messages, model="gpt-4o-mini", tools=None, ...) -> ChatResult
    chat_streaming(...)  -> async generator of delta chunks
    current_spend() -> {"total_usd": ..., "cap_usd": ..., "calls": ...}
    reset_spend()   -> wipe the spend file (admin override)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# Pricing as of 2026-05 — verify against https://openai.com/api/pricing
# Costs are USD per 1M tokens (cached input prices not used here).
_PRICING = {
    "gpt-4o-mini":  {"input": 0.15,  "output": 0.60},
    "gpt-4o":       {"input": 2.50,  "output": 10.00},
    "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},  # explicit version alias
    "whisper-1":    {"per_minute_usd": 0.006},  # not used for chat; tracked in stt_openai
}

_SPEND_FILE = Path(os.getenv("VOICE_AGENT_V2_SPEND_FILE", "data/voice_v2_spend.json"))
_MAX_SPEND_USD = float(os.getenv("VOICE_AGENT_V2_MAX_SPEND_USD", "25.00"))
_DEFAULT_MODEL = os.getenv("VOICE_AGENT_V2_MODEL", "gpt-4o-mini")
_HARD_MODEL    = os.getenv("VOICE_AGENT_V2_HARD_MODEL", "gpt-4o")

_lock = threading.Lock()


class SpendCapExceeded(RuntimeError):
    """Raised when cumulative voice agent v2 spend exceeds the hard cap."""

    def __init__(self, total_usd: float, cap_usd: float):
        self.total_usd = total_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"Voice agent v2 spend cap exceeded: ${total_usd:.4f} > ${cap_usd:.2f}. "
            f"Reset via agent.voice_v2.llm_openai.reset_spend() or raise "
            f"VOICE_AGENT_V2_MAX_SPEND_USD env var."
        )


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{name, args}]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    first_token_ms: int = 0
    total_ms: int = 0


def _read_spend() -> dict:
    if not _SPEND_FILE.exists():
        return {"total_usd": 0.0, "calls": 0, "first_call_at": None, "last_call_at": None}
    try:
        return json.loads(_SPEND_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"total_usd": 0.0, "calls": 0, "first_call_at": None, "last_call_at": None}


def _write_spend(s: dict) -> None:
    _SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SPEND_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    for attempt in range(3):
        try:
            os.replace(tmp, _SPEND_FILE)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.1 * (2 ** attempt))


def current_spend() -> dict:
    """Return current spend snapshot + cap."""
    s = _read_spend()
    return {**s, "cap_usd": _MAX_SPEND_USD, "headroom_usd": max(0.0, _MAX_SPEND_USD - s.get("total_usd", 0.0))}


def reset_spend() -> None:
    """Wipe the spend file. Admin override — use after intentional purges."""
    with _lock:
        if _SPEND_FILE.exists():
            _SPEND_FILE.unlink()


def _record_spend(cost_usd: float) -> None:
    """Atomically increment the persisted spend total."""
    with _lock:
        s = _read_spend()
        s["total_usd"] = round(s.get("total_usd", 0.0) + cost_usd, 6)
        s["calls"] = s.get("calls", 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        if not s.get("first_call_at"):
            s["first_call_at"] = now
        s["last_call_at"] = now
        _write_spend(s)


def _check_spend_cap() -> None:
    """Raise SpendCapExceeded when cumulative spend > cap. Called BEFORE each LLM call."""
    s = _read_spend()
    total = s.get("total_usd", 0.0)
    if total >= _MAX_SPEND_USD:
        raise SpendCapExceeded(total_usd=total, cap_usd=_MAX_SPEND_USD)


def _cost_for(model: str, in_tokens: int, out_tokens: int) -> float:
    """Compute call cost in USD from token counts."""
    p = _PRICING.get(model)
    if not p or "input" not in p:
        # Unknown model — return 0 so we don't fail, but log it for review.
        logger.warning("action=voice_v2_unknown_pricing model=%s", model)
        return 0.0
    return round((in_tokens / 1_000_000) * p["input"] + (out_tokens / 1_000_000) * p["output"], 6)


def _normalize_tools(tools: Optional[list[dict]]) -> Optional[list[dict]]:
    """Accept either raw OpenAI tool dicts or our simpler {name, description, parameters} shape."""
    if not tools:
        return None
    out = []
    for t in tools:
        if "type" in t and t["type"] == "function":
            out.append(t)
        elif "name" in t:
            out.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            })
    return out


def _extract_tool_calls(message: Any) -> list[dict]:
    """Pull tool_calls off an OpenAI message object → [{name, args}, ...]."""
    out = []
    raw = getattr(message, "tool_calls", None) or []
    for tc in raw:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {"_raw": tc.function.arguments or ""}
        out.append({"name": tc.function.name, "args": args, "id": tc.id})
    return out


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
    seed: Optional[int] = None,
) -> ChatResult:
    """One-shot OpenAI chat call. Records spend; raises SpendCapExceeded when over cap.

    Returns a ChatResult; either `text` is populated (no tool call needed) or
    `tool_calls` is populated (LLM chose to call one or more functions). Both
    can be populated for parallel tool calls + chatter.
    """
    _check_spend_cap()
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = model or _DEFAULT_MODEL

    t0 = time.monotonic()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if seed is not None:
        kwargs["seed"] = seed
    norm_tools = _normalize_tools(tools)
    if norm_tools:
        kwargs["tools"] = norm_tools
        kwargs["tool_choice"] = "auto"

    response = client.chat.completions.create(**kwargs)
    total_ms = round((time.monotonic() - t0) * 1000)

    msg = response.choices[0].message
    text = (msg.content or "").strip()
    tool_calls = _extract_tool_calls(msg)
    in_tok = response.usage.prompt_tokens
    out_tok = response.usage.completion_tokens
    cost = _cost_for(model, in_tok, out_tok)
    _record_spend(cost)

    return ChatResult(
        text=text,
        tool_calls=tool_calls,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        model=model,
        first_token_ms=total_ms,  # not streaming — same as total
        total_ms=total_ms,
    )


def chat_streaming(
    messages: list[dict],
    model: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> Iterator[dict]:
    """Streaming variant. Yields {type, ...} dicts:

        {"type": "delta", "text": "..."}            — incremental text
        {"type": "tool_call", "name": "...", ...}  — when complete
        {"type": "done", "result": ChatResult}      — final
    """
    _check_spend_cap()
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = model or _DEFAULT_MODEL

    t0 = time.monotonic()
    first_token_ms = 0
    accumulated = []
    tool_call_acc: dict[int, dict] = {}

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    norm_tools = _normalize_tools(tools)
    if norm_tools:
        kwargs["tools"] = norm_tools
        kwargs["tool_choice"] = "auto"

    in_tok = 0
    out_tok = 0
    for chunk in client.chat.completions.create(**kwargs):
        if first_token_ms == 0 and chunk.choices and chunk.choices[0].delta.content:
            first_token_ms = round((time.monotonic() - t0) * 1000)
        if chunk.choices:
            d = chunk.choices[0].delta
            if d.content:
                accumulated.append(d.content)
                yield {"type": "delta", "text": d.content}
            for tc in (d.tool_calls or []):
                idx = tc.index
                slot = tool_call_acc.setdefault(idx, {"name": "", "args_raw": ""})
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args_raw"] += tc.function.arguments
        if chunk.usage:
            in_tok = chunk.usage.prompt_tokens
            out_tok = chunk.usage.completion_tokens

    text = "".join(accumulated).strip()
    tool_calls = []
    for slot in tool_call_acc.values():
        try:
            args = json.loads(slot["args_raw"] or "{}")
        except Exception:
            args = {"_raw": slot["args_raw"]}
        tool_calls.append({"name": slot["name"], "args": args})
        yield {"type": "tool_call", "name": slot["name"], "args": args}

    cost = _cost_for(model, in_tok, out_tok)
    _record_spend(cost)
    yield {
        "type": "done",
        "result": ChatResult(
            text=text,
            tool_calls=tool_calls,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            model=model,
            first_token_ms=first_token_ms,
            total_ms=round((time.monotonic() - t0) * 1000),
        ),
    }
