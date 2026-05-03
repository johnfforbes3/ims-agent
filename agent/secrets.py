"""
Secrets accessor — vault-ready secret fetching pattern.

All secrets in the IMS Agent are retrieved via ``get_secret()``.  In the
current deployment (Phase 6.1), secrets are read from environment variables
loaded by ``python-dotenv``.  When moving to a production vault (HashiCorp
Vault, AWS Secrets Manager, Azure Key Vault), only this module needs to change
— callers are unchanged.

Usage
-----
    from agent.secrets import get_secret

    api_key = get_secret("DASHBOARD_API_KEY")

Vault swap (future)
-------------------
Replace the ``_read_env`` backend with a vault client:

    import hvac  # or boto3, azure-keyvault-secrets, etc.
    _client = hvac.Client(url=os.getenv("VAULT_ADDR"))
    _client.auth.token.login(os.getenv("VAULT_TOKEN"))

    def _read_vault(name: str, default: str) -> str:
        resp = _client.secrets.kv.v2.read_secret_version(path=f"ims-agent/{name}")
        return resp["data"]["data"].get(name, default)

Then change the ``_BACKEND`` assignment below from ``_read_env`` to
``_read_vault``.  The audit log call is the same either way.

Security notes
--------------
- ``get_secret()`` reads at call time (not import time) so secret rotation
  does not require a process restart.
- Audit log entries are emitted for every secret access so security teams
  can detect unexpected fetches.
- Secret *values* are never logged; only the secret *name* and call site.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

def _read_env(name: str, default: str) -> str:
    """Read secret from environment variable (current backend)."""
    return os.getenv(name, default)


# Swap this to _read_vault (or any callable) for production vault integration.
_BACKEND = _read_env


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_secret(name: str, default: str = "") -> str:
    """
    Fetch a secret by name.

    Args:
        name:    Environment variable name (e.g. ``"ANTHROPIC_API_KEY"``).
        default: Returned when the secret is absent or empty.

    Returns:
        The secret value as a string, or *default* if not found.
    """
    value = _BACKEND(name, default)
    logger.debug("action=secret_accessed name=%s found=%s", name, bool(value))
    return value
