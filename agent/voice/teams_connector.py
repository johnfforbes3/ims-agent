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


class LocalElevenLabsConnector:
    """
    Local audio connector — plays TTS via ElevenLabs through the system speakers.

    Fires into the same ACSEventBus as TeamsACSConnector so demo_interview.py
    requires no changes. Useful when ACS Teams meeting join is unavailable.

    Requires:
      ELEVENLABS_API_KEY  — set in .env
      sounddevice          — pip install sounddevice
      numpy                — pip install numpy
    """

    _AGENT_VOICE_ID = "pFZP5JQG7iQjIQuC4Bku"  # Rachel (professional)
    _CAM_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"    # Bella (softer, different timbre)

    _VOICE_MAP: dict[str, str] = {
        "en-US-JennyNeural": _AGENT_VOICE_ID,
        "en-US-AriaNeural": _CAM_VOICE_ID,
    }

    def __init__(self) -> None:
        api_key = os.getenv("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise EnvironmentError("ELEVENLABS_API_KEY is not set.")
        try:
            import sounddevice  # noqa: F401
            import numpy        # noqa: F401
            from elevenlabs.client import ElevenLabs  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "sounddevice, numpy, and elevenlabs are required. "
                "Run: pip install sounddevice numpy elevenlabs"
            ) from exc
        self._el_api_key = api_key
        self.transport_name = "local_elevenlabs"
        logger.info("action=transport_init type=local_elevenlabs")

    def join_meeting(self, meeting_url: str, callback_url: str) -> str:
        """Fake meeting join — immediately fires CallConnected into event_bus."""
        import uuid
        from agent.acs_event_handler import event_bus
        fake_id = str(uuid.uuid4())
        event_bus.handle("Microsoft.Communication.CallConnected", {"callConnectionId": fake_id})
        logger.info("action=local_join_simulated call_id=%s", fake_id)
        return fake_id

    def play_text(
        self,
        call_connection_id: str,
        text: str,
        voice: str = "en-US-JennyNeural",
    ) -> None:
        """Generate TTS via ElevenLabs (PCM) and play through system speakers."""
        import numpy as np
        import sounddevice as sd
        from elevenlabs.client import ElevenLabs as _EL
        from agent.acs_event_handler import event_bus

        voice_id = self._VOICE_MAP.get(voice, self._AGENT_VOICE_ID)
        if voice == "en-US-AriaNeural":
            voice_id = self._CAM_VOICE_ID

        try:
            client = _EL(api_key=self._el_api_key)
            chunks = client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2"),
                output_format="pcm_16000",  # raw 16-bit PCM, 16 kHz mono
            )
            pcm_bytes = b"".join(chunks)

            # Convert raw PCM bytes → float32 numpy array for sounddevice
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            sd.play(audio, samplerate=16000)
            sd.wait()  # blocks until playback finishes

            event_bus.handle("Microsoft.Communication.PlayCompleted", {"callConnectionId": call_connection_id})
            logger.info("action=play_local_done cid=%s chars=%d", call_connection_id, len(text))
        except Exception as exc:
            logger.error("action=play_local_error error=%s", exc)
            event_bus.handle("Microsoft.Communication.PlayFailed", {"callConnectionId": call_connection_id})

    def end_call(self, call_id: str) -> None:
        from agent.acs_event_handler import event_bus
        event_bus.handle("Microsoft.Communication.CallDisconnected", {"callConnectionId": call_id})
        logger.info("action=local_call_ended call_id=%s", call_id)


class TeamsGraphConnector:
    """
    Microsoft Graph Communications API connector.

    Joins a Teams meeting as a named bot participant ("ATLAS Scheduler"),
    plays TTS audio (ElevenLabs-generated WAV) into the meeting via playPrompt,
    and receives playback-complete events on our FastAPI /graph/callback endpoint.

    Requirements in .env:
        TEAMS_BOT_APP_ID      — Azure AD App Registration Application (client) ID
        TEAMS_BOT_APP_SECRET  — Client secret value
        TEAMS_TENANT_ID       — Azure AD Directory (tenant) ID
        ELEVENLABS_API_KEY    — for TTS generation

    Azure AD App permissions required (application-level, admin-consented):
        Calls.JoinGroupCall.All
        Calls.JoinGroupCallAsGuest.All

    See TEAMS-SETUP.md for full provisioning steps.
    """

    _GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    _BOT_DISPLAY_NAME = os.getenv("TEAMS_BOT_DISPLAY_NAME", "ATLAS Scheduler")

    # ElevenLabs voice IDs
    _AGENT_VOICE_ID = os.getenv("ELEVENLABS_AGENT_VOICE_ID", "pFZP5JQG7iQjIQuC4Bku")  # Rachel
    _CAM_VOICE_ID   = os.getenv("ELEVENLABS_CAM_VOICE_ID",   "EXAVITQu4vr4xnSDxMaL")  # Bella

    _VOICE_MAP: dict[str, str] = {
        "en-US-JennyNeural": _AGENT_VOICE_ID,
        "en-US-AriaNeural":  _CAM_VOICE_ID,
    }

    def __init__(self) -> None:
        self._app_id     = os.getenv("TEAMS_BOT_APP_ID", "")
        self._app_secret = os.getenv("TEAMS_BOT_APP_SECRET", "")
        self._tenant_id  = os.getenv("TEAMS_TENANT_ID", "")
        self._el_api_key = os.getenv("ELEVENLABS_API_KEY", "")

        missing = [k for k, v in {
            "TEAMS_BOT_APP_ID": self._app_id,
            "TEAMS_BOT_APP_SECRET": self._app_secret,
            "TEAMS_TENANT_ID": self._tenant_id,
            "ELEVENLABS_API_KEY": self._el_api_key,
        }.items() if not v]
        if missing:
            raise EnvironmentError(
                f"TeamsGraphConnector requires these .env vars: {', '.join(missing)}"
            )

        self._token: str | None = None
        self._active_calls: dict[str, dict] = {}   # call_id → {callback_url, ...}
        # In-memory audio buffer served by /graph/audio/<id>
        self.audio_cache: dict[str, bytes] = {}
        self.transport_name = "teams_graph"
        logger.info("action=transport_init type=teams_graph app_id=%s", self._app_id[:8] + "...")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Acquire (or reuse) an app-only OAuth token via MSAL."""
        import msal
        app = msal.ConfidentialClientApplication(
            client_id=self._app_id,
            client_credential=self._app_secret,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"MSAL token acquisition failed: {result.get('error_description', result)}"
            )
        return result["access_token"]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Meeting join
    # ------------------------------------------------------------------

    def join_meeting(
        self,
        meeting_url: str,
        callback_url: str,
        join_meeting_id: str | None = None,
        passcode: str | None = None,
    ) -> str:
        """
        Join a Teams meeting as the ATLAS Scheduler bot.

        Accepts either:
          - A full join URL:  https://teams.microsoft.com/l/meetup-join/...
          - A short meet URL: https://teams.microsoft.com/meet/24359063473177?p=Abc...
          - Explicit join_meeting_id + passcode

        Returns the Graph call ID (used for play_text and end_call).
        """
        import re, requests

        # --- Extract join meeting ID and passcode from URL if not explicit ---
        if not join_meeting_id:
            # Short URL: .../meet/ID?p=PASSCODE
            m = re.search(r"/meet/(\d+)\?p=([A-Za-z0-9]+)", meeting_url)
            if m:
                join_meeting_id = m.group(1)
                passcode = m.group(2)
            else:
                # Full URL — the joinMeetingId is embedded in the context parameter
                # Fall back to passing the full meeting URL as meetingInfo.meetingUrl
                join_meeting_id = None

        if join_meeting_id:
            meeting_info = {
                "@odata.type": "#microsoft.graph.joinMeetingIdMeetingInfo",
                "joinMeetingId": join_meeting_id,
                "passcode": passcode or "",
            }
        else:
            meeting_info = {
                "@odata.type": "#microsoft.graph.organizerMeetingInfo",
                "meetingUrl": meeting_url,
            }

        full_callback = callback_url.rstrip("/") + "/graph/callback"

        payload = {
            "callbackUri": full_callback,
            "requestedModalities": ["audio"],
            "mediaConfig": {
                "@odata.type": "#microsoft.graph.serviceHostedMediaConfig",
            },
            "source": {
                "@odata.type": "#microsoft.graph.participantInfo",
                "identity": {
                    "@odata.type": "#microsoft.graph.identitySet",
                    "application": {
                        "@odata.type": "#microsoft.graph.identity",
                        "id": self._app_id,
                        "displayName": self._BOT_DISPLAY_NAME,
                    },
                },
                "languageId": "en-US",
            },
            "meetingInfo": meeting_info,
            "tenantId": self._tenant_id,
        }

        resp = requests.post(
            f"{self._GRAPH_BASE}/communications/calls",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(
                f"Graph join_meeting failed {resp.status_code}: {resp.text[:400]}"
            )
        call_id = resp.json()["id"]
        self._active_calls[call_id] = {
            "callback_url": full_callback,
            "status": "connecting",
        }
        logger.info("action=graph_join_initiated call_id=%s callback=%s",
                    call_id, full_callback)
        return call_id

    # ------------------------------------------------------------------
    # Audio playback
    # ------------------------------------------------------------------

    def play_text(
        self,
        call_id: str,
        text: str,
        voice: str = "en-US-JennyNeural",
        callback_url: str | None = None,
    ) -> None:
        """
        Generate TTS via ElevenLabs, store the WAV in the audio cache,
        and play it into the Teams meeting via Graph playPrompt.

        The audio is served temporarily from our FastAPI /graph/audio/<id> endpoint
        so Graph can fetch it.  The call to playPrompt is non-blocking; the
        PlayCompleted event arrives on /graph/callback.
        """
        import uuid, wave, io, struct, requests
        from elevenlabs.client import ElevenLabs as _EL
        from agent.acs_event_handler import event_bus

        voice_id = self._VOICE_MAP.get(voice, self._AGENT_VOICE_ID)
        if voice == "en-US-AriaNeural":
            voice_id = self._CAM_VOICE_ID

        # Generate PCM audio from ElevenLabs (16 kHz mono, 16-bit)
        client = _EL(api_key=self._el_api_key)
        chunks = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2"),
            output_format="pcm_16000",   # raw PCM, 16000 Hz, 16-bit, mono
        )
        pcm_bytes = b"".join(chunks)

        # Wrap PCM in a proper WAV container (Graph requires WAV)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)       # mono
            wf.setsampwidth(2)       # 16-bit
            wf.setframerate(16000)   # 16 kHz
            wf.writeframes(pcm_bytes)
        wav_bytes = buf.getvalue()

        # Store in audio cache and derive a public URL
        audio_id = str(uuid.uuid4())
        self.audio_cache[audio_id] = wav_bytes
        call_info = self._active_calls.get(call_id, {})
        base_url = (callback_url or call_info.get("callback_url", "")).replace(
            "/graph/callback", ""
        )
        audio_url = f"{base_url}/graph/audio/{audio_id}"

        payload = {
            "clientContext": audio_id,
            "prompts": [
                {
                    "@odata.type": "#microsoft.graph.mediaPrompt",
                    "mediaInfo": {
                        "@odata.type": "#microsoft.graph.mediaInfo",
                        "uri": audio_url,
                        "resourceId": audio_id,
                    },
                }
            ],
        }

        resp = requests.post(
            f"{self._GRAPH_BASE}/communications/calls/{call_id}/playPrompt",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        if not resp.ok:
            logger.error("action=graph_play_failed call_id=%s status=%d body=%s",
                         call_id, resp.status_code, resp.text[:300])
            event_bus.handle("Microsoft.Communication.PlayFailed",
                             {"callConnectionId": call_id})
        else:
            logger.info("action=graph_play_initiated call_id=%s chars=%d audio_id=%s",
                        call_id, len(text), audio_id)

    # ------------------------------------------------------------------
    # Call termination
    # ------------------------------------------------------------------

    def end_call(self, call_id: str) -> None:
        import requests
        try:
            resp = requests.delete(
                f"{self._GRAPH_BASE}/communications/calls/{call_id}",
                headers=self._headers(),
                timeout=10,
            )
            logger.info("action=graph_call_ended call_id=%s status=%d",
                        call_id, resp.status_code)
        except Exception as exc:
            logger.warning("action=graph_end_call_error call_id=%s error=%s", call_id, exc)
        finally:
            self._active_calls.pop(call_id, None)


def build_transport() -> CallTransport:
    """Factory — select the configured call transport."""
    if _TRANSPORT == "teams_acs":
        logger.info("action=transport_select type=teams_acs")
        return TeamsACSConnector()
    logger.info("action=transport_select type=simulated")
    return SimulatedTransport()
