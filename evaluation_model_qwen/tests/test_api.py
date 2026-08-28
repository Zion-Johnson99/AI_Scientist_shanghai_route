from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from evaluation_model_qwen import api
from evaluation_model_qwen.loaders import LoaderError, load_data
from evaluation_model_qwen.models import RecommendationResult, UserProfile
from evaluation_model_qwen.service import recommend, write_audit_result


@pytest.fixture(scope="module")
def profile() -> UserProfile:
    snapshot_time = load_data().environment.generated_at
    return UserProfile(
        route_mode="walk",
        target_time=snapshot_time,
        distance_min_m=500,
        target_distance_m=2500,
        distance_max_m=6000,
        free_text="安静一些，DASHSCOPE_API_KEY=secret-value",
    )


@pytest.fixture(scope="module")
def offline_result(profile: UserProfile) -> RecommendationResult:
    return recommend(profile, offline=True)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("EVALUATION_MODEL_QWEN_OFFLINE", "1")
    monkeypatch.setenv("EVALUATION_MODEL_QWEN_AUDIT_ROOT", str(tmp_path / "audit"))
    return cast(Any, TestClient(api.create_app()))


def test_health_reports_data_and_qwen_configuration_without_secret(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "do-not-return-this-secret")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.invalid/v1")

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    document = response.json()
    assert document["status"] == "ok"
    assert document["data"]["status"] in {"ok", "partial", "stale", "no_data", "error"}
    assert datetime.fromisoformat(document["data"]["generated_at"])
    assert document["qwen"] == {"configured": True, "offline": True}
    assert "do-not-return-this-secret" not in response.text


def test_questionnaire_returns_ui_ready_chinese_options(client: Any) -> None:
    response = client.get("/api/v1/questionnaire")

    assert response.status_code == 200
    document = response.json()
    assert document["target_times"] == [
        {"value": "now", "label": "现在"},
        {"value": "plus_2h", "label": "两小时后"},
        {"value": "custom", "label": "自定义时间"},
    ]
    assert [item["value"] for item in document["search_scopes"]] == [
        "nearby_3000",
        "nearby_5000",
        "nearby_8000",
        "area",
        "all_xuhui",
    ]
    assert [item["value"] for item in document["route_shapes"]] == [
        "any",
        "strict_loop",
        "one_way",
    ]
    for field in (
        "route_modes",
        "goals",
        "experience_levels",
        "age_groups",
        "areas",
        "interests",
        "sensitivities",
        "target_times",
        "search_scopes",
        "route_shapes",
    ):
        assert document[field]
        assert all(item["value"] and item["label"] for item in document[field])
        assert all(
            any("\u4e00" <= char <= "\u9fff" for char in item["label"]) for item in document[field]
        )
    for ranges in document["distance_ranges"].values():
        assert ranges
        assert all(item["value"] and item["label"] for item in ranges)


@pytest.mark.parametrize("status", ["ok", "degraded", "paused", "no_candidates"])
def test_recommendation_business_statuses_return_200_and_write_audit(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    profile: UserProfile,
    offline_result: RecommendationResult,
    status: str,
) -> None:
    result = offline_result.model_copy(update={"status": status})
    calls: dict[str, Any] = {}

    def fake_recommend(received: UserProfile, *, offline: bool) -> RecommendationResult:
        calls["profile"] = received
        calls["offline"] = offline
        return result

    def fake_write_audit(received: RecommendationResult, runtime_root: Path) -> Path:
        calls["audit_result"] = received
        calls["runtime_root"] = runtime_root
        return runtime_root / f"{received.run_id}.json"

    monkeypatch.setattr(api, "recommend", fake_recommend)
    monkeypatch.setattr(api, "write_audit_result", fake_write_audit)

    response = client.post("/api/v1/recommendations", json=profile.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json()["status"] == status
    assert calls["profile"] == profile
    assert calls["offline"] is True
    assert calls["audit_result"] is result


def test_recommendation_audit_and_logs_omit_free_text(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: UserProfile,
    offline_result: RecommendationResult,
    caplog: pytest.LogCaptureFixture,
) -> None:
    audit_root = tmp_path / "recommendations"
    monkeypatch.setenv("EVALUATION_MODEL_QWEN_AUDIT_ROOT", str(audit_root))

    def fake_recommend(received: UserProfile, *, offline: bool) -> RecommendationResult:
        del received, offline
        return offline_result

    def write_real_audit(result: RecommendationResult, runtime_root: Path) -> Path:
        return write_audit_result(result, runtime_root)

    monkeypatch.setattr(api, "recommend", fake_recommend)
    monkeypatch.setattr(api, "write_audit_result", write_real_audit)

    with caplog.at_level(logging.INFO, logger="evaluation_model_qwen.api"):
        response = client.post("/api/v1/recommendations", json=profile.model_dump(mode="json"))

    assert response.status_code == 200
    audit_files = list(audit_root.glob("*.json"))
    assert len(audit_files) == 1
    audit_document = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_document["profile"]["free_text"] == "[已省略]"
    assert profile.free_text not in caplog.text
    assert "secret-value" not in caplog.text


def test_invalid_profile_and_gender_return_422(client: Any, profile: UserProfile) -> None:
    document = profile.model_dump(mode="json")
    document["target_distance_m"] = 999_999
    document["gender"] = "female"

    response = client.post("/api/v1/recommendations", json=document)

    assert response.status_code == 422


def test_data_failure_returns_uniform_503(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    profile: UserProfile,
) -> None:
    def fail_recommend(received: UserProfile, *, offline: bool) -> RecommendationResult:
        del received, offline
        raise LoaderError("DASHSCOPE_API_KEY=secret-value bad data")

    monkeypatch.setattr(api, "recommend", fail_recommend)

    response = client.post("/api/v1/recommendations", json=profile.model_dump(mode="json"))

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "推荐服务暂不可用，请稍后重试。",
        }
    }
    assert "secret-value" not in response.text


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8123", "http://localhost:8123"])
def test_cors_allows_only_local_static_origins(client: Any, origin: str) -> None:
    response = client.options(
        "/api/v1/recommendations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_rejects_other_origins(client: Any) -> None:
    response = client.options(
        "/api/v1/recommendations",
        headers={
            "Origin": "http://127.0.0.1:9999",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
