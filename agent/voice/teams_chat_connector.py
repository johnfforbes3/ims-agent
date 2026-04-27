"""
Teams Chat connector — text-based CAM status interviews.

The ATLAS Scheduler bot sends direct messages to a CAM's Teams chat and
processes their typed replies through the InterviewAgent. No audio pipeline
is needed — latency is just the LLM classifier (~1-2 s per turn).

Architecture:
  FastAPI /bot/messages  ← Teams delivers incoming CAM messages here
       ↓
  ChatInterviewManager   — maps Teams user IDs to active sessions
       ↓
  ChatInterviewSession   — wraps InterviewAgent for one interview
       ↓
  _bf_reply()            — sends next question back via Bot Framework REST

Bot Framework REST (no SDK required):
  - Incoming messages arrive as JSON Activity objects at /bot/messages
  - Replies are POST'd to {serviceUrl}/v3/conversations/{id}/activities
  - Auth uses a Bot Framework-scoped MSAL token
    (authority: login.microsoftonline.com/botframework.com)
"""

import logging
import os
import threading
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

_BF_TOKEN_AUTHORITY = "https://login.microsoftonline.com/ac1eafc0-ad8c-4b29-b615-554ad6626f9e"
_BF_SCOPE = "https://api.botframework.com/.default"
_GRAPH = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Bot Framework token helper
# ---------------------------------------------------------------------------

_bf_token_cache: dict[str, Any] = {}
_bf_token_lock = threading.Lock()


def _get_bf_token() -> str:
    """Acquire (or reuse) a Bot Framework connector service token via MSAL."""
    import msal
    with _bf_token_lock:
        cached = _bf_token_cache.get("token")
        expires = _bf_token_cache.get("expires_at", 0)
        if cached and time.monotonic() < expires - 60:
            return cached

    app_id = os.getenv("TEAMS_BOT_APP_ID", "")
    app_secret = os.getenv("TEAMS_BOT_APP_SECRET", "")
    msal_app = msal.ConfidentialClientApplication(
        client_id=app_id,
        client_credential=app_secret,
        authority=_BF_TOKEN_AUTHORITY,
    )
    result = msal_app.acquire_token_for_client(scopes=[_BF_SCOPE])
    if "access_token" not in result:
        raise RuntimeError(f"BF token failed: {result.get('error_description', result)}")

    with _bf_token_lock:
        _bf_token_cache["token"] = result["access_token"]
        _bf_token_cache["expires_at"] = time.monotonic() + result.get("expires_in", 3600)

    return result["access_token"]


def _bf_reply(service_url: str, conversation_id: str, reply_to_id: str, text: str) -> None:
    """Post a text reply back to the Teams chat via Bot Framework REST."""
    token = _get_bf_token()
    url = (
        f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}"
        f"/activities/{reply_to_id}"
    )
    payload = {"type": "message", "text": text}
    resp = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    if not resp.ok:
        logger.warning("action=bf_reply_failed status=%d body=%s", resp.status_code, resp.text[:200])


def _bf_typing(service_url: str, conversation_id: str) -> None:
    """Send a 'typing' indicator so the CAM sees 'ATLAS Scheduler is typing...'"""
    try:
        token = _get_bf_token()
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        requests.post(
            url,
            json={"type": "typing"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=5,
        )
    except Exception as exc:
        logger.debug("action=typing_indicator_failed error=%s", exc)


# ---------------------------------------------------------------------------
# Interview session
# ---------------------------------------------------------------------------

class ChatInterviewSession:
    """Tracks one active interview for a specific Teams user."""

    def __init__(
        self,
        cam_name: str,
        tasks: list[dict],
        all_tasks: list[dict],
    ) -> None:
        from agent.voice.interview_agent import InterviewAgent
        self.cam_name = cam_name
        self.agent = InterviewAgent(cam_name, tasks, all_tasks=all_tasks)
        self.started = False
        self.done = threading.Event()
        # Set on first contact — used for proactive follow-ups
        self.service_url: str = ""
        self.conversation_id: str = ""

    def start(self) -> str:
        """Return the opening greeting text."""
        turn = self.agent.start()
        self.started = True
        return turn.text

    def process(self, utterance: str) -> str | None:
        """Process a CAM reply. Returns next agent message or None if done."""
        from agent.voice.interview_agent import InterviewState
        turn = self.agent.process(utterance)
        if self.agent.state in (InterviewState.COMPLETE, InterviewState.ABORTED):
            self.done.set()
        return turn.text if turn.text else None

    @property
    def is_done(self) -> bool:
        from agent.voice.interview_agent import InterviewState
        return self.agent.state in (InterviewState.COMPLETE, InterviewState.ABORTED)


# ---------------------------------------------------------------------------
# Session manager (singleton)
# ---------------------------------------------------------------------------

class ChatInterviewManager:
    """
    Singleton that maps Teams user IDs to active ChatInterviewSessions.

    Pre-register a session before the user messages the bot using
    register() or register_by_email(). When the user's first message
    arrives at /bot/messages, get_or_start_session() activates it.

    Wildcard key "*" matches any user — useful for single-CAM demos.
    """

    _instance: "ChatInterviewManager | None" = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._active: dict[str, ChatInterviewSession] = {}
        self._pending: dict[str, ChatInterviewSession] = {}
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> "ChatInterviewManager":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = ChatInterviewManager()
        return cls._instance

    def register(self, user_id: str, session: ChatInterviewSession) -> None:
        with self._lock:
            self._pending[user_id] = session

    def register_by_email(self, email: str, session: ChatInterviewSession) -> None:
        with self._lock:
            self._pending[email.lower()] = session

    def register_wildcard(self, session: ChatInterviewSession) -> None:
        """Assign session to the first user who messages the bot."""
        with self._lock:
            self._pending["*"] = session

    def get_or_start_session(
        self,
        user_id: str,
        user_email: str = "",
    ) -> ChatInterviewSession | None:
        with self._lock:
            if user_id in self._active:
                return self._active[user_id]
            session = (
                self._pending.pop(user_id, None)
                or (self._pending.pop(user_email.lower(), None) if user_email else None)
                or self._pending.pop("*", None)
            )
            if session:
                self._active[user_id] = session
            return session

    def remove_session(self, user_id: str) -> None:
        with self._lock:
            self._active.pop(user_id, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
