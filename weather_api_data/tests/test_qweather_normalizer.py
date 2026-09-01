from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import cast

import pytest

from weather_api_data.http_client import HttpResult
from weather_api_data.models import NormalizedRecord
from weather_api_data.qweather_normalizer import QWeatherNormalizer

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "qweather_responses.json"
FETCHED_AT = datetime(2026, 8, 26, 11, 35, tzinfo=timezone.utc)
SOURCE_ID = "qweather:31.16,121.46"
POINT_IDS = ("XH_ENT_0001", "XH_ENT_0002")


@pytest.fixture(scope="module")
def responses() -> Mapping[str, object]:
    payload: object = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _normalize(
    endpoint: str,
    payload: object,
) -> list[NormalizedRecord]:
    result = HttpResult(
        payload=payload,
        status_code=200,
        expires=None,
        fetched_at=FETCHED_AT,
    )
    return QWeatherNormalizer().normalize(endpoint, result, SOURCE_ID, POINT_IDS)


def test_current_weather_maps_units_and_uses_fetched_at_as_business_time(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("current_conditions", responses["current_conditions"])

    assert len(records) == 1
    record = records[0]
    assert record.dataset_type == "weather_observation"
    assert record.location_key == SOURCE_ID
    assert record.probe_point_ids == POINT_IDS
    assert record.business_time == FETCHED_AT.isoformat()
    assert record.status == "ok"
    assert record.values == {
        "temperature_c": 31.2,
        "relative_humidity_pct": 65.0,
        "weather_text": "多云",
        "weather_icon": "101",
        "real_feel_temperature_c": 35.1,
        "wind_direction_deg": 120.0,
        "wind_speed_kmh": 12.4,
        "wind_gust_kmh": 18.0,
        "pressure_mb": 1004.2,
        "visibility_km": 16.1,
        "uv_index": 3.0,
        "precipitation_mm": 1.3,
    }
    assert record.units["temperature_c"] == "C"
    assert record.units["wind_speed_kmh"] == "km/h"
    assert record.units["pressure_mb"] == "mb"
    source = dict(record.source)
    assert list(cast(tuple[object, ...], source["attributions"])) == ["QWeather"]
    assert "fetched_at" in str(source["time_basis"])


def test_hourly_weather_maps_forecast_time_probability_and_target_morning(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("hourly_weather_24", responses["hourly_weather_24"])

    assert [record.business_time for record in records] == [
        "2026-08-26T20:00:00+08:00",
        "2026-08-27T09:00:00+08:00",
    ]
    assert all(record.dataset_type == "weather_forecast" for record in records)
    assert records[0].values["relative_humidity_pct"] == 68.0
    assert records[0].values["precipitation_probability_pct"] == 45.0
    assert records[0].values["precipitation_mm"] == 2.4
    assert records[1].values["weather_text"] == "小雨"


def test_current_air_prefers_cn_mee_1h_and_converts_co_to_mg_m3(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("current_air_quality", responses["current_air_quality"])

    assert len(records) == 1
    record = records[0]
    assert record.dataset_type == "air_quality_observation"
    assert record.business_time == "2026-08-26T19:00:00+08:00"
    assert record.status == "ok"
    assert record.values == {
        "aqi": 42,
        "pm2_5_ug_m3": 18.2,
        "pm10_ug_m3": 31.0,
        "ozone_ug_m3": 72.0,
        "nitrogen_dioxide_ug_m3": 20.0,
        "sulfur_dioxide_ug_m3": 5.0,
        "carbon_monoxide_mg_m3": 0.62,
    }
    assert record.units["carbon_monoxide_mg_m3"] == "mg/m3"
    source = dict(record.source)
    assert source["aqi_standard"] == "cn-mee-1h"
    assert "shanghai" in str(source["time_basis"]).lower()


def test_current_air_falls_back_to_cn_mee_when_hourly_standard_is_absent(
    responses: Mapping[str, object],
) -> None:
    copied: object = deepcopy(responses["current_air_quality"])
    assert isinstance(copied, dict)
    payload = cast(dict[str, object], copied)
    raw_indexes = payload["indexes"]
    assert isinstance(raw_indexes, list)
    indexes = cast(list[object], raw_indexes)
    payload["indexes"] = [
        item
        for item in indexes
        if isinstance(item, Mapping) and cast(Mapping[str, object], item).get("code") == "cn-mee"
    ]

    record = _normalize("current_air_quality", payload)[0]

    assert record.values["aqi"] == 55
    assert dict(record.source)["aqi_standard"] == "cn-mee"


def test_hourly_air_uses_cn_mee_and_preserves_existing_mg_m3(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("hourly_air_quality_24", responses["hourly_air_quality_24"])

    assert [record.business_time for record in records] == [
        "2026-08-26T20:00:00+08:00",
        "2026-08-27T09:00:00+08:00",
    ]
    assert all(record.dataset_type == "air_quality_forecast" for record in records)
    assert records[0].values["aqi"] == 48
    assert records[0].values["pm2_5_ug_m3"] == 21.0
    assert records[0].values["carbon_monoxide_mg_m3"] == 0.58
    assert dict(records[0].source)["aqi_standard"] == "cn-mee"


def test_indices_emit_three_unique_dates_and_keep_refer_sources(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("indices_3day", responses["indices_3day"])

    assert len(records) == 3
    assert {str(record.business_time)[:10] for record in records} == {
        "2026-08-26",
        "2026-08-27",
        "2026-08-28",
    }
    assert all(record.dataset_type == "life_index" for record in records)
    assert records[0].values["index_id"] == "1"
    assert records[0].values["name"] == "运动指数"
    assert records[0].values["value"] == "2"
    assert records[0].values["category"] == "较适宜"
    assert records[0].valid_until == (FETCHED_AT + timedelta(hours=1)).isoformat()
    attributions = dict(records[0].source)["attributions"]
    assert list(cast(tuple[object, ...], attributions)) == ["QWeather"]


def test_indices_expiry_is_capped_at_one_hour_when_response_expires_later(
    responses: Mapping[str, object],
) -> None:
    result = HttpResult(
        payload=responses["indices_3day"],
        status_code=200,
        expires=format_datetime(FETCHED_AT + timedelta(hours=6), usegmt=True),
        fetched_at=FETCHED_AT,
    )

    records = QWeatherNormalizer().normalize("indices_3day", result, SOURCE_ID, POINT_IDS)

    assert records[0].valid_until == (FETCHED_AT + timedelta(hours=1)).isoformat()


def test_zero_result_alert_is_normal_empty_result(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("alerts", responses["alerts_empty"])

    assert records == []


def test_active_alert_maps_event_identity_times_and_attribution(
    responses: Mapping[str, object],
) -> None:
    records = _normalize("alerts", responses["alerts_active"])

    assert len(records) == 1
    record = records[0]
    assert record.dataset_type == "weather_alert"
    assert record.business_time == "2026-08-26T18:30:00+08:00"
    assert record.values["alert_id"] == "SH-RAIN-20260826-001"
    assert record.values["type"] == "暴雨"
    assert record.values["level"] == "Moderate"
    assert record.values["source"] == "上海市气象台"
    assert record.values["end_time"] == "2026-08-27T01:00:00+08:00"
    assert record.values["instruction"] == "注意道路积水和户外运动安全"
    assert record.raw_data["instruction"] == "注意道路积水和户外运动安全"
    attributions = dict(record.source)["attributions"]
    assert list(cast(tuple[object, ...], attributions)) == ["QWeather"]


def test_missing_pm25_marks_air_record_partial_without_fabricating_value(
    responses: Mapping[str, object],
) -> None:
    records = _normalize(
        "current_air_quality",
        responses["air_current_missing_pollutant"],
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "partial"
    assert "pm2_5_ug_m3" in record.missing_fields
    assert "pm2_5_ug_m3" not in record.values
    assert record.values["aqi"] == 42
