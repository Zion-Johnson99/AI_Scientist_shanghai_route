"""FeedbackAgent：feedback_decision 阶段（设计文档 01 §12.2、§17）。

根据结果解释与迭代状态决定继续迭代或停止；自动动作必须在允许类型内，
建议类动作只写提案不执行。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import (
    AUTOMATIC_FEEDBACK_ACTIONS,
    PROPOSED_FEEDBACK_ACTIONS,
    IterationDecision,
    StageResult,
)
from .base import BaseAgent, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext


class FeedbackAgent(BaseAgent[IterationDecision]):
    name = "feedback-planner"
    prompt_name = "feedback-planner"
    output_model = IterationDecision
    required_skills = ("qwen-harness-orchestration",)


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    interpretation = read_dependency(context, "experiment_analysis")
    state = context.state
    return {
        "stage": "feedback_decision",
        "iteration": state.iteration,
        "max_iterations": state.max_iterations,
        "interpretation": interpretation,
        "applied_action_log": list(state.applied_action_log),
        "automatic_action_whitelist": sorted(AUTOMATIC_FEEDBACK_ACTIONS),
        "proposal_action_whitelist": sorted(PROPOSED_FEEDBACK_ACTIONS),
        "offline": context.options.offline,
    }


def _sanitize_actions(decision: IterationDecision) -> tuple[IterationDecision, list[str]]:
    """过滤未知动作类型；返回清洗后的决策与警告。"""
    warnings: list[str] = []
    allowed_auto = set(AUTOMATIC_FEEDBACK_ACTIONS)
    kept: list[dict[str, object]] = []
    for action in decision.automatic_actions:
        name = str(action.get("action", ""))
        if name in allowed_auto:
            kept.append(action)
        else:
            warnings.append(f"未知自动动作已移除: {name}")
    proposals: list[dict[str, object]] = []
    for change in decision.proposed_code_changes:
        name = str(change.get("action", ""))
        if name in PROPOSED_FEEDBACK_ACTIONS or name.startswith("propose_"):
            proposals.append(change)
        else:
            warnings.append(f"未知建议动作已移除: {name}")
    if kept == decision.automatic_actions and proposals == decision.proposed_code_changes:
        return decision, warnings
    return decision.model_copy(
        update={"automatic_actions": kept, "proposed_code_changes": proposals}
    ), warnings


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = FeedbackAgent()
    decision, audit = agent.run(context, _build_payload(context))
    decision, warnings = _sanitize_actions(decision)
    if decision.status == "continue" and not decision.automatic_actions:
        raise InputContractError(
            "status=continue 时必须给出至少一个自动动作",
            stage="feedback_decision",
            run_id=context.run_id,
            suggested_action="重试该阶段；无可行动作时改为 stop_* 状态",
        )
    artifact = write_model_audit(context, "feedback_decision", audit)
    return passed_result(
        context,
        decision,
        summary=f"迭代决策: {decision.status}",
        artifacts=[artifact],
        warnings=warnings,
    )
