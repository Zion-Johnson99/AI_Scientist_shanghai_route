from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import pytest

from weather_api_data.route_environment import (
    RouteEnvironmentError,
    build_route_environment_document,
)


def _segments(route_count: int = 1) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    for route_index in range(route_count):
        route_id = f"XH_TEST_{route_index + 1:04d}"
        segments.extend(
            [
                {
                    "segment_id": f"{route_id}_S0001",
                    "route_id": route_id,
                    "segment_index": 1,
                    "length_m": 100.0,
                    "pm25_grid_id": "XH_PM25_G001",
                },
                {
                    "segment_id": f"{route_id}_S0002",
                    "route_id": route_id,
                    "segment_index": 2,
                    "length_m": 300.0,
                    "pm25_grid_id": "XH_PM25_G002",
                },
            ]
        )
    return segments


def _pm25_document() -> dict[str, object]:
    return {
        "dataset_type": "pm25_grid_estimate",
        "status": "ok",
        "target_time": "2026-08-26T09:00:00+08:00",
        "generated_at": "2026-08-26T09:02:00+08:00",
        "spatial_basis": "grid_1km",
        "calibration": {"active_station_count": 2},
        "quality": {"status": "estimated", "confidence": "medium"},
        "grids": [
            {"grid_id": "XH_PM25_G001", "pm2_5_ug_m3": 10.0, "is_estimated": True},
            {"grid_id": "XH_PM25_G002", "pm2_5_ug_m3": 30.0, "is_estimated": True},
        ],
    }


def _pollen_document(day_count: int = 6) -> dict[str, object]:
    scores: list[dict[str, object]] = []
    for day in range(1, day_count + 1):
        forecast_date = f"2026-09-{day:02d}"
        scores.extend(
            [
                {
                    "grid_id": "XH_PM25_G001",
                    "forecast_date": forecast_date,
                    "pollen_risk_score": 10.0 + day,
                    "status": "ok",
                    "confidence": "medium",
                    "estimated": True,
                },
                {
                    "grid_id": "XH_PM25_G002",
                    "forecast_date": forecast_date,
                    "pollen_risk_score": 30.0 + day,
                    "status": "ok",
                    "confidence": "medium",
                    "estimated": True,
                },
            ]
        )
    return {
        "dataset_type": "pollen_grid_scores",
        "generated_at": "2026-08-26T09:03:00+08:00",
        "spatial_resolution_m": 1000,
        "source": "google_pollen+qweather+vegetation_proxy",
        "grid_scores": scores,
    }


def _noise_segments(route_count: int = 1) -> list[dict[str, object]]:
    assessments: list[dict[str, object]] = []
    for route_index in range(route_count):
        route_id = f"XH_TEST_{route_index + 1:04d}"
        assessments.extend(
            [
                {
                    "segment_id": f"{route_id}_S0001",
                    "route_id": route_id,
                    "static_risk_score": 20.0,
                    "scenario_risk_scores": {"morning_peak": 24.0},
                    "status": "ok",
                    "confidence": "medium",
                    "estimated": True,
                    "source_ids": ["osm", "shanghai_acoustic_zone"],
                },
                {
                    "segment_id": f"{route_id}_S0002",
                    "route_id": route_id,
                    "static_risk_score": 60.0,
                    "scenario_risk_scores": {"morning_peak": 72.0},
                    "status": "ok",
                    "confidence": "medium",
                    "estimated": True,
                    "source_ids": ["osm", "shanghai_acoustic_zone"],
                },
            ]
        )
    return assessments


def test_build_route_environment_length_weights_three_exposures_and_caps_pollen_days() -> None:
    document = build_route_environment_document(
        route_segments=_segments(),
        pm25_document=_pm25_document(),
        pollen_document=_pollen_document(),
        noise_segments=_noise_segments(),
        generated_at=datetime.fromisoformat("2026-09-01T09:05:00+08:00"),
    )

    routes = cast(list[dict[str, object]], document["routes"])
    route = routes[0]
    pm25 = cast(dict[str, object], route["pm2_5"])
    pollen = cast(list[dict[str, object]], route["pollen_daily"])
    noise = cast(dict[str, object], route["noise"])

    assert document["schema_version"] == "1.0"
    assert document["dataset_type"] == "route_environment"
    assert document["route_count"] == 1
    assert route["total_length_m"] == 400.0
    assert pm25["value"] == pytest.approx(25.0)
    assert pm25["unit"] == "ug/m3"
    assert pm25["source"] == ["qweather", "shanghai_sthj", "CHAP"]
    assert pm25["business_time"] == "2026-08-26T09:00:00+08:00"
    assert pm25["fetched_at"] == "2026-08-26T09:02:00+08:00"
    assert len(pollen) == 5
    assert pollen[0]["source"] == ["google_pollen", "qweather", "vegetation_proxy"]
    assert [item["business_time"] for item in pollen] == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
        "2026-09-04",
        "2026-09-05",
    ]
    assert pollen[0]["value"] == pytest.approx(26.0)
    assert noise["value"] == pytest.approx(50.0)
    assert cast(dict[str, float], noise["scenarios"])["morning_peak"] == pytest.approx(60.0)
    assert route["status"] == "ok"
    assert json.loads(json.dumps(document, ensure_ascii=False))["route_count"] == 1

    for metric in (pm25, pollen[0], noise):
        assert {
            "source",
            "business_time",
            "fetched_at",
            "expires_at",
            "spatial_scale",
            "status",
            "confidence",
            "estimated",
        } <= metric.keys()


def test_build_route_environment_keeps_all_routes_sorted_and_marks_missing_sources_partial() -> (
    None
):
    document = build_route_environment_document(
        route_segments=list(reversed(_segments(route_count=90))),
        pm25_document=_pm25_document(),
        pollen_document=None,
        noise_segments=[],
        generated_at=datetime.fromisoformat("2026-09-01T09:05:00+08:00"),
    )

    routes = cast(list[dict[str, object]], document["routes"])
    assert document["route_count"] == 90
    assert [route["route_id"] for route in routes] == sorted(
        cast(str, route["route_id"]) for route in routes
    )
    assert document["status"] == "partial"
    assert all(route["status"] == "partial" for route in routes)
    assert all(route["pollen_daily"] == [] for route in routes)
    assert all(cast(dict[str, object], route["noise"])["status"] == "no_data" for route in routes)


def test_build_route_environment_reports_partial_segment_coverage() -> None:
    pollen = _pollen_document(day_count=1)
    scores = cast(list[dict[str, object]], pollen["grid_scores"])
    pollen["grid_scores"] = [score for score in scores if score["grid_id"] == "XH_PM25_G001"]

    document = build_route_environment_document(
        route_segments=_segments(),
        pm25_document=_pm25_document(),
        pollen_document=pollen,
        noise_segments=_noise_segments(),
        generated_at=datetime.fromisoformat("2026-09-01T09:05:00+08:00"),
    )

    route = cast(list[dict[str, object]], document["routes"])[0]
    pollen_daily = cast(list[dict[str, object]], route["pollen_daily"])
    assert route["status"] == "partial"
    assert pollen_daily[0]["value"] == pytest.approx(11.0)
    assert pollen_daily[0]["coverage_ratio"] == pytest.approx(0.25)
    assert pollen_daily[0]["status"] == "partial"


def test_route_environment_propagates_degraded_pm25_fusion_status() -> None:
    pm25_document = _pm25_document()
    pm25_document["status"] = "partial"
    pm25_document["quality"] = {"status": "estimated", "confidence": "low"}
    pm25_document["calibration"] = {"active_station_count": 1}

    document = build_route_environment_document(
        route_segments=_segments(),
        pm25_document=pm25_document,
        pollen_document=_pollen_document(day_count=1),
        noise_segments=_noise_segments(),
        generated_at=datetime.fromisoformat("2026-09-01T09:05:00+08:00"),
    )

    route = cast(list[dict[str, object]], document["routes"])[0]
    metric = cast(dict[str, object], route["pm2_5"])
    assert metric["status"] == "partial"
    assert metric["confidence"] == "low"
    assert metric["source"] == ["qweather", "CHAP"]
    assert route["status"] == "partial"


def test_route_environment_ignores_expired_pollen_dates() -> None:
    pollen = _pollen_document(day_count=6)
    scores = cast(list[dict[str, object]], pollen["grid_scores"])
    for score in scores:
        day = cast(str, score["forecast_date"])[-2:]
        score["forecast_date"] = f"2026-08-{day}"

    document = build_route_environment_document(
        route_segments=_segments(),
        pm25_document=_pm25_document(),
        pollen_document=pollen,
        noise_segments=_noise_segments(),
        generated_at=datetime.fromisoformat("2026-08-03T09:05:00+08:00"),
    )

    route = cast(list[dict[str, object]], document["routes"])[0]
    pollen_daily = cast(list[dict[str, object]], route["pollen_daily"])
    assert [item["business_time"] for item in pollen_daily] == [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
    ]


def test_route_environment_marks_mixed_observed_and_estimated_inputs_as_estimated() -> None:
    pm25 = _pm25_document()
    cast(list[dict[str, object]], pm25["grids"])[0]["is_estimated"] = False
    pollen = _pollen_document(day_count=1)
    cast(list[dict[str, object]], pollen["grid_scores"])[0]["estimated"] = False
    noise = _noise_segments()
    noise[0]["estimated"] = False

    document = build_route_environment_document(
        route_segments=_segments(),
        pm25_document=pm25,
        pollen_document=pollen,
        noise_segments=noise,
        generated_at=datetime.fromisoformat("2026-09-01T09:05:00+08:00"),
    )

    route = cast(list[dict[str, object]], document["routes"])[0]
    assert cast(dict[str, object], route["pm2_5"])["estimated"] is True
    pollen_daily = cast(list[dict[str, object]], route["pollen_daily"])
    assert pollen_daily[0]["estimated"] is True
    assert cast(dict[str, object], route["noise"])["estimated"] is True


@pytest.mark.parametrize("length_m", [0.0, -1.0])
def test_build_route_environment_rejects_non_positive_segment_length(length_m: float) -> None:
    segments = _segments()
    segments[0]["length_m"] = length_m

    with pytest.raises(RouteEnvironmentError, match="length_m"):
        build_route_environment_document(
            route_segments=segments,
            pm25_document=None,
            pollen_document=None,
            noise_segments=[],
        )
