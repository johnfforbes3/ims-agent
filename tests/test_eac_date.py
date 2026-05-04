"""
Tests for EAC (Estimate at Completion) date feature — Phase 7.3.

Covers:
- InterviewState.AWAITING_EAC_DATE is inserted for 1-99% tasks
- 0% and 100% tasks skip the EAC date question
- EAC date and eac_uncertain fields populate TaskResult correctly
- SRARunner.eac_dates parameter overrides remaining-duration estimate
- ReportGenerator shows CAM Forecast and Δ Days columns
- _classify_eac_date LLM fallback returns (None, True) gracefully
"""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from agent.voice.interview_agent import (
    InterviewAgent,
    InterviewState,
    TaskResult,
    _classify_eac_date,
)
from agent.sra_runner import SRARunner
from agent.report_generator import ReportGenerator

BASE = datetime(2026, 1, 5, 8, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(uid: str, name: str, pct: int = 50, duration: int = 20,
               start_offset: int = 0) -> dict:
    start = BASE + timedelta(days=start_offset)
    finish = start + timedelta(days=duration)
    return {
        "task_id": uid,
        "name": name,
        "start": start,
        "finish": finish,
        "percent_complete": pct,
        "predecessors": [],
        "cam": "Test CAM",
        "is_milestone": False,
        "duration_days": duration,
        "baseline_start": start,
        "baseline_finish": finish,
        "notes": "",
    }


def _make_milestone(uid: str, name: str, days_from_now: int = 60) -> dict:
    finish = datetime.now() + timedelta(days=days_from_now)
    return {
        "task_id": uid,
        "name": name,
        "start": finish - timedelta(days=1),
        "finish": finish,
        "percent_complete": 0,
        "predecessors": [],
        "cam": "",
        "is_milestone": True,
        "duration_days": 0,
        "baseline_finish": finish,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# State machine — EAC date insertion
# ---------------------------------------------------------------------------

class TestEACDateStateMachine:
    """Verify the AWAITING_EAC_DATE state is inserted correctly."""

    def test_1_to_99_pct_enters_eac_date_state(self):
        """Tasks at 1-99% should trigger AWAITING_EAC_DATE after PCT."""
        for pct in (1, 25, 50, 75, 99):
            task = _make_task("T1", f"Task {pct}pct", pct=pct)
            agent = InterviewAgent("Bob", [task], expected_pcts={"T1": pct})
            agent.start()
            agent.process("yes")   # greeting
            agent.process(str(pct))  # pct response
            assert agent.state == InterviewState.AWAITING_EAC_DATE, (
                f"Expected AWAITING_EAC_DATE after pct={pct}, got {agent.state}"
            )

    def test_0_pct_skips_eac_date_state(self):
        """0% tasks (not started) should NOT ask for an EAC date."""
        task = _make_task("T1", "Not Started", pct=0)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 0})
        agent.start()
        agent.process("yes")
        agent.process("0")
        assert agent.state != InterviewState.AWAITING_EAC_DATE

    def test_100_pct_skips_eac_date_state(self):
        """100% tasks (complete) should NOT ask for an EAC date."""
        task = _make_task("T1", "Done Task", pct=100)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 100})
        agent.start()
        agent.process("yes")
        agent.process("100")
        assert agent.state != InterviewState.AWAITING_EAC_DATE

    def test_eac_date_advances_to_blocker_when_behind(self):
        """After EAC date answer on a behind task, agent asks for blocker."""
        task = _make_task("T1", "Behind", pct=30)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 80})
        agent.start()
        agent.process("yes")
        agent.process("30")               # pct → AWAITING_EAC_DATE
        assert agent.state == InterviewState.AWAITING_EAC_DATE
        agent.process("end of next month")  # EAC date → AWAITING_BLOCKER
        assert agent.state == InterviewState.AWAITING_BLOCKER

    def test_eac_date_advances_to_confirm_when_on_track_no_blocker(self):
        """On-track task with no blocker → CONFIRM after EAC date."""
        task = _make_task("T1", "On Track", pct=50)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        agent.process("50")               # pct → AWAITING_EAC_DATE
        agent.process("still on track")   # EAC date → CONFIRM
        assert agent.state == InterviewState.CONFIRM

    def test_eac_date_question_mentions_planned_finish(self):
        """The EAC date question should mention the planned finish for on-track tasks."""
        task = _make_task("T1", "On Track Task", pct=50)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 50})
        agent.start()
        agent.process("yes")
        turn = agent.process("50")        # pct → AWAITING_EAC_DATE
        # The question should mention the planned date (Jan 25 for BASE + 20 days)
        assert agent.state == InterviewState.AWAITING_EAC_DATE
        # Question text should contain a date reference (month or day number)
        assert any(c.isdigit() for c in turn.text), (
            f"EAC date question should contain date digits: {turn.text!r}"
        )


# ---------------------------------------------------------------------------
# TaskResult — EAC date fields
# ---------------------------------------------------------------------------

class TestTaskResultEACFields:
    """TaskResult dataclass and to_cam_input_dict include EAC fields."""

    def test_task_result_defaults_eac_fields(self):
        """TaskResult default eac_date=None and eac_uncertain=False."""
        r = TaskResult(
            task_id="T1", cam_name="Alice", percent_complete=50,
            blocker="", risk_flag=False, risk_description="", status="captured",
        )
        assert r.eac_date is None
        assert r.eac_uncertain is False

    def test_task_result_stores_eac_date(self):
        r = TaskResult(
            task_id="T1", cam_name="Alice", percent_complete=50,
            blocker="", risk_flag=False, risk_description="", status="captured",
            eac_date="2026-06-30",
        )
        assert r.eac_date == "2026-06-30"
        assert r.eac_uncertain is False

    def test_task_result_stores_eac_uncertain(self):
        r = TaskResult(
            task_id="T1", cam_name="Alice", percent_complete=50,
            blocker="", risk_flag=False, risk_description="", status="captured",
            eac_uncertain=True,
        )
        assert r.eac_date is None
        assert r.eac_uncertain is True

    def test_to_cam_input_dict_includes_eac_date(self):
        r = TaskResult(
            task_id="T1", cam_name="Alice", percent_complete=50,
            blocker="", risk_flag=False, risk_description="", status="captured",
            eac_date="2026-07-15",
            eac_uncertain=False,
        )
        d = r.to_cam_input_dict()
        assert d["eac_date"] == "2026-07-15"
        assert d["eac_uncertain"] is False

    def test_to_cam_input_dict_includes_eac_uncertain(self):
        r = TaskResult(
            task_id="T1", cam_name="Alice", percent_complete=30,
            blocker="", risk_flag=False, risk_description="", status="captured",
            eac_uncertain=True,
        )
        d = r.to_cam_input_dict()
        assert d["eac_date"] is None
        assert d["eac_uncertain"] is True


# ---------------------------------------------------------------------------
# EAC date captured in interview results
# ---------------------------------------------------------------------------

class TestEACDateCapturedInResults:
    """Verify EAC date propagates from interview through to captured TaskResult."""

    def test_eac_date_captured_in_result_on_track(self):
        """When LLM returns a date, it is stored on the TaskResult."""
        task = _make_task("T1", "On Track Task", pct=60)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 60})

        # Mock _classify_eac_date to return a known date
        with patch("agent.voice.interview_agent._classify_eac_date",
                   return_value=("2026-06-30", False)):
            agent.start()
            agent.process("yes")
            agent.process("60")               # pct → AWAITING_EAC_DATE
            agent.process("end of june")      # EAC date response
            # on track, no blocker → CONFIRM
            if agent.state == InterviewState.CONFIRM:
                agent.process("yes")

        results = agent.results
        assert len(results) == 1
        assert results[0].eac_date == "2026-06-30"
        assert results[0].eac_uncertain is False

    def test_eac_uncertain_captured_when_llm_returns_uncertain(self):
        """When LLM returns uncertain, eac_uncertain=True on the TaskResult."""
        task = _make_task("T1", "Uncertain Task", pct=40)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 40})

        with patch("agent.voice.interview_agent._classify_eac_date",
                   return_value=(None, True)):
            agent.start()
            agent.process("yes")
            agent.process("40")               # pct → AWAITING_EAC_DATE
            agent.process("I'm not sure")     # EAC date response → uncertain
            if agent.state == InterviewState.CONFIRM:
                agent.process("yes")

        results = agent.results
        assert len(results) == 1
        assert results[0].eac_date is None
        assert results[0].eac_uncertain is True

    def test_eac_date_absent_for_zero_pct_task(self):
        """0% task has no EAC date asked — result should have eac_date=None."""
        task = _make_task("T1", "Not Started", pct=0)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 0})
        agent.start()
        agent.process("yes")
        agent.process("0")
        # On-track 0% → finalise directly
        if agent.state == InterviewState.CONFIRM:
            agent.process("yes")
        elif agent.state == InterviewState.AWAITING_BLOCKER:
            agent.process("no blocker")
            if agent.state == InterviewState.CONFIRM:
                agent.process("yes")

        results = agent.results
        if results:
            assert results[0].eac_date is None

    def test_eac_date_absent_for_100_pct_task(self):
        """100% task has no EAC date — result should have eac_date=None."""
        task = _make_task("T1", "Done Task", pct=100)
        agent = InterviewAgent("Bob", [task], expected_pcts={"T1": 100})
        agent.start()
        agent.process("yes")
        agent.process("100")
        if agent.state == InterviewState.CONFIRM:
            agent.process("yes")

        results = agent.results
        if results:
            assert results[0].eac_date is None


# ---------------------------------------------------------------------------
# _classify_eac_date — LLM fallback
# ---------------------------------------------------------------------------

class TestClassifyEACDate:
    """_classify_eac_date graceful fallback when LLM is unavailable."""

    def test_classify_eac_date_fallback_returns_uncertain(self):
        """Without an LLM, _classify_eac_date should return (None, True)."""
        eac_date, uncertain = _classify_eac_date(
            response="I'm not sure when we'll finish",
            planned_finish_iso="2026-06-30",
        )
        # LLM will fail in test env → fallback returns (None, True)
        assert eac_date is None
        assert uncertain is True

    def test_classify_eac_date_with_mocked_llm_absolute_date(self):
        """When LLM returns a JSON with a date, it is parsed correctly."""
        mock_llm = MagicMock()
        mock_llm.ask.return_value = '{"eac_date": "2026-07-15", "eac_uncertain": false}'

        # _classify_eac_date does a local `from agent.llm_interface import LLMInterface`
        # so we patch at the source module, not the caller module.
        with patch("agent.llm_interface.LLMInterface", return_value=mock_llm):
            eac_date, uncertain = _classify_eac_date(
                response="We'll be done by July 15th",
                planned_finish_iso="2026-06-30",
            )

        assert eac_date == "2026-07-15"
        assert uncertain is False

    def test_classify_eac_date_with_mocked_llm_on_track(self):
        """When CAM says on track, LLM should return the planned finish."""
        mock_llm = MagicMock()
        mock_llm.ask.return_value = '{"eac_date": "2026-06-30", "eac_uncertain": false}'

        with patch("agent.llm_interface.LLMInterface", return_value=mock_llm):
            eac_date, uncertain = _classify_eac_date(
                response="Still on track for the planned date",
                planned_finish_iso="2026-06-30",
            )

        assert eac_date == "2026-06-30"
        assert uncertain is False

    def test_classify_eac_date_with_mocked_llm_uncertain(self):
        """When CAM doesn't know, LLM should return uncertain."""
        mock_llm = MagicMock()
        mock_llm.ask.return_value = '{"eac_date": null, "eac_uncertain": true}'

        with patch("agent.llm_interface.LLMInterface", return_value=mock_llm):
            eac_date, uncertain = _classify_eac_date(
                response="I really have no idea",
                planned_finish_iso="2026-06-30",
            )

        assert eac_date is None
        assert uncertain is True

    def test_classify_eac_date_rejects_invalid_iso_format(self):
        """If LLM returns a malformed date, fallback to (None, True)."""
        mock_llm = MagicMock()
        mock_llm.ask.return_value = '{"eac_date": "not-a-date", "eac_uncertain": false}'

        with patch("agent.llm_interface.LLMInterface", return_value=mock_llm):
            eac_date, uncertain = _classify_eac_date(
                response="Maybe around the 15th?",
                planned_finish_iso="2026-06-30",
            )

        # Invalid date → fallback to uncertain
        assert eac_date is None
        assert uncertain is True


# ---------------------------------------------------------------------------
# SRARunner — eac_dates parameter
# ---------------------------------------------------------------------------

class TestSRARunnerEACDates:
    """SRARunner uses EAC dates to override remaining-duration estimates."""

    def _make_sra_task(self, uid: str, pct: int, days_until_finish: int,
                       is_milestone: bool = False) -> dict:
        now = datetime.now()
        start = now - timedelta(days=30)
        finish = now + timedelta(days=days_until_finish)
        return {
            "task_id": uid,
            "name": f"Task {uid}",
            "start": start,
            "finish": finish,
            "percent_complete": pct,
            "predecessors": [],
            "cam": "Bob",
            "is_milestone": is_milestone,
            "duration_days": 30 + days_until_finish,
            "baseline_finish": finish,
            "notes": "",
        }

    def test_sra_runner_accepts_eac_dates_parameter(self):
        """SRARunner.__init__ accepts eac_dates without raising."""
        task = self._make_sra_task("T1", 50, 30)
        milestone = self._make_sra_task("M1", 0, 60, is_milestone=True)
        milestone["name"] = "Test Milestone"
        eac_dates = {"T1": "2026-07-01"}
        runner = SRARunner([task, milestone], seed=42, eac_dates=eac_dates)
        results = runner.run()
        assert len(results) == 1
        assert results[0]["milestone_name"] == "Test Milestone"

    def test_eac_date_shortens_remaining_duration(self):
        """When EAC is sooner than linear estimate, P50 should be earlier."""
        task = self._make_sra_task("T1", 10, 90)  # 10% done, 90 days left by linear
        milestone = self._make_sra_task("M1", 0, 100, is_milestone=True)
        milestone["name"] = "Delivery"

        # No EAC override — uses linear estimate (90 days remaining)
        runner_base = SRARunner([task, milestone], seed=42)
        result_base = runner_base.run()[0]

        # EAC date = 20 days from now (much sooner than 90-day linear estimate)
        eac_date = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
        runner_eac = SRARunner([task, milestone], seed=42, eac_dates={"T1": eac_date})
        result_eac = runner_eac.run()[0]

        # P50 with EAC should be the same or earlier than without EAC
        p50_base = datetime.strptime(result_base["p50_date"], "%Y-%m-%d")
        p50_eac = datetime.strptime(result_eac["p50_date"], "%Y-%m-%d")
        assert p50_eac <= p50_base, (
            f"EAC-anchored P50 ({p50_eac.date()}) should be ≤ linear P50 ({p50_base.date()})"
        )

    def test_eac_date_in_past_clamps_remaining_to_zero(self):
        """Past EAC dates clamp remaining to 0 (task should already be done)."""
        task = self._make_sra_task("T1", 80, 30)
        milestone = self._make_sra_task("M1", 0, 60, is_milestone=True)
        milestone["name"] = "Milestone"

        # EAC date was yesterday — task overdue
        past_eac = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        runner = SRARunner([task, milestone], seed=42, eac_dates={"T1": past_eac})
        results = runner.run()
        assert len(results) == 1
        # Should not crash — remaining clamped to 0

    def test_no_eac_dates_behaves_identically_to_baseline(self):
        """SRARunner with no eac_dates produces same results as seed-identical run."""
        task = self._make_sra_task("T1", 50, 30)
        milestone = self._make_sra_task("M1", 0, 60, is_milestone=True)
        milestone["name"] = "Milestone"

        r1 = SRARunner([task, milestone], seed=99).run()
        r2 = SRARunner([task, milestone], seed=99, eac_dates={}).run()
        assert r1[0]["p50_date"] == r2[0]["p50_date"]
        assert r1[0]["risk_level"] == r2[0]["risk_level"]


# ---------------------------------------------------------------------------
# ReportGenerator — CAM Forecast and Δ Days columns
# ---------------------------------------------------------------------------

class TestReportGeneratorEACColumns:
    """ReportGenerator shows EAC forecast and slippage in the behind-schedule table."""

    def _make_synthesis(self) -> dict:
        return {
            "schedule_health": "YELLOW",
            "narrative": "Test narrative.",
            "top_risks": "1. Risk one.",
            "recommended_actions": "1. Action one.",
        }

    def _make_rg_task(self, uid: str, pct: int, exp_pct_offset: int = -30) -> dict:
        """Make a task that is behind schedule."""
        now = datetime.now()
        start = now - timedelta(days=60)
        finish = now + timedelta(days=5)   # nearly done → expected near 100%
        return {
            "task_id": uid,
            "name": f"Task {uid}",
            "start": start,
            "finish": finish,
            "percent_complete": pct,
            "predecessors": [],
            "cam": "Alice Smith",
            "is_milestone": False,
            "duration_days": 65,
            "baseline_finish": finish,
            "notes": "",
        }

    def test_report_includes_cam_forecast_column(self):
        """Report table header should include 'CAM Forecast'."""
        task = self._make_rg_task("T1", pct=30)
        cam_input = {
            "task_id": "T1",
            "cam_name": "Alice Smith",
            "percent_complete": 30,
            "blocker": "vendor delay",
            "risk_flag": False,
            "risk_description": "",
            "timestamp": datetime.now().isoformat(),
            "eac_date": "2026-07-15",
            "eac_uncertain": False,
        }
        rg = ReportGenerator()
        content = rg._build_report(
            tasks=[task],
            cp_result={"critical_path": [], "total_float": {}},
            sra_result=[],
            cam_inputs=[cam_input],
            synthesis=self._make_synthesis(),
            report_date=datetime.now(),
        )
        assert "CAM Forecast" in content, "Report should include 'CAM Forecast' column"
        assert "Δ Days" in content, "Report should include 'Δ Days' column"

    def test_report_shows_eac_date_in_forecast_cell(self):
        """When eac_date is set, it appears in the forecast column."""
        task = self._make_rg_task("T1", pct=25)
        cam_input = {
            "task_id": "T1",
            "cam_name": "Alice Smith",
            "percent_complete": 25,
            "blocker": "needs approval",
            "risk_flag": False,
            "risk_description": "",
            "timestamp": datetime.now().isoformat(),
            "eac_date": "2026-08-31",
            "eac_uncertain": False,
        }
        rg = ReportGenerator()
        content = rg._build_report(
            tasks=[task],
            cp_result={"critical_path": [], "total_float": {}},
            sra_result=[],
            cam_inputs=[cam_input],
            synthesis=self._make_synthesis(),
            report_date=datetime.now(),
        )
        assert "2026-08-31" in content

    def test_report_shows_uncertain_when_eac_uncertain(self):
        """When eac_uncertain, forecast column shows 'uncertain'."""
        task = self._make_rg_task("T1", pct=20)
        cam_input = {
            "task_id": "T1",
            "cam_name": "Alice Smith",
            "percent_complete": 20,
            "blocker": "scope unclear",
            "risk_flag": False,
            "risk_description": "",
            "timestamp": datetime.now().isoformat(),
            "eac_date": None,
            "eac_uncertain": True,
        }
        rg = ReportGenerator()
        content = rg._build_report(
            tasks=[task],
            cp_result={"critical_path": [], "total_float": {}},
            sra_result=[],
            cam_inputs=[cam_input],
            synthesis=self._make_synthesis(),
            report_date=datetime.now(),
        )
        assert "uncertain" in content.lower()

    def test_report_shows_dash_when_no_eac_date(self):
        """When no eac_date and not uncertain, forecast column shows '—'."""
        task = self._make_rg_task("T1", pct=15)
        cam_input = {
            "task_id": "T1",
            "cam_name": "Alice Smith",
            "percent_complete": 15,
            "blocker": "waiting on parts",
            "risk_flag": False,
            "risk_description": "",
            "timestamp": datetime.now().isoformat(),
            # No eac fields
        }
        rg = ReportGenerator()
        content = rg._build_report(
            tasks=[task],
            cp_result={"critical_path": [], "total_float": {}},
            sra_result=[],
            cam_inputs=[cam_input],
            synthesis=self._make_synthesis(),
            report_date=datetime.now(),
        )
        assert "—" in content

    def test_report_positive_delta_when_eac_after_baseline(self):
        """Δ Days should be positive when EAC is after the planned finish."""
        now = datetime.now()
        task = self._make_rg_task("T1", pct=20)

        # Use midnight dates to avoid time-component arithmetic discrepancies.
        # baseline_finish in the task has a time component, so we override it.
        baseline_date = datetime(2026, 7, 1, 0, 0, 0)
        task["finish"] = baseline_date
        task["baseline_finish"] = baseline_date
        eac_date_str = "2026-07-31"  # exactly 30 days later (July has 31 days → 30 day gap)

        cam_input = {
            "task_id": "T1",
            "cam_name": "Alice Smith",
            "percent_complete": 20,
            "blocker": "vendor",
            "risk_flag": False,
            "risk_description": "",
            "timestamp": now.isoformat(),
            "eac_date": eac_date_str,
            "eac_uncertain": False,
        }
        rg = ReportGenerator()
        content = rg._build_report(
            tasks=[task],
            cp_result={"critical_path": [], "total_float": {}},
            sra_result=[],
            cam_inputs=[cam_input],
            synthesis=self._make_synthesis(),
            report_date=now,
        )
        # Should show a positive delta (slip): 2026-07-31 - 2026-07-01 = 30 days
        assert "+30d" in content, f"Expected '+30d' in report, got:\n{content}"
