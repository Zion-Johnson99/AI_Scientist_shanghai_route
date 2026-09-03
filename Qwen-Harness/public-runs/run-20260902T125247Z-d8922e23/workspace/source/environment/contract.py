"""Canonical unit/status/risk contract for the environment dashboard.

Every producer in this run reads its units, status vocabulary and risk
thresholds from this module exactly once, so no second spelling of a unit
string can appear anywhere downstream.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

StatusValue = Literal["measured", "derived", "estimated", "unavailable"]
RiskLevel = Literal["normal", "caution", "pause", "stop", "unknown"]

CANONICAL_CRS = "CRS84/WGS84 (lon,lat)"
GRID_ROWS = 6
GRID_COLS = 9
GRID_CELL_COUNT = 54

STATUS_DOMAIN: tuple[str, ...] = ("measured", "derived", "estimated", "unavailable")
MISSING_RATE_LIMIT = 0.10

SOURCE_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROUTE_CATALOG_PATH = (
    SOURCE_ROOT / "xuhui_route_builder" / "data" / "web" / "route_catalog.json"
)
DEFAULT_DASHBOARD_PATH = (
    SOURCE_ROOT / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json"
)

FIELD_SPECS: list[dict[str, Any]] = [
    {
        "key": "pm25_ug_m3",
        "unit": "ug/m3",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "PM2.5 质量浓度，来自 Open-Meteo 空气质量 API 逐小时 pm2_5 字段。",
    },
    {
        "key": "aqi_us",
        "unit": "index_us_aqi",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "美国 AQI 指数，来自 Open-Meteo 空气质量 API 逐小时 us_aqi 字段。",
    },
    {
        "key": "temperature_c",
        "unit": "degC",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "2 米气温，来自 Open-Meteo 预报 API temperature_2m 字段。",
    },
    {
        "key": "feels_like_c",
        "unit": "degC",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "体感温度，来自 Open-Meteo 预报 API apparent_temperature 字段。",
    },
    {
        "key": "humidity_pct",
        "unit": "percent",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "2 米相对湿度百分比，来自 relative_humidity_2m 字段。",
    },
    {
        "key": "wind_speed_kmh",
        "unit": "km/h",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "10 米风速，公里每小时，来自 wind_speed_10m 字段。",
    },
    {
        "key": "wind_gust_kmh",
        "unit": "km/h",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "10 米阵风，公里每小时，来自 wind_gusts_10m 字段。",
    },
    {
        "key": "precipitation_mm",
        "unit": "mm",
        "status_domain": ["measured", "unavailable"],
        "provenance": "public_api_measurement",
        "missing_value": None,
        "description_zh": "逐小时降水量，毫米，来自 precipitation 字段。",
    },
    {
        "key": "green_ratio_0_1",
        "unit": "ratio_0_1",
        "status_domain": ["derived", "unavailable"],
        "provenance": "osm_local_geometry",
        "missing_value": None,
        "description_zh": "网格内绿地面积占比，由 OSM 公园、绿地、林地多边形鞋带公式面积计算。",
    },
    {
        "key": "water_ratio_0_1",
        "unit": "ratio_0_1",
        "status_domain": ["derived", "unavailable"],
        "provenance": "osm_local_geometry",
        "missing_value": None,
        "description_zh": "网格内水体面积占比，由 OSM 水体、水库、池塘多边形面积计算。",
    },
    {
        "key": "road_density_km_per_km2",
        "unit": "km/km2",
        "status_domain": ["derived", "unavailable"],
        "provenance": "osm_local_geometry",
        "missing_value": None,
        "description_zh": "网格内全部 highway 道路长度除以网格面积，单位公里每平方公里。",
    },
    {
        "key": "major_road_density_km_per_km2",
        "unit": "km/km2",
        "status_domain": ["derived", "unavailable"],
        "provenance": "osm_local_geometry",
        "missing_value": None,
        "description_zh": "网格内快速路与主干路（motorway 至 secondary 及其 link）长度密度。",
    },
    {
        "key": "traffic_exposure_0_1",
        "unit": "ratio_0_1",
        "status_domain": ["derived", "unavailable"],
        "provenance": "deterministic_proxy",
        "missing_value": None,
        "description_zh": "交通暴露代理，min(1, major_road_density_km_per_km2 / 20)，固定标尺。",
    },
    {
        "key": "noise_proxy_db",
        "unit": "dB_proxy",
        "status_domain": ["derived", "unavailable"],
        "provenance": "deterministic_proxy_model",
        "missing_value": None,
        "description_zh": "噪声代理值，由主干路与全部道路密度对数公式推得，非实测声级。",
    },
]

FIELD_KEYS: tuple[str, ...] = tuple(spec["key"] for spec in FIELD_SPECS)
CANONICAL_UNITS: dict[str, str] = {spec["key"]: str(spec["unit"]) for spec in FIELD_SPECS}
FIELD_STATUS_DOMAINS: dict[str, tuple[str, ...]] = {
    spec["key"]: tuple(str(item) for item in spec["status_domain"]) for spec in FIELD_SPECS
}
FIELD_PROVENANCE: dict[str, str] = {
    spec["key"]: str(spec["provenance"]) for spec in FIELD_SPECS
}

WEATHER_FIELD_KEYS: tuple[str, ...] = (
    "temperature_c",
    "feels_like_c",
    "humidity_pct",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "precipitation_mm",
)
AIR_QUALITY_FIELD_KEYS: tuple[str, ...] = ("pm25_ug_m3", "aqi_us")
MEASURED_FIELD_KEYS: tuple[str, ...] = WEATHER_FIELD_KEYS + AIR_QUALITY_FIELD_KEYS

RISK_THRESHOLDS: dict[str, dict[str, float | str]] = {
    "precipitation_mm": {"unit": "mm", "pause": 2.5, "stop": 10.0},
    "feels_like_c": {"unit": "degC", "pause": 35.0, "stop": 40.0},
    "wind_gust_kmh": {"unit": "km/h", "pause": 40.0, "stop": 62.0},
    "aqi_us": {"unit": "index_us_aqi", "caution": 100, "pause": 150, "stop": 200},
    "pm25_ug_m3": {"unit": "ug/m3", "caution": 75.0, "pause": 115.0, "stop": 150.0},
}

RISK_LEVEL_SEVERITY: dict[str, int] = {
    "normal": 0,
    "caution": 1,
    "pause": 2,
    "stop": 3,
}

_RISK_ORDER: tuple[str, ...] = ("caution", "pause", "stop")


def risk_level(field_key: str, value: float | None) -> RiskLevel:
    """Map a numeric field value onto the fixed risk ladder; None is unknown."""
    if value is None:
        return "unknown"
    block = RISK_THRESHOLDS.get(field_key)
    if block is None:
        return "unknown"
    level: RiskLevel = "normal"
    for name in _RISK_ORDER:
        raw = block.get(name)
        if isinstance(raw, (int, float)) and value >= float(raw):
            level = cast(RiskLevel, name)
    return level


def worst_risk(levels: list[RiskLevel]) -> RiskLevel:
    """Most severe level, ignoring unknown; all-unknown stays unknown."""
    known = [level for level in levels if level != "unknown"]
    if not known:
        return "unknown"
    return cast(RiskLevel, max(known, key=lambda item: RISK_LEVEL_SEVERITY[item]))


def _is_iso8601(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    candidate = text.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _value_object_errors(
    cell_id: str, field_key: str, obj: Any, errors: list[str]
) -> float | None:
    if not isinstance(obj, dict):
        errors.append(f"field_missing_in_cell: {cell_id}:{field_key} value object absent")
        return None
    if "value" not in obj:
        errors.append(f"field_missing_in_cell: {cell_id}:{field_key} has no value member")
    unit = obj.get("unit")
    if unit != CANONICAL_UNITS[field_key]:
        errors.append(f"unit_mismatch: {cell_id}:{field_key} unit={unit!r}")
    status = obj.get("status")
    if status not in FIELD_STATUS_DOMAINS[field_key]:
        errors.append(f"status_out_of_domain: {cell_id}:{field_key} status={status!r}")
    value = obj.get("value")
    if value is not None and not isinstance(value, (int, float)):
        errors.append(f"field_missing_in_cell: {cell_id}:{field_key} value not numeric or null")
        return None
    return None if value is None else float(value)


def validate_dashboard(
    payload: dict[str, Any], catalog_route_ids: set[str] | None = None
) -> dict[str, Any]:
    """Check the dashboard payload against this contract and return a report."""
    errors: list[str] = []
    warnings: list[str] = []

    if payload.get("crs") != CANONICAL_CRS:
        errors.append(f"crs_mismatch: {payload.get('crs')!r}")

    for stamp_key in ("generated_at", "data_generated_at"):
        raw = payload.get(stamp_key)
        if raw is None:
            errors.append(f"missing_generated_at: {stamp_key}")
        elif not _is_iso8601(raw):
            errors.append(f"invalid_generated_at: {stamp_key}={raw!r}")

    cells_raw = payload.get("cells")
    cells: list[Any] = cells_raw if isinstance(cells_raw, list) else []
    if len(cells) != GRID_CELL_COUNT:
        errors.append(f"cell_count_mismatch: {len(cells)}")

    excluded_raw = payload.get("excluded_fields")
    excluded_keys: set[str] = set()
    if isinstance(excluded_raw, list):
        for entry in excluded_raw:
            if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                excluded_keys.add(entry["key"])

    missing_counts: dict[str, int] = {key: 0 for key in FIELD_KEYS}
    cell_ids: set[str] = set()
    for cell in cells:
        if not isinstance(cell, dict):
            errors.append("field_missing_in_cell: cell entry is not an object")
            continue
        cell_id = str(cell.get("cell_id", "<unknown>"))
        cell_ids.add(cell_id)
        values = cell.get("values")
        if not isinstance(values, dict):
            errors.append(f"field_missing_in_cell: {cell_id} has no values object")
            continue
        for field_key in FIELD_KEYS:
            value = _value_object_errors(cell_id, field_key, values.get(field_key), errors)
            if value is None:
                missing_counts[field_key] += 1

    missing_rate: dict[str, float] = {}
    denominator = len(cells) if cells else 1
    for field_key in FIELD_KEYS:
        rate = missing_counts[field_key] / denominator
        missing_rate[field_key] = round(rate, 4)
        if rate > MISSING_RATE_LIMIT:
            if field_key in excluded_keys:
                warnings.append(
                    f"field_excluded_from_missing_rate: {field_key} rate={rate:.3f}"
                )
            else:
                errors.append(f"missing_rate_exceeded: {field_key} rate={rate:.3f}")

    if catalog_route_ids is None:
        if DEFAULT_ROUTE_CATALOG_PATH.exists():
            catalog_payload: dict[str, Any] = json.loads(
                DEFAULT_ROUTE_CATALOG_PATH.read_text(encoding="utf-8")
            )
            routes_raw = catalog_payload.get("routes")
            catalog_route_ids = {
                str(route.get("route_id"))
                for route in routes_raw
                if isinstance(route, dict)
            } if isinstance(routes_raw, list) else set()
        else:
            catalog_route_ids = set()
            warnings.append(
                f"route_catalog_unavailable: {DEFAULT_ROUTE_CATALOG_PATH.name} not found"
            )

    routes_raw = payload.get("routes")
    routes: list[Any] = routes_raw if isinstance(routes_raw, list) else []
    for route in routes:
        if not isinstance(route, dict):
            errors.append("route_id_not_in_catalog: route entry is not an object")
            continue
        route_id = str(route.get("route_id", "<unknown>"))
        if route_id not in catalog_route_ids:
            errors.append(f"route_id_not_in_catalog: {route_id}")
        route_cells = route.get("cell_ids")
        if not isinstance(route_cells, list) or not route_cells:
            errors.append(f"empty_cell_ids: {route_id}")
            continue
        for route_cell_id in route_cells:
            if str(route_cell_id) not in cell_ids:
                errors.append(f"unknown_cell_id: {route_id}:{route_cell_id}")

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "missing_rate": missing_rate,
        "cell_count": len(cells),
        "route_count": len(routes),
    }
