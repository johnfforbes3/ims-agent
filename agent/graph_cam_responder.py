"""
Graph CAM Responder — auto-responds to ATLAS Scheduler bot messages on behalf
of simulated CAM accounts using Microsoft Graph API with delegated auth.

Each auto-respond CAM account:
  1. Authenticates via MSAL device code flow (interactive, once per account).
     Tokens are cached in data/cam_tokens/ and refreshed silently thereafter.
  2. Finds the 1:1 Teams chat with the ATLAS Scheduler bot.
  3. Polls for new bot messages every POLL_INTERVAL_SEC seconds.
  4. Generates a natural-language response via CAMSimulator (same LLM-backed
     persona logic used in the simulated cycle mode).
  5. Posts the response as that user via Graph API, creating a real Teams log.

Setup requirements (one-time Azure portal changes):
  - App Registration -> API permissions -> add Chat.ReadWrite (Delegated), grant admin consent
  - App Registration -> Authentication -> enable "Allow public client flows"
  - App Registration -> Authentication -> add redirect URI:
      https://login.microsoftonline.com/common/oauth2/nativeclient

Required env vars:
  AZURE_TENANT_ID      — tenant ID for intelligenceexpanse.onmicrosoft.com
  TEAMS_BOT_APP_ID     — the bot's App Registration client ID (already set)

Usage:
  python main.py --cam-responder                    # all auto-respond accounts
  python main.py --cam-responder --cam "Alice"      # single account (substring match)
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import msal
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_POLL_SEC = int(os.getenv("CAM_RESPONDER_POLL_SEC", "5"))
_RESPOND_DELAY_SEC = float(os.getenv("CAM_RESPONDER_DELAY_SEC", "2.0"))
_TOKEN_CACHE_DIR = Path(os.getenv("DATA_DIR", "data")) / "cam_tokens"
_BOT_APP_ID = os.getenv("TEAMS_BOT_APP_ID", "")
_SCOPES = ["Chat.ReadWrite"]


def _strip_html(text: str) -> str:
    """Strip HTML tags from Graph API message content."""
    clean = re.sub(r"<[^>]+>", " ", text)
    for entity, char in [("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
                          ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")]:
        clean = clean.replace(entity, char)
    return re.sub(r"\s+", " ", clean).strip()


class GraphCAMResponder:
    """
    Authenticates as one simulated CAM account and auto-responds to the
    ATLAS Scheduler bot via Microsoft Graph API.
    """

    def __init__(
        self,
        cam_name: str,
        email: str,
        persona,
        stop_event: threading.Event | None = None,
    ) -> None:
        from agent.voice.cam_simulator import CAMSimulator
        self.cam_name = cam_name
        self.email = email
        self._simulator = CAMSimulator(persona)
        self._stop = stop_event or threading.Event()
        self._chat_id: str | None = None
        self._last_check: datetime = datetime.now(timezone.utc)
        self._token_cache = msal.SerializableTokenCache()
        self._load_token_cache()
        logger.info("action=responder_init cam=%s email=%s", cam_name, email)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def authenticate(self) -> bool:
        """Ensure we have a valid delegated token. Returns True on success."""
        try:
            self._get_token()
            return True
        except Exception as exc:
            logger.error("action=auth_failed cam=%s error=%s", self.cam_name, exc)
            return False

    def run(self) -> None:
        """Blocking poll loop — runs until stop_event is set."""
        logger.info("action=responder_running cam=%s email=%s", self.cam_name, self.email)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.error("action=tick_error cam=%s error=%s", self.cam_name, exc)
            self._stop.wait(timeout=_POLL_SEC)
        logger.info("action=responder_stopped cam=%s", self.cam_name)

    # ------------------------------------------------------------------
    # Poll tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        token = self._get_token()

        if not self._chat_id:
            self._chat_id = self._find_bot_chat(token)
            if not self._chat_id:
                return

        new_msgs = self._get_new_bot_messages(token, self._chat_id)
        for msg in new_msgs:
            raw = _strip_html(msg.get("body", {}).get("content", ""))
            if not raw:
                continue
            logger.info("action=bot_message cam=%s text=%r", self.cam_name, raw[:100])
            time.sleep(_RESPOND_DELAY_SEC)
            response = self._simulator.respond(raw)
            self._post_message(token, self._chat_id, response)
            logger.info("action=cam_responded cam=%s response=%r", self.cam_name, response[:100])
            # Relay to the local interview engine so it can generate the next question
            self._relay_to_server(response)

    def _relay_to_server(self, text: str) -> None:
        """Notify the local dashboard server of this CAM's response."""
        server_url = os.getenv("INTERVIEW_RELAY_URL", "http://localhost:9000")
        try:
            r = httpx.post(
                f"{server_url}/internal/cam_message",
                json={"email": self.email, "text": text},
                timeout=10,
            )
            logger.info("action=relay_posted cam=%s status=%d", self.cam_name, r.status_code)
        except Exception as exc:
            logger.debug("action=relay_failed cam=%s error=%s", self.cam_name, exc)

    # ------------------------------------------------------------------
    # Graph API helpers
    # ------------------------------------------------------------------

    def _find_bot_chat(self, token: str) -> str | None:
        """Find the 1:1 chat between this user and the ATLAS Scheduler bot."""
        bot_app_id_lower = _BOT_APP_ID.lower()
        headers = {"Authorization": f"Bearer {token}"}
        url: str | None = f"{_GRAPH_BASE}/me/chats?$top=50"
        try:
            while url:
                r = httpx.get(url, headers=headers, timeout=20)
                r.raise_for_status()
                data = r.json()
                for chat in data.get("value", []):
                    if chat.get("chatType") != "oneOnOne":
                        continue
                    cid = chat["id"]
                    # Fast path: 1:1 chat IDs encode both user IDs — if the bot's
                    # app ID appears in the chat ID it's the bot chat.
                    if bot_app_id_lower in cid.lower():
                        logger.info("action=bot_chat_found cam=%s chatId=%s", self.cam_name, cid[:20])
                        return cid
                    # Fallback: check members list for bot userId variants
                    mr = httpx.get(
                        f"{_GRAPH_BASE}/me/chats/{cid}/members",
                        headers=headers, timeout=20,
                    )
                    if mr.status_code != 200:
                        continue
                    members = mr.json().get("value", [])
                    for m in members:
                        uid = m.get("userId", "").lower()
                        if bot_app_id_lower in uid:
                            logger.info("action=bot_chat_found cam=%s chatId=%s", self.cam_name, cid[:20])
                            return cid
                url = data.get("@odata.nextLink")
        except Exception as exc:
            logger.warning("action=find_chat_failed cam=%s error=%s", self.cam_name, exc)
        return None

    def _get_new_bot_messages(self, token: str, chat_id: str) -> list[dict]:
        """Return bot messages posted after _last_check, oldest-first."""
        headers = {"Authorization": f"Bearer {token}"}
        url = (
            f"{_GRAPH_BASE}/me/chats/{chat_id}/messages"
            "?$top=20&$orderby=createdDateTime desc"
        )
        try:
            r = httpx.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            msgs = r.json().get("value", [])
        except Exception as exc:
            logger.warning("action=get_msgs_error cam=%s error=%s", self.cam_name, exc)
            return []

        cutoff = self._last_check
        new_bot = []
        for msg in reversed(msgs):  # oldest-first
            created_str = msg.get("createdDateTime", "")
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created <= cutoff:
                continue
            from_app = msg.get("from", {}).get("application") or {}
            if from_app.get("id") == _BOT_APP_ID:
                new_bot.append(msg)

        if msgs:
            try:
                latest_str = msgs[0].get("createdDateTime", "")
                latest = datetime.fromisoformat(latest_str.replace("Z", "+00:00"))
                if latest > self._last_check:
                    self._last_check = latest
            except ValueError:
                pass

        return new_bot

    def _post_message(self, token: str, chat_id: str, text: str) -> None:
        """Post a plain-text message to the chat as this user."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {"body": {"content": text, "contentType": "text"}}
        url = f"{_GRAPH_BASE}/me/chats/{chat_id}/messages"
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logger.error("action=post_msg_error cam=%s error=%s", self.cam_name, exc)

    # ------------------------------------------------------------------
    # MSAL token management
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        client_id = os.getenv("AZURE_CLIENT_ID") or os.getenv("TEAMS_BOT_APP_ID", "")
        tenant_id = os.getenv("AZURE_TENANT_ID", "")
        if not client_id or not tenant_id:
            raise RuntimeError(
                "AZURE_CLIENT_ID (or TEAMS_BOT_APP_ID) and AZURE_TENANT_ID must be set in .env"
            )
        msal_app = msal.PublicClientApplication(
            client_id=client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            token_cache=self._token_cache,
        )
        accounts = msal_app.get_accounts(username=self.email)
        if accounts:
            result = msal_app.acquire_token_silent(_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_token_cache()
                return result["access_token"]

        # Interactive device code flow
        flow = msal_app.initiate_device_flow(scopes=_SCOPES)
        print(f"\n{'='*62}")
        print(f"  Authenticate: {self.cam_name}  ({self.email})")
        print(f"  {flow['message']}")
        print(f"{'='*62}\n")
        result = msal_app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            self._save_token_cache()
            return result["access_token"]
        raise RuntimeError(
            f"Token acquisition failed for {self.email}: {result.get('error_description', result)}"
        )

    def _token_cache_path(self) -> Path:
        _TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", self.email)
        return _TOKEN_CACHE_DIR / f"{safe}.bin"

    def _load_token_cache(self) -> None:
        p = self._token_cache_path()
        if p.exists():
            self._token_cache.deserialize(p.read_text(encoding="utf-8"))

    def _save_token_cache(self) -> None:
        if self._token_cache.has_state_changed:
            self._token_cache_path().write_text(
                self._token_cache.serialize(), encoding="utf-8"
            )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_cam_responder(
    cam_filter: str = "",
    ims_path: str = "data/sample_ims.xml",
) -> None:
    """
    Start Graph auto-responders for all auto_respond accounts in cam_identity_map.json.

    Args:
        cam_filter: Optional substring filter on cam_name (case-insensitive).
        ims_path:   Path to IMS XML, used to build CAMPersona task context.
    """
    from agent.cam_identity import get_auto_respond_cams
    from agent.file_handler import IMSFileHandler
    from agent.voice.cam_simulator import build_atlas_personas

    identity = get_auto_respond_cams()
    if cam_filter:
        identity = {k: v for k, v in identity.items()
                    if cam_filter.lower() in k.lower()}

    if not identity:
        print("No auto-respond accounts matched. Check data/cam_identity_map.json.")
        return

    tasks = IMSFileHandler(ims_path).parse()
    personas = build_atlas_personas(tasks)

    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    started = 0

    print(f"\n{'='*62}")
    print(f"  IMS Agent — Graph CAM Responder")
    print(f"  Authenticating {len(identity)} account(s)...")
    print(f"{'='*62}")

    for cam_name, info in identity.items():
        email = info.get("email", "")
        persona = personas.get(cam_name)
        if not persona:
            print(f"  WARNING: No persona for '{cam_name}' — skipping")
            continue

        responder = GraphCAMResponder(cam_name, email, persona, stop_event)
        if not responder.authenticate():
            print(f"  ERROR: Auth failed for {cam_name} ({email})")
            continue

        t = threading.Thread(
            target=responder.run,
            name=f"responder_{cam_name.split()[0].lower()}",
            daemon=True,
        )
        threads.append(t)
        t.start()
        print(f"  + {cam_name} ({email}) — polling every {_POLL_SEC}s")
        started += 1

    if not started:
        print("No responders started. Exiting.")
        return

    print(f"\n  {started} responder(s) active. Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
        print("\nAll responders stopped.")
