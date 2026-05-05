"""
Tests for agent.bootstrap_sessions — TD-023 bootstrap CLI utility.

Covers:
  - find_missing_cams: all-missing, partial, none-missing, cam_filter,
    case-insensitive filter, skips entries without email
  - load_identity_map / load_sessions: present and absent files
  - bootstrap() orchestrator: no-credentials path, all-present path
"""

import json
import pytest
from pathlib import Path

from agent.bootstrap_sessions import (
    find_missing_cams,
    load_identity_map,
    load_sessions,
    bootstrap,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def identity_map_5():
    """Full five-CAM identity map (mirrors the real cam_identity_map.json)."""
    return {
        "Alice Nguyen": {
            "email": "alice@intelligenceexpanse.onmicrosoft.com",
            "auto_respond": True,
            "responder_type": "graph",
        },
        "Bob Martinez": {
            "email": "bob@intelligenceexpanse.onmicrosoft.com",
            "auto_respond": True,
            "responder_type": "graph",
        },
        "Carol Smith": {
            "email": "carol@intelligenceexpanse.onmicrosoft.com",
            "auto_respond": True,
            "responder_type": "graph",
        },
        "David Lee": {
            "email": "david@intelligenceexpanse.onmicrosoft.com",
            "auto_respond": True,
            "responder_type": "graph",
        },
        "Eva Johnson": {
            "email": "eva@intelligenceexpanse.onmicrosoft.com",
            "auto_respond": True,
            "responder_type": "graph",
        },
    }


@pytest.fixture()
def sessions_alice_only():
    return {"alice@intelligenceexpanse.onmicrosoft.com": {"conversation_id": "abc123"}}


@pytest.fixture()
def sessions_all_five(identity_map_5):
    return {info["email"]: {"conversation_id": f"conv_{name[:3]}"}
            for name, info in identity_map_5.items()}


# ---------------------------------------------------------------------------
# find_missing_cams
# ---------------------------------------------------------------------------

class TestFindMissingCams:
    def test_all_missing_when_sessions_empty(self, identity_map_5):
        missing = find_missing_cams(identity_map_5, sessions={})
        assert len(missing) == 5
        names = {c["name"] for c in missing}
        assert names == {"Alice Nguyen", "Bob Martinez", "Carol Smith",
                         "David Lee", "Eva Johnson"}

    def test_partial_missing(self, identity_map_5, sessions_alice_only):
        missing = find_missing_cams(identity_map_5, sessions_alice_only)
        assert len(missing) == 4
        names = {c["name"] for c in missing}
        assert "Alice Nguyen" not in names
        assert "Bob Martinez" in names

    def test_none_missing_when_all_present(self, identity_map_5, sessions_all_five):
        missing = find_missing_cams(identity_map_5, sessions_all_five)
        assert missing == []

    def test_cam_filter_selects_single_cam(self, identity_map_5):
        missing = find_missing_cams(identity_map_5, sessions={},
                                    cam_filter="Alice Nguyen")
        assert len(missing) == 1
        assert missing[0]["name"] == "Alice Nguyen"
        assert missing[0]["email"] == "alice@intelligenceexpanse.onmicrosoft.com"

    def test_cam_filter_case_insensitive(self, identity_map_5):
        missing = find_missing_cams(identity_map_5, sessions={},
                                    cam_filter="alice nguyen")
        assert len(missing) == 1
        assert missing[0]["name"] == "Alice Nguyen"

    def test_skips_cams_without_email(self):
        identity_map = {
            "Alice Nguyen": {"email": "alice@test.com"},
            "No Email CAM": {},  # missing email field
        }
        missing = find_missing_cams(identity_map, sessions={})
        assert len(missing) == 1
        assert missing[0]["name"] == "Alice Nguyen"

    def test_missing_cam_dict_has_expected_keys(self, identity_map_5):
        missing = find_missing_cams(identity_map_5, sessions={},
                                    cam_filter="Bob Martinez")
        cam = missing[0]
        assert "name" in cam
        assert "email" in cam
        assert "auto_respond" in cam
        assert "responder_type" in cam


# ---------------------------------------------------------------------------
# load_identity_map / load_sessions
# ---------------------------------------------------------------------------

class TestLoadHelpers:
    def test_load_identity_map_from_file(self, tmp_path):
        data = {"Alice": {"email": "alice@example.com"}}
        p = tmp_path / "id_map.json"
        p.write_text(json.dumps(data))
        result = load_identity_map(p)
        assert result == data

    def test_load_identity_map_missing_file_returns_empty(self, tmp_path):
        result = load_identity_map(tmp_path / "does_not_exist.json")
        assert result == {}

    def test_load_sessions_from_file(self, tmp_path):
        data = {"alice@example.com": {"conversation_id": "xyz"}}
        p = tmp_path / "sessions.json"
        p.write_text(json.dumps(data))
        result = load_sessions(p)
        assert result == data

    def test_load_sessions_missing_file_returns_empty(self, tmp_path):
        result = load_sessions(tmp_path / "does_not_exist.json")
        assert result == {}


# ---------------------------------------------------------------------------
# bootstrap() orchestrator
# ---------------------------------------------------------------------------

class TestBootstrapOrchestrator:
    def test_returns_zero_when_all_present(self, tmp_path, identity_map_5,
                                           sessions_all_five, capsys):
        id_path = tmp_path / "id.json"
        sess_path = tmp_path / "sess.json"
        id_path.write_text(json.dumps(identity_map_5))
        sess_path.write_text(json.dumps(sessions_all_five))

        result = bootstrap(identity_map_path=id_path, sessions_path=sess_path)
        assert result == 0
        out = capsys.readouterr().out
        assert "already have" in out.lower() or "all cams" in out.lower()

    def test_returns_one_when_cams_missing_no_creds(self, tmp_path,
                                                     identity_map_5, capsys,
                                                     monkeypatch):
        # Clear Graph API env vars so automated email is not attempted
        for var in ["TEAMS_TENANT_ID", "TEAMS_BOT_APP_ID",
                    "TEAMS_BOT_APP_SECRET", "BOOTSTRAP_SENDER_EMAIL"]:
            monkeypatch.delenv(var, raising=False)

        id_path = tmp_path / "id.json"
        sess_path = tmp_path / "sess.json"
        id_path.write_text(json.dumps(identity_map_5))
        sess_path.write_text(json.dumps({}))  # no sessions

        result = bootstrap(identity_map_path=id_path, sessions_path=sess_path)
        assert result == 1
        out = capsys.readouterr().out
        assert "manual" in out.lower()

    def test_cam_filter_passed_to_find(self, tmp_path, identity_map_5, capsys,
                                       monkeypatch):
        for var in ["TEAMS_TENANT_ID", "TEAMS_BOT_APP_ID",
                    "TEAMS_BOT_APP_SECRET", "BOOTSTRAP_SENDER_EMAIL"]:
            monkeypatch.delenv(var, raising=False)

        id_path = tmp_path / "id.json"
        sess_path = tmp_path / "sess.json"
        id_path.write_text(json.dumps(identity_map_5))
        sess_path.write_text(json.dumps({}))

        result = bootstrap(cam_filter="Alice Nguyen",
                           identity_map_path=id_path, sessions_path=sess_path)
        assert result == 1
        out = capsys.readouterr().out
        # Only one CAM reported
        assert "Alice Nguyen" in out
        assert "Bob Martinez" not in out
