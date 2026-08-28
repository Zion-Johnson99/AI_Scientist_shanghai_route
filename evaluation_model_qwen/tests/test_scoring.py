from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from evaluation_model_qwen.constraints import haversine_gcj02
from evaluation_model_qwen.models import (
    Coordinate,
    DataBundle,
    EnvironmentMetric,
    EnvironmentSnapshot,
    PollenMetric,
    RouteEnvironment,
    RouteLocation,
    RouteRecord,
    TimedRecord,
    UserProfile,
)
from evaluation_model_qwen.scoring import ScoringError, evaluate_risk, score_routes

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=TZ)
WEIGHTS = json.loads(
    (Path(__file__).parents[1] / "config" / "default_weights.json").read_text(encoding="utf-8")
)


def profile(**changes: object) -> UserProfile:
    data: dict[str, object] = {
        "route_mode": "walk",
        "target_time": NOW,
        "distance_min_m": 800,
        "target_distance_m": 1000,
        "distance_max_m": 1200,
    }
    data.update(changes)
    return UserProfile.model_validate(data)


def route(route_id: str, **changes: object) -> RouteRecord:
    data: dict[str, object] = {
        "route_id": route_id,
        "route_name": route_id,
        "route_mode": "walk",
        "route_shape": "strict_loop",
        "distance_m": 1000,
        "duration_min": 15,
        "start_location": {"name": "起点", "lng_gcj02": 121.45, "lat_gcj02": 31.18},
        "end_location": {"name": "终点", "lng_gcj02": 121.45, "lat_gcj02": 31.18},
        "region_zone": "徐汇滨江",
        "tags": ["滨水"],
        "feature_tags": ["公园"],
        "popular_area_ids": ["west_bund"],
        "preference_hits": ["toilet"],
        "nearby_pois": [{"poi_type": "toilet", "poi_name": "公厕", "distance_m": 20}],
        "confidence": "high",
        "validation_status": "accepted",
        "geometry_status": "complete",
        "route_inside_ratio": 1.0,
        "snap_ratio": 1.0,
    }
    data.update(changes)
    return RouteRecord.model_validate(data)


def metric(
    value: float | None,
    *,
    status: str = "ok",
    business_time: str | None = None,
    confidence: str = "high",
    estimated: bool = False,
    scenarios: dict[str, float] | None = None,
    valid_until: str | None = None,
    spatial_scale: str = "test_grid",
    unit: str = "test_index",
) -> EnvironmentMetric:
    return EnvironmentMetric.model_validate(
        {
            "status": status,
            "value": value,
            "business_time": business_time,
            "confidence": confidence,
            "estimated": estimated,
            "scenarios": scenarios or {},
            "valid_until": valid_until,
            "spatial_scale": spatial_scale,
            "unit": unit,
        }
    )


def environment(route_id: str, *, pm: EnvironmentMetric | None = None) -> RouteEnvironment:
    return RouteEnvironment(
        route_id=route_id,
        status="ok",
        pm2_5=pm or metric(10, business_time=NOW.isoformat()),
        noise=metric(
            40,
            status="partial",
            confidence="low",
            estimated=True,
            scenarios={
                "weekday_peak": 80,
                "weekday_offpeak": 40,
                "night": 20,
                "daytime": 30,
            },
        ),
        pollen_daily=[
            PollenMetric(
                status="partial",
                value=25,
                business_time=NOW.date().isoformat(),
                confidence="low",
                estimated=True,
                spatial_scale="test_grid",
                unit="test_index",
            )
        ],
    )


def timed(at: datetime, *, valid_until: datetime | None = None, **values: object) -> TimedRecord:
    return TimedRecord(
        status="ok",
        business_time=at.isoformat(),
        valid_until=valid_until.isoformat() if valid_until else None,
        values=values,
    )


def bundle(
    routes: list[RouteRecord],
    *,
    environments: dict[str, RouteEnvironment] | None = None,
    current_weather: TimedRecord | None = None,
    current_aqi: TimedRecord | None = None,
    current_alerts: list[TimedRecord] | None = None,
    weather_hourly: list[TimedRecord] | None = None,
    aqi_hourly: list[TimedRecord] | None = None,
) -> DataBundle:
    return DataBundle(
        routes=routes,
        environment=EnvironmentSnapshot(
            generated_at=NOW,
            status="ok",
            current_weather=current_weather,
            current_aqi=current_aqi,
            current_alerts=current_alerts or [],
            weather_hourly=weather_hourly or [],
            aqi_hourly=aqi_hourly or [],
            route_environment=environments
            if environments is not None
            else {item.route_id: environment(item.route_id) for item in routes},
        ),
    )


def test_hard_constraints_and_gcj02_radius_are_applied() -> None:
    good = route("good")
    candidates = [
        good,
        route("rejected", validation_status="rejected"),
        route("broken", geometry_status="partial"),
        route("bike", route_mode="bike"),
        route("far-distance", distance_m=1400),
        route("one-way", route_shape="one_way"),
        route("wrong-area", popular_area_ids=["xujiahui"]),
        route(
            "far-away",
            start_location=RouteLocation(name="远处", lng_gcj02=121.55, lat_gcj02=31.18),
        ),
    ]
    selected = score_routes(
        bundle(candidates),
        profile(
            route_shape="strict_loop",
            area_ids=["west_bund"],
            origin=Coordinate(lng_gcj02=121.45, lat_gcj02=31.18),
            search_radius_m=2000,
        ),
        evaluate_risk(bundle(candidates), profile(), WEIGHTS),
        WEIGHTS,
    )

    assert [item.route.route_id for item in selected] == ["good"]
    assert haversine_gcj02(121.45, 31.18, 121.45, 31.18) == pytest.approx(0)
    assert haversine_gcj02(121.45, 31.18, 121.46, 31.18) == pytest.approx(952, abs=5)


def test_target_time_is_limited_to_now_through_next_24_hours() -> None:
    data = bundle([route("route")])

    with pytest.raises(ScoringError, match="未来 24 小时"):
        evaluate_risk(data, profile(target_time=NOW - timedelta(seconds=1)), WEIGHTS)
    with pytest.raises(ScoringError, match="未来 24 小时"):
        evaluate_risk(data, profile(target_time=NOW + timedelta(hours=24, seconds=1)), WEIGHTS)


def test_risk_uses_current_within_30_minutes_then_nearest_hourly_record() -> None:
    current = timed(NOW, precipitation_mm=0, real_feel_temperature_c=30, wind_gust_kmh=10)
    hourly = timed(
        NOW + timedelta(hours=1),
        precipitation_mm=WEIGHTS["risk_thresholds"]["pause_precipitation_mm"],
        real_feel_temperature_c=30,
        wind_gust_kmh=10,
    )
    data = bundle([route("route")], current_weather=current, weather_hourly=[hourly])

    current_risk = evaluate_risk(data, profile(target_time=NOW + timedelta(minutes=30)), WEIGHTS)
    hourly_risk = evaluate_risk(data, profile(target_time=NOW + timedelta(minutes=31)), WEIGHTS)

    assert current_risk.status == "ok"
    assert current_risk.weather == current
    assert hourly_risk.status == "paused"
    assert hourly_risk.weather == hourly


def test_expired_current_record_is_skipped_for_valid_hourly_record() -> None:
    target = NOW + timedelta(minutes=20)
    current = timed(
        target,
        valid_until=NOW - timedelta(minutes=1),
        precipitation_mm=0,
        real_feel_temperature_c=30,
        wind_gust_kmh=10,
    )
    hourly = timed(
        target + timedelta(minutes=10),
        valid_until=target + timedelta(hours=1),
        precipitation_mm=0,
        real_feel_temperature_c=30,
        wind_gust_kmh=10,
    )
    data = bundle([route("route")], current_weather=current, weather_hourly=[hourly])

    risk = evaluate_risk(data, profile(target_time=target), WEIGHTS)

    assert risk.weather == hourly


def test_forecast_cache_expiry_is_checked_at_snapshot_time_not_target_time() -> None:
    target = NOW + timedelta(hours=4)
    hourly = timed(
        target,
        valid_until=NOW + timedelta(minutes=15),
        precipitation_mm=0,
        real_feel_temperature_c=30,
        wind_gust_kmh=10,
    )
    data = bundle([route("route")], weather_hourly=[hourly])

    risk = evaluate_risk(data, profile(target_time=target), WEIGHTS)

    assert risk.weather == hourly


@pytest.mark.parametrize(
    ("color", "expected_status", "expected_penalty"),
    [
        ("blue", "warning", 8.0),
        ("yellow", "warning", 15.0),
        ("orange", "paused", 100.0),
        ("red", "paused", 100.0),
    ],
)
def test_alert_colors_control_pause_and_penalty(
    color: str, expected_status: str, expected_penalty: float
) -> None:
    alert = timed(NOW, color_code=color, summary=f"{color} alert")
    risk = evaluate_risk(bundle([route("route")], current_alerts=[alert]), profile(), WEIGHTS)

    assert risk.status == expected_status
    assert risk.score_penalty == expected_penalty


def test_all_active_alerts_are_evaluated_and_orange_overrides_blue() -> None:
    blue = timed(NOW, color_code="blue", summary="blue alert")
    orange = timed(NOW, color_code="orange", summary="orange alert")

    risk = evaluate_risk(
        bundle([route("route")], current_alerts=[blue, orange]),
        profile(),
        WEIGHTS,
    )

    assert risk.status == "paused"
    assert risk.score_penalty == 100
    assert risk.alerts == [blue, orange]


def test_missing_all_risk_records_is_reported_as_warning() -> None:
    risk = evaluate_risk(bundle([route("route")]), profile(), WEIGHTS)

    assert risk.status == "warning"
    assert risk.score_penalty == 0
    assert risk.reasons == ["目标时段缺少可用天气、AQI 和预警记录"]


def test_aqi_and_weather_thresholds_are_inclusive() -> None:
    thresholds = WEIGHTS["risk_thresholds"]
    weather = timed(
        NOW,
        precipitation_mm=thresholds["warning_precipitation_mm"],
        real_feel_temperature_c=thresholds["warning_real_feel_c"],
        wind_gust_kmh=thresholds["warning_wind_gust_kmh"],
    )
    aqi = timed(NOW, aqi=thresholds["sensitive_pause_aqi"])

    warning = evaluate_risk(bundle([route("route")], current_weather=weather), profile(), WEIGHTS)
    paused = evaluate_risk(
        bundle([route("route")], current_aqi=aqi), profile(sensitivities=["air"]), WEIGHTS
    )

    assert warning.status == "warning"
    assert paused.status == "paused"


def test_environment_reliability_shrinks_toward_50_and_missing_weights_renormalize() -> None:
    route_record = route("route")
    reliable = environment("route", pm=metric(0, business_time=NOW.isoformat()))
    unreliable = environment(
        "route",
        pm=metric(
            0,
            status="partial",
            business_time=NOW.isoformat(),
            confidence="low",
            estimated=True,
        ),
    )
    for item in (reliable, unreliable):
        item.noise = metric(None, status="no_data")
        item.pollen_daily = []

    reliable_score = score_routes(
        bundle([route_record], environments={"route": reliable}),
        profile(),
        evaluate_risk(bundle([route_record]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]
    unreliable_score = score_routes(
        bundle([route_record], environments={"route": unreliable}),
        profile(),
        evaluate_risk(bundle([route_record]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert reliable_score.dimension_scores["environment_health"] == pytest.approx(100)
    assert unreliable_score.dimension_scores["environment_health"] == pytest.approx(65.75)
    assert unreliable_score.data_confidence == pytest.approx(0.315)


def test_pm25_requires_two_hour_alignment_pollen_uses_date_and_noise_uses_scenario() -> None:
    item = environment(
        "route",
        pm=metric(
            1,
            business_time=(NOW - timedelta(hours=2, seconds=1)).isoformat(),
            spatial_scale="1km_grid_estimate",
            unit="µg/m³",
        ),
    )
    item.pollen_daily = [
        PollenMetric(
            status="ok",
            value=10,
            business_time=(NOW.date() - timedelta(days=1)).isoformat(),
            confidence="high",
            estimated=False,
            spatial_scale="test_grid",
            unit="test_index",
        ),
        PollenMetric(
            status="ok",
            value=20,
            business_time=NOW.date().isoformat(),
            confidence="high",
            estimated=False,
            spatial_scale="test_grid",
            unit="test_index",
        ),
    ]
    scored = score_routes(
        bundle([route("route")], environments={"route": item}),
        profile(target_time=NOW + timedelta(hours=5)),
        evaluate_risk(bundle([route("route")]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert "pm2_5" not in scored.environment_summary
    assert scored.environment_summary["pollen"]["value"] == 20
    assert scored.environment_summary["noise"]["scenario"] == "weekday_peak"
    assert scored.environment_summary["noise"]["value"] == 80


def test_expired_route_pm25_exits_environment_scoring() -> None:
    item = environment(
        "route",
        pm=metric(
            10,
            business_time=NOW.isoformat(),
            valid_until=(NOW - timedelta(seconds=1)).isoformat(),
        ),
    )

    scored = score_routes(
        bundle([route("route")], environments={"route": item}),
        profile(),
        evaluate_risk(bundle([route("route")]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert "pm2_5" not in scored.environment_summary


def test_environment_summary_keeps_scale_estimate_confidence_and_unit() -> None:
    item = environment(
        "route",
        pm=metric(
            10,
            business_time=NOW.isoformat(),
            confidence="medium",
            estimated=True,
            spatial_scale="1km_grid_estimate",
            unit="µg/m³",
        ),
    )

    scored = score_routes(
        bundle([route("route")], environments={"route": item}),
        profile(),
        evaluate_risk(bundle([route("route")]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert scored.environment_summary["pm2_5"] == {
        "value": 10.0,
        "business_time": NOW.isoformat(),
        "valid_until": None,
        "status": "ok",
        "spatial_scale": "1km_grid_estimate",
        "estimated": True,
        "confidence": "medium",
        "unit": "µg/m³",
        "reliability": 0.72,
    }


def test_equal_pollen_values_do_not_change_rank_and_order_is_stable() -> None:
    routes = [route(route_id) for route_id in ["c", "a", "b", "f", "e", "d"]]
    environments = {item.route_id: environment(item.route_id) for item in routes}
    for route_environment in environments.values():
        route_environment.pm2_5 = metric(None, status="no_data")
        route_environment.noise = metric(None, status="no_data")
        route_environment.pollen_daily[0].value = 90

    data = bundle(routes, environments=environments)
    risk = evaluate_risk(data, profile(), WEIGHTS)
    first = score_routes(data, profile(), risk, WEIGHTS)
    second = score_routes(data, profile(), risk, WEIGHTS)

    assert [item.route.route_id for item in first] == ["a", "b", "c", "d", "e", "f"]
    assert [item.base_rank for item in first] == [1, 2, 3, 4, 5, 6]
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    assert all("pollen" not in item.environment_summary for item in first)
    assert risk.reasons.count("花粉在候选路线间为全区同值，仅作全局提醒，未参与排序") == 1
    assert all(
        "花粉在候选路线间为全区同值" not in note for item in first for note in item.risk_notes
    )
