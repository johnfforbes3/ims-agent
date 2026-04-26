"""
Teams / ACS call transport — production connector (stub).

This module provides the CallTransport abstraction and two implementations:
  - SimulatedTransport  — default; routes to CAMSimulator (no infra required)
  - TeamsACSConnector   — production; requires Azure subscription + ACS resource

See docs/teams-integration-decision.md for the full ACS setup guide.

To activate TeamsACSConnector, set in .env:
  CALL_TRANSPORT=teams_acs
  ACS_CONNECTION_STRING=...
  TEAMS_AGENT_USER_ID=...
  TEAMS_TENANT_ID=...
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_TRANSPORT = os.getenv("CALL_TRANSPORT", "simulated").lower()
_ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING", "")
_TEAMS_AGENT_USER_ID = os.getenv("TEAMS_AGENT_USER_ID", "")
_TEAMS_TENANT_ID = os.getenv("TEAMS_TENANT_ID", "")


class CallTransport(ABC):
    """Abstract base class for call transports."""

    @abstractmethod
    def initiate_call(self, cam_record: Any) -> str:
        """
        Initiate an outbound call to a CAM.

        Args:
            cam_record: CAMRecord from cam_directory.

        Returns:
            A call session ID string.
        """

    @abstractmethod
    def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """
        Send TTS audio to the active call.

        Args:
            call_id: Session ID from initiate_call.
            audio_bytes: MP3/WAV audio to play to the CAM.
        """

    @abstractmethod
    def receive_audio(self, call_id: str, timeout_sec: float) -> bytes | None:
        """
        Receive a CAM audio response from the active call.

        Args:
            call_id: Session ID from initiate_call.
            timeout_sec: Max seconds to wait.

        Returns:
            Audio bytes, or None if no response within timeout.
        """

    @abstractmethod
    def end_call(self, call_id: str) -> None:
        """Cleanly terminate the call."""

    @property
    @abstractmethod
    def transport_name(self) -> str:
        """Human-readable transport name."""


class SimulatedTransport(CallTransport):
    """
    Simulated transport — routes all calls through the CAM simulator.

    No audio infrastructure required. Audio bytes are ignored; text responses
    come from the CAMSimulator (Claude-powered).

    The simulation loop in run_phase2_demo.py drives this transport directly
    by calling the CAMSimulator separately — this class exists to satisfy the
    interface and provide session tracking.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        logger.info("action=transport_init type=simulated")

    def initiate_call(self, cam_record: Any) -> str:
        import uuid
        call_id = str(uuid.uuid4())[:8]
        self._sessions[call_id] = {"cam": cam_record, "active": True}
        logger.info("action=call_initiated transport=simulated cam=%s call_id=%s",
                    getattr(cam_record, "name", "?"), call_id)
        return call_id

    def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        logger.debug("action=audio_sent transport=simulated call_id=%s bytes=%d",
                     call_id, len(audio_bytes))

    def receive_audio(self, call_id: str, timeout_sec: float) -> bytes | None:
        # Simulated transport never returns real audio — the demo loop
        # calls CAMSimulator.respond() directly and bypasses this method.
        return None

    def end_call(self, call_id: str) -> None:
        if call_id in self._sessions:
            self._sessions[call_id]["active"] = False
        logger.info("action=call_ended transport=simulated call_id=%s", call_id)

    @property
    def transport_name(self) -> str:
        return "simulated"


class TeamsACSConnector(CallTransport):
    """
    Azure Communication Services → Microsoft Teams outbound calling.

    STATUS: STUB — requires Azure subscription, ACS resource, and Teams-ACS
    interoperability enabled. See docs/teams-integration-decision.md.

    Setup checklist:
      1. az login && az account set --subscription <sub-id>
      2. az communication create --name ims-agent-acs --resource-group <rg>
             --location <region> --data-location UnitedStates
      3. az communication show-connection-string --name ims-agent-acs \
             --resource-group <rg>   → set ACS_CONNECTION_STRING in .env
      4. Enable Teams-ACS interop in Teams admin center:
             https://admin.teams.microsoft.com → Voice → Teams Phone
      5. Obtain Teams user object ID for the agent identity → TEAMS_AGENT_USER_ID
      6. Set CALL_TRANSPORT=teams_acs in .env
    """

    def __init__(self) -> None:
        if not _ACS_CONNECTION_STRING:
            raise EnvironmentError(
                "ACS_CONNECTION_STRING is not set. "
                "See docs/teams-integration-decision.md for setup instructions."
            )
        # Real implementation would import:
        #   from azure.communication.callautomation import CallAutomationClient
        #   from azure.communication.callautomation.models import CallInvite
        raise NotImplementedError(
            "TeamsACSConnector is a stub pending Azure subscription. "
            "Set CALL_TRANSPORT=simulated to use simulation mode."
        )

    def initiate_call(self, cam_record: Any) -> str:
        raise NotImplementedError

    def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        raise NotImplementedError

    def receive_audio(self, call_id: str, timeout_sec: float) -> bytes | None:
        raise NotImplementedError

    def end_call(self, call_id: str) -> None:
        raise NotImplementedError

    @property
    def transport_name(self) -> str:
        return "teams_acs"


def build_transport() -> CallTransport:
    """Factory — select the configured call transport."""
    if _TRANSPORT == "teams_acs":
        logger.info("action=transport_select type=teams_acs")
        return TeamsACSConnector()
    logger.info("action=transport_select type=simulated")
    return SimulatedTransport()
