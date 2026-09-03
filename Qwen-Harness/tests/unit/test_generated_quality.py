from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qwen_harness.errors import ModuleCommandError
from qwen_harness.generation.quality import (
    GeneratedQualityCheck,
    GeneratedQualityReport,
    run_generated_quality_checks,
)
from qwen_harness.models import CommandAudit
from qwen_harness.workflow.stages import _generated_quality_gate


class FakeStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def write_json_atomic(self, relative: str, data: object) -> Path:
        target = self.run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target


class RecordingRunner:
    def __init__(self, *, failing_command: str | None = None) -> None:
        self.specs: list[Any] = []
        self.failing_command = failing_command

    def run(self, spec: Any, run_store: object | None = None) -> CommandAudit:
        self.specs.append(spec)
        now = datetime.now(timezone.utc)
        stdout_path = (
            Path(getattr(run_store, "run_dir")) / "commands" / f"{spec.command_id}.stdout.log"
        )
        stderr_path = (
            Path(getattr(run_store, "run_dir")) / "commands" / f"{spec.command_id}.stderr.log"
        )
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("ok\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if spec.command_id == self.failing_command:
            stderr_path.write_text("generated failure\n", encoding="utf-8")
            raise ModuleCommandError(
                "generated command failed",
                details={
                    "command_id": spec.command_id,
                    "argv": spec.argv,
                    "exit_code": 1,
                    "timed_out": False,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                },
            )
        return CommandAudit(
            command_id=spec.command_id,
            argv=spec.argv,
            cwd=str(spec.cwd),
            started_at=now,
            finished_at=now,
            exit_code=0,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            timeout=False,
        )


def _context(tmp_path: Path) -> SimpleNamespace:
    harness_root = tmp_path / "repo" / "Qwen-Harness"
    run_dir = harness_root / "runtime" / "runs" / "run-quality"
    source_root = run_dir / "workspace" / "source"
    for project in (
        "Qwen-Harness",
        "evaluation_model_qwen",
        "weather_api_data",
        "xuhui_route_builder",
    ):
        (source_root / project / "src").mkdir(parents=True)
        (source_root / project / "tests").mkdir()
    for project in ("Qwen-Harness", "evaluation_model_qwen", "weather_api_data"):
        (source_root / project / "tests" / "test_generated.py").write_text(
            "def test_generated(): assert True\n", encoding="utf-8"
        )
    route_tests = source_root / "xuhui_route_builder" / "tests"
    (route_tests / "data_contract.test.mjs").write_text(
        "import test from 'node:test'; test('ok', () => {});\n", encoding="utf-8"
    )
    (harness_root / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (harness_root / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0'\n", encoding="utf-8"
    )
    browser_script = harness_root / "scripts" / "generated_browser_gate.py"
    browser_script.parent.mkdir()
    browser_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    store = FakeStore(run_dir)
    return SimpleNamespace(
        run_dir=run_dir,
        harness_root=harness_root,
        store=store,
        paths=SimpleNamespace(repo_root=tmp_path / "repo", runtime_root=harness_root / "runtime"),
    )


def test_quality_checks_use_generated_boundary_and_record_all_required_gates(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    runner = RecordingRunner()

    report = run_generated_quality_checks(context, runner=runner)

    assert report.passed is True
    assert {check.category for check in report.checks if check.required} == {
        "pytest",
        "ruff",
        "pyright",
        "node",
        "evaluation_api",
        "browser",
    }
    assert report.checks[-1].category == "browser"
    assert report.checks[-1].status == "passed"
    assert report.checks[-1].passed is True
    assert report.checks[-1].required is True
    source_root = (context.run_dir / "workspace" / "source").resolve()
    assert all(Path(spec.cwd).resolve().is_relative_to(source_root) for spec in runner.specs)
    assert all(spec.argv[0] in {"uv", "node"} for spec in runner.specs)
    browser_spec = next(
        spec for spec in runner.specs if spec.command_id == "generated.browser_gate"
    )
    assert browser_spec.argv[:4] == ["uv", "run", "--with", "playwright==1.55.0"]
    assert "--source-root" in browser_spec.argv
    assert "--output-dir" in browser_spec.argv
    static_specs = [
        spec
        for spec in runner.specs
        if spec.command_id.startswith(("generated.ruff.", "generated.pyright."))
    ]
    assert len(static_specs) == 8
    assert all("--directory" in spec.argv for spec in static_specs)
    saved = json.loads(
        (context.run_dir / "checks" / "generated_quality.json").read_text(encoding="utf-8")
    )
    assert saved["passed"] is True
    assert saved["source_root"] == str(source_root)


def test_quality_checks_keep_running_and_expose_failed_command_logs(tmp_path: Path) -> None:
    context = _context(tmp_path)
    runner = RecordingRunner(failing_command="generated.ruff.qwen-harness")

    report = run_generated_quality_checks(context, runner=runner)

    failed = next(check for check in report.checks if check.name == "ruff:Qwen-Harness")
    assert report.passed is False
    assert failed.status == "failed"
    assert failed.exit_code == 1
    assert failed.stderr_path is not None
    assert Path(failed.stderr_path).read_text(encoding="utf-8") == "generated failure\n"
    assert len(runner.specs) == 14


def test_quality_checks_report_missing_node_contract_without_claiming_success(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    route_tests = context.run_dir / "workspace" / "source" / "xuhui_route_builder" / "tests"
    (route_tests / "data_contract.test.mjs").unlink()
    runner = RecordingRunner()

    report = run_generated_quality_checks(context, runner=runner)

    node = next(check for check in report.checks if check.category == "node")
    assert report.passed is False
    assert node.status == "failed"
    assert node.command is None
    assert "*.test.mjs" in (node.error or "")
    assert all(spec.command_id != "generated.node_contract" for spec in runner.specs)


def test_generated_quality_gate_only_promotes_required_checks() -> None:
    report = GeneratedQualityReport(
        source_root="workspace/source",
        passed=False,
        report_path="checks/generated_quality.json",
        checks=[
            GeneratedQualityCheck(
                name="pytest:evaluation",
                category="pytest",
                status="failed",
                passed=False,
                error="ImportError",
            ),
            GeneratedQualityCheck(
                name="真实浏览器验收",
                category="browser",
                status="not_run",
                passed=False,
                required=True,
            ),
        ],
    )

    gate = _generated_quality_gate(report)

    assert gate.passed is False
    assert len(gate.checks) == 2
    assert gate.checks[0].name == "generated_pytest_pytest:evaluation"
    assert gate.checks[1].name == "generated_browser_真实浏览器验收"
