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
        reviews = {item.route_id: item for item in decision.route_reviews}
        by_id = {item.route.route_id: item for item in candidates}
        final_routes = [
            FinalRoute(
                route=by_id[route_id],
                final_rank=index,
                personalized_fit=reviews[route_id].personalized_fit_reason,
                cautions=reviews[route_id].cautions,
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
            personalized_fit="依据硬约束、五维基础评分和数据可信度形成该顺序。",
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
