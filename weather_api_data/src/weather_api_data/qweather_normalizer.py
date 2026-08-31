"""和风天气响应到项目统一记录的标准化。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import cast

from weather_api_data.http_client import HttpResult
from weather_api_data.models import NormalizedRecord
from weather_api_data.normalizer import ResponseShapeError
from weather_api_data.qweather_client import coordinates_from_source_id

_SHANGHAI = timezone(timedelta(hours=8))
_AIR_FIELDS = (
    "aqi",
    "pm2_5_ug_m3",
    "pm10_ug_m3",
    "ozone_ug_m3",
    "nitrogen_dioxide_ug_m3",
    "sulfur_dioxide_ug_m3",
    "carbon_monoxide_mg_m3",
)
_AIR_UNITS = {
    "aqi": "index",
    "pm2_5_ug_m3": "ug/m3",
    "pm10_ug_m3": "ug/m3",
    "ozone_ug_m3": "ug/m3",
    "nitrogen_dioxide_ug_m3": "ug/m3",
    "sulfur_dioxide_ug_m3": "ug/m3",
    "carbon_monoxide_mg_m3": "mg/m3",
}
_WEATHER_UNITS = {
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
_REQUIRED = {
    "current_conditions": (
        "temperature_c",
        "relative_humidity_pct",
        "weather_text",
        "wind_speed_kmh",
        "pressure_mb",
        "visibility_km",
        "business_time",
    ),
    "hourly_weather_24": (
        "temperature_c",
        "relative_humidity_pct",
        "weather_text",
        "wind_speed_kmh",
        "precipitation_probability_pct",
        "business_time",
    ),
    "current_air_quality": (*_AIR_FIELDS, "business_time"),
    "hourly_air_quality_24": (*_AIR_FIELDS, "business_time"),
    "indices_3day": (
        "index_id",
        "name",
        "value",
        "category",
        "text",
        "business_time",
    ),
    "alerts": ("alert_id", "type", "source", "summary", "text", "business_time"),
}
_TTL = {
    "current_conditions": timedelta(minutes=15),
    "hourly_weather_24": timedelta(hours=1),
    "current_air_quality": timedelta(hours=1),
    "hourly_air_quality_24": timedelta(hours=1),
    "indices_3day": timedelta(hours=1),
    "alerts": timedelta(minutes=5),
}
_POLLUTANT_FIELDS = {
    "pm2p5": "pm2_5_ug_m3",
    "pm10": "pm10_ug_m3",
    "o3": "ozone_ug_m3",
    "no2": "nitrogen_dioxide_ug_m3",
    "so2": "sulfur_dioxide_ug_m3",
    "co": "carbon_monoxide_mg_m3",
}


class QWeatherNormalizer:
    """按字段 code 和 unit 解析和风六类响应。"""

    def normalize(
        self,
        endpoint: str,
        result: HttpResult,
        source_id: str,
        probe_point_ids: tuple[str, ...] = (),
    ) -> list[NormalizedRecord]:
        if endpoint not in _REQUIRED:
            raise ResponseShapeError(endpoint, "未知和风端点")
        payload = _mapping(result.payload, endpoint)
        raw_records = _business_records(endpoint, payload)
        fetched_at = _utc_iso(result.fetched_at)
        valid_until = _valid_until(endpoint, result)
        if endpoint == "alerts" and not raw_records:
            return []
        if not raw_records:
            return [
                NormalizedRecord(
                    dataset_type=_dataset_type(endpoint),
                    dataset_role="operational",
                    granularity=_granularity(endpoint),
                    location_key=source_id,
                    probe_point_ids=tuple(probe_point_ids),
                    business_time=None,
                    fetched_at=fetched_at,
                    valid_until=valid_until,
                    status="no_data",
                    source=_source(endpoint, payload, source_id, None),
                    values={},
                    units={},
                    completeness=0.0,
                    missing_fields=_REQUIRED[endpoint],
                    raw_data={},
                )
            ]

        records: list[NormalizedRecord] = []
        for raw in raw_records:
            values, units, business_time, aqi_standard = _normalize_values(
                endpoint,
                raw,
                result.fetched_at,
            )
            missing = tuple(
                field
                for field in _REQUIRED[endpoint]
                if (business_time is None if field == "business_time" else field not in values)
            )
            records.append(
                NormalizedRecord(
                    dataset_type=_dataset_type(endpoint),
                    dataset_role="operational",
                    granularity=_granularity(endpoint),
                    location_key=source_id,
                    probe_point_ids=tuple(probe_point_ids),
                    business_time=business_time,
                    fetched_at=fetched_at,
                    valid_until=valid_until,
                    status="ok" if not missing else "partial",
                    source=_source(endpoint, payload, source_id, aqi_standard),
                    values=values,
                    units=units,
                    completeness=round(1 - len(missing) / len(_REQUIRED[endpoint]), 6),
                    missing_fields=missing,
                    raw_data=dict(raw),
                )
            )
        return records


def _business_records(
    endpoint: str,
    payload: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    if endpoint in {"current_conditions", "current_air_quality"}:
        return (payload,)
    field = {
        "hourly_weather_24": "hours",
        "hourly_air_quality_24": "hours",
        "indices_3day": "daily",
        "alerts": "alerts",
    }[endpoint]
    value = payload.get(field)
    if value is None and endpoint == "alerts" and _zero_result(payload):
        return ()
    if not isinstance(value, list):
        raise ResponseShapeError(endpoint, f"{field} 应为数组")
    records: list[Mapping[str, object]] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, Mapping):
            raise ResponseShapeError(endpoint, f"{field}[{index}] 应为对象")
        records.append(cast(Mapping[str, object], item))
    return tuple(records)


def _normalize_values(
    endpoint: str,
    raw: Mapping[str, object],
    fetched_at: datetime,
) -> tuple[dict[str, object], dict[str, object], str | None, str | None]:
    if endpoint in {"current_conditions", "hourly_weather_24"}:
        values = _weather_values(raw)
        business_time = (
            _utc_iso(fetched_at)
            if endpoint == "current_conditions"
            else _time(raw.get("forecastTime"))
        )
        return (
            values,
            {key: _WEATHER_UNITS[key] for key in values if key in _WEATHER_UNITS},
            business_time,
            None,
        )
    if endpoint in {"current_air_quality", "hourly_air_quality_24"}:
        values, aqi_standard = _air_values(raw)
        business_time = (
            _fetched_hour(fetched_at)
            if endpoint == "current_air_quality"
            else _time(raw.get("forecastTime"))
        )
        return values, {key: _AIR_UNITS[key] for key in values}, business_time, aqi_standard
    if endpoint == "indices_3day":
        business_time = _date_time(raw.get("date"))
        values = _index_values(raw)
        return values, {}, business_time, None
    business_time = _time(raw.get("issuedTime"))
    values = _alert_values(raw)
    return values, {}, business_time, None


def _weather_values(raw: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    _put(values, "weather_text", _path(raw, "condition", "text"))
    _put(values, "weather_icon", _path(raw, "condition", "code"))
    _put(values, "temperature_c", _quantity(raw.get("temperature"), {"°C", "C"}))
    _put(values, "real_feel_temperature_c", _quantity(raw.get("feelsLike"), {"°C", "C"}))
    humidity = _number(raw.get("humidity"))
    if humidity is not None and 0 <= humidity <= 1:
        values["relative_humidity_pct"] = humidity * 100
    _put(values, "wind_direction_deg", _path(raw, "wind", "direction", "degree"))
    _put(values, "wind_speed_kmh", _speed(_path(raw, "wind", "speed")))
    _put(values, "wind_gust_kmh", _speed(raw.get("windGust")))
    _put(values, "pressure_mb", _quantity(raw.get("pressure"), {"hPa", "mb"}))
    _put(values, "visibility_km", _distance_km(raw.get("visibility")))
    _put(values, "uv_index", _quantity_or_number(raw.get("uvIndex"), {"index"}))
    _put(values, "precipitation_mm", _quantity(_path(raw, "precipitation", "amount"), {"mm"}))
    probability = _number(_path(raw, "precipitation", "probability"))
    if probability is not None and 0 <= probability <= 1:
        values["precipitation_probability_pct"] = probability * 100
    return values


def _air_values(raw: Mapping[str, object]) -> tuple[dict[str, object], str | None]:
    values: dict[str, object] = {}
    aqi_standard: str | None = None
    indexes = _mapping_list(raw.get("indexes"))
    for preferred in ("cn-mee-1h", "cn-mee"):
        index = next((item for item in indexes if item.get("code") == preferred), None)
        if index is not None:
            aqi = _number(index.get("aqi"))
            if aqi is not None:
                values["aqi"] = aqi
                aqi_standard = preferred
            break
    for pollutant in _mapping_list(raw.get("pollutants")):
        code = pollutant.get("code")
        if not isinstance(code, str) or code not in _POLLUTANT_FIELDS:
            continue
        field = _POLLUTANT_FIELDS[code]
        concentration = pollutant.get("concentration")
        if not isinstance(concentration, Mapping):
            continue
        quantity = cast(Mapping[str, object], concentration)
        value = _mass_concentration(quantity, carbon_monoxide=code == "co")
        _put(values, field, value)
    return values, aqi_standard


def _index_values(raw: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    _put(values, "index_id", raw.get("type"))
    _put(values, "name", raw.get("name"))
    _put(values, "value", raw.get("level"))
    _put(values, "category", raw.get("category"))
    _put(values, "category_value", raw.get("level"))
    _put(values, "text", raw.get("text"))
    _put(values, "local_date_time", raw.get("date"))
    return values


def _alert_values(raw: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    _put(values, "alert_id", raw.get("id"))
    _put(values, "type", _path(raw, "eventType", "name"))
    _put(values, "level", raw.get("severity"))
    _put(values, "source", raw.get("senderName"))
    _put(values, "start_time", raw.get("effectiveTime"))
    _put(values, "end_time", raw.get("expireTime"))
    _put(values, "onset_time", raw.get("onsetTime"))
    _put(values, "issued_time", raw.get("issuedTime"))
    _put(values, "summary", raw.get("headline"))
    _put(values, "text", raw.get("description"))
    _put(values, "instruction", raw.get("instruction"))
    _put(values, "criteria", raw.get("criteria"))
    _put(values, "color_code", _path(raw, "color", "code"))
    return values


def _source(
    endpoint: str,
    payload: Mapping[str, object],
    source_id: str,
    aqi_standard: str | None,
) -> dict[str, object]:
    latitude, longitude = coordinates_from_source_id(source_id)
    source: dict[str, object] = {
        "provider": "qweather",
        "source_id": source_id,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "attributions": _attributions(payload),
    }
    if endpoint in {"current_conditions", "current_air_quality"}:
        source["time_basis"] = (
            "fetched_at" if endpoint == "current_conditions" else "fetched_at_shanghai_hour"
        )
    if "air_quality" in endpoint:
        source["spatial_resolution"] = "1x1_km"
        source["is_estimated"] = True
        source["air_quality_source"] = "QWeather 1x1 km coordinate product"
        source["aqi_standard"] = aqi_standard
    return source


def _attributions(payload: Mapping[str, object]) -> list[str]:
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        value = cast(Mapping[str, object], metadata).get("attributions")
        if isinstance(value, list):
            return [item for item in cast(list[object], value) if isinstance(item, str)]
    refer = payload.get("refer")
    if isinstance(refer, Mapping):
        value = cast(Mapping[str, object], refer).get("sources")
        if isinstance(value, list):
            return [item for item in cast(list[object], value) if isinstance(item, str)]
    return []


def _dataset_type(endpoint: str) -> str:
    return {
        "current_conditions": "weather_observation",
        "hourly_weather_24": "weather_forecast",
        "current_air_quality": "air_quality_observation",
        "hourly_air_quality_24": "air_quality_forecast",
        "indices_3day": "life_index",
        "alerts": "weather_alert",
    }[endpoint]


def _granularity(endpoint: str) -> str:
    return {
        "current_conditions": "current",
        "hourly_weather_24": "hourly",
        "current_air_quality": "current",
        "hourly_air_quality_24": "hourly",
        "indices_3day": "daily",
        "alerts": "event",
    }[endpoint]


def _valid_until(endpoint: str, result: HttpResult) -> str:
    ttl_expiry = _aware(result.fetched_at) + _TTL[endpoint]
    if result.expires:
        try:
            expires = parsedate_to_datetime(result.expires)
            if expires.tzinfo is not None:
                if endpoint == "indices_3day":
                    expires = min(expires, ttl_expiry)
                return _utc_iso(expires)
        except (TypeError, ValueError, OverflowError):
            pass
    return _utc_iso(ttl_expiry)


def _zero_result(payload: Mapping[str, object]) -> bool:
    metadata = payload.get("metadata")
    return (
        isinstance(metadata, Mapping)
        and cast(Mapping[str, object], metadata).get("zeroResult") is True
    )


def _fetched_hour(value: datetime) -> str:
    local = _aware(value).astimezone(_SHANGHAI).replace(minute=0, second=0, microsecond=0)
    return local.isoformat()


def _date_time(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=_SHANGHAI).isoformat()
    except ValueError:
        return None


def _time(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat()


def _mapping(value: object, endpoint: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResponseShapeError(endpoint, "响应顶层应为对象")
    return cast(Mapping[str, object], value)


def _mapping_list(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        cast(Mapping[str, object], item)
        for item in cast(list[object], value)
        if isinstance(item, Mapping)
    )


def _path(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = cast(Mapping[str, object], current).get(key)
    return current


def _quantity(value: object, accepted_units: set[str]) -> float | None:
    if not isinstance(value, Mapping):
        return None
    quantity = cast(Mapping[str, object], value)
    if quantity.get("unit") not in accepted_units:
        return None
    return _number(quantity.get("value"))


def _quantity_or_number(value: object, accepted_units: set[str]) -> float | None:
    direct = _number(value)
    return direct if direct is not None else _quantity(value, accepted_units)


def _speed(value: object) -> float | None:
    if not isinstance(value, Mapping):
        return None
    quantity = cast(Mapping[str, object], value)
    number = _number(quantity.get("value"))
    if number is None:
        return None
    unit = quantity.get("unit")
    if unit == "m/s":
        return number * 3.6
    if unit == "km/h":
        return number
    return None


def _distance_km(value: object) -> float | None:
    if not isinstance(value, Mapping):
        return None
    quantity = cast(Mapping[str, object], value)
    number = _number(quantity.get("value"))
    if number is None:
        return None
    if quantity.get("unit") == "m":
        return number / 1000
    if quantity.get("unit") == "km":
        return number
    return None


def _mass_concentration(
    value: Mapping[str, object],
    *,
    carbon_monoxide: bool,
) -> float | None:
    number = _number(value.get("value"))
    if number is None or number < 0:
        return None
    unit = str(value.get("unit", "")).replace("³", "3").replace("µ", "μ")
    if unit in {"μg/m3", "ug/m3"}:
        return number / 1000 if carbon_monoxide else number
    if unit == "mg/m3":
        return number if carbon_monoxide else number * 1000
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _put(target: dict[str, object], key: str, value: object) -> None:
    if value is not None:
        target[key] = value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _utc_iso(value: datetime) -> str:
    return _aware(value).astimezone(timezone.utc).isoformat()


__all__ = ["QWeatherNormalizer"]
