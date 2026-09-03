"""Deterministic quality gates (design doc sections 16, 18).

Thresholds are pre-registered in ``config/quality_gates.json`` and loaded via
``config.load_quality_gates``; runtime code must never adjust them ad hoc —
changes only happen through the feedback loop and the derived config. All
``evaluate`` methods are pure: no network, no model calls.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from ..logging_utils import get_logger
from ..models import (
    EvidenceCard,
    ExperimentPlan,
    GateCheck,
    GateResult,
    HypothesisReview,
    HypothesisSet,
    SourceRecord,
    WebPayload,
)

LOGGER = get_logger("gates")

_ABSOLUTE_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![\w./-])/home/|(?<![\w.])~/)"
)
_DEFAULT_FORBIDDEN_TOKENS = ("DASHSCOPE_API_KEY", "Authorization:", "sk-")


def load_gate_thresholds(quality_gates: Mapping[str, Any], section: str) -> dict[str, Any]:
    """Return one gate section's thresholds (validated upstream by config)."""
    data = quality_gates.get(section)
    if not isinstance(data, dict):
        return {}
    return dict(data)


class QualityGate:
    """Base class: thresholds in, GateResult out."""

    gate_name = "quality"

    def __init__(self, thresholds: Mapping[str, Any] | None = None) -> None:
        self.thresholds: dict[str, Any] = dict(thresholds or {})

    def _result(self, gate: str, checks: list[GateCheck], summary: str | None = None) -> GateResult:
        passed = all(check.passed for check in checks)
        if summary is None:
            failed = [check.name for check in checks if not check.passed]
            summary = "全部检查通过" if passed else f"未通过: {', '.join(failed)}"
        return GateResult(gate=gate, passed=passed, checks=checks, summary=summary)


class EvidenceGate(QualityGate):
    """Section 16.2: registered, verified sources backing every claim."""

    def evaluate(
        self, sources: Mapping[str, SourceRecord], cards: Sequence[EvidenceCard]
    ) -> GateResult:
        checks: list[GateCheck] = []
        verified = [
            record for record in sources.values() if record.verification_status == "verified"
        ]
        min_verified = int(self.thresholds.get("min_verified_sources", 5))
        checks.append(
            GateCheck(
                name="verified_source_count",
                passed=len(verified) >= min_verified,
                detail=f"已验证来源 {len(verified)}/{min_verified}",
            )
        )

        rate_min = float(self.thresholds.get("reference_verification_rate_min", 1.0))
        rate = (len(verified) / len(sources)) if sources else 1.0
        checks.append(
            GateCheck(
                name="reference_verification_rate",
                passed=rate >= rate_min,
                detail=f"验证率 {rate:.2f}（阈值 {rate_min:.2f}）",
            )
        )

        rejected_used = sorted(
            {
                source_id
                for card in cards
                for source_id in card.source_ids
                if source_id in sources and sources[source_id].verification_status == "rejected"
            }
        )
        checks.append(
            GateCheck(
                name="no_rejected_sources_used",
                passed=not rejected_used,
                detail=f"被拒来源仍被引用: {', '.join(rejected_used)}" if rejected_used else None,
            )
        )

        unregistered = sorted(
            {
                source_id
                for card in cards
                for source_id in card.source_ids
                if source_id not in sources
            }
        )
        checks.append(
            GateCheck(
                name="claims_reference_registered_sources",
                passed=not unregistered,
                detail=f"未注册来源: {', '.join(unregistered)}" if unregistered else None,
            )
        )

        require_location = bool(self.thresholds.get("require_evidence_location", True))
        missing_location = [
            claim.claim_id
            for card in cards
            for claim in card.claims
            if require_location and not claim.evidence_location.strip()
        ]
        checks.append(
            GateCheck(
                name="claims_have_evidence_location",
                passed=not missing_location,
                detail=f"缺少定位: {', '.join(missing_location[:8])}" if missing_location else None,
            )
        )

        excerpt_max = int(self.thresholds.get("excerpt_max_chars", 400))
        oversized = [
            claim.claim_id
            for card in cards
            for claim in card.claims
            if claim.short_excerpt and len(claim.short_excerpt) > excerpt_max
        ]
        checks.append(
            GateCheck(
                name="excerpt_length_within_policy",
                passed=not oversized,
                detail=f"超过 {excerpt_max} 字符的摘录: {', '.join(oversized[:8])}"
                if oversized
                else None,
            )
        )
        return self._result("evidence", checks)


class HypothesisGate(QualityGate):
    """Section 16.3: falsifiable, complete, selected hypotheses."""

    def evaluate(self, hypotheses: HypothesisSet, review: HypothesisReview | None) -> GateResult:
        checks: list[GateCheck] = []
        min_candidates = int(self.thresholds.get("min_candidates", 3))
        checks.append(
            GateCheck(
                name="candidate_count",
                passed=len(hypotheses.hypotheses) >= min_candidates,
                detail=f"候选假设 {len(hypotheses.hypotheses)}/{min_candidates}",
            )
        )

        require_falsification = bool(self.thresholds.get("require_falsification_criteria", True))
        require_variables = bool(self.thresholds.get("require_variables", True))
        not_falsifiable = [
            hypothesis.hypothesis_id
            for hypothesis in hypotheses.hypotheses
            if require_falsification and not hypothesis.falsification_criteria
        ]
        checks.append(
            GateCheck(
                name="falsifiable",
                passed=not not_falsifiable,
                detail=f"缺少可证伪标准: {', '.join(not_falsifiable)}" if not_falsifiable else None,
            )
        )

        incomplete = [
            hypothesis.hypothesis_id
            for hypothesis in hypotheses.hypotheses
            if (
                require_variables
                and not (hypothesis.independent_variables and hypothesis.dependent_variables)
            )
            or not hypothesis.expected_direction.strip()
            or not hypothesis.supporting_claim_ids
        ]
        checks.append(
            GateCheck(
                name="complete_fields",
                passed=not incomplete,
                detail=f"字段不完整: {', '.join(incomplete)}" if incomplete else None,
            )
        )

        ids = {hypothesis.hypothesis_id for hypothesis in hypotheses.hypotheses}
        recommended_ok = bool(hypotheses.recommended_hypothesis_id) and (
            hypotheses.recommended_hypothesis_id in ids
        )
        checks.append(
            GateCheck(
                name="recommended_exists",
                passed=recommended_ok,
                detail=f"recommended_hypothesis_id={hypotheses.recommended_hypothesis_id!r}",
            )
        )

        selected_ok = (
            review is not None
            and bool(review.selected_hypothesis_id)
            and (review.selected_hypothesis_id in ids)
        )
        checks.append(
            GateCheck(
                name="selected_exists",
                passed=selected_ok,
                detail="评审已选出假设" if selected_ok else "评审缺失或未选出假设",
            )
        )
        return self._result("hypothesis", checks)


class ExperimentGate(QualityGate):
    """Section 16.4: pre-registered baselines, metrics and constraints."""

    def evaluate(self, plan: ExperimentPlan, snapshot_hashes: Mapping[str, str]) -> GateResult:
        checks: list[GateCheck] = []

        require_baselines = bool(self.thresholds.get("require_baselines", True))
        checks.append(
            GateCheck(
                name="baselines_pre_registered",
                passed=(not require_baselines) or bool(plan.baselines),
                detail=f"基线 {len(plan.baselines)} 个",
            )
        )

        require_primary = bool(self.thresholds.get("require_primary_metric", True))
        primary = [metric for metric in plan.metrics if metric.primary]
        secondary = [metric for metric in plan.metrics if not metric.primary]
        checks.append(
            GateCheck(
                name="primary_secondary_metric_split",
                passed=(not require_primary) or (bool(primary) and bool(secondary)),
                detail=f"主指标 {len(primary)} 个，辅助指标 {len(secondary)} 个",
            )
        )

        detour_max = float(self.thresholds.get("detour_limit_max", 0.30))
        checks.append(
            GateCheck(
                name="distance_constraints_declared",
                passed=plan.detour_limit > 0 and plan.detour_limit <= detour_max,
                detail=f"detour_limit={plan.detour_limit}（上限 {detour_max}）",
            )
        )

        checks.append(
            GateCheck(
                name="stop_conditions_declared",
                passed=bool(plan.stop_conditions),
                detail="已声明停止条件" if plan.stop_conditions else "缺少停止条件",
            )
        )

        require_hashes = bool(self.thresholds.get("require_snapshot_hashes", True))
        checks.append(
            GateCheck(
                name="input_snapshot_hashes",
                passed=(not require_hashes) or bool(snapshot_hashes),
                detail=f"输入快照哈希 {len(snapshot_hashes)} 项",
            )
        )
        return self._result("experiment", checks)


class ResultGate(QualityGate):
    """Section 16.5 (uses the ``supported`` thresholds section)."""

    def evaluate(self, metrics_summary: Mapping[str, Any]) -> GateResult:
        checks: list[GateCheck] = []

        provenance = str(metrics_summary.get("provenance", ""))
        require_provenance = bool(self.thresholds.get("require_module_provenance", True))
        checks.append(
            GateCheck(
                name="module_provenance",
                passed=(not require_provenance)
                or provenance in {"module_outputs", "offline_fixtures"},
                detail=f"provenance={provenance!r}",
            )
        )

        metric_names = metrics_summary.get("metric_names") or []
        allow_sole_composite = bool(self.thresholds.get("composite_utility_as_sole_metric", False))
        checks.append(
            GateCheck(
                name="composite_not_sole_metric",
                passed=allow_sole_composite or len(metric_names) >= 2,
                detail=f"指标数 {len(metric_names)}",
            )
        )

        require_negative = bool(self.thresholds.get("require_negative_result_reporting", True))
        negative_reported = "negative_results" in metrics_summary
        checks.append(
            GateCheck(
                name="negative_results_reported",
                passed=(not require_negative) or negative_reported,
                detail=None if negative_reported else "缺少 negative_results 字段",
            )
        )
        return self._result("result", checks)


def determine_support_status(metrics_summary: Mapping[str, Any]) -> str:
    """Map pre-registered metric rates to the frozen support status."""
    keys = (
        "detour_pass_rate",
        "environment_win_rate",
        "preference_win_rate",
        "reference_verification_rate",
        "fatal_data_errors",
    )
    if any(key not in metrics_summary for key in keys):
        return "inconclusive"

    fatal_max = float(metrics_summary.get("fatal_data_errors_max", 0))
    if float(metrics_summary["fatal_data_errors"]) > fatal_max:
        return "inconclusive"

    detour = float(metrics_summary["detour_pass_rate"])
    environment_win = float(metrics_summary["environment_win_rate"])
    preference_win = float(metrics_summary["preference_win_rate"])
    if detour < 0.5 or environment_win < 0.5 or preference_win < 0.5:
        return "unsupported"

    if (
        detour >= float(metrics_summary.get("detour_pass_rate_min", 0.90))
        and environment_win >= float(metrics_summary.get("environment_win_rate_min", 0.60))
        and preference_win >= float(metrics_summary.get("preference_win_rate_min", 0.60))
        and float(metrics_summary["reference_verification_rate"])
        >= float(metrics_summary.get("reference_verification_rate_min", 1.0))
    ):
        return "supported"
    return "partially_supported"


class PublishGate(QualityGate):
    """Section 16.7: web payload safety before anything leaves runtime/."""

    def evaluate(self, payload: WebPayload, route_ids: set[str]) -> GateResult:
        checks: list[GateCheck] = []

        required_version = str(self.thresholds.get("require_schema_version", "1.0"))
        checks.append(
            GateCheck(
                name="schema_version",
                passed=payload.schema_version == required_version,
                detail=f"schema_version={payload.schema_version}",
            )
        )

        route = payload.selected_route
        needs_route = payload.status in {"supported", "partially_supported"}
        route_ok = route is not None and (not route_ids or route.route_id in route_ids)
        checks.append(
            GateCheck(
                name="selected_route_exists",
                passed=(not needs_route) or route_ok,
                detail=f"selected_route={route.route_id if route else None}",
            )
        )

        dump = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        forbid_paths = bool(self.thresholds.get("forbid_absolute_paths", True))
        absolute_hits = _ABSOLUTE_PATH_RE.findall(dump) if forbid_paths else []
        checks.append(
            GateCheck(
                name="no_absolute_paths",
                passed=not absolute_hits,
                detail=f"检出绝对路径 {len(absolute_hits)} 处" if absolute_hits else None,
            )
        )

        forbidden = list(self.thresholds.get("forbidden_tokens") or _DEFAULT_FORBIDDEN_TOKENS)
        token_hits = [token for token in forbidden if token in dump]
        checks.append(
            GateCheck(
                name="no_sensitive_tokens",
                passed=not token_hits,
                detail=f"检出敏感词: {', '.join(token_hits)}" if token_hits else None,
            )
        )

        require_https = bool(self.thresholds.get("require_https_references", True))

        def _ref_ok(url: str) -> bool:
            if not require_https:
                return True
            return url.startswith("https://") or url.startswith(("data/", "local:", "repository:"))

        bad_refs = [
            str(ref.get("url"))
            for ref in payload.references
            if isinstance(ref.get("url"), str) and not _ref_ok(str(ref["url"]))
        ]
        checks.append(
            GateCheck(
                name="references_https_or_local",
                passed=not bad_refs,
                detail=f"非法引用: {', '.join(bad_refs[:8])}" if bad_refs else None,
            )
        )

        bad_artifacts = [
            artifact for artifact in payload.artifacts if _ABSOLUTE_PATH_RE.search(artifact)
        ]
        checks.append(
            GateCheck(
                name="artifacts_relative_or_url",
                passed=not bad_artifacts,
                detail=f"非法产物路径: {', '.join(bad_artifacts[:8])}" if bad_artifacts else None,
            )
        )
        return self._result("publish", checks)


def build_gates(quality_gates: Mapping[str, Any]) -> dict[str, QualityGate]:
    """Factory used by the engine/stages to instantiate all five gates."""
    return {
        "evidence": EvidenceGate(load_gate_thresholds(quality_gates, "evidence")),
        "hypothesis": HypothesisGate(load_gate_thresholds(quality_gates, "hypothesis")),
        "experiment": ExperimentGate(load_gate_thresholds(quality_gates, "experiment")),
        "result": ResultGate(load_gate_thresholds(quality_gates, "supported")),
        "publish": PublishGate(load_gate_thresholds(quality_gates, "publish")),
    }
