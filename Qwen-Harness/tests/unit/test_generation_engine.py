from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import sleep
from typing import Any, Sequence, cast

import pytest
from pydantic import BaseModel

from qwen_harness.errors import InputContractError, PathBoundaryError
from qwen_harness.generation import (
    ArchitecturePlan,
    FilePlan,
    GeneratedFile,
    GenerationEngine,
    GenerationWorkspace,
    ValidationIssue,
)
from qwen_harness.llm.prompts import PromptBuilder
from qwen_harness.models import ModelCallAudit, RunOptions
from qwen_harness.workflow.engine import WorkflowEngine


class SequenceModelClient:
    """按测试给定顺序返回结构化响应，不访问网络。"""

    model = "offline-sequence"

    def __init__(self, responses: Sequence[BaseModel]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any) -> tuple[BaseModel, ModelCallAudit]:
        response = self.responses.popleft()
        output_model = kwargs["output_model"]
        assert isinstance(response, output_model)
        self.calls.append(kwargs)
        return response, ModelCallAudit(
            stage=kwargs["stage_name"],
            model=self.model,
            created_at=datetime.now(timezone.utc),
            prompt_version=kwargs["prompt_version"],
        )


def _plan() -> ArchitecturePlan:
    return ArchitecturePlan(
        summary="四模块最小可运行工程",
        technology_choices=["Python 3.10", "原生 HTML/CSS/JavaScript"],
        integration_contracts=["网页从 data/web/route_catalog.json 读取路线"],
        files=[
            FilePlan(
                path="Qwen-Harness/README.md",
                purpose="说明生成工程",
                acceptance_criteria=["包含启动步骤"],
            ),
            FilePlan(
                path="evaluation_model_qwen/app.py",
                purpose="提供评价 API",
                acceptance_criteria=["暴露健康评分入口"],
            ),
            FilePlan(
                path="weather_api_data/provider.py",
                purpose="提供环境数据",
                acceptance_criteria=["返回结构化环境记录"],
            ),
            FilePlan(
                path="xuhui_route_builder/web/index.html",
                purpose="提供地图页面",
                acceptance_criteria=["可本地打开"],
            ),
        ],
    )


def _generated_files() -> list[GeneratedFile]:
    return [
        GeneratedFile(path=item.path, content=f"generated: {item.path}\n") for item in _plan().files
    ]


def test_architecture_plan_rejects_more_than_64_files() -> None:
    files = [
        FilePlan(
            path=f"{root}/file-{index}.txt",
            purpose="生成必要工程文件",
            acceptance_criteria=["文件可读"],
        )
        for index in range(17)
        for root in (
            "Qwen-Harness",
            "evaluation_model_qwen",
            "weather_api_data",
            "xuhui_route_builder",
        )
    ]

    with pytest.raises(ValueError, match="64"):
        ArchitecturePlan(
            summary="过度拆分的架构",
            technology_choices=["Python"],
            integration_contracts=["统一 JSON 契约"],
            files=files,
        )


def test_engine_generates_independent_files_in_parallel(tmp_path: Path) -> None:
    plan = _plan()

    class ParallelClient:
        model = "parallel-test"

        def __init__(self) -> None:
            self.lock = Lock()
            self.active = 0
            self.max_active = 0

        def generate_structured(self, **kwargs: Any) -> tuple[BaseModel, ModelCallAudit]:
            if kwargs["stage_name"] == "generation_architecture":
                response: BaseModel = plan
            else:
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                sleep(0.05)
                target = kwargs["user_payload"]["target_file"]
                response = GeneratedFile(path=target["path"], content="generated\n")
                with self.lock:
                    self.active -= 1
            return response, ModelCallAudit(
                stage=kwargs["stage_name"],
                model=self.model,
                created_at=datetime.now(timezone.utc),
                prompt_version=kwargs["prompt_version"],
            )

    client = ParallelClient()
    engine = GenerationEngine(
        workspace=GenerationWorkspace(tmp_path / "run-parallel"),
        model_client=client,
        prompts=PromptBuilder(),
        max_parallel_files=4,
    )

    result = engine.generate("生成完整工程")

    assert client.max_active >= 2
    assert result.written_files == [item.path for item in plan.files]
    assert all((engine.workspace.source_root / item.path).is_file() for item in plan.files)


def test_engine_reuses_cached_plan_existing_files_and_defers_large_data(tmp_path: Path) -> None:
    plan = _plan()
    run_dir = tmp_path / "run-resume"
    workspace = GenerationWorkspace(run_dir)
    workspace.initialize()
    architecture_path = run_dir / "workspace" / "architecture.json"
    architecture_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    workspace.write_text(plan.files[0].path, "existing\n")
    deferred_path = plan.files[-1].path
    responses = [GeneratedFile(path=item.path, content="resumed\n") for item in plan.files[1:-1]]
    client = SequenceModelClient(responses)
    engine = GenerationEngine(
        workspace=workspace,
        model_client=client,
        prompts=PromptBuilder(),
        max_parallel_files=1,
    )

    result = engine.generate(
        "续跑完整工程",
        reuse_existing=True,
        deferred_file_paths={deferred_path},
    )

    assert [call["stage_name"] for call in client.calls] == [
        "generation_file",
        "generation_file",
    ]
    assert result.architecture == plan
    assert result.written_files == [item.path for item in plan.files[:-1]]
    assert not (workspace.source_root / deferred_path).exists()


def test_cached_resume_can_enter_repair_loop(tmp_path: Path) -> None:
    plan = _plan()
    run_dir = tmp_path / "run-cached-repair"
    workspace = GenerationWorkspace(run_dir)
    workspace.initialize()
    (run_dir / "workspace" / "architecture.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    for item in plan.files:
        workspace.write_text(item.path, "existing\n")
    validation_round = 0

    def validator(_source_root: Path) -> list[ValidationIssue]:
        nonlocal validation_round
        validation_round += 1
        if validation_round == 1:
            return [
                ValidationIssue(
                    check="launcher",
                    summary="启动脚本需要修复",
                    files=[plan.files[0].path],
                )
            ]
        return []

    repair = GeneratedFile(path=plan.files[0].path, content="repaired\n")
    engine = GenerationEngine(
        workspace=workspace,
        model_client=SequenceModelClient([repair]),
        prompts=PromptBuilder(),
    )

    result = engine.generate(
        "续跑并修复工程",
        validator=validator,
        max_repair_rounds=1,
        reuse_existing=True,
    )

    assert result.remaining_issues == []
    assert result.repair_rounds == 1
    assert workspace.read_text(plan.files[0].path) == "repaired\n"


def test_engine_repairs_each_validation_issue_with_a_separate_call(tmp_path: Path) -> None:
    plan = _plan()
    first = ValidationIssue(
        check="environment",
        summary="环境契约",
        files=[plan.files[2].path],
    )
    second = ValidationIssue(
        check="launcher",
        summary="启动契约",
        files=[plan.files[0].path],
    )
    validation_round = 0

    def validator(_source_root: Path) -> list[ValidationIssue]:
        nonlocal validation_round
        validation_round += 1
        return [first, second] if validation_round == 1 else []

    repairs = [
        GeneratedFile(path=plan.files[2].path, content="environment-fixed\n"),
        GeneratedFile(path=plan.files[0].path, content="launcher-fixed\n"),
    ]
    client = SequenceModelClient([plan, *_generated_files(), *repairs])
    engine = GenerationEngine(
        workspace=GenerationWorkspace(tmp_path / "run-separated-repair"),
        model_client=client,
        prompts=PromptBuilder(),
        max_parallel_files=1,
    )

    result = engine.generate(
        "分问题修复",
        validator=validator,
        max_repair_rounds=1,
    )

    repair_calls = [call for call in client.calls if call["stage_name"] == "generation_repair"]
    assert len(repair_calls) == 2
    assert all("validation_issue" in call["user_payload"] for call in repair_calls)
    assert result.remaining_issues == []


def test_repair_context_caps_large_affected_files(tmp_path: Path) -> None:
    workspace = GenerationWorkspace(tmp_path / "run-large-repair")
    workspace.initialize()
    target = "weather_api_data/large.json"
    workspace.write_text(target, "x" * 50_000)
    engine = GenerationEngine(
        workspace=workspace,
        model_client=SequenceModelClient([]),
        prompts=PromptBuilder(),
    )

    contents = engine._affected_contents(
        [ValidationIssue(check="large", summary="大文件", files=[target])],
        [target],
    )

    assert len(contents[target]) <= 6_100
    assert contents[target].endswith("\n...内容已截断")


def test_repair_context_prefers_production_source_over_data_and_tests(tmp_path: Path) -> None:
    workspace = GenerationWorkspace(tmp_path / "run-repair-selection")
    workspace.initialize()
    paths = [
        "weather_api_data/data/dashboard.json",
        "weather_api_data/tests/test_export.py",
        "weather_api_data/src/weather_api_data/web_export.py",
    ]
    for path in paths:
        workspace.write_text(path, path)
    engine = GenerationEngine(
        workspace=workspace,
        model_client=SequenceModelClient([]),
        prompts=PromptBuilder(),
    )

    contents = engine._affected_contents(
        [ValidationIssue(check="environment", summary="环境契约", files=paths)],
        paths,
    )

    assert list(contents) == ["weather_api_data/src/weather_api_data/web_export.py"]


def test_workspace_creates_required_projects_and_rejects_escape(tmp_path: Path) -> None:
    workspace = GenerationWorkspace(tmp_path / "run-001")

    workspace.initialize()

    assert {path.name for path in workspace.source_root.iterdir()} == {
        "Qwen-Harness",
        "evaluation_model_qwen",
        "weather_api_data",
        "xuhui_route_builder",
    }
    assert not any(path.is_file() for path in workspace.source_root.rglob("*"))
    for invalid in ("../outside.txt", str(tmp_path / "outside.txt"), "Qwen-Harness\\bad.py"):
        with pytest.raises(PathBoundaryError):
            workspace.write_text(invalid, "blocked")
    assert not (tmp_path / "outside.txt").exists()


def test_workspace_rejects_workspace_link_outside_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-link"
    outside = tmp_path / "outside-workspace"
    run_dir.mkdir()
    outside.mkdir()
    try:
        (run_dir / "workspace").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 配置不允许创建目录符号链接")

    with pytest.raises(PathBoundaryError, match="越出当前 run"):
        GenerationWorkspace(run_dir).initialize()

    assert not (outside / "source").exists()


def test_engine_plans_and_generates_each_file_with_injected_responses(tmp_path: Path) -> None:
    plan = _plan()
    client = SequenceModelClient([plan, *_generated_files()])
    engine = GenerationEngine(
        workspace=GenerationWorkspace(tmp_path / "run-002"),
        model_client=client,
        prompts=PromptBuilder(),
    )

    result = engine.generate("生成完整的徐汇健康路线工程")

    assert result.remaining_issues == []
    assert result.written_files == [item.path for item in plan.files]
    assert [call["stage_name"] for call in client.calls] == [
        "generation_architecture",
        "generation_file",
        "generation_file",
        "generation_file",
        "generation_file",
    ]
    for item in plan.files:
        assert (
            (engine.workspace.source_root / item.path)
            .read_text(encoding="utf-8")
            .startswith("generated:")
        )


def test_engine_rejects_generated_path_different_from_plan(tmp_path: Path) -> None:
    plan = _plan()
    responses: list[BaseModel] = [
        plan,
        GeneratedFile(path="Qwen-Harness/UNPLANNED.md", content="unexpected"),
    ]
    engine = GenerationEngine(
        workspace=GenerationWorkspace(tmp_path / "run-003"),
        model_client=SequenceModelClient(responses),
        prompts=PromptBuilder(),
    )

    with pytest.raises(InputContractError, match="与计划目标不一致"):
        engine.generate("生成完整工程")

    assert not (engine.workspace.source_root / "Qwen-Harness" / "UNPLANNED.md").exists()


def test_engine_repairs_validation_issues_until_validator_passes(tmp_path: Path) -> None:
    issue = ValidationIssue(
        check="pytest",
        summary="评价接口返回值错误",
        details="test_score 期望 85，实际 0",
        files=["evaluation_model_qwen/app.py"],
    )
    validation_round = 0

    def validator(_source_root: Path) -> list[ValidationIssue]:
        nonlocal validation_round
        validation_round += 1
        return [issue] if validation_round == 1 else []

    repair = GeneratedFile(path="evaluation_model_qwen/app.py", content="SCORE = 85\n")
    client = SequenceModelClient([_plan(), *_generated_files(), repair])
    engine = GenerationEngine(
        workspace=GenerationWorkspace(tmp_path / "run-004"),
        model_client=client,
        prompts=PromptBuilder(),
    )

    result = engine.generate("生成完整工程", validator=validator, max_repair_rounds=2)

    assert result.repair_rounds == 1
    assert result.remaining_issues == []
    assert (engine.workspace.source_root / "evaluation_model_qwen" / "app.py").read_text(
        encoding="utf-8"
    ) == "SCORE = 85\n"


def test_engine_returns_remaining_issues_after_repair_limit(tmp_path: Path) -> None:
    issue = ValidationIssue(check="browser", summary="地图页面仍缺少路线图层")
    repair = GeneratedFile(
        path="xuhui_route_builder/web/index.html",
        content="<main id='map'></main>\n",
    )
    client = SequenceModelClient([_plan(), *_generated_files(), repair])
    engine = GenerationEngine(
        workspace=GenerationWorkspace(tmp_path / "run-005"),
        model_client=client,
        prompts=PromptBuilder(),
    )

    result = engine.generate(
        "生成完整工程",
        validator=lambda _source_root: [issue],
        max_repair_rounds=1,
    )

    assert result.repair_rounds == 1
    assert result.remaining_issues == [issue]


def test_offline_workflow_still_builds_prompts_for_generation_fixture() -> None:
    workflow_engine = object.__new__(WorkflowEngine)
    cast(Any, workflow_engine).paths = type(
        "Paths", (), {"harness_root": Path(__file__).resolve().parents[2]}
    )()

    prompts = workflow_engine._build_prompts(RunOptions(offline=True))

    assert isinstance(prompts, PromptBuilder)
