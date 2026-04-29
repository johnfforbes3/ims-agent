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

import pytest
from unittest.mock import patch


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
