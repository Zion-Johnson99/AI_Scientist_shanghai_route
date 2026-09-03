"""qwen-harness 命令行入口（设计文档 01 §5）。

命令：run / doctor / validate / status / resume / report / publish /
list-runs。错误输出为包含 ``error_type`` / ``message`` / ``run_id`` /
``stage`` / ``suggested_action`` 的 JSON；绝不输出 API Key 等敏感信息。

退出码：0 成功；1 门禁未通过或结果不支持假设但运行完整；2 配置/输入/
契约错误；3 模型或外部来源故障且无回退；4 模块命令失败；5 运行状态
损坏、锁冲突或恢复失败。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import __version__
from .config import (
    env_diagnostics,
    load_harness_config,
    load_quality_gates,
    load_settings,
    load_source_policy,
)
from .errors import GateFailure, HarnessError, InputContractError, RunStateError
from .logging_utils import redact_text
from .models import ResearchGoal, ResumeOptions, RunOptions, RunSummary, WebPayload
from .paths import HarnessPaths
from .run_store import RunStore
from .skills import CORE_SKILLS, SkillRegistry

WORKFLOW_NAMES = ("full-research", "research-only", "reproduce-existing")
_ADAPTER_METHODS = ("preflight", "snapshot", "execute", "validate")


def harness_root() -> Path:
    """Qwen-Harness/ 根目录（由包位置推导）。"""
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------
def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _print_error(payload: dict[str, Any]) -> None:
    payload = dict(payload)
    for key in ("message", "suggested_action"):
        if isinstance(payload.get(key), str):
            payload[key] = redact_text(payload[key])
    _print_json({"ok": False, "error": payload})


def _summary_exit_code(summary: RunSummary) -> int:
    if summary.status == "needs_approval":
        return 0
    if summary.status == "failed":
        error_type = str((summary.error or {}).get("error_type", ""))
        if error_type in {"gate_failed", "approval_pending"}:
            return 1
        if error_type in {
            "config_error",
            "input_contract_error",
            "path_boundary_error",
            "skill_error",
        }:
            return 2
        if error_type in {"model_unavailable", "source_unavailable"}:
            return 3
        if error_type == "module_command_failed":
            return 4
        return 5
    if summary.final_support_status == "unsupported":
        return 1
    return 0


def _print_summary(summary: RunSummary, json_output: bool) -> None:
    if json_output:
        _print_json(
            {"ok": summary.status != "failed", "summary": json.loads(summary.model_dump_json())}
        )
        return
    print(f"运行 {summary.run_id} [{summary.workflow}] 状态: {summary.status}")
    print(f"  运行目录: {summary.run_dir}")
    print(f"  支持状态: {summary.final_support_status or '未定'}")
    print(f"  迭代轮数: {summary.iterations}")
    if summary.published:
        print("  网页发布: 已完成")
    for warning in summary.warnings:
        print(f"  警告: {warning}")


def _resolve_environment() -> tuple[Any, Any, HarnessPaths]:
    root = harness_root()
    settings = load_settings(root)
    config = load_harness_config(root)
    paths = HarnessPaths.resolve(root, config, settings.runtime_root)
    return settings, config, paths


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def _load_goal(args: argparse.Namespace) -> ResearchGoal:
    if args.goal_file:
        path = Path(args.goal_file)
        if not path.is_file():
            raise InputContractError(
                f"目标文件不存在: {path}", suggested_action="检查 --goal-file 路径"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InputContractError(f"目标文件不可读: {exc}") from exc
        try:
            return ResearchGoal.model_validate(data)
        except ValidationError as exc:
            raise InputContractError(f"目标文件不符合 ResearchGoal 契约: {exc}") from exc
    text = (args.goal or "").strip()
    if not text:
        raise InputContractError("研究目标不能为空", suggested_action="提供 --goal 或 --goal-file")
    title = text if len(text) <= 60 else text[:57] + "..."
    return ResearchGoal(title=title, question=text)


def cmd_run(args: argparse.Namespace) -> int:
    goal = _load_goal(args)
    try:
        options = RunOptions(
            workflow=args.workflow,
            offline=args.offline,
            allow_network=args.allow_network,
            refresh_environment=args.refresh_environment,
            approval_mode=args.approval_mode,
            max_iterations=args.max_iterations,
            publish_web=args.publish_web,
            run_id=args.run_id,
            json_output=args.json,
        )
    except ValidationError as exc:
        raise InputContractError(f"运行参数组合非法: {exc}") from exc
    from .workflow.engine import WorkflowEngine

    summary = WorkflowEngine().run(goal, options)
    _print_summary(summary, args.json)
    return _summary_exit_code(summary)


def cmd_doctor(args: argparse.Namespace) -> int:
    root = harness_root()
    problems: list[dict[str, Any]] = []
    settings = load_settings(root)
    problems.extend(env_diagnostics(settings))
    paths: HarnessPaths | None = None
    try:
        config = load_harness_config(root)
        paths = HarnessPaths.resolve(root, config, settings.runtime_root)
    except HarnessError as exc:
        problems.append({"level": "error", "item": "harness.json", "message": exc.message})
    if paths is not None:
        for label, target in (
            ("paths.route_module", paths.route_module),
            ("paths.environment_module", paths.environment_module),
            ("paths.evaluation_module", paths.evaluation_module),
            ("paths.web_data_root", paths.web_data_root),
        ):
            if not target.is_dir():
                problems.append(
                    {"level": "error", "item": label, "message": f"模块目录不存在: {target}"}
                )
        try:
            registry = SkillRegistry(paths.repo_root)
            discovered = registry.discover()
            missing = [name for name in CORE_SKILLS if name not in discovered]
            if missing:
                problems.append(
                    {
                        "level": "error",
                        "item": "skills",
                        "message": f"缺少项目技能: {', '.join(missing)}",
                    }
                )
        except HarnessError as exc:
            problems.append({"level": "error", "item": "skills", "message": exc.message})
        try:
            paths.runtime_root.mkdir(parents=True, exist_ok=True)
            probe = paths.runtime_root / ".write_probe"
            probe.write_text("probe", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(
                {"level": "error", "item": "runtime", "message": f"runtime 目录不可写: {exc}"}
            )
    has_error = any(problem["level"] == "error" for problem in problems)
    _print_json({"ok": not has_error, "version": __version__, "problems": problems})
    return 2 if has_error else 0


def _validate_config_scope(paths: HarnessPaths) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    root = paths.harness_root
    for label, loader in (
        ("harness.json", lambda: load_harness_config(root)),
        ("source_policy.json", lambda: load_source_policy(root)),
        ("quality_gates.json", lambda: load_quality_gates(root)),
    ):
        try:
            loader()
        except HarnessError as exc:
            problems.append({"scope": "config", "item": label, "message": exc.message})
    from .workflow.registry import load_workflow

    for name in WORKFLOW_NAMES:
        try:
            load_workflow(paths.workflows_dir, name)
        except HarnessError as exc:
            problems.append(
                {"scope": "config", "item": f"workflows/{name}.json", "message": exc.message}
            )
    return problems


def _validate_skills_scope(paths: HarnessPaths) -> list[dict[str, Any]]:
    try:
        discovered = SkillRegistry(paths.repo_root).discover()
    except HarnessError as exc:
        return [{"scope": "skills", "item": "discover", "message": exc.message}]
    problems = []
    for name in CORE_SKILLS:
        if name not in discovered:
            problems.append({"scope": "skills", "item": name, "message": "项目技能缺失"})
    return problems


def _validate_adapters_scope() -> list[dict[str, Any]]:
    try:
        module = importlib.import_module("qwen_harness.adapters")
    except ModuleNotFoundError:
        return [
            {"scope": "adapters", "item": "qwen_harness.adapters", "message": "Adapter 包尚未实现"}
        ]
    adapters = getattr(module, "ADAPTERS", None)
    if not isinstance(adapters, dict):
        return [{"scope": "adapters", "item": "ADAPTERS", "message": "ADAPTERS 注册表必须是 dict"}]
    problems = []
    for key in ("route", "environment", "evaluation", "web"):
        adapter = adapters.get(key)
        if adapter is None:
            problems.append({"scope": "adapters", "item": key, "message": "未注册"})
            continue
        for method in _ADAPTER_METHODS:
            if not callable(getattr(adapter, method, None)):
                problems.append(
                    {
                        "scope": "adapters",
                        "item": f"{key}.{method}",
                        "message": "方法缺失或不可调用",
                    }
                )
    return problems


def _validate_runs_scope(settings: Any, config: Any, paths: HarnessPaths) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    if not paths.runs_dir.is_dir():
        return []
    for entry in sorted(paths.runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            store = RunStore(paths, settings, config)
            context = store.load_run(entry.name)
            for stage, status in context.state.stage_statuses.items():
                if (
                    status in {"passed", "needs_approval"}
                    and not store.stage_output_path(stage, "output").is_file()
                ):
                    problems.append(
                        {
                            "scope": "runs",
                            "item": f"{entry.name}/{stage}",
                            "message": "已通过阶段缺少输出文件",
                        }
                    )
        except HarnessError as exc:
            problems.append({"scope": "runs", "item": entry.name, "message": exc.message})
    return problems


def cmd_validate(args: argparse.Namespace) -> int:
    settings, config, paths = _resolve_environment()
    scopes = ("config", "skills", "adapters", "runs") if args.scope == "all" else (args.scope,)
    problems: list[dict[str, Any]] = []
    for scope in scopes:
        if scope == "config":
            problems.extend(_validate_config_scope(paths))
        elif scope == "skills":
            problems.extend(_validate_skills_scope(paths))
        elif scope == "adapters":
            problems.extend(_validate_adapters_scope())
        elif scope == "runs":
            problems.extend(_validate_runs_scope(settings, config, paths))
    _print_json({"ok": not problems, "scopes": list(scopes), "problems": problems})
    return 2 if problems else 0


def cmd_status(args: argparse.Namespace) -> int:
    settings, config, paths = _resolve_environment()
    store = RunStore(paths, settings, config)
    context = store.load_run(args.run_id)
    payload = {
        "run_id": context.run_id,
        "workflow": context.manifest.workflow_name,
        "status": context.state.status,
        "iteration": context.state.iteration,
        "current_stage": context.state.current_stage,
        "final_support_status": context.state.final_support_status,
        "created_at": context.manifest.created_at,
        "stage_statuses": context.state.stage_statuses,
        "run_dir": context.run_dir,
    }
    if args.json:
        _print_json(payload)
        return 0
    print(f"运行 {payload['run_id']} [{payload['workflow']}] 状态: {payload['status']}")
    print(f"  迭代: {payload['iteration']}  当前阶段: {payload['current_stage'] or '-'}")
    print(f"  支持状态: {payload['final_support_status'] or '未定'}")
    for stage, status in payload["stage_statuses"].items():
        print(f"  - {stage}: {status}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from .workflow.engine import WorkflowEngine

    summary = WorkflowEngine().resume(
        args.run_id, ResumeOptions(publish_web=args.publish_web, force_continue=args.force_continue)
    )
    _print_summary(summary, args.json)
    return _summary_exit_code(summary)


def cmd_report(args: argparse.Namespace) -> int:
    settings, config, paths = _resolve_environment()
    store = RunStore(paths, settings, config)
    context = store.load_run(args.run_id)
    run_dir = Path(context.run_dir)
    candidates = (
        run_dir / "reports" / "full_run_report.md",
        run_dir / "reports" / "scientific_plan.json",
        run_dir / "reports" / "experiment_report.md",
        run_dir / "publish" / "research_harness_latest.json",
        run_dir / "publish" / "launch-local.ps1",
    )
    found = [path for path in candidates if path.is_file()]
    if not found:
        raise InputContractError(
            f"运行 {args.run_id} 尚无报告产物",
            run_id=args.run_id,
            suggested_action="先完整执行工作流（含 scientific_report 阶段）",
        )
    print(f"运行 {args.run_id} 报告产物:")
    for path in found:
        print(f"  - {path.relative_to(run_dir).as_posix()}")
    plan = store.read_json("reports/scientific_plan.json")
    if isinstance(plan, dict):
        print(f"  论文标题: {plan.get('paper_title', '-')}")
        print(f"  问题陈述: {str(plan.get('problem_statement', '-'))[:120]}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    settings, config, paths = _resolve_environment()
    store = RunStore(paths, settings, config)
    context = store.load_run(args.run_id)
    if context.state.stage_statuses.get("final_validation") != "passed":
        raise GateFailure(
            "最终门禁未通过，禁止发布",
            run_id=args.run_id,
            suggested_action="先让 final_validation 阶段通过",
        )
    publish_root = Path(context.run_dir) / "publish"
    source = publish_root / "research_harness_latest.json"
    local_index = publish_root / "local-product" / "web" / "index.html"
    launcher = publish_root / "launch-local.ps1"
    if not source.is_file() or not local_index.is_file() or not launcher.is_file():
        raise RunStateError(
            "运行目录缺少完整本地交付包",
            run_id=args.run_id,
            suggested_action="先完成 web_payload 与 final_validation 阶段",
        )
    WebPayload.model_validate_json(source.read_bytes())
    store.write_json_atomic(
        "publish/published.flag",
        {
            "target": "publish/local-product",
            "run_id": args.run_id,
            "local_url": "http://127.0.0.1:8130/web/",
        },
    )
    store.emit("published_local", "本地交付包已确认", stage="publish_web")
    _print_json(
        {
            "ok": True,
            "published_to": str(publish_root / "local-product"),
            "local_url": "http://127.0.0.1:8130/web/",
        }
    )
    return 0


def cmd_list_runs(args: argparse.Namespace) -> int:
    _settings, _config, paths = _resolve_environment()
    rows: list[dict[str, Any]] = []
    if paths.runs_dir.is_dir():
        entries = sorted(
            (entry for entry in paths.runs_dir.iterdir() if entry.is_dir()),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
        for entry in entries[: args.limit]:
            row: dict[str, Any] = {"run_id": entry.name}
            state_file = entry / "state.json"
            if state_file.is_file():
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                    row.update(
                        workflow=state.get("workflow"),
                        status=state.get("status"),
                        iteration=state.get("iteration"),
                        updated_at=state.get("updated_at"),
                    )
                except (OSError, json.JSONDecodeError):
                    row["status"] = "unreadable"
            rows.append(row)
    if args.json:
        _print_json({"ok": True, "runs": rows})
        return 0
    if not rows:
        print("尚无运行记录（runtime/runs 为空）")
        return 0
    for row in rows:
        print(
            f"{row['run_id']}  workflow={row.get('workflow', '-')}  "
            f"status={row.get('status', '-')}  iteration={row.get('iteration', '-')}"
        )
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qwen-harness", description="Qwen-Harness 施工工作流引擎")
    parser.add_argument("--version", action="version", version=f"qwen-harness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="执行研究工作流")
    goal_group = run.add_mutually_exclusive_group(required=True)
    goal_group.add_argument("--goal", help="研究目标文本")
    goal_group.add_argument("--goal-file", help="ResearchGoal JSON 文件路径")
    run.add_argument("--workflow", choices=WORKFLOW_NAMES, default="full-research")
    run.add_argument("--offline", action="store_true", help="离线夹具模式")
    run.add_argument("--allow-network", action="store_true", help="允许网络访问")
    run.add_argument(
        "--refresh-environment", choices=("none", "weather", "hourly", "daily"), default="none"
    )
    run.add_argument("--approval-mode", choices=("auto", "critical", "all"), default="critical")
    run.add_argument("--max-iterations", type=int, default=2)
    run.add_argument("--publish-web", action="store_true")
    run.add_argument("--run-id", default=None)
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    doctor = sub.add_parser("doctor", help="环境与配置体检")
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser("validate", help="按范围校验契约")
    validate.add_argument(
        "--scope", choices=("config", "skills", "adapters", "runs", "all"), default="all"
    )
    validate.set_defaults(func=cmd_validate)

    status = sub.add_parser("status", help="查看运行状态")
    status.add_argument("run_id")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    resume = sub.add_parser("resume", help="恢复中断的运行")
    resume.add_argument("run_id")
    resume.add_argument("--publish-web", action="store_true")
    resume.add_argument("--force-continue", action="store_true")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(func=cmd_resume)

    report = sub.add_parser("report", help="查看运行报告产物")
    report.add_argument("run_id")
    report.set_defaults(func=cmd_report)

    publish = sub.add_parser("publish", help="发布已验证的网页 payload")
    publish.add_argument("run_id")
    publish.set_defaults(func=cmd_publish)

    list_runs = sub.add_parser("list-runs", help="列出运行记录")
    list_runs.add_argument("--limit", type=int, default=20)
    list_runs.add_argument("--json", action="store_true")
    list_runs.set_defaults(func=cmd_list_runs)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except HarnessError as exc:
        _print_error(exc.to_dict())
        return exc.exit_code
    except ValidationError as exc:
        _print_error(
            {
                "error_type": "input_contract_error",
                "message": str(exc),
                "suggested_action": "核对输入契约字段",
                "exit_code": 2,
            }
        )
        return 2
    except KeyboardInterrupt:
        _print_error({"error_type": "interrupted", "message": "用户中断", "exit_code": 5})
        return 5
    except Exception as exc:  # noqa: BLE001 - 顶层保护，绝不泄露敏感信息
        _print_error(
            {
                "error_type": "internal_error",
                "message": redact_text(f"{type(exc).__name__}: {exc}"),
                "suggested_action": "查看 runtime/logs 日志定位问题",
                "exit_code": 5,
            }
        )
        return 5


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
