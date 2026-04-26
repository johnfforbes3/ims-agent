"""
Phase 5 tests — metrics, RBAC, rate limiting, purge, LLM_BASE_URL.

Covers every item added during Phase 5 production hardening.
"""

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


# ===========================================================================
# Metrics module
# ===========================================================================

class TestMetrics:
    @pytest.fixture(autouse=True)
    def reset_metrics(self):
        from agent import metrics
        with metrics._lock:
            metrics._counters.update({
                "cycles_completed": 0,
                "cycles_failed": 0,
                "last_cycle_id": None,
                "last_cycle_duration_seconds": None,
                "qa_queries_total": 0,
                "qa_queries_direct": 0,
                "qa_queries_llm": 0,
            })

    def test_increment(self):
        from agent.metrics import increment, snapshot
        increment("cycles_completed")
        assert snapshot()["cycles_completed"] == 1

    def test_increment_by_amount(self):
        from agent.metrics import increment, snapshot
        increment("qa_queries_total", 5)
        assert snapshot()["qa_queries_total"] == 5

    def test_increment_unknown_key_ignored(self):
        from agent.metrics import increment
        increment("nonexistent_key")  # must not raise

    def test_set_value(self):
        from agent.metrics import set_value, snapshot
        set_value("last_cycle_id", "20260426T060000Z")
        assert snapshot()["last_cycle_id"] == "20260426T060000Z"

    def test_snapshot_returns_independent_copy(self):
        from agent.metrics import snapshot, set_value
        s1 = snapshot()
        set_value("last_cycle_id", "changed")
        s2 = snapshot()
        assert s1["last_cycle_id"] is None
        assert s2["last_cycle_id"] == "changed"

    def test_thread_safe_increment(self):
        from agent.metrics import increment, snapshot
        errors = []

        def worker():
            try:
                for _ in range(100):
                    increment("qa_queries_total")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert snapshot()["qa_queries_total"] == 1000

    def test_all_expected_keys_present(self):
        from agent.metrics import snapshot
        keys = snapshot().keys()
        for k in ("cycles_completed", "cycles_failed", "qa_queries_total",
                  "qa_queries_direct", "qa_queries_llm"):
            assert k in keys


# ===========================================================================
# Data retention / purge
# ===========================================================================

class TestPurgeOldData:
    def test_deletes_old_cycle_status_json(self, tmp_path, monkeypatch):
        import agent.cycle_runner as cr

        reports_dir = tmp_path / "reports" / "cycles"
        reports_dir.mkdir(parents=True)
        snap_dir = tmp_path / "data" / "snapshots"
        snap_dir.mkdir(parents=True)

        old_file = reports_dir / "20230101T060000Z_status.json"
        old_file.write_text("{}", encoding="utf-8")
        stale = time.time() - (100 * 86400)
        os.utime(old_file, (stale, stale))

        new_file = reports_dir / "20260101T060000Z_status.json"
        new_file.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(cr, "_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setattr(cr, "_DATA_DIR", str(tmp_path / "data"))

        deleted = cr.CycleRunner.purge_old_data(retention_days=90)

        assert deleted["cycle_status"] == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_deletes_old_xml_snapshots(self, tmp_path, monkeypatch):
        import agent.cycle_runner as cr

        snap_dir = tmp_path / "data" / "snapshots"
        snap_dir.mkdir(parents=True)
        (tmp_path / "reports" / "cycles").mkdir(parents=True)

        old_snap = snap_dir / "20230101T060000Z_sample.xml"
        old_snap.write_text("<project/>", encoding="utf-8")
        stale = time.time() - (100 * 86400)
        os.utime(old_snap, (stale, stale))

        monkeypatch.setattr(cr, "_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setattr(cr, "_DATA_DIR", str(tmp_path / "data"))

        deleted = cr.CycleRunner.purge_old_data(retention_days=90)
        assert deleted["snapshots"] == 1
        assert not old_snap.exists()

    def test_returns_zeros_when_nothing_to_delete(self, tmp_path, monkeypatch):
        import agent.cycle_runner as cr
        monkeypatch.setattr(cr, "_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setattr(cr, "_DATA_DIR", str(tmp_path / "data"))

        deleted = cr.CycleRunner.purge_old_data(retention_days=90)
        assert deleted == {"cycle_status": 0, "snapshots": 0}

    def test_recent_files_not_deleted(self, tmp_path, monkeypatch):
        import agent.cycle_runner as cr

        reports_dir = tmp_path / "reports" / "cycles"
        reports_dir.mkdir(parents=True)
        (tmp_path / "data" / "snapshots").mkdir(parents=True)

        recent_file = reports_dir / "20260101T060000Z_status.json"
        recent_file.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(cr, "_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setattr(cr, "_DATA_DIR", str(tmp_path / "data"))

        deleted = cr.CycleRunner.purge_old_data(retention_days=90)
        assert deleted["cycle_status"] == 0
        assert recent_file.exists()


# ===========================================================================
# LLM_BASE_URL — on-prem model support
# ===========================================================================

class TestLLMBaseURL:
    def test_base_url_passed_to_anthropic_client(self, monkeypatch):
        monkeypatch.setattr("agent.llm_interface._BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value = MagicMock()
            from agent.llm_interface import LLMInterface
            LLMInterface()

        _, kwargs = mock_cls.call_args
        assert kwargs.get("base_url") == "http://localhost:11434"

    def test_no_base_url_by_default(self, monkeypatch):
        monkeypatch.setattr("agent.llm_interface._BASE_URL", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value = MagicMock()
            from agent.llm_interface import LLMInterface
            LLMInterface()

        _, kwargs = mock_cls.call_args
        assert "base_url" not in kwargs


# ===========================================================================
# Dashboard server — shared fixtures
# ===========================================================================

@pytest.fixture
def dev_client(monkeypatch):
    """TestClient with auth fully disabled (dev mode: no keys set)."""
    import agent.dashboard.server as srv
    monkeypatch.setattr(srv, "_API_KEY", "")
    monkeypatch.setattr(srv, "_ADMIN_KEY", "")
    srv._rate_limiter.clear()
    from fastapi.testclient import TestClient
    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture
def two_key_client(monkeypatch):
    """TestClient with separate read and admin keys configured."""
    import agent.dashboard.server as srv
    monkeypatch.setattr(srv, "_API_KEY", "read-key")
    monkeypatch.setattr(srv, "_ADMIN_KEY", "admin-key")
    srv._rate_limiter.clear()
    from fastapi.testclient import TestClient
    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.fixture
def single_key_client(monkeypatch):
    """TestClient with one key for both read and admin (no ADMIN_KEY)."""
    import agent.dashboard.server as srv
    monkeypatch.setattr(srv, "_API_KEY", "shared-key")
    monkeypatch.setattr(srv, "_ADMIN_KEY", "")
    srv._rate_limiter.clear()
    from fastapi.testclient import TestClient
    return TestClient(srv.app, raise_server_exceptions=False)


# ===========================================================================
# /health — always unauthenticated
# ===========================================================================

class TestHealthEndpoint:
    def test_returns_200_dev(self, dev_client):
        r = dev_client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_returns_200_without_key_even_when_auth_enabled(self, two_key_client):
        r = two_key_client.get("/health")
        assert r.status_code == 200

    def test_includes_uptime_and_auth_flag(self, two_key_client):
        r = two_key_client.get("/health")
        data = r.json()
        assert "uptime_seconds" in data
        assert data["auth_enabled"] is True


# ===========================================================================
# GET /metrics
# ===========================================================================

class TestMetricsEndpoint:
    def test_accessible_in_dev_mode(self, dev_client):
        r = dev_client.get("/metrics")
        assert r.status_code == 200
        data = r.json()
        assert "cycles_completed" in data

    def test_requires_key_when_auth_enabled(self, two_key_client):
        r = two_key_client.get("/metrics")
        assert r.status_code == 401

    def test_read_key_grants_access(self, two_key_client):
        r = two_key_client.get("/metrics", headers={"X-API-Key": "read-key"})
        assert r.status_code == 200


# ===========================================================================
# POST /api/admin/purge — admin-only
# ===========================================================================

class TestAdminPurgeEndpoint:
    def test_no_key_returns_401(self, two_key_client):
        r = two_key_client.post("/api/admin/purge")
        assert r.status_code == 401

    def test_read_key_rejected_in_two_key_mode(self, two_key_client):
        r = two_key_client.post("/api/admin/purge", headers={"X-API-Key": "read-key"})
        assert r.status_code == 401

    def test_admin_key_accepted(self, two_key_client):
        with patch("agent.cycle_runner.CycleRunner.purge_old_data",
                   return_value={"cycle_status": 3, "snapshots": 1}):
            r = two_key_client.post("/api/admin/purge",
                                    headers={"X-Admin-Key": "admin-key"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["deleted"]["cycle_status"] == 3

    def test_dev_mode_no_key_needed(self, dev_client):
        with patch("agent.cycle_runner.CycleRunner.purge_old_data",
                   return_value={"cycle_status": 0, "snapshots": 0}):
            r = dev_client.post("/api/admin/purge")
        assert r.status_code == 200


# ===========================================================================
# POST /api/trigger — admin-only
# ===========================================================================

class TestTriggerEndpoint:
    def test_admin_key_required_in_two_key_mode(self, two_key_client):
        r = two_key_client.post("/api/trigger", headers={"X-API-Key": "read-key"})
        assert r.status_code == 401

    def test_admin_key_triggers_cycle(self, two_key_client):
        with patch("agent.cycle_runner.CycleRunner.is_active", return_value=False), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            r = two_key_client.post("/api/trigger", headers={"X-Admin-Key": "admin-key"})
        assert r.status_code == 200

    def test_single_key_mode_api_key_triggers_cycle(self, single_key_client):
        with patch("agent.cycle_runner.CycleRunner.is_active", return_value=False), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            r = single_key_client.post("/api/trigger", headers={"X-API-Key": "shared-key"})
        assert r.status_code == 200


# ===========================================================================
# RBAC — single-key fallback behaviour
# ===========================================================================

class TestRBACFallback:
    def test_single_key_api_key_accepted_for_admin(self, single_key_client):
        with patch("agent.cycle_runner.CycleRunner.purge_old_data",
                   return_value={"cycle_status": 0, "snapshots": 0}):
            r = single_key_client.post("/api/admin/purge",
                                       headers={"X-API-Key": "shared-key"})
        assert r.status_code == 200

    def test_two_key_mode_read_key_cannot_admin(self, two_key_client):
        r = two_key_client.post("/api/admin/purge", headers={"X-API-Key": "read-key"})
        assert r.status_code == 401

    def test_two_key_mode_admin_key_via_x_admin_key_header(self, two_key_client):
        with patch("agent.cycle_runner.CycleRunner.purge_old_data",
                   return_value={"cycle_status": 0, "snapshots": 0}):
            r = two_key_client.post("/api/admin/purge",
                                    headers={"X-Admin-Key": "admin-key"})
        assert r.status_code == 200


# ===========================================================================
# Rate limiting
# ===========================================================================

class TestRateLimiting:
    @pytest.fixture(autouse=True)
    def reset_rate_limiter(self):
        import agent.dashboard.server as srv
        srv._rate_limiter.clear()

    def test_blocks_after_limit_reached(self, monkeypatch):
        import agent.dashboard.server as srv
        monkeypatch.setattr(srv, "_QA_RATE_LIMIT", 3)

        for _ in range(3):
            srv._check_rate_limit("1.2.3.4")

        with pytest.raises(HTTPException) as exc_info:
            srv._check_rate_limit("1.2.3.4")
        assert exc_info.value.status_code == 429

    def test_zero_disables_rate_limiting(self, monkeypatch):
        import agent.dashboard.server as srv
        monkeypatch.setattr(srv, "_QA_RATE_LIMIT", 0)

        for _ in range(200):
            srv._check_rate_limit("1.2.3.4")  # must not raise

    def test_independent_per_ip(self, monkeypatch):
        import agent.dashboard.server as srv
        monkeypatch.setattr(srv, "_QA_RATE_LIMIT", 2)

        srv._check_rate_limit("10.0.0.1")
        srv._check_rate_limit("10.0.0.1")
        # 10.0.0.1 is at limit; 10.0.0.2 should still succeed
        srv._check_rate_limit("10.0.0.2")

    def test_stale_entries_outside_window_dont_count(self, monkeypatch):
        import agent.dashboard.server as srv
        monkeypatch.setattr(srv, "_QA_RATE_LIMIT", 2)

        # Inject entries older than 1 hour
        stale = time.monotonic() - 3700
        srv._rate_limiter["5.5.5.5"] = [stale, stale]

        # Stale entries should be purged — this call should succeed
        srv._check_rate_limit("5.5.5.5")

    def test_ask_endpoint_rate_limited(self, monkeypatch, dev_client):
        import agent.dashboard.server as srv
        monkeypatch.setattr(srv, "_QA_RATE_LIMIT", 1)

        state = {
            "cycle_id": "c1", "schedule_health": "GREEN",
            "critical_path_task_ids": [], "milestones": [],
            "top_risks": "r1", "recommended_actions": "", "narrative": "",
            "tasks_behind": [], "cam_response_status": {},
        }
        with patch("agent.qa.context_builder.load_state", return_value=state):
            r1 = dev_client.post("/api/ask", json={"question": "What are the top risks?"})
            r2 = dev_client.post("/api/ask", json={"question": "What are the top risks?"})

        assert r1.status_code == 200
        assert r2.status_code == 429


# ===========================================================================
# QAEngine metrics wiring
# ===========================================================================

class TestQAEngineMetrics:
    @pytest.fixture(autouse=True)
    def reset_metrics(self):
        from agent import metrics
        with metrics._lock:
            metrics._counters.update({
                "cycles_completed": 0, "cycles_failed": 0,
                "last_cycle_id": None, "last_cycle_duration_seconds": None,
                "qa_queries_total": 0, "qa_queries_direct": 0, "qa_queries_llm": 0,
            })

    def _make_state(self, tmp_path, **overrides):
        base = {
            "cycle_id": "c1", "schedule_health": "GREEN",
            "critical_path_task_ids": [], "milestones": [],
            "top_risks": "", "recommended_actions": "",
            "narrative": "", "tasks_behind": [], "cam_response_status": {},
        }
        base.update(overrides)
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(base), encoding="utf-8")
        return state_file

    def test_direct_path_increments_direct_counter(self, tmp_path, monkeypatch):
        import agent.qa.context_builder as cb
        sf = self._make_state(tmp_path, top_risks="Risk 1")
        monkeypatch.setattr(cb, "_STATE_FILE", sf)

        from agent.qa.qa_engine import QAEngine
        from agent.metrics import snapshot
        QAEngine().ask("What are the top risks?")
        s = snapshot()
        assert s["qa_queries_total"] == 1
        assert s["qa_queries_direct"] == 1
        assert s["qa_queries_llm"] == 0

    def test_llm_path_increments_llm_counter(self, tmp_path, monkeypatch):
        import agent.qa.context_builder as cb
        sf = self._make_state(tmp_path)
        monkeypatch.setattr(cb, "_STATE_FILE", sf)

        from agent.qa.qa_engine import QAEngine
        from agent.metrics import snapshot
        with patch("agent.llm_interface.LLMInterface.ask_with_tools",
                   return_value="Because of X"):
            QAEngine().ask("Why is task SE-03 behind?")
        s = snapshot()
        assert s["qa_queries_total"] == 1
        assert s["qa_queries_llm"] == 1
        assert s["qa_queries_direct"] == 0

    def test_no_state_does_not_increment(self, tmp_path, monkeypatch):
        import agent.qa.context_builder as cb
        monkeypatch.setattr(cb, "_STATE_FILE", tmp_path / "nonexistent.json")

        from agent.qa.qa_engine import QAEngine
        from agent.metrics import snapshot
        QAEngine().ask("What is the schedule health?")
        s = snapshot()
        assert s["qa_queries_total"] == 0
