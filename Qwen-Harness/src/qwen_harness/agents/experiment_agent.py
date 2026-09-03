"""ExperimentAgent：experiment_design 阶段（设计文档 01 §12.2）。

为选中假设设计预注册实验计划：基线、主/辅指标、距离约束、停止条件与
白名单模块操作。输出先通过结构化预注册检查（写入 GateResult）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import ExperimentPlan, GateCheck, GateResult, StageResult
from ..workflow.stages import ALLOWED_OPERATION_IDS
from .base import BaseAgent, gate_failed_result, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

DEFAULT_DETOUR_LIMIT_MAX = 0.30


class ExperimentAgent(BaseAgent[ExperimentPlan]):
    name = "experiment-planner"
    prompt_name = "experiment-planner"
    output_model = ExperimentPlan
    required_skills = (
        "evaluation-qwen-experiments",
        "xuhui-route-builder-engineering",
        "weather-environment-pipeline",
    )


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    selection = read_dependency(context, "hypothesis_selection")
    hypothesis_set = read_dependency(context, "hypothesis_generation")
    selected_id = str(selection.get("selected_hypothesis_id", ""))
    selected = next(
        (
            hypothesis
            for hypothesis in hypothesis_set.get("hypotheses", [])
            if hypothesis.get("hypothesis_id") == selected_id
        ),
        None,
    )
    if selected is None:
        raise InputContractError(
            f"未找到选中假设 {selected_id}",
            stage="experiment_design",
            run_id=context.run_id,
            suggested_action="检查 hypothesis_selection 输出",
        )
    detour_max = float(
        (context.quality_gates.get("experiment") or {}).get(
            "detour_limit_max", DEFAULT_DETOUR_LIMIT_MAX
        )
    )
    return {
        "stage": "experiment_design",
        "iteration": context.iteration,
        "selected_hypothesis": selected,
        "module_contracts": {
            "allowed_operations": sorted(ALLOWED_OPERATION_IDS),
            "write_operations": "v1 禁用（模块只读/导出）",
        },
        "derived_config": context.read_derived_config(),
        "constraints": {
            "detour_limit_max": detour_max,
            "target_distance_tolerance_suggested": 0.15,
        },
    }


def _preregistration_checks(context: "WorkflowContext", plan: ExperimentPlan) -> GateResult:
    checks: list[GateCheck] = []
    checks.append(
        GateCheck(
            name="baselines_pre_registered",
            passed=bool(plan.baselines),
            detail=f"基线 {len(plan.baselines)} 个",
        )
    )
    primary = [metric for metric in plan.metrics if metric.primary]
    secondary = [metric for metric in plan.metrics if not metric.primary]
    checks.append(
        GateCheck(
            name="primary_secondary_metric_split",
            passed=bool(primary) and bool(secondary),
            detail=f"主指标 {len(primary)} 个，辅助指标 {len(secondary)} 个",
        )
    )
    detour_max = float(
        (context.quality_gates.get("experiment") or {}).get(
            "detour_limit_max", DEFAULT_DETOUR_LIMIT_MAX
        )
    )
    checks.append(
        GateCheck(
            name="distance_constraints_declared",
            passed=0 < plan.detour_limit <= detour_max and plan.target_distance_tolerance > 0,
            detail=(
                f"detour_limit={plan.detour_limit}（上限 {detour_max}）, "
                f"target_distance_tolerance={plan.target_distance_tolerance}"
            ),
        )
    )
    checks.append(
        GateCheck(
            name="stop_conditions_declared",
            passed=bool(plan.stop_conditions),
            detail="已声明停止条件" if plan.stop_conditions else "缺少停止条件",
        )
    )
    operation_ids = [item.operation_id for item in plan.module_operations]
    unknown = sorted({op for op in operation_ids if op not in ALLOWED_OPERATION_IDS})
    checks.append(
        GateCheck(
            name="module_operations_whitelisted",
            passed=not unknown,
            detail=f"白名单外操作: {', '.join(unknown)}" if unknown else None,
        )
    )
    passed = all(check.passed for check in checks)
    failed = [check.name for check in checks if not check.passed]
    return GateResult(
        gate="experiment_preregistration",
        passed=passed,
        checks=checks,
        summary="预注册检查通过" if passed else f"预注册检查未通过: {', '.join(failed)}",
    )


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = ExperimentAgent()
    plan, audit = agent.run(context, _build_payload(context))
    selection = read_dependency(context, "hypothesis_selection")
    if plan.hypothesis_id != selection.get("selected_hypothesis_id"):
        raise InputContractError(
            f"实验计划的假设 {plan.hypothesis_id} 与选中假设不一致",
            stage="experiment_design",
            run_id=context.run_id,
        )
    gate_result = _preregistration_checks(context, plan)
    artifact = write_model_audit(context, "experiment_design", audit)
    if not gate_result.passed:
        return gate_failed_result(context, gate_result, "实验计划预注册检查未通过")
    return passed_result(
        context,
        plan,
        summary=(
            f"实验计划就绪：基线 {len(plan.baselines)}、指标 {len(plan.metrics)}、"
            f"操作 {len(plan.module_operations)}"
        ),
        gate_result=gate_result,
        artifacts=[artifact],
    )
