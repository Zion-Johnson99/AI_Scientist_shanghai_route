"""当前 run 生成四项目的可执行质量门禁。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from ..errors import InputContractError, ModuleCommandError, PathBoundaryError
from ..models import CommandAudit, StrictModel
from ..subprocess_runner import CommandSpec, SafeSubprocessRunner

QualityCategory = Literal["pytest", "ruff", "pyright", "node", "evaluation_api", "browser"]
QualityStatus = Literal["passed", "failed", "not_run"]

_PYTHON_PROJECTS: tuple[tuple[str, str], ...] = (
    ("Qwen-Harness", "Qwen-Harness"),
    ("evaluation_model_qwen", "evaluation_model_qwen"),
    ("weather_api_data", "weather_api_data"),
)
_ALL_PROJECTS: tuple[str, ...] = (
    "Qwen-Harness",
    "evaluation_model_qwen",
    "weather_api_data",
    "xuhui_route_builder",
)

_API_HEALTH_SCRIPT = (
    "from fastapi.testclient import TestClient; "
    "from evaluation_model_qwen.api import app; "
    "response=TestClient(app).get('/api/v1/health'); "
    "assert response.status_code == 200, response.text; "
    "payload=response.json(); "
    "assert payload.get('status') in {'ok', 'healthy'}, payload"
)


class GeneratedQualityCheck(StrictModel):
    """单项生成工程质量检查及可追溯命令记录。"""

    name: str
    category: QualityCategory
    status: QualityStatus
    passed: bool
    required: bool = True
    command: list[str] | None = None
    cwd: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    stdout_path: str | None = None
    stderr_path: str | None = None
    error: str | None = None


class GeneratedQualityReport(StrictModel):
    """生成工程的整体门禁结果。"""

    source_root: str
    passed: bool
    checks: list[GeneratedQualityCheck] = Field(default_factory=list)
    report_path: str


class _CommandRunner(Protocol):
    def run(self, spec: CommandSpec, run_store: object | None = None) -> CommandAudit: ...


BrowserCheck = Callable[[Path], GeneratedQualityCheck]

_PLAYWRIGHT_VERSION = "1.55.0"
_REFERENCE_PRODUCT_URL = "https://zion-johnson99.github.io/AI_Scientist_shanghai_route/"


def run_generated_quality_checks(
    context: Any,
    *,
    runner: _CommandRunner | None = None,
    browser_check: BrowserCheck | None = None,
) -> GeneratedQualityReport:
    """检查当前 run 的生成源码，并保存 ``checks/generated_quality.json``。

    pytest、Ruff 与 Pyright 使用主 Harness 锁定的 dev 工具链。评价 API
    健康检查使用生成评价项目的锁定运行环境，因此同时验证包构建、
    路由注册与实际响应。在线运行默认执行主 Harness 自带的真实浏览器门禁；
    测试可注入 browser_check 隔离浏览器进程。
    """
    run_dir = Path(context.run_dir).resolve()
    harness_root = Path(context.harness_root).resolve()
    source_root = (run_dir / "workspace" / "source").resolve()
    _validate_roots(run_dir, harness_root, source_root)

    command_runner = runner or SafeSubprocessRunner(
        Path(context.paths.repo_root), Path(context.paths.runtime_root)
    )
    checks: list[GeneratedQualityCheck] = []

    for label, project in _PYTHON_PROJECTS:
        project_root = source_root / project
        tests_root = project_root / "tests"
        check_name = f"pytest:{label}"
        if not any(tests_root.rglob("test_*.py")):
            checks.append(
                _local_failure(
                    name=check_name,
                    category="pytest",
                    error=f"{project}/tests 缺少 test_*.py",
                )
            )
            continue
        checks.append(
            _run_check(
                command_runner,
                context.store,
                name=check_name,
                category="pytest",
                spec=CommandSpec(
                    command_id=f"generated.pytest.{project.lower().replace('_', '-')}",
                    argv=[
                        "uv",
                        "run",
                        "--directory",
                        str(project_root),
                        "--frozen",
                        "--extra",
                        "dev",
                        "pytest",
                        "-q",
                    ],
                    cwd=project_root,
                ),
            )
        )

    for project in _ALL_PROJECTS:
        project_root = source_root / project
        command_label = project.lower().replace("_", "-")
        quality_tools: tuple[tuple[QualityCategory, str, list[str]], ...] = (
            ("ruff", "ruff", ["check", "."]),
            ("pyright", "pyright", []),
        )
        for category, tool, arguments in quality_tools:
            checks.append(
                _run_check(
                    command_runner,
                    context.store,
                    name=f"{tool}:{project}",
                    category=category,
                    spec=CommandSpec(
                        command_id=f"generated.{tool}.{command_label}",
                        argv=[
                            "uv",
                            "run",
                            "--directory",
                            str(project_root),
                            "--frozen",
                            "--extra",
                            "dev",
                            tool,
                            *arguments,
                        ],
                        cwd=project_root,
                    ),
                )
            )

    node_tests = sorted(
        (source_root / "xuhui_route_builder" / "tests").glob("*.test.mjs")
    )
    if node_tests:
        checks.append(
            _run_check(
                command_runner,
                context.store,
                name="Node 契约测试",
                category="node",
                spec=CommandSpec(
                    command_id="generated.node_contract",
                    argv=["node", "--test", *[_relative(source_root, path) for path in node_tests]],
                    cwd=source_root,
                ),
            )
        )
    else:
        checks.append(
            _local_failure(
                name="Node 契约测试",
                category="node",
                error="xuhui_route_builder/tests 缺少 *.test.mjs",
            )
        )

    evaluation_root = source_root / "evaluation_model_qwen"
    checks.append(
        _run_check(
            command_runner,
            context.store,
            name="评价 API 健康检查",
            category="evaluation_api",
            spec=CommandSpec(
                command_id="generated.evaluation_api_health",
                argv=[
                    "uv",
                    "run",
                    "--project",
                    ".",
                    "--frozen",
                    "python",
                    "-c",
                    _API_HEALTH_SCRIPT,
                ],
                cwd=evaluation_root,
            ),
        )
    )

    if browser_check is None:
        checks.append(run_generated_browser_check(context, runner=command_runner))
    else:
        browser_result = browser_check(source_root)
        if browser_result.category != "browser":
            raise InputContractError("browser_check 需返回 category=browser 的检查结果")
        checks.append(browser_result)

    passed = all(check.passed for check in checks if check.required)
    report_path = run_dir / "checks" / "generated_quality.json"
    report = GeneratedQualityReport(
        source_root=str(source_root),
        passed=passed,
        checks=checks,
        report_path=str(report_path),
    )
    _write_report(context, report)
    return report


def run_generated_browser_check(
    context: Any, *, runner: _CommandRunner | None = None
) -> GeneratedQualityCheck:
    """运行强制真实浏览器门禁，并把截图及结构化证据写入当前 run。"""
    run_dir = Path(context.run_dir).resolve()
    harness_root = Path(context.harness_root).resolve()
    source_root = (run_dir / "workspace" / "source").resolve()
    _validate_roots(run_dir, harness_root, source_root)
    browser_script = harness_root / "scripts" / "generated_browser_gate.py"
    if not browser_script.is_file():
        return _local_failure(
            name="真实浏览器验收",
            category="browser",
            error=f"浏览器门禁脚本缺失: {browser_script}",
        )
    command_runner = runner or SafeSubprocessRunner(
        Path(context.paths.repo_root), Path(context.paths.runtime_root)
    )
    browser_output = run_dir / "checks" / "browser"
    return _run_check(
        command_runner,
        context.store,
        name="真实浏览器验收",
        category="browser",
        spec=CommandSpec(
            command_id="generated.browser_gate",
            argv=[
                "uv",
                "run",
                "--with",
                f"playwright=={_PLAYWRIGHT_VERSION}",
                "python",
                str(browser_script),
                "--source-root",
                str(source_root),
                "--output-dir",
                str(browser_output),
                "--reference-url",
                _REFERENCE_PRODUCT_URL,
            ],
            cwd=source_root / "xuhui_route_builder",
            timeout_seconds=180,
            writes=[browser_output],
        ),
    )


def _validate_roots(run_dir: Path, harness_root: Path, source_root: Path) -> None:
    try:
        source_root.relative_to(run_dir)
    except ValueError as exc:
        raise PathBoundaryError(
            f"workspace/source 解析后越出当前 run: {source_root}",
            details={"run_dir": str(run_dir), "source_root": str(source_root)},
        ) from exc
    if not source_root.is_dir():
        raise InputContractError(f"生成源码目录缺失: {source_root}")
    missing = [project for project in _ALL_PROJECTS if not (source_root / project).is_dir()]
    if missing:
        raise InputContractError(
            "生成源码缺少规定项目目录",
            details={"missing_projects": missing, "source_root": str(source_root)},
        )
    if not (harness_root / "pyproject.toml").is_file():
        raise InputContractError(f"主 Harness 工具链配置缺失: {harness_root / 'pyproject.toml'}")


def _relative(source_root: Path, path: Path) -> str:
    return path.resolve().relative_to(source_root).as_posix()


def _run_check(
    runner: _CommandRunner,
    run_store: object,
    *,
    name: str,
    category: QualityCategory,
    spec: CommandSpec,
) -> GeneratedQualityCheck:
    try:
        audit = runner.run(spec, run_store=run_store)
    except ModuleCommandError as exc:
        details = exc.details
        return GeneratedQualityCheck(
            name=name,
            category=category,
            status="failed",
            passed=False,
            command=_string_list(details.get("argv")) or list(spec.argv),
            cwd=str(spec.cwd.resolve()),
            exit_code=_optional_int(details.get("exit_code")),
            timed_out=bool(details.get("timed_out", False)),
            stdout_path=_optional_str(details.get("stdout_path")),
            stderr_path=_optional_str(details.get("stderr_path")),
            error=exc.message,
        )
    return GeneratedQualityCheck(
        name=name,
        category=category,
        status="passed",
        passed=True,
        command=list(audit.argv),
        cwd=audit.cwd,
        exit_code=audit.exit_code,
        timed_out=audit.timeout,
        stdout_path=audit.stdout_path,
        stderr_path=audit.stderr_path,
    )


def _local_failure(
    *, name: str, category: QualityCategory, error: str
) -> GeneratedQualityCheck:
    return GeneratedQualityCheck(
        name=name,
        category=category,
        status="failed",
        passed=False,
        error=error,
    )


def _write_report(context: Any, report: GeneratedQualityReport) -> None:
    payload = report.model_dump(mode="json")
    writer = getattr(context.store, "write_json_atomic", None)
    if callable(writer):
        writer("checks/generated_quality.json", payload)
        return
    target = Path(report.report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "BrowserCheck",
    "GeneratedQualityCheck",
    "GeneratedQualityReport",
    "run_generated_browser_check",
    "run_generated_quality_checks",
]
