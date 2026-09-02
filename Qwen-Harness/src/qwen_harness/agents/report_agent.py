"""ReportAgent：scientific_report 阶段（设计文档 01 §12.2、§19.1）。

把全部已通过的上游产物整合为 ScientificPlan，并写入
``reports/scientific_plan.json``（final_validation 的前置产物）。
参考文献字段逐字来自来源注册表，输出经 CitationGate 计划核验。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ..llm.audit import utc_now
from ..models import EvidenceClaim, ScientificPlan, StageResult
from ..reporting.full_run_report import write_full_run_report
from ..sources.citation_gate import CitationGate
from .base import BaseAgent, gate_failed_result, passed_result, read_dependency, write_model_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext


class ReportAgent(BaseAgent[ScientificPlan]):
    name = "report-writer"
    prompt_name = "report-writer"
    output_model = ScientificPlan
    required_skills = ("scientific-evidence-hypothesis", "qwen-harness-orchestration")


def _evidence_inputs(context: "WorkflowContext") -> tuple[dict[str, Any], dict[str, EvidenceClaim]]:
    evidence = read_dependency(context, "evidence_extraction")
    cards = evidence.get("items") if isinstance(evidence.get("items"), list) else [evidence]
    claims: dict[str, EvidenceClaim] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        for claim_data in card.get("claims", []) or []:
            try:
                claim = EvidenceClaim.model_validate(claim_data)
            except ValidationError:  # 损坏条目跳过
                continue
            claims[claim.claim_id] = claim
    return evidence, claims


def _build_payload(context: "WorkflowContext") -> dict[str, Any]:
    sources = context.source_registry()
    evidence, _claims = _evidence_inputs(context)
    return {
        "stage": "scientific_report",
        "iteration": context.iteration,
        "problem_frame": read_dependency(context, "problem_framing"),
        "evidence_cards": evidence,
        "knowledge_gaps": read_dependency(context, "gap_analysis"),
        "hypothesis_set": read_dependency(context, "hypothesis_generation"),
        "hypothesis_review": read_dependency(context, "hypothesis_selection"),
        "experiment_plan": read_dependency(context, "experiment_design"),
        "interpretation": read_dependency(context, "experiment_analysis"),
        "iteration_decision": read_dependency(context, "feedback_decision"),
        "source_registry": {
            source_id: record.model_dump(mode="json") for source_id, record in sources.items()
        },
        "run_meta": {
            "run_id": context.run_id,
            "workflow": context.workflow.name,
            "offline": context.options.offline,
        },
    }


def stage_handler(context: "WorkflowContext") -> StageResult:
    agent = ReportAgent()
    plan, audit = agent.run(context, _build_payload(context))
    plan = plan.model_copy(update={"run_id": context.run_id, "generated_at": utc_now()})

    _evidence, claims = _evidence_inputs(context)
    gate_result = CitationGate().validate_scientific_plan(plan, claims)
    artifact = write_model_audit(context, "scientific_report", audit)
    if not gate_result.passed:
        return gate_failed_result(context, gate_result, "科学计划引用核验未通过")

    report_path = context.store.write_json_atomic(
        "reports/scientific_plan.json", plan.model_dump(mode="json")
    )
    full_report_path = write_full_run_report(context)
    return passed_result(
        context,
        plan,
        summary=f"科学计划就绪：参考文献 {len(plan.references)} 条",
        gate_result=gate_result,
        artifacts=[
            artifact,
            str(report_path.relative_to(context.store.run_dir).as_posix()),
            str(full_report_path.relative_to(context.store.run_dir).as_posix()),
        ],
    )
