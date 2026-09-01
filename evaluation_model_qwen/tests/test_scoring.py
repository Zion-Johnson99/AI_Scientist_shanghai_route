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


def test_heat_sensitivity_uses_existing_real_feel_warning_threshold_as_pause_threshold() -> None:
    weather = timed(
        NOW,
        precipitation_mm=0,
        real_feel_temperature_c=WEIGHTS["risk_thresholds"]["warning_real_feel_c"],
        wind_gust_kmh=0,
    )
    data = bundle([route("route")], current_weather=weather)

    regular = evaluate_risk(data, profile(), WEIGHTS)
    heat_sensitive = evaluate_risk(data, profile(sensitivities=["heat"]), WEIGHTS)

    assert regular.status == "warning"
    assert heat_sensitive.status == "paused"
    assert "体感温度达到敏感人群暂停阈值" in heat_sensitive.reasons


def test_environment_reliability_shrinks_toward_50_and_missing_metrics_stay_neutral() -> None:
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

    assert reliable_score.dimension_scores["environment_health"] == pytest.approx(72.5)
    assert reliable_score.data_confidence == pytest.approx(0.45)
    assert unreliable_score.dimension_scores["environment_health"] == pytest.approx(57.0875)
    assert unreliable_score.data_confidence == pytest.approx(0.14175)


def test_missing_environment_is_neutral_and_loses_confidence_tie_break() -> None:
    known = environment("known", pm=metric(91, business_time=NOW.isoformat()))
    known.noise = metric(50)
    known.pollen_daily = []
    routes = [route("missing"), route("known")]

    scored = score_routes(
        bundle(routes, environments={"known": known}),
        profile(),
        evaluate_risk(bundle(routes), profile(), WEIGHTS),
        WEIGHTS,
    )

    assert [item.route.route_id for item in scored] == ["known", "missing"]
    assert scored[0].base_score == pytest.approx(scored[1].base_score)
    assert scored[1].dimension_scores["environment_health"] == pytest.approx(50)
    assert scored[1].data_confidence == 0
    assert "路线环境数据缺失，环境维度按中性分计入" in scored[1].risk_notes


def test_missing_environment_metric_does_not_gain_from_weight_renormalization() -> None:
    partial = environment("partial", pm=metric(0, business_time=NOW.isoformat()))
    partial.noise = metric(None, status="no_data")
    partial.pollen_daily = []
    complete = environment("complete", pm=metric(0, business_time=NOW.isoformat()))
    complete.noise = metric(50)
    complete.pollen_daily = []
    routes = [route("partial"), route("complete")]

    scored = score_routes(
        bundle(routes, environments={"partial": partial, "complete": complete}),
        profile(),
        evaluate_risk(bundle(routes), profile(), WEIGHTS),
        WEIGHTS,
    )
    by_id = {item.route.route_id: item for item in scored}

    assert by_id["partial"].dimension_scores["environment_health"] == pytest.approx(
        by_id["complete"].dimension_scores["environment_health"]
    )
    assert by_id["partial"].data_confidence < by_id["complete"].data_confidence


@pytest.mark.parametrize(
    "identity_fields",
    [
        {"popular_area_ids": ["west_bund"], "region_zone": "龙华", "route_name": "测试路线"},
        {"popular_area_ids": [], "region_zone": "徐汇滨江—龙华", "route_name": "测试路线"},
        {"popular_area_ids": [], "region_zone": "龙华", "route_name": "西岸龙腾大道骑行线"},
    ],
)
def test_waterfront_matches_trusted_route_identity_fields(
    identity_fields: dict[str, object],
) -> None:
    record = route("waterfront", tags=[], feature_tags=[], preference_hits=[], **identity_fields)

    scored = score_routes(
        bundle([record]),
        profile(interests=["waterfront"]),
        evaluate_risk(bundle([record]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert scored.matched_preferences == ["waterfront"]
    assert scored.dimension_scores["interest_service"] == 100


def test_false_generic_waterfront_tag_is_rejected_and_real_waterfront_gets_priority() -> None:
    false_tag = route(
        "XH_BIKE_0063",
        route_name="漕河泾—桂江外围骑行短环",
        region_zone="漕河泾—桂江绿廊",
        popular_area_ids=["caohejing", "kangjian"],
        tags=["骑行", "滨江", "商业"],
    )
    waterfront = route(
        "waterfront",
        route_name="衡复—西岸—龙华骑行中环",
        region_zone="衡复风貌区—徐汇滨江—龙华",
        popular_area_ids=["west_bund", "longhua"],
        tags=[],
        distance_m=1200,
        confidence="low",
        route_inside_ratio=0.5,
        snap_ratio=0.5,
    )
    false_environment = environment("XH_BIKE_0063", pm=metric(0, business_time=NOW.isoformat()))
    false_environment.noise = metric(0)
    waterfront_environment = environment(
        "waterfront", pm=metric(150, business_time=NOW.isoformat())
    )
    waterfront_environment.noise = metric(100)
    routes = [false_tag, waterfront]

    scored = score_routes(
        bundle(
            routes,
            environments={
                "XH_BIKE_0063": false_environment,
                "waterfront": waterfront_environment,
            },
        ),
        profile(interests=["waterfront"]),
        evaluate_risk(bundle(routes), profile(), WEIGHTS),
        WEIGHTS,
    )

    assert scored[0].route.route_id == "waterfront"
    assert scored[0].matched_preferences == ["waterfront"]
    assert scored[1].matched_preferences == []


def test_park_uses_canonical_area_evidence_and_rejects_generic_tag() -> None:
    false_tag = route(
        "false-park",
        route_name="普通道路环线",
        region_zone="漕河泾",
        popular_area_ids=["caohejing"],
        tags=["公园"],
    )
    park = route(
        "park",
        route_name="植物园骑行环线",
        region_zone="上海植物园及周边",
        popular_area_ids=["shanghai_botanical_garden"],
        tags=[],
    )

    scored = score_routes(
        bundle([false_tag, park]),
        profile(interests=["park"]),
        evaluate_risk(bundle([false_tag, park]), profile(), WEIGHTS),
        WEIGHTS,
    )
    by_id = {item.route.route_id: item for item in scored}

    assert by_id["park"].matched_preferences == ["park"]
    assert by_id["false-park"].matched_preferences == []


def test_quiet_interest_uses_continuous_noise_score_without_claiming_explicit_match() -> None:
    quiet_environment = environment("quieter")
    quiet_environment.noise = metric(20, scenarios={"weekday_offpeak": 20})
    loud_environment = environment("louder")
    loud_environment.noise = metric(80, scenarios={"weekday_offpeak": 80})
    routes = [route("louder", tags=[]), route("quieter", tags=[])]

    scored = score_routes(
        bundle(
            routes,
            environments={"quieter": quiet_environment, "louder": loud_environment},
        ),
        profile(interests=["quiet"]),
        evaluate_risk(bundle(routes), profile(), WEIGHTS),
        WEIGHTS,
    )
    by_id = {item.route.route_id: item for item in scored}

    assert scored[0].route.route_id == "quieter"
    assert (
        by_id["quieter"].dimension_scores["interest_service"]
        > by_id["louder"].dimension_scores["interest_service"]
    )
    assert by_id["quieter"].matched_preferences == []
    assert by_id["louder"].matched_preferences == []


def test_facility_interest_remains_a_soft_preference() -> None:
    coffee = route(
        "coffee",
        preference_hits=["coffee"],
        nearby_pois=[{"poi_type": "coffee", "poi_name": "咖啡店", "distance_m": 20}],
        distance_m=1200,
        confidence="low",
        route_inside_ratio=0,
        snap_ratio=0,
    )
    healthy = route("healthy", preference_hits=[], nearby_pois=[])
    coffee_environment = environment("coffee", pm=metric(150, business_time=NOW.isoformat()))
    coffee_environment.noise = metric(100)
    healthy_environment = environment("healthy", pm=metric(0, business_time=NOW.isoformat()))
    healthy_environment.noise = metric(0)
    routes = [coffee, healthy]

    scored = score_routes(
        bundle(
            routes,
            environments={"coffee": coffee_environment, "healthy": healthy_environment},
        ),
        profile(interests=["coffee"]),
        evaluate_risk(bundle(routes), profile(), WEIGHTS),
        WEIGHTS,
    )

    assert scored[0].route.route_id == "healthy"
    assert scored[1].matched_preferences == ["coffee"]


def test_access_distance_is_labeled_as_gcj02_straight_line_estimate() -> None:
    scored = score_routes(
        bundle([route("route")]),
        profile(origin=Coordinate(lng_gcj02=121.44, lat_gcj02=31.18)),
        evaluate_risk(bundle([route("route")]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert "起点接驳距离为 GCJ-02 直线估算，实际道路距离通常更长" in scored.risk_notes


def test_area_filter_without_origin_does_not_fabricate_access_score() -> None:
    scored = score_routes(
        bundle([route("route")]),
        profile(area_ids=["west_bund"]),
        evaluate_risk(bundle([route("route")]), profile(), WEIGHTS),
        WEIGHTS,
    )[0]

    assert "access_convenience" not in scored.dimension_scores


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


def test_pollen_is_only_removed_when_every_candidate_has_the_same_value() -> None:
    routes = [route(route_id) for route_id in ["a", "b", "missing"]]
    environments = {item.route_id: environment(item.route_id) for item in routes}
    environments["a"].pollen_daily[0].value = 60
    environments["b"].pollen_daily[0].value = 60
    environments["missing"].pollen_daily = []

    data = bundle(routes, environments=environments)
    risk = evaluate_risk(data, profile(), WEIGHTS)
    scored = score_routes(data, profile(), risk, WEIGHTS)
    by_id = {item.route.route_id: item for item in scored}

    assert "pollen" in by_id["a"].environment_summary
    assert "pollen" in by_id["b"].environment_summary
    assert "花粉数据缺失或状态不可用，按中性分计入" in by_id["missing"].risk_notes
    assert "花粉在候选路线间为全区同值，仅作全局提醒，未参与排序" not in risk.reasons
