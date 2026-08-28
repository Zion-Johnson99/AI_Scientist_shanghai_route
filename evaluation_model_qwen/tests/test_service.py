from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_model_qwen.loaders import load_data
from evaluation_model_qwen.models import ApiAudit, RiskAssessment, ScoredRoute, UserProfile
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
                model="qwen3.7-plus",
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
    assert audit_document["profile"]["free_text"] == "[已省略]"
