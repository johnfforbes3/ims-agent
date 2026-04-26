"""
Teams / ACS call transport.

Provides:
  - SimulatedTransport   — default; routes to CAMSimulator (no infra required)
  - TeamsACSConnector    — production; joins Teams meetings / calls CAMs via ACS

See TEAMS-SETUP.md for the step-by-step Azure provisioning guide.

Quick start (demo mode):
  1. Create ACS resource in Azure portal → copy connection string
  2. Install ngrok → run: ngrok http 8080
  3. Set ACS_CONNECTION_STRING in .env
  4. python main.py --demo-interview \\
         --meeting-url "https://teams.microsoft.com/l/meetup-join/..." \\
         --callback-url "https://xxxx.ngrok.io"
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
_ACS_COGNITIVE_SERVICES_ENDPOINT = os.getenv("ACS_COGNITIVE_SERVICES_ENDPOINT", "")
_TEAMS_AGENT_USER_ID = os.getenv("TEAMS_AGENT_USER_ID", "")
_TEAMS_TENANT_ID = os.getenv("TEAMS_TENANT_ID", "")


class CallTransport(ABC):
    """Abstract base class for call transports."""

    @abstractmethod
    def initiate_call(self, cam_record: Any) -> str:
        """Initiate an outbound call to a CAM. Returns a call session ID."""

    @abstractmethod
    def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Send TTS audio bytes to the active call."""

    @abstractmethod
    def receive_audio(self, call_id: str, timeout_sec: float) -> bytes | None:
        """Receive a CAM audio response. Returns bytes or None on timeout."""

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
    No audio infrastructure required.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        logger.info("action=transport_init type=simulated")

    def initiate_call(self, cam_record: Any) -> str:
        import uuid
        call_id = str(uuid.uuid4())[:8]
        self._sessions[call_id] = {"cam": cam_record, "active": True}
        logger.info(
            "action=call_initiated transport=simulated cam=%s call_id=%s",
            getattr(cam_record, "name", "?"),
            call_id,
        )
        return call_id

    def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        logger.debug(
            "action=audio_sent transport=simulated call_id=%s bytes=%d",
            call_id,
            len(audio_bytes),
        )

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
    Azure Communication Services → Microsoft Teams connector.

    Supports two usage patterns:

    1. Demo mode — join_meeting(meeting_url, callback_url):
       Joins an existing Teams meeting as a bot participant and plays both
       sides of a simulated CAM interview as TTS audio. Anyone in the meeting
       hears the conversation. No real CAM audio received (CAM is simulated
       via Claude API).

    2. Production mode — initiate_call(cam_record):
       Places an outbound call to an individual CAM via their Teams user ID
       or ACS-provisioned phone number. (Not yet implemented — see TD-011.)

    Requirements:
      - ACS_CONNECTION_STRING must be set in .env
      - A public HTTPS callback URL for ACS events (ngrok / Azure Dev Tunnels)
      - azure-communication-callautomation installed (in requirements.txt)

    See TEAMS-SETUP.md for the full provisioning walkthrough.
    """

    def __init__(self) -> None:
        if not _ACS_CONNECTION_STRING:
            raise EnvironmentError(
                "ACS_CONNECTION_STRING is not set. "
                "Follow TEAMS-SETUP.md to provision an Azure ACS resource "
                "and add the connection string to your .env file."
            )
        try:
            from azure.communication.callautomation import CallAutomationClient  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "azure-communication-callautomation is not installed. "
                "Run: pip install -r requirements.txt"
            ) from exc

        from azure.communication.callautomation import CallAutomationClient
        self._client = CallAutomationClient.from_connection_string(_ACS_CONNECTION_STRING)
        self._sessions: dict[str, dict] = {}
        logger.info(
            "action=transport_init type=teams_acs endpoint=%s",
            _ACS_CONNECTION_STRING.split(";")[0],
        )

    # ------------------------------------------------------------------
    # Demo mode: join an existing Teams meeting
    # ------------------------------------------------------------------

    def join_meeting(self, meeting_url: str, callback_url: str) -> str:
        """
        Join an existing Teams meeting via ACS Call Automation.

        Args:
            meeting_url: Full Teams meeting join URL
                         (https://teams.microsoft.com/l/meetup-join/...)
            callback_url: Public HTTPS base URL that ACS will POST events to.
                          '/acs/callback' is appended automatically.
                          Use ngrok or Azure Dev Tunnels for local dev.

        Returns:
            call_connection_id from the create_call response.

        Note:
            Always use event_bus.call_connection_id (from the CallConnected event)
            for subsequent play_text / end_call calls — ACS may issue a different
            confirmed ID in the event payload.
        """
        from azure.communication.callautomation import TeamsMeetingLocator

        full_callback = callback_url.rstrip("/") + "/acs/callback"
        call_locator = TeamsMeetingLocator(meeting_link=meeting_url)

        extra: dict[str, Any] = {}
        if _ACS_COGNITIVE_SERVICES_ENDPOINT:
            extra["cognitive_services_endpoint"] = _ACS_COGNITIVE_SERVICES_ENDPOINT

        # SDK 1.3+ uses create_call with call_locator for meeting joins.
        # Older versions used create_group_call — try both.
        try:
            result = self._client.create_call(
                target_participant=None,
                callback_url=full_callback,
                call_locator=call_locator,
                **extra,
            )
        except TypeError:
            result = self._client.create_group_call(
                target_participants=[],
                callback_url=full_callback,
                call_locator=call_locator,
            )

        call_id = result.call_connection_id
        self._sessions[call_id] = {"meeting_url": meeting_url, "active": True}
        logger.info(
            "action=meeting_join_initiated call_id=%s callback=%s",
            call_id,
            full_callback,
        )
        return call_id

    def play_text(
        self,
        call_connection_id: str,
        text: str,
        voice: str = "en-US-JennyNeural",
    ) -> None:
        """
        Synthesise text as speech and play it to all participants in the call.

        This is non-blocking — ACS fires a PlayCompleted (or PlayFailed) event
        to the callback URL when finished. Call event_bus.arm_play() before this
        and event_bus.wait_for_play() after to synchronise with the interview loop.

        Args:
            call_connection_id: Confirmed connection ID from the CallConnected event.
            text: Text to synthesise and play.
            voice: Azure Neural TTS voice name.
                   Agent:  "en-US-JennyNeural"  (AGENT_TTS_VOICE env var)
                   CAM:    "en-US-AriaNeural"   (CAM_TTS_VOICE env var)
                   Full list: https://learn.microsoft.com/azure/ai-services/speech-service/language-support
        """
        from azure.communication.callautomation import TextSource

        conn = self._client.get_call_connection(call_connection_id)
        source = TextSource(text=text, voice_name=voice)
        conn.play_media(play_source=source, play_to=[])
        logger.info(
            "action=play_text cid=%s voice=%s chars=%d",
            call_connection_id,
            voice,
            len(text),
        )

    # ------------------------------------------------------------------
    # Production mode: outbound call to an individual CAM
    # ------------------------------------------------------------------

    def initiate_call(self, cam_record: Any) -> str:
        """
        Place an outbound call to a CAM via their Teams user ID.

        Not yet implemented. To implement (TD-011):
          dial cam_record.teams_id via MicrosoftTeamsUserIdentifier, handle
          CallConnected, then drive the interview via play_text / receive_audio.
        """
        raise NotImplementedError(
            "Outbound CAM calling is not yet implemented (TD-011). "
            "Use join_meeting() for demo mode."
        )

    def send_audio(self, call_id: str, audio_bytes: bytes) -> None:
        """Use play_text() for TTS. Raw byte upload not supported in this release."""
        raise NotImplementedError("Use play_text() for TTS audio playback.")

    def receive_audio(self, call_id: str, timeout_sec: float) -> bytes | None:
        """
        Real-time CAM audio capture requires ACS media streaming (TD-011).
        In demo mode the CAM is simulated — no audio input is needed.
        """
        raise NotImplementedError(
            "Real-time audio capture requires ACS media streaming (TD-011). "
            "Demo mode uses the Claude-powered CAM simulator instead."
        )

    def end_call(self, call_id: str) -> None:
        """Hang up the call for all participants."""
        try:
            conn = self._client.get_call_connection(call_id)
            conn.hang_up(is_for_everyone=True)
            logger.info("action=call_ended call_id=%s", call_id)
        except Exception as exc:
            logger.warning("action=end_call_error call_id=%s error=%s", call_id, exc)
        finally:
            self._sessions.pop(call_id, None)

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
