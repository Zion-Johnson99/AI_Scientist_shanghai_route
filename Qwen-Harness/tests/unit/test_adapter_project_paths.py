from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qwen_harness.adapters.environment_data import EnvironmentDataAdapter
from qwen_harness.adapters.evaluation_model import EvaluationModelAdapter
from qwen_harness.adapters.project_paths import GeneratedProjectPaths
from qwen_harness.adapters.route_builder import RouteBuilderAdapter
from qwen_harness.adapters.web_product import WebProductAdapter
from qwen_harness.errors import InputContractError, PathBoundaryError
from qwen_harness.models import CommandAudit, ModuleOperation


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _generated_context(tmp_path: Path) -> Any:
    run_dir = tmp_path / "runtime" / "runs" / "run-1"
    source = run_dir / "workspace" / "source"
    route = source / "xuhui_route_builder"
    environment = source / "weather_api_data"
    evaluation = source / "evaluation_model_qwen"
    harness = source / "Qwen-Harness"
    for root in (route, environment, evaluation, harness):
        root.mkdir(parents=True)
    score_script = harness / "src/qwen_harness/adapters/evaluation_score_candidates.py"
    score_script.parent.mkdir(parents=True)
    score_script.write_text("# generated score entry\n", encoding="utf-8")

    _write_json(route / "data/web/route_catalog.json", [{"source": "generated"}])
    _write_json(route / "data/web/xuhui_routes.geojson", {"source": "generated"})
    _write_json(route / "data/web/environment_dashboard.json", {"source": "generated"})
    (route / "web").mkdir()
    (route / "web/index.html").write_text("generated", encoding="utf-8")
    _write_json(
        evaluation / "config/default_weights.json",
        {
            "goal_weights": {},
            "environment_weights": {},
            "risk_thresholds": {},
            "status_reliability": {},
        },
    )

    external = tmp_path / "external-repository"
    _write_json(external / "xuhui_route_builder/data/web/route_catalog.json", [{"source": "bait"}])
    _write_json(
        external / "xuhui_route_builder/data/web/environment_dashboard.json", {"source": "bait"}
    )
    legacy_paths = SimpleNamespace(
        repo_root=tmp_path,
        harness_root=external / "Qwen-Harness",
        route_module=external / "xuhui_route_builder",
        environment_module=external / "weather_api_data",
        evaluation_module=external / "evaluation_model_qwen",
        web_root=external / "xuhui_route_builder/web",
        web_data_root=external / "xuhui_route_builder/data/web",
        route_catalog_path=external / "xuhui_route_builder/data/web/route_catalog.json",
        environment_dashboard_path=external
        / "xuhui_route_builder/data/web/environment_dashboard.json",
    )
    return SimpleNamespace(
        run_dir=run_dir,
        generated=SimpleNamespace(
            module_paths={
                "route": "xuhui_route_builder",
                "environment": "weather_api_data",
                "evaluation": "evaluation_model_qwen",
                "web": "xuhui_route_builder/web",
            }
        ),
        options=SimpleNamespace(offline=False, refresh_environment="none"),
        paths=legacy_paths,
    )


def test_generated_project_paths_ignore_external_repository_bait(tmp_path: Path) -> None:
    context = _generated_context(tmp_path)

    paths = GeneratedProjectPaths.from_context(context)

    assert paths.generated is True
    assert paths.route_catalog_path.read_text(encoding="utf-8").find("generated") >= 0
    assert paths.environment_dashboard_path.read_text(encoding="utf-8").find("generated") >= 0
    for root in paths.module_roots:
        root.resolve().relative_to(paths.source_root.resolve())


def test_all_adapters_read_generated_workspace_view(tmp_path: Path) -> None:
    context = _generated_context(tmp_path)

    route_result = RouteBuilderAdapter().snapshot(context)
    environment_result = EnvironmentDataAdapter().snapshot(context)
    evaluation_result = EvaluationModelAdapter().preflight(context)
    web_result = WebProductAdapter().preflight(context)

    assert route_result.status == "partial"
    assert environment_result.status == "partial"
    assert evaluation_result.status == "ok"
    assert web_result.status == "ok"
    generated_catalog = GeneratedProjectPaths.from_context(context).route_catalog_path
    generated_dashboard = GeneratedProjectPaths.from_context(context).environment_dashboard_path
    assert (
        route_result.data_hashes["route_catalog.json"]
        == hashlib.sha256(generated_catalog.read_bytes()).hexdigest()
    )
    assert (
        environment_result.data_hashes["environment_dashboard.json"]
        == hashlib.sha256(generated_dashboard.read_bytes()).hexdigest()
    )
    assert all(
        "bait" not in message
        for result in (route_result, environment_result)
        for message in result.errors
    )


def test_environment_preflight_accepts_generated_routes_items_contract(tmp_path: Path) -> None:
    context = _generated_context(tmp_path)
    paths = GeneratedProjectPaths.from_context(context)
    route_ids = [f"route-{index:03d}" for index in range(90)]
    _write_json(
        paths.route_catalog_path,
        [{"route_id": route_id} for route_id in route_ids],
    )
    metric = {
        "value": None,
        "unit": "proxy",
        "estimated": True,
        "status": "no_data",
    }
    _write_json(
        paths.environment_dashboard_path,
        {
            "metadata": {
                "generated_at": "2026-09-02T00:00:00+00:00",
                "status": "ok",
            },
            "current": {"status": "no_data"},
            "forecast": {"status": "no_data"},
            "routes": {
                "count": 90,
                "items": [
                    {
                        "route_id": route_id,
                        "pm2_5": metric,
                        "noise": metric,
                        "pollen_daily": metric,
                    }
                    for route_id in route_ids
                ],
            },
        },
    )

    result = EnvironmentDataAdapter().preflight(context)

    assert result.status == "partial"
    assert result.errors == []


def test_generated_project_paths_reject_module_outside_current_run(tmp_path: Path) -> None:
    context = _generated_context(tmp_path)
    context.generated.module_paths["route"] = str(
        tmp_path / "external-repository/xuhui_route_builder"
    )

    with pytest.raises(PathBoundaryError, match="越出当前 run 生成源码边界"):
        GeneratedProjectPaths.from_context(context)


def test_module_commands_use_generated_module_as_directory(tmp_path: Path, monkeypatch) -> None:
    context = _generated_context(tmp_path)
    captured: list[tuple[list[str], Path]] = []

    def fake_run_fixed_command(
        _context: Any, command_id: str, argv: list[str], *, cwd: Path, **_kwargs: Any
    ) -> CommandAudit:
        captured.append((argv, cwd))
        now = datetime.now(timezone.utc)
        return CommandAudit(
            command_id=command_id,
            argv=argv,
            cwd=str(cwd),
            started_at=now,
            finished_at=now,
            exit_code=0,
            stdout_path="stdout.log",
            stderr_path="stderr.log",
            timeout=False,
        )

    route = RouteBuilderAdapter()
    environment = EnvironmentDataAdapter()
    monkeypatch.setattr(route, "run_fixed_command", fake_run_fixed_command)
    monkeypatch.setattr(environment, "run_fixed_command", fake_run_fixed_command)

    route.execute(ModuleOperation(operation_id="route.validate_routes", module="route"), context)
    environment.validate(context)

    source_root = GeneratedProjectPaths.from_context(context).source_root
    assert len(captured) == 3
    for argv, cwd in captured:
        cwd.resolve().relative_to(source_root)
        assert argv[3] == str(cwd)


def test_generated_project_paths_require_explicit_module_mapping(tmp_path: Path) -> None:
    with pytest.raises(InputContractError, match=r"generated\.module_paths"):
        GeneratedProjectPaths.from_context(SimpleNamespace(run_dir=tmp_path))
