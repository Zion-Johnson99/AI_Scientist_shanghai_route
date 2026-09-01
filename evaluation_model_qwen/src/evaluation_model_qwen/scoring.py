from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

from .constraints import ScoringError, filter_candidates, validate_target_time
from .models import (
    DataBundle,
    EnvironmentMetric,
    PollenMetric,
    RiskAssessment,
    RouteEnvironment,
    RouteRecord,
    ScoredRoute,
    TimedRecord,
    UserProfile,
)

DIMENSION_NAMES = (
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "interest_service",
)


def _parse_datetime(value: str | None, fallback_tz: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fallback_tz)
    return parsed


def _reliability(
    status: str, confidence: str | None, estimated: bool, weights: dict[str, Any]
) -> float:
    status_value = float(weights["status_reliability"].get(status, 0.0))
    confidence_value = float(weights["confidence_reliability"].get(confidence, 1.0))
    estimate_value = float(weights["estimated_reliability"]) if estimated else 1.0
    return max(0.0, min(1.0, status_value * confidence_value * estimate_value))


def _not_expired(valid_until: str | None, target: datetime) -> bool:
    if not valid_until:
        return True
    expiry = _parse_datetime(valid_until, target.tzinfo)
    if expiry is None:
        return False
    if len(valid_until) == 10:
        expiry = expiry + timedelta(days=1) - timedelta(microseconds=1)
    return target <= expiry


def _record_usable(record: TimedRecord | None, target: datetime, weights: dict[str, Any]) -> bool:
    return (
        record is not None
        and float(weights["status_reliability"].get(record.status, 0)) > 0
        and _not_expired(record.valid_until, target)
    )


def _select_timed_record(
    current: TimedRecord | None,
    hourly: list[TimedRecord],
    target: datetime,
    freshness_time: datetime,
    weights: dict[str, Any],
) -> TimedRecord | None:
    if _record_usable(current, freshness_time, weights):
        assert current is not None
        current_time = _parse_datetime(current.business_time, target.tzinfo)
        if current_time is not None and abs(target - current_time) <= timedelta(minutes=30):
            return current

    timed_hourly = [
        (record, _parse_datetime(record.business_time, target.tzinfo))
        for record in hourly
        if _record_usable(record, freshness_time, weights)
    ]
    available = [(record, at) for record, at in timed_hourly if at is not None]
    if not available:
        return None
    return min(available, key=lambda pair: (abs(target - pair[1]), pair[1]))[0]


def _select_alerts(
    alerts: list[TimedRecord],
    target: datetime,
    freshness_time: datetime,
    weights: dict[str, Any],
) -> list[TimedRecord]:
    selected: list[TimedRecord] = []
    for alert in alerts:
        if not _record_usable(alert, freshness_time, weights):
            continue
        start = _parse_datetime(
            str(alert.values.get("start_time") or alert.values.get("onset_time") or ""),
            target.tzinfo,
        )
        end = _parse_datetime(str(alert.values.get("end_time") or ""), target.tzinfo)
        if start is not None and target < start:
            continue
        if end is not None and target > end:
            continue
        if start is None and end is None:
            business_time = _parse_datetime(alert.business_time, target.tzinfo)
            if business_time is not None and abs(target - business_time) > timedelta(minutes=30):
                continue
        selected.append(alert)
    return selected


def _number(values: dict[str, Any], key: str) -> float | None:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def evaluate_risk(
    bundle: DataBundle, profile: UserProfile, weights: dict[str, Any]
) -> RiskAssessment:
    """按目标时段选择天气、AQI、预警并应用配置阈值。"""
    validate_target_time(profile.target_time, bundle.environment.generated_at)
    try:
        thresholds = weights["risk_thresholds"]
        alert_penalties = weights["alert_penalties"]
    except KeyError as exc:
        raise ScoringError(f"评分配置缺少字段：{exc.args[0]}") from exc

    weather = _select_timed_record(
        bundle.environment.current_weather,
        bundle.environment.weather_hourly,
        profile.target_time,
        bundle.environment.generated_at,
        weights,
    )
    aqi = _select_timed_record(
        bundle.environment.current_aqi,
        bundle.environment.aqi_hourly,
        profile.target_time,
        bundle.environment.generated_at,
        weights,
    )
    alerts = _select_alerts(
        bundle.environment.current_alerts,
        profile.target_time,
        bundle.environment.generated_at,
        weights,
    )
    reasons: list[str] = []
    warnings = False
    paused = False
    penalty = 0.0

    if weather is not None:
        checks = (
            ("降水", "precipitation_mm", "warning_precipitation_mm", "pause_precipitation_mm"),
            ("体感温度", "real_feel_temperature_c", "warning_real_feel_c", "pause_real_feel_c"),
            ("阵风", "wind_gust_kmh", "warning_wind_gust_kmh", "pause_wind_gust_kmh"),
        )
        for label, value_key, warning_key, pause_key in checks:
            value = _number(weather.values, value_key)
            if value is None:
                continue
            if value >= float(thresholds[pause_key]):
                paused = True
                reasons.append(f"{label}达到暂停阈值")
            elif value >= float(thresholds[warning_key]):
                warnings = True
                reasons.append(f"{label}达到提醒阈值")

    if aqi is not None:
        aqi_value = _number(aqi.values, "aqi")
        if aqi_value is not None:
            sensitive_pause = "air" in profile.sensitivities and aqi_value >= float(
                thresholds["sensitive_pause_aqi"]
            )
            if aqi_value >= float(thresholds["pause_aqi"]) or sensitive_pause:
                paused = True
                reasons.append("AQI 达到暂停阈值")
            elif aqi_value >= float(thresholds["warning_aqi"]):
                warnings = True
                reasons.append("AQI 达到提醒阈值")

    for alert in alerts:
        color = str(alert.values.get("color_code") or alert.values.get("color") or "").lower()
        if color in {"red", "orange", "红", "橙"}:
            paused = True
            reasons.append("气象红色或橙色预警生效")
        elif color in {"yellow", "黄"}:
            warnings = True
            penalty += float(alert_penalties["yellow"])
            reasons.append("气象黄色预警生效")
        elif color in {"blue", "蓝"}:
            warnings = True
            penalty += float(alert_penalties["blue"])
            reasons.append("气象蓝色预警生效")

    if weather is None and aqi is None and not alerts:
        warnings = True
        reasons.append("目标时段缺少可用天气、AQI 和预警记录")

    if paused:
        status = "paused"
        penalty = 100.0
    elif warnings:
        status = "warning"
    else:
        status = "ok"
    return RiskAssessment(
        status=status,
        score_penalty=min(100.0, penalty),
        reasons=reasons,
        weather=weather,
        aqi=aqi,
        alerts=alerts,
    )


def _metric_value(
    metric: EnvironmentMetric, value: float, weights: dict[str, Any]
) -> tuple[float, float]:
    reliability = _reliability(metric.status, metric.confidence, metric.estimated, weights)
    raw_score = max(0.0, min(100.0, value))
    return 50.0 + reliability * (raw_score - 50.0), reliability


def _pm25_health_score(value: float) -> float:
    points = ((0.0, 100.0), (35.0, 85.0), (75.0, 60.0), (115.0, 35.0), (150.0, 15.0), (250.0, 0.0))
    value = max(0.0, value)
    for (left_x, left_y), (right_x, right_y) in pairwise(points):
        if value <= right_x:
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + ratio * (right_y - left_y)
    return 0.0


def _noise_scenario(target: datetime) -> str:
    if target.hour >= 22 or target.hour < 6:
        return "night"
    if target.weekday() < 5:
        if 7 <= target.hour < 10 or 17 <= target.hour < 20:
            return "weekday_peak"
        return "weekday_offpeak"
    return "daytime"


def _select_pollen(route_environment: RouteEnvironment, target_date: date) -> PollenMetric | None:
    for metric in route_environment.pollen_daily:
        if metric.business_time and metric.business_time[:10] == target_date.isoformat():
            return metric
    return None


def _valid_metric(
    metric: EnvironmentMetric | None, target: datetime, weights: dict[str, Any]
) -> bool:
    return (
        metric is not None
        and metric.value is not None
        and _reliability(metric.status, metric.confidence, metric.estimated, weights) > 0
        and _not_expired(metric.valid_until, target)
    )


def _environment_dimension(
    route_environment: RouteEnvironment | None,
    profile: UserProfile,
    weights: dict[str, Any],
    ignore_pollen: bool,
) -> tuple[float | None, float, dict[str, Any], list[str]]:
    if route_environment is None:
        return None, 0.0, {}, ["路线环境数据缺失"]
    metric_weights = {key: float(value) for key, value in weights["environment_weights"].items()}
    boost = float(weights["sensitivity_boost"])
    if "air" in profile.sensitivities:
        metric_weights["pm2_5"] += boost
    if "noise" in profile.sensitivities:
        metric_weights["noise"] += boost
    if "pollen" in profile.sensitivities:
        metric_weights["pollen"] += boost

    values: list[tuple[float, float, float]] = []
    summary: dict[str, Any] = {}
    notes: list[str] = []
    pm = route_environment.pm2_5
    pm_time = _parse_datetime(pm.business_time, profile.target_time.tzinfo)
    if (
        _valid_metric(pm, profile.target_time, weights)
        and pm_time is not None
        and abs(profile.target_time - pm_time) <= timedelta(hours=2)
    ):
        assert pm.value is not None
        score, reliability = _metric_value(pm, _pm25_health_score(pm.value), weights)
        values.append((score, reliability, metric_weights["pm2_5"]))
        summary["pm2_5"] = {
            "value": pm.value,
            "business_time": pm.business_time,
            "valid_until": pm.valid_until,
            "status": pm.status,
            "spatial_scale": pm.spatial_scale,
            "estimated": pm.estimated,
            "confidence": pm.confidence,
            "unit": pm.unit,
            "reliability": round(reliability, 6),
        }
    elif pm.value is not None:
        notes.append("PM2.5 与目标业务时间相差超过 2 小时或状态不可用")

    noise = route_environment.noise
    scenario = _noise_scenario(profile.target_time)
    noise_value = noise.scenarios.get(scenario, noise.value)
    if (
        noise_value is not None
        and _reliability(noise.status, noise.confidence, noise.estimated, weights) > 0
        and _not_expired(noise.valid_until, profile.target_time)
    ):
        score, reliability = _metric_value(noise, 100.0 - noise_value, weights)
        values.append((score, reliability, metric_weights["noise"]))
        summary["noise"] = {
            "value": noise_value,
            "business_time": noise.business_time,
            "valid_until": noise.valid_until,
            "scenario": scenario,
            "status": noise.status,
            "spatial_scale": noise.spatial_scale,
            "estimated": noise.estimated,
            "confidence": noise.confidence,
            "unit": noise.unit,
            "reliability": round(reliability, 6),
        }

    pollen = _select_pollen(route_environment, profile.target_time.date())
    if not ignore_pollen and _valid_metric(pollen, profile.target_time, weights):
        assert pollen is not None and pollen.value is not None
        score, reliability = _metric_value(pollen, 100.0 - pollen.value, weights)
        values.append((score, reliability, metric_weights["pollen"]))
        summary["pollen"] = {
            "value": pollen.value,
            "business_time": pollen.business_time,
            "valid_until": pollen.valid_until,
            "status": pollen.status,
            "spatial_scale": pollen.spatial_scale,
            "estimated": pollen.estimated,
            "confidence": pollen.confidence,
            "unit": pollen.unit,
            "reliability": round(reliability, 6),
        }
    if not values:
        return None, 0.0, summary, notes
    total_weight = sum(item[2] for item in values)
    score = sum(item[0] * item[2] for item in values) / total_weight
    confidence = sum(item[1] * item[2] for item in values) / total_weight
    return score, confidence, summary, notes


def _sport_score(route: RouteRecord, profile: UserProfile) -> float:
    relative_error = abs(route.distance_m - profile.target_distance_m) / profile.target_distance_m
    return max(0.0, 100.0 * (1.0 - relative_error))


def _access_score(access_distance_m: float | None, profile: UserProfile) -> float | None:
    if access_distance_m is None:
        return 85.0 if profile.area_ids else None
    scale = float(profile.search_radius_m or 5000)
    return max(0.0, 100.0 * (1.0 - access_distance_m / scale))


def _quality_score(route: RouteRecord, weights: dict[str, Any]) -> float:
    components = (
        [100.0 * float(route.route_inside_ratio)] if route.route_inside_ratio is not None else []
    )
    if route.snap_ratio is not None:
        components.append(100.0 * float(route.snap_ratio))
    confidence = float(weights["confidence_reliability"].get(route.confidence, 0.5)) * 100.0
    components.append(confidence)
    return sum(components) / len(components)


def _interest_score(route: RouteRecord, profile: UserProfile) -> tuple[float | None, list[str]]:
    if not profile.interests:
        return None, []
    searchable = {
        value.lower() for value in route.tags + route.feature_tags + route.preference_hits
    }
    searchable.update(poi.poi_type.lower() for poi in route.nearby_pois)
    aliases = {
        "waterfront": {"waterfront", "滨水", "滨江"},
        "park": {"park", "公园", "绿地"},
        "quiet": {"quiet", "安静", "静谧"},
    }
    matched = [
        interest
        for interest in profile.interests
        if searchable.intersection(aliases.get(interest, {interest}))
    ]
    return 100.0 * len(matched) / len(profile.interests), matched


def _pollen_is_equal(
    candidates: list[tuple[RouteRecord, float | None]],
    environments: dict[str, RouteEnvironment],
    profile: UserProfile,
    weights: dict[str, Any],
) -> bool:
    values: list[float] = []
    for route, _ in candidates:
        route_environment = environments.get(route.route_id)
        if route_environment is None:
            continue
        pollen = _select_pollen(route_environment, profile.target_time.date())
        if _valid_metric(pollen, profile.target_time, weights):
            assert pollen is not None and pollen.value is not None
            values.append(pollen.value)
    return len(values) > 1 and len(set(values)) == 1


def score_routes(
    bundle: DataBundle,
    profile: UserProfile,
    risk: RiskAssessment,
    weights: dict[str, Any],
) -> list[ScoredRoute]:
    """执行硬过滤、五维评分、可靠性收缩并返回稳定排序结果。"""
    validate_target_time(profile.target_time, bundle.environment.generated_at)
    candidates = filter_candidates(bundle.routes, profile)
    ignore_pollen = _pollen_is_equal(
        candidates, bundle.environment.route_environment, profile, weights
    )
    pollen_note = "花粉在候选路线间为全区同值，仅作全局提醒，未参与排序"
    if ignore_pollen and pollen_note not in risk.reasons:
        risk.reasons.append(pollen_note)
    dimension_weights: dict[str, float] = {
        name: float(value)
        for name, value in zip(DIMENSION_NAMES, weights["goal_weights"][profile.goal])
    }
    scored: list[ScoredRoute] = []
    for route, access_distance_m in candidates:
        environment_score, data_confidence, environment_summary, notes = _environment_dimension(
            bundle.environment.route_environment.get(route.route_id),
            profile,
            weights,
            ignore_pollen,
        )
        access_score = _access_score(access_distance_m, profile)
        interest_score, matched = _interest_score(route, profile)
        dimensions: dict[str, float] = {
            "sport_match": _sport_score(route, profile),
            "route_quality": _quality_score(route, weights),
        }
        if environment_score is not None:
            dimensions["environment_health"] = environment_score
        if access_score is not None:
            dimensions["access_convenience"] = access_score
        if interest_score is not None:
            dimensions["interest_service"] = interest_score
        active_weight = sum(float(dimension_weights[name]) for name in dimensions)
        base_score = (
            sum(value * float(dimension_weights[name]) for name, value in dimensions.items())
            / active_weight
        )
        base_score = max(0.0, min(100.0, base_score - risk.score_penalty))
        scored.append(
            ScoredRoute(
                route=route,
                base_score=round(base_score, 6),
                dimension_scores={key: round(value, 6) for key, value in dimensions.items()},
                data_confidence=round(data_confidence, 6),
                access_distance_m=round(access_distance_m, 3)
                if access_distance_m is not None
                else None,
                matched_preferences=matched,
                environment_summary=environment_summary,
                risk_notes=notes,
            )
        )

    scored.sort(
        key=lambda item: (
            -item.base_score,
            -item.data_confidence,
            item.access_distance_m if item.access_distance_m is not None else float("inf"),
            item.route.route_id,
        )
    )
    for rank, item in enumerate(scored, start=1):
        item.base_rank = rank
    return scored


__all__ = ["ScoringError", "evaluate_risk", "score_routes"]
