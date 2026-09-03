"""Hard constraint logic for route candidate filtering.

Implements:
- Route mode matching
- Distance deviation <= 15% of target distance (inclusive boundary)
- Detour (additional distance) <= 20% for same-endpoint routes
- Safety thresholds (precipitation, feels-like temperature, gust, AQI)

Public API:
- apply_hard_constraints(routes, profile, environment=None, detour_limit=0.20)
- evaluate_safety_thresholds(environment) -> RiskAssessment
- evaluate_safety (internal alias)
"""

from __future__ import annotations

from typing import Any, TypeVar, Union

from evaluation_model_qwen.models import (
    EnvironmentData,
    RiskAssessment,
    RouteEntry,
    ScoredRoute,
    UserProfile,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_DISTANCE_TOLERANCE = 0.15  # max 15% deviation from target distance (inclusive)
DETOUR_LIMIT = 0.20  # max 20% additional distance for same-endpoint routes

# Safety thresholds that trigger a pause recommendation
SAFETY_THRESHOLDS: dict[str, float] = {
    "precipitation_mm": 10.0,
    "feels_like_temp_high_c": 38.0,
    "feels_like_temp_low_c": -10.0,
    "gust_speed_ms": 17.0,
    "aqi": 150.0,
}

# Type variable so apply_hard_constraints returns the same type it receives
RouteLike = TypeVar("RouteLike", RouteEntry, ScoredRoute)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_environment(
    environment: Union[EnvironmentData, dict, None],
) -> EnvironmentData | None:
    """Normalise environment input to EnvironmentData or None."""
    if environment is None:
        return None
    if isinstance(environment, EnvironmentData):
        return environment
    if isinstance(environment, dict):
        return EnvironmentData(**environment)
    return None


def _env_to_dict(env: EnvironmentData | None) -> dict[str, Any]:
    """Convert EnvironmentData to a flat dict for threshold checks."""
    if env is None:
        return {}
    d: dict[str, Any] = {}
    if env.precipitation_mm is not None:
        d["precipitation_mm"] = env.precipitation_mm
    if env.feels_like_temp_c is not None:
        d["feels_like_temp_c"] = env.feels_like_temp_c
    if env.gust_speed_ms is not None:
        d["gust_speed_ms"] = env.gust_speed_ms
    if env.aqi is not None:
        d["aqi"] = env.aqi
    return d


# ---------------------------------------------------------------------------
# Safety threshold evaluation
# ---------------------------------------------------------------------------


def evaluate_safety_thresholds(
    environment: Union[EnvironmentData, dict, None],
    thresholds: dict[str, float] | None = None,
) -> RiskAssessment:
    """Evaluate safety thresholds from environment data.

    Args:
        environment: EnvironmentData instance, a dict with current readings,
            or None when no data is available.
        thresholds: Optional override of default thresholds.

    Returns:
        RiskAssessment with risk_level and triggered reasons.
    """
    if thresholds is None:
        thresholds = SAFETY_THRESHOLDS

    env = _coerce_environment(environment)
    env_dict = _env_to_dict(env)

    if not env_dict:
        return RiskAssessment(
            risk_level="unknown",
            reasons=["no_environment_data"],
            triggered_thresholds={},
        )

    reasons: list[str] = []
    triggered: dict[str, Any] = {}

    # Precipitation
    precip = env_dict.get("precipitation_mm")
    if precip is not None and precip > thresholds.get("precipitation_mm", 10.0):
        reasons.append(
            f"Precipitation {precip} mm/h exceeds threshold "
            f"{thresholds.get('precipitation_mm', 10.0)} mm/h"
        )
        triggered["precipitation_mm"] = precip

    # Feels-like temperature high
    feels_like = env_dict.get("feels_like_temp_c")
    if feels_like is not None:
        high_limit = thresholds.get("feels_like_temp_high_c", 38.0)
        low_limit = thresholds.get("feels_like_temp_low_c", -10.0)
        if feels_like > high_limit:
            reasons.append(
                f"Feels-like temperature {feels_like} C exceeds upper "
                f"threshold {high_limit} C"
            )
            triggered["feels_like_temp_high_c"] = feels_like
        elif feels_like < low_limit:
            reasons.append(
                f"Feels-like temperature {feels_like} C below lower "
                f"threshold {low_limit} C"
            )
            triggered["feels_like_temp_low_c"] = feels_like

    # Gust speed
    gust = env_dict.get("gust_speed_ms")
    if gust is not None and gust > thresholds.get("gust_speed_ms", 17.0):
        reasons.append(
            f"Gust speed {gust} m/s exceeds threshold "
            f"{thresholds.get('gust_speed_ms', 17.0)} m/s"
        )
        triggered["gust_speed_ms"] = gust

    # AQI
    aqi = env_dict.get("aqi")
    if aqi is not None and aqi > thresholds.get("aqi", 150.0):
        reasons.append(
            f"AQI {aqi} exceeds threshold {thresholds.get('aqi', 150.0)}"
        )
        triggered["aqi"] = aqi

    if reasons:
        risk_level = "high"
    else:
        risk_level = "low"

    return RiskAssessment(
        risk_level=risk_level,
        reasons=reasons,
        triggered_thresholds=triggered,
    )


# Internal alias kept for backward compatibility within the package.
evaluate_safety = evaluate_safety_thresholds


# ---------------------------------------------------------------------------
# Hard constraint filtering
# ---------------------------------------------------------------------------


def apply_hard_constraints(
    routes: list[RouteLike],
    profile: UserProfile,
    environment: Union[EnvironmentData, dict, None] = None,
    detour_limit: float = DETOUR_LIMIT,
) -> list[RouteLike]:
    """Filter routes by hard constraints.

    Constraints applied:
    1. Route mode must match profile.route_mode.
    2. Route distance must be within 15% (inclusive) of
       profile.target_distance_m when that field is present.
    3. Detour limit: if profile.baseline_distance_m is explicitly set,
       the route distance must not exceed baseline by more than
       *detour_limit* fraction.
    4. Safety thresholds: if environment data is provided and triggers
       a high-risk assessment, all routes are rejected.

    Args:
        routes: List of RouteEntry or ScoredRoute objects.
        profile: UserProfile containing route_mode and optional distance
            targets.
        environment: Optional environment data for safety checks.
        detour_limit: Maximum additional-distance fraction (default 0.20).

    Returns:
        Filtered list of the same type as input routes.
    """
    # --- Safety gate --------------------------------------------------------
    risk = evaluate_safety_thresholds(environment)
    if risk.risk_level == "high":
        return []

    # --- Mode filter --------------------------------------------------------
    target_mode: str | None = getattr(profile, "route_mode", None)

    filtered: list[RouteLike] = []
    for route in routes:
        # Mode check
        if target_mode is not None:
            route_mode: str | None = getattr(route, "route_mode", None)
            if route_mode != target_mode:
                continue

        # Distance deviation check (inclusive boundary)
        target_distance: float | None = getattr(profile, "target_distance_m", None)
        route_distance: float | None = getattr(route, "distance_m", None)
        if target_distance is not None and route_distance is not None:
            if target_distance > 0:
                deviation = abs(route_distance - target_distance) / target_distance
                if deviation > TARGET_DISTANCE_TOLERANCE:
                    continue

        # Detour limit check – only when baseline_distance_m is explicit
        baseline_distance: float | None = getattr(
            profile, "baseline_distance_m", None
        )
        if baseline_distance is not None and route_distance is not None:
            if baseline_distance > 0:
                extra_fraction = (
                    route_distance - baseline_distance
                ) / baseline_distance
                if extra_fraction > detour_limit:
                    continue

        filtered.append(route)

    return filtered
