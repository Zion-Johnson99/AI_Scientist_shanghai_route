"""生成供静态网页使用的环境数据包。"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from weather_api_data.route_environment import build_route_environment_document

EXPECTED_GRID_COUNT = 54
EXPECTED_ROUTE_COUNT = 90
EXPECTED_HOURLY_COUNT = 24
EXPECTED_LIFE_INDEX_DAYS = 3
EXPECTED_LIFE_INDEX_TYPES = 16
EXPECTED_POLLEN_DAYS = 5

_LOCAL_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_LOCAL_POSIX_PATH = re.compile(r"^/(?:home|Users|tmp|var/tmp)/")
_SENSITIVE_KEYS = {
    "raw_data",
    "raw_response",
    "raw_response_path",
    "raw_response_paths",
    "authorization",
    "api_key",
    "access_key",
    "private_key",
    "password",
    "secret",
    "token",
    "credentials",
}


class WebExportError(ValueError):
    """表示源数据无法满足网页契约。"""


def publish_web_dashboard(
    *,
    root: Path,
    route_geojson_path: Path | None = None,
    output_path: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """校验后原子发布网页数据包, 失败时保留并标记旧快照。"""

    module_root = root.resolve()
    routes_path = route_geojson_path or (
        module_root.parent / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"
    )
    destination = output_path or (
        module_root.parent / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json"
    )
    try:
        dashboard = _build_dashboard(
            exports_dir=module_root / "runtime" / "exports",
            route_geojson_path=routes_path,
            generated_at=generated_at or datetime.now().astimezone(),
        )
    except (WebExportError, OSError, json.JSONDecodeError) as error:
        if not destination.exists():
            if isinstance(error, WebExportError):
                raise
            raise WebExportError("source_read_failed") from error
        dashboard = _stale_snapshot(destination, _failure_reason(error))
    _write_json_atomic(destination, dashboard)
    return dashboard


def _build_dashboard(
    *,
    exports_dir: Path,
    route_geojson_path: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    latest = _load_source(exports_dir, "environment_latest.json")
    hourly = _load_source(exports_dir, "environment_hourly.json")
    grid_environment = _load_source(exports_dir, "grid_environment_latest.json")
    pm25_grid = _load_source(exports_dir, "pm25_grid_latest.json")
    pollen_grid = _load_source(exports_dir, "pollen_grid_scores.json")
    route_environment = _load_source(exports_dir, "route_environment.json")
    noise_segments_document = _load_source(exports_dir, "noise_segments.json")
    route_geojson = _load_mapping(route_geojson_path, "xuhui_routes.geojson")

    current_weather = [_latest_reference_weather_record(latest, "current_weather")]
    alerts = _latest_reference_weather_batch(
        latest,
        "active_alerts",
        allow_empty=True,
    )
    current_aqi = _records(latest, "xuhui_aqi")
    life_indices = _records(latest, "daily_indices_3day")
    life_by_date = _group_life_indices(life_indices)
    if len(life_by_date) != EXPECTED_LIFE_INDEX_DAYS:
        raise WebExportError("daily_indices_3day 需要包含 3 天")
    for local_date, records in life_by_date.items():
        index_ids = {_life_index_id(record) for record in records}
        if len(records) != EXPECTED_LIFE_INDEX_TYPES or len(index_ids) != EXPECTED_LIFE_INDEX_TYPES:
            raise WebExportError(f"{local_date} 生活指数需要包含 16 类")

    weather_hourly = _latest_reference_weather_batch(
        hourly,
        "weather_forecast_24h",
    )[:EXPECTED_HOURLY_COUNT]
    aqi_hourly = _records(hourly, "xuhui_aqi_forecast_24h")[:EXPECTED_HOURLY_COUNT]
    pm25_hourly = _records(hourly, "xuhui_pm2_5_forecast_24h")[:EXPECTED_HOURLY_COUNT]
    _require_count(weather_hourly, EXPECTED_HOURLY_COUNT, "weather_forecast_24h")
    _require_count(aqi_hourly, EXPECTED_HOURLY_COUNT, "xuhui_aqi_forecast_24h")
    _require_count(pm25_hourly, EXPECTED_HOURLY_COUNT, "xuhui_pm2_5_forecast_24h")

    grid_records = _records(grid_environment, "grids")
    pm25_records = _records(pm25_grid, "grids")
    _require_count(grid_records, EXPECTED_GRID_COUNT, "grid_environment_latest.grids")
    _require_count(pm25_records, EXPECTED_GRID_COUNT, "pm25_grid_latest.grids")
    grid_ids = _unique_ids(grid_records, "grid_id", "grid_environment_latest.grids")
    pm25_grid_ids = _unique_ids(pm25_records, "grid_id", "pm25_grid_latest.grids")
    if grid_ids != pm25_grid_ids:
        raise WebExportError("54 网格 grid_id 集合不一致")

    route_records = _records(route_environment, "routes")
    _require_count(route_records, EXPECTED_ROUTE_COUNT, "route_environment.routes")
    environment_route_ids = _unique_ids(route_records, "route_id", "route_environment.routes")
    geometry_route_ids = _route_ids_from_geojson(route_geojson)
    if environment_route_ids != geometry_route_ids:
        raise WebExportError("route_environment 与 xuhui_routes.geojson 的 route_id 集合不一致")
    noise_segments = _records(noise_segments_document, "segments")
    recomputed_route_pm25 = _recompute_route_pm25(
        noise_segments=noise_segments,
        pm25_grid=pm25_grid,
        generated_at=generated_at,
    )
    if set(recomputed_route_pm25) != environment_route_ids:
        raise WebExportError("noise_segments 与 route_environment 的 route_id 集合不一致")

    pollen_records = _records(pollen_grid, "grid_scores")
    pollen_by_date = _group_by_string_field(pollen_records, "forecast_date")
    if len(pollen_by_date) != EXPECTED_POLLEN_DAYS:
        raise WebExportError("pollen_grid_scores 需要包含 5 个预报日")

    current_date = sorted(life_by_date)[0]
    current_records = [*current_weather, *alerts, *current_aqi, *life_by_date[current_date]]
    grid_items = [
        _web_grid(record, pm25_grid=pm25_grid, grid_environment=grid_environment)
        for record in sorted(grid_records, key=lambda item: _required_string(item, "grid_id"))
    ]
    route_items = [
        _web_route(
            record,
            pm25_override=recomputed_route_pm25[_required_string(record, "route_id")],
            pm25_source=_source_names(pm25_grid),
        )
        for record in sorted(route_records, key=lambda item: _required_string(item, "route_id"))
    ]
    current_status = _records_status(current_records)
    forecast_status = _records_status(
        [*weather_hourly, *aqi_hourly, *pm25_hourly, *life_indices, *pollen_records]
    )
    grids_status = _records_status(grid_records)
    routes_status = _records_status(route_records)
    overall_status = (
        "ok"
        if {current_status, forecast_status, grids_status, routes_status} == {"ok"}
        else "partial"
    )
    dashboard: dict[str, Any] = {
        "current": {
            "status": current_status,
            "weather": _first_or_none(current_weather),
            "alerts": alerts,
            "aqi": _first_or_none(current_aqi),
            "life_indices": life_by_date[current_date],
        },
        "forecast": {
            "status": forecast_status,
            "weather_hourly": weather_hourly,
            "aqi_hourly": aqi_hourly,
            "pm2_5_hourly": pm25_hourly,
            "life_indices_daily": life_indices,
            "pollen_grid_daily": [
                {"forecast_date": forecast_date, "grids": pollen_by_date[forecast_date]}
                for forecast_date in sorted(pollen_by_date)
            ],
        },
        "grids": {
            "status": grids_status,
            "count": len(grid_items),
            "items": grid_items,
        },
        "routes": {
            "status": routes_status,
            "count": len(route_items),
            "items": route_items,
        },
        "metadata": {
            "schema_version": "1.0",
            "dataset_type": "environment_dashboard",
            "generated_at": _aware_isoformat(generated_at),
            "status": overall_status,
            "coordinate_systems": ["WGS84", "GCJ-02"],
            "source_files": [
                "environment_latest.json",
                "environment_hourly.json",
                "grid_environment_latest.json",
                "pm25_grid_latest.json",
                "pollen_grid_scores.json",
                "noise_segments.json",
                "route_environment.json",
                "xuhui_routes.geojson",
            ],
            "pm2_5": {
                "name": "PM2.5",
                "unit": "µg/m³",
                "spatial_resolution_m": 1000,
                "spatial_scale": "1km_grid_estimate",
                "estimated": True,
            },
            "pm2_5_route_method": {
                "method": "length_weighted_mean_of_intersected_grid_segments",
                "weight": "segment_length_m",
                "grid_count": EXPECTED_GRID_COUNT,
                "same_grid_source_as_grids": True,
                "recomputed_by_web_export": True,
            },
            "access_route_environment": {
                "status": "not_aggregated",
                "aggregation": "not_computed",
            },
            "future_pm2_5": {
                "status": "partial",
                "concentration_inferred_from_aqi": False,
            },
        },
    }
    return cast(dict[str, Any], _sanitize(dashboard))


def _web_grid(
    record: Mapping[str, Any],
    *,
    pm25_grid: Mapping[str, Any],
    grid_environment: Mapping[str, Any],
) -> dict[str, Any]:
    longitude = _required_float(record, "longitude")
    latitude = _required_float(record, "latitude")
    gcj_longitude, gcj_latitude = _wgs84_to_gcj02(longitude, latitude)
    grid_fetched_at = _optional_string(grid_environment, "generated_at")
    pollen_value = record.get("pollen")
    pollen = (
        dict(cast(Mapping[str, Any], pollen_value)) if isinstance(pollen_value, Mapping) else None
    )
    if pollen is not None:
        pollen.setdefault("fetched_at", grid_fetched_at)
        pollen.setdefault("expires_at", None)
    noise_value = record.get("noise")
    noise = dict(cast(Mapping[str, Any], noise_value)) if isinstance(noise_value, Mapping) else None
    if noise is not None:
        noise.update(
            {
                "name": "noise_risk",
                "unit": "0-100 risk index",
                "business_time": "static_scenario",
                "fetched_at": grid_fetched_at,
                "expires_at": None,
                "spatial_scale": "route_segment_proxy_aggregated_to_1km_grid",
                "estimated": True,
            }
        )
        noise.setdefault("source", ["noise_segments"])
    result: dict[str, Any] = {
        "grid_id": _required_string(record, "grid_id"),
        "status": _status(record.get("status")),
        "coordinates": {
            "wgs84": {"longitude": longitude, "latitude": latitude},
            "gcj02": {
                "longitude": round(gcj_longitude, 6),
                "latitude": round(gcj_latitude, 6),
            },
        },
        "pm2_5": {
            "name": "PM2.5",
            "value": _required_float(record, "pm2_5_ug_m3"),
            "unit": "µg/m³",
            "spatial_resolution_m": 1000,
            "spatial_scale": "1km_grid_estimate",
            "estimated": bool(record.get("is_estimated", True)),
            "status": "ok",
            "business_time": _optional_string(pm25_grid, "target_time"),
            "fetched_at": _optional_string(pm25_grid, "generated_at"),
            "expires_at": _optional_string(pm25_grid, "expires_at"),
            "source": _source_names(pm25_grid),
        },
        "pollen": pollen,
        "noise": noise,
        "fetched_at": grid_fetched_at,
        "business_time": _optional_string(grid_environment, "target_time"),
        "expires_at": _optional_string(grid_environment, "expires_at"),
    }
    return result


def _web_route(
    record: Mapping[str, Any],
    *,
    pm25_override: Mapping[str, Any],
    pm25_source: list[str],
) -> dict[str, Any]:
    result = dict(record)
    pm25 = dict(pm25_override)
    pm25.update(
        {
            "name": "PM2.5",
            "unit": "µg/m³",
            "spatial_resolution_m": 1000,
            "spatial_scale": "1km_grid_estimate",
            "estimated": True,
            "aggregation": "segment_length_weighted_mean",
            "source_grid_count": EXPECTED_GRID_COUNT,
            "source": pm25_source,
        }
    )
    result["pm2_5"] = pm25
    result["access_route_environment"] = {
        "status": "not_aggregated",
        "aggregation": "not_computed",
    }
    return result


def _recompute_route_pm25(
    *,
    noise_segments: list[dict[str, Any]],
    pm25_grid: Mapping[str, Any],
    generated_at: datetime,
) -> dict[str, dict[str, Any]]:
    try:
        document = build_route_environment_document(
            route_segments=noise_segments,
            pm25_document=pm25_grid,
            pollen_document=None,
            noise_segments=noise_segments,
            generated_at=generated_at,
        )
    except (TypeError, ValueError) as error:
        raise WebExportError(f"路线 PM2.5 重算失败: {error}") from error
    records = _records(document, "routes")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        route_id = _required_string(record, "route_id")
        pm25_value = record.get("pm2_5")
        if not isinstance(pm25_value, Mapping):
            raise WebExportError(f"{route_id} 重算结果缺少 pm2_5")
        if route_id in result:
            raise WebExportError(f"路线 PM2.5 重算结果包含重复 route_id: {route_id}")
        result[route_id] = dict(cast(Mapping[str, Any], pm25_value))
    return result


def _load_source(exports_dir: Path, filename: str) -> dict[str, Any]:
    path = exports_dir / filename
    if not path.is_file():
        raise WebExportError(f"missing_source:{filename}")
    return _load_mapping(path, filename)


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WebExportError(f"{label} 顶层需要为对象")
    return cast(dict[str, Any], value)


def _records(document: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    value = document.get(field)
    if not isinstance(value, list):
        raise WebExportError(f"{field} 需要为数组")
    records: list[dict[str, Any]] = []
    for item in cast(list[Any], value):
        if not isinstance(item, dict):
            raise WebExportError(f"{field} 元素需要为对象")
        records.append(cast(dict[str, Any], item))
    return records


def _latest_reference_weather_record(document: Mapping[str, Any], field: str) -> dict[str, Any]:
    records = _valid_reference_qweather_records(document, field)
    return max(
        records,
        key=lambda record: (
            _record_timestamp(record, "business_time", field),
            _record_timestamp(record, "fetched_at", field),
        ),
    )


def _latest_reference_weather_batch(
    document: Mapping[str, Any], field: str, *, allow_empty: bool = False
) -> list[dict[str, Any]]:
    records = _valid_reference_qweather_records(document, field, allow_empty=allow_empty)
    if not records:
        return []
    latest_fetched_at = max(_record_timestamp(record, "fetched_at", field) for record in records)
    latest_records = [
        record
        for record in records
        if _record_timestamp(record, "fetched_at", field) == latest_fetched_at
    ]
    return sorted(
        latest_records,
        key=lambda record: _record_timestamp(record, "business_time", field),
    )


def _valid_reference_qweather_records(
    document: Mapping[str, Any], field: str, *, allow_empty: bool = False
) -> list[dict[str, Any]]:
    reference_source_id = _required_string(document, "reference_source_id")
    if not reference_source_id.startswith("qweather:"):
        raise WebExportError(
            f"{field}.reference_source_id 需要为 qweather 来源: {reference_source_id}"
        )
    matching: list[dict[str, Any]] = []
    for record in _records(document, field):
        source = record.get("source")
        if not isinstance(source, Mapping):
            continue
        source_mapping = cast(Mapping[str, Any], source)
        if (
            _status(record.get("status")) in {"ok", "partial"}
            and record.get("location_key") == reference_source_id
            and source_mapping.get("provider") == "qweather"
            and source_mapping.get("source_id") == reference_source_id
        ):
            matching.append(record)
    if not matching and not allow_empty:
        raise WebExportError(f"{field} 缺少有效的 qweather 参考源记录: {reference_source_id}")
    return matching


def _record_timestamp(record: Mapping[str, Any], field: str, label: str) -> datetime:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise WebExportError(f"{label} 有效记录缺少 {field}")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise WebExportError(f"{label} 有效记录的 {field} 不是 ISO 8601 时间: {value}") from error
    if timestamp.utcoffset() is None:
        raise WebExportError(f"{label} 有效记录的 {field} 缺少时区: {value}")
    return timestamp


def _require_count(records: list[dict[str, Any]], expected: int, label: str) -> None:
    if len(records) != expected:
        raise WebExportError(f"{label} 需要 {expected} 条，实际 {len(records)} 条")


def _unique_ids(records: list[dict[str, Any]], field: str, label: str) -> set[str]:
    values = [_required_string(record, field) for record in records]
    if len(values) != len(set(values)):
        raise WebExportError(f"{label} 包含重复 {field}")
    return set(values)


def _route_ids_from_geojson(document: Mapping[str, Any]) -> set[str]:
    features = document.get("features")
    if not isinstance(features, list):
        raise WebExportError("xuhui_routes.geojson.features 需要为数组")
    route_ids: list[str] = []
    for feature_value in cast(list[Any], features):
        if not isinstance(feature_value, Mapping):
            raise WebExportError("xuhui_routes.geojson feature 需要为对象")
        feature = cast(Mapping[str, Any], feature_value)
        properties_value = feature.get("properties")
        if not isinstance(properties_value, Mapping):
            raise WebExportError("xuhui_routes.geojson properties 需要为对象")
        properties = cast(Mapping[str, Any], properties_value)
        route_ids.append(_required_string(properties, "route_id"))
    if len(route_ids) != EXPECTED_ROUTE_COUNT or len(set(route_ids)) != EXPECTED_ROUTE_COUNT:
        raise WebExportError("xuhui_routes.geojson 需要包含 90 个唯一 route_id")
    return set(route_ids)


def _group_life_indices(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        values = record.get("values")
        if not isinstance(values, Mapping):
            raise WebExportError("life_index.values 需要为对象")
        local_date = _required_string(cast(Mapping[str, Any], values), "local_date_time")
        grouped.setdefault(local_date, []).append(record)
    return grouped


def _life_index_id(record: Mapping[str, Any]) -> str:
    values = record.get("values")
    if not isinstance(values, Mapping):
        raise WebExportError("life_index.values 需要为对象")
    return _required_string(cast(Mapping[str, Any], values), "index_id")


def _group_by_string_field(
    records: list[dict[str, Any]], field: str
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(_required_string(record, field), []).append(record)
    return grouped


def _records_status(records: list[dict[str, Any]]) -> str:
    statuses = {_status(record.get("status")) for record in records}
    if "error" in statuses or "no_data" in statuses:
        return "partial"
    if "partial" in statuses or "stale" in statuses:
        return "partial"
    return "ok"


def _status(value: object) -> str:
    return str(value) if value in {"ok", "partial", "stale", "no_data", "error"} else "partial"


def _source_names(document: Mapping[str, Any]) -> list[str]:
    sources: list[str] = []
    for field in ("provider", "source", "source_id"):
        value = document.get(field)
        if isinstance(value, str) and value and value not in sources:
            sources.append(value)
    return sources


def _first_or_none(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    return records[0] if records else None


def _required_string(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value:
        raise WebExportError(f"{field} 需要为非空字符串")
    return value


def _optional_string(document: Mapping[str, Any], field: str) -> str | None:
    value = document.get(field)
    return value if isinstance(value, str) and value else None


def _required_float(document: Mapping[str, Any], field: str) -> float:
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WebExportError(f"{field} 需要为数值")
    result = float(value)
    if not math.isfinite(result):
        raise WebExportError(f"{field} 需要为有限数值")
    return result


def _aware_isoformat(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WebExportError("generated_at 需要包含时区")
    return value.isoformat()


def _wgs84_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
    if not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271):
        raise WebExportError("网格 WGS84 坐标需要位于中国大陆范围")
    semi_major_axis = 6378245.0
    eccentricity_squared = 0.006693421622965943
    latitude_offset = _transform_latitude(longitude - 105.0, latitude - 35.0)
    longitude_offset = _transform_longitude(longitude - 105.0, latitude - 35.0)
    radian_latitude = latitude / 180.0 * math.pi
    magic = 1 - eccentricity_squared * math.sin(radian_latitude) ** 2
    square_root_magic = math.sqrt(magic)
    latitude_offset = (
        latitude_offset
        * 180.0
        / ((semi_major_axis * (1 - eccentricity_squared)) / (magic * square_root_magic) * math.pi)
    )
    longitude_offset = (
        longitude_offset
        * 180.0
        / (semi_major_axis / square_root_magic * math.cos(radian_latitude) * math.pi)
    )
    return longitude + longitude_offset, latitude + latitude_offset


def _transform_latitude(x_value: float, y_value: float) -> float:
    result = (
        -100.0
        + 2.0 * x_value
        + 3.0 * y_value
        + 0.2 * y_value**2
        + 0.1 * x_value * y_value
        + 0.2 * math.sqrt(abs(x_value))
    )
    result += (
        (20.0 * math.sin(6.0 * x_value * math.pi) + 20.0 * math.sin(2.0 * x_value * math.pi))
        * 2.0
        / 3.0
    )
    result += (
        (20.0 * math.sin(y_value * math.pi) + 40.0 * math.sin(y_value / 3.0 * math.pi)) * 2.0 / 3.0
    )
    return (
        result
        + (160.0 * math.sin(y_value / 12.0 * math.pi) + 320.0 * math.sin(y_value * math.pi / 30.0))
        * 2.0
        / 3.0
    )


def _transform_longitude(x_value: float, y_value: float) -> float:
    result = (
        300.0
        + x_value
        + 2.0 * y_value
        + 0.1 * x_value**2
        + 0.1 * x_value * y_value
        + 0.1 * math.sqrt(abs(x_value))
    )
    result += (
        (20.0 * math.sin(6.0 * x_value * math.pi) + 20.0 * math.sin(2.0 * x_value * math.pi))
        * 2.0
        / 3.0
    )
    result += (
        (20.0 * math.sin(x_value * math.pi) + 40.0 * math.sin(x_value / 3.0 * math.pi)) * 2.0 / 3.0
    )
    return (
        result
        + (150.0 * math.sin(x_value / 12.0 * math.pi) + 300.0 * math.sin(x_value / 30.0 * math.pi))
        * 2.0
        / 3.0
    )


def _sanitize(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key_value, item in cast(Mapping[object, object], value).items():
            key = str(key_value)
            if _is_sensitive_key(key):
                continue
            if isinstance(item, str) and _is_local_absolute_path(item):
                continue
            result[key] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [
            _sanitize(item)
            for item in cast(list[object], value)
            if not (isinstance(item, str) and _is_local_absolute_path(item))
        ]
    return value


def _is_local_absolute_path(value: str) -> bool:
    return bool(_LOCAL_WINDOWS_PATH.match(value) or _LOCAL_POSIX_PATH.match(value))


def _is_sensitive_key(value: str) -> bool:
    normalized = value.lower()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        (
            "_token",
            "_secret",
            "_password",
            "_api_key",
            "_access_key",
            "_private_key",
            "_credentials",
        )
    )


def _failure_reason(error: Exception) -> str:
    if isinstance(error, WebExportError):
        return str(error)
    if isinstance(error, json.JSONDecodeError):
        return "invalid_source_json"
    return "source_read_failed"


def _stale_snapshot(path: Path, reason: str) -> dict[str, Any]:
    previous = _load_mapping(path, "environment_dashboard.json")
    sanitized = _sanitize(previous)
    if not isinstance(sanitized, dict):
        raise WebExportError("environment_dashboard.json 顶层需要为对象")
    snapshot = cast(dict[str, Any], sanitized)
    for section_name in ("current", "forecast", "grids", "routes"):
        section = snapshot.get(section_name)
        if isinstance(section, dict):
            cast(dict[str, Any], section)["status"] = "stale"
    metadata_value = snapshot.get("metadata")
    if not isinstance(metadata_value, dict):
        metadata_value = {}
        snapshot["metadata"] = metadata_value
    metadata = cast(dict[str, Any], metadata_value)
    metadata["status"] = "stale"
    metadata["stale_reason"] = reason
    return snapshot


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = ["WebExportError", "publish_web_dashboard"]
