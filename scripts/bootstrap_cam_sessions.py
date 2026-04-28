"""
Bootstrap cam_sessions.json using existing MSAL token caches.

Looks up each auto-respond CAM's AAD object ID via Graph API (using any
cached token), then writes data/cam_sessions.json with the Bot Framework
user ID and Teams service URL needed for proactive interview messaging.

Run once after first-time account bootstrap:
    python scripts/bootstrap_cam_sessions.py
"""

import json
import os
import re
import sys
from pathlib import Path

import httpx
import msal
from dotenv import load_dotenv

load_dotenv(override=True)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_CACHE_DIR = Path(os.getenv("DATA_DIR", "data")) / "cam_tokens"
_SESSIONS_FILE = Path(os.getenv("DATA_DIR", "data")) / "cam_sessions.json"
_SCOPES = ["Chat.ReadWrite"]

# Teams Bot Framework service URLs by region — try amer first
_SERVICE_URLS = [
    "https://smba.trafficmanager.net/amer/",
    "https://smba.trafficmanager.net/emea/",
    "https://smba.trafficmanager.net/apac/",
]


def _load_token(email: str) -> str | None:
    """Load a cached Graph delegated token for this email."""
    client_id = os.getenv("AZURE_CLIENT_ID") or os.getenv("TEAMS_BOT_APP_ID", "")
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", email)
    cache_path = _TOKEN_CACHE_DIR / f"{safe}.bin"
    if not cache_path.exists():
        print(f"  [WARN] No token cache for {email} — run --cam-responder first")
        return None
    cache = msal.SerializableTokenCache()
    cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    accounts = app.get_accounts(username=email)
    if not accounts:
        print(f"  [WARN] No cached account for {email}")
        return None
    result = app.acquire_token_silent(_SCOPES, account=accounts[0])
    if result and "access_token" in result:
        return result["access_token"]
    print(f"  [WARN] Silent token refresh failed for {email}: {result.get('error_description', '')}")
    return None


def _get_aad_id(token: str, email: str) -> str | None:
    """Look up the AAD object ID for a user by email."""
    r = httpx.get(
        f"{_GRAPH_BASE}/users/{email}",
        params={"$select": "id,displayName,userPrincipalName"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if r.status_code == 200:
        return r.json().get("id")
    print(f"  [WARN] Graph user lookup failed for {email}: {r.status_code} {r.text[:200]}")
    return None


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.cam_identity import get_auto_respond_cams

    identity = get_auto_respond_cams()
    if not identity:
        print("No auto-respond accounts in cam_identity_map.json")
        return

    existing: dict = {}
    if _SESSIONS_FILE.exists():
        try:
            existing = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    added = 0
    for cam_name, info in identity.items():
        email = info.get("email", "")
        if not email:
            continue

        # Each account can only read their own profile — use their own token
        token = _load_token(email)
        if not token:
            continue

        # GET /me returns the authenticated user's own profile
        r = httpx.get(
            f"{_GRAPH_BASE}/me",
            params={"$select": "id,displayName,userPrincipalName"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [{cam_name}] /me lookup failed: {r.status_code}")
            continue

        aad_id = r.json().get("id", "")
        if not aad_id:
            continue

        bf_user_id = f"29:{aad_id}"
        existing[email.lower()] = {
            "user_id": bf_user_id,
            "service_url": _SERVICE_URLS[0],
            "conversation_id": "",
        }
        print(f"  [{cam_name}] user_id={bf_user_id[:20]}... service_url={_SERVICE_URLS[0]}")
        added += 1

    tmp = _SESSIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    os.replace(tmp, _SESSIONS_FILE)
    print(f"\n  Wrote {added} entries to {_SESSIONS_FILE}")
    print("  Now restart the dashboard server and trigger a cycle.")


if __name__ == "__main__":
    main()
