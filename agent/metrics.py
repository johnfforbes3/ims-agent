"""
In-memory metrics counters for the IMS Agent.

Thread-safe module-level counters incremented by cycle_runner and qa_engine.
Reset on process restart — no persistence required.

Exposed at GET /metrics by the dashboard server (JSON or Prometheus format).

Phase 6.1 additions:
- last_cycle_completed_at  — ISO timestamp for dead man's switch
- last_cycle_cam_response_rate — CAM response rate for last cycle
- cycle_duration_history   — ring buffer of last 20 durations (P50/P95)
- qa_response_latency_history — ring buffer of last 20 QA latency_ms (P50/P95)
"""

import threading
from typing import Any

_lock = threading.Lock()

_MAX_HISTORY = 20  # ring-buffer depth for P50/P95 computation

_counters: dict[str, Any] = {
    "cycles_completed": 0,
    "cycles_failed": 0,
    "last_cycle_id": None,
    "last_cycle_duration_seconds": None,
    "last_cycle_completed_at": None,       # ISO-8601 — for dead man's switch
    "last_cycle_cam_response_rate": None,  # float 0.0–1.0
    "qa_queries_total": 0,
    "qa_queries_direct": 0,
    "qa_queries_llm": 0,
    # Ring buffers — never exposed directly in snapshot(); use percentile() instead
    "_cycle_duration_history": [],
    "_qa_latency_ms_history": [],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def increment(key: str, amount: int = 1) -> None:
    """Increment an integer counter by *amount*. Silently ignores unknown keys."""
    with _lock:
        if key in _counters and isinstance(_counters[key], int):
            _counters[key] += amount


def set_value(key: str, value: Any) -> None:
    """Set a counter/gauge to an arbitrary value."""
    with _lock:
        _counters[key] = value


def record_cycle_duration(seconds: float) -> None:
    """Append a cycle duration (seconds) to the ring buffer."""
    with _lock:
        hist = _counters["_cycle_duration_history"]
        hist.append(float(seconds))
        if len(hist) > _MAX_HISTORY:
            del hist[:-_MAX_HISTORY]


def record_qa_latency(ms: float) -> None:
    """Append a Q&A response latency (milliseconds) to the ring buffer."""
    with _lock:
        hist = _counters["_qa_latency_ms_history"]
        hist.append(float(ms))
        if len(hist) > _MAX_HISTORY:
            del hist[:-_MAX_HISTORY]


def percentile(key: str, pct: float) -> float | None:
    """
    Return the *pct*-th percentile of the named ring buffer.

    Args:
        key: ``"cycle_duration_seconds"`` or ``"qa_latency_ms"``
        pct: 0.0–1.0  (e.g. 0.50 for P50, 0.95 for P95)

    Returns:
        The percentile value, or ``None`` if the buffer is empty.
    """
    buf_key = f"_{key.replace('-', '_')}_history"
    with _lock:
        data = list(_counters.get(buf_key, []))
    if not data:
        return None
    data.sort()
    idx = max(0, int(pct * len(data)) - 1)
    return data[idx]


def snapshot() -> dict[str, Any]:
    """
    Return a copy of the public counters plus computed percentile SLIs.

    Ring-buffer keys (``_*_history``) are excluded; computed percentiles are
    injected as ``cycle_duration_p50_seconds``, ``cycle_duration_p95_seconds``,
    ``qa_latency_p50_ms``, ``qa_latency_p95_ms``.
    """
    with _lock:
        raw = {k: v for k, v in _counters.items() if not k.startswith("_")}
        dur_hist = list(_counters["_cycle_duration_history"])
        qa_hist = list(_counters["_qa_latency_ms_history"])

    def _pct(data: list, p: float) -> float | None:
        if not data:
            return None
        s = sorted(data)
        return s[max(0, int(p * len(s)) - 1)]

    raw["cycle_duration_p50_seconds"] = _pct(dur_hist, 0.50)
    raw["cycle_duration_p95_seconds"] = _pct(dur_hist, 0.95)
    raw["qa_latency_p50_ms"] = _pct(qa_hist, 0.50)
    raw["qa_latency_p95_ms"] = _pct(qa_hist, 0.95)
    return raw


def prometheus_text() -> str:
    """
    Render current metrics in Prometheus text exposition format.

    Suitable for scraping by Prometheus, Grafana Agent, or any OpenMetrics
    compatible collector. Returned as ``text/plain; version=0.0.4``.
    """
    s = snapshot()

    def _g(metric: str, value: Any, help_text: str, mtype: str = "gauge") -> list[str]:
        if value is None:
            return []
        return [
            f"# HELP {metric} {help_text}",
            f"# TYPE {metric} {mtype}",
            f"{metric} {value}",
        ]

    lines: list[str] = []

    lines += _g("ims_cycles_completed_total",
                s.get("cycles_completed"),
                "Total successful IMS cycles completed", "counter")

    lines += _g("ims_cycles_failed_total",
                s.get("cycles_failed"),
                "Total IMS cycles that ended in failure", "counter")

    lines += _g("ims_last_cycle_duration_seconds",
                s.get("last_cycle_duration_seconds"),
                "Duration of the most recent cycle in seconds", "gauge")

    lines += _g("ims_cycle_duration_p50_seconds",
                s.get("cycle_duration_p50_seconds"),
                "P50 cycle duration over the last 20 cycles (seconds)", "gauge")

    lines += _g("ims_cycle_duration_p95_seconds",
                s.get("cycle_duration_p95_seconds"),
                "P95 cycle duration over the last 20 cycles (seconds)", "gauge")

    lines += _g("ims_cam_response_rate",
                s.get("last_cycle_cam_response_rate"),
                "CAM response rate for the most recent cycle (0.0–1.0)", "gauge")

    lines += _g("ims_qa_queries_total",
                s.get("qa_queries_total"),
                "Total Q&A queries received", "counter")

    lines += _g("ims_qa_queries_direct_total",
                s.get("qa_queries_direct"),
                "Q&A queries answered directly (no LLM call)", "counter")

    lines += _g("ims_qa_queries_llm_total",
                s.get("qa_queries_llm"),
                "Q&A queries routed to LLM", "counter")

    lines += _g("ims_qa_latency_p50_ms",
                s.get("qa_latency_p50_ms"),
                "P50 Q&A response latency over the last 20 queries (ms)", "gauge")

    lines += _g("ims_qa_latency_p95_ms",
                s.get("qa_latency_p95_ms"),
                "P95 Q&A response latency over the last 20 queries (ms)", "gauge")

    lines.append("")  # Prometheus expects trailing newline
    return "\n".join(lines)
