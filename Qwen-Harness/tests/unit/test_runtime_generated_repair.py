from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from qwen_harness.errors import ModuleCommandError
from qwen_harness.generation.engine import GenerationEngine
from qwen_harness.generation.models import ValidationIssue
from qwen_harness.generation.quality import GeneratedQualityCheck, GeneratedQualityReport
from qwen_harness.generation.workspace import GenerationWorkspace
from qwen_harness.models import CommandAudit, ModuleOperation, ModuleResult
from qwen_harness.workflow import stages


def test_browser_quality_issue_targets_css_for_layout_failure(tmp_path: Path) -> None:
    stderr = tmp_path / "browser.stderr.log"
    stderr.write_text("AssertionError: mobile: 页面存在横向溢出 28px", encoding="utf-8")
    check = GeneratedQualityCheck(
        name="真实浏览器验收",
        category="browser",
        status="failed",
        passed=False,
        stderr_path=str(stderr),
        error="浏览器门禁失败",
    )

    issue = stages._browser_quality_issue(check, tmp_path)

    assert issue.files == ["xuhui_route_builder/web/styles/main.css"]
    assert "横向溢出" in issue.details


def test_browser_quality_issue_targets_main_js_for_environment_failure(tmp_path: Path) -> None:
    stderr = tmp_path / "browser.stderr.log"
    stderr.write_text("AssertionError: desktop: 环境详情缺少 PM2.5", encoding="utf-8")
    check = GeneratedQualityCheck(
        name="真实浏览器验收",
        category="browser",
        status="failed",
        passed=False,
        stderr_path=str(stderr),
        error="浏览器门禁失败",
    )

    issue = stages._browser_quality_issue(check, tmp_path)

    assert issue.files == ["xuhui_route_builder/web/src/main.js"]
    assert "环境详情" in issue.details

    stderr.write_text(
        "AssertionError: desktop: data-testid=route-card 未在 5 秒内出现",
        encoding="utf-8",
    )
    route_card_issue = stages._browser_quality_issue(check, tmp_path)
    assert route_card_issue.files == ["xuhui_route_builder/web/src/main.js"]


def test_failed_browser_gate_repairs_once_and_replaces_result(tmp_path: Path, monkeypatch) -> None:
    stderr = tmp_path / "browser.stderr.log"
    stderr.write_text("AssertionError: desktop: 环境详情缺少 PM2.5", encoding="utf-8")
    failed = GeneratedQualityCheck(
        name="真实浏览器验收",
        category="browser",
        status="failed",
        passed=False,
        stderr_path=str(stderr),
        error="浏览器门禁失败",
    )
    report = GeneratedQualityReport(
        source_root="workspace/source",
        passed=False,
        checks=[failed],
        report_path="checks/generated_quality.json",
    )
    repaired: list[str] = []
    saved: list[tuple[str, object]] = []

    monkeypatch.setattr(
        stages,
        "repair_generated_runtime_issue",
        lambda _context, issue, *, repair_round=1: repaired.append(issue.files[0]),
    )
    monkeypatch.setattr(
        stages,
        "run_generated_browser_check",
        lambda _context: GeneratedQualityCheck(
            name="真实浏览器验收",
            category="browser",
            status="passed",
            passed=True,
        ),
    )
    context = SimpleNamespace(
        run_dir=tmp_path,
        options=SimpleNamespace(offline=False),
        model_client=object(),
        emit=lambda *_args, **_kwargs: None,
        store=SimpleNamespace(write_json_atomic=lambda path, data: saved.append((path, data))),
    )

    updated = stages._repair_failed_browser_once(cast(Any, context), report)

    assert updated.passed is True
    assert updated.checks[0].passed is True
    assert repaired == ["xuhui_route_builder/web/src/main.js"]
    assert saved[0][0] == "checks/generated_quality.json"


def test_explicit_repair_file_wins_over_browser_heuristic() -> None:
    issue = ValidationIssue(
        check="browser_data_path",
        summary="网页数据路径错误",
        details="route_catalog.json 请求 404",
        files=["xuhui_route_builder/web/src/data-loader.js"],
    )

    target = GenerationEngine._repair_target(
        issue,
        [
            "xuhui_route_builder/web/index.html",
            "xuhui_route_builder/web/src/data-loader.js",
        ],
    )

    assert target == "xuhui_route_builder/web/src/data-loader.js"


def test_repair_context_keeps_head_and_tail_of_long_file(tmp_path: Path) -> None:
    workspace = GenerationWorkspace(tmp_path / "run")
    workspace.initialize()
    target = "xuhui_route_builder/web/src/main.js"
    workspace.write_text(target, "HEAD\n" + ("x" * 8_000) + "\nTAIL")
    engine = GenerationEngine(workspace=workspace, model_client=None, prompts=None)
    issue = ValidationIssue(
        check="browser_filter",
        summary="末尾筛选函数错误",
        details="修复文件末尾函数",
        files=[target],
    )

    content = engine._affected_contents([issue], [target])[target]

    assert "HEAD" in content
    assert "TAIL" in content


def _source_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "run" / "workspace" / "source"
    (source_root / "evaluation_model_qwen").mkdir(parents=True)
    (source_root / "evaluation_model_qwen" / "pyproject.toml").write_text(
        "[project]\nname = 'evaluation-model-qwen'\n",
        encoding="utf-8",
    )
    models = source_root / "evaluation_model_qwen" / "src" / "evaluation_model_qwen" / "models.py"
    models.parent.mkdir(parents=True)
    models.write_text("class UserProfile:\n    pass\n", encoding="utf-8")
    bridge = source_root / "Qwen-Harness" / "src" / "qwen_harness" / "adapters"
    bridge.mkdir(parents=True)
    (bridge / "evaluation_score_candidates.py").write_text(
        "def main():\n    pass\n", encoding="utf-8"
    )
    return source_root


def test_runtime_repair_target_maps_missing_readme_build_error_to_pyproject(tmp_path: Path) -> None:
    source_root = _source_root(tmp_path)

    target = stages._runtime_repair_target(
        module="evaluation",
        diagnostics="OSError: Readme file does not exist: README.md",
        source_root=source_root,
    )

    assert target == "evaluation_model_qwen/pyproject.toml"


def test_runtime_repair_target_maps_missing_import_symbol_to_defining_module(
    tmp_path: Path,
) -> None:
    source_root = _source_root(tmp_path)

    target = stages._runtime_repair_target(
        module="evaluation",
        diagnostics=(
            "ImportError: cannot import name 'EnvironmentRecord' "
            "from 'evaluation_model_qwen.models'"
        ),
        source_root=source_root,
    )

    assert target == "evaluation_model_qwen/src/evaluation_model_qwen/models.py"


def test_operation_retries_after_qwen_repairs_generated_file(tmp_path: Path, monkeypatch) -> None:
    source_root = _source_root(tmp_path)
    stderr_path = tmp_path / "run" / "commands" / "evaluation.stderr.log"
    stderr_path.parent.mkdir(parents=True)
    stderr_path.write_text(
        "OSError: Readme file does not exist: README.md",
        encoding="utf-8",
    )
    calls = 0
    repaired: list[tuple[str, str]] = []

    class Adapter:
        def execute(self, _operation, _context):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ModuleCommandError(
                    "generated package failed",
                    details={"stderr_path": str(stderr_path)},
                )
            return {"module": "evaluation", "status": "ok"}

    def fake_repair(_context, issue, *, repair_round=1):
        repaired.append((issue.check, issue.files[0]))
        return SimpleNamespace(model="qwen-test")

    monkeypatch.setattr(stages, "repair_generated_runtime_issue", fake_repair)
    context = SimpleNamespace(
        run_dir=tmp_path / "run",
        options=SimpleNamespace(offline=False, max_iterations=2),
        harness_config=SimpleNamespace(runtime=SimpleNamespace(max_iterations=2)),
        model_client=object(),
        emit=lambda *_args, **_kwargs: None,
    )
    operation = ModuleOperation(
        operation_id="evaluation.score_candidates",
        module="evaluation",
        parameters={},
        reason="test",
    )

    result = stages._execute_operation_with_runtime_repair(Adapter(), operation, cast(Any, context))

    assert result == {"module": "evaluation", "status": "ok"}
    assert calls == 2
    assert repaired == [
        ("runtime_evaluation_score_candidates", "evaluation_model_qwen/pyproject.toml")
    ]
    assert source_root.is_dir()


def test_operation_repairs_zero_exit_command_with_invalid_output(
    tmp_path: Path, monkeypatch
) -> None:
    _source_root(tmp_path)
    stdout_path = tmp_path / "run" / "commands" / "evaluation.stdout.log"
    stderr_path = tmp_path / "run" / "commands" / "evaluation.stderr.log"
    stdout_path.parent.mkdir(parents=True)
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    audit = CommandAudit(
        command_id="evaluation.score_candidates.case",
        argv=["python", "adapter.py"],
        cwd=str(tmp_path),
        started_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 2, 0, 0, 1, tzinfo=timezone.utc),
        exit_code=0,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        timeout=False,
    )
    responses = [
        ModuleResult(
            module="evaluation",
            status="error",
            commands=[audit],
            errors=["score-candidates 输出不是合法 JSON"],
        ),
        ModuleResult(module="evaluation", status="ok"),
    ]
    repaired: list[object] = []

    class Adapter:
        def execute(self, _operation, _context):
            return responses.pop(0)

    def fake_repair(_context, issue, *, repair_round=1):
        repaired.append(issue)
        return SimpleNamespace(path=issue.files[0])

    monkeypatch.setattr(stages, "repair_generated_runtime_issue", fake_repair)
    context = SimpleNamespace(
        run_dir=tmp_path / "run",
        options=SimpleNamespace(offline=False, max_iterations=2),
        harness_config=SimpleNamespace(runtime=SimpleNamespace(max_iterations=2)),
        model_client=object(),
        emit=lambda *_args, **_kwargs: None,
    )
    operation = ModuleOperation(
        operation_id="evaluation.score_candidates",
        module="evaluation",
        parameters={},
        reason="test",
    )

    result = stages._execute_operation_with_runtime_repair(Adapter(), operation, cast(Any, context))

    assert result.status == "ok"
    assert len(repaired) == 1
    issue = repaired[0]
    assert getattr(issue, "files") == [
        "Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py"
    ]
    assert "__main__" in getattr(issue, "details")
    assert "stdout 只输出一个 JSON 对象" in getattr(issue, "details")
