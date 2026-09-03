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

# Required fields per route item
REQUIRED_ROUTE_FIELDS = ("route_id", "pm2_5", "noise", "pollen_daily")

# Fields that must never appear in output
SENSITIVE_PATTERNS = ("api_key", "authorization", "token", "secret", "password")


def _sanitize_value(value: Any) -> Any:
    """Recursively remove sensitive keys and absolute paths from data."""
    if isinstance(value, dict):
        sanitized = {}
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
    source_snapshots: list[str],
    route_count: int,
    status: str,
) -> dict[str, Any]:
    """Build the metadata section of the dashboard."""
    return {
        "generated_at": generated_at,
        "source_snapshots": source_snapshots,
        "route_count": route_count,
        "status": status,
        "spatial_scale": "route_segment",
        "coordinate_system": "GCJ-02",
        "data_semantics": {
            "pm2_5": "Grid/station fusion estimate, not per-address observation",
            "noise": "0-100 risk proxy, not measured decibels",
            "pollen_daily": "Daily background/proxy indicator, not real-time concentration",
        },
    }


def _build_current_condition(
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the current weather/environment condition block."""
    if snapshot is None:
        return {
            "status": "no_data",
            "stale_reason": "No snapshot available",
            "estimated": True,
        }
    return {
        "status": snapshot.get("status", "ok"),
        "business_time": snapshot.get("business_time", ""),
        "valid_until": snapshot.get("valid_until", ""),
        "temperature_c": snapshot.get("temperature_c"),
        "feels_like_c": snapshot.get("feels_like_c"),
        "humidity_pct": snapshot.get("humidity_pct"),
        "wind_speed_ms": snapshot.get("wind_speed_ms"),
        "wind_gust_ms": snapshot.get("wind_gust_ms"),
        "precipitation_mm": snapshot.get("precipitation_mm"),
        "aqi": snapshot.get("aqi"),
        "pm2_5_ug_m3": snapshot.get("pm2_5_ug_m3"),
        "estimated": snapshot.get("estimated", False),
        "confidence": snapshot.get("confidence", "unknown"),
        "unit": snapshot.get("unit", {}),
    }


def _build_forecast(
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the forecast block."""
    if snapshot is None:
        return {
            "status": "no_data",
            "stale_reason": "No forecast snapshot available",
            "items": [],
        }
    return {
        "status": snapshot.get("status", "ok"),
        "items": snapshot.get("items", []),
    }


def _build_route_item(
    route_id: str,
    route_env: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a single route environment item."""
    if route_env is None:
        return {
            "route_id": route_id,
            "pm2_5": {"value": None, "unit": "ug/m3", "estimated": True, "status": "no_data"},
            "noise": {"value": None, "unit": "proxy_0_100", "estimated": True, "status": "no_data"},
            "pollen_daily": {"value": None, "unit": "index", "estimated": True, "status": "no_data"},
            "green_coverage_pct": {"value": None, "unit": "%", "estimated": True, "status": "no_data"},
            "water_proximity_m": {"value": None, "unit": "m", "estimated": True, "status": "no_data"},
        }

    def _env_block(key: str, default_unit: str) -> dict[str, Any]:
        raw = route_env.get(key)
        if raw is None:
            return {"value": None, "unit": default_unit, "estimated": True, "status": "no_data"}
        if isinstance(raw, dict):
            return {
                "value": raw.get("value"),
                "unit": raw.get("unit", default_unit),
                "estimated": raw.get("estimated", False),
                "status": raw.get("status", "ok"),
                "confidence": raw.get("confidence", "unknown"),
            }
        return {"value": raw, "unit": default_unit, "estimated": False, "status": "ok"}

    return {
        "route_id": route_id,
        "pm2_5": _env_block("pm2_5", "ug/m3"),
        "noise": _env_block("noise", "proxy_0_100"),
        "pollen_daily": _env_block("pollen_daily", "index"),
        "green_coverage_pct": _env_block("green_coverage_pct", "%"),
        "water_proximity_m": _env_block("water_proximity_m", "m"),
    }


def generate_dashboard(
    route_ids: list[str],
    current_snapshot: dict[str, Any] | None = None,
    forecast_snapshot: dict[str, Any] | None = None,
    route_env_map: dict[str, dict[str, Any]] | None = None,
    source_snapshots: list[str] | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    """Generate the full environment dashboard structure.

    Args:
        route_ids: List of route ID strings (expected 90).
        current_snapshot: Current weather/environment snapshot dict or None.
        forecast_snapshot: Forecast snapshot dict or None.
        route_env_map: Mapping from route_id to per-route environment data.
        source_snapshots: List of source snapshot identifiers.
        status: Overall status string.

    Returns:
        Dashboard dict with metadata, current, forecast, routes keys.
    """
    if route_env_map is None:
        route_env_map = {}
    if source_snapshots is None:
        source_snapshots = []

    generated_at = datetime.now(timezone.utc).isoformat()

    route_items = [
        _build_route_item(rid, route_env_map.get(rid))
        for rid in route_ids
    ]

    dashboard: dict[str, Any] = {
        "metadata": _build_metadata(
            generated_at=generated_at,
            source_snapshots=source_snapshots,
            route_count=len(route_ids),
            status=status,
        ),
        "current": _build_current_condition(current_snapshot),
        "forecast": _build_forecast(forecast_snapshot),
        "routes": {
            "count": len(route_items),
            "items": route_items,
        },
    }

    return _sanitize_value(dashboard)


def _load_route_ids_from_catalog(catalog_path: Path) -> list[str]:
    """Load route IDs from route_catalog.json."""
    if not catalog_path.exists():
        logger.warning("Route catalog not found at %s", catalog_path)
        return []
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    if isinstance(catalog, list):
        return [item["route_id"] for item in catalog if "route_id" in item]
    return []


def _load_route_env_from_snapshots(
    snapshot_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Load per-route environment data from snapshot directory.

    Looks for route_environment.json or similar files in the snapshot dir.
    """
    route_env_path = snapshot_dir / "route_environment.json"
    if not route_env_path.exists():
        return {}
    try:
        with open(route_env_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {item["route_id"]: item for item in data if "route_id" in item}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to load route environment from %s: %s", route_env_path, exc)
    return {}


def _load_current_snapshot(snapshot_dir: Path) -> dict[str, Any] | None:
    """Load current weather snapshot from snapshot directory."""
    candidates = ["current_weather.json", "weather_current.json", "current.json"]
    for name in candidates:
        path = snapshot_dir / name
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load current snapshot %s: %s", path, exc)
    return None


def _load_forecast_snapshot(snapshot_dir: Path) -> dict[str, Any] | None:
    """Load forecast snapshot from snapshot directory."""
    candidates = ["forecast.json", "weather_forecast.json"]
    for name in candidates:
        path = snapshot_dir / name
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load forecast snapshot %s: %s", path, exc)
    return None


def publish_web(
    data_dir: Path,
    output_path: Path | None = None,
    snapshot_dir: Path | None = None,
    status: str = "ok",
) -> Path:
    """Generate and write environment_dashboard.json for the web frontend.

    Args:
        data_dir: Path to the data/web directory containing route_catalog.json.
        output_path: Output path for the dashboard JSON. Defaults to
            data_dir / "environment_dashboard.json".
        snapshot_dir: Directory containing environment snapshot files.
            If None, uses data_dir.parent.parent / "runtime" / "exports".
        status: Overall status to embed in metadata.

    Returns:
        The path where the dashboard was written.
    """
    if output_path is None:
        output_path = data_dir / "environment_dashboard.json"

    # Resolve snapshot directory
    if snapshot_dir is None:
        snapshot_dir = data_dir.parent.parent / "runtime" / "exports"

    # Load route IDs from catalog
    catalog_path = data_dir / "route_catalog.json"
    route_ids = _load_route_ids_from_catalog(catalog_path)

    if not route_ids:
        logger.warning(
            "No route IDs loaded from %s; generating empty dashboard", catalog_path
        )

    # Load snapshots
    current_snapshot = _load_current_snapshot(snapshot_dir)
    forecast_snapshot = _load_forecast_snapshot(snapshot_dir)
    route_env_map = _load_route_env_from_snapshots(snapshot_dir)

    # Determine source snapshot identifiers
    source_snapshots: list[str] = []
    if snapshot_dir.exists():
        for p in sorted(snapshot_dir.glob("*.json")):
            source_snapshots.append(p.name)

    # Generate dashboard
    dashboard = generate_dashboard(
        route_ids=route_ids,
        current_snapshot=current_snapshot,
        forecast_snapshot=forecast_snapshot,
        route_env_map=route_env_map,
        source_snapshots=source_snapshots,
        status=status,
    )

    # Write output atomically
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
        f.flush()
    tmp_path.replace(output_path)

    logger.info(
        "Published environment dashboard to %s (%d routes)",
        output_path,
        len(route_ids),
    )
    return output_path


def validate_dashboard(dashboard: dict[str, Any]) -> list[str]:
    """Validate a dashboard dict against the contract.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []

    # Check top-level keys
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in dashboard:
            errors.append(f"Missing top-level key: {key}")

    if "routes" in dashboard:
        routes = dashboard["routes"]
        if not isinstance(routes, dict):
            errors.append("routes must be a dict")
        else:
            items = routes.get("items", [])
            if not isinstance(items, list):
                errors.append("routes.items must be a list")
            else:
                for i, item in enumerate(items):
                    for field in REQUIRED_ROUTE_FIELDS:
                        if field not in item:
                            errors.append(
                                f"routes.items[{i}] missing field: {field}"
                            )

    if "metadata" in dashboard:
        meta = dashboard["metadata"]
        if not isinstance(meta, dict):
            errors.append("metadata must be a dict")
        else:
            if "generated_at" not in meta:
                errors.append("metadata missing generated_at")
            if "status" not in meta:
                errors.append("metadata missing status")

    return errors
