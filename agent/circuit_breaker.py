"""
LLM circuit breaker — Phase 16 productionization.

When the Anthropic API returns a terminal billing error ("credit balance too
low", "insufficient quota", etc.), retrying makes things worse: we burn more
failed requests and rack up latency.  This module categorizes errors into
three buckets and exposes a simple open/closed circuit:

  TRANSIENT  — RateLimitError, APIConnectionError, 5xx           → retry with backoff
  TERMINAL   — BadRequestError (non-billing), bad prompt          → fail fast, no retry
  BILLING    — credit balance, insufficient quota, payment        → trip breaker, fail fast for N minutes

State is persisted to data/llm_circuit.json so a restart doesn't reset the
breaker.  The dashboard /health endpoint surfaces breaker state so ops sees
the alert.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

_STATE_FILE = os.getenv("LLM_CIRCUIT_STATE_FILE", "data/llm_circuit.json")
_OPEN_DURATION_SECONDS = int(os.getenv("LLM_CIRCUIT_OPEN_SECONDS", "900"))  # 15 min

_lock = threading.Lock()


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"
    TERMINAL = "terminal"
    BILLING = "billing"


# Substrings that identify a billing error in the response body.  Anthropic
# uses "credit balance is too low" — we also match a couple of other common
# phrases so this is robust to phrasing changes.
_BILLING_MARKERS = (
    "credit balance",
    "insufficient_quota",
    "insufficient quota",
    "billing_hard_limit",
    "payment required",
    "payment_required",
    "no balance",
)


def categorize(exc: BaseException) -> ErrorCategory:
    """Inspect an exception (Anthropic SDK or arbitrary) and return its category."""
    name = type(exc).__name__
    msg = str(exc).lower()

    # Billing — match first because it presents as a 4xx BadRequestError
    for marker in _BILLING_MARKERS:
        if marker in msg:
            return ErrorCategory.BILLING

    # SDK class names (string-match so we don't import the SDK in this module)
    if name in ("RateLimitError", "APIConnectionError", "APITimeoutError"):
        return ErrorCategory.TRANSIENT
    if name == "APIStatusError":
        status = getattr(exc, "status_code", 0) or 0
        if status >= 500:
            return ErrorCategory.TRANSIENT
        return ErrorCategory.TERMINAL
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return ErrorCategory.TERMINAL
    if name == "BadRequestError":
        return ErrorCategory.TERMINAL

    # Anything else — be conservative, mark transient so caller retries
    return ErrorCategory.TRANSIENT


def state() -> dict:
    """Return current circuit state.  closed = healthy."""
    p = Path(_STATE_FILE)
    if not p.exists():
        return {"status": "closed", "opened_at": None, "reason": None, "opens_until": None}
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "closed", "opened_at": None, "reason": None, "opens_until": None}
    # Auto-close when the open window has elapsed
    opens_until = s.get("opens_until")
    if opens_until:
        try:
            until_dt = datetime.fromisoformat(opens_until.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > until_dt:
                close()
                return {"status": "closed", "opened_at": None, "reason": None, "opens_until": None}
        except ValueError:
            pass
    return s


def is_open() -> bool:
    return state().get("status") == "open"


def open(reason: str, duration_seconds: int = _OPEN_DURATION_SECONDS) -> None:
    """Trip the breaker for `duration_seconds`."""
    with _lock:
        now = datetime.now(timezone.utc)
        until = now.timestamp() + duration_seconds
        until_dt = datetime.fromtimestamp(until, tz=timezone.utc)
        s = {
            "status": "open",
            "opened_at": now.isoformat(),
            "opens_until": until_dt.isoformat(),
            "duration_seconds": duration_seconds,
            "reason": reason,
        }
        _write(s)


def close() -> None:
    """Manually reset the breaker — e.g. after billing is topped up."""
    with _lock:
        p = Path(_STATE_FILE)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def handle_exception(exc: BaseException) -> ErrorCategory:
    """Call from an LLM error handler.  Trips the breaker on BILLING errors.

    Returns the category so the caller knows whether to retry, fail fast, etc.
    """
    cat = categorize(exc)
    if cat == ErrorCategory.BILLING:
        open(reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    return cat


class CircuitOpenError(RuntimeError):
    """Raised when an LLM call is attempted while the breaker is open."""

    def __init__(self, state_dict: dict) -> None:
        self.state = state_dict
        super().__init__(f"LLM circuit breaker is open: {state_dict.get('reason', 'unknown')}")


def guard() -> None:
    """Raise CircuitOpenError when the breaker is open.  No-op when closed."""
    s = state()
    if s.get("status") == "open":
        raise CircuitOpenError(s)


def _write(s: dict) -> None:
    p = Path(_STATE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    for attempt in range(3):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.1 * (2 ** attempt))
