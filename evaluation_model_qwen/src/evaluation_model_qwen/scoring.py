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

CORE_SCENIC_INTERESTS = frozenset({"waterfront", "park", "quiet"})
WATERFRONT_AREA_IDS = frozenset({"west_bund"})
PARK_AREA_IDS = frozenset({"shanghai_botanical_garden", "kangjian", "xujiahui_sports"})
WATERFRONT_KEYWORDS = ("徐汇滨江", "西岸", "龙腾大道")
PARK_KEYWORDS = ("上海植物园", "植物园", "康健园", "体育公园", "桂江绿廊")
INTEREST_ALIASES = {
    "quiet": frozenset({"quiet", "安静", "静谧"}),
    "coffee": frozenset({"coffee", "咖啡"}),
    "toilet": frozenset({"toilet", "厕所", "公厕"}),
    "convenience": frozenset({"convenience", "便利店"}),
}


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
            elif (
                value_key == "real_feel_temperature_c"
                and "heat" in profile.sensitivities
                and value >= float(thresholds[warning_key])
            ):
                paused = True
                reasons.append("体感温度达到敏感人群暂停阈值")
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
) -> tuple[float, float, dict[str, Any], list[str]]:
    missing_score = float(weights["missing_metric_score"])
    if route_environment is None:
        return missing_score, 0.0, {}, ["路线环境数据缺失，环境维度按中性分计入"]
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
        values.append((missing_score, 0.0, metric_weights["pm2_5"]))
    else:
        notes.append("PM2.5 数据缺失，按中性分计入")
        values.append((missing_score, 0.0, metric_weights["pm2_5"]))

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
    else:
        notes.append("噪声数据缺失或状态不可用，按中性分计入")
        values.append((missing_score, 0.0, metric_weights["noise"]))

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
    elif not ignore_pollen:
        notes.append("花粉数据缺失或状态不可用，按中性分计入")
        values.append((missing_score, 0.0, metric_weights["pollen"]))
    total_weight = sum(item[2] for item in values)
    score = sum(item[0] * item[2] for item in values) / total_weight
    confidence = sum(item[1] * item[2] for item in values) / total_weight
    return score, confidence, summary, notes


def _sport_score(route: RouteRecord, profile: UserProfile) -> float:
    relative_error = abs(route.distance_m - profile.target_distance_m) / profile.target_distance_m
    return max(0.0, 100.0 * (1.0 - relative_error))


def _access_score(access_distance_m: float | None, profile: UserProfile) -> float | None:
    if access_distance_m is None:
        return None
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


def _text_has_keyword(value: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in value for keyword in keywords)


def _explicit_interest_match(route: RouteRecord, interest: str) -> bool:
    area_ids = set(route.popular_area_ids)
    if interest == "waterfront":
        return bool(
            area_ids.intersection(WATERFRONT_AREA_IDS)
            or _text_has_keyword(route.region_zone, WATERFRONT_KEYWORDS)
            or _text_has_keyword(route.route_name, WATERFRONT_KEYWORDS)
        )
    if interest == "park":
        return bool(
            area_ids.intersection(PARK_AREA_IDS)
            or _text_has_keyword(route.region_zone, PARK_KEYWORDS)
            or _text_has_keyword(route.route_name, PARK_KEYWORDS)
            or any(poi.poi_type.lower() in {"park", "park_gate"} for poi in route.nearby_pois)
        )
    aliases = INTEREST_ALIASES.get(interest, frozenset({interest}))
    searchable = {
        value.lower() for value in route.tags + route.feature_tags + route.preference_hits
    }
    searchable.update(poi.poi_type.lower() for poi in route.nearby_pois)
    return bool(searchable.intersection(aliases))


def _quiet_interest_score(
    route_environment: RouteEnvironment | None,
    profile: UserProfile,
    weights: dict[str, Any],
) -> tuple[float, bool]:
    if route_environment is None:
        return float(weights["missing_metric_score"]), False
    noise = route_environment.noise
    noise_value = noise.scenarios.get(_noise_scenario(profile.target_time), noise.value)
    if (
        noise_value is None
        or _reliability(noise.status, noise.confidence, noise.estimated, weights) <= 0
        or not _not_expired(noise.valid_until, profile.target_time)
    ):
        return float(weights["missing_metric_score"]), False
    score, _ = _metric_value(noise, 100.0 - noise_value, weights)
    return score, True


def _interest_score(
    route: RouteRecord,
    route_environment: RouteEnvironment | None,
    profile: UserProfile,
    weights: dict[str, Any],
) -> tuple[float | None, list[str], bool]:
    if not profile.interests:
        return None, [], False
    core_scores: list[float] = []
    facility_scores: list[float] = []
    matched: list[str] = []
    core_evidence = False
    for interest in profile.interests:
        explicit_match = _explicit_interest_match(route, interest)
        if explicit_match:
            matched.append(interest)
        if interest == "quiet":
            score, noise_evidence = _quiet_interest_score(route_environment, profile, weights)
            core_scores.append(score if noise_evidence or not explicit_match else 100.0)
            core_evidence = core_evidence or explicit_match or noise_evidence
        elif interest in CORE_SCENIC_INTERESTS:
            core_scores.append(100.0 if explicit_match else 0.0)
            core_evidence = core_evidence or explicit_match
        else:
            facility_scores.append(100.0 if explicit_match else 0.0)

    if core_scores and facility_scores:
        core_share = float(weights["core_interest_weight_floor"]) / 100.0
        score = core_share * sum(core_scores) / len(core_scores)
        score += (1.0 - core_share) * sum(facility_scores) / len(facility_scores)
    elif core_scores:
        score = sum(core_scores) / len(core_scores)
    else:
        score = sum(facility_scores) / len(facility_scores)
    return score, matched, core_evidence


def _prioritize_core_interest(dimension_weights: dict[str, float], weights: dict[str, Any]) -> None:
    floor = float(weights["core_interest_weight_floor"])
    current = dimension_weights["interest_service"]
    if current >= floor:
        return
    non_interest_total = sum(
        value for name, value in dimension_weights.items() if name != "interest_service"
    )
    remaining = 100.0 - floor
    for name in dimension_weights:
        if name != "interest_service":
            dimension_weights[name] = dimension_weights[name] * remaining / non_interest_total
    dimension_weights["interest_service"] = floor


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
    return len(values) == len(candidates) and len(values) > 1 and len(set(values)) == 1


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
    interest_results = {
        route.route_id: _interest_score(
            route,
            bundle.environment.route_environment.get(route.route_id),
            profile,
            weights,
        )
        for route, _ in candidates
    }
    if any(result[2] for result in interest_results.values()):
        _prioritize_core_interest(dimension_weights, weights)
    scored: list[ScoredRoute] = []
    for route, access_distance_m in candidates:
        environment_score, data_confidence, environment_summary, notes = _environment_dimension(
            bundle.environment.route_environment.get(route.route_id),
            profile,
            weights,
            ignore_pollen,
        )
        access_score = _access_score(access_distance_m, profile)
        interest_score, matched, _ = interest_results[route.route_id]
        dimensions: dict[str, float] = {
            "sport_match": _sport_score(route, profile),
            "route_quality": _quality_score(route, weights),
        }
        dimensions["environment_health"] = environment_score
        if access_score is not None:
            dimensions["access_convenience"] = access_score
        if interest_score is not None:
            dimensions["interest_service"] = interest_score
        if access_distance_m is not None:
            notes.append("起点接驳距离为 GCJ-02 直线估算，实际道路距离通常更长")
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
