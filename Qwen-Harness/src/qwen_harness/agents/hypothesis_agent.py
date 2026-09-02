"""HypothesisAgent：hypothesis_generation 阶段（设计文档 01 §12.2）。

基于知识缺口生成至少 3 个可证伪候选假设；证据支撑只引用 ``claim_id``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import HypothesisSet, StageResult
from .base import BaseAgent, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

MIN_CANDIDATES_DEFAULT = 3


class HypothesisAgent(BaseAgent[HypothesisSet]):
    name = "hypothesis-generator"
    prompt_name = "hypothesis-generator"
    output_model = HypothesisSet
    required_skills = ("scientific-evidence-hypothesis",)


def _known_claim_ids(context: "WorkflowContext") -> set[str]:
    evidence = read_dependency(context, "evidence_extraction")
    cards = evidence.get("items") if isinstance(evidence.get("items"), list) else [evidence]
    claim_ids: set[str] = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        for claim in card.get("claims", []) or []:
            claim_id = claim.get("claim_id")
            if isinstance(claim_id, str) and claim_id:
                claim_ids.add(claim_id)
    return claim_ids


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    gaps = read_dependency(context, "gap_analysis")
    return {
        "stage": "hypothesis_generation",
        "iteration": context.iteration,
        "knowledge_gaps": gaps,
        "known_claim_ids": sorted(_known_claim_ids(context)),
        "data_availability": {
            "available": [
                "徐汇区候选路线库与路线快照",
                "网格/站点融合 PM2.5 估计",
                "日级花粉背景代理",
                "0-100 噪声风险代理",
                "接驳成本、目标距离与偏好字段",
            ],
            "unavailable": ["逐地址实测暴露", "实时花粉浓度", "实测噪声分贝"],
        },
        "requirements": {"min_candidates": MIN_CANDIDATES_DEFAULT},
    }


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = HypothesisAgent()
    hypothesis_set, audit = agent.run(context, _build_payload(context))

    min_candidates = int(
        (context.quality_gates.get("hypothesis") or {}).get("min_candidates", MIN_CANDIDATES_DEFAULT)
    )
    if len(hypothesis_set.hypotheses) < min_candidates:
        raise InputContractError(
            f"候选假设不足 {min_candidates} 个（当前 {len(hypothesis_set.hypotheses)}）",
            stage="hypothesis_generation",
            run_id=context.run_id,
            suggested_action="重试该阶段以补齐候选假设",
        )
    ids = {hypothesis.hypothesis_id for hypothesis in hypothesis_set.hypotheses}
    if hypothesis_set.recommended_hypothesis_id not in ids:
        raise InputContractError(
            f"推荐假设 {hypothesis_set.recommended_hypothesis_id} 不在候选集中",
            stage="hypothesis_generation",
            run_id=context.run_id,
        )
    known_claims = _known_claim_ids(context)
    fabricated = sorted(
        {
            claim_id
            for hypothesis in hypothesis_set.hypotheses
            for claim_id in hypothesis.supporting_claim_ids
            if claim_id not in known_claims
        }
    )
    if fabricated:
        raise InputContractError(
            f"假设引用了不存在的 claim_id: {', '.join(fabricated)}",
            stage="hypothesis_generation",
            run_id=context.run_id,
            suggested_action="引用越权，修正后重试该阶段",
        )
    artifact = write_model_audit(context, "hypothesis_generation", audit)
    return passed_result(
        context,
        hypothesis_set,
        summary=f"生成候选假设 {len(hypothesis_set.hypotheses)} 个，推荐 {hypothesis_set.recommended_hypothesis_id}",
        artifacts=[artifact],
    )
