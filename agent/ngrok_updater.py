"""
ngrok auto-updater — detects the current ngrok public URL and patches the
Azure Bot Service messaging endpoint so the Teams chat bot works across
ngrok restarts without manual portal changes.

Required env vars (all optional — if absent, endpoint update is skipped):
    AZURE_SUBSCRIPTION_ID  — Azure subscription GUID
    AZURE_RESOURCE_GROUP   — Resource group containing the Bot Service
    AZURE_BOT_NAME         — Bot Service resource name (e.g. "atlas-scheduler")

Uses the same TEAMS_BOT_APP_ID / TEAMS_BOT_APP_SECRET / TEAMS_TENANT_ID
credentials already configured for the Teams chat bot to acquire a
Management API token (no extra credentials needed).
"""

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

_NGROK_LOCAL_API = "http://127.0.0.1:4040/api/tunnels"
_MGMT_SCOPE = "https://management.azure.com/.default"
_MGMT_API_VER = "2022-09-15"


# ---------------------------------------------------------------------------
# ngrok URL detection
# ---------------------------------------------------------------------------

def get_ngrok_url(port: int = 9000) -> str | None:
    """
    Return the current public HTTPS ngrok URL tunnelling to *port*.
    Returns None if ngrok is not running or no matching tunnel is found.
    """
    try:
        resp = requests.get(_NGROK_LOCAL_API, timeout=3)
        resp.raise_for_status()
        for tunnel in resp.json().get("tunnels", []):
            pub = tunnel.get("public_url", "")
            addr = tunnel.get("config", {}).get("addr", "")
            if pub.startswith("https://") and str(port) in addr:
                return pub.rstrip("/")
    except Exception as exc:
        logger.debug("action=ngrok_detect_failed error=%s", exc)
    return None


# ---------------------------------------------------------------------------
# Azure Management token
# ---------------------------------------------------------------------------

def _get_mgmt_token() -> str | None:
    """Acquire an Azure Management API token using the bot app credentials."""
    try:
        import msal
        tenant_id = os.getenv("TEAMS_TENANT_ID", "")
        app_id = os.getenv("TEAMS_BOT_APP_ID", "")
        app_secret = os.getenv("TEAMS_BOT_APP_SECRET", "")
        if not all([tenant_id, app_id, app_secret]):
            return None
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        msal_app = msal.ConfidentialClientApplication(
            client_id=app_id,
            client_credential=app_secret,
            authority=authority,
        )
        result = msal_app.acquire_token_for_client(scopes=[_MGMT_SCOPE])
        return result.get("access_token")
    except Exception as exc:
        logger.debug("action=mgmt_token_failed error=%s", exc)
    return None


# ---------------------------------------------------------------------------
# Azure Bot Service endpoint update
# ---------------------------------------------------------------------------

def update_bot_service_endpoint(messaging_url: str) -> bool:
    """
    PATCH the Azure Bot Service to point its messaging endpoint at *messaging_url*.

    Returns True on success, False if Azure env vars are missing or the call fails.
    """
    sub = os.getenv("AZURE_SUBSCRIPTION_ID", "")
    rg = os.getenv("AZURE_RESOURCE_GROUP", "")
    bot = os.getenv("AZURE_BOT_NAME", "")
    app_id = os.getenv("TEAMS_BOT_APP_ID", "")

    if not all([sub, rg, bot]):
        logger.debug(
            "action=bot_endpoint_update_skipped "
            "reason=AZURE_SUBSCRIPTION_ID/AZURE_RESOURCE_GROUP/AZURE_BOT_NAME not set"
        )
        return False

    token = _get_mgmt_token()
    if not token:
        logger.warning("action=bot_endpoint_update_failed reason=could_not_acquire_mgmt_token")
        return False

    url = (
        f"https://management.azure.com/subscriptions/{sub}"
        f"/resourceGroups/{rg}"
        f"/providers/Microsoft.BotService/botServices/{bot}"
        f"?api-version={_MGMT_API_VER}"
    )
    payload = {
        "properties": {
            "msaAppId": app_id,
            "endpoint": messaging_url,
        }
    }
    resp = requests.patch(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    if resp.ok:
        logger.info("action=bot_endpoint_updated url=%s", messaging_url)
        return True
    logger.warning(
        "action=bot_endpoint_update_failed status=%d body=%s",
        resp.status_code, resp.text[:300],
    )
    return False


# ---------------------------------------------------------------------------
# Combined: detect + update
# ---------------------------------------------------------------------------

def auto_update_from_ngrok(port: int = 9000) -> str | None:
    """
    Detect the current ngrok URL and update Azure Bot Service if configured.

    Returns the ngrok base URL on success/detection, None if ngrok is not running.
    Prints a one-liner to stdout so the operator sees the current URL.
    """
    ngrok_url = get_ngrok_url(port)
    if not ngrok_url:
        return None

    messaging_url = f"{ngrok_url}/bot/messages"
    updated = update_bot_service_endpoint(messaging_url)

    if updated:
        print(f"  [ngrok] Bot Service endpoint updated → {messaging_url}")
    else:
        print(f"  [ngrok] Detected URL: {ngrok_url}")
        print(f"  [ngrok] To auto-update Azure Bot Service set:")
        print(f"          AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_BOT_NAME")
        print(f"  [ngrok] Messaging endpoint to set manually: {messaging_url}")

    return ngrok_url
