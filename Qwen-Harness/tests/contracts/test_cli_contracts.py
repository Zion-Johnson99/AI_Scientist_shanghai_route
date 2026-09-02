from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import qwen_harness.adapters.evaluation_score_candidates as score_module
from qwen_harness.adapters.evaluation_model import EvaluationModelAdapter
from qwen_harness.adapters.evaluation_score_candidates import build_parser as build_score_parser
from qwen_harness.cli import _build_parser, main
from qwen_harness.models import ModuleOperation


def test_qwen_harness_parser_preserves_offline_run_contract() -> None:
    args = _build_parser().parse_args(
        [
            "run",
            "--goal",
            "验证本地科研闭环",
            "--workflow",
            "reproduce-existing",
            "--offline",
            "--approval-mode",
            "auto",
        ]
    )

    assert args.command == "run"
    assert args.goal == "验证本地科研闭环"
    assert args.workflow == "reproduce-existing"
    assert args.offline is True
    assert args.allow_network is False


def test_qwen_harness_cli_rejects_blank_goal(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["run", "--goal", "   ", "--offline"])

    assert exit_code == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"]["error_type"] == "input_contract_error"


def test_harness_score_candidates_parser_exposes_narrow_local_interface() -> None:
    args = build_score_parser().parse_args(
        [
            "--profile",
            "profile.json",
            "--weights",
            "weights.json",
            "--route-catalog",
            "routes.json",
            "--environment-dashboard",
            "environment.json",
        ]
    )

    assert str(args.profile) == "profile.json"
    assert str(args.weights) == "weights.json"
    assert str(args.route_catalog) == "routes.json"
    assert str(args.environment_dashboard) == "environment.json"


def test_score_entry_reports_missing_generated_evaluation_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_module(_name: str) -> None:
        raise ModuleNotFoundError("generated module missing")

    monkeypatch.setattr(score_module, "import_module", missing_module)

    with pytest.raises(RuntimeError, match="当前 run 生成的评价模块"):
        score_module._load_evaluation_api()


def test_evaluation_adapter_invokes_harness_owned_score_script(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    context: Any = SimpleNamespace(
        run_dir=run_dir,
        generated=SimpleNamespace(
            module_paths={
                "route": "xuhui_route_builder",
                "environment": "weather_api_data",
                "evaluation": "evaluation_model_qwen",
                "web": "xuhui_route_builder/web",
            }
        )
    )

    argv = EvaluationModelAdapter()._score_command_argv(
        context,
        profile_path=Path("profile.json"),
        weights_path=Path("weights.json"),
        catalog_path=Path("routes.json"),
        dashboard_path=Path("environment.json"),
    )

    assert "evaluation-model-qwen" not in argv
    assert argv[3] == str(
        (run_dir / "workspace/source/evaluation_model_qwen").resolve()
    )
    assert argv[5].endswith("evaluation_score_candidates.py")


def test_evaluation_adapter_accepts_exact_score_candidates_contract() -> None:
    payload: dict[str, Any] = {
        "profile": {"profile_id": "qa"},
        "risk": {"status": "ok"},
        "data_generated_at": "2026-09-02T00:00:00+00:00",
        "candidate_count": 1,
        "candidates": [{"route": {"route_id": "route-1"}}],
        "weights_sha256": "a" * 64,
    }

    assert EvaluationModelAdapter()._validate_contract(payload) == []


def test_evaluation_adapter_rejects_candidate_count_mismatch() -> None:
    payload: dict[str, Any] = {
        "profile": {},
        "risk": {},
        "data_generated_at": "2026-09-02T00:00:00+00:00",
        "candidate_count": 2,
        "candidates": [],
        "weights_sha256": "a" * 64,
    }

    errors = EvaluationModelAdapter()._validate_contract(payload)

    assert any("candidates 数量" in error for error in errors)


def test_evaluation_adapter_writes_one_candidate_cell_per_variant(tmp_path: Path) -> None:
    class Store:
        run_dir = tmp_path

        @staticmethod
        def write_json_atomic(relative: str, payload: dict[str, Any]) -> Path:
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
            return target

    context: Any = SimpleNamespace(store=Store())
    operation = ModuleOperation(
        operation_id="evaluation.score_candidates",
        module="evaluation",
        parameters={
            "label": "P01",
            "variants": ["B0_shortest_feasible", "M1_personalized_constrained"],
        },
    )
    payload: dict[str, Any] = {
        "profile": {"case_id": "P01"},
        "risk": {"status": "ok"},
        "data_generated_at": "2026-09-02T00:00:00+00:00",
        "candidate_count": 0,
        "candidates": [],
        "weights_sha256": "a" * 64,
    }

    outputs = EvaluationModelAdapter()._write_candidate_cells(
        operation, context, payload
    )

    assert outputs == [
        "experiments/score_candidates/P01__B0_shortest_feasible.json",
        "experiments/score_candidates/P01__M1_personalized_constrained.json",
    ]
    bodies = [json.loads((tmp_path / relative).read_text(encoding="utf-8")) for relative in outputs]
    assert [body["variant_id"] for body in bodies] == [
        "B0_shortest_feasible",
        "M1_personalized_constrained",
    ]
