from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from qwen_harness.models import ExperimentPlan
from qwen_harness.workflow.stages import _expand_plan_operations


def _plan_payload() -> dict[str, object]:
    return {
        "hypothesis_id": "hyp-001",
        "profiles": [],
        "baselines": [],
        "variants": [],
        "metrics": [],
        "detour_limit": 0.2,
        "target_distance_tolerance": 0.15,
        "acceptance_criteria": [],
        "stop_conditions": [],
    }


def test_module_operation_requires_explicit_id_and_module() -> None:
    payload = _plan_payload()
    payload["module_operations"] = [{"parameters": {}}]

    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(payload)


def test_module_operation_schema_exposes_required_fields() -> None:
    schema = ExperimentPlan.model_json_schema()
    operation_schema = cast(dict[str, Any], schema["$defs"]["ModuleOperation"])

    assert set(operation_schema["required"]) >= {"operation_id", "module"}


def test_score_operation_expands_to_each_declared_profile() -> None:
    payload = _plan_payload()
    payload["profiles"] = [
        {"case_id": "P01", "route_mode": "walk", "target_distance_m": 3000},
        {"case_id": "P02", "route_mode": "run", "target_distance_m": 5000},
    ]
    payload["variants"] = ["B0_shortest_feasible", "M1_personalized_constrained"]
    payload["module_operations"] = [
        {
            "operation_id": "evaluation.score_candidates",
            "module": "evaluation",
            "parameters": {"profiles": "all"},
        }
    ]
    plan = ExperimentPlan.model_validate(payload)

    operations = _expand_plan_operations(plan)

    assert [item.parameters["label"] for item in operations] == ["P01", "P02"]
    assert [
        cast(dict[str, object], item.parameters["profile"])["case_id"] for item in operations
    ] == ["P01", "P02"]
    assert all(item.parameters["variants"] == payload["variants"] for item in operations)
