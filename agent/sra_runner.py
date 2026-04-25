"""
Schedule Risk Assessment (SRA) runner — Monte Carlo simulation engine.

Implements a pure-Python Monte Carlo simulation to estimate P50/P80/P95
completion dates for each milestone task.
"""

import logging
import os
import random
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_ITERATIONS = int(os.getenv("SRA_ITERATIONS", "1000"))
_UNCERTAINTY = float(os.getenv("SRA_DURATION_UNCERTAINTY", "0.10"))
_HIGH_RISK_THRESHOLD = float(os.getenv("SRA_HIGH_RISK_THRESHOLD", "0.50"))
_MEDIUM_RISK_THRESHOLD = float(os.getenv("SRA_MEDIUM_RISK_THRESHOLD", "0.75"))


class SRARunner:
    """Runs Monte Carlo SRA on a parsed task list."""

    def __init__(self, tasks: list[dict[str, Any]], seed: int | None = None) -> None:
        """
        Args:
            tasks: Parsed task list from IMSFileHandler.parse().
            seed: Optional random seed for reproducible results.
        """
        self._tasks = tasks
        self._task_map = {t["task_id"]: t for t in tasks}
        self._seed = seed

    def run(self) -> list[dict[str, Any]]:
        """
        Run N Monte Carlo iterations and return SRA results for all milestones.

        Returns:
            List of dicts, one per milestone task, containing:
            milestone_name, baseline_date, p50_date, p80_date, p95_date,
            prob_on_baseline, risk_level.
        """
        rng = random.Random(self._seed)
        milestones = [t for t in self._tasks if t.get("is_milestone")]

        if not milestones:
            logger.warning("action=sra_warning msg=no_milestones_found")
            return []

        results: list[dict[str, Any]] = []
        for milestone in milestones:
            sim_dates = self._simulate_milestone(milestone, rng)
            result = self._summarize(milestone, sim_dates)
            results.append(result)
            logger.info(
                "action=sra_milestone milestone=%s risk=%s p50=%s prob=%.2f",
                milestone["name"],
                result["risk_level"],
                result.get("p50_date", "N/A"),
                result.get("prob_on_baseline", 0),
            )

        logger.info("action=sra_complete iterations=%d milestones=%d", _ITERATIONS, len(results))
        return results

    def _simulate_milestone(
        self, milestone: dict[str, Any], rng: random.Random
    ) -> list[datetime]:
        """
        Run Monte Carlo iterations for a single milestone.

        Returns:
            List of simulated finish dates (length = _ITERATIONS).
        """
        sim_dates: list[datetime] = []

        for _ in range(_ITERATIONS):
            # Walk the predecessor chain, accumulating duration variance
            total_slip_days = self._simulate_chain_slip(milestone, rng, visited=set())
            base_finish = milestone.get("finish") or datetime.now()
            sim_dates.append(base_finish + timedelta(days=total_slip_days))

        return sim_dates

    def _simulate_chain_slip(
        self,
        task: dict[str, Any],
        rng: random.Random,
        visited: set[str],
    ) -> float:
        """
        Recursively compute total slip for a task's predecessor chain.

        Uses triangular distribution: min = -uncertainty, mode = 0,
        max = +uncertainty * remaining_duration.
        """
        task_id = task["task_id"]
        if task_id in visited:
            return 0.0
        visited.add(task_id)

        remaining = task["duration_days"] * (1 - task["percent_complete"] / 100.0)
        if remaining <= 0:
            slip = 0.0
        else:
            # Triangular distribution: optimistic, likely, pessimistic
            low = -_UNCERTAINTY * remaining
            mode = 0.0
            high = _UNCERTAINTY * remaining
            slip = rng.triangular(low, high, mode)

        # Add worst-case slip from predecessors
        predecessor_slip = 0.0
        for pred_id in task.get("predecessors", []):
            pred = self._task_map.get(pred_id)
            if pred:
                predecessor_slip = max(
                    predecessor_slip,
                    self._simulate_chain_slip(pred, rng, visited),
                )

        return slip + predecessor_slip

    def _summarize(
        self, milestone: dict[str, Any], sim_dates: list[datetime]
    ) -> dict[str, Any]:
        """Compute P50/P80/P95 and risk level from simulation results."""
        sorted_dates = sorted(sim_dates)
        n = len(sorted_dates)
        p50 = sorted_dates[int(n * 0.50)]
        p80 = sorted_dates[int(n * 0.80)]
        p95 = sorted_dates[int(n * 0.95)]

        baseline = milestone.get("baseline_finish") or milestone.get("finish")
        if baseline:
            on_time_count = sum(1 for d in sorted_dates if d <= baseline)
            prob_on_baseline = on_time_count / n
        else:
            prob_on_baseline = 1.0

        if prob_on_baseline < _HIGH_RISK_THRESHOLD:
            risk_level = "HIGH"
        elif prob_on_baseline < _MEDIUM_RISK_THRESHOLD:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return {
            "task_id": milestone["task_id"],
            "milestone_name": milestone["name"],
            "baseline_date": _fmt(baseline),
            "p50_date": _fmt(p50),
            "p80_date": _fmt(p80),
            "p95_date": _fmt(p95),
            "prob_on_baseline": prob_on_baseline,
            "risk_level": risk_level,
        }


def _fmt(dt: datetime | None) -> str:
    """Format a datetime as YYYY-MM-DD, or 'N/A' if None."""
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d")
