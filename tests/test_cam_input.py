"""
Tests for agent.cam_input — CAM status input validation.

Covers 1.3 checklist items:
- Validation catches invalid inputs (percent out of range, missing fields, etc.)
"""

import pytest
from datetime import datetime


def _valid_input(**overrides) -> dict:
    base = {
        "task_id": "5",
        "cam_name": "Alice Nguyen",
        "percent_complete": 50,
        "blocker": "",
        "risk_flag": False,
        "risk_description": "",
        "timestamp": datetime.now().isoformat(),
    }
    base.update(overrides)
    return base


class TestValidateCamInputs:
    def test_valid_input_no_errors(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input()])
        assert errors == []

    def test_percent_complete_below_zero(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(percent_complete=-1)])
        assert any("percent_complete" in e for e in errors)

    def test_percent_complete_above_100(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(percent_complete=101)])
        assert any("percent_complete" in e for e in errors)

    def test_percent_complete_exactly_zero(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(percent_complete=0)])
        assert errors == []

    def test_percent_complete_exactly_100(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(percent_complete=100)])
        assert errors == []

    def test_missing_cam_name(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(cam_name="")])
        assert any("cam_name" in e for e in errors)

    def test_missing_task_id(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(task_id="")])
        assert any("task_id" in e for e in errors)

    def test_risk_flag_true_requires_description(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([_valid_input(risk_flag=True, risk_description="")])
        assert any("risk_description" in e for e in errors)

    def test_risk_flag_true_with_description_valid(self):
        from agent.cam_input import validate_cam_inputs
        errors = validate_cam_inputs([
            _valid_input(risk_flag=True, risk_description="Supplier lead time extended")
        ])
        assert errors == []

    def test_multiple_inputs_mixed_validity(self):
        from agent.cam_input import validate_cam_inputs
        inputs = [
            _valid_input(task_id="1"),
            _valid_input(task_id="2", percent_complete=150),  # invalid
            _valid_input(task_id="3", risk_flag=True, risk_description=""),  # invalid
        ]
        errors = validate_cam_inputs(inputs)
        assert len(errors) == 2

    def test_none_percent_complete_flagged(self):
        from agent.cam_input import validate_cam_inputs
        inp = _valid_input()
        inp["percent_complete"] = None
        errors = validate_cam_inputs([inp])
        assert any("percent_complete" in e for e in errors)
