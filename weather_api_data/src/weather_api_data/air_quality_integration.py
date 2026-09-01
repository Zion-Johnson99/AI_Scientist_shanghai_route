"""将和风、上海站点和跨区融合统一为 11 区空气质量记录。"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import cast

from weather_api_data.aqi import calculate_aqi
from weather_api_data.qweather_client import coordinates_from_source_id
from weather_api_data.zone_air_quality import blend_pollutants

_OFFICIAL_STATION_PAGE = (
    "https://link.sthj.sh.gov.cn/aqi/kqzl/"
    "kqzlCountyhourlydataController/subarea/toSubareaDetail.do?groupid=204"
)
_UNIFIED_FIELDS = {
    "provider",
    "spatial_basis",
    "spatial_id",
    "zone_ids",
    "observed_at",
    "fetched_at",
    "values",
    "units",
    "status",
    "is_estimated",
    "components",
    "source_url",
}
_POLLUTANTS = {
    "pm2_5_ug_m3",
    "pm10_ug_m3",
    "ozone_ug_m3",
    "nitrogen_dioxide_ug_m3",
    "sulfur_dioxide_ug_m3",
    "carbon_monoxide_mg_m3",
}


def build_zone_air_quality_records(
    zones: Sequence[Mapping[str, object]],
    provider_records: Sequence[Mapping[str, object]],
    station_records: Sequence[Mapping[str, object]],
    *,
    provider_base_url: str,
) -> tuple[dict[str, object], ...]:
    """按分区策略生成固定十二字段的当前空气质量记录。"""

    point_records = _index_provider_records(provider_records)
    station_index = {
        str(record.get("spatial_id")): record
        for record in station_records
        if record.get("spatial_id") is not None
    }
    output: list[dict[str, object]] = []
    for zone in zones:
        zone_id = _required_text(zone, "zone_id")
        strategy = _required_text(zone, "source_strategy")
        if strategy == "qweather_direct":
            record = _direct_record(zone_id, zone, point_records, provider_base_url)
        elif strategy == "shanghai_station":
            record = _station_record(zone_id, zone, station_index)
        elif strategy == "district_blend":
            record = _blend_record(zone_id, zone, point_records, provider_base_url)
        else:
            raise ValueError(f"未知空气质量分区策略: {strategy}")
        if set(record) != _UNIFIED_FIELDS:
            raise AssertionError("分区空气质量记录字段偏离统一契约")
        output.append(record)
    return tuple(output)


def _index_provider_records(
    records: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for record in records:
        point_ids = record.get("probe_point_ids")
        if not isinstance(point_ids, list):
            continue
        for point_id in cast(list[object], point_ids):
            if isinstance(point_id, str) and point_id:
                indexed[point_id] = record
    return indexed


def _direct_record(
    zone_id: str,
    zone: Mapping[str, object],
    point_records: Mapping[str, Mapping[str, object]],
    base_url: str,
) -> dict[str, object]:
    point_ids = _text_list(zone.get("probe_point_ids"), "probe_point_ids")
    source = point_records.get(point_ids[0])
    if source is None:
        return _empty_record(
            provider="qweather",
            spatial_basis="coordinate_1x1_km",
            spatial_id=point_ids[0],
            zone_id=zone_id,
            source_url=base_url.rstrip("/"),
        )

    location_key = _required_text(source, "location_key")
    values = _mapping_copy(source.get("values"))
    return {
        "provider": "qweather",
        "spatial_basis": "coordinate_1x1_km",
        "spatial_id": location_key,
        "zone_ids": [zone_id],
        "observed_at": source.get("business_time"),
        "fetched_at": source.get("fetched_at"),
        "values": values,
        "units": _mapping_copy(source.get("units")),
        "status": source.get("status", "partial"),
        "is_estimated": True,
        "components": [],
        "source_url": _qweather_source_url(base_url, location_key),
    }


def _station_record(
    zone_id: str,
    zone: Mapping[str, object],
    station_index: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    station_id = str(zone.get("station_id"))
    source = station_index.get(station_id)
    if source is None:
        return _empty_record(
            provider="shanghai_sthj",
            spatial_basis="station",
            spatial_id=station_id,
            zone_id=zone_id,
            source_url=_OFFICIAL_STATION_PAGE,
        )
    return {
        "provider": "shanghai_sthj",
        "spatial_basis": "station",
        "spatial_id": station_id,
        "zone_ids": [zone_id],
        "observed_at": source.get("observed_at"),
        "fetched_at": source.get("fetched_at"),
        "values": _mapping_copy(source.get("values")),
        "units": _mapping_copy(source.get("units")),
        "status": source.get("status", "partial"),
        "is_estimated": False,
        "components": [],
        "source_url": source.get("source_url", _OFFICIAL_STATION_PAGE),
    }


def _blend_record(
    zone_id: str,
    zone: Mapping[str, object],
    point_records: Mapping[str, Mapping[str, object]],
    provider_base_url: str,
) -> dict[str, object]:
    source_url = f"{provider_base_url.rstrip('/')}/airquality/v1/current"
    raw_components = zone.get("blend_components")
    if not isinstance(raw_components, list):
        raise TypeError(f"融合分区 {zone_id} 缺少 blend_components")
    components = cast(list[Mapping[str, object]], raw_components)
    selected = {
        point_id: point_records.get(point_id)
        for point_id in (_required_text(item, "point_id") for item in components)
    }
    trace = _component_trace(components, selected)
    available_records = [record for record in selected.values() if record is not None]
    if len(available_records) != len(components) or any(
        not _blend_component_is_complete(record) for record in available_records
    ):
        return _invalid_blend_record(
            zone_id,
            selected,
            trace,
            source_url,
            status="partial" if available_records else "no_data",
        )
    observed_times = {_normalized_time(record.get("business_time")) for record in available_records}
    if len(observed_times) != 1:
        return _invalid_blend_record(
            zone_id,
            selected,
            trace,
            source_url,
            status="partial",
        )

    blended = blend_pollutants(
        selected,
        components,
        aqi_calculator=lambda concentrations: calculate_aqi(concentrations)["aqi"],
    )
    values = _mapping_copy(blended.get("values"))
    if values:
        aqi_details = calculate_aqi(values)
        pm25_iaqi = cast(Mapping[str, object], aqi_details["iaqi"]).get("pm2_5_ug_m3")
        if pm25_iaqi is not None:
            values["pm2_5_iaqi"] = pm25_iaqi
    units = {
        key: (
            "mg/m3"
            if key == "carbon_monoxide_mg_m3"
            else "index"
            if key in {"aqi", "pm2_5_iaqi"}
            else "ug/m3"
        )
        for key in values
    }
    observed_at = next(
        (
            record.get("business_time")
            for record in selected.values()
            if record is not None and record.get("business_time") is not None
        ),
        None,
    )
    return {
        "provider": "district_blend",
        "spatial_basis": "district_blend",
        "spatial_id": f"blend:{zone_id}",
        "zone_ids": [zone_id],
        "observed_at": observed_at,
        "fetched_at": _latest_value(
            record.get("fetched_at") for record in selected.values() if record is not None
        ),
        "values": values,
        "units": units,
        "status": blended["status"],
        "is_estimated": True,
        "components": trace,
        "source_url": source_url,
    }


def _blend_component_is_complete(record: Mapping[str, object]) -> bool:
    if record.get("status") != "ok":
        return False
    observed_at = record.get("business_time")
    if not isinstance(observed_at, str) or not observed_at:
        return False
    if _parse_time(observed_at) is None:
        return False
    values = record.get("values")
    if not isinstance(values, Mapping):
        return False
    typed_values = cast(Mapping[str, object], values)
    for pollutant in _POLLUTANTS:
        value = typed_values.get(pollutant)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not math.isfinite(float(value)) or float(value) < 0:
            return False
    return True


def _invalid_blend_record(
    zone_id: str,
    selected: Mapping[str, Mapping[str, object] | None],
    trace: Sequence[Mapping[str, object]],
    source_url: str,
    *,
    status: str,
) -> dict[str, object]:
    return {
        "provider": "district_blend",
        "spatial_basis": "district_blend",
        "spatial_id": f"blend:{zone_id}",
        "zone_ids": [zone_id],
        "observed_at": None,
        "fetched_at": _latest_value(
            record.get("fetched_at") for record in selected.values() if record is not None
        ),
        "values": {},
        "units": {},
        "status": status,
        "is_estimated": True,
        "components": [dict(component) for component in trace],
        "source_url": source_url,
    }


def _component_trace(
    components: Sequence[Mapping[str, object]],
    selected: Mapping[str, Mapping[str, object] | None],
) -> list[dict[str, object]]:
    trace: list[dict[str, object]] = []
    for component in components:
        point_id = _required_text(component, "point_id")
        record = selected.get(point_id)
        trace.append(
            {
                "district": component.get("district"),
                "point_id": point_id,
                "weight": component.get("weight"),
                "provider": "qweather",
                "spatial_id": record.get("location_key") if record is not None else None,
                "observed_at": record.get("business_time") if record is not None else None,
                "values": _mapping_copy(record.get("values")) if record is not None else {},
                "units": _mapping_copy(record.get("units")) if record is not None else {},
                "status": record.get("status", "partial") if record is not None else "no_data",
            }
        )
    return trace


def _empty_record(
    *,
    provider: str,
    spatial_basis: str,
    spatial_id: str,
    zone_id: str,
    source_url: str,
) -> dict[str, object]:
    return {
        "provider": provider,
        "spatial_basis": spatial_basis,
        "spatial_id": spatial_id,
        "zone_ids": [zone_id],
        "observed_at": None,
        "fetched_at": None,
        "values": {},
        "units": {},
        "status": "no_data",
        "is_estimated": provider in {"qweather", "district_blend"},
        "components": [],
        "source_url": source_url,
    }


def _mapping_copy(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in cast(Mapping[object, object], value).items()}


def _qweather_source_url(base_url: str, source_id: str) -> str:
    latitude, longitude = coordinates_from_source_id(source_id)
    return f"{base_url.rstrip('/')}/airquality/v1/current/{latitude}/{longitude}"


def _text_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} 应为非空字符串数组")
    values = cast(list[object], value)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{field_name} 应为非空字符串数组")
    return cast(list[str], values)


def _required_text(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} 应为非空字符串")
    return value


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _normalized_time(value: object) -> datetime:
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError("融合组件观测时间无效")
    return parsed.astimezone(timezone.utc)


def _latest_value(values: Iterable[object]) -> object:
    valid = [item for item in values if item is not None]
    return max(valid, key=lambda item: str(item), default=None)


__all__ = ["build_zone_air_quality_records"]
