"""生成工程阶段处理器与测试专用离线 fixture。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from pydantic import BaseModel

from ..errors import InputContractError, ModelUnavailableError
from ..models import GateCheck, GateResult, ModelCallAudit, StageResult
from ..skills import CORE_SKILLS
from .engine import GenerationEngine
from .models import ArchitecturePlan, FilePlan, GeneratedFile, RepairBatch, ValidationIssue
from .validation import FunctionalContractReport, FunctionalContractValidator
from .workspace import GenerationWorkspace

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

OFFLINE_FIXTURE_PROVENANCE = "offline_fixture"
QWEN_PROVENANCE = "qwen"

_DEFERRED_DATA_PATHS = {
    "xuhui_route_builder/data/web/route_catalog.json",
    "xuhui_route_builder/data/web/xuhui_routes.geojson",
    "xuhui_route_builder/data/web/environment_dashboard.json",
}


def _materialize_generated_data(source_root: Path) -> list[ValidationIssue]:
    """执行本次千问生成的数据构建器，物化大型 JSON 交付物。"""
    route_builder = "xuhui_route_builder/src/xuhui_route_builder/generate_data.py"
    environment_builder = "weather_api_data/src/weather_api_data/web_export.py"
    required_sources = [route_builder, environment_builder]
    missing = [path for path in required_sources if not (source_root / path).is_file()]
    if missing:
        return [
            ValidationIssue(
                check="generated_data_materialization",
                summary="生成数据构建器缺失",
                details=", ".join(missing),
                files=missing,
            )
        ]

    data_dir = source_root / "xuhui_route_builder" / "data" / "web"
    catalog_path = data_dir / "route_catalog.json"
    environment_path = data_dir / "environment_dashboard.json"
    python_paths = [
        source_root / "xuhui_route_builder" / "src",
        source_root / "weather_api_data" / "src",
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(path) for path in python_paths]
        + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
    )
    commands = [
        (
            [
                sys.executable,
                "-c",
                "from xuhui_route_builder.generate_data import main; import sys; main(sys.argv[1])",
                str(data_dir),
            ],
            [route_builder],
        ),
        (
            [
                sys.executable,
                "-c",
                (
                    "from inspect import signature; from pathlib import Path; "
                    "from weather_api_data.web_export import publish_web; import sys; "
                    "params=signature(publish_web).parameters; "
                    "source=Path(sys.argv[1]) if 'data_dir' in params else Path(sys.argv[2]); "
                    "publish_web(source, output_path=Path(sys.argv[3]))"
                ),
                str(data_dir),
                str(catalog_path),
                str(environment_path),
            ],
            [environment_builder],
        ),
    ]
    for command, affected_files in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=source_root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [
                ValidationIssue(
                    check="generated_data_materialization",
                    summary="生成数据构建器执行失败",
                    details=f"{type(exc).__name__}: {exc}",
                    files=affected_files,
                )
            ]
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "无输出")[-2000:]
            return [
                ValidationIssue(
                    check="generated_data_materialization",
                    summary=f"生成数据构建器退出码 {completed.returncode}",
                    details=details,
                    files=affected_files,
                )
            ]
    return []


def _fixture_route_id(index: int) -> str:
    fixed = {
        1: "XH_WALK_0001",
        2: "XH_WALK_0002",
        31: "XH_RUN_0031",
        61: "XH_BIKE_0061",
    }
    return fixed.get(index, f"fixture-route-{index:03d}")


def _fixture_routes() -> str:
    routes = [
        {
            "route_id": _fixture_route_id(index),
            "route_name": f"离线路线 {index}",
            "route_mode": ("walk", "run", "bike")[(index - 1) // 30],
            "distance_m": 1000 + ((index - 1) % 30) * 300,
            "validation_status": "accepted",
            "geometry_status": "accepted",
            "provenance": OFFLINE_FIXTURE_PROVENANCE,
        }
        for index in range(1, 91)
    ]
    return json.dumps(routes, ensure_ascii=False, indent=2)


def _fixture_route_geojson() -> str:
    features = [
        {
            "type": "Feature",
            "properties": {"route_id": _fixture_route_id(index)},
            "geometry": {
                "type": "LineString",
                "coordinates": [[121.43, 31.18], [121.44, 31.19]],
            },
        }
        for index in range(1, 91)
    ]
    return json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        indent=2,
    )


def _fixture_environment_dashboard() -> str:
    def metric(value: float, unit: str) -> dict[str, object]:
        return {
            "value": value,
            "status": "ok",
            "estimated": True,
            "unit": unit,
            "business_time": "static_scenario",
        }

    items = [
        {
            "route_id": _fixture_route_id(index),
            "status": "ok",
            "pm2_5": metric(18.0 + index % 5, "µg/m³"),
            "noise": metric(35.0 + index % 8, "0-100 risk index"),
            "pollen_daily": [metric(20.0 + index % 6, "0-100 risk index")],
        }
        for index in range(1, 91)
    ]
    return json.dumps(
        {
            "metadata": {
                "generated_at": "2026-09-02T00:00:00+08:00",
                "status": "ok",
                "provenance": OFFLINE_FIXTURE_PROVENANCE,
            },
            "current": {"status": "ok"},
            "forecast": {"status": "ok"},
            "routes": {"status": "ok", "count": len(items), "items": items},
        },
        ensure_ascii=False,
        indent=2,
    )


_OFFLINE_FILE_CONTENTS: dict[str, str] = {
    "Qwen-Harness/pyproject.toml": (
        "[project]\nname = \"generated-qwen-harness\"\nversion = \"0.1.0\"\n"
    ),
    "Qwen-Harness/README.md": (
        "# 离线生成夹具\n\n"
        "该源码树仅服务自动化测试，来源标记为 offline_fixture。\n"
    ),
    "Qwen-Harness/launch-local.ps1": (
        "$sourceRoot = Split-Path -Parent $PSScriptRoot\n"
        "$webRoot = Join-Path $sourceRoot 'xuhui_route_builder/web'\n"
        "python -m http.server 8130 --directory $webRoot\n"
    ),
    "Qwen-Harness/tests/test_smoke.py": (
        "def test_offline_fixture_marker():\n"
        "    assert 'offline_fixture'.startswith('offline')\n"
    ),
    "Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py": (
        "# offline_fixture marker; online generation must implement the scoring bridge\n"
    ),
    "weather_api_data/environment_api.py": (
        "def get_environment():\n"
        "    return {'pm2.5': 18, 'aqi': 42, 'provenance': 'offline_fixture'}\n"
    ),
    "weather_api_data/pyproject.toml": (
        "[project]\nname = \"generated-weather-api-data\"\nversion = \"0.1.0\"\n"
    ),
    "weather_api_data/tests/test_environment.py": (
        "from weather_api_data.environment_api import get_environment\n\n"
        "def test_environment_fields():\n"
        "    assert 'aqi' in get_environment()\n"
    ),
    "evaluation_model_qwen/api.py": (
        "HEALTH_PATH = '/health'\n"
        "RECOMMENDATION_PATH = '/api/v1/recommendations'\n\n"
        "def score_candidates(routes):\n"
        "    return [{'route_id': route['route_id'], 'score': 85} for route in routes]\n"
    ),
    "evaluation_model_qwen/pyproject.toml": (
        "[project]\nname = \"generated-evaluation-model-qwen\"\nversion = \"0.1.0\"\n"
    ),
    "evaluation_model_qwen/config/default_weights.json": json.dumps(
        {
            "goal_weights": {},
            "environment_weights": {},
            "risk_thresholds": {},
            "status_reliability": {},
        },
        ensure_ascii=False,
        indent=2,
    ),
    "evaluation_model_qwen/tests/test_api.py": (
        "from evaluation_model_qwen.api import HEALTH_PATH\n\n"
        "def test_health_path():\n"
        "    assert HEALTH_PATH == '/health'\n"
    ),
    "xuhui_route_builder/route_generator.py": (
        "def generate_routes(route_catalog):\n"
        "    return route_catalog['routes']\n"
    ),
    "xuhui_route_builder/pyproject.toml": (
        "[project]\nname = \"generated-xuhui-route-builder\"\nversion = \"0.1.0\"\n"
    ),
    "xuhui_route_builder/data/web/route_catalog.json": _fixture_routes(),
    "xuhui_route_builder/data/web/xuhui_routes.geojson": _fixture_route_geojson(),
    "xuhui_route_builder/data/web/environment_dashboard.json": _fixture_environment_dashboard(),
    "xuhui_route_builder/web/index.html": (
        "<!doctype html><html><body>\n"
        "<main id='map'></main><select id='route-select'></select>\n"
        "<button id='filter'>筛选</button><button id='qwen'>千问</button>\n"
        "<script src='app.js'></script></body></html>\n"
    ),
    "xuhui_route_builder/web/app.js": (
        "const map = document.querySelector('#map');\n"
        "document.querySelector('#route-select').addEventListener('change', () => {\n"
        "  map.dataset.route = 'selected';\n"
        "});\n"
        "document.querySelector('#filter').addEventListener('click', () => {});\n"
        "document.querySelector('#qwen').addEventListener('click', () => {});\n"
    ),
    "xuhui_route_builder/tests/test_routes.py": (
        "from xuhui_route_builder.route_generator import generate_routes\n\n"
        "def test_generate_routes():\n"
        "    assert generate_routes({'routes': []}) == []\n"
    ),
}


def _offline_architecture() -> ArchitecturePlan:
    return ArchitecturePlan(
        summary="测试专用离线四模块工程",
        technology_choices=["Python 3.10", "原生 HTML/CSS/JavaScript"],
        integration_contracts=[
            "weather_api_data 提供环境字段",
            "evaluation_model_qwen 提供评价与健康端点",
            "xuhui_route_builder 提供 90 条路线和地图网页",
        ],
        files=[
            FilePlan(
                path=path,
                purpose="离线功能契约夹具",
                acceptance_criteria=["保留 offline_fixture 来源标记"],
            )
            for path in _OFFLINE_FILE_CONTENTS
        ],
    )


class OfflineFixtureModelClient:
    """固定结构化响应客户端，仅供离线测试复现。"""

    model = "offline-fixture"

    def generate_structured(self, **kwargs: Any) -> tuple[BaseModel, ModelCallAudit]:
        output_model = kwargs["output_model"]
        if output_model is ArchitecturePlan:
            response: BaseModel = _offline_architecture()
        elif output_model is GeneratedFile:
            target = kwargs["user_payload"].get("target_file")
            path = target.get("path") if isinstance(target, dict) else None
            if not isinstance(path, str) or path not in _OFFLINE_FILE_CONTENTS:
                raise InputContractError(f"离线 fixture 未注册生成文件: {path!r}")
            response = GeneratedFile(path=path, content=_OFFLINE_FILE_CONTENTS[path])
        elif output_model is RepairBatch:
            raise InputContractError("离线 fixture 未通过固定功能契约，需修正 fixture 本身")
        else:
            raise InputContractError(f"离线 fixture 不支持输出类型: {output_model}")
        return response, ModelCallAudit(
            stage=str(kwargs["stage_name"]),
            model=self.model,
            created_at=datetime.now(timezone.utc),
            prompt_version=str(kwargs["prompt_version"]),
        )


def _load_generation_skills(context: "WorkflowContext") -> tuple[list[Any], list[str]]:
    requested = list(getattr(context.stage_spec, "required_skills", ()) or CORE_SKILLS)
    discovered = context.skills.discover()
    skills = [discovered[name] for name in requested if name in discovered]
    missing = [name for name in requested if name not in discovered]
    return skills, missing


def build_generation_requirements(context: "WorkflowContext", skills: Sequence[Any]) -> str:
    """把研究目标、实验设计与 Skill 摘要固化为生成需求。"""
    experiment_design = context.read_stage_output("experiment_design")
    if not isinstance(experiment_design, dict):
        raise InputContractError(
            "experiment_design 阶段输出缺失",
            stage=getattr(context.stage_spec, "name", "project_generation"),
            run_id=context.run_id,
            suggested_action="先完成 experiment_design 阶段",
        )
    goal_dump = getattr(context.goal, "model_dump", None)
    goal = goal_dump(mode="json") if callable(goal_dump) else context.goal
    if not isinstance(goal, dict):
        goal = {"title": str(goal)}

    def compact_text(value: Any, limit: int = 240) -> str:
        text = str(value).strip()
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def compact_list(value: Any, *, limit: int = 12) -> list[str]:
        if not isinstance(value, list):
            return []
        return [compact_text(item) for item in value[:limit]]

    def select_records(value: Any, keys: tuple[str, ...], *, limit: int = 12) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        selected: list[dict[str, Any]] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            record: dict[str, Any] = {}
            for key in keys:
                field = item.get(key)
                if field is None:
                    continue
                if isinstance(field, str):
                    record[key] = compact_text(field)
                elif isinstance(field, list):
                    record[key] = [compact_text(entry, 80) for entry in field[:8]]
                elif isinstance(field, (int, float, bool)):
                    record[key] = field
            selected.append(record)
        return selected

    compact_goal: dict[str, Any] = {
        key: compact_text(goal[key])
        for key in ("title", "question", "domain")
        if goal.get(key) is not None
    }
    compact_goal["constraints"] = compact_list(goal.get("constraints"), limit=12)
    compact_experiment = {
        "hypothesis_id": compact_text(experiment_design.get("hypothesis_id", "")),
        "profiles": select_records(
            experiment_design.get("profiles"),
            (
                "profile_id",
                "case_id",
                "route_mode",
                "goal",
                "target_distance_m",
                "sensitivities",
                "interests",
            ),
        ),
        "baselines": select_records(
            experiment_design.get("baselines"), ("baseline_id", "name")
        ),
        "variants": compact_list(experiment_design.get("variants"), limit=12),
        "metrics": select_records(
            experiment_design.get("metrics"),
            ("metric_id", "name", "direction", "primary"),
        ),
        "detour_limit": experiment_design.get("detour_limit"),
        "target_distance_tolerance": experiment_design.get("target_distance_tolerance"),
        "module_operations": select_records(
            experiment_design.get("module_operations"), ("operation_id", "module")
        ),
        "acceptance_criteria": compact_list(
            experiment_design.get("acceptance_criteria"), limit=12
        ),
        "stop_conditions": compact_list(experiment_design.get("stop_conditions"), limit=8),
    }
    payload = {
        "goal": compact_goal,
        "experiment_design": compact_experiment,
        "skills": [str(getattr(skill, "name", "")) for skill in skills],
        "delivery_contract": {
            "required_projects": [
                "Qwen-Harness",
                "evaluation_model_qwen",
                "weather_api_data",
                "xuhui_route_builder",
            ],
            "minimum_functional_score": 85,
            "route_count": 90,
            "deliverables": ["完整源码", "地图网页", "本地启动", "测试"],
            "required_files": [
                "Qwen-Harness/launch-local.ps1",
                "Qwen-Harness/src/qwen_harness/__init__.py",
                "Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py",
                "evaluation_model_qwen/pyproject.toml",
                "evaluation_model_qwen/src/evaluation_model_qwen/__init__.py",
                "evaluation_model_qwen/config/default_weights.json",
                "weather_api_data/src/weather_api_data/__init__.py",
                "xuhui_route_builder/pyproject.toml",
                "xuhui_route_builder/src/xuhui_route_builder/__init__.py",
                "xuhui_route_builder/data/web/route_catalog.json",
                "xuhui_route_builder/data/web/xuhui_routes.geojson",
                "xuhui_route_builder/data/web/environment_dashboard.json",
                "xuhui_route_builder/web/index.html",
                "xuhui_route_builder/web/src/main.js",
                "xuhui_route_builder/web/styles/main.css",
                "xuhui_route_builder/tests/visual_contract.test.mjs",
            ],
            "route_data_contract": (
                "route_catalog.json 顶层为 90 项数组；walk/run/bike 各 30；每项含 "
                "route_id、route_name、route_mode、validation_status、geometry_status；"
                "xuhui_routes.geojson 为 90 项 FeatureCollection 且 route_id 一致"
            ),
            "environment_data_contract": (
                "environment_dashboard.json 含 metadata/current/forecast/routes；"
                "routes.items 为 90 项并逐项含 route_id、pm2_5、noise、pollen_daily"
            ),
            "evaluation_python_contract": (
                "evaluation_model_qwen 提供 loaders.load_data、models 中 RiskAssessment/"
                "ScoredRoute/StrictModel/UserProfile、scoring.evaluate_risk/score_routes、"
                "service.evaluation_root/load_weights；API 提供 /api/v1/health 与 "
                "/api/v1/recommendations"
            ),
            "web_contract": (
                "本地地图从 data/web 读取本轮 90 条路线和环境数据，支持路线切换、"
                "筛选、千问推荐入口，并可由 launch-local.ps1 启动；参考在线产品 "
                "https://zion-johnson99.github.io/AI_Scientist_shanghai_route/ 的信息层级与"
                "地图工作台布局，不复制其源码或资源；同一页面适配 1440x900 与 390x844，"
                "地图、路线工作台和关键操作在首屏真实可见且无横向溢出；固定测试接口为 "
                "data-testid=map、data-testid=route-workbench、data-testid=route-card、"
                "data-testid=mode-filter、data-testid=environment-details、"
                "data-testid=recommendation-button；初始显示 90 条路线，walk/run/bike 筛选"
                "各显示 30 条；选择路线后 environment-details 在当前视口可见，展示 "
                "PM2.5、噪声、花粉及数据状态或业务时间；地图需加载真实底图或明确的本地"
                "矢量底图，并通过 map 的 data-selected-route-id 暴露所选路线高亮状态"
            ),
        },
    }
    return "请从空源码工作区生成完整工程。结构化需求如下：\n" + json.dumps(
        payload, ensure_ascii=False, indent=2, default=str
    )


def repair_generated_runtime_issue(
    context: "WorkflowContext", issue: ValidationIssue, *, repair_round: int = 1
) -> GeneratedFile:
    """根据真实命令错误，让千问定向修复当前 run 的生成文件。"""
    if context.options.offline:
        raise ModelUnavailableError(
            "离线运行不调用千问修复生成源码",
            stage="module_execution",
            run_id=context.run_id,
        )
    if context.model_client is None or context.prompts is None:
        raise ModelUnavailableError(
            "运行时修复缺少千问模型客户端或 PromptBuilder",
            stage="module_execution",
            run_id=context.run_id,
        )
    discovered = context.skills.discover()
    skills = [discovered[name] for name in CORE_SKILLS if name in discovered]
    requirements = build_generation_requirements(context, skills)
    engine = GenerationEngine(
        workspace=GenerationWorkspace(context.run_dir),
        model_client=context.model_client,
        prompts=context.prompts,
        max_parallel_files=1,
    )
    generated, audit = engine.repair_issue(
        requirements,
        issue,
        skills=skills,
        repair_round=repair_round,
    )
    relative = "checks/runtime_repairs.json"
    audit_path = context.run_dir / relative
    history: dict[str, Any] = {"provenance": QWEN_PROVENANCE, "repairs": []}
    if audit_path.is_file():
        try:
            loaded = json.loads(audit_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("repairs"), list):
                history = loaded
        except (OSError, json.JSONDecodeError):
            pass
    history["repairs"].append(
        {
            "round": repair_round,
            "issue": issue.model_dump(mode="json"),
            "target_file": generated.path,
            "audit": audit.model_dump(mode="json"),
        }
    )
    context.store.write_json_atomic(relative, history)
    context.emit(
        "generated_runtime_repaired",
        f"千问已修复生成文件 {generated.path}",
        status="ok",
        details={"check": issue.check, "repair_round": repair_round},
    )
    return generated


def _gate_result(report: FunctionalContractReport) -> GateResult:
    return GateResult(
        gate="generation_functional_contract",
        passed=report.passed,
        checks=[
            GateCheck(
                name=check.name,
                passed=check.passed,
                detail=f"{check.label}: {check.earned}/{check.weight}；{check.detail}",
            )
            for check in report.checks
        ],
        summary=f"功能契约得分 {report.score}/100，门槛 {report.threshold}",
    )


def stage_handler(context: "WorkflowContext") -> StageResult:
    """生成四模块源码，执行功能评分，并固化架构、检查与模型审计。"""
    stage_name = getattr(context.stage_spec, "name", "project_generation")
    skills, missing_skills = _load_generation_skills(context)
    requirements = build_generation_requirements(context, skills)
    offline = bool(context.options.offline)
    provenance = OFFLINE_FIXTURE_PROVENANCE if offline else QWEN_PROVENANCE
    model_client = OfflineFixtureModelClient() if offline else context.model_client
    if model_client is None:
        raise ModelUnavailableError(
            "工程生成阶段缺少千问模型客户端",
            stage=stage_name,
            run_id=context.run_id,
        )
    if context.prompts is None:
        raise ModelUnavailableError("工程生成阶段缺少 PromptBuilder", stage=stage_name, run_id=context.run_id)

    validator = FunctionalContractValidator(provenance=provenance)
    max_repairs = min(
        int(context.options.max_iterations),
        int(context.harness_config.runtime.max_iterations),
    )
    engine = GenerationEngine(
        workspace=GenerationWorkspace(context.run_dir),
        model_client=model_client,
        prompts=context.prompts,
        max_parallel_files=1 if offline else 4,
    )
    use_generated_builders = not offline and not isinstance(
        model_client, OfflineFixtureModelClient
    )

    def validate_generated_source(source_root: Path) -> list[ValidationIssue]:
        materialization_issues = (
            _materialize_generated_data(source_root) if use_generated_builders else []
        )
        return [*materialization_issues, *validator(source_root)]

    generation = engine.generate(
        requirements,
        skills=skills,
        validator=validate_generated_source,
        max_repair_rounds=max_repairs,
        reuse_existing=not offline,
        deferred_file_paths=_DEFERRED_DATA_PATHS if use_generated_builders else set(),
    )
    report = validator.last_report
    if report is None:
        raise InputContractError("工程生成验证器未产生功能契约报告", stage=stage_name, run_id=context.run_id)

    architecture_path = context.store.write_json_atomic(
        "workspace/architecture.json", generation.architecture.model_dump(mode="json")
    )
    generation_path = context.store.write_json_atomic(
        "workspace/generation_result.json", generation.model_dump(mode="json")
    )
    checks_path = context.store.write_json_atomic(
        "checks/generation_contract.json", report.model_dump(mode="json")
    )
    audits_path = context.store.write_json_atomic(
        f"stages/{stage_name}/model_audits.json",
        {
            "provenance": provenance,
            "audits": [audit.model_dump(mode="json") for audit in generation.model_audits],
        },
    )
    artifacts = [
        architecture_path.relative_to(context.run_dir).as_posix(),
        generation_path.relative_to(context.run_dir).as_posix(),
        checks_path.relative_to(context.run_dir).as_posix(),
        audits_path.relative_to(context.run_dir).as_posix(),
    ]
    warnings = [f"缺少生成阶段 Skill: {', '.join(missing_skills)}"] if missing_skills else []
    if offline:
        warnings.append("offline_fixture 仅服务自动化测试，不代表千问在线生成结果")
    gate = _gate_result(report)
    context.emit(
        "generation_contract_scored",
        f"生成工程功能契约得分 {report.score}/100",
        status="ok" if report.passed else "failed",
        details={"score": report.score, "provenance": provenance},
    )
    return StageResult(
        stage=stage_name,
        status="passed" if report.passed else "failed",
        summary=f"生成工程功能契约得分 {report.score}/100",
        output={
            "provenance": provenance,
            "score": report.score,
            "threshold": report.threshold,
            "passed": report.passed,
            "repair_rounds": generation.repair_rounds,
            "remaining_issues": [issue.model_dump(mode="json") for issue in generation.remaining_issues],
            "architecture": "workspace/architecture.json",
            "generation_result": "workspace/generation_result.json",
            "checks": "checks/generation_contract.json",
            "model_audits": f"stages/{stage_name}/model_audits.json",
        },
        gate_result=gate,
        artifacts=artifacts,
        warnings=warnings,
        exit_code=None if report.passed else 1,
    )
