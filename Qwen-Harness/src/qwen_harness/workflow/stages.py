"""平台原生阶段处理器（冻结契约，设计文档 01 §13/§15/§18/§19）。

本文件实现引擎侧的五个阶段：``initialize_stage``、
``module_preflight_stage``、``module_execution_stage``、
``final_validation_stage``、``publish_web_stage``。科研智能层的阶段处理器
由第二轮包（agents/sources/experiments/reporting）提供，工作流 JSON 通过
``"模块:函数"`` 引用它们。所有处理器遵循
``def stage_handler(context: WorkflowContext) -> StageResult``。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import load_quality_gates
from ..errors import InputContractError, ModuleCommandError
from ..generation.models import ValidationIssue
from ..generation.quality import (
    GeneratedQualityCheck,
    GeneratedQualityReport,
    run_generated_browser_check,
    run_generated_quality_checks,
)
from ..generation.stage_handlers import repair_generated_runtime_issue
from ..logging_utils import get_logger
from ..models import (
    ExperimentPlan,
    GateCheck,
    GateResult,
    ModuleOperation,
    ModuleResult,
    ScientificPlan,
    StageResult,
    WebPayload,
)
from .gates import PublishGate, ResultGate, load_gate_thresholds

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from .engine import WorkflowContext

LOGGER = get_logger("workflow.stages")

#: 模型可选择的预注册操作 ID 白名单（v1 只读/导出类）。
ALLOWED_OPERATION_IDS: frozenset[str] = frozenset(
    {
        "route.read_snapshot",
        "environment.read_snapshot",
        "evaluation.score_candidates",
        "web.export_payload",
    }
)

#: CLI 显式授权时才允许执行的合成操作（环境数据刷新分层）。
SYNTHETIC_OPERATION_IDS: frozenset[str] = frozenset({"environment.refresh"})

#: v1 禁用的模块操作（设计文档 §5.1、§15.2）。
DISABLED_OPERATIONS_V1: frozenset[str] = frozenset({"route_export_candidates", "route_generate"})

_ADAPTER_MODULE_KEYS = ("route", "environment", "evaluation", "web")

_MODULE_PROJECT_ROOTS = {
    "route": "xuhui_route_builder",
    "environment": "weather_api_data",
    "evaluation": "evaluation_model_qwen",
    "web": "xuhui_route_builder",
}

_PACKAGE_PROJECT_ROOTS = {
    "qwen_harness": "Qwen-Harness",
    "evaluation_model_qwen": "evaluation_model_qwen",
    "weather_api_data": "weather_api_data",
    "xuhui_route_builder": "xuhui_route_builder",
}


def _load_adapters(context: "WorkflowContext") -> dict[str, Any]:
    """惰性导入四模块 Adapter，平台可在 Adapter 就绪前启动。"""
    try:
        from ..adapters import ADAPTERS
    except ModuleNotFoundError as exc:
        raise InputContractError(
            "qwen_harness.adapters.ADAPTERS 尚未实现",
            stage=context.stage_spec.name if context.stage_spec else None,
            run_id=context.run_id,
            suggested_action="等待四模块 Adapter 完成后运行该阶段",
        ) from exc
    if not isinstance(ADAPTERS, dict):
        raise InputContractError("ADAPTERS 必须是 dict[模块名, ModuleAdapter]")
    missing = [key for key in _ADAPTER_MODULE_KEYS if key not in ADAPTERS]
    if missing:
        raise InputContractError(
            f"ADAPTERS 缺少模块: {', '.join(missing)}",
            suggested_action="检查 qwen_harness/adapters/__init__.py 的注册表",
        )
    return ADAPTERS


def _coerce_module_result(module: str, value: Any) -> ModuleResult:
    if isinstance(value, ModuleResult):
        return value
    dump = getattr(value, "model_dump", None)
    data = dump() if callable(dump) else value
    try:
        return ModuleResult.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        raise ModuleCommandError(
            f"模块 {module} 返回了不符合 ModuleResult 契约的结果: {exc}",
            suggested_action="检查该模块 Adapter 的返回值",
        ) from exc


def _save_module_result(context: "WorkflowContext", module: str, label: str, result: ModuleResult) -> str:
    relative = f"modules/{module}/{label}.json"
    context.store.write_json_atomic(relative, result.model_dump(mode="json"))
    return relative


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------
def initialize_stage(context: "WorkflowContext") -> StageResult:
    """校验脚手架、快照技能并初始化派生配置。"""
    warnings: list[str] = []
    required_skills: list[str] = []
    for stage in context.workflow.stages:
        for name in stage.required_skills:
            if name not in required_skills:
                required_skills.append(name)
    try:
        discovered = context.skills.discover()
    except Exception as exc:  # noqa: BLE001 - doctor 会严格报告
        discovered = {}
        warnings.append(f"技能发现失败: {exc}")
    present = [name for name in required_skills if name in discovered]
    missing = [name for name in required_skills if name not in discovered]
    if missing:
        warnings.append(f"工作流引用的技能缺失: {', '.join(missing)}")
    try:
        snapshot_files = context.skills.snapshot(context.store, present)
    except Exception as exc:  # noqa: BLE001 - 快照失败降级为警告
        snapshot_files = []
        warnings.append(f"技能快照失败: {exc}")

    derived = context.read_derived_config()
    if not derived:
        gates = load_quality_gates(context.harness_root)
        derived = context.write_derived_config(
            {"supported_thresholds": load_gate_thresholds(gates, "supported"), "weights": {}},
            reason="初始化派生配置",
        )
    variants_path = context.paths.config_dir / "experiment_variants.json"
    if variants_path.is_file():
        try:
            variants = json.loads(variants_path.read_text(encoding="utf-8"))
            context.write_derived_config({"experiment_variants": variants}, reason="载入实验变体")
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"experiment_variants.json 无法解析: {exc}")

    context.emit(
        "initialized",
        f"技能快照 {len(snapshot_files)} 个文件，派生配置就绪",
        details={"workflow": context.workflow.name, "skills_missing": missing},
    )
    return StageResult(
        stage="initialize",
        status="passed",
        summary=f"初始化完成：快照技能 {len(present)} 个",
        output={
            "skills_snapshotted": present,
            "skills_missing": missing,
            "derived_config_keys": sorted(derived.keys()),
        },
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# module preflight / execution
# ---------------------------------------------------------------------------
def module_preflight_stage(context: "WorkflowContext") -> StageResult:
    """四模块只读预检：数据齐全为 ok，部分缺失为 partial，损坏为 error。"""
    adapters = _load_adapters(context)
    warnings: list[str] = []
    statuses: dict[str, str] = {}
    for key in _ADAPTER_MODULE_KEYS:
        adapter = adapters[key]
        try:
            raw = adapter.preflight(context)
        except Exception as exc:
            raise ModuleCommandError(
                f"模块 {key} 预检异常: {exc}",
                stage="module_preflight",
                run_id=context.run_id,
            ) from exc
        result = _coerce_module_result(key, raw)
        statuses[key] = result.status
        _save_module_result(context, key, "preflight", result)
        warnings.extend(f"{key}: {message}" for message in result.warnings)
        if result.status == "error":
            raise ModuleCommandError(
                f"模块 {key} 预检失败: {'; '.join(result.errors) or '未知错误'}",
                stage="module_preflight",
                run_id=context.run_id,
                suggested_action="修复模块数据或命令环境后重试",
            )
    if any(status == "partial" for status in statuses.values()):
        warnings.append("部分模块为 partial：实验解释需保留数据限制说明")
    return StageResult(
        stage="module_preflight",
        status="passed",
        summary=f"预检状态: {', '.join(f'{k}={v}' for k, v in statuses.items())}",
        output={"preflight_statuses": statuses},
        warnings=warnings,
    )


def _expand_plan_operations(plan: ExperimentPlan) -> list[ModuleOperation]:
    """将面向全部画像的评分操作展开为可审计单元。"""
    expanded: list[ModuleOperation] = []
    for raw_operation in plan.module_operations:
        operation = ModuleOperation.model_validate(raw_operation)
        if (
            operation.operation_id != "evaluation.score_candidates"
            or isinstance(operation.parameters.get("profile"), (dict, str))
        ):
            expanded.append(operation)
            continue
        for index, profile in enumerate(plan.profiles, start=1):
            if not isinstance(profile, dict):
                continue
            case_id = str(profile.get("case_id") or profile.get("profile_id") or f"profile-{index:02d}")
            parameters = dict(operation.parameters)
            parameters.update(
                {
                    "profile": dict(profile),
                    "label": case_id,
                    "variants": list(plan.variants),
                }
            )
            expanded.append(operation.model_copy(update={"parameters": parameters}))
    return expanded


def _runtime_error_diagnostics(error: ModuleCommandError, run_dir: Path) -> str:
    """读取当前 run 内的命令错误日志，限制长度并阻止越界读取。"""
    chunks = [error.message]
    resolved_run = run_dir.resolve()
    for key in ("stderr_path", "stdout_path"):
        raw = error.details.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        candidate = Path(raw).resolve()
        try:
            candidate.relative_to(resolved_run)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if content.strip():
            chunks.append(content[-6_000:])
    return "\n".join(chunks)[-8_000:]


def _runtime_repair_target(*, module: str, diagnostics: str, source_root: Path) -> str | None:
    """从构建错误、导入错误和生成源码回溯中定位单个修复目标。"""
    project_root = _MODULE_PROJECT_ROOTS.get(module)
    if project_root is None:
        return None

    lowered = diagnostics.lower()
    pyproject = f"{project_root}/pyproject.toml"
    if ("readme file does not exist" in lowered or "failed to build" in lowered) and (
        source_root / pyproject
    ).is_file():
        return pyproject

    imported_from = re.search(r"from ['\"]([A-Za-z_][\w.]*)['\"]", diagnostics)
    if imported_from:
        module_name = imported_from.group(1)
        package = module_name.split(".", maxsplit=1)[0]
        owner = _PACKAGE_PROJECT_ROOTS.get(package)
        if owner:
            candidate = f"{owner}/src/{module_name.replace('.', '/')}.py"
            if (source_root / candidate).is_file():
                return candidate

    normalized = diagnostics.replace("\\", "/")
    generated_paths = re.findall(r"workspace/source/([^\"\r\n]+?\.py)", normalized)
    for candidate in reversed(generated_paths):
        candidate = candidate.strip()
        if (source_root / candidate).is_file():
            return candidate

    fallbacks = {
        "evaluation": [
            "Qwen-Harness/src/qwen_harness/adapters/evaluation_score_candidates.py",
            "evaluation_model_qwen/pyproject.toml",
        ],
        "environment": ["weather_api_data/src/weather_api_data/web_export.py"],
        "route": ["xuhui_route_builder/src/xuhui_route_builder/generate_data.py"],
        "web": ["xuhui_route_builder/web/src/main.js", "xuhui_route_builder/web/index.html"],
    }
    return next(
        (candidate for candidate in fallbacks.get(module, []) if (source_root / candidate).is_file()),
        None,
    )


def _execute_operation_with_runtime_repair(
    adapter: Any, operation: ModuleOperation, context: "WorkflowContext"
) -> Any:
    """执行生成模块；真实命令失败时调用千问定向修复后重试。"""
    max_repairs = min(
        int(context.options.max_iterations),
        int(context.harness_config.runtime.max_iterations),
    )
    source_root = context.run_dir / "workspace" / "source"
    for repair_round in range(max_repairs + 1):
        try:
            raw = adapter.execute(operation, context)
        except ModuleCommandError as error:
            command_error = error
        else:
            result = _coerce_module_result(operation.module, raw)
            if result.status != "error":
                return raw
            details: dict[str, Any] = {}
            if result.commands:
                command = result.commands[-1]
                details = {
                    "stdout_path": command.stdout_path,
                    "stderr_path": command.stderr_path,
                    "command_id": command.command_id,
                    "exit_code": command.exit_code,
                }
            command_error = ModuleCommandError(
                f"模块 {operation.module} 返回错误结果: "
                + ("; ".join(result.errors) or "未知错误"),
                details=details,
            )
        if context.options.offline or context.model_client is None or repair_round >= max_repairs:
            raise command_error
        diagnostics = _runtime_error_diagnostics(command_error, context.run_dir)
        target = _runtime_repair_target(
            module=operation.module,
            diagnostics=diagnostics,
            source_root=source_root,
        )
        if target is None:
            raise command_error
        guidance = ""
        if operation.operation_id == "evaluation.score_candidates":
            guidance = (
                "目标脚本由 Harness 通过 python <script> --profile <json> --weights <json> "
                "--route-catalog <json> --environment-dashboard <json> 直接执行。脚本需要提供 "
                "__main__ 入口并解析这些参数；成功时 stdout 只输出一个 JSON 对象，字段至少包含 "
                "profile、risk、data_generated_at、candidate_count、candidates、weights_sha256。"
            )
        issue = ValidationIssue(
            check=f"runtime_{operation.operation_id.replace('.', '_')}",
            summary=f"生成模块的运行或输出契约失败，需要修复 {target}",
            details=f"{guidance}\n\n真实运行诊断：\n{diagnostics}".strip(),
            files=[target],
        )
        context.emit(
            "generated_runtime_repair_started",
            f"千问开始修复生成文件 {target}",
            status="warning",
            details={"repair_round": repair_round + 1},
        )
        repair_generated_runtime_issue(
            context,
            issue,
            repair_round=repair_round + 1,
        )
    raise ModuleCommandError("生成模块运行时修复循环异常退出")


def module_execution_stage(context: "WorkflowContext") -> StageResult:
    """执行实验计划声明的白名单模块操作，并固化路线/环境快照。"""
    adapters = _load_adapters(context)
    plan = context.read_stage_output_model("experiment_design", ExperimentPlan)
    warnings: list[str] = []
    executed: list[str] = []

    operations = _expand_plan_operations(plan)
    refresh = context.options.refresh_environment
    if refresh != "none" and not context.options.offline:
        operations.insert(
            0,
            ModuleOperation(
                operation_id="environment.refresh",
                module="environment",
                parameters={"tier": refresh},
                reason="CLI --refresh-environment 显式授权",
            ),
        )

    for operation in operations:
        if operation.operation_id in DISABLED_OPERATIONS_V1:
            warnings.append(f"操作 {operation.operation_id} 在 v1 中禁用，已跳过")
            context.emit("operation_skipped", f"v1 禁用操作 {operation.operation_id}", status="warning")
            continue
        if (
            operation.operation_id not in ALLOWED_OPERATION_IDS
            and operation.operation_id not in SYNTHETIC_OPERATION_IDS
        ):
            raise InputContractError(
                f"操作 {operation.operation_id} 不在预注册白名单内",
                stage="module_execution",
                run_id=context.run_id,
                suggested_action=f"允许的操作: {', '.join(sorted(ALLOWED_OPERATION_IDS))}",
            )
        adapter = adapters.get(operation.module)
        if adapter is None:
            raise InputContractError(f"操作 {operation.operation_id} 指向未知模块 {operation.module}")
        try:
            raw = _execute_operation_with_runtime_repair(adapter, operation, context)
        except ModuleCommandError:
            raise
        except Exception as exc:
            raise ModuleCommandError(
                f"模块 {operation.module} 操作 {operation.operation_id} 异常: {exc}",
                stage="module_execution",
                run_id=context.run_id,
            ) from exc
        result = _coerce_module_result(operation.module, raw)
        operation_label = adapter.safe_label(operation.parameters.get("label"), "")
        label = operation.operation_id.replace(".", "_")
        if operation_label:
            label = f"{label}__{operation_label}"
        _save_module_result(context, operation.module, label, result)
        executed.append(f"{operation.module}:{operation.operation_id}")
        warnings.extend(f"{operation.module}: {message}" for message in result.warnings)
        if result.status == "error":
            raise ModuleCommandError(
                f"模块 {operation.module} 操作 {operation.operation_id} 失败: "
                + ("; ".join(result.errors) or "未知错误"),
                stage="module_execution",
                run_id=context.run_id,
            )

    for key in ("route", "environment"):
        adapter = adapters[key]
        try:
            raw_snapshot = adapter.snapshot(context)
        except Exception as exc:  # noqa: BLE001 - 快照降级
            warnings.append(f"{key} 快照失败: {exc}")
            continue
        snapshot = _coerce_module_result(key, raw_snapshot)
        _save_module_result(context, key, "snapshot", snapshot)
        warnings.extend(f"{key}: {message}" for message in snapshot.warnings)

    return StageResult(
        stage="module_execution",
        status="passed",
        summary=f"执行模块操作 {len(executed)} 个",
        output={"executed_operations": executed},
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# final validation + publish
# ---------------------------------------------------------------------------
def _load_route_ids(context: "WorkflowContext") -> set[str]:
    from ..adapters.project_paths import GeneratedProjectPaths

    catalog_path = GeneratedProjectPaths.from_context(context).route_catalog_path
    if not catalog_path.is_file():
        return set()
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids: set[str] = set()

    def _collect(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("route_id", "id"):
                value = node.get(key)
                if isinstance(value, str) and value:
                    ids.add(value)
            for value in node.values():
                _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(data)
    return ids


def _generated_quality_gate(report: GeneratedQualityReport) -> GateResult:
    required = [check for check in report.checks if check.required]
    return GateResult(
        gate="generated_project_quality",
        passed=report.passed,
        checks=[
            GateCheck(
                name=f"generated_{check.category}_{check.name}",
                passed=check.passed,
                detail=(
                    f"{check.status}; exit_code={check.exit_code}; "
                    f"error={check.error or 'none'}"
                ),
            )
            for check in required
        ],
        summary=f"生成工程可执行质量检查通过 {sum(check.passed for check in required)}/{len(required)} 项",
    )


def _browser_quality_issue(
    check: GeneratedQualityCheck, run_dir: Path
) -> ValidationIssue:
    """把浏览器断言转换成单文件千问修复任务。"""
    diagnostics = check.error or "真实浏览器验收失败"
    if check.stderr_path:
        stderr_path = Path(check.stderr_path).resolve()
        try:
            stderr_path.relative_to(Path(run_dir).resolve())
        except ValueError:
            pass
        else:
            if stderr_path.is_file():
                stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
                diagnostics = f"{diagnostics}\n{stderr[-6_000:]}"
    layout_markers = ("横向溢出", "地图宽度", "地图高度", "地图不可见", "工作台不可见")
    interaction_markers = (
        "环境详情",
        "data-testid=route-card",
        "路线数量",
        "筛选",
        "同步到地图",
        "控制台错误",
        "资源请求失败",
    )
    if any(marker in diagnostics for marker in layout_markers):
        target = "xuhui_route_builder/web/styles/main.css"
        check_name = "browser_visual_contract"
    elif any(marker in diagnostics for marker in interaction_markers):
        target = "xuhui_route_builder/web/src/main.js"
        check_name = "browser_interaction_contract"
    else:
        target = "xuhui_route_builder/web/index.html"
        check_name = "browser_dom_contract"
    return ValidationIssue(
        check=check_name,
        summary="真实浏览器核心门禁未通过",
        details=diagnostics,
        files=[target],
    )


def _repair_failed_browser_once(
    context: "WorkflowContext", report: GeneratedQualityReport
) -> GeneratedQualityReport:
    browser = next((check for check in report.checks if check.category == "browser"), None)
    if browser is None or browser.passed or context.options.offline or context.model_client is None:
        return report
    issue = _browser_quality_issue(browser, Path(context.run_dir))
    if "AssertionError:" not in issue.details:
        return report
    context.emit(
        "generated_browser_repair_started",
        "真实浏览器门禁失败，启动一次千问定向修复",
        details={"target": issue.files[0]},
    )
    repair_generated_runtime_issue(context, issue, repair_round=1)
    retried = run_generated_browser_check(context)
    checks = [retried if check.category == "browser" else check for check in report.checks]
    updated = report.model_copy(
        update={
            "checks": checks,
            "passed": all(check.passed for check in checks if check.required),
        }
    )
    context.store.write_json_atomic(
        "checks/generated_quality.json", updated.model_dump(mode="json")
    )
    return updated


def final_validation_stage(context: "WorkflowContext") -> StageResult:
    """发布前最终门禁：科研报告、网页 payload 契约与 PublishGate。"""
    store = context.store
    warnings: list[str] = []

    plan_data = store.read_json("reports/scientific_plan.json")
    if plan_data is None:
        raise InputContractError(
            "reports/scientific_plan.json 缺失",
            stage="final_validation",
            run_id=context.run_id,
            suggested_action="先完成 scientific_report 阶段",
        )
    try:
        ScientificPlan.model_validate(plan_data)
    except Exception as exc:  # pydantic ValidationError
        raise InputContractError(
            f"scientific_plan.json 不符合契约: {exc}",
            stage="final_validation",
            run_id=context.run_id,
        ) from exc

    payload_data = store.read_json("publish/research_harness_latest.json")
    has_web_stage = any(stage.name == "web_payload" for stage in context.workflow.stages)
    if payload_data is None and has_web_stage:
        raise InputContractError(
            "publish/research_harness_latest.json 缺失",
            stage="final_validation",
            run_id=context.run_id,
            suggested_action="先完成 web_payload 阶段",
        )

    gates = load_quality_gates(context.harness_root)
    route_ids = _load_route_ids(context)
    if payload_data is not None:
        try:
            payload = WebPayload.model_validate(payload_data)
        except Exception as exc:  # pydantic ValidationError
            raise InputContractError(
                f"网页 payload 不符合契约: {exc}",
                stage="final_validation",
                run_id=context.run_id,
            ) from exc
        publish_gate = PublishGate(load_gate_thresholds(gates, "publish"))
        gate_result = publish_gate.evaluate(payload, route_ids)
    else:
        payload = None
        warnings.append("工作流不包含 web_payload 阶段，跳过网页发布门禁")
        gate_result = GateResult(
            gate="publish", passed=True, checks=[], summary="跳过: 工作流未包含 web_payload 阶段"
        )

    generation = context.read_stage_output("project_generation")
    generation_score = generation.get("score") if isinstance(generation, dict) else None
    generation_passed = False
    if isinstance(generation, dict) and isinstance(generation_score, (int, float)):
        generation_passed = float(generation_score) >= 85.0 and generation.get("passed") is True
    generation_check = GateCheck(
        name="generated_project_functional_score",
        passed=generation_passed,
        detail=f"生成工程功能契约得分 {generation_score!r}/100（门槛 85）",
    )
    if not generation_passed:
        gate_result = gate_result.model_copy(
            update={
                "passed": False,
                "checks": [*gate_result.checks, generation_check],
                "summary": f"{gate_result.summary}; 生成工程功能契约未达 85 分",
            }
        )
    else:
        gate_result = gate_result.model_copy(
            update={"checks": [*gate_result.checks, generation_check]}
        )

    generated_quality_output: dict[str, Any] | None = None
    if context.options.offline:
        warnings.append("离线 fixture 跳过生成工程可执行质量检查")
    else:
        generated_quality = run_generated_quality_checks(context)
        generated_quality = _repair_failed_browser_once(context, generated_quality)
        generated_quality_output = generated_quality.model_dump(mode="json")
        quality_gate = _generated_quality_gate(generated_quality)
        gate_result = gate_result.model_copy(
            update={
                "passed": gate_result.passed and quality_gate.passed,
                "checks": [*gate_result.checks, *quality_gate.checks],
                "summary": f"{gate_result.summary}; {quality_gate.summary}",
            }
        )

    metrics_summary = store.read_json("reports/metrics_summary.json")
    result_gate_output: dict[str, Any] | None = None
    if isinstance(metrics_summary, dict):
        result_gate = ResultGate(load_gate_thresholds(gates, "supported"))
        result_result = result_gate.evaluate(metrics_summary)
        result_gate_output = result_result.model_dump(mode="json")
        if not result_result.passed:
            gate_result = gate_result.model_copy(
                update={
                    "passed": False,
                    "checks": gate_result.checks + result_result.checks,
                    "summary": f"{gate_result.summary}; {result_result.summary}",
                }
            )

    support = context.state.final_support_status
    if support is not None and payload is not None and payload.status != support:
        warnings.append(f"支持状态不一致: 状态机={support}, payload={payload.status}")

    if not gate_result.passed:
        failed = [check.name for check in gate_result.checks if not check.passed]
        return StageResult(
            stage="final_validation",
            status="failed",
            summary=f"发布门禁未通过: {', '.join(failed)}",
            gate_result=gate_result,
            output={
                "error_type": "gate_failed",
                "error_message": f"发布门禁未通过: {', '.join(failed)}",
                "result_gate": result_gate_output,
                "generated_quality": generated_quality_output,
            },
            warnings=warnings,
            exit_code=1,
        )
    return StageResult(
        stage="final_validation",
        status="passed",
        summary="最终门禁通过",
        gate_result=gate_result,
        output={
            "support_status": support,
            "route_ids_checked": len(route_ids),
            "generation_score": generation_score,
            "result_gate": result_gate_output,
            "generated_quality": generated_quality_output,
        },
        warnings=warnings,
    )


def publish_run_payload(context: "WorkflowContext") -> str:
    """在当前运行目录内刷新本地交付包，返回本地产品路径。"""
    from ..reporting.local_publish import build_local_publish

    details = build_local_publish(context)
    target = context.store.run_dir / "publish" / "local-product"
    context.store.write_json_atomic(
        "publish/published.flag",
        {
            "target": target.relative_to(context.store.run_dir).as_posix(),
            "run_id": context.run_id,
            "local_url": details["local_url"],
        },
    )
    return str(target)


def publish_web_stage(context: "WorkflowContext") -> StageResult:
    """最终门禁通过后刷新运行目录内的本地产品，不写现有产品目录。"""
    if context.state.stage_statuses.get("final_validation") != "passed":
        return StageResult(
            stage="publish_web",
            status="failed",
            summary="最终门禁未通过，禁止发布",
            output={"error_type": "gate_failed", "error_message": "最终门禁未通过，禁止发布"},
            exit_code=1,
        )
    target = publish_run_payload(context)
    context.emit("published_local", f"本地产品已生成到 {target}")
    return StageResult(
        stage="publish_web",
        status="passed",
        summary="本地产品与源码交付包已生成",
        output={"published_to": target, "local_url": "http://127.0.0.1:8130/web/"},
        artifacts=["publish/local-product/web/index.html", "publish/source_manifest.json"],
    )
