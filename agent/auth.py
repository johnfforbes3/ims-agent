"""
JWT authentication module — Phase 7.2 (CMMC AC.1.001, IA.3.083, IA.3.084)

Provides short-lived HS256 tokens to replace the static API-key model.
Tokens are issued by ``POST /api/auth/token`` and accepted alongside the
legacy ``X-API-Key`` / ``X-Admin-Key`` headers on all protected routes.

Env vars
--------
AUTH_SECRET_KEY    HMAC signing secret (min 32 chars).  Required when JWT
                   auth is enabled.  Generate with:
                     python -c "import secrets; print(secrets.token_hex(32))"
AUTH_CLIENT_ID     Client ID accepted by /api/auth/token.
AUTH_CLIENT_SECRET Client secret accepted by /api/auth/token.
JWT_EXPIRY_SECONDS Token lifetime in seconds (default: 3600 = 1 hour).
"""

import logging
import os
import threading
import time
import uuid
from typing import Any

import jwt  # PyJWT>=2.0

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"

# ---------------------------------------------------------------------------
# Configuration helpers — read at call time for hot-reload
# ---------------------------------------------------------------------------


def _secret_key() -> str:
    return os.getenv("AUTH_SECRET_KEY", "")


def _client_id() -> str:
    return os.getenv("AUTH_CLIENT_ID", "")


def _client_secret() -> str:
    return os.getenv("AUTH_CLIENT_SECRET", "")


def _expiry_seconds() -> int:
    try:
        return int(os.getenv("JWT_EXPIRY_SECONDS", "3600"))
    except ValueError:
        return 3600


# ---------------------------------------------------------------------------
# JTI blocklist — admin-tier tokens are one-time-use (replay resistance)
# ---------------------------------------------------------------------------

_jti_blocklist: set[str] = set()
_jti_lock = threading.Lock()


def block_jti(jti: str) -> None:
    """Add a token JTI to the one-time-use blocklist."""
    with _jti_lock:
        _jti_blocklist.add(jti)
    logger.info("action=jti_blocked jti=%s", jti)


def is_jti_blocked(jti: str) -> bool:
    """Return True if this JTI has already been used on an admin route."""
    with _jti_lock:
        return jti in _jti_blocklist


def _clear_blocklist() -> None:
    """Clear the JTI blocklist — for testing only."""
    with _jti_lock:
        _jti_blocklist.clear()


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_token(tier: str = "read") -> str:
    """Create a signed HS256 JWT.

    Args:
        tier: ``"read"`` (default) or ``"admin"`` — included in the ``tier``
              claim.  Admin tokens are subject to JTI blocklisting on admin
              routes (replay resistance per IA.3.084).

    Returns:
        Encoded JWT string.

    Raises:
        ValueError: when ``AUTH_SECRET_KEY`` is not configured.
    """
    key = _secret_key()
    if not key:
        raise ValueError(
            "AUTH_SECRET_KEY is not set — cannot issue JWT tokens. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": _client_id() or "ims-agent-client",
        "tier": tier,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + _expiry_seconds(),
    }
    token = jwt.encode(payload, key, algorithm=_ALGORITHM)
    logger.info("action=token_issued tier=%s jti=%s", tier, payload["jti"])
    return token


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def verify_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Returns:
        Decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError: token has expired.
        jwt.InvalidTokenError:    signature invalid, malformed, missing claim.
        ValueError:               AUTH_SECRET_KEY not set.
    """
    key = _secret_key()
    if not key:
        raise ValueError("AUTH_SECRET_KEY is not set")
    return jwt.decode(token, key, algorithms=[_ALGORITHM])
