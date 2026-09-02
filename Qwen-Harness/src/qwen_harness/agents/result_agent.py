"""ResultAgent：实验结果解释（设计文档 01 §12.2）。

把模块输出与指标汇总解释为 ResultInterpretation；不用综合分自证综合
分，不扩大结论范围。该 Agent 供实验运行器或后续工作流调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import ResultInterpretation, StageResult
from .base import BaseAgent, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext


class ResultAgent(BaseAgent[ResultInterpretation]):
    name = "result-analyst"
    prompt_name = "result-analyst"
    output_model = ResultInterpretation
    required_skills = ("evaluation-qwen-experiments",)


def _module_results_summary(context: "WorkflowContext") -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for module in ("route", "environment", "evaluation", "web"):
        for label in ("preflight", "snapshot", "score_candidates", "export_payload"):
            data = context.store.read_json(f"modules/{module}/{label}.json")
            if isinstance(data, dict):
                summary[f"{module}.{label}"] = {
                    "status": data.get("status"),
                    "warnings": data.get("warnings", []),
                    "errors": data.get("errors", []),
                }
    return summary


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    metrics_summary = context.store.read_json("reports/metrics_summary.json")
    if not isinstance(metrics_summary, dict):
        raise InputContractError(
            "reports/metrics_summary.json 缺失",
            stage="experiment_analysis",
            run_id=context.run_id,
            suggested_action="先执行模块运行与统计汇总",
        )
    plan = read_dependency(context, "experiment_design")
    return {
        "stage": "experiment_analysis",
        "iteration": context.iteration,
        "metrics_summary": metrics_summary,
        "module_results": _module_results_summary(context),
        "experiment_plan": {
            "metrics": plan.get("metrics", []),
            "detour_limit": plan.get("detour_limit"),
            "acceptance_criteria": plan.get("acceptance_criteria", []),
        },
        "provenance": str(metrics_summary.get("provenance", "module_outputs")),
        "support_rules": {
            "insufficient_evidence": "inconclusive",
            "partial_support": "partially_supported",
            "opposite_direction": "unsupported",
        },
    }


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = ResultAgent()
    interpretation, audit = agent.run(context, _build_payload(context))
    artifact = write_model_audit(context, "experiment_analysis", audit)
    return passed_result(
        context,
        interpretation,
        summary=f"结果解释：{interpretation.status}（置信 {interpretation.confidence}）",
        artifacts=[artifact],
    )
