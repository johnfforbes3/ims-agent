"""
Diagnostic script — verify Teams Graph API credentials and permissions.

Usage:
    python scripts/check_teams_auth.py

What it checks:
  1. Environment variables are set
  2. MSAL token acquisition succeeds
  3. Token contains Calls.JoinGroupCall.All in the scp/roles claim
  4. Basic Graph API call succeeds (/organization)
  5. /communications/calls listing (requires Calls.JoinGroupCall.All with admin consent)

If step 5 fails with 403 7504, you need to grant admin consent in Azure portal.
"""

import base64
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

_OK  = "\033[92m[OK]\033[0m"
_FAIL = "\033[91m[FAIL]\033[0m"
_WARN = "\033[93m[WARN]\033[0m"
_BOLD = "\033[1m"
_RST  = "\033[0m"

def _check(label: str, ok: bool, detail: str = "") -> bool:
    symbol = _OK if ok else _FAIL
    print(f"  {symbol} {label}", end="")
    if detail:
        print(f"\n       {detail}", end="")
    print()
    return ok

def _decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload without verifying signature."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        # Pad to multiple of 4
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}

def main() -> None:
    print(f"\n{_BOLD}Teams Graph API Diagnostic{_RST}")
    print("-" * 50)

    # 1. Environment variables
    print("\n1. Environment Variables")
    app_id     = os.getenv("TEAMS_BOT_APP_ID", "")
    app_secret = os.getenv("TEAMS_BOT_APP_SECRET", "")
    tenant_id  = os.getenv("TEAMS_TENANT_ID", "")
    el_key     = os.getenv("ELEVENLABS_API_KEY", "")

    _check("TEAMS_BOT_APP_ID",     bool(app_id),     app_id[:8] + "..." if app_id else "(not set)")
    _check("TEAMS_BOT_APP_SECRET", bool(app_secret), "(set)" if app_secret else "(not set)")
    _check("TEAMS_TENANT_ID",      bool(tenant_id),  tenant_id[:8] + "..." if tenant_id else "(not set)")
    _check("ELEVENLABS_API_KEY",   bool(el_key),     "(set)" if el_key else "(not set)")

    if not all([app_id, app_secret, tenant_id]):
        print(f"\n  {_FAIL} Missing required env vars — set them in .env and retry.")
        sys.exit(1)

    # 2. Token acquisition
    print("\n2. MSAL Token Acquisition")
    try:
        import msal
        msal_app = msal.ConfidentialClientApplication(
            client_id=app_id,
            client_credential=app_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        result = msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            desc = result.get("error_description", str(result))
            _check("Token acquired", False, desc)
            print(f"\n  Fix: Check TEAMS_BOT_APP_ID and TEAMS_BOT_APP_SECRET are correct.")
            sys.exit(1)
        token = result["access_token"]
        _check("Token acquired", True, f"expires_in={result.get('expires_in', '?')}s")
    except ImportError:
        print(f"  {_FAIL} msal not installed. Run: pip install msal")
        sys.exit(1)

    # 3. Inspect token claims
    print("\n3. Token Claims (API Permissions)")
    claims = _decode_jwt_claims(token)
    roles  = claims.get("roles", [])
    scp    = claims.get("scp", "").split()

    has_join_call  = "Calls.JoinGroupCall.All" in roles
    has_guest_call = "Calls.JoinGroupCallAsGuest.All" in roles
    has_initiate   = "Calls.Initiate.All" in roles

    _check("Calls.JoinGroupCall.All",      has_join_call,
           "MISSING — grant admin consent in Azure portal" if not has_join_call else "present in token")
    _check("Calls.JoinGroupCallAsGuest.All", has_guest_call,
           "Optional — not present" if not has_guest_call else "present in token")
    _check("Calls.Initiate.All",           has_initiate,
           "Optional — not present" if not has_initiate else "present in token")

    if roles:
        other = [r for r in roles if not r.startswith("Calls.")]
        if other:
            print(f"       Other roles: {', '.join(other[:5])}")
    else:
        print(f"  {_WARN} No 'roles' in token — this app may not have application permissions configured")
        print(       "       Ensure 'Calls.JoinGroupCall.All' is added as an Application permission")
        print(       "       (not Delegated) and admin consent is granted.")

    # 4. Basic Graph API call
    print("\n4. Graph API Connectivity")
    import requests
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = requests.get("https://graph.microsoft.com/v1.0/organization", headers=headers, timeout=10)
    if resp.ok:
        orgs = resp.json().get("value", [])
        org_name = orgs[0].get("displayName", "?") if orgs else "?"
        _check("/organization GET", True, f"tenant: {org_name}")
    else:
        _check("/organization GET", False, f"{resp.status_code}: {resp.text[:100]}")

    # 5. Communications API access
    print("\n5. Communications API Access")
    resp2 = requests.get(
        "https://graph.microsoft.com/v1.0/communications/calls",
        headers=headers,
        timeout=10,
    )
    if resp2.ok:
        _check("/communications/calls GET", True, "API accessible — permissions look good!")
    else:
        body = resp2.json() if resp2.headers.get("Content-Type", "").startswith("application/json") else {}
        code = body.get("error", {}).get("code", "")
        msg  = body.get("error", {}).get("message", resp2.text[:100])
        _check("/communications/calls GET", False, f"{resp2.status_code} code={code}: {msg}")

        if code == "7504":
            print(f"""
  {_BOLD}How to fix error 7504:{_RST}
  The app's API permissions need admin consent in Azure portal.

  Steps:
    1. Go to https://portal.azure.com
    2. Navigate to: Microsoft Entra ID → App registrations → ATLAS Scheduler
    3. Click "API permissions" in the left menu
    4. Verify you see:
         Microsoft Graph → Calls.JoinGroupCall.All  (Application)
    5. If it shows "Not granted", click:
         "Grant admin consent for Intelligence Expanse"
    6. Confirm and wait ~30 seconds, then re-run this script.

  If "Grant admin consent" button is greyed out:
    - You need Global Administrator role.
    - Sign into portal.azure.com with the account that owns the M365 trial.
""")
        elif code == "7503":
            print(f"""
  {_BOLD}How to fix error 7503:{_RST}
  The app is not registered in the Teams calling infrastructure.

  Steps:
    1. Create an Azure Bot Service resource (Messaging endpoint = ngrok URL)
    2. Enable Teams channel on the bot → enable "Calling"
    3. Set webhook URL to: <ngrok-url>/graph/callback
""")

    # Summary
    print("\n" + "-" * 50)
    if resp2.ok:
        print(f"  {_OK} {_BOLD}All checks passed — Teams Graph API is ready!{_RST}")
    elif not has_join_call:
        print(f"  {_FAIL} {_BOLD}Admin consent missing. Follow the fix steps above.{_RST}")
    else:
        print(f"  {_WARN} {_BOLD}Token has the right permissions but API call failed. See details above.{_RST}")
    print()


if __name__ == "__main__":
    main()
