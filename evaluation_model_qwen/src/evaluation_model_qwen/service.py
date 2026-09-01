from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from .loaders import load_data
from .models import (
    ApiAudit,
    FinalRoute,
    RecommendationResult,
    RiskAssessment,
    ScoredRoute,
    UserProfile,
)
from .qwen_client import QwenClient, QwenClientError
from .scoring import evaluate_risk, score_routes

SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def evaluation_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_weights(path: Path | None = None) -> dict[str, Any]:
    resolved = path or evaluation_root() / "config" / "default_weights.json"
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"评价权重配置读取失败: path={resolved}, error={exc}") from exc
    if not isinstance(document, dict):
        raise TypeError(f"评价权重配置顶层需为对象: path={resolved}")
    return cast(dict[str, Any], document)


def recommend(
    profile: UserProfile,
    *,
    offline: bool = False,
    project_root: Path | None = None,
    route_catalog_path: Path | None = None,
    environment_path: Path | None = None,
    weights_path: Path | None = None,
    env_file: Path | None = None,
) -> RecommendationResult:
    bundle = load_data(
        project_root=project_root or evaluation_root(),
        route_catalog_path=route_catalog_path,
        environment_path=environment_path,
    )
    weights = load_weights(weights_path)
    risk = evaluate_risk(bundle, profile, weights)
    run_id = _run_id()
    generated_at = datetime.now(SHANGHAI_TZ)

    if risk.status == "paused":
        return RecommendationResult(
            run_id=run_id,
            generated_at=generated_at,
            status="paused",
            decision_source="none",
            profile=profile,
            risk=risk,
            base_candidates=[],
            final_routes=[],
            decision_summary="目标时段触发暂停条件，本次不生成户外路线。",
            data_generated_at=bundle.environment.generated_at,
            api_audit=ApiAudit(status="not_used"),
        )

    candidates = score_routes(bundle, profile, risk, weights)[:5]
    if not candidates:
        return RecommendationResult(
            run_id=run_id,
            generated_at=generated_at,
            status="no_candidates",
            decision_source="none",
            profile=profile,
            risk=risk,
            base_candidates=[],
            final_routes=[],
            decision_summary="当前约束下没有合格路线，请扩大距离、范围或放宽路线形态。",
            data_generated_at=bundle.environment.generated_at,
            api_audit=ApiAudit(status="not_used"),
        )

    if offline:
        return _fallback_result(
            run_id=run_id,
            generated_at=generated_at,
            profile=profile,
            risk=risk,
            candidates=candidates,
            data_generated_at=bundle.environment.generated_at,
            status="ok",
            decision_source="offline",
            audit=ApiAudit(status="not_used"),
            summary="离线模式采用 Python 基础排序。",
        )

    try:
        client = QwenClient.from_env(env_file or evaluation_root() / ".env")
        decision, audit = client.review(candidates, profile, risk)
        by_id = {item.route.route_id: item for item in candidates}
        final_routes = [
            FinalRoute(
                route=by_id[route_id],
                final_rank=index,
                personalized_fit=_verified_personalized_fit(by_id[route_id], profile),
                advantages=_fallback_advantages(by_id[route_id], profile, candidates),
                suggestions=_fallback_suggestions(by_id[route_id], risk),
                cautions=by_id[route_id].risk_notes,
            )
            for index, route_id in enumerate(decision.ranked_route_ids, start=1)
        ]
        return RecommendationResult(
            run_id=run_id,
            generated_at=generated_at,
            status="ok",
            decision_source="qwen",
            profile=profile,
            risk=risk,
            base_candidates=candidates,
            final_routes=final_routes,
            decision_summary=decision.decision_summary,
            profile_conflicts=decision.profile_conflicts,
            data_generated_at=bundle.environment.generated_at,
            api_audit=audit,
        )
    except QwenClientError as exc:
        return _fallback_result(
            run_id=run_id,
            generated_at=generated_at,
            profile=profile,
            risk=risk,
            candidates=candidates,
            data_generated_at=bundle.environment.generated_at,
            status="degraded",
            decision_source="python_fallback",
            audit=exc.audit,
            summary="千问审核暂不可用，当前结果采用 Python 基础排序。",
        )


def write_audit_result(result: RecommendationResult, runtime_root: Path | None = None) -> Path:
    target_root = runtime_root or evaluation_root() / "runtime" / "recommendations"
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / f"{result.run_id}.json"
    document = result.model_dump(mode="json")
    if document["profile"].get("free_text"):
        document["profile"]["free_text"] = "[已省略]"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _fallback_result(
    *,
    run_id: str,
    generated_at: datetime,
    profile: UserProfile,
    risk: RiskAssessment,
    candidates: list[ScoredRoute],
    data_generated_at: datetime,
    status: Literal["ok", "degraded"],
    decision_source: Literal["python_fallback", "offline"],
    audit: ApiAudit,
    summary: str,
) -> RecommendationResult:
    final_routes = [
        FinalRoute(
            route=item,
            final_rank=index,
            personalized_fit=_verified_personalized_fit(item, profile),
            advantages=_fallback_advantages(item, profile, candidates),
            suggestions=_fallback_suggestions(item, risk),
            cautions=item.risk_notes,
        )
        for index, item in enumerate(candidates, start=1)
    ]
    return RecommendationResult.model_validate(
        {
            "run_id": run_id,
            "generated_at": generated_at,
            "status": status,
            "decision_source": decision_source,
            "profile": profile,
            "risk": risk,
            "base_candidates": candidates,
            "final_routes": final_routes,
            "decision_summary": summary,
            "data_generated_at": data_generated_at,
            "api_audit": audit,
        }
    )


def _run_id() -> str:
    now = datetime.now(SHANGHAI_TZ).strftime("%Y%m%dT%H%M%S")
    return f"{now}-{uuid4().hex[:8]}"


def _fallback_advantages(
    candidate: ScoredRoute,
    profile: UserProfile,
    candidates: list[ScoredRoute],
) -> list[str]:
    advantages = ["距离符合目标范围"]
    matched_labels = _matched_interest_labels(candidate, profile)
    if matched_labels:
        advantages.append(f"路线数据支持{'、'.join(matched_labels[:3])}偏好")
    if profile.route_shape == "strict_loop" and candidate.route.route_shape == "strict_loop":
        advantages.append("闭环形态符合回到起点需求")
    pm25_value = _metric_value(candidate, "pm2_5")
    comparable_pm25 = [
        value for item in candidates if (value := _metric_value(item, "pm2_5")) is not None
    ]
    if pm25_value is not None and comparable_pm25 and pm25_value <= min(comparable_pm25):
        advantages.append("PM2.5 在候选中较低")
    if len(advantages) < 2 and candidate.data_confidence >= 0.7:
        advantages.append("路线数据可信度较高")
    if len(advantages) < 2:
        advantages.append("基础评分在候选中靠前")
    if profile.goal == "nearby" and candidate.access_distance_m is not None:
        advantages.append("到路线起点接驳较短")
    return advantages[:3]


def _verified_personalized_fit(candidate: ScoredRoute, profile: UserProfile) -> str:
    distance_km = candidate.route.distance_m / 1000
    clauses = [f"全程约{distance_km:g}公里，符合目标距离范围"]
    if profile.route_shape == "strict_loop" and candidate.route.route_shape == "strict_loop":
        clauses.append("闭环形态符合回到起点需求")
    matched_labels = _matched_interest_labels(candidate, profile)
    if matched_labels:
        clauses.append(f"路线数据支持{'、'.join(matched_labels)}偏好")
    return "；".join(clauses) + "。"


def _matched_interest_labels(candidate: ScoredRoute, profile: UserProfile) -> list[str]:
    labels = {
        "waterfront": "滨江",
        "park": "公园",
        "quiet": "安静",
        "coffee": "咖啡",
        "toilet": "厕所",
        "convenience": "便利设施",
    }
    matched = set(candidate.matched_preferences) & set(profile.interests)
    return [labels[interest] for interest in profile.interests if interest in matched]


def _fallback_suggestions(candidate: ScoredRoute, risk: RiskAssessment) -> list[str]:
    suggestions: list[str] = []
    if candidate.risk_notes:
        suggestions.append("查看详情中的环境数据限制")
    if risk.status == "warning" or risk.reasons:
        suggestions.append("出发前复核天气与空气提醒")
    if not suggestions:
        suggestions.append("出发前查看实时天气与预警")
    return suggestions[:2]


def _metric_value(candidate: ScoredRoute, metric_name: str) -> float | None:
    raw_value = candidate.environment_summary.get(metric_name, {}).get("value")
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    return None
