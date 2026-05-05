"""
Bootstrap Teams chat sessions for CAMs that have not yet messaged the bot.

Usage:
    python main.py --bootstrap-sessions
    python main.py --bootstrap-sessions --wait
    python main.py --bootstrap-sessions --cam "Alice Nguyen"

For each CAM in cam_identity_map.json that has no entry in cam_sessions.json:
  1. Attempts to send a proactive bootstrap email via Microsoft Graph API if
     BOOTSTRAP_SENDER_EMAIL, TEAMS_BOT_APP_ID, TEAMS_BOT_APP_SECRET, and
     TEAMS_TENANT_ID are all configured and the app has Mail.Send permission.
  2. Falls back to printing manual-action instructions when credentials are
     absent or the send fails.

--wait polls cam_sessions.json every 30 s until all missing sessions are
detected or BOOTSTRAP_WAIT_TIMEOUT_SEC (default 600) elapses.
"""

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_IDENTITY_MAP_PATH = Path(os.getenv("CAM_IDENTITY_MAP_PATH", "data/cam_identity_map.json"))
_SESSIONS_PATH = Path(os.getenv("CAM_SESSIONS_PATH", "data/cam_sessions.json"))
_WAIT_TIMEOUT_SEC = int(os.getenv("BOOTSTRAP_WAIT_TIMEOUT_SEC", "600"))
_POLL_INTERVAL_SEC = 30


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_identity_map(path: Path | None = None) -> dict:
    """Load cam_identity_map.json → {cam_name: {email, auto_respond, ...}}."""
    p = path or _IDENTITY_MAP_PATH
    if not p.exists():
        logger.warning("action=bootstrap_missing_identity_map path=%s", p)
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_sessions(path: Path | None = None) -> dict:
    """Load cam_sessions.json → {email: {conversation_id, ...}}."""
    p = path or _SESSIONS_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def find_missing_cams(
    identity_map: dict,
    sessions: dict,
    cam_filter: str = "",
) -> list[dict]:
    """
    Return CAMs from *identity_map* that have no entry in *sessions*.

    Args:
        identity_map: Loaded cam_identity_map.json dict (name → info).
        sessions:     Loaded cam_sessions.json dict (email → session data).
        cam_filter:   If non-empty, only include the CAM whose name matches
                      (case-insensitive).  Empty string = include all.

    Returns:
        List of dicts, one per missing CAM:
        ``{name, email, auto_respond, responder_type}``.
    """
    missing: list[dict] = []
    for cam_name, info in identity_map.items():
        if cam_filter and cam_name.lower() != cam_filter.lower():
            continue
        email = info.get("email", "")
        if not email:
            continue
        if email not in sessions:
            missing.append({
                "name": cam_name,
                "email": email,
                "auto_respond": info.get("auto_respond", False),
                "responder_type": info.get("responder_type", ""),
            })
    return missing


# ---------------------------------------------------------------------------
# Graph API helpers (optional — graceful fallback when msal/requests absent)
# ---------------------------------------------------------------------------

def _get_app_token(tenant_id: str, client_id: str, client_secret: str) -> str | None:
    """Acquire an app-only Microsoft Graph token via client credentials flow.

    Returns the access token string, or None if *msal* is not installed or
    token acquisition fails.
    """
    try:
        import msal  # type: ignore
    except ImportError:
        logger.debug("action=bootstrap_no_msal")
        return None
    try:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        token = result.get("access_token")
        if not token:
            logger.warning("action=bootstrap_token_fail error=%s",
                           result.get("error_description", "unknown"))
        return token
    except Exception as exc:  # pragma: no cover
        logger.warning("action=bootstrap_token_exception error=%s", exc)
        return None


def send_bootstrap_email(
    cam_email: str,
    cam_name: str,
    access_token: str,
    sender_email: str,
    bot_display_name: str = "ATLAS IMS Agent",
) -> bool:
    """
    Send a bootstrap email via Microsoft Graph ``/users/{sender}/sendMail``.

    Requires the AAD app to have the ``Mail.Send`` application permission and
    *sender_email* to be a valid mailbox in the tenant.

    Args:
        cam_email:       Recipient email address.
        cam_name:        CAM display name (used in greeting).
        access_token:    App-only Graph Bearer token.
        sender_email:    Mailbox that sends the email (BOOTSTRAP_SENDER_EMAIL).
        bot_display_name: Display name of the Teams bot (for instructions).

    Returns:
        True on HTTP 202 (accepted), False otherwise.
    """
    try:
        import requests as _req  # type: ignore
    except ImportError:
        logger.debug("action=bootstrap_no_requests")
        return False

    body_text = (
        f"Hi {cam_name},\n\n"
        f"To participate in the weekly IMS schedule status interview, please open "
        f"Microsoft Teams and send any message to the {bot_display_name} bot. "
        f"Once you have messaged the bot, your interview session will be configured "
        f"automatically and you will receive your first schedule question.\n\n"
        f"If you do not see the bot, search for \"{bot_display_name}\" in the Teams "
        f"search bar or ask your programme manager to add it to your Teams.\n\n"
        f"Thank you,\nIMS Agent"
    )

    payload = {
        "message": {
            "subject": f"Action Required: Set up your IMS interview with {bot_display_name}",
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [
                {"emailAddress": {"address": cam_email, "name": cam_name}}
            ],
        },
        "saveToSentItems": "false",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"
    try:
        resp = _req.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 202:
            logger.info("action=bootstrap_email_sent cam=%s", cam_name)
            return True
        logger.warning(
            "action=bootstrap_email_failed cam=%s http=%d body=%.200s",
            cam_name, resp.status_code, resp.text,
        )
        return False
    except Exception as exc:
        logger.warning("action=bootstrap_email_exception cam=%s error=%s", cam_name, exc)
        return False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def bootstrap(
    cam_filter: str = "",
    wait: bool = False,
    identity_map_path: Path | None = None,
    sessions_path: Path | None = None,
) -> int:
    """
    Main bootstrap orchestrator.

    Identifies CAMs without chat sessions, attempts automated outreach, and
    optionally polls until all sessions are established.

    Args:
        cam_filter:         Filter to a single CAM by name (empty = all).
        wait:               If True, poll cam_sessions.json until all missing
                            CAMs appear or the timeout elapses.
        identity_map_path:  Override path for cam_identity_map.json (tests).
        sessions_path:      Override path for cam_sessions.json (tests).

    Returns:
        0 if all CAMs have sessions after the run, 1 otherwise.
    """
    identity_map = load_identity_map(identity_map_path)
    sessions = load_sessions(sessions_path)
    sp = sessions_path or _SESSIONS_PATH

    missing = find_missing_cams(identity_map, sessions, cam_filter)

    if not missing:
        print("All CAMs already have Teams chat sessions in cam_sessions.json.")
        return 0

    # Attempt Graph API email bootstrap if all credentials are configured
    tenant_id = os.getenv("TEAMS_TENANT_ID", "")
    client_id = os.getenv("TEAMS_BOT_APP_ID", "")
    client_secret = os.getenv("TEAMS_BOT_APP_SECRET", "")
    sender_email = os.getenv("BOOTSTRAP_SENDER_EMAIL", "")

    access_token: str | None = None
    if all([tenant_id, client_id, client_secret, sender_email]):
        print("Acquiring Microsoft Graph token ...")
        access_token = _get_app_token(tenant_id, client_id, client_secret)
        if access_token:
            print("  Token acquired.\n")
        else:
            print("  Token acquisition failed — falling back to manual instructions.\n")
    else:
        missing_vars = [
            v for v, val in [
                ("TEAMS_TENANT_ID", tenant_id),
                ("TEAMS_BOT_APP_ID", client_id),
                ("TEAMS_BOT_APP_SECRET", client_secret),
                ("BOOTSTRAP_SENDER_EMAIL", sender_email),
            ]
            if not val
        ]
        print(
            f"Graph email not configured (missing env vars: {', '.join(missing_vars)}).\n"
            "Set those variables to enable automated bootstrap emails.\n"
        )

    print(f"CAMs needing session bootstrap: {len(missing)}\n")
    print(f"{'CAM':<22} {'Email':<45} Action")
    print("-" * 80)

    manual: list[dict] = []
    for cam in missing:
        if access_token and sender_email:
            ok = send_bootstrap_email(
                cam_email=cam["email"],
                cam_name=cam["name"],
                access_token=access_token,
                sender_email=sender_email,
            )
            if ok:
                print(f"  {cam['name']:<20} {cam['email']:<45} Bootstrap email sent")
                continue

        print(f"  {cam['name']:<20} {cam['email']:<45} Manual action required")
        manual.append(cam)

    if manual:
        print("\nManual bootstrap instructions:")
        for cam in manual:
            print(f"  {cam['name']} ({cam['email']}):")
            print(f"    1. In Teams, search for the IMS Agent bot and send any message.")
            print(f"    2. Or run: python main.py --cam-responder --cam \"{cam['name']}\"")
            print(f"       to authenticate the responder, then trigger a cycle.\n")

    if not wait:
        print("Run with --wait to poll until all sessions are established.")
        return 1

    # --wait mode: poll until all sessions appear or timeout
    print(f"\nPolling every {_POLL_INTERVAL_SEC}s "
          f"(timeout {_WAIT_TIMEOUT_SEC}s) ...")
    deadline = time.monotonic() + _WAIT_TIMEOUT_SEC
    pending = {c["email"] for c in missing}

    while time.monotonic() < deadline and pending:
        time.sleep(_POLL_INTERVAL_SEC)
        current = load_sessions(sp)
        newly_found = pending & set(current.keys())
        for email in sorted(newly_found):
            cam_name = next(
                (c["name"] for c in missing if c["email"] == email), email
            )
            print(f"  Session detected: {cam_name} ({email})")
        pending -= newly_found

    if not pending:
        print("\nAll CAMs now have sessions. Bootstrap complete.")
        return 0

    still_missing = [c["name"] for c in missing if c["email"] in pending]
    print(f"\nTimed out. Still missing sessions for: {', '.join(still_missing)}")
    return 1
