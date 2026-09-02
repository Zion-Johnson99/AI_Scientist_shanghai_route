"""CriticAgent：hypothesis_critique 与 hypothesis_selection 阶段。

评审与选择使用同一角色提示词但阶段契约不同（01 §12.2）：

- ``stage_handler``（critique）：对每个候选给出独立评审意见。
- ``selection_stage_handler``（selection）：在评审基础上做出最终选择，
  并运行 HypothesisGate；门禁未通过即阶段失败。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import HypothesisReview, HypothesisSet, StageResult
from .base import BaseAgent, gate_failed_result, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext


class CriticAgent(BaseAgent[HypothesisReview]):
    name = "hypothesis-critic"
    prompt_name = "hypothesis-critic"
    output_model = HypothesisReview
    required_skills = ("scientific-evidence-hypothesis",)


def _load_hypothesis_set(context: "WorkflowContext") -> HypothesisSet:
    data = read_dependency(context, "hypothesis_generation")
    try:
        return HypothesisSet.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        raise InputContractError(
            f"hypothesis_generation 输出不符合 HypothesisSet 契约: {exc}",
            stage="hypothesis_critique",
            run_id=context.run_id,
        ) from exc


def _assessments_cover_all(review: HypothesisReview, hypothesis_set: HypothesisSet) -> list[str]:
    assessed = {assessment.hypothesis_id for assessment in review.assessments}
    return sorted(
        hypothesis.hypothesis_id
        for hypothesis in hypothesis_set.hypotheses
        if hypothesis.hypothesis_id not in assessed
    )


def stage_handler(context: "WorkflowContext") -> StageResult:
    """hypothesis_critique：独立评审全部候选假设。"""
    agent = CriticAgent()
    hypothesis_set = _load_hypothesis_set(context)
    payload: dict[str, Any] = {
        "stage": "hypothesis_critique",
        "iteration": context.iteration,
        "mode": "critique",
        "hypotheses": hypothesis_set.model_dump(mode="json"),
        "evidence_cards": context.read_stage_output("evidence_extraction") or {},
    }
    review, audit = agent.run(context, payload)
    missing = _assessments_cover_all(review, hypothesis_set)
    if missing:
        raise InputContractError(
            f"评审未覆盖候选假设: {', '.join(missing)}",
            stage="hypothesis_critique",
            run_id=context.run_id,
            suggested_action="重试该阶段，补齐每个候选的评审",
        )
    artifact = write_model_audit(context, "hypothesis_critique", audit)
    return passed_result(
        context,
        review,
        summary=f"评审完成：{len(review.assessments)} 个候选，冲突 {len(review.conflicts)} 项",
        artifacts=[artifact],
    )


def selection_stage_handler(context: "WorkflowContext") -> StageResult:
    """hypothesis_selection：最终选择并运行 HypothesisGate。"""
    agent = CriticAgent()
    hypothesis_set = _load_hypothesis_set(context)
    critique = context.read_stage_output("hypothesis_critique")
    if critique is None:
        raise InputContractError(
            "hypothesis_critique 阶段尚无输出",
            stage="hypothesis_selection",
            run_id=context.run_id,
            suggested_action="先执行假设评审阶段",
        )
    payload: dict[str, Any] = {
        "stage": "hypothesis_selection",
        "iteration": context.iteration,
        "mode": "selection",
        "hypotheses": hypothesis_set.model_dump(mode="json"),
        "critique": critique,
    }
    review, audit = agent.run(context, payload)

    ids = {hypothesis.hypothesis_id for hypothesis in hypothesis_set.hypotheses}
    if review.selected_hypothesis_id not in ids:
        raise InputContractError(
            f"选出的假设 {review.selected_hypothesis_id} 不在候选集中",
            stage="hypothesis_selection",
            run_id=context.run_id,
        )
    gate_result = context.gates["hypothesis"].evaluate(hypothesis_set, review)
    artifact = write_model_audit(context, "hypothesis_selection", audit)
    if not gate_result.passed:
        return gate_failed_result(context, gate_result, "假设门禁未通过")
    return passed_result(
        context,
        review,
        summary=f"选定假设 {review.selected_hypothesis_id}",
        gate_result=gate_result,
        artifacts=[artifact],
    )
