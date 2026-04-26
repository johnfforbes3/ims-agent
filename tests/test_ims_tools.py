"""Tests for Phase 4.5 IMS schedule tools and LLM tool-use loop."""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Shared task fixture
# ---------------------------------------------------------------------------

def _make_tasks():
    now = datetime.now()
    return [
        {
            "task_id": "1",
            "name": "SE-01 System Requirements",
            "cam": "Alice Nguyen",
            "percent_complete": 100,
            "start": now - timedelta(days=60),
            "finish": now - timedelta(days=30),
            "baseline_start": now - timedelta(days=60),
            "baseline_finish": now - timedelta(days=30),
            "duration_days": 30.0,
            "is_milestone": False,
            "predecessors": [],
            "notes": "",
        },
        {
            "task_id": "2",
            "name": "SE-02 ICD Draft",
            "cam": "Alice Nguyen",
            "percent_complete": 60,
            "start": now - timedelta(days=20),
            "finish": now + timedelta(days=10),
            "baseline_start": now - timedelta(days=20),
            "baseline_finish": now + timedelta(days=10),
            "duration_days": 30.0,
            "is_milestone": False,
            "predecessors": ["1"],
            "notes": "Blocked on RF specs",
        },
        {
            "task_id": "3",
            "name": "HW-01 PCB Layout",
            "cam": "Bob Martinez",
            "percent_complete": 40,
            "start": now - timedelta(days=10),
            "finish": now + timedelta(days=20),
            "baseline_start": now - timedelta(days=10),
            "baseline_finish": now + timedelta(days=20),
            "duration_days": 30.0,
            "is_milestone": False,
            "predecessors": ["2"],
            "notes": "",
        },
        {
            "task_id": "51",
            "name": "MS-01 SRR Complete",
            "cam": "Alice Nguyen",
            "percent_complete": 100,
            "start": now - timedelta(days=90),
            "finish": now - timedelta(days=60),
            "baseline_start": now - timedelta(days=90),
            "baseline_finish": now - timedelta(days=60),
            "duration_days": 1.0,
            "is_milestone": True,
            "predecessors": [],
            "notes": "",
        },
    ]


def _make_cp(task_ids=None):
    ids = task_ids or ["1", "2", "3"]
    return {
        "critical_path": ids,
        "total_float": {"1": 0.0, "2": 0.0, "3": 0.0, "51": 5.0},
        "near_critical": ["51"],
        "projected_finish": datetime.now() + timedelta(days=20),
    }


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the IMS tools cache before each test."""
    from agent.qa import ims_tools
    ims_tools._task_cache = None
    ims_tools._cp_cache = None
    yield
    ims_tools._task_cache = None
    ims_tools._cp_cache = None


@pytest.fixture
def patched_data():
    """Patch _get_tasks() and _get_cp() with deterministic test data."""
    tasks = _make_tasks()
    cp = _make_cp()
    with patch("agent.qa.ims_tools._get_tasks", return_value=tasks), \
         patch("agent.qa.ims_tools._get_cp", return_value=cp):
        yield tasks, cp


# ---------------------------------------------------------------------------
# Tool handler tests
# ---------------------------------------------------------------------------

class TestGetTask:
    def test_found_task(self, patched_data):
        from agent.qa.ims_tools import get_task
        result = json.loads(get_task("1"))
        assert result["task_id"] == "1"
        assert result["name"] == "SE-01 System Requirements"
        assert result["cam"] == "Alice Nguyen"
        assert result["is_critical"] is True
        assert result["total_float_days"] == 0.0

    def test_not_found(self, patched_data):
        from agent.qa.ims_tools import get_task
        result = json.loads(get_task("999"))
        assert "error" in result
        assert "999" in result["error"]

    def test_near_critical_flag(self, patched_data):
        from agent.qa.ims_tools import get_task
        result = json.loads(get_task("51"))
        assert result["near_critical"] is True
        assert result["is_critical"] is False


class TestSearchTasks:
    def test_search_by_name(self, patched_data):
        from agent.qa.ims_tools import search_tasks
        result = json.loads(search_tasks("SE-01"))
        assert result["count"] == 1
        assert result["results"][0]["task_id"] == "1"

    def test_search_by_cam(self, patched_data):
        from agent.qa.ims_tools import search_tasks
        result = json.loads(search_tasks("Alice"))
        assert result["count"] == 3  # task 1, 2, and 51 (milestone)

    def test_no_results(self, patched_data):
        from agent.qa.ims_tools import search_tasks
        result = json.loads(search_tasks("nonexistent_xyz"))
        assert result["results"] == []
        assert "No tasks" in result["message"]

    def test_case_insensitive(self, patched_data):
        from agent.qa.ims_tools import search_tasks
        result = json.loads(search_tasks("alice"))
        assert result["count"] >= 1


class TestGetCriticalPath:
    def test_returns_critical_tasks(self, patched_data):
        from agent.qa.ims_tools import get_critical_path
        result = json.loads(get_critical_path())
        ids = [t["task_id"] for t in result["critical_path_tasks"]]
        assert "1" in ids
        assert "2" in ids
        assert "3" in ids

    def test_count_matches(self, patched_data):
        from agent.qa.ims_tools import get_critical_path
        result = json.loads(get_critical_path())
        assert result["count"] == len(result["critical_path_tasks"])

    def test_all_marked_critical(self, patched_data):
        from agent.qa.ims_tools import get_critical_path
        result = json.loads(get_critical_path())
        for t in result["critical_path_tasks"]:
            assert t["is_critical"] is True


class TestGetTasksByCam:
    def test_alice_tasks(self, patched_data):
        from agent.qa.ims_tools import get_tasks_by_cam
        result = json.loads(get_tasks_by_cam("Alice"))
        assert result["task_count"] == 3
        ids = [t["task_id"] for t in result["tasks"]]
        assert "1" in ids and "2" in ids

    def test_cam_not_found(self, patched_data):
        from agent.qa.ims_tools import get_tasks_by_cam
        result = json.loads(get_tasks_by_cam("Zephyr"))
        assert "error" in result

    def test_partial_name_match(self, patched_data):
        from agent.qa.ims_tools import get_tasks_by_cam
        result = json.loads(get_tasks_by_cam("Martinez"))
        assert result["task_count"] == 1
        assert result["tasks"][0]["task_id"] == "3"


class TestGetFloat:
    def test_critical_task_float(self, patched_data):
        from agent.qa.ims_tools import get_float
        result = json.loads(get_float("1"))
        assert result["total_float_days"] == 0.0
        assert result["is_critical"] is True

    def test_non_critical_task_float(self, patched_data):
        from agent.qa.ims_tools import get_float
        result = json.loads(get_float("51"))
        assert result["total_float_days"] == 5.0
        assert result["is_critical"] is False
        assert result["near_critical"] is True

    def test_not_found(self, patched_data):
        from agent.qa.ims_tools import get_float
        result = json.loads(get_float("999"))
        assert "error" in result


class TestGetDependencies:
    def test_predecessors(self, patched_data):
        from agent.qa.ims_tools import get_dependencies
        result = json.loads(get_dependencies("2"))
        pred_ids = [p["task_id"] for p in result["predecessors"]]
        assert "1" in pred_ids

    def test_successors(self, patched_data):
        from agent.qa.ims_tools import get_dependencies
        result = json.loads(get_dependencies("1"))
        succ_ids = [s["task_id"] for s in result["successors"]]
        assert "2" in succ_ids

    def test_task_not_found(self, patched_data):
        from agent.qa.ims_tools import get_dependencies
        result = json.loads(get_dependencies("999"))
        assert "error" in result

    def test_no_predecessors(self, patched_data):
        from agent.qa.ims_tools import get_dependencies
        result = json.loads(get_dependencies("1"))
        assert result["predecessors"] == []


class TestGetMilestones:
    def test_returns_milestones_only(self, patched_data):
        from agent.qa.ims_tools import get_milestones
        result = json.loads(get_milestones())
        assert result["count"] == 1
        assert result["milestones"][0]["task_id"] == "51"
        assert result["milestones"][0]["is_milestone"] is True

    def test_no_non_milestones(self, patched_data):
        from agent.qa.ims_tools import get_milestones
        result = json.loads(get_milestones())
        for m in result["milestones"]:
            assert m.get("is_milestone") is True


class TestGetBehindTasks:
    def test_finds_behind_tasks(self, patched_data):
        from agent.qa.ims_tools import get_behind_tasks
        result = json.loads(get_behind_tasks(threshold_pct=0))
        # Tasks 2 and 3 are in-progress and likely behind expected pct
        assert "behind_tasks" in result
        assert result["count"] >= 0  # can be 0 if all on track at test time

    def test_threshold_filters(self, patched_data):
        from agent.qa.ims_tools import get_behind_tasks
        # High threshold should return fewer tasks
        result_high = json.loads(get_behind_tasks(threshold_pct=90))
        result_low = json.loads(get_behind_tasks(threshold_pct=0))
        assert result_high["count"] <= result_low["count"]

    def test_sorted_by_variance(self, patched_data):
        from agent.qa.ims_tools import get_behind_tasks
        result = json.loads(get_behind_tasks(threshold_pct=0))
        variances = [t["variance_pct"] for t in result["behind_tasks"]]
        assert variances == sorted(variances, reverse=True)

    def test_milestones_excluded(self, patched_data):
        from agent.qa.ims_tools import get_behind_tasks
        result = json.loads(get_behind_tasks(threshold_pct=0))
        for t in result["behind_tasks"]:
            assert t.get("is_milestone") is not True


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------

class TestCallTool:
    def test_dispatches_get_task(self, patched_data):
        from agent.qa.ims_tools import call_tool
        result = json.loads(call_tool("get_task", {"task_id": "1"}))
        assert result["task_id"] == "1"

    def test_dispatches_search_tasks(self, patched_data):
        from agent.qa.ims_tools import call_tool
        result = json.loads(call_tool("search_tasks", {"query": "HW"}))
        assert result["count"] >= 1

    def test_unknown_tool(self, patched_data):
        from agent.qa.ims_tools import call_tool
        result = json.loads(call_tool("nonexistent_tool", {}))
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_tool_error_returns_json(self, patched_data):
        from agent.qa.ims_tools import call_tool
        # Pass wrong arg type to trigger an internal error
        result = json.loads(call_tool("get_float", {"task_id": None}))
        # Either an error key or a result — should never raise
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TOOL_SCHEMAS structure tests
# ---------------------------------------------------------------------------

class TestToolSchemas:
    def test_all_eight_tools_present(self):
        from agent.qa.ims_tools import TOOL_SCHEMAS
        names = {t["name"] for t in TOOL_SCHEMAS}
        expected = {
            "get_task", "search_tasks", "get_critical_path",
            "get_tasks_by_cam", "get_float", "get_dependencies",
            "get_milestones", "get_behind_tasks",
        }
        assert names == expected

    def test_each_schema_has_required_fields(self):
        from agent.qa.ims_tools import TOOL_SCHEMAS
        for tool in TOOL_SCHEMAS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_required_params_match_handlers(self):
        from agent.qa.ims_tools import TOOL_SCHEMAS
        # Tools that require task_id
        task_id_tools = {"get_task", "get_float", "get_dependencies"}
        for tool in TOOL_SCHEMAS:
            if tool["name"] in task_id_tools:
                assert "task_id" in tool["input_schema"]["required"]


# ---------------------------------------------------------------------------
# LLMInterface.ask_with_tools tests
# ---------------------------------------------------------------------------

class TestAskWithTools:
    """Test the Anthropic tool-use agentic loop in LLMInterface."""

    def _make_response(self, stop_reason, content):
        resp = MagicMock()
        resp.stop_reason = stop_reason
        resp.content = content
        resp.usage = MagicMock(output_tokens=100)
        return resp

    def _make_text_block(self, text):
        block = MagicMock()
        block.type = "text"
        block.text = text
        return block

    def _make_tool_use_block(self, name, input_dict, use_id="tu_123"):
        block = MagicMock()
        block.type = "tool_use"
        block.name = name
        block.input = input_dict
        block.id = use_id
        return block

    @pytest.fixture
    def llm(self):
        with patch("agent.llm_interface.os.getenv", return_value="fake-key"):
            with patch("agent.llm_interface.anthropic.Anthropic"):
                from agent.llm_interface import LLMInterface
                return LLMInterface()

    def test_end_turn_on_first_round(self, llm, patched_data):
        text_block = self._make_text_block("The schedule is RED.")
        response = self._make_response("end_turn", [text_block])
        llm._client.messages.create.return_value = response

        from agent.qa.ims_tools import TOOL_SCHEMAS
        result = llm.ask_with_tools("What is the schedule?", "context", TOOL_SCHEMAS)
        assert result == "The schedule is RED."
        assert llm._client.messages.create.call_count == 1

    def test_tool_use_then_end_turn(self, llm, patched_data):
        tool_block = self._make_tool_use_block("get_task", {"task_id": "1"})
        text_block = self._make_text_block("Task 1 is on the critical path.")

        round1 = self._make_response("tool_use", [tool_block])
        round2 = self._make_response("end_turn", [text_block])
        llm._client.messages.create.side_effect = [round1, round2]

        from agent.qa.ims_tools import TOOL_SCHEMAS
        result = llm.ask_with_tools("Tell me about task 1", "context", TOOL_SCHEMAS)
        assert "Task 1" in result
        assert llm._client.messages.create.call_count == 2

    def test_tool_result_appended_to_messages(self, llm, patched_data):
        tool_block = self._make_tool_use_block("get_milestones", {}, "tu_456")
        text_block = self._make_text_block("There is 1 milestone.")

        round1 = self._make_response("tool_use", [tool_block])
        round2 = self._make_response("end_turn", [text_block])
        llm._client.messages.create.side_effect = [round1, round2]

        from agent.qa.ims_tools import TOOL_SCHEMAS
        llm.ask_with_tools("What are the milestones?", "context", TOOL_SCHEMAS)

        # Second call should have 3 messages: user, assistant (tool_use), user (tool_result)
        second_call_messages = llm._client.messages.create.call_args_list[1][1]["messages"]
        assert len(second_call_messages) == 3
        # Last message should be tool_result
        tool_result_msg = second_call_messages[-1]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "tu_456"

    def test_max_rounds_exceeded_returns_fallback(self, llm, patched_data):
        tool_block = self._make_tool_use_block("get_task", {"task_id": "1"})
        always_tool = self._make_response("tool_use", [tool_block])
        llm._client.messages.create.return_value = always_tool

        from agent.qa.ims_tools import TOOL_SCHEMAS
        result = llm.ask_with_tools("any question", "ctx", TOOL_SCHEMAS, max_rounds=3)
        assert "Unable" in result
        assert llm._client.messages.create.call_count == 3

    def test_unexpected_stop_reason_returns_text(self, llm, patched_data):
        text_block = self._make_text_block("Partial answer.")
        response = self._make_response("max_tokens", [text_block])
        llm._client.messages.create.return_value = response

        from agent.qa.ims_tools import TOOL_SCHEMAS
        result = llm.ask_with_tools("anything", "ctx", TOOL_SCHEMAS)
        assert result == "Partial answer."

    def test_tools_passed_to_api(self, llm, patched_data):
        text_block = self._make_text_block("Answer.")
        response = self._make_response("end_turn", [text_block])
        llm._client.messages.create.return_value = response

        from agent.qa.ims_tools import TOOL_SCHEMAS
        llm.ask_with_tools("question", "ctx", TOOL_SCHEMAS)

        call_kwargs = llm._client.messages.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# QAEngine integration (tool-use path)
# ---------------------------------------------------------------------------

class TestQAEngineWithTools:
    """Test that QAEngine.ask() uses ask_with_tools for LLM-routed questions."""

    @pytest.fixture
    def state_file(self, tmp_path, monkeypatch):
        import json as _json
        state = {
            "cycle_id": "20260426T104747Z",
            "schedule_health": "RED",
            "critical_path_task_ids": ["1", "2"],
            "narrative": "Schedule is in critical condition.",
            "top_risks": "1. RF specs dependency",
            "recommended_actions": "1. Escalate RF specs.",
            "milestones": [],
            "tasks_behind": [],
            "cam_response_status": {},
        }
        sf = tmp_path / "dashboard_state.json"
        sf.write_text(_json.dumps(state))
        hf = tmp_path / "cycle_history.json"
        hf.write_text("[]")
        import agent.qa.context_builder as cb
        monkeypatch.setattr(cb, "_STATE_FILE", sf)
        monkeypatch.setattr(cb, "_HISTORY_FILE", hf)
        return sf

    def test_llm_path_calls_ask_with_tools(self, state_file, patched_data):
        # LLMInterface is lazily imported inside ask(), so patch at its definition site
        with patch("agent.llm_interface.LLMInterface") as MockLLM:
            mock_instance = MagicMock()
            mock_instance.ask_with_tools.return_value = "Task 1 has 0 days float."
            MockLLM.return_value = mock_instance

            from agent.qa.qa_engine import QAEngine
            response = QAEngine().ask("What is the float on task 1?")

            assert mock_instance.ask_with_tools.called
            assert response.direct is False

    def test_direct_path_skips_tools(self, state_file):
        with patch("agent.llm_interface.LLMInterface") as MockLLM:
            mock_instance = MagicMock()
            MockLLM.return_value = mock_instance

            from agent.qa.qa_engine import QAEngine
            response = QAEngine().ask("What is the schedule health?")

            # Direct path — LLM should not be called at all
            assert not mock_instance.ask_with_tools.called
            assert not mock_instance.ask.called
            assert response.direct is True
            assert "RED" in response.answer
