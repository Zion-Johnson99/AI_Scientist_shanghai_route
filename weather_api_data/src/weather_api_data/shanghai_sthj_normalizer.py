"""上海市生态环境局站点小时响应标准化。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import cast

from weather_api_data.shanghai_sthj_client import ShanghaiSthjFetchResult

_SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))
_VALUE_UNITS = {
    "aqi": "index",
    "pm2_5_ug_m3": "ug/m3",
    "pm2_5_iaqi": "index",
}


def normalize_station_observation(
    result: ShanghaiSthjFetchResult,
    *,
    zone_ids: Sequence[str],
) -> dict[str, object]:
    """将单站响应转为项目通用的站点观测字典。"""

    aqi_records = _records(result.payload, "100")
    pm25_records = _records(result.payload, "101")
    all_records = (*aqi_records, *pm25_records)
    station_id_mismatch = _has_station_id_mismatch(all_records, result.station_id)
    if station_id_mismatch:
        observed_at = None
        values: dict[str, int | float] = {}
    else:
        observed_time = _latest_observed_time(all_records)
        aqi_record = _record_at(aqi_records, observed_time)
        pm25_record = _record_at(pm25_records, observed_time)
        values = _values(aqi_record, pm25_record)
        observed_at = _iso_observed_time(observed_time)
    status = _status(result, all_records, observed_at, values, station_id_mismatch)
    units = {name: _VALUE_UNITS[name] for name in values}

    return {
        "provider": "shanghai_sthj",
        "data_role": "station_observation",
        "spatial_basis": "station",
        "spatial_id": result.station_id,
        "zone_ids": list(zone_ids),
        "observed_at": observed_at,
        "fetched_at": _iso_datetime(result.fetched_at),
        "values": values,
        "units": units,
        "status": status,
        "is_estimated": False,
        "components": [],
        "source_url": result.source_url,
        "raw_data": result.payload,
    }


def _records(payload: object, pollutant_id: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(payload, Mapping):
        return ()
    typed_payload = cast(Mapping[str, object], payload)
    raw_records = typed_payload.get(pollutant_id)
    if not isinstance(raw_records, list):
        return ()
    typed_records = cast(list[object], raw_records)
    return tuple(
        cast(Mapping[str, object], record)
        for record in typed_records
        if isinstance(record, Mapping)
    )


def _latest_observed_time(records: Sequence[Mapping[str, object]]) -> datetime | None:
    parsed = (_parse_observed_time(record.get("lstAqi")) for record in records)
    return max((value for value in parsed if value is not None), default=None)


def _has_station_id_mismatch(
    records: Sequence[Mapping[str, object]], expected_station_id: str
) -> bool:
    for record in records:
        station_id = record.get("siteId")
        if station_id is not None and str(station_id) != expected_station_id:
            return True
    return False


def _record_at(
    records: Sequence[Mapping[str, object]],
    observed_time: datetime | None,
) -> Mapping[str, object] | None:
    if observed_time is None:
        return records[0] if records else None
    for record in records:
        if _parse_observed_time(record.get("lstAqi")) == observed_time:
            return record
    return None


def _parse_observed_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SHANGHAI_TIMEZONE)
    return parsed.astimezone(_SHANGHAI_TIMEZONE)


def _iso_observed_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _iso_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.isoformat()


def _values(
    aqi_record: Mapping[str, object] | None,
    pm25_record: Mapping[str, object] | None,
) -> dict[str, int | float]:
    values: dict[str, int | float] = {}
    aqi = _integer(aqi_record.get("aqi")) if aqi_record is not None else None
    pm25 = _decimal(pm25_record.get("value")) if pm25_record is not None else None
    pm25_iaqi = _integer(pm25_record.get("aqi")) if pm25_record is not None else None
    if aqi is not None:
        values["aqi"] = aqi
    if pm25 is not None:
        values["pm2_5_ug_m3"] = float(pm25 * Decimal("1000"))
    if pm25_iaqi is not None:
        values["pm2_5_iaqi"] = pm25_iaqi
    return values


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _integer(value: object) -> int | None:
    parsed = _decimal(value)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _status(
    result: ShanghaiSthjFetchResult,
    records: Sequence[Mapping[str, object]],
    observed_at: str | None,
    values: Mapping[str, int | float],
    station_id_mismatch: bool,
) -> str:
    if result.status == "no_data" or not records:
        return "no_data"
    if station_id_mismatch:
        return "partial"
    required_values = {"aqi", "pm2_5_ug_m3", "pm2_5_iaqi"}
    if observed_at is None or not required_values.issubset(values):
        return "partial"
    return "ok"


__all__ = ["normalize_station_observation"]
