"""
Global pytest fixtures shared across all test modules.

Key concern: tests/test_cycle_runner.py calls CycleRunner.run() with a
nonexistent IMS path, expecting a graceful failure.  However, _run_inner()
first tries to load from data/ims_master/ via the mpp_converter.  When an
.mpp file is present there (COM backend), this triggers MS Project COM
automation, which can show modal dialogs and, if the connection is severed
mid-call, causes a Windows fatal exception that crashes the entire pytest
process.

The `no_mpp_master` fixture patches find_latest_master() to return None for
ALL unit tests that don't explicitly need it.  This makes every test that
exercises CycleRunner independent of whatever happens to be in data/ims_master/
at test time.

Tests that need the real MPP workflow should opt out with:
    @pytest.mark.usefixtures()  # do NOT include no_mpp_master
or by passing autouse=False and requesting the fixture explicitly.
"""

import os

import pytest
from unittest.mock import patch


def pytest_configure(config):
    """Register custom marks so pytest doesn't warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require external services or optional "
        "packages (e.g. openai-whisper, Azure credentials). Skipped in CI.",
    )
    config.addinivalue_line(
        "markers",
        "legacy: marks dashboard tests that target the Phase 12/12.1/14 "
        "monolithic dashboard layout (index.html with server-rendered IDs). "
        "Phase 15 replaced the dashboard with a React app where IDs are "
        "injected client-side, so these element-by-element string assertions "
        "no longer apply to the live `/` route.  They REMAIN valid when the "
        "soft-rollback flag IMS_LEGACY_DASHBOARD=1 is set, and run as a "
        "regression suite against the preserved legacy template.  Skipped "
        "by default; enable with `pytest -m legacy` or by exporting "
        "IMS_LEGACY_DASHBOARD=1 before the test run.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.legacy tests unless explicitly enabled.

    Phase 15 added this so the Phase 12/12.1/14 dashboard tests don't fail
    against the new React-based dashboard.  Two ways to run the legacy tests:

      1. Selector:  pytest -m legacy
      2. Env var:   IMS_LEGACY_DASHBOARD=1 pytest
                    (also flips the server route to render the old template)
    """
    legacy_enabled = (
        os.getenv("IMS_LEGACY_DASHBOARD") == "1"
        or "legacy" in (config.getoption("-m") or "")
    )
    if legacy_enabled:
        return
    skip_legacy = pytest.mark.skip(
        reason="Phase 12/12.1/14 dashboard tests — the Phase 15 React shell does "
               "not server-render these element IDs.  Set IMS_LEGACY_DASHBOARD=1 "
               "or run `pytest -m legacy` to execute them against the preserved "
               "legacy template."
    )
    for item in items:
        if "legacy" in item.keywords:
            item.add_marker(skip_legacy)


@pytest.fixture(autouse=True)
def no_mpp_master():
    """
    Prevent CycleRunner unit tests from hitting the real COM/MPP backend.

    Patches agent.mpp_converter.find_latest_master to always return None so
    _run_inner() skips the mpp→xml ingest step and proceeds straight to IMS
    file parsing (which fails gracefully when the file doesn't exist).
    """
    with patch("agent.mpp_converter.find_latest_master", return_value=None):
        yield
