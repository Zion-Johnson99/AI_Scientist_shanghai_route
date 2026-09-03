"""Web export module: generates environment_dashboard.json for the web frontend.

This module aggregates environment data from pipeline snapshots and route-level
exposure records into a single dashboard JSON file consumed by the map web page.

It serves as the primary environment data entry point for the web product,
producing the environment_dashboard.json file that contains:
- metadata: generation info, data semantics, coordinate system
- current: current weather/environment conditions
- forecast: forecast items
- routes: per-route environment exposure data (90 items)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default output path relative to repository root
DEFAULT_OUTPUT_PATH = Path("xuhui_route_builder/data/web/environment_dashboard.json")

# Required top-level keys in the output
REQUIRED_TOP_LEVEL_KEYS = ("metadata", "current", "forecast", "routes")

# Required environment keys per route item
REQUIRED_ENV_KEYS = ("pm2_5", "noise", "pollen_daily")

# Required semantic fields per environment block
REQUIRED_SEMANTIC_FIELDS = ("value", "unit", "estimated", "status")

# Fields that must never appear in output
SENSITIVE_PATTERNS = ("api_key", "authorization", "token", "secret", "password")

# Expected route count for full coverage
EXPECTED_ROUTE_COUNT = 90


class DashboardValidationError(Exception):
    """Raised when dashboard structure or content fails validation."""

    pass


def _sanitize_value(value: Any) -> Any:
    """Recursively remove sensitive keys and absolute paths from data."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for k, v in value.items():
            lower_key = k.lower()
            if any(pattern in lower_key for pattern in SENSITIVE_PATTERNS):
                continue
            sanitized[k] = _sanitize_value(v)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        # Remove absolute paths (Unix and Windows)
        if value.startswith("/") and len(value) > 1 and not value.startswith("//"):
            return "<path-redacted>"
        if len(value) >= 3 and value[1] == ":" and value[2] in ("\\", "/"):
            return "<path-redacted>"
        return value
    return value


def _build_metadata(
    generated_at: str,
    status: str,
    route_count: int,
    sources: list[str],
) -> dict[str, Any]:
    """Build the metadata section of the dashboard."""
    return {
        "generated_at": generated_at,
        "status": status,
        "route_count": route_count,
        "sources": sources,
        "spatial_scale": "route_segment",
        "coordinate_system": "GCJ-02",
        "data_semantics": {
            "pm2_5": "Grid/station fusion estimate, not per-address observation",
            "noise": "0-100 risk proxy, not measured decibels",
            "pollen_daily": "Daily background/proxy indicator, not real-time concentration",
        },
    }


def _build_current_condition(
    weather: dict[str, Any] | None,
    aqi: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the current weather/environment condition block."""
    current: dict[str, Any] = {}
    if weather is not None:
        current["temperature_c"] = weather.get("temperature_c")
        current["humidity_pct"] = weather.get("humidity_pct")
        current["wind_speed_ms"] = weather.get("wind_speed_ms")
        current["precipitation_mm"] = weather.get("precipitation_mm")
        current["condition"] = weather.get("condition")
    else:
        current["temperature_c"] = None
        current["humidity_pct"] = None
        current["wind_speed_ms"] = None
        current["precipitation_mm"] = None
        current["condition"] = None

    if aqi is not None:
        current["aqi_value"] = aqi.get("value")
        current["aqi_primary_pollutant"] = aqi.get("primary_pollutant")
        current["aqi_status"] = aqi.get("status")
    else:
        current["aqi_value"] = None
        current["aqi_primary_pollutant"] = None
        current["aqi_status"] = None

    return current


def _build_forecast() -> list[dict[str, Any]]:
    """Build the forecast block. Returns an empty list when no forecast data."""
    return []


def _build_route_item(route_env: dict[str, Any]) -> dict[str, Any]:
    """Build a single route environment item from pipeline data."""
    item: dict[str, Any] = {
        "route_id": route_env.get("route_id", ""),
    }

    for key in REQUIRED_ENV_KEYS:
        raw = route_env.get(key)
        if raw is None:
            # Missing field: provide a no_data placeholder
            item[key] = {
                "value": None,
                "unit": _default_unit(key),
                "estimated": True,
                "status": "no_data",
            }
        elif isinstance(raw, dict):
            block: dict[str, Any] = {
                "value": raw.get("value"),
                "unit": raw.get("unit", _default_unit(key)),
                "estimated": bool(raw.get("estimated", False)),
                "status": raw.get("status", "ok"),
            }
            if "confidence" in raw:
                block["confidence"] = raw["confidence"]
            item[key] = block
        else:
            item[key] = {
                "value": raw,
                "unit": _default_unit(key),
                "estimated": False,
                "status": "ok",
            }

    return item


def _default_unit(key: str) -> str:
    """Return the canonical unit string for a given environment key."""
    units = {
        "pm2_5": "ug/m3",
        "noise": "risk_index_0_100",
        "pollen_daily": "grains/m3_proxy",
    }
    return units.get(key, "unknown")


def build_dashboard(pipeline_result: dict[str, Any]) -> dict[str, Any]:
    """Build the environment dashboard from a pipeline result.

    Parameters
    ----------
    pipeline_result:
        Dictionary produced by the weather pipeline containing weather, aqi,
        routes list, generated_at and status fields.

    Returns
    -------
    dict with top-level keys: metadata, current, forecast, routes.
    """
    generated_at = pipeline_result.get(
        "generated_at", datetime.now(timezone.utc).isoformat()
    )
    pipeline_status = pipeline_result.get("status", "ok")
    weather = pipeline_result.get("weather")
    aqi = pipeline_result.get("aqi")
    routes_raw = pipeline_result.get("routes", [])

    # Determine dashboard status
    route_count = len(routes_raw)
    if pipeline_status == "error":
        status = "error"
    elif route_count == 0:
        status = "no_data"
    elif route_count < EXPECTED_ROUTE_COUNT:
        status = "partial"
    else:
        # Check if any route items are incomplete
        has_missing = False
        for route_env in routes_raw:
            for key in REQUIRED_ENV_KEYS:
                if key not in route_env:
                    has_missing = True
                    break
            if has_missing:
                break
        status = "partial" if has_missing else "ok"

    # Build route items
    route_items = [_build_route_item(r) for r in routes_raw]

    # Build sources list
    sources: list[str] = ["weather_pipeline", "aqi_station", "noise_model", "pollen_proxy"]

    dashboard: dict[str, Any] = {
        "metadata": _build_metadata(generated_at, status, route_count, sources),
        "current": _build_current_condition(weather, aqi),
        "forecast": _build_forecast(),
        "routes": {
            "count": route_count,
            "items": route_items,
        },
    }

    # Sanitize to remove any sensitive data
    dashboard = _sanitize_value(dashboard)

    return dashboard


def validate_dashboard(
    dashboard: dict[str, Any],
    *,
    expected_route_count: int | None = None,
) -> None:
    """Validate the dashboard structure and content.

    Parameters
    ----------
    dashboard:
        The dashboard dict to validate.
    expected_route_count:
        If provided, validates that routes.items has exactly this many entries.

    Raises
    ------
    DashboardValidationError
        If any structural or semantic check fails.
    """
    # Check top-level keys
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in dashboard:
            raise DashboardValidationError(
                f"Missing required top-level key: '{key}'"
            )

    # Check metadata
    metadata = dashboard.get("metadata", {})
    if "generated_at" not in metadata:
        raise DashboardValidationError("Missing 'generated_at' in metadata")
    if "status" not in metadata:
        raise DashboardValidationError("Missing 'status' in metadata")

    # Check routes structure
    routes = dashboard.get("routes")
    if not isinstance(routes, dict):
        raise DashboardValidationError("'routes' must be a dict")
    if "items" not in routes:
        raise DashboardValidationError("Missing 'items' in routes")

    items = routes["items"]
    if not isinstance(items, list):
        raise DashboardValidationError("'routes.items' must be a list")

    # Check route count if specified
    if expected_route_count is not None and len(items) != expected_route_count:
        raise DashboardValidationError(
            f"Expected {expected_route_count} route items, got {len(items)}"
        )

    # Check each route item
    for i, item in enumerate(items):
        if "route_id" not in item:
            raise DashboardValidationError(
                f"Missing 'route_id' in routes.items[{i}]"
            )
        for env_key in REQUIRED_ENV_KEYS:
            if env_key not in item:
                raise DashboardValidationError(
                    f"Missing '{env_key}' in routes.items[{i}] "
                    f"(route_id={item.get('route_id', '?')})"
                )
            block = item[env_key]
            if not isinstance(block, dict):
                raise DashboardValidationError(
                    f"'{env_key}' in routes.items[{i}] must be a dict"
                )
            for field in REQUIRED_SEMANTIC_FIELDS:
                if field not in block:
                    raise DashboardValidationError(
                        f"Missing semantic field '{field}' in "
                        f"routes.items[{i}].{env_key}"
                    )


def publish_web(
    pipeline_result: dict[str, Any],
    output_path: Path | str | None = None,
) -> Path:
    """Build the dashboard and write it to the web export path.

    Parameters
    ----------
    pipeline_result:
        The pipeline result dict.
    output_path:
        Optional override for the output file path.

    Returns
    -------
    Path to the written file.
    """
    if output_path is None:
        output_path = DEFAULT_OUTPUT_PATH
    output_path = Path(output_path)

    dashboard = build_dashboard(pipeline_result)
    validate_dashboard(dashboard)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(dashboard, fh, ensure_ascii=False, indent=2)

    logger.info("Published environment dashboard to %s", output_path)
    return output_path
