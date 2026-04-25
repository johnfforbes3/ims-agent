"""
Tests for agent.sra_runner — Monte Carlo SRA engine.

Covers 1.6 checklist items:
- Simulation output is reproducible within expected variance (seeded RNG)
- HIGH/MEDIUM/LOW risk classification is correct
- P50 <= P80 <= P95 ordering
- No milestones in task list returns empty list
"""

from datetime import datetime, timedelta
import pytest


BASE = datetime(2026, 1, 5, 8, 0, 0)


def _make_milestone(uid: str, name: str, finish: datetime, predecessors: list[str] | None = None) -> dict:
    return {
        "task_id": uid,
        "name": name,
        "start": finish,
        "finish": finish,
        "baseline_start": finish,
        "baseline_finish": finish,
        "duration_days": 0,
        "percent_complete": 0,
        "predecessors": predecessors or [],
        "is_milestone": True,
        "cam": "Eva Johnson",
        "notes": "",
    }


def _make_work_task(uid: str, name: str, start: datetime, duration_days: float,
                    predecessors: list[str] | None = None, pct: int = 0) -> dict:
    finish = start + timedelta(days=duration_days)
    return {
        "task_id": uid,
        "name": name,
        "start": start,
        "finish": finish,
        "baseline_start": start,
        "baseline_finish": finish,
        "duration_days": duration_days,
        "percent_complete": pct,
        "predecessors": predecessors or [],
        "is_milestone": False,
        "cam": "Test CAM",
        "notes": "",
    }


class TestSRARunner:
    def test_reproducible_with_seed(self):
        """Two runs with the same seed produce identical results."""
        from agent.sra_runner import SRARunner
        task = _make_work_task("W1", "Work Task", BASE, 20)
        ms = _make_milestone("M1", "Milestone 1", BASE + timedelta(days=20), ["W1"])
        tasks = [task, ms]

        result1 = SRARunner(tasks, seed=42).run()
        result2 = SRARunner(tasks, seed=42).run()

        assert result1[0]["p50_date"] == result2[0]["p50_date"]
        assert result1[0]["p80_date"] == result2[0]["p80_date"]
        assert result1[0]["p95_date"] == result2[0]["p95_date"]

    def test_p50_le_p80_le_p95(self):
        """P50 <= P80 <= P95 for all milestones."""
        from agent.sra_runner import SRARunner
        from datetime import date
        task = _make_work_task("W1", "Work Task", BASE, 30)
        ms = _make_milestone("M1", "Milestone", BASE + timedelta(days=30), ["W1"])
        results = SRARunner([task, ms], seed=7).run()
        r = results[0]
        p50 = datetime.strptime(r["p50_date"], "%Y-%m-%d")
        p80 = datetime.strptime(r["p80_date"], "%Y-%m-%d")
        p95 = datetime.strptime(r["p95_date"], "%Y-%m-%d")
        assert p50 <= p80, f"P50 {p50} > P80 {p80}"
        assert p80 <= p95, f"P80 {p80} > P95 {p95}"

    def test_no_milestones_returns_empty(self):
        """Empty result when no milestones in task list."""
        from agent.sra_runner import SRARunner
        task = _make_work_task("W1", "Work Task", BASE, 10)
        results = SRARunner([task], seed=1).run()
        assert results == []

    def test_risk_level_high_for_impossible_baseline(self):
        """Milestone with baseline in the past (already late) is HIGH risk."""
        from agent.sra_runner import SRARunner
        # Baseline finish is well in the past
        past = datetime(2025, 1, 1)
        task = _make_work_task("W1", "Overdue Task", BASE, 30)
        ms = _make_milestone("M1", "Overdue Milestone", BASE + timedelta(days=30), ["W1"])
        ms["baseline_finish"] = past  # baseline was 1 year ago

        results = SRARunner([task, ms], seed=99).run()
        assert results[0]["risk_level"] == "HIGH"

    def test_risk_level_low_for_future_baseline(self):
        """Milestone with generous baseline in the future is LOW risk for a short task."""
        from agent.sra_runner import SRARunner
        future = BASE + timedelta(days=365)
        task = _make_work_task("W1", "Easy Task", BASE, 1)  # 1 day task
        ms = _make_milestone("M1", "Easy Milestone", BASE + timedelta(days=1), ["W1"])
        ms["baseline_finish"] = future

        results = SRARunner([task, ms], seed=5).run()
        assert results[0]["risk_level"] == "LOW"

    def test_prob_on_baseline_in_range(self):
        """prob_on_baseline is between 0.0 and 1.0."""
        from agent.sra_runner import SRARunner
        task = _make_work_task("W1", "Task", BASE, 15)
        ms = _make_milestone("M1", "MS", BASE + timedelta(days=15), ["W1"])
        results = SRARunner([task, ms], seed=3).run()
        prob = results[0]["prob_on_baseline"]
        assert 0.0 <= prob <= 1.0, f"prob_on_baseline={prob} out of range"

    def test_sample_file_milestones(self):
        """SRA runs on full sample file and returns one result per milestone."""
        from pathlib import Path
        from agent.file_handler import IMSFileHandler
        from agent.sra_runner import SRARunner

        sample = Path(__file__).parent.parent / "data" / "sample_ims.xml"
        handler = IMSFileHandler(str(sample))
        tasks = handler.parse()
        milestones = [t for t in tasks if t.get("is_milestone")]

        results = SRARunner(tasks, seed=42).run()
        assert len(results) == len(milestones)
