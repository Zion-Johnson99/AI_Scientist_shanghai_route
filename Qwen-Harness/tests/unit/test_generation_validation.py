from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qwen_harness.adapters.environment_data import EnvironmentDataAdapter
from qwen_harness.adapters.evaluation_model import EvaluationModelAdapter
from qwen_harness.adapters.route_builder import RouteBuilderAdapter
from qwen_harness.adapters.web_product import WebProductAdapter
from qwen_harness.generation.stage_handlers import (
    OFFLINE_FIXTURE_PROVENANCE,
    OfflineFixtureModelClient,
    _materialize_generated_data,
    build_generation_requirements,
    stage_handler,
)
from qwen_harness.generation.validation import FunctionalContractValidator
from qwen_harness.llm.prompts import PromptBuilder
from qwen_harness.models import ResearchGoal


class FakeStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_id = "run-generation-test"

    def write_json_atomic(self, relative: str, data: Any) -> Path:
        target = self.run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target


class EmptySkills:
    def discover(self) -> dict[str, Any]:
        return {}


def _offline_context(tmp_path: Path) -> Any:
    store = FakeStore(tmp_path / "run")
    store.run_dir.mkdir(parents=True)
    experiment = {
        "hypothesis_id": "hyp-001",
        "profiles": [{"profile_id": "runner"}],
        "baselines": [{"baseline_id": "shortest"}],
        "variants": ["health_weighted"],
        "metrics": [{"metric_id": "exposure", "primary": True}],
        "detour_limit": 0.3,
        "target_distance_tolerance": 0.15,
        "module_operations": [],
        "acceptance_criteria": ["生成 90 条路线"],
        "stop_conditions": ["功能契约分数达到 85"],
    }
    context = SimpleNamespace(
        store=store,
        run_dir=store.run_dir,
        run_id=store.run_id,
        goal=ResearchGoal(
            title="徐汇健康路线",
            question="如何生成环境暴露更低的运动路线？",
            constraints=["提供本地地图网页"],
        ),
        options=SimpleNamespace(offline=True, max_iterations=2),
        harness_config=SimpleNamespace(runtime=SimpleNamespace(max_iterations=2)),
        model_client=None,
        prompts=PromptBuilder(),
        skills=EmptySkills(),
        stage_spec=SimpleNamespace(name="project_generation", required_skills=[]),
        read_stage_output=lambda stage: experiment if stage == "experiment_design" else None,
        emit=lambda *args, **kwargs: None,
    )
    return context


def test_functional_validator_scores_complete_fixture_at_least_85(tmp_path: Path) -> None:
    context = _offline_context(tmp_path)

    result = stage_handler(context)
    report = json.loads(
        (context.run_dir / "checks" / "generation_contract.json").read_text(encoding="utf-8")
    )

    assert result.status == "passed"
    assert report["score"] >= 85
    assert report["passed"] is True
    assert report["provenance"] == OFFLINE_FIXTURE_PROVENANCE
    assert result.output["provenance"] == OFFLINE_FIXTURE_PROVENANCE
    assert (context.run_dir / "workspace" / "architecture.json").is_file()
    assert (context.run_dir / "workspace" / "generation_result.json").is_file()
    assert (context.run_dir / "stages" / "project_generation" / "model_audits.json").is_file()


def test_validator_blocks_sensitive_value_even_when_score_is_high(tmp_path: Path) -> None:
    context = _offline_context(tmp_path)
    stage_handler(context)
    source_root = context.run_dir / "workspace" / "source"
    (source_root / "weather_api_data" / "secret.py").write_text(
        'api_key = "sk-live-secret-value-123456"\n', encoding="utf-8"
    )

    validator = FunctionalContractValidator(provenance="qwen")
    issues = validator(source_root)

    assert validator.last_report is not None
    assert validator.last_report.passed is False
    assert any(issue.check == "sensitive_information" for issue in issues)


def test_validator_reports_missing_contracts_and_stays_below_threshold(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    for name in (
        "Qwen-Harness",
        "evaluation_model_qwen",
        "weather_api_data",
        "xuhui_route_builder",
    ):
        (source_root / name).mkdir(parents=True)

    validator = FunctionalContractValidator(provenance="qwen")
    issues = validator(source_root)

    assert validator.last_report is not None
    assert validator.last_report.score < 85
    assert validator.last_report.passed is False
    assert {issue.check for issue in issues} >= {
        "environment_interface",
        "route_generation",
        "evaluation_api",
        "route_catalog_90",
        "map_web",
        "local_launcher",
        "tests_present",
    }


def test_validator_rejects_non_module_entry_and_wrong_web_data_path(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    for name in (
        "Qwen-Harness",
        "evaluation_model_qwen",
        "weather_api_data",
        "xuhui_route_builder",
    ):
        (source_root / name).mkdir(parents=True)
    web = source_root / "xuhui_route_builder" / "web"
    (web / "src").mkdir(parents=True)
    (web / "index.html").write_text(
        '<div id="map"></div><script src="src/main.js"></script>',
        encoding="utf-8",
    )
    (web / "src" / "main.js").write_text(
        "import { load } from './data-loader.js';\nload();\n",
        encoding="utf-8",
    )
    (web / "src" / "data-loader.js").write_text(
        "const DATA_BASE = 'data/web/';\nfetch(DATA_BASE + 'route_catalog.json');\n",
        encoding="utf-8",
    )

    issues = FunctionalContractValidator(provenance="qwen")(source_root)

    assert any(issue.check == "map_web" for issue in issues)


def test_validator_reports_absolute_path_and_parent_traversal(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target = source_root / "Qwen-Harness" / "bad_paths.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        'CACHE = "C:\\\\Users\\\\fixture\\\\cache"\nopen("../outside.txt")\n',
        encoding="utf-8",
    )

    validator = FunctionalContractValidator(provenance="qwen")
    issues = validator(source_root)

    assert {issue.check for issue in issues} >= {"absolute_paths", "path_traversal"}


def test_validator_does_not_treat_https_or_test_assertions_as_absolute_paths(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    for name in (
        "Qwen-Harness",
        "evaluation_model_qwen",
        "weather_api_data",
        "xuhui_route_builder",
    ):
        (source_root / name).mkdir(parents=True)
    web = source_root / "xuhui_route_builder" / "web" / "index.html"
    web.parent.mkdir(parents=True)
    web.write_text('<script src="https://unpkg.com/library.js"></script>', encoding="utf-8")
    test_file = source_root / "weather_api_data" / "tests" / "test_paths.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text('assert "C:\\\\Users\\\\" not in output\n', encoding="utf-8")

    issues = FunctionalContractValidator(provenance="qwen")(source_root)

    assert not any(issue.check == "absolute_paths" for issue in issues)


def test_online_stage_uses_injected_qwen_client_and_qwen_provenance(tmp_path: Path) -> None:
    context = _offline_context(tmp_path)
    context.options.offline = False
    context.model_client = OfflineFixtureModelClient()

    result = stage_handler(context)

    assert result.status == "passed"
    assert result.output["provenance"] == "qwen"
    audit = json.loads(
        (context.run_dir / "stages" / "project_generation" / "model_audits.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["provenance"] == "qwen"


def test_build_requirements_includes_goal_experiment_and_skill_names(tmp_path: Path) -> None:
    context = _offline_context(tmp_path)
    skills = [SimpleNamespace(name="route-skill", description="路线工程约束")]

    requirements = build_generation_requirements(context, skills)

    assert "徐汇健康路线" in requirements
    assert "hyp-001" in requirements
    assert "route-skill" in requirements
    assert "Qwen-Harness/src/qwen_harness/__init__.py" in requirements
    assert "evaluation_model_qwen/src/evaluation_model_qwen/__init__.py" in requirements
    assert "weather_api_data/src/weather_api_data/__init__.py" in requirements
    assert "xuhui_route_builder/src/xuhui_route_builder/__init__.py" in requirements
    assert "xuhui_route_builder/pyproject.toml" in requirements
    assert "1440x900" in requirements
    assert "390x844" in requirements
    assert "data-testid=map" in requirements
    assert "data-testid=route-card" in requirements
    assert "data-testid=environment-details" in requirements
    assert "PM2.5、噪声、花粉" in requirements
    assert "https://zion-johnson99.github.io/AI_Scientist_shanghai_route/" in requirements


def test_build_requirements_compacts_verbose_research_fields(tmp_path: Path) -> None:
    context = _offline_context(tmp_path)
    verbose = "冗长科研描述" * 2_000
    experiment = context.read_stage_output("experiment_design")
    experiment["profiles"][0]["description"] = verbose
    experiment["metrics"][0]["formula"] = verbose
    context.read_stage_output = lambda stage: experiment if stage == "experiment_design" else None
    skills = [SimpleNamespace(name="route-skill", description=verbose)]

    requirements = build_generation_requirements(context, skills)

    assert len(requirements) < 12_000
    assert verbose not in requirements
    assert '"profile_id": "runner"' in requirements
    assert '"metric_id": "exposure"' in requirements


def test_materializer_builds_large_data_from_generated_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    route_src = source_root / "xuhui_route_builder" / "src" / "xuhui_route_builder"
    weather_src = source_root / "weather_api_data" / "src" / "weather_api_data"
    route_src.mkdir(parents=True)
    weather_src.mkdir(parents=True)
    (route_src / "__init__.py").write_text("", encoding="utf-8")
    (weather_src / "__init__.py").write_text("", encoding="utf-8")
    (route_src / "generate_data.py").write_text(
        "from pathlib import Path\n"
        "def main(output):\n"
        " p=Path(output); p.mkdir(parents=True, exist_ok=True)\n"
        " (p/'route_catalog.json').write_text('[]', encoding='utf-8')\n"
        " (p/'xuhui_routes.geojson').write_text('{\\\"type\\\":\\\"FeatureCollection\\\",\\\"features\\\":[]}', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (weather_src / "web_export.py").write_text(
        "from pathlib import Path\n"
        "def publish_web(data_dir, output_path):\n"
        " assert (Path(data_dir)/'route_catalog.json').is_file()\n"
        ' Path(output_path).write_text(\'{\\"metadata\\":{},\\"current\\":{},\\"forecast\\":{},\\"routes\\":{\\"items\\":[]}}\', encoding=\'utf-8\')\n',
        encoding="utf-8",
    )

    issues = _materialize_generated_data(source_root)

    data_dir = source_root / "xuhui_route_builder" / "data" / "web"
    assert issues == []
    assert (data_dir / "route_catalog.json").is_file()
    assert (data_dir / "xuhui_routes.geojson").is_file()
    assert (data_dir / "environment_dashboard.json").is_file()


def test_offline_generated_fixture_satisfies_all_module_preflights(tmp_path: Path) -> None:
    context = _offline_context(tmp_path)
    context.generated = SimpleNamespace(
        module_paths={
            "route": "xuhui_route_builder",
            "environment": "weather_api_data",
            "evaluation": "evaluation_model_qwen",
            "web": "xuhui_route_builder/web",
        }
    )
    stage_handler(context)

    results = [
        RouteBuilderAdapter().preflight(context),
        EnvironmentDataAdapter().preflight(context),
        EvaluationModelAdapter().preflight(context),
        WebProductAdapter().preflight(context),
    ]

    assert all(result.status != "error" for result in results), [
        result.errors for result in results
    ]
