"""引用核验门禁（设计文档 01 §11.7、§18.1）。

:class:`CitationGate` 拒绝模型编造的 DOI / PMID / 作者 / 年份 / 数值：

- ``source_id`` 必须存在于来源注册表；
- 每条证据必须有可复查位置（页码 / 章节 / 摘要字段 / 模块路径）；
- 来源 ``verification_status`` 必须达标（默认 ``verified``）；
- Claim 中的数值必须能追溯到原文摘录、位置或来源年份；
- 参考文献按 DOI / PMID / 标题+年份去重；
- 标题、DOI、PMID 的组合一致（格式合法、互不冲突）。

``stage_handler`` 是 ``citation_validation`` 阶段的冻结处理器，合并
CitationGate 与 EvidenceGate 的检查结果，违规项写入 ``GateResult``
并按门禁语义返回（未通过即阶段失败）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..errors import InputContractError
from ..logging_utils import get_logger
from ..models import (
    EvidenceCard,
    EvidenceClaim,
    GateCheck,
    GateResult,
    ScientificPlan,
    SourceRecord,
    StageResult,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

LOGGER = get_logger("sources.citation_gate")

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PMID_RE = re.compile(r"^\d{1,12}$")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ALLOWED_MIN_STATUS = {"verified", "partial"}
#: verification_status 达标要求的默认最低级别。
DEFAULT_MIN_VERIFICATION = "verified"


def _normalize_title(title: str) -> str:
    return re.sub(r"\W+", " ", title or "").strip().lower()


class CitationGate:
    """纯函数式引用核验：不联网、不调模型。"""

    def __init__(self, min_verification: str = DEFAULT_MIN_VERIFICATION) -> None:
        self.min_verification = min_verification

    # -- claims ----------------------------------------------------------------
    def validate_claims(
        self,
        claims: list[EvidenceClaim],
        sources: dict[str, SourceRecord],
    ) -> GateResult:
        checks: list[GateCheck] = []

        unregistered = sorted(
            {claim.source_id for claim in claims if claim.source_id not in sources}
        )
        checks.append(
            GateCheck(
                name="source_id_registered",
                passed=not unregistered,
                detail=f"未注册来源: {', '.join(unregistered)}" if unregistered else None,
            )
        )

        missing_location = [
            claim.claim_id for claim in claims if not claim.evidence_location.strip()
        ]
        checks.append(
            GateCheck(
                name="evidence_location_present",
                passed=not missing_location,
                detail=f"缺少证据位置: {', '.join(missing_location[:8])}"
                if missing_location
                else None,
            )
        )

        allowed = set(_ALLOWED_MIN_STATUS) if self.min_verification == "partial" else {"verified"}
        below = sorted(
            {
                claim.claim_id
                for claim in claims
                if claim.source_id in sources
                and sources[claim.source_id].verification_status not in allowed
            }
        )
        checks.append(
            GateCheck(
                name="verification_status_sufficient",
                passed=not below,
                detail=f"来源核验未达标（要求 {self.min_verification}）: {', '.join(below[:8])}"
                if below
                else None,
            )
        )

        untraceable = self._untraceable_numbers(claims, sources)
        checks.append(
            GateCheck(
                name="numbers_traceable",
                passed=not untraceable,
                detail=f"数值不可追溯: {', '.join(untraceable[:8])}" if untraceable else None,
            )
        )

        duplicated = self._duplicate_reference_keys(
            [sources[claim.source_id] for claim in claims if claim.source_id in sources]
        )
        checks.append(
            GateCheck(
                name="references_deduplicated",
                passed=not duplicated,
                detail=f"重复引用: {', '.join(duplicated[:8])}" if duplicated else None,
            )
        )

        inconsistent = self._inconsistent_identifiers(sources)
        checks.append(
            GateCheck(
                name="identifier_consistency",
                passed=not inconsistent,
                detail="; ".join(inconsistent[:8]) if inconsistent else None,
            )
        )
        return self._result(checks, "引用与证据核验")

    # -- plan ------------------------------------------------------------------
    def validate_scientific_plan(
        self,
        plan: ScientificPlan,
        claims: dict[str, EvidenceClaim],
    ) -> GateResult:
        checks: list[GateCheck] = []
        duplicated = self._duplicate_reference_keys(plan.references)
        checks.append(
            GateCheck(
                name="references_deduplicated",
                passed=not duplicated,
                detail=f"重复参考文献: {', '.join(duplicated[:8])}" if duplicated else None,
            )
        )
        bad_reference = [
            ref.source_id
            for ref in plan.references
            if (ref.doi and not _DOI_RE.match(ref.doi))
            or (ref.pmid and not _PMID_RE.match(ref.pmid))
        ]
        checks.append(
            GateCheck(
                name="reference_identifier_format",
                passed=not bad_reference,
                detail=f"DOI/PMID 格式异常: {', '.join(bad_reference[:8])}"
                if bad_reference
                else None,
            )
        )
        missing_claims = sorted(
            {
                claim_id
                for claim_ids in plan.evidence_map.values()
                for claim_id in claim_ids
                if claim_id not in claims
            }
        )
        checks.append(
            GateCheck(
                name="evidence_map_traceable",
                passed=not missing_claims,
                detail=f"evidence_map 指向未知 claim: {', '.join(missing_claims[:8])}"
                if missing_claims
                else None,
            )
        )
        return self._result(checks, "科学计划引用核验")

    # -- 内部检查 ----------------------------------------------------------------
    @staticmethod
    def _untraceable_numbers(
        claims: list[EvidenceClaim], sources: dict[str, SourceRecord]
    ) -> list[str]:
        flagged: list[str] = []
        for claim in claims:
            numbers = _NUMBER_RE.findall(claim.claim)
            if not numbers:
                continue
            source = sources.get(claim.source_id)
            searchable = f"{claim.short_excerpt or ''}\n{claim.evidence_location}"
            for number in numbers:
                if number in searchable:
                    continue
                if source is not None and source.year is not None and number == str(source.year):
                    continue
                flagged.append(claim.claim_id)
                break
        return flagged

    @staticmethod
    def _duplicate_reference_keys(records: list[Any]) -> list[str]:
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for record in records:
            title = _normalize_title(getattr(record, "title", "") or "")
            year = getattr(record, "year", None)
            keys: list[str] = []
            doi = getattr(record, "doi", None)
            pmid = getattr(record, "pmid", None)
            if doi:
                keys.append(f"doi:{doi.lower()}")
            if pmid:
                keys.append(f"pmid:{pmid}")
            if title:
                keys.append(f"title:{title}:{year}")
            source_id = str(getattr(record, "source_id", "?"))
            for key in keys:
                if key in seen and seen[key] != source_id:
                    duplicates.append(f"{seen[key]}~{source_id}({key.split(':')[0]})")
                seen.setdefault(key, source_id)
        return duplicates

    @staticmethod
    def _inconsistent_identifiers(sources: dict[str, SourceRecord]) -> list[str]:
        problems: list[str] = []
        doi_owner: dict[str, str] = {}
        pmid_owner: dict[str, str] = {}
        for source_id, record in sources.items():
            if record.doi:
                if not _DOI_RE.match(record.doi):
                    problems.append(f"{source_id}: DOI 格式非法 {record.doi}")
                elif doi_owner.setdefault(record.doi.lower(), source_id) != source_id:
                    problems.append(f"{source_id}: DOI {record.doi} 被多个来源共用")
            if record.pmid:
                if not _PMID_RE.match(record.pmid):
                    problems.append(f"{source_id}: PMID 非法 {record.pmid}")
                elif pmid_owner.setdefault(record.pmid, source_id) != source_id:
                    problems.append(f"{source_id}: PMID {record.pmid} 被多个来源共用")
            if record.doi and record.pmid and not record.title.strip():
                problems.append(f"{source_id}: 同时含 DOI 与 PMID 但缺少标题")
        return problems

    @staticmethod
    def _result(checks: list[GateCheck], label: str) -> GateResult:
        passed = all(check.passed for check in checks)
        failed = [check.name for check in checks if not check.passed]
        return GateResult(
            gate="citation",
            passed=passed,
            checks=checks,
            summary=f"{label}通过" if passed else f"{label}未通过: {', '.join(failed)}",
        )


# ---------------------------------------------------------------------------
# citation_validation 阶段处理器
# ---------------------------------------------------------------------------
def _load_evidence_cards(context: "WorkflowContext") -> list[EvidenceCard]:
    cards = list(context.store.load_evidence_cards())
    data = context.read_stage_output("evidence_extraction")
    if data is None:
        raise InputContractError(
            "evidence_extraction 阶段尚无输出",
            stage="citation_validation",
            run_id=context.run_id,
            suggested_action="先执行证据抽取阶段",
        )
    payloads: list[dict[str, Any]]
    if isinstance(data.get("items"), list):
        payloads = [item for item in data["items"] if isinstance(item, dict)]
    else:
        payloads = [data]
    known_ids = {card.card_id for card in cards}
    for payload in payloads:
        try:
            card = EvidenceCard.model_validate(payload)
        except Exception as exc:  # pydantic ValidationError
            raise InputContractError(
                f"evidence_extraction 输出不符合 EvidenceCard 契约: {exc}",
                stage="citation_validation",
                run_id=context.run_id,
            ) from exc
        if card.card_id not in known_ids:
            cards.append(card)
            known_ids.add(card.card_id)
    if not cards:
        raise InputContractError(
            "未找到任何证据卡",
            stage="citation_validation",
            run_id=context.run_id,
            suggested_action="检查 evidence_extraction 阶段输出",
        )
    return cards


def stage_handler(context: "WorkflowContext") -> StageResult:
    """citation_validation：引用核验 + 证据门禁，违规即失败。"""
    sources = context.source_registry()
    if not sources:
        raise InputContractError(
            "来源注册表为空",
            stage="citation_validation",
            run_id=context.run_id,
            suggested_action="先执行 source_collection 阶段",
        )
    cards = _load_evidence_cards(context)
    claims = [claim for card in cards for claim in card.claims]

    min_verification = str(
        (context.quality_gates.get("evidence") or {}).get(
            "min_verification_status", DEFAULT_MIN_VERIFICATION
        )
    )
    citation = CitationGate(min_verification=min_verification).validate_claims(claims, sources)
    evidence = context.gates["evidence"].evaluate(sources, cards)

    checks = list(citation.checks) + list(evidence.checks)
    passed = citation.passed and evidence.passed
    gate_result = GateResult(
        gate="citation_validation",
        passed=passed,
        checks=checks,
        summary=(citation.summary or "") + "; " + (evidence.summary or ""),
    )
    context.store.write_json_atomic(
        "stages/citation_validation/gate_detail.json", gate_result.model_dump(mode="json")
    )
    if not passed:
        failed = [check.name for check in checks if not check.passed]
        return StageResult(
            stage="citation_validation",
            status="failed",
            summary=f"引用核验未通过: {', '.join(failed)}",
            output={
                "error_type": "gate_failed",
                "error_message": "存在编造引用或证据不可追溯（拒绝虚构 DOI/PMID/数值）",
                "claims_checked": len(claims),
            },
            gate_result=gate_result,
            exit_code=1,
        )
    return StageResult(
        stage="citation_validation",
        status="passed",
        summary=f"引用核验通过：{len(claims)} 条 Claim / {len(sources)} 个来源",
        output={
            "claims_checked": len(claims),
            "sources_checked": len(sources),
            "cards": len(cards),
        },
        gate_result=gate_result,
    )
