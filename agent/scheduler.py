"""
Cycle scheduler — APScheduler wrapper for recurring IMS Agent cycles.

Supports cron-based scheduling, manual trigger (admin override),
pause/resume, and cycle locking to prevent duplicate runs.
"""

import logging
import os
from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Default: Monday at 06:00 in the configured timezone
_SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 6 * * 1")
_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "America/New_York")


class CycleScheduler:
    """
    APScheduler-backed scheduler for IMS Agent status cycles.

    Usage:
        scheduler = CycleScheduler(cycle_fn=runner.run)
        scheduler.start()           # begins background scheduling
        scheduler.trigger_now()     # admin override — fires immediately
        scheduler.pause()           # suspend without stopping
        scheduler.resume()
        scheduler.stop()            # clean shutdown
    """

    def __init__(self, cycle_fn: Callable[[], None]) -> None:
        self._cycle_fn = cycle_fn
        self._scheduler = BackgroundScheduler(timezone=_TIMEZONE)
        self._job = None

    def start(self) -> None:
        trigger = CronTrigger.from_crontab(_SCHEDULE_CRON, timezone=_TIMEZONE)
        self._job = self._scheduler.add_job(
            self._cycle_fn,
            trigger=trigger,
            id="ims_cycle",
            name="IMS Agent Status Cycle",
            replace_existing=True,
            # If the server was down when the cycle was supposed to fire,
            # still run it within 1 hour of the missed time.
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        next_run = self._job.next_run_time
        logger.info(
            "action=scheduler_start cron=%s tz=%s next_run=%s",
            _SCHEDULE_CRON, _TIMEZONE,
            next_run.isoformat() if next_run else "N/A",
        )

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("action=scheduler_stop")

    def trigger_now(self) -> None:
        """Admin override: fire the cycle immediately, outside the normal schedule."""
        logger.info("action=manual_trigger")
        self._scheduler.add_job(
            self._cycle_fn,
            id="ims_cycle_manual",
            name="IMS Agent Cycle (Manual)",
            replace_existing=True,
        )

    def pause(self) -> None:
        if self._job:
            self._job.pause()
            logger.info("action=scheduler_pause")

    def resume(self) -> None:
        if self._job:
            self._job.resume()
            logger.info("action=scheduler_resume")

    @property
    def next_run_time(self) -> datetime | None:
        return self._job.next_run_time if self._job else None

    @property
    def is_running(self) -> bool:
        return self._scheduler.running
