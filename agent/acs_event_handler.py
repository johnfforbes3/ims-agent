"""
ACS Event Bus — thread-safe synchronization for Azure Communication Services
Call Automation webhook events.

The FastAPI /acs/callback route receives CloudEvent payloads and routes them
here. The demo interview runner blocks on this bus to synchronize its
sequential interview loop with ACS's async event model.

Architecture:
    FastAPI thread (webhook) → event_bus.handle() → sets threading.Event
    Interview thread          ← event_bus.wait_for_*() ← blocks on Event
"""
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class ACSEventBus:
    """Thread-safe event bus for ACS Call Automation webhook events."""

    def __init__(self) -> None:
        self._call_connected = threading.Event()
        self._play_done = threading.Event()
        self._call_disconnected = threading.Event()
        self._call_connection_id: str | None = None
        self._last_play_succeeded: bool = True
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Called from the FastAPI /acs/callback route (server thread)
    # ------------------------------------------------------------------

    def handle(self, event_type: str, data: dict[str, Any]) -> None:
        """Route an incoming ACS CloudEvent to the appropriate signal."""
        logger.info(
            "action=acs_event type=%s cid=%s",
            event_type,
            data.get("callConnectionId", "?"),
        )

        if event_type == "Microsoft.Communication.CallConnected":
            with self._lock:
                self._call_connection_id = data.get("callConnectionId")
            self._call_connected.set()

        elif event_type == "Microsoft.Communication.PlayCompleted":
            with self._lock:
                self._last_play_succeeded = True
            self._play_done.set()

        elif event_type in (
            "Microsoft.Communication.PlayFailed",
            "Microsoft.Communication.PlayCanceled",
        ):
            logger.warning(
                "action=play_failed type=%s reason=%s",
                event_type,
                data.get("resultInformation", {}).get("message", "unknown"),
            )
            with self._lock:
                self._last_play_succeeded = False
            self._play_done.set()

        elif event_type == "Microsoft.Communication.CallDisconnected":
            self._call_disconnected.set()
            self._play_done.set()  # unblock any waiting play

        elif event_type == "Microsoft.Communication.ParticipantsUpdated":
            pass  # informational only

    # ------------------------------------------------------------------
    # Called from the interview loop thread
    # ------------------------------------------------------------------

    def wait_for_connect(self, timeout: float = 60.0) -> bool:
        """Block until CallConnected event. Returns True on success."""
        return self._call_connected.wait(timeout=timeout)

    def arm_play(self) -> None:
        """Clear the play-done flag before issuing play_media.
        Must be called immediately before play_text() to avoid race conditions."""
        self._play_done.clear()

    def wait_for_play(self, timeout: float = 120.0) -> bool:
        """Block until PlayCompleted / PlayFailed / PlayCanceled.
        Returns True if signalled before timeout."""
        return self._play_done.wait(timeout=timeout)

    def wait_for_disconnect(self, timeout: float = 10.0) -> bool:
        """Block until CallDisconnected event."""
        return self._call_disconnected.wait(timeout=timeout)

    def reset(self) -> None:
        """Reset all events. Call before starting a new demo run."""
        self._call_connected.clear()
        self._play_done.clear()
        self._call_disconnected.clear()
        with self._lock:
            self._call_connection_id = None
            self._last_play_succeeded = True

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def call_connection_id(self) -> str | None:
        with self._lock:
            return self._call_connection_id

    @property
    def last_play_succeeded(self) -> bool:
        with self._lock:
            return self._last_play_succeeded


# Module-level singleton — shared between server.py (webhook route) and
# demo_interview.py (interview loop thread).
event_bus = ACSEventBus()
