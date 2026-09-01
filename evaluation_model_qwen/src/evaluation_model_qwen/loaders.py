from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, TypeVar, cast
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from .models import (
    DataBundle,
    EnvironmentMetric,
    EnvironmentSnapshot,
    PollenMetric,
    RouteEnvironment,
    RouteLocation,
    RouteRecord,
    TimedRecord,
    VerifiedPoi,
)

EXPECTED_ROUTE_COUNT = 90
_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_STATUSES = {"ok", "partial", "stale", "no_data", "error"}
_ENVIRONMENT_URL_ENV = "EVALUATION_MODEL_QWEN_ENVIRONMENT_URL"
_ENVIRONMENT_CACHE_SECONDS_ENV = "EVALUATION_MODEL_QWEN_ENVIRONMENT_CACHE_SECONDS"
_REMOTE_TIMEOUT_SECONDS = 10.0
_MAX_REMOTE_BYTES = 16 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class LoaderError(ValueError):
    """Raised when a source file does not satisfy the evaluation data contract."""


def load_data(
    project_root: Path | None = None,
    route_catalog_path: Path | None = None,
    environment_path: Path | None = None,
) -> DataBundle:
    """Load and validate the route catalog and environment dashboard."""
    root = project_root or _DEFAULT_PROJECT_ROOT
    data_dir = root.parent / "xuhui_route_builder" / "data" / "web"
    route_path = route_catalog_path or data_dir / "route_catalog.json"
    dashboard_path = environment_path or data_dir / "environment_dashboard.json"
    if environment_path is None and os.getenv(_ENVIRONMENT_URL_ENV):
        dashboard_path = _remote_environment_path(
            os.environ[_ENVIRONMENT_URL_ENV],
            root / "runtime" / "cache" / "environment_dashboard.json",
        )

    routes = _load_routes(route_path)
    environment = _load_environment(dashboard_path)
    route_ids = {route.route_id for route in routes}
    environment_ids = set(environment.route_environment)
    if route_ids != environment_ids:
        missing = sorted(route_ids - environment_ids)
        unexpected = sorted(environment_ids - route_ids)
        raise LoaderError(
            f"{route_path} route_catalog[].route_id and "
            f"{dashboard_path} routes.items.route_id do not match: "
            f"missing_in_environment={missing}, unexpected_in_environment={unexpected}"
        )
    return DataBundle(routes=routes, environment=environment)


def _remote_environment_path(url: str, cache_path: Path) -> Path:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise LoaderError(f"{_ENVIRONMENT_URL_ENV} 需为无凭据、无片段的 HTTPS 地址")
    cache_seconds = _environment_cache_seconds()
    if cache_path.is_file() and time.time() - cache_path.stat().st_mtime < cache_seconds:
        return cache_path
    try:
        _download_environment(url, cache_path)
    except (OSError, UnicodeError, json.JSONDecodeError, LoaderError) as exc:
        if cache_path.is_file():
            _LOGGER.warning(
                "environment_download_failed fallback=cache error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return cache_path
        raise LoaderError(f"远端环境数据读取失败: error_type={type(exc).__name__}") from exc
    return cache_path


def _environment_cache_seconds() -> int:
    raw = os.getenv(_ENVIRONMENT_CACHE_SECONDS_ENV, "60")
    try:
        value = int(raw)
    except ValueError as exc:
        raise LoaderError(f"{_ENVIRONMENT_CACHE_SECONDS_ENV} 需为非负整数") from exc
    if value < 0:
        raise LoaderError(f"{_ENVIRONMENT_CACHE_SECONDS_ENV} 需为非负整数")
    return value


def _download_environment(url: str, destination: Path) -> None:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "xuhui-route-qwen-api/1.0"},
    )
    with urlopen(request, timeout=_REMOTE_TIMEOUT_SECONDS) as response:
        payload = response.read(_MAX_REMOTE_BYTES + 1)
    if len(payload) > _MAX_REMOTE_BYTES:
        raise LoaderError("远端环境数据超过 16 MiB 限制")
    document = json.loads(payload.decode("utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    try:
        _load_environment(temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_routes(path: Path) -> list[RouteRecord]:
    raw = _read_json(path)
    values = _array(raw, path, "route_catalog")

    routes: list[RouteRecord] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(values):
        context = f"route_catalog[{index}]"
        item = _mapping(value, path, context)
        route_id = _required(item, "route_id", path, context)
        if not isinstance(route_id, str):
            raise LoaderError(f"{path} {context}.route_id: expected a string")
        if route_id in seen_ids:
            raise LoaderError(f"{path} {context}.route_id: duplicate value {route_id!r}")
        seen_ids.add(route_id)
        routes.append(_parse_route(item, path, context))

    if len(routes) != EXPECTED_ROUTE_COUNT:
        raise LoaderError(
            f"{path} route_catalog: expected {EXPECTED_ROUTE_COUNT} routes, got {len(routes)}"
        )
    return routes


def _parse_route(item: dict[str, Any], path: Path, context: str) -> RouteRecord:
    start = _parse_location(
        _required(item, "start_location", path, context), path, f"{context}.start_location"
    )
    end = _parse_location(
        _required(item, "end_location", path, context), path, f"{context}.end_location"
    )
    pois_raw = _array(_required(item, "nearby_pois", path, context), path, f"{context}.nearby_pois")

    pois: list[VerifiedPoi] = []
    for index, value in enumerate(pois_raw):
        poi_context = f"{context}.nearby_pois[{index}]"
        poi = _mapping(value, path, poi_context)
        if poi.get("verification_status") != "verified":
            continue
        pois.append(
            _model(
                VerifiedPoi,
                {
                    "poi_type": _required(poi, "poi_type", path, poi_context),
                    "poi_name": _required(poi, "poi_name", path, poi_context),
                    "distance_m": _required(poi, "distance_m", path, poi_context),
                },
                path,
                poi_context,
            )
        )

    required_fields = (
        "route_id",
        "route_name",
        "route_mode",
        "route_shape",
        "distance_m",
        "duration_min",
        "region_zone",
        "tags",
        "feature_tags",
        "popular_area_ids",
        "preference_hits",
        "confidence",
        "validation_status",
        "geometry_status",
    )
    selected = {field: _required(item, field, path, context) for field in required_fields}
    selected.update(
        start_location=start,
        end_location=end,
        nearby_pois=pois,
        route_inside_ratio=item.get("route_inside_ratio"),
        snap_ratio=item.get("snap_ratio"),
    )
    return _model(RouteRecord, selected, path, context)


def _parse_location(value: Any, path: Path, context: str) -> RouteLocation:
    item = _mapping(value, path, context)
    selected = {
        field: _required(item, field, path, context) for field in ("name", "lng_gcj02", "lat_gcj02")
    }
    return _model(RouteLocation, selected, path, context)


def _load_environment(path: Path) -> EnvironmentSnapshot:
    dashboard = _mapping(_read_json(path), path, "environment_dashboard")
    metadata = _child_mapping(dashboard, "metadata", path, "environment_dashboard")
    current = _child_mapping(dashboard, "current", path, "environment_dashboard")
    forecast = _child_mapping(dashboard, "forecast", path, "environment_dashboard")
    route_group = _child_mapping(dashboard, "routes", path, "environment_dashboard")

    _validate_status(current, path, "current")
    _validate_status(forecast, path, "forecast")
    _validate_status(route_group, path, "routes")

    alerts = _array(_required(current, "alerts", path, "current"), path, "current.alerts")
    current_alerts = [
        _parse_timed(value, path, f"current.alerts[{index}]") for index, value in enumerate(alerts)
    ]

    weather_hourly = _parse_timed_list(forecast, "weather_hourly", path, "forecast")
    aqi_hourly = _parse_timed_list(forecast, "aqi_hourly", path, "forecast")
    route_environment = _parse_route_environment(route_group, path)

    selected = {
        "generated_at": _required(metadata, "generated_at", path, "metadata"),
        "status": _required(metadata, "status", path, "metadata"),
        "current_weather": _parse_optional_timed(current, "weather", path, "current"),
        "current_aqi": _parse_optional_timed(current, "aqi", path, "current"),
        "current_alerts": current_alerts,
        "weather_hourly": weather_hourly,
        "aqi_hourly": aqi_hourly,
        "route_environment": route_environment,
    }
    return _model(EnvironmentSnapshot, selected, path, "environment_dashboard")


def _parse_optional_timed(
    parent: dict[str, Any], key: str, path: Path, context: str
) -> TimedRecord | None:
    value = _required(parent, key, path, context)
    if value is None:
        return None
    return _parse_timed(value, path, f"{context}.{key}")


def _parse_timed_list(
    parent: dict[str, Any], key: str, path: Path, context: str
) -> list[TimedRecord]:
    values = _array(_required(parent, key, path, context), path, f"{context}.{key}")
    return [
        _parse_timed(value, path, f"{context}.{key}[{index}]") for index, value in enumerate(values)
    ]


def _parse_timed(value: Any, path: Path, context: str) -> TimedRecord:
    item = _mapping(value, path, context)
    selected = {
        "status": _required(item, "status", path, context),
        "business_time": item.get("business_time"),
        "valid_until": item.get("valid_until"),
        "values": _required(item, "values", path, context),
    }
    return _model(TimedRecord, selected, path, context)


def _parse_route_environment(
    route_group: dict[str, Any], path: Path
) -> dict[str, RouteEnvironment]:
    items = _array(_required(route_group, "items", path, "routes"), path, "routes.items")
    declared_count = _required(route_group, "count", path, "routes")
    if declared_count != len(items):
        raise LoaderError(
            f"{path} routes.count: declared {declared_count!r}, got {len(items)} items"
        )
    if len(items) != EXPECTED_ROUTE_COUNT:
        raise LoaderError(
            f"{path} routes.items: expected {EXPECTED_ROUTE_COUNT} routes, got {len(items)}"
        )

    result: dict[str, RouteEnvironment] = {}
    for index, value in enumerate(items):
        context = f"routes.items[{index}]"
        item = _mapping(value, path, context)
        route_id = _required(item, "route_id", path, context)
        if not isinstance(route_id, str):
            raise LoaderError(f"{path} {context}.route_id: expected a string")
        if route_id in result:
            raise LoaderError(f"{path} {context}.route_id: duplicate value {route_id!r}")
        selected = {
            "route_id": route_id,
            "status": _required(item, "status", path, context),
            "pm2_5": _parse_metric(item, "pm2_5", EnvironmentMetric, path, context),
            "noise": _parse_metric(item, "noise", EnvironmentMetric, path, context),
            "pollen_daily": _parse_pollen(item, path, context),
        }
        result[route_id] = _model(RouteEnvironment, selected, path, context)
    return result


def _parse_pollen(item: dict[str, Any], path: Path, context: str) -> list[PollenMetric]:
    values = _array(_required(item, "pollen_daily", path, context), path, f"{context}.pollen_daily")
    return [
        _parse_metric_value(
            value,
            PollenMetric,
            path,
            f"{context}.pollen_daily[{index}]",
        )
        for index, value in enumerate(values)
    ]


def _parse_metric(
    parent: dict[str, Any],
    key: str,
    model: type[_ModelT],
    path: Path,
    context: str,
) -> _ModelT:
    return _parse_metric_value(
        _required(parent, key, path, context), model, path, f"{context}.{key}"
    )


def _parse_metric_value(value: Any, model: type[_ModelT], path: Path, context: str) -> _ModelT:
    item = _mapping(value, path, context)
    selected = {
        "status": _required(item, "status", path, context),
        "value": item.get("value"),
        "business_time": item.get("business_time"),
        "fetched_at": item.get("fetched_at"),
        "valid_until": item.get("expires_at"),
        "confidence": _required(item, "confidence", path, context),
        "estimated": _required(item, "estimated", path, context),
        "spatial_scale": _required(item, "spatial_scale", path, context),
        "unit": _required(item, "unit", path, context),
        "scenarios": item.get("scenarios", {}),
    }
    if model is PollenMetric:
        selected["risk_level"] = item.get("risk_level")
    return _model(model, selected, path, context)


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except json.JSONDecodeError as error:
        raise LoaderError(
            f"{path} JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error
    except (OSError, UnicodeError) as error:
        raise LoaderError(f"{path} file: {error}") from error


def _mapping(value: Any, path: Path, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LoaderError(f"{path} {context}: expected an object")
    return cast(dict[str, Any], value)


def _array(value: Any, path: Path, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise LoaderError(f"{path} {context}: expected an array")
    return cast(list[Any], value)


def _child_mapping(parent: dict[str, Any], key: str, path: Path, context: str) -> dict[str, Any]:
    return _mapping(_required(parent, key, path, context), path, f"{context}.{key}")


def _required(parent: dict[str, Any], key: str, path: Path, context: str) -> Any:
    if key not in parent:
        raise LoaderError(f"{path} {context}.{key}: missing required field")
    return parent[key]


def _validate_status(parent: dict[str, Any], path: Path, context: str) -> None:
    status = _required(parent, "status", path, context)
    if not isinstance(status, str) or status not in _DATA_STATUSES:
        raise LoaderError(f"{path} {context}.status: invalid value {status!r}")


def _model(model: type[_ModelT], selected: dict[str, Any], path: Path, context: str) -> _ModelT:
    try:
        return model.model_validate(selected)
    except ValidationError as error:
        detail = error.errors(include_url=False)[0]
        location = ".".join(str(part) for part in detail["loc"])
        field = f"{context}.{location}" if location else context
        raise LoaderError(f"{path} {field}: {detail['msg']}") from error
