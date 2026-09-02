"""GapAgent：gap_analysis 阶段（设计文档 01 §12.2）。

从证据卡识别知识缺口；缺口必须由已有 ``claim_id`` 支撑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import KnowledgeGapSet, StageResult
from .base import BaseAgent, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext


class GapAgent(BaseAgent[KnowledgeGapSet]):
    name = "gap-analyst"
    prompt_name = "gap-analyst"
    output_model = KnowledgeGapSet
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
    problem_frame = read_dependency(context, "problem_framing")
    evidence = read_dependency(context, "evidence_extraction")
    cards = evidence.get("items") if isinstance(evidence.get("items"), list) else [evidence]
    claims: list[dict[str, Any]] = []
    for card in cards:
        for claim in card.get("claims", []) if isinstance(card, dict) else []:
            claims.append(
                {
                    "claim_id": claim.get("claim_id"),
                    "source_id": claim.get("source_id"),
                    "claim": claim.get("claim"),
                    "evidence_type": claim.get("evidence_type"),
                    "support_strength": claim.get("support_strength"),
                    "caveats": claim.get("caveats", []),
                }
            )
    if not claims:
        raise InputContractError(
            "证据卡中没有任何 Claim，无法进行缺口分析",
            stage="gap_analysis",
            run_id=context.run_id,
            suggested_action="重新执行 evidence_extraction 阶段",
        )
    return {
        "stage": "gap_analysis",
        "iteration": context.iteration,
        "problem_frame": problem_frame,
        "claims": claims,
        "project_context": {
            "available_data": [
                "徐汇区候选路线库（步行/跑步/骑行）",
                "网格/站点融合 PM2.5 估计、日级花粉代理、0-100 噪声风险代理",
                "接驳成本与入口可达性字段",
            ]
        },
    }


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = GapAgent()
    gap_set, audit = agent.run(context, _build_payload(context))
    known_claims = _known_claim_ids(context)
    unsupported = sorted(
        {
            claim_id
            for gap in gap_set.gaps
            for claim_id in gap.supported_by_claim_ids
            if claim_id not in known_claims
        }
    )
    if unsupported:
        raise InputContractError(
            f"缺口引用了不存在的 claim_id: {', '.join(unsupported)}",
            stage="gap_analysis",
            run_id=context.run_id,
            suggested_action="引用越权，修正后重试该阶段",
        )
    artifact = write_model_audit(context, "gap_analysis", audit)
    return passed_result(
        context,
        gap_set,
        summary=f"识别知识缺口 {len(gap_set.gaps)} 个",
        artifacts=[artifact],
    )
