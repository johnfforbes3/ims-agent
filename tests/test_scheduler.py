"""Tests for agent.scheduler — CycleScheduler."""

import time
from unittest.mock import MagicMock, patch

import pytest


class TestCycleScheduler:
    def test_scheduler_starts_and_stops(self):
        from agent.scheduler import CycleScheduler

        calls = []
        scheduler = CycleScheduler(cycle_fn=lambda: calls.append(1))
        scheduler.start()
        assert scheduler.is_running
        scheduler.stop()
        assert not scheduler.is_running

    def test_next_run_time_is_set_after_start(self):
        from agent.scheduler import CycleScheduler

        scheduler = CycleScheduler(cycle_fn=lambda: None)
        scheduler.start()
        try:
            assert scheduler.next_run_time is not None
        finally:
            scheduler.stop()

    def test_pause_and_resume(self):
        from agent.scheduler import CycleScheduler

        scheduler = CycleScheduler(cycle_fn=lambda: None)
        scheduler.start()
        try:
            scheduler.pause()
            # APScheduler marks job paused — next_run_time becomes None when paused
            scheduler.resume()
            assert scheduler.is_running
        finally:
            scheduler.stop()

    def test_trigger_now_does_not_raise(self):
        from agent.scheduler import CycleScheduler

        called = []
        scheduler = CycleScheduler(cycle_fn=lambda: called.append(1))
        scheduler.start()
        try:
            scheduler.trigger_now()
            time.sleep(0.5)  # give the job a moment to fire
        finally:
            scheduler.stop()
        assert len(called) >= 1

    def test_next_run_time_none_before_start(self):
        from agent.scheduler import CycleScheduler

        scheduler = CycleScheduler(cycle_fn=lambda: None)
        assert scheduler.next_run_time is None
        assert not scheduler.is_running
