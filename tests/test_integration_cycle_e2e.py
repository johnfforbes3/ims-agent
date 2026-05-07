"""
End-to-end integration tests: full simulated cycle.

Runs a real CycleRunner with:
  - CALL_TRANSPORT=simulated  (CAM simulator, not real Teams)
  - Real data/sample_ims.xml
  - Real Anthropic LLM calls (claude-haiku-4-5)
  - SIMULATOR_CALL_DELAY_MS=0 (no throttling)

Marked @pytest.mark.integration — SKIPPED in CI unless ANTHROPIC_API_KEY is set.

Run manually:
  pytest tests/test_integration_cycle_e2e.py -m integration -v -s

These tests act as the authoritative verification that:
  1. A full cycle completes without error
  2. The state file has the correct schema
  3. EVM, DCMA, and variance data are all written
  4. All Phase 9 API endpoints return 200 after the cycle
  5. GET /api/briefing produces a valid HTML document with real data
  6. The relay bus has events (greetings sent during cycle)
"""

import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Required keys / shapes
# ---------------------------------------------------------------------------

_REQUIRED_STATE_KEYS = frozenset({
    "cycle_id", "health", "summary", "top_risks",
    "cams_responded", "cams_total", "cam_status",
})
_REQUIRED_EVM_PROGRAM_KEYS = frozenset({
    "BAC", "BCWP", "BCWS", "SPI", "SV", "EAC", "VAC", "TCPI", "BEI",
})
_REQUIRED_DCMA_KEYS = frozenset({
    "score", "max_score", "overall_health", "checks",
})
_REQUIRED_VARIANCE_SECTIONS = frozenset({
    "technical_performance", "schedule_variance",
    "cost_variance", "corrective_actions", "forward_look",
})


# ---------------------------------------------------------------------------
# Module-scoped fixture: run cycle once, reuse state across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cycle_output(tmp_path_factory):
    """
    Run one full simulated cycle. Returns dict with:
      state     — parsed dashboard_state.json
      state_file — Path to state file (for server fixture)
      reports_dir — Path to reports dir
    """
    pytest.importorskip("anthropic", reason="anthropic package required")
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping E2E cycle tests")

    ims_path = Path(__file__).parent.parent / "data" / "sample_ims.xml"
    if not ims_path.exists():
        pytest.skip("data/sample_ims.xml not found")

    tmp = tmp_path_factory.mktemp("cycle_e2e")
    state_file = tmp / "state.json"
    reports_dir = tmp / "reports"
    reports_dir.mkdir()

    # Configure environment for the cycle
    for key, val in [
        ("DASHBOARD_STATE_FILE", str(state_file)),
        ("REPORTS_DIR", str(reports_dir)),
        ("CALL_TRANSPORT", "simulated"),
        ("SIMULATOR_CALL_DELAY_MS", "0"),
        ("SIMULATOR_MODEL", os.getenv("SIMULATOR_MODEL", "claude-haiku-4-5")),
        ("LLM_MODEL", os.getenv("LLM_MODEL", "claude-haiku-4-5")),
        ("CLASSIFIER_MODEL", os.getenv("CLASSIFIER_MODEL", "claude-haiku-4-5")),
    ]:
        os.environ[key] = val

    # Pre-populate the COM/MPXJ availability cache so the probe never runs.
    # win32com.client.Dispatch("MSProject.Application") can raise a fatal
    # Windows SEH (0x80010108 RPC_E_DISCONNECTED) when MS Project is in a broken
    # C2R AppV state, crashing the Python process before any except clause runs.
    import agent.mpp_converter as _mpp
    _mpp._com_ok  = False   # skip COM probe entirely in test environment
    _mpp._mpxj_ok = False   # skip MPXJ probe (no JVM in CI/test)

    # Reset relay bus before cycle
    from agent.voice import interview_relay
    interview_relay.InterviewRelayBus._instance = None

    from agent.cycle_runner import CycleRunner
    runner = CycleRunner(ims_path=str(ims_path), mode="simulated")
    runner.run()

    assert state_file.exists(), "State file not written after full cycle"
    state = json.loads(state_file.read_text(encoding="utf-8"))

    return {"state": state, "state_file": state_file, "reports_dir": reports_dir}


@pytest.fixture(scope="module")
def cycle_api_client(cycle_output):
    """FastAPI TestClient pointed at the post-cycle state file."""
    import importlib
    import agent.dashboard.server as srv
    os.environ["DASHBOARD_API_KEY"] = ""
    os.environ["DASHBOARD_ADMIN_KEY"] = ""
    importlib.reload(srv)
    srv._STATE_FILE = str(cycle_output["state_file"])
    srv._REPORTS_DIR = str(cycle_output["reports_dir"])
    from fastapi.testclient import TestClient
    return TestClient(srv.app, raise_server_exceptions=False)


# ===========================================================================
# State file structure
# ===========================================================================

@pytest.mark.integration
class TestFullCycleStateFile:
    def test_state_written(self, cycle_output):
        assert cycle_output["state"] is not None

    def test_required_top_level_keys(self, cycle_output):
        state = cycle_output["state"]
        for key in _REQUIRED_STATE_KEYS:
            assert key in state, f"State missing key: {key}"

    def test_health_is_valid(self, cycle_output):
        assert cycle_output["state"]["health"] in ("GREEN", "YELLOW", "RED")

    def test_cycle_id_format(self, cycle_output):
        cid = cycle_output["state"]["cycle_id"]
        assert len(cid) == 16 and "T" in cid, f"Unexpected cycle_id format: {cid!r}"

    def test_cams_responded_positive(self, cycle_output):
        assert cycle_output["state"]["cams_responded"] > 0

    def test_cams_total_matches_ims(self, cycle_output):
        # Sample IMS has 5 CAMs
        assert cycle_output["state"]["cams_total"] == 5

    def test_cam_status_has_entries(self, cycle_output):
        assert len(cycle_output["state"].get("cam_status", {})) > 0

    def test_summary_is_non_empty_string(self, cycle_output):
        s = cycle_output["state"].get("summary", "")
        assert isinstance(s, str) and len(s) > 10


# ===========================================================================
# EVM data
# ===========================================================================

@pytest.mark.integration
class TestFullCycleEVM:
    def test_evm_key_present(self, cycle_output):
        assert "evm" in cycle_output["state"], "EVM data missing from state"

    def test_program_has_all_metrics(self, cycle_output):
        prog = cycle_output["state"]["evm"]["program"]
        for key in _REQUIRED_EVM_PROGRAM_KEYS:
            assert key in prog, f"EVM program missing: {key}"

    def test_spi_is_positive_float(self, cycle_output):
        spi = cycle_output["state"]["evm"]["program"]["SPI"]
        assert isinstance(spi, (int, float)) and spi > 0

    def test_bac_positive(self, cycle_output):
        bac = cycle_output["state"]["evm"]["program"]["BAC"]
        assert bac > 0

    def test_by_cam_non_empty(self, cycle_output):
        by_cam = cycle_output["state"]["evm"]["by_cam"]
        assert len(by_cam) > 0

    def test_by_cam_each_has_spi(self, cycle_output):
        for cam, metrics in cycle_output["state"]["evm"]["by_cam"].items():
            assert "SPI" in metrics, f"CAM {cam} missing SPI"


# ===========================================================================
# DCMA data
# ===========================================================================

@pytest.mark.integration
class TestFullCycleDCMA:
    def test_dcma_key_present(self, cycle_output):
        assert "dcma" in cycle_output["state"], "DCMA data missing from state"

    def test_dcma_has_required_keys(self, cycle_output):
        dcma = cycle_output["state"]["dcma"]
        for key in _REQUIRED_DCMA_KEYS:
            assert key in dcma, f"DCMA missing key: {key}"

    def test_score_in_range(self, cycle_output):
        dcma = cycle_output["state"]["dcma"]
        assert 0 <= dcma["score"] <= dcma["max_score"]

    def test_has_14_checks(self, cycle_output):
        assert len(cycle_output["state"]["dcma"]["checks"]) == 14

    def test_overall_health_valid(self, cycle_output):
        h = cycle_output["state"]["dcma"]["overall_health"]
        assert h in ("GREEN", "YELLOW", "RED")

    def test_score_matches_passed_checks(self, cycle_output):
        dcma = cycle_output["state"]["dcma"]
        passed = sum(1 for c in dcma["checks"] if c.get("passed"))
        assert dcma["score"] == passed


# ===========================================================================
# Variance data
# ===========================================================================

@pytest.mark.integration
class TestFullCycleVariance:
    def test_variance_key_present(self, cycle_output):
        assert "variance" in cycle_output["state"], "Variance data missing"

    def test_has_all_sections(self, cycle_output):
        sections = cycle_output["state"]["variance"]["sections"]
        for key in _REQUIRED_VARIANCE_SECTIONS:
            assert key in sections, f"Variance missing section: {key}"

    def test_sections_non_empty(self, cycle_output):
        for key, text in cycle_output["state"]["variance"]["sections"].items():
            assert isinstance(text, str) and len(text) > 10, \
                f"Variance section {key!r} too short: {text!r}"

    def test_cycle_id_matches(self, cycle_output):
        assert (cycle_output["state"]["variance"]["cycle_id"] ==
                cycle_output["state"]["cycle_id"])


# ===========================================================================
# API endpoints after full cycle
# ===========================================================================

@pytest.mark.integration
class TestFullCycleAPIEndpoints:
    def test_health_200(self, cycle_api_client):
        assert cycle_api_client.get("/health").status_code == 200

    def test_evm_200(self, cycle_api_client):
        assert cycle_api_client.get("/api/evm").status_code == 200

    def test_dcma_200(self, cycle_api_client):
        assert cycle_api_client.get("/api/dcma").status_code == 200

    def test_variance_200(self, cycle_api_client):
        assert cycle_api_client.get("/api/variance").status_code == 200

    def test_briefing_200(self, cycle_api_client):
        resp = cycle_api_client.get("/api/briefing")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_briefing_has_real_spi(self, cycle_api_client, cycle_output):
        html = cycle_api_client.get("/api/briefing").text
        assert "SPI" in html

    def test_state_200(self, cycle_api_client):
        assert cycle_api_client.get("/api/state").status_code == 200

    def test_evm_spi_plausible(self, cycle_api_client):
        spi = cycle_api_client.get("/api/evm").json()["program"]["SPI"]
        assert 0.1 < spi < 3.0, f"SPI out of plausible range: {spi}"

    def test_dcma_14_checks(self, cycle_api_client):
        checks = cycle_api_client.get("/api/dcma").json()["checks"]
        assert len(checks) == 14

    def test_variance_sections_non_empty(self, cycle_api_client):
        sections = cycle_api_client.get("/api/variance").json()["sections"]
        for k, v in sections.items():
            assert len(v) > 10, f"Variance section {k} too short after real cycle"


# ===========================================================================
# Relay bus populated during cycle
# ===========================================================================

@pytest.mark.integration
class TestFullCycleRelayBus:
    """
    After a simulated cycle, the relay bus should have received greeting
    events for each CAM (pushed by cycle_runner when greetings were sent).
    """

    def test_relay_has_events(self, cycle_output):
        from agent.voice.interview_relay import InterviewRelayBus
        bus = InterviewRelayBus.get()
        # A full cycle interviews multiple CAMs — there should be many events
        events = bus.recent_events(n=100)
        assert len(events) > 0, "No events in relay bus after full cycle"

    def test_relay_has_bot_turns(self, cycle_output):
        from agent.voice.interview_relay import InterviewRelayBus
        bus = InterviewRelayBus.get()
        bot_events = [e for e in bus.recent_events(n=100) if e.speaker == "bot"]
        assert len(bot_events) > 0, "No bot turns in relay bus"

    def test_relay_has_cam_turns(self, cycle_output):
        from agent.voice.interview_relay import InterviewRelayBus
        bus = InterviewRelayBus.get()
        cam_events = [e for e in bus.recent_events(n=100) if e.speaker == "cam"]
        assert len(cam_events) > 0, "No CAM turns in relay bus"

    def test_relay_events_have_cycle_id(self, cycle_output):
        from agent.voice.interview_relay import InterviewRelayBus
        bus = InterviewRelayBus.get()
        cycle_id = cycle_output["state"]["cycle_id"]
        events_with_cycle = [
            e for e in bus.recent_events(n=100)
            if e.cycle_id == cycle_id
        ]
        assert len(events_with_cycle) > 0, \
            f"No relay events tagged with cycle_id={cycle_id}"
