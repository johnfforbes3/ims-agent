"""
Schedule Risk Assessment (SRA) runner — Monte Carlo simulation engine.

Implements a pure-Python Monte Carlo simulation to estimate P50/P80/P95
completion dates for each milestone task.

Duration sampling:
  - Default: triangular distribution ±SRA_DURATION_UNCERTAINTY around remaining.
  - Beta-PERT (Phase 8.3): when a task dict contains ``duration_opt`` and
    ``duration_pess`` (optimistic and pessimistic full-duration estimates in
    days), the simulation uses the beta-PERT distribution (λ=4) instead of the
    triangular fallback.  The three-point estimates are scaled by the remaining
    completion fraction to produce per-task remaining-duration samples.
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


def _pert_variate(
    rng: random.Random,
    optimistic: float,
    most_likely: float,
    pessimistic: float,
) -> float:
    """Sample from the beta-PERT distribution (λ=4).

    Maps the three-point estimate onto a scaled Beta(α₁, α₂) distribution:
      α₁ = 1 + 4 * (m - a) / (b - a)
      α₂ = 1 + 4 * (b - m) / (b - a)
      sample = a + (b - a) * Beta(α₁, α₂)

    Args:
        optimistic:  Best-case value (lower bound).
        most_likely: Modal value (the peak of the distribution).
        pessimistic: Worst-case value (upper bound).

    Returns:
        A single float sample in [optimistic, pessimistic].
    """
    a, m, b = optimistic, most_likely, pessimistic
    if b <= a:
        # Degenerate: no spread — return most_likely
        return m
    alpha1 = 1.0 + 4.0 * (m - a) / (b - a)
    alpha2 = 1.0 + 4.0 * (b - m) / (b - a)
    return a + (b - a) * rng.betavariate(alpha1, alpha2)


class SRARunner:
    """Runs Monte Carlo SRA on a parsed task list."""

    def __init__(
        self,
        tasks: list[dict[str, Any]],
        seed: int | None = None,
        eac_dates: dict[str, str] | None = None,
    ) -> None:
        """
        Args:
            tasks: Parsed task list from IMSFileHandler.parse().
            seed: Optional random seed for reproducible results.
            eac_dates: Optional mapping of task_id → ISO date string "YYYY-MM-DD".
                       When present for a task, the EAC date overrides the linear
                       remaining-duration estimate and becomes the centre (P50) of
                       the triangular distribution for that task's slip.
        """
        self._tasks = tasks
        self._task_map = {t["task_id"]: t for t in tasks}
        self._seed = seed
        self._eac_dates: dict[str, str] = eac_dates or {}

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

        # Determine remaining duration.
        # If a CAM-provided EAC date exists, use (eac_date - today) as the P50
        # centre of the distribution instead of the linear (1-pct) * duration estimate.
        eac_date_str = self._eac_dates.get(task_id)
        if eac_date_str:
            try:
                eac_dt = datetime.strptime(eac_date_str, "%Y-%m-%d")
                remaining = max(0.0, (eac_dt - datetime.now()).days)
                logger.debug("action=sra_eac_override task=%s eac=%s remaining_days=%.1f",
                             task_id, eac_date_str, remaining)
            except ValueError:
                remaining = task["duration_days"] * (1 - task["percent_complete"] / 100.0)
        else:
            remaining = task["duration_days"] * (1 - task["percent_complete"] / 100.0)

        if remaining <= 0:
            slip = 0.0
        else:
            duration_opt = task.get("duration_opt")
            duration_pess = task.get("duration_pess")

            if duration_opt is not None and duration_pess is not None:
                # Beta-PERT (Phase 8.3): scale three-point duration estimates by
                # the remaining completion fraction to get remaining-duration bounds.
                frac = 1.0 - task["percent_complete"] / 100.0
                opt_rem = max(0.0, duration_opt * frac)
                pess_rem = max(0.0, duration_pess * frac)
                # Enforce opt ≤ mode ≤ pess (clamp if estimates are mis-ordered)
                opt_rem = min(opt_rem, remaining)
                pess_rem = max(pess_rem, remaining)
                sampled = _pert_variate(rng, opt_rem, remaining, pess_rem)
                slip = sampled - remaining
                logger.debug(
                    "action=sra_pert task=%s opt=%.1f ml=%.1f pess=%.1f "
                    "sampled=%.1f slip=%.1f",
                    task_id, opt_rem, remaining, pess_rem, sampled, slip,
                )
            else:
                # Triangular fallback: ±uncertainty around the expected remaining
                low = -_UNCERTAINTY * remaining
                high = _UNCERTAINTY * remaining
                slip = rng.triangular(low, high, 0.0)

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
