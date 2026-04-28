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

Session persistence (data/cam_sessions.json):
  After each reactive interview contact, the CAM's serviceUrl + userId are
  saved keyed by their email.  On the next cycle trigger the CycleRunner
  can call proactive_create_conversation() to open a new conversation without
  waiting for the CAM to initiate.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

_BF_TOKEN_AUTHORITY = "https://login.microsoftonline.com/ac1eafc0-ad8c-4b29-b615-554ad6626f9e"
_BF_SCOPE = "https://api.botframework.com/.default"
_CAM_SESSIONS_FILE = Path(os.getenv("DATA_DIR", "data")) / "cam_sessions.json"


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


def _bf_send(service_url: str, conversation_id: str, text: str) -> bool:
    """Proactively post a new message into an existing Teams conversation via Bot Framework REST.

    Unlike _bf_reply(), this creates a new activity rather than replying to a specific one,
    so it works for cycle-initiated interviews where no incoming activity_id exists.
    Returns True on success.
    """
    try:
        token = _get_bf_token()
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        resp = requests.post(
            url,
            json={"type": "message", "text": text},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        if not resp.ok:
            logger.warning(
                "action=bf_send_failed status=%d body=%s",
                resp.status_code, resp.text[:200],
            )
            return False
        logger.info("action=bf_send_ok conv=%s", conversation_id[:20])
        return True
    except Exception as exc:
        logger.warning("action=bf_send_exception error=%s", exc)
        return False


def proactive_create_conversation(service_url: str, user_id: str) -> str | None:
    """
    Create a new proactive conversation with a Teams user via the Bot Framework
    CreateConversation API.

    Returns the new conversation ID, or None on failure.
    """
    app_id = os.getenv("TEAMS_BOT_APP_ID", "")
    tenant_id = os.getenv("TEAMS_TENANT_ID", "")
    if not app_id:
        logger.warning("action=proactive_create_failed reason=TEAMS_BOT_APP_ID_not_set")
        return None
    try:
        token = _get_bf_token()
        url = f"{service_url.rstrip('/')}/v3/conversations"
        payload = {
            "bot": {"id": app_id, "name": os.getenv("TEAMS_BOT_DISPLAY_NAME", "ATLAS Scheduler")},
            "members": [{"id": user_id}],
            "isGroup": False,
            "tenantId": tenant_id,
            "channelData": {"tenant": {"id": tenant_id}},
        }
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.ok:
            conv_id = resp.json().get("id", "")
            logger.info("action=proactive_conversation_created conv=%s", conv_id[:12] if conv_id else "?")
            return conv_id
        logger.warning(
            "action=proactive_create_failed status=%d body=%s",
            resp.status_code, resp.text[:300],
        )
    except Exception as exc:
        logger.warning("action=proactive_create_exception error=%s", exc)
    return None


# ---------------------------------------------------------------------------
# Session persistence (cam_sessions.json)
# ---------------------------------------------------------------------------

_session_file_lock = threading.Lock()


def load_cam_sessions() -> dict[str, dict]:
    """Return the persisted CAM session map keyed by email/name (lowercase)."""
    with _session_file_lock:
        if not _CAM_SESSIONS_FILE.exists():
            return {}
        try:
            return json.loads(_CAM_SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def save_cam_session(
    cam_email: str,
    user_id: str,
    service_url: str,
    conversation_id: str,
) -> None:
    """Persist a CAM's Teams contact details for future proactive initiation."""
    with _session_file_lock:
        _CAM_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        sessions: dict = {}
        if _CAM_SESSIONS_FILE.exists():
            try:
                sessions = json.loads(_CAM_SESSIONS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        import os as _os
        from datetime import datetime, timezone
        sessions[cam_email.lower()] = {
            "user_id": user_id,
            "service_url": service_url,
            "conversation_id": conversation_id,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
        tmp = _CAM_SESSIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
        _os.replace(tmp, _CAM_SESSIONS_FILE)
        logger.info("action=cam_session_saved email=%s", cam_email)


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
        email: str = "",
    ) -> None:
        from agent.voice.interview_agent import InterviewAgent
        self.cam_name = cam_name
        self.email: str = email.lower()
        self.agent = InterviewAgent(cam_name, tasks, all_tasks=all_tasks)
        self.started = False
        self.done = threading.Event()
        # Set on first contact — used for proactive follow-ups
        self.service_url: str = ""
        self.conversation_id: str = ""
        self.user_id: str = ""

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

    def get_cam_inputs(self) -> list[dict]:
        """
        Extract cam_input dicts from completed interview results.
        Returns an empty list if the interview is not yet done.
        """
        results = getattr(self.agent, "results", [])
        return [
            r.to_cam_input_dict()
            for r in results
            if r.status == "captured"
        ]

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
        self._by_email: dict[str, ChatInterviewSession] = {}
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
            email_lower = email.lower()
            self._pending[email_lower] = session
            self._by_email[email_lower] = session

    def register_wildcard(self, session: ChatInterviewSession) -> None:
        """Assign session to the first user who messages the bot."""
        with self._lock:
            self._pending["*"] = session

    def get_session_by_email(self, email: str) -> "ChatInterviewSession | None":
        """Look up an active session by email (for relay endpoint)."""
        with self._lock:
            return self._by_email.get(email.lower())

    def get_or_start_session(
        self,
        user_id: str,
        user_email: str = "",
    ) -> "ChatInterviewSession | None":
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
                session.user_id = user_id
                if session.email:
                    self._by_email[session.email] = session
            return session

    def remove_session(self, user_id: str) -> None:
        with self._lock:
            session = self._active.pop(user_id, None)
            if session and session.email:
                self._by_email.pop(session.email, None)

    def remove_session_by_email(self, email: str) -> None:
        with self._lock:
            email_lower = email.lower()
            session = self._by_email.pop(email_lower, None)
            if session:
                self._active = {k: v for k, v in self._active.items() if v is not session}
            self._pending.pop(email_lower, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
