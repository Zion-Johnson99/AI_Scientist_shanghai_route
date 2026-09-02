"""EvidenceAgent：evidence_extraction 阶段（设计文档 01 §12.2）。

从已注册来源的抽取文本中提取可追溯的 EvidenceCard；Claim 必须携带
``source_id`` 与证据位置，禁止虚构引用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..models import EvidenceCard, StageResult
from .base import BaseAgent, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

#: 传给模型的单来源文本上限（字符），避免超长上下文。
_SOURCE_TEXT_LIMIT = 6000


class EvidenceAgent(BaseAgent[EvidenceCard]):
    name = "evidence-agent"
    prompt_name = "evidence-extractor"
    output_model = EvidenceCard
    required_skills = ("scientific-evidence-hypothesis",)


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    sources = context.source_registry()
    if not sources:
        raise InputContractError(
            "来源注册表为空，无法抽取证据",
            stage="evidence_extraction",
            run_id=context.run_id,
            suggested_action="先执行 source_collection 阶段",
        )
    extracted = context.store.read_json("sources/extracted_texts.json") or {}
    problem_frame = read_dependency(context, "problem_framing")
    source_items: list[dict[str, Any]] = []
    for source_id, record in sources.items():
        document = extracted.get(source_id)
        pages = document.get("pages") if isinstance(document, dict) else None
        text = "\n".join(str(page) for page in pages)[:_SOURCE_TEXT_LIMIT] if pages else ""
        source_items.append(
            {
                "source_id": source_id,
                "title": record.title,
                "source_type": record.source_type,
                "year": record.year,
                "verification_status": record.verification_status,
                "text": text,
            }
        )
    return {
        "stage": "evidence_extraction",
        "iteration": context.iteration,
        "research_question": str(problem_frame.get("problem_statement", context.goal.question)),
        "sources": source_items,
        "policy": {"excerpt_max_chars": 400},
    }


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = EvidenceAgent()
    card, audit = agent.run(context, _build_payload(context))
    registered = set(context.source_registry())
    unknown = sorted({source_id for source_id in card.source_ids if source_id not in registered})
    if unknown:
        raise InputContractError(
            f"证据卡引用了未注册来源: {', '.join(unknown)}",
            stage="evidence_extraction",
            run_id=context.run_id,
            suggested_action="模型输出越权，交由引用门禁处理；可重试该阶段",
        )
    context.append_evidence_card(card)
    artifact = write_model_audit(context, "evidence_extraction", audit)
    return passed_result(
        context,
        card,
        summary=f"证据卡 {card.card_id}：{len(card.claims)} 条 Claim",
        artifacts=[artifact, "sources/evidence_cards.jsonl"],
    )
