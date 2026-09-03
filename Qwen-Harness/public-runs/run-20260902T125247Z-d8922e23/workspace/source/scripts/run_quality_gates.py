"""Run the fourteen mandatory quality gates and write checks/generated_quality.json.

Every recorded command starts with ``uv`` or ``node`` and every ``cwd`` resolves
inside ``source_root``, as the harness contract requires. Credential variables are
stripped from each subprocess environment so no gate can reach a paid model API.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
CHECKS_DIR: Path = RUN_ROOT / "checks"
LOG_DIR: Path = RUN_ROOT / "commands" / "quality"
REPORT_PATH: Path = RUN_ROOT / "reports" / "generated_quality.md"
SCRUBBED_ENV_KEYS: tuple[str, ...] = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY")

#: Only these three carry a graded pytest suite in the contract's check list.
PYTEST_PROJECTS: tuple[str, ...] = (
    "Qwen-Harness",
    "evaluation_model_qwen",
    "weather_api_data",
)

PROJECTS: tuple[str, ...] = (
    "Qwen-Harness",
    "xuhui_route_builder",
    "weather_api_data",
    "evaluation_model_qwen",
)

PYTEST = "uv run --no-project pytest {target} -q"
RUFF = "uv run --no-project --with ruff ruff check {target}"
PYRIGHT = "uv run --no-project --with pyright pyright {target}"


def _scrubbed_env() -> dict[str, str]:
    import os

    return {key: value for key, value in os.environ.items() if key not in SCRUBBED_ENV_KEYS}


def _check_specs() -> list[dict[str, Any]]:
    """The fourteen gates in contract order."""
    specs: list[dict[str, Any]] = [
        {
            "name": f"pytest:{project}",
            "category": "pytest",
            "command": PYTEST.format(target=f"{project}/tests"),
            "timeout": 900,
        }
        for project in PYTEST_PROJECTS
    ]
    for project in PROJECTS:
        specs.append(
            {
                "name": f"ruff:{project}",
                "category": "ruff",
                "command": RUFF.format(target=project),
                "timeout": 300,
            }
        )
        specs.append(
            {
                "name": f"pyright:{project}",
                "category": "pyright",
                "command": PYRIGHT.format(target=project),
                "timeout": 1200,
            }
        )
    specs.append(
        {
            "name": "Node 契约测试",
            "category": "node",
            "command": "node --test node/test_payload_contract.mjs",
            "timeout": 900,
        }
    )
    specs.append(
        {
            "name": "评价 API 健康检查",
            "category": "evaluation_api",
            "command": "uv run --no-project python scripts/check_evaluation_api.py",
            "timeout": 300,
        }
    )
    specs.append(
        {
            "name": "真实浏览器验收",
            "category": "browser",
            "command": "uv run --no-project python scripts/browser_acceptance.py",
            "timeout": 600,
        }
    )
    return specs


def _run(spec: dict[str, Any]) -> dict[str, Any]:
    """Execute one gate, capturing streams under commands/quality/."""
    safe = spec["name"].replace(":", "_").replace(" ", "_")
    stdout_path = LOG_DIR / f"{safe}.out"
    stderr_path = LOG_DIR / f"{safe}.err"
    record: dict[str, Any] = {
        "name": spec["name"],
        "category": spec["category"],
        "status": "not_run",
        "passed": False,
        "required": True,
        "command": spec["command"],
        "cwd": "workspace/source",
        "exit_code": None,
        "timed_out": False,
        "stdout_path": f"commands/quality/{stdout_path.name}",
        "stderr_path": f"commands/quality/{stderr_path.name}",
        "error": None,
    }
    started = time.perf_counter()
    try:
        result = subprocess.run(
            spec["command"].split(),
            cwd=str(SOURCE_ROOT),
            env=_scrubbed_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=spec["timeout"],
        )
    except subprocess.TimeoutExpired as exc:
        record["timed_out"] = True
        record["error"] = f"timed out after {spec['timeout']}s"
        stdout_path.write_text(str(exc.stdout or ""), encoding="utf-8")
        stderr_path.write_text(str(exc.stderr or ""), encoding="utf-8")
    except OSError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(record["error"], encoding="utf-8")
    else:
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        record["exit_code"] = result.returncode
        record["status"] = "passed" if result.returncode == 0 else "failed"
        record["passed"] = result.returncode == 0
    record["duration_s"] = round(time.perf_counter() - started, 1)
    return record


def _write_report(checks: list[dict[str, Any]], passed: bool, source_root: str) -> None:
    """Emit a human-readable gate table alongside the machine-readable JSON."""
    lines = [
        "# 工程质量门禁结果",
        "",
        f"- source_root: `{source_root}`",
        f"- 总体结论: {'passed' if passed else 'failed'}",
        f"- required 检查数: {sum(1 for c in checks if c['required'])}",
        f"- 通过数: {sum(1 for c in checks if c['passed'])}",
        "",
        "| 检查 | 类别 | 状态 | 退出码 | 耗时(s) | 日志 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        lines.append(
            "| {name} | {category} | {status} | {code} | {duration} | `{log}` |".format(
                name=check["name"],
                category=check["category"],
                status=check["status"],
                code=check["exit_code"] if check["exit_code"] is not None else "-",
                duration=check.get("duration_s", "-"),
                log=check["stdout_path"],
            )
        )
    lines += [
        "",
        "失败检查的 stderr 摘要：",
        "",
    ]
    failures = [c for c in checks if not c["passed"]]
    if not failures:
        lines.append("无。")
    for check in failures:
        stderr_file = RUN_ROOT / check["stderr_path"]
        tail = ""
        if stderr_file.exists():
            tail = stderr_file.read_text(encoding="utf-8").strip()[-600:]
        lines += [
            f"## {check['name']}",
            "",
            f"- 命令: `{check['command']}`",
            f"- 错误: {check['error'] or '非零退出码'}",
            "",
            "```",
            tail or "(stderr 为空)",
            "```",
            "",
        ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """Run every gate, write generated_quality.json and report the outcome."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    checks = [_run(spec) for spec in _check_specs()]
    passed = all(check["passed"] for check in checks if check["required"])
    source_root = "workspace/source"
    payload = {
        "source_root": source_root,
        "passed": passed,
        "checks": checks,
        "report_path": "reports/generated_quality.md",
    }
    (CHECKS_DIR / "generated_quality.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(checks, passed, source_root)
    for check in checks:
        sys.stdout.write(
            f"{'PASS' if check['passed'] else 'FAIL'} {check['name']} "
            f"exit={check['exit_code']} {check.get('duration_s')}s\n"
        )
    sys.stdout.write(f"GENERATED_QUALITY_PASSED={str(passed).lower()}\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
