"""WeatherCN v1 响应形状校验与业务字段标准化。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal, cast

from weather_api_data.http_client import HttpResult
from weather_api_data.models import NormalizedRecord, Status

_MISSING = object()
_PayloadKind = Literal["list", "dict"]


class ResponseShapeError(ValueError):
    """端点响应与已知 v1 顶层形状不一致。"""

    def __init__(self, endpoint: str, detail: str) -> None:
        self.endpoint = endpoint
        self.detail = detail
        super().__init__(f"{endpoint}: {detail}")


@dataclass(frozen=True, slots=True)
class _EndpointSpec:
    payload_kind: _PayloadKind
    dataset_type: str
    dataset_role: str
    granularity: str
    family: str
    required_fields: tuple[str, ...]


_WEATHER_FIELDS = (
    "temperature_c",
    "relative_humidity_pct",
    "weather_text",
    "weather_icon",
    "real_feel_temperature_c",
    "wind_direction_deg",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "pressure_mb",
    "visibility_km",
    "uv_index",
    "precipitation_mm",
    "precipitation_probability_pct",
)
_HOURLY_WEATHER_FIELDS = tuple(field for field in _WEATHER_FIELDS if field != "pressure_mb")
_AIR_FIELDS = (
    "aqi",
    "pm2_5_ug_m3",
    "pm10_ug_m3",
    "ozone_ug_m3",
    "nitrogen_dioxide_ug_m3",
    "sulfur_dioxide_ug_m3",
    "carbon_monoxide_mg_m3",
)
_INDEX_FIELDS = (
    "index_id",
    "name",
    "value",
    "category",
    "category_value",
    "text",
    "local_date_time",
)
_ALERT_FIELDS = (
    "alert_id",
    "type",
    "level",
    "source",
    "start_time",
    "end_time",
    "summary",
    "text",
)
_CLIMO_FIELDS = ("date", "epoch_date", "actuals")

_SPECS = {
    "current_conditions": _EndpointSpec(
        "list",
        "weather_observation",
        "operational",
        "current",
        "current_weather",
        (*_WEATHER_FIELDS, "business_time"),
    ),
    "historical_24": _EndpointSpec(
        "list",
        "weather_observation",
        "operational",
        "hourly",
        "current_weather",
        (*_WEATHER_FIELDS, "business_time"),
    ),
    "hourly_weather_24": _EndpointSpec(
        "list",
        "weather_forecast",
        "operational",
        "hourly",
        "hourly_weather",
        (*_HOURLY_WEATHER_FIELDS, "business_time"),
    ),
    "current_air_quality": _EndpointSpec(
        "dict",
        "air_quality_observation",
        "operational",
        "current",
        "current_air",
        (*_AIR_FIELDS, "business_time"),
    ),
    "hourly_air_quality_24": _EndpointSpec(
        "list",
        "air_quality_forecast",
        "operational",
        "hourly",
        "hourly_air",
        (*_AIR_FIELDS, "business_time"),
    ),
    "indices_1day": _EndpointSpec(
        "list",
        "life_index",
        "operational",
        "daily",
        "index",
        (*_INDEX_FIELDS, "business_time"),
    ),
    "indices_5day": _EndpointSpec(
        "list",
        "life_index",
        "operational",
        "daily",
        "index",
        (*_INDEX_FIELDS, "business_time"),
    ),
    "alerts": _EndpointSpec(
        "list",
        "weather_alert",
        "operational",
        "event",
        "alert",
        (*_ALERT_FIELDS, "business_time"),
    ),
    "climo_actuals": _EndpointSpec(
        "list",
        "climate_actual",
        "backfill_2025",
        "daily",
        "climo",
        (*_CLIMO_FIELDS, "business_time"),
    ),
}

_WEATHER_UNITS: dict[str, object] = {
    "temperature_c": "C",
    "relative_humidity_pct": "%",
    "real_feel_temperature_c": "C",
    "wind_direction_deg": "degree",
    "wind_speed_kmh": "km/h",
    "wind_gust_kmh": "km/h",
    "pressure_mb": "mb",
    "visibility_km": "km",
    "uv_index": "index",
    "precipitation_mm": "mm",
    "precipitation_probability_pct": "%",
}
_AIR_UNITS: dict[str, object] = {
    "aqi": "index",
    "pm2_5_ug_m3": "ug/m3",
    "pm10_ug_m3": "ug/m3",
    "ozone_ug_m3": "ug/m3",
    "nitrogen_dioxide_ug_m3": "ug/m3",
    "sulfur_dioxide_ug_m3": "ug/m3",
    "carbon_monoxide_mg_m3": "mg/m3",
}


class Normalizer:
    """将已知 WeatherCN v1 业务响应转为统一记录。"""

    def normalize(
        self,
        endpoint: str,
        result: HttpResult,
        location_key: str,
        probe_point_ids: tuple[str, ...] = (),
    ) -> list[NormalizedRecord]:
        spec = _SPECS.get(endpoint)
        if spec is None:
            raise ResponseShapeError(endpoint, "未知端点")

        raw_records = _business_objects(endpoint, result.payload, spec.payload_kind)
        fetched_at = _utc_iso(result.fetched_at)
        valid_until, is_stale = _expiry(endpoint, result.expires, result.fetched_at)
        point_ids = tuple(probe_point_ids)

        if not raw_records:
            return [
                NormalizedRecord(
                    dataset_type=spec.dataset_type,
                    dataset_role=spec.dataset_role,
                    granularity=spec.granularity,
                    location_key=location_key,
                    probe_point_ids=point_ids,
                    business_time=None,
                    fetched_at=fetched_at,
                    valid_until=valid_until,
                    status="no_data",
                    source={},
                    values={},
                    units={},
                    completeness=0.0,
                    missing_fields=spec.required_fields,
                    raw_data={},
                )
            ]

        return [
            self._normalize_object(
                spec,
                raw,
                location_key,
                point_ids,
                fetched_at,
                valid_until,
                is_stale,
            )
            for raw in raw_records
        ]

    @staticmethod
    def _normalize_object(
        spec: _EndpointSpec,
        raw: Mapping[str, object],
        location_key: str,
        probe_point_ids: tuple[str, ...],
        fetched_at: str,
        valid_until: str | None,
        is_stale: bool,
    ) -> NormalizedRecord:
        values, units, source, business_time = _map_object(spec.family, raw)
        present = set(values)
        if business_time is not None:
            present.add("business_time")
        missing_fields = tuple(field for field in spec.required_fields if field not in present)
        completeness = (len(spec.required_fields) - len(missing_fields)) / len(spec.required_fields)
        status: Status = "partial" if missing_fields else "ok"
        if is_stale:
            status = "stale"

        return NormalizedRecord(
            dataset_type=spec.dataset_type,
            dataset_role=spec.dataset_role,
            granularity=spec.granularity,
            location_key=location_key,
            probe_point_ids=probe_point_ids,
            business_time=business_time,
            fetched_at=fetched_at,
            valid_until=valid_until,
            status=status,
            source=source,
            values=values,
            units=units,
            completeness=completeness,
            missing_fields=missing_fields,
            raw_data=raw,
        )


def _business_objects(
    endpoint: str, payload: object, payload_kind: _PayloadKind
) -> list[Mapping[str, object]]:
    if endpoint == "hourly_air_quality_24":
        if not isinstance(payload, dict):
            raise ResponseShapeError(endpoint, "顶层响应应为 dict")
        payload_mapping = cast(Mapping[str, object], payload)
        forecasts = payload_mapping.get("Forecasts")
        if not isinstance(forecasts, list):
            raise ResponseShapeError(endpoint, "Forecasts 应为 list")
        payload = cast(list[object], forecasts)

    if payload_kind == "dict":
        if not isinstance(payload, dict):
            raise ResponseShapeError(endpoint, "顶层响应应为 dict")
        if not payload:
            return []
        return [cast(Mapping[str, object], payload)]

    if not isinstance(payload, list):
        raise ResponseShapeError(endpoint, "顶层响应应为 list")
    records: list[Mapping[str, object]] = []
    payload_items = cast(list[object], payload)
    for index, item in enumerate(payload_items):
        if not isinstance(item, dict):
            raise ResponseShapeError(endpoint, f"第 {index} 项应为 dict")
        records.append(cast(Mapping[str, object], item))
    return records


def _map_object(
    family: str, raw: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str | None]:
    if family in {"current_weather", "hourly_weather"}:
        return _map_weather(raw, forecast=family == "hourly_weather")
    if family in {"current_air", "hourly_air"}:
        return _map_air(raw, forecast=family == "hourly_air")
    if family == "index":
        return _map_index(raw)
    if family == "alert":
        return _map_alert(raw)
    if family == "climo":
        return _map_climo(raw)
    raise AssertionError(f"未实现的端点类别: {family}")


def _map_weather(
    raw: Mapping[str, object], *, forecast: bool
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str | None]:
    values: dict[str, object] = {}
    if forecast:
        temperature = _nested(raw, "Temperature", "Value")
        real_feel = _nested(raw, "RealFeelTemperature", "Value")
        wind_speed = _nested(raw, "Wind", "Speed", "Value")
        wind_gust = _nested(raw, "WindGust", "Speed", "Value")
        pressure = _nested(raw, "Pressure", "Value")
        visibility = _nested(raw, "Visibility", "Value")
    else:
        temperature = _nested(raw, "Temperature", "Metric", "Value")
        real_feel = _nested(raw, "RealFeelTemperature", "Metric", "Value")
        wind_speed = _nested(raw, "Wind", "Speed", "Metric", "Value")
        wind_gust = _nested(raw, "WindGust", "Speed", "Metric", "Value")
        pressure = _nested(raw, "Pressure", "Metric", "Value")
        visibility = _nested(raw, "Visibility", "Metric", "Value")

    _put(values, "temperature_c", temperature)
    _put(values, "relative_humidity_pct", raw.get("RelativeHumidity", _MISSING))
    text_keys = ("IconPhrase", "WeatherText") if forecast else ("WeatherText", "IconPhrase")
    _put(values, "weather_text", _first(raw, text_keys))
    _put(values, "weather_icon", raw.get("WeatherIcon", _MISSING))
    _put(values, "real_feel_temperature_c", real_feel)
    _put(values, "wind_direction_deg", _nested(raw, "Wind", "Direction", "Degrees"))
    _put(values, "wind_speed_kmh", wind_speed)
    _put(values, "wind_gust_kmh", wind_gust)
    _put(values, "pressure_mb", pressure)
    _put(values, "visibility_km", visibility)
    _put(values, "uv_index", raw.get("UVIndex", _MISSING))
    precipitation = _nested(raw, "PrecipitationSummary", "Precipitation", "Metric", "Value")
    if precipitation is _MISSING:
        precipitation = _nested(raw, "TotalLiquid", "Value")
    _put(values, "precipitation_mm", precipitation)
    _put(
        values,
        "precipitation_probability_pct",
        raw.get("PrecipitationProbability", _MISSING),
    )
    business_time = _as_string(
        raw.get("DateTime" if forecast else "LocalObservationDateTime", _MISSING)
    )
    return values, dict(_WEATHER_UNITS), _source(raw), business_time


def _map_air(
    raw: Mapping[str, object], *, forecast: bool
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str | None]:
    values: dict[str, object] = {}
    for output_name, input_name in (
        ("aqi", "AirQuality" if forecast else "Index"),
        ("pm2_5_ug_m3", "ParticulateMatter2_5"),
        ("pm10_ug_m3", "ParticulateMatter10"),
        ("ozone_ug_m3", "Ozone"),
        ("nitrogen_dioxide_ug_m3", "NitrogenDioxide"),
        ("sulfur_dioxide_ug_m3", "SulfurDioxide"),
        ("carbon_monoxide_mg_m3", "CarbonMonoxide"),
    ):
        value = raw.get(input_name, _MISSING)
        _put(values, output_name, _as_number(value) if forecast else value)
    business_time = _as_string(raw.get("StartDateTime" if forecast else "Date", _MISSING))
    return values, dict(_AIR_UNITS), _source(raw, include_air_source=True), business_time


def _map_index(
    raw: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str | None]:
    values: dict[str, object] = {}
    for output_name, input_name in (
        ("index_id", "ID"),
        ("name", "Name"),
        ("value", "Value"),
        ("category", "Category"),
        ("category_value", "CategoryValue"),
        ("text", "Text"),
        ("local_date_time", "LocalDateTime"),
    ):
        _put(values, output_name, raw.get(input_name, _MISSING))
    return values, {}, _source(raw), _as_string(raw.get("LocalDateTime", _MISSING))


def _map_alert(
    raw: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str | None]:
    values: dict[str, object] = {}
    for output_name, input_name in (
        ("alert_id", "AlertID"),
        ("type", "Type"),
        ("level", "Level"),
        ("source", "Source"),
    ):
        _put(values, output_name, raw.get(input_name, _MISSING))

    area = _first_area(raw)
    for output_name, input_name in (
        ("start_time", "StartTime"),
        ("end_time", "EndTime"),
        ("summary", "Summary"),
        ("text", "Text"),
    ):
        _put(values, output_name, area.get(input_name, _MISSING))
    return values, {}, _source(raw), _as_string(area.get("StartTime", _MISSING))


def _map_climo(
    raw: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str | None]:
    values: dict[str, object] = {}
    for output_name, input_name in (
        ("date", "Date"),
        ("epoch_date", "EpochDate"),
        ("actuals", "Actuals"),
    ):
        _put(values, output_name, raw.get(input_name, _MISSING))
    return values, {}, _source(raw), _as_string(raw.get("Date", _MISSING))


def _source(raw: Mapping[str, object], *, include_air_source: bool = False) -> dict[str, object]:
    source: dict[str, object] = {}
    local_source = raw.get("LocalSource", _MISSING)
    if isinstance(local_source, Mapping):
        local_mapping = cast(Mapping[str, object], local_source)
        local_id = local_mapping.get("Id", _MISSING)
        local_name = local_mapping.get("Name", _MISSING)
        _put(source, "local_source_id", local_id)
        _put(source, "local_source_name", local_name)
        if local_id is _MISSING or local_id is None:
            source["source_status"] = "unknown"
        elif local_id == 7:
            source["source_status"] = "expected_local_source"
        else:
            source["source_status"] = "unexpected_local_source"
    elif local_source is _MISSING or local_source is None:
        source["source_status"] = "unknown"

    if include_air_source:
        _put(source, "air_quality_source", raw.get("Source", _MISSING))
    return source


def _first_area(raw: Mapping[str, object]) -> Mapping[str, object]:
    areas = raw.get("Area", _MISSING)
    if not isinstance(areas, list) or not areas or not isinstance(areas[0], dict):
        return {}
    return cast(Mapping[str, object], areas[0])


def _nested(raw: Mapping[str, object], *path: str) -> object:
    if not path:
        return raw
    current = raw.get(path[0], _MISSING)
    for key in path[1:]:
        if not isinstance(current, dict):
            return _MISSING
        current = cast(dict[str, object], current).get(key, _MISSING)
        if current is _MISSING:
            return _MISSING
    return current


def _first(raw: Mapping[str, object], keys: tuple[str, ...]) -> object:
    for key in keys:
        value = raw.get(key, _MISSING)
        if value is not _MISSING and value is not None:
            return value
    return _MISSING


def _put(target: dict[str, object], key: str, value: object) -> None:
    if value is not _MISSING and value is not None:
        target[key] = value


def _as_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_number(value: object) -> object:
    if isinstance(value, bool):
        return _MISSING
    if isinstance(value, (int, float)):
        converted = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            converted = float(value)
        except ValueError:
            return _MISSING
    else:
        return _MISSING
    if not math.isfinite(converted):
        return _MISSING
    return int(converted) if converted.is_integer() else converted


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _expiry(endpoint: str, expires: str | None, fetched_at: datetime) -> tuple[str | None, bool]:
    if expires is None:
        return None, False
    try:
        parsed = parsedate_to_datetime(expires)
    except (TypeError, ValueError, OverflowError):
        raise ResponseShapeError(endpoint, "Expires 不是有效的 HTTP 日期") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed_utc = parsed.astimezone(timezone.utc)
    fetched_utc = (
        fetched_at.replace(tzinfo=timezone.utc) if fetched_at.tzinfo is None else fetched_at
    )
    return parsed_utc.isoformat(), parsed_utc < fetched_utc.astimezone(timezone.utc)


__all__ = ["Normalizer", "ResponseShapeError"]
