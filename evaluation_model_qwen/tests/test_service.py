from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from evaluation_model_qwen.loaders import load_data
from evaluation_model_qwen.models import (
    ApiAudit,
    Coordinate,
    QwenDecision,
    QwenRouteReview,
    RiskAssessment,
    ScoredRoute,
    UserProfile,
)
from evaluation_model_qwen.qwen_client import QwenApiError, QwenClient
from evaluation_model_qwen.service import recommend, write_audit_result


class FailingReviewClient:
    def review(
        self,
        top5: list[ScoredRoute],
        profile: UserProfile,
        risk: RiskAssessment,
    ) -> tuple[object, ApiAudit]:
        del top5, profile, risk
        raise QwenApiError(
            ApiAudit(
                status="degraded",
                model="qwen3.8-flash",
                error_type="rate_limit",
                error_message="千问请求触发限流",
            )
        )


def failing_from_env(
    cls: type[QwenClient],
    env_file: Path | None = None,
    *,
    client: object | None = None,
) -> FailingReviewClient:
    del cls, env_file, client
    return FailingReviewClient()


def test_service_falls_back_and_audit_omits_full_free_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot_time = load_data().environment.generated_at
    profile = UserProfile(
        route_mode="walk",
        target_time=snapshot_time,
        distance_min_m=500,
        target_distance_m=2500,
        distance_max_m=6000,
        free_text="这段完整需求只用于个性化，审计记录需要省略",
    )
    monkeypatch.setattr(QwenClient, "from_env", classmethod(failing_from_env))

    result = recommend(profile)
    audit_path = write_audit_result(result, tmp_path)
    audit_document = json.loads(audit_path.read_text(encoding="utf-8"))

    assert result.status == "degraded"
    assert result.decision_source == "python_fallback"
    assert len(result.base_candidates) == 5
    assert [item.route.route.route_id for item in result.final_routes] == [
        item.route.route_id for item in result.base_candidates
    ]
    assert result.api_audit.error_type == "rate_limit"
    assert all(2 <= len(item.advantages) <= 3 for item in result.final_routes)
    assert all(1 <= len(item.suggestions) <= 2 for item in result.final_routes)
    assert audit_document["profile"]["free_text"] == "[已省略]"


class HallucinatingReviewClient:
    def review(
        self,
        top5: list[ScoredRoute],
        profile: UserProfile,
        risk: RiskAssessment,
    ) -> tuple[QwenDecision, ApiAudit]:
        del profile, risk
        route_ids = [item.route.route_id for item in top5]
        return (
            QwenDecision(
                profile_summary="测试",
                ranked_route_ids=route_ids,
                route_reviews=[
                    QwenRouteReview(
                        route_id=route_id,
                        personalized_fit_reason="沿途拥有未经输入证实的绝佳江景与休息站",
                        advantages=["绝佳江景", "补给站很多"],
                        suggestions=["放心出发"],
                    )
                    for route_id in route_ids
                ],
                decision_summary="维持原排序",
                review_status="approved",
            ),
            ApiAudit(status="ok", model="qwen3.8-flash"),
        )


def hallucinating_from_env(
    cls: type[QwenClient],
    env_file: Path | None = None,
    *,
    client: object | None = None,
) -> HallucinatingReviewClient:
    del cls, env_file, client
    return HallucinatingReviewClient()


def test_service_replaces_model_route_copy_with_verified_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_time = load_data().environment.generated_at
    profile = UserProfile(
        route_mode="walk",
        target_time=snapshot_time,
        distance_min_m=500,
        target_distance_m=2500,
        distance_max_m=6000,
        route_shape="strict_loop",
        free_text="想走闭环路线",
    )
    monkeypatch.setattr(QwenClient, "from_env", classmethod(hallucinating_from_env))

    result = recommend(profile)

    assert result.decision_source == "qwen"
    assert all("绝佳江景" not in item.personalized_fit for item in result.final_routes)
    assert all("补给站很多" not in item.advantages for item in result.final_routes)
    assert all("距离" in item.personalized_fit for item in result.final_routes)


def test_real_catalog_waterfront_loop_request_keeps_semantics_and_verified_fit() -> None:
    snapshot_time = load_data().environment.generated_at
    profile = UserProfile(
        route_mode="bike",
        target_time=snapshot_time + timedelta(minutes=30),
        distance_min_m=9000,
        target_distance_m=10000,
        distance_max_m=11000,
        origin=Coordinate(lng_gcj02=121.433095, lat_gcj02=31.199005),
        search_radius_m=5000,
        goal="scenery",
        route_shape="strict_loop",
        interests=["waterfront"],
        free_text="周末骑行 10 公里左右，想看滨江风景，最后回到出发点",
    )

    result = recommend(profile, offline=True)

    assert result.status == "ok"
    assert result.final_routes
    assert result.final_routes[0].route.matched_preferences == ["waterfront"]
    assert "滨江偏好" in result.final_routes[0].personalized_fit
    assert all(item.route.route.route_shape == "strict_loop" for item in result.final_routes)
    assert all(item.route.route.route_id != "XH_BIKE_0077" for item in result.final_routes)


def test_real_catalog_filters_near_duplicate_routes_and_reports_missing_toilet() -> None:
    snapshot_time = load_data().environment.generated_at
    profile = UserProfile(
        route_mode="run",
        target_time=snapshot_time,
        distance_min_m=10000,
        target_distance_m=12000,
        distance_max_m=14000,
        interests=["toilet"],
    )

    result = recommend(profile, offline=True)

    route_ids = [item.route.route.route_id for item in result.final_routes]
    assert not {"XH_RUN_0053", "XH_RUN_0059"}.issubset(route_ids)
    assert "没有已核实的厕所" in result.decision_summary
    assert any("没有已核实的厕所" in item for item in result.profile_conflicts)
