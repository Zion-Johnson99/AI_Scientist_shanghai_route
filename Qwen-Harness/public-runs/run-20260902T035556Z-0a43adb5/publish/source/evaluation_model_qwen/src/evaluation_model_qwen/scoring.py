"""Five-dimension scoring and risk evaluation for route candidates.

This module provides:
- evaluate_risk: computes a RiskAssessment based on current environmental conditions.
- score_routes: computes five-dimension scores for each candidate route.

Dimensions:
- environment_health
- sport_match
- access_convenience
- route_quality
- interest_service
"""

from __future__ import annotations

import logging
from typing import Any

from evaluation_model_qwen.models import (
    EnvironmentDashboard,
    EnvironmentData,
    EnvironmentRouteRecord,
    RiskAssessment,
    RouteEntry,
    ScoredRoute,
    UserProfile,
)

logger = logging.getLogger(__name__)

# Safety thresholds for risk pause
_RISK_THRESHOLDS = {
    "precipitation_mm": 10.0,
    "feels_like_temp_high": 38.0,
    "feels_like_temp_low": -10.0,
    "wind_gust_ms": 17.0,
    "aqi_high": 150,
    "pm25_high": 75.0,
}

# Dimension keys
DIMENSION_KEYS = [
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "interest_service",
]


def evaluate_risk(
    environment: EnvironmentData | EnvironmentDashboard,
    profile: UserProfile | None = None,
) -> RiskAssessment:
    """Evaluate environmental risk and determine whether to pause.

    Accepts either an EnvironmentData instance (unit-test path) or an
    EnvironmentDashboard instance (service / CLI path).  When a Dashboard is
    given the values are extracted from its ``current`` block with safe
    fallbacks.

    Args:
        environment: Current environmental conditions.
        profile: Optional user profile (reserved for future sensitivity
            tuning; does NOT alter safety thresholds).

    Returns:
        RiskAssessment with paused flag and reasons.
    """
    if isinstance(environment, EnvironmentDashboard):
        env_data = _dashboard_to_environment_data(environment)
    else:
        env_data = environment

    reasons: list[str] = []

    precipitation = env_data.precipitation_mm
    if precipitation is not None and precipitation >= _RISK_THRESHOLDS["precipitation_mm"]:
        reasons.append(
            f"precipitation_mm {precipitation} >= threshold {_RISK_THRESHOLDS['precipitation_mm']}"
        )

    feels_like = env_data.feels_like_c
    if feels_like is not None:
        if feels_like >= _RISK_THRESHOLDS["feels_like_temp_high"]:
            reasons.append(
                f"feels_like_c {feels_like} >= high threshold "
                f"{_RISK_THRESHOLDS['feels_like_temp_high']}"
            )
        elif feels_like <= _RISK_THRESHOLDS["feels_like_temp_low"]:
            reasons.append(
                f"feels_like_c {feels_like} <= low threshold "
                f"{_RISK_THRESHOLDS['feels_like_temp_low']}"
            )

    wind_gust = env_data.wind_gust_ms
    if wind_gust is not None and wind_gust >= _RISK_THRESHOLDS["wind_gust_ms"]:
        reasons.append(f"wind_gust_ms {wind_gust} >= threshold {_RISK_THRESHOLDS['wind_gust_ms']}")

    aqi = env_data.aqi
    if aqi is not None and aqi >= _RISK_THRESHOLDS["aqi_high"]:
        reasons.append(f"aqi {aqi} >= threshold {_RISK_THRESHOLDS['aqi_high']}")

    pm25 = env_data.pm25
    if pm25 is not None and pm25 >= _RISK_THRESHOLDS["pm25_high"]:
        reasons.append(f"pm25 {pm25} >= threshold {_RISK_THRESHOLDS['pm25_high']}")

    paused = len(reasons) > 0

    logger.info(
        "evaluate_risk: paused=%s, reasons=%d, aqi=%s, "
        "precipitation=%s, wind_gust=%s, feels_like=%s",
        paused,
        len(reasons),
        aqi,
        precipitation,
        wind_gust,
        feels_like,
    )

    return RiskAssessment(
        paused=paused,
        reasons=reasons,
        thresholds_applied=dict(_RISK_THRESHOLDS),
    )


def _dashboard_to_environment_data(dashboard: EnvironmentDashboard) -> EnvironmentData:
    """Convert an EnvironmentDashboard into an EnvironmentData instance.

    Reads from ``dashboard.current`` with safe fallbacks for missing fields.
    """
    current = dashboard.current or {}

    def number(keys: tuple[str, ...], default: float | None) -> float | None:
        for key in keys:
            value = current.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return default

    temperature_c = number(("temperature_c",), 20.0)
    feels_like_c = number(("feels_like_c",), temperature_c)
    precipitation_mm = number(("precipitation_mm",), 0.0)
    wind_gust_ms = number(("wind_gust_ms", "wind_speed_ms"), 0.0)
    aqi = number(("aqi", "aqi_value"), 0.0)
    pm25 = number(("pm2_5_ug_m3", "pm25"), None)

    return EnvironmentData(
        temperature_c=temperature_c,
        feels_like_c=feels_like_c,
        precipitation_mm=precipitation_mm,
        wind_gust_ms=wind_gust_ms,
        aqi=aqi,
        pm25=pm25,
    )


def _env_block_value(record: EnvironmentRouteRecord, field: str) -> float | None:
    """Extract numeric value from an EnvironmentBlock field, handling None."""
    block = getattr(record, field, None)
    if block is None:
        return None
    value = getattr(block, "value", None)
    if value is None:
        return None
    return float(value)


def _score_environment_health(
    env_record: EnvironmentRouteRecord | None,
    profile: UserProfile,
) -> float:
    """Score environment health dimension (0-100)."""
    if env_record is None:
        logger.debug("_score_environment_health: no env record, default 50")
        return 50.0

    score = 100.0

    pm25_value = _env_block_value(env_record, "pm2_5")
    if pm25_value is not None:
        penalty = min(40.0, (pm25_value / 75.0) * 40.0)
        if "pm25" in profile.sensitivities:
            penalty *= 1.5
        score -= penalty

    noise_value = _env_block_value(env_record, "noise")
    if noise_value is not None:
        penalty = min(30.0, (noise_value / 100.0) * 30.0)
        if "noise" in profile.sensitivities:
            penalty *= 1.5
        score -= penalty

    pollen_value = _env_block_value(env_record, "pollen_daily")
    if pollen_value is not None:
        penalty = min(20.0, (pollen_value / 10.0) * 20.0)
        if "pollen" in profile.sensitivities:
            penalty *= 1.5
        score -= penalty

    return max(0.0, min(100.0, score))


def _score_sport_match(route: RouteEntry, profile: UserProfile) -> float:
    """Score sport match dimension (0-100)."""
    mode = route.route_mode
    preferred = profile.preferred_modes if hasattr(profile, "preferred_modes") else []
    if not preferred:
        return 70.0
    if mode in preferred:
        return 100.0
    return 40.0


def _score_access_convenience(route: RouteEntry) -> float:
    """Score access convenience dimension (0-100)."""
    score = 60.0
    if hasattr(route, "validation_status") and route.validation_status == "valid":
        score += 20.0
    if hasattr(route, "geometry_status") and route.geometry_status == "ok":
        score += 20.0
    return max(0.0, min(100.0, score))


def _score_route_quality(route: RouteEntry) -> float:
    """Score route quality dimension (0-100)."""
    score = 50.0
    if hasattr(route, "geometry_status") and route.geometry_status == "ok":
        score += 30.0
    if hasattr(route, "validation_status") and route.validation_status == "valid":
        score += 20.0
    return max(0.0, min(100.0, score))


def _score_interest_service(route: RouteEntry) -> float:
    """Score interest/service dimension (0-100)."""
    score = 55.0
    if hasattr(route, "route_name") and route.route_name:
        score += 15.0
    if hasattr(route, "route_mode") and route.route_mode in ("walk", "run", "bike"):
        score += 15.0
    return max(0.0, min(100.0, score))


def _resolve_env_records(
    environment: EnvironmentDashboard | list[Any],
) -> dict[str, EnvironmentRouteRecord]:
    """Build a mapping from route_id to EnvironmentRouteRecord.

    Accepts either an EnvironmentDashboard (reads .routes.items) or a plain
    list of EnvironmentRouteRecord objects.
    """
    records: list[Any] = []
    if isinstance(environment, EnvironmentDashboard):
        routes_block = environment.routes
        if routes_block is not None:
            items = getattr(routes_block, "items", None)
            if items is not None:
                records = list(items)
    elif isinstance(environment, list):
        records = environment

    mapping: dict[str, EnvironmentRouteRecord] = {}
    for rec in records:
        rid = getattr(rec, "route_id", None)
        if rid is not None:
            mapping[str(rid)] = rec
    return mapping


def score_routes(
    routes: list[RouteEntry],
    environment: EnvironmentDashboard | list[Any],
    profile: UserProfile,
    weights: dict[str, float],
) -> list[ScoredRoute]:
    """Score candidate routes using five weighted dimensions.

    Args:
        routes: List of RouteEntry candidates.
        environment: EnvironmentDashboard or list of EnvironmentRouteRecord.
        profile: User profile for personalisation.
        weights: Mapping of dimension key to numeric weight.  All five
            dimension keys should be present; missing keys default to 0.0.

    Returns:
        List of ScoredRoute sorted by base_score descending.
    """
    env_map = _resolve_env_records(environment)

    results: list[ScoredRoute] = []

    for route in routes:
        route_id = route.route_id
        env_record = env_map.get(str(route_id))

        dim_scores: dict[str, float] = {
            "environment_health": _score_environment_health(env_record, profile),
            "sport_match": _score_sport_match(route, profile),
            "access_convenience": _score_access_convenience(route),
            "route_quality": _score_route_quality(route),
            "interest_service": _score_interest_service(route),
        }

        # Weighted base score: sum(score*weight) / sum(weight)
        weighted_sum = 0.0
        weight_total = 0.0
        for key in DIMENSION_KEYS:
            w = float(weights.get(key, 0.0))
            weighted_sum += dim_scores[key] * w
            weight_total += w

        if weight_total > 0.0:
            base_score = weighted_sum / weight_total
        else:
            base_score = sum(dim_scores.values()) / len(dim_scores)

        scored = ScoredRoute(
            route_id=route_id,
            route_name=route.route_name,
            route_mode=route.route_mode,
            distance_m=route.distance_m,
            environment_health=round(dim_scores["environment_health"], 4),
            sport_match=round(dim_scores["sport_match"], 4),
            access_convenience=round(dim_scores["access_convenience"], 4),
            route_quality=round(dim_scores["route_quality"], 4),
            interest_service=round(dim_scores["interest_service"], 4),
            base_score=round(base_score, 4),
        )
        results.append(scored)

    results.sort(key=lambda s: s.base_score, reverse=True)
    return results
