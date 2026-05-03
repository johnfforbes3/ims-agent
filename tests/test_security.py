"""
Phase 7.2 security tests.

Covers:
  - JWT token issuance (POST /api/auth/token)
  - Bearer token auth on protected read routes
  - Admin-tier JTI blocklisting (replay resistance — IA.3.084)
  - Expired / tampered token rejection
  - Key age alert in GET /health (SC.3.187)
  - SIEM syslog handler attachment (AU.3.045)
"""

import logging
import logging.handlers
import os
import time
import pytest
import jwt as _jwt

from fastapi.testclient import TestClient
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SECRET = "test-secret-key-at-least-32-chars-long!!"
_CLIENT_ID = "test-client"
_CLIENT_SECRET = "test-client-secret"


@pytest.fixture()
def env_auth(monkeypatch):
    """Set the JWT auth env vars for the duration of a test."""
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    monkeypatch.setenv("AUTH_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("AUTH_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.setenv("JWT_EXPIRY_SECONDS", "3600")
    # Disable static-key auth so only JWT is evaluated for read/admin paths
    monkeypatch.setenv("DASHBOARD_API_KEY", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_KEY", "")


@pytest.fixture()
def client(env_auth):
    """FastAPI TestClient with auth env vars pre-set and JTI blocklist cleared."""
    from agent.auth import _clear_blocklist
    _clear_blocklist()

    from agent.dashboard.server import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper: mint a raw JWT without going through the /api/auth/token endpoint
# ---------------------------------------------------------------------------

def _mint(tier: str = "read", expired: bool = False) -> str:
    now = int(time.time())
    exp = (now - 10) if expired else (now + 3600)
    payload = {
        "sub": "test-client",
        "tier": tier,
        "jti": f"test-jti-{tier}-{now}",
        "iat": now,
        "exp": exp,
    }
    return _jwt.encode(payload, _SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# 7.2.1 — POST /api/auth/token
# ---------------------------------------------------------------------------

class TestTokenEndpoint:
    """POST /api/auth/token issues valid JWTs for correct credentials."""

    def test_valid_credentials_return_token(self, client):
        """Valid client_id + client_secret → 200 with access_token."""
        resp = client.post("/api/auth/token", json={
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "tier": "read",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 3600

    def test_token_contains_correct_claims(self, client):
        """Issued token decodes to the expected tier and sub claims."""
        resp = client.post("/api/auth/token", json={
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "tier": "admin",
        })
        token = resp.json()["access_token"]
        claims = _jwt.decode(token, _SECRET, algorithms=["HS256"])
        assert claims["tier"] == "admin"
        assert "jti" in claims
        assert "exp" in claims

    def test_invalid_credentials_return_401(self, client):
        """Wrong client_secret → 401."""
        resp = client.post("/api/auth/token", json={
            "client_id": _CLIENT_ID,
            "client_secret": "wrong-secret",
            "tier": "read",
        })
        assert resp.status_code == 401

    def test_invalid_tier_returns_400(self, client):
        """Unknown tier value → 400."""
        resp = client.post("/api/auth/token", json={
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "tier": "superadmin",
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 7.2.1 — Bearer token accepted on read routes
# ---------------------------------------------------------------------------

class TestBearerAuth:
    """Bearer JWT is accepted on protected read routes."""

    def test_valid_bearer_accepted_on_read_route(self, client):
        """Valid read-tier Bearer token → read route returns non-401."""
        token = _mint("read")
        resp = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
        # The route itself might 404 if state file missing, but not 401.
        assert resp.status_code != 401

    def test_expired_token_rejected(self, client):
        """Expired JWT → 401 on any protected route."""
        token = _mint("read", expired=True)
        resp = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_tampered_token_rejected(self, client):
        """Signature-invalid token → 401."""
        token = _mint("read")
        # Flip the last character of the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        resp = client.get("/api/status", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code == 401

    def test_read_jwt_not_blocklisted_after_use(self, client):
        """Read-tier token can be reused on read routes (no JTI blocklisting)."""
        token = _mint("read")
        headers = {"Authorization": f"Bearer {token}"}
        resp1 = client.get("/api/status", headers=headers)
        resp2 = client.get("/api/status", headers=headers)
        assert resp1.status_code != 401
        assert resp2.status_code != 401


# ---------------------------------------------------------------------------
# 7.2.1 — Admin JTI blocklisting (IA.3.084 replay resistance)
# ---------------------------------------------------------------------------

class TestAdminJTIBlocklist:
    """Admin-tier JWT JTI is blocklisted after first admin-route use."""

    def test_admin_jwt_rejected_on_second_admin_use(self, client):
        """Same admin JWT cannot be used twice on an admin route."""
        token = _mint("admin")
        headers = {"Authorization": f"Bearer {token}"}

        # First admin call — mock CycleRunner at source to avoid actual cycle
        with patch("agent.cycle_runner.CycleRunner.is_active", return_value=True):
            resp1 = client.post("/api/trigger", headers=headers)
        # 409 = cycle already running (admin auth succeeded, business logic rejected it)
        assert resp1.status_code in (200, 409), (
            f"First admin call should succeed auth; got {resp1.status_code}"
        )

        # Second admin call — same token, JTI should now be blocked
        with patch("agent.cycle_runner.CycleRunner.is_active", return_value=True):
            resp2 = client.post("/api/trigger", headers=headers)
        assert resp2.status_code == 401, (
            f"Second admin call with same JWT should be blocked; got {resp2.status_code}"
        )

    def test_read_jwt_rejected_on_admin_route(self, client):
        """Read-tier JWT is rejected on admin routes (tier check)."""
        token = _mint("read")
        with patch("agent.cycle_runner.CycleRunner.is_active", return_value=True):
            resp = client.post("/api/trigger", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 7.2.2 — Key age alert in GET /health (SC.3.187)
# ---------------------------------------------------------------------------

class TestKeyAgeAlert:
    """GET /health includes key_age_warning when KEY_CREATED_AT > 90 days old."""

    def test_key_age_warning_when_old(self, monkeypatch):
        """key_age_warning=True and key_age_days>90 when key is 91 days old."""
        from datetime import datetime, timedelta, timezone
        old_date = (datetime.now(timezone.utc) - timedelta(days=91)).date().isoformat()
        monkeypatch.setenv("KEY_CREATED_AT", old_date)

        from agent.dashboard.server import app
        with TestClient(app) as c:
            resp = c.get("/health")
        body = resp.json()
        assert body["key_age_warning"] is True
        assert body["key_age_days"] is not None
        assert body["key_age_days"] > 90

    def test_no_key_age_warning_when_recent(self, monkeypatch):
        """key_age_warning=False when KEY_CREATED_AT is 30 days ago."""
        from datetime import datetime, timedelta, timezone
        recent_date = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        monkeypatch.setenv("KEY_CREATED_AT", recent_date)

        from agent.dashboard.server import app
        with TestClient(app) as c:
            resp = c.get("/health")
        body = resp.json()
        assert body["key_age_warning"] is False
        assert body["key_age_days"] is not None
        assert body["key_age_days"] <= 90

    def test_no_key_age_fields_when_not_set(self, monkeypatch):
        """When KEY_CREATED_AT is absent, key_age_days is None and no warning."""
        monkeypatch.delenv("KEY_CREATED_AT", raising=False)

        from agent.dashboard.server import app
        with TestClient(app) as c:
            resp = c.get("/health")
        body = resp.json()
        assert body.get("key_age_warning") is False
        assert body.get("key_age_days") is None


# ---------------------------------------------------------------------------
# 7.2.4 — SIEM syslog handler (AU.3.045)
# ---------------------------------------------------------------------------

class TestSIEMConfiguration:
    """configure_siem_logging() attaches a SysLogHandler when host is set."""

    def _count_syslog_handlers(self) -> int:
        return sum(
            1 for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.SysLogHandler)
        )

    def test_syslog_handler_added_when_host_configured(self, monkeypatch):
        """SysLogHandler is added to root logger when SIEM_SYSLOG_HOST is set."""
        # Use 127.0.0.1 to avoid DNS lookup; SysLogHandler resolves at construction
        monkeypatch.setenv("SIEM_SYSLOG_HOST", "127.0.0.1")
        monkeypatch.setenv("SIEM_SYSLOG_PORT", "60514")  # high port avoids privilege issues

        # Remove any pre-existing syslog handlers targeting our test host
        root = logging.getLogger()
        for h in list(root.handlers):
            if (isinstance(h, logging.handlers.SysLogHandler)
                    and getattr(h, "address", None) == ("127.0.0.1", 60514)):
                root.removeHandler(h)

        from agent.siem import configure_siem_logging
        result = configure_siem_logging()
        assert result is True

        after = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.SysLogHandler)
            and getattr(h, "address", None) == ("127.0.0.1", 60514)
        ]
        assert len(after) == 1

        # Cleanup
        root.removeHandler(after[0])

    def test_no_syslog_handler_without_config(self, monkeypatch):
        """configure_siem_logging() is a no-op when SIEM_SYSLOG_HOST is unset."""
        monkeypatch.delenv("SIEM_SYSLOG_HOST", raising=False)
        before = self._count_syslog_handlers()

        from agent.siem import configure_siem_logging
        result = configure_siem_logging()
        assert result is False
        assert self._count_syslog_handlers() == before

    def test_syslog_handler_idempotent(self, monkeypatch):
        """Calling configure_siem_logging() twice does not add duplicate handlers."""
        monkeypatch.setenv("SIEM_SYSLOG_HOST", "127.0.0.1")
        monkeypatch.setenv("SIEM_SYSLOG_PORT", "60515")

        root = logging.getLogger()
        # Clean state
        for h in list(root.handlers):
            if (isinstance(h, logging.handlers.SysLogHandler)
                    and getattr(h, "address", None) == ("127.0.0.1", 60515)):
                root.removeHandler(h)

        from agent.siem import configure_siem_logging
        configure_siem_logging()
        configure_siem_logging()  # second call — should be no-op

        handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.SysLogHandler)
            and getattr(h, "address", None) == ("127.0.0.1", 60515)
        ]
        assert len(handlers) == 1

        # Cleanup
        root.removeHandler(handlers[0])
