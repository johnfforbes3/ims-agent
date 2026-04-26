"""
In-memory metrics counters for the IMS Agent.

Thread-safe module-level counters incremented by cycle_runner and qa_engine.
Reset on process restart — no persistence required for Phase 5 MVP.

Exposed at GET /metrics by the dashboard server.
"""

import threading
from typing import Any

_lock = threading.Lock()

_counters: dict[str, Any] = {
    "cycles_completed": 0,
    "cycles_failed": 0,
    "last_cycle_id": None,
    "last_cycle_duration_seconds": None,
    "qa_queries_total": 0,
    "qa_queries_direct": 0,
    "qa_queries_llm": 0,
}


def increment(key: str, amount: int = 1) -> None:
    with _lock:
        if key in _counters and isinstance(_counters[key], int):
            _counters[key] += amount


def set_value(key: str, value: Any) -> None:
    with _lock:
        _counters[key] = value


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_counters)
