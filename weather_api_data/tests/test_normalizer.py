from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from weather_api_data.http_client import HttpResult
from weather_api_data.models import SamplingPoint
from weather_api_data.normalizer import Normalizer, ResponseShapeError

FETCHED_AT = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
LOCATION_KEY = "101021200"


def result(payload: object, *, expires: str | None = None) -> HttpResult:
    return HttpResult(
        payload=payload,
        status_code=200,
        expires=expires,
        fetched_at=FETCHED_AT,
    )


def weather_payload(*, local_source_id: int = 7) -> dict[str, object]:
    return {
        "LocalObservationDateTime": "2026-08-24T15:00:00+08:00",
        "DateTime": "2026-08-24T16:00:00+08:00",
        "Temperature": {"Metric": {"Value": 31.2, "Unit": "C"}},
        "RelativeHumidity": 63,
        "WeatherText": "多云",
        "IconPhrase": "间歇性多云",
        "WeatherIcon": 4,
        "RealFeelTemperature": {"Metric": {"Value": 35.1}},
        "Wind": {
            "Direction": {"Degrees": 135},
            "Speed": {"Metric": {"Value": 12.4}},
        },
        "WindGust": {"Speed": {"Metric": {"Value": 21.6}}},
        "Pressure": {"Metric": {"Value": 1004.2}},
        "Visibility": {"Metric": {"Value": 16.1}},
        "UVIndex": 7,
        "PrecipitationSummary": {
            "Precipitation": {"Metric": {"Value": 1.3}},
        },
        "PrecipitationProbability": 45,
        "LocalSource": {"Id": local_source_id, "Name": "华风爱科"},
    }


def hourly_weather_payload() -> dict[str, object]:
    return {
        "DateTime": "2026-08-24T18:00:00+08:00",
        "Temperature": {"Value": 30.0, "Unit": "C", "UnitType": 17},
        "RelativeHumidity": 70,
        "IconPhrase": "晴",
        "WeatherIcon": 1,
        "RealFeelTemperature": {"Value": 34.0, "Unit": "C", "UnitType": 17},
        "Wind": {
            "Direction": {"Degrees": 135, "Localized": "东南"},
            "Speed": {"Value": 8.3, "Unit": "km/h", "UnitType": 7},
        },
        "WindGust": {"Speed": {"Value": 16.7, "Unit": "km/h", "UnitType": 7}},
        "Pressure": {"Value": 1005.0, "Unit": "mb", "UnitType": 14},
        "Visibility": {"Value": 16.1, "Unit": "km", "UnitType": 6},
        "UVIndex": 1,
        "TotalLiquid": {"Value": 0.0, "Unit": "mm", "UnitType": 3},
        "PrecipitationProbability": 0,
    }


def air_payload() -> dict[str, object]:
    return {
        "Date": "2026-08-24T15:00:00+08:00",
        "DateTime": "2026-08-24T16:00:00+08:00",
        "Index": 52,
        "ParticulateMatter2_5": 18.2,
        "ParticulateMatter10": 35.4,
        "Ozone": 91.0,
        "NitrogenDioxide": 24.0,
        "SulfurDioxide": 8.0,
        "CarbonMonoxide": 0.7,
        "Source": {"Id": "CN-001", "Name": "Xuhui"},
    }


def air_forecast_payload() -> dict[str, object]:
    return {
        "AirQuality": "33",
        "ParticulateMatter2_5": "21",
        "ParticulateMatter10": "28",
        "CarbonMonoxide": "0.55",
        "Ozone": "43",
        "SulfurDioxide": "8",
        "NitrogenDioxide": "45",
        "StartDateTime": "2026-08-26T11:00:00+08:00",
    }


def test_hourly_air_quality_unwraps_live_forecasts_object() -> None:
    payload = {
        "LocationKey": LOCATION_KEY,
        "Forecasts": [air_forecast_payload()],
        "ForecastsFrom0": [],
    }

    records = Normalizer().normalize(
        "hourly_air_quality_24",
        result(payload),
        LOCATION_KEY,
    )

    assert len(records) == 1
    assert records[0].dataset_type == "air_quality_forecast"
    assert records[0].business_time == "2026-08-26T11:00:00+08:00"
    assert records[0].values["aqi"] == 33
    assert records[0].values["pm2_5_ug_m3"] == 21


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"LocationKey": LOCATION_KEY},
        {"LocationKey": LOCATION_KEY, "Forecasts": {}},
        {"LocationKey": LOCATION_KEY, "Forecasts": ["invalid"]},
    ],
)
def test_hourly_air_quality_rejects_invalid_forecasts_object(payload: object) -> None:
    with pytest.raises(ResponseShapeError):
        Normalizer().normalize(
            "hourly_air_quality_24",
            result(payload),
            LOCATION_KEY,
        )


def index_payload() -> dict[str, object]:
    return {
        "ID": 3,
        "Name": "户外运动指数",
        "Value": 2,
        "Category": "良好",
        "CategoryValue": 1,
        "Text": "适宜运动",
        "LocalDateTime": "2026-08-24T07:00:00+08:00",
    }


def alert_payload() -> dict[str, object]:
    return {
        "AlertID": 998,
        "Type": "高温",
        "Level": "黄色",
        "Source": "上海市气象局",
        "Area": [
            {
                "StartTime": "2026-08-24T10:00:00+08:00",
                "EndTime": "2026-08-24T18:00:00+08:00",
                "Summary": "高温预警",
                "Text": "避免长时间户外运动",
            }
        ],
    }


def climo_payload() -> dict[str, object]:
    return {
        "Date": "2025-08-24",
        "EpochDate": 1755993600,
        "Actuals": {"HighTemperature": {"Metric": {"Value": 34.0}}},
    }


@pytest.mark.parametrize(
    ("endpoint", "payload", "dataset_type", "dataset_role", "granularity", "business_time"),
    [
        (
            "current_conditions",
            [weather_payload()],
            "weather_observation",
            "operational",
            "current",
            "2026-08-24T15:00:00+08:00",
        ),
        (
            "historical_24",
            [weather_payload()],
            "weather_observation",
            "operational",
            "hourly",
            "2026-08-24T15:00:00+08:00",
        ),
        (
            "hourly_weather_24",
            [hourly_weather_payload()],
            "weather_forecast",
            "operational",
            "hourly",
            "2026-08-24T18:00:00+08:00",
        ),
        (
            "current_air_quality",
            air_payload(),
            "air_quality_observation",
            "operational",
            "current",
            "2026-08-24T15:00:00+08:00",
        ),
        (
            "hourly_air_quality_24",
            {"LocationKey": LOCATION_KEY, "Forecasts": [air_forecast_payload()]},
            "air_quality_forecast",
            "operational",
            "hourly",
            "2026-08-26T11:00:00+08:00",
        ),
        (
            "indices_1day",
            [index_payload()],
            "life_index",
            "operational",
            "daily",
            "2026-08-24T07:00:00+08:00",
        ),
        (
            "indices_5day",
            [index_payload()],
            "life_index",
            "operational",
            "daily",
            "2026-08-24T07:00:00+08:00",
        ),
        (
            "alerts",
            [alert_payload()],
            "weather_alert",
            "operational",
            "event",
            "2026-08-24T10:00:00+08:00",
        ),
        (
            "climo_actuals",
            [climo_payload()],
            "climate_actual",
            "backfill_2025",
            "daily",
            "2025-08-24",
        ),
    ],
)
def test_normalizes_every_v1_endpoint(
    endpoint: str,
    payload: object,
    dataset_type: str,
    dataset_role: str,
    granularity: str,
    business_time: str,
) -> None:
    records = Normalizer().normalize(
        endpoint,
        result(payload),
        LOCATION_KEY,
        probe_point_ids=("xuhui-west", "xuhui-east"),
    )

    assert len(records) == 1
    record = records[0]
    assert (record.dataset_type, record.dataset_role, record.granularity) == (
        dataset_type,
        dataset_role,
        granularity,
    )
    assert record.location_key == LOCATION_KEY
    assert record.probe_point_ids == ("xuhui-west", "xuhui-east")
    assert record.business_time == business_time
    assert record.fetched_at == "2026-08-24T08:00:00+00:00"
    assert record.status == "ok"
    assert record.completeness == 1.0
    assert record.missing_fields == ()


def test_weather_maps_core_fields_units_source_and_raw_data() -> None:
    raw = weather_payload()

    record = Normalizer().normalize("current_conditions", result([raw]), LOCATION_KEY)[0]

    assert dict(record.values) == {
        "temperature_c": 31.2,
        "relative_humidity_pct": 63,
        "weather_text": "多云",
        "weather_icon": 4,
        "real_feel_temperature_c": 35.1,
        "wind_direction_deg": 135,
        "wind_speed_kmh": 12.4,
        "wind_gust_kmh": 21.6,
        "pressure_mb": 1004.2,
        "visibility_km": 16.1,
        "uv_index": 7,
        "precipitation_mm": 1.3,
        "precipitation_probability_pct": 45,
    }
    assert dict(record.units) == {
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
    assert dict(record.source) == {
        "local_source_id": 7,
        "local_source_name": "华风爱科",
        "source_status": "expected_local_source",
    }
    assert dict(record.raw_data) == raw


def test_hourly_weather_accepts_total_liquid_as_precipitation() -> None:
    raw = hourly_weather_payload()
    raw["TotalLiquid"] = {"Value": 2.4}

    record = Normalizer().normalize("hourly_weather_24", result([raw]), LOCATION_KEY)[0]

    assert record.values["precipitation_mm"] == 2.4
    assert record.status == "ok"


def test_hourly_weather_maps_flat_fields_from_live_contract() -> None:
    record = Normalizer().normalize(
        "hourly_weather_24",
        result([hourly_weather_payload()]),
        LOCATION_KEY,
    )[0]

    assert record.values["temperature_c"] == 30.0
    assert record.values["real_feel_temperature_c"] == 34.0
    assert record.values["wind_speed_kmh"] == 8.3
    assert record.values["wind_gust_kmh"] == 16.7
    assert record.values["pressure_mb"] == 1005.0
    assert record.values["visibility_km"] == 16.1
    assert record.status == "ok"


def test_hourly_weather_treats_provider_omitted_pressure_as_optional() -> None:
    raw = hourly_weather_payload()
    raw.pop("Pressure")

    record = Normalizer().normalize(
        "hourly_weather_24",
        result([raw]),
        LOCATION_KEY,
    )[0]

    assert "pressure_mb" not in record.values
    assert "pressure_mb" not in record.missing_fields
    assert record.status == "ok"


def test_air_quality_maps_core_fields_and_preserves_co_interface_unit() -> None:
    record = Normalizer().normalize("current_air_quality", result(air_payload()), LOCATION_KEY)[0]

    assert dict(record.values) == {
        "aqi": 52,
        "pm2_5_ug_m3": 18.2,
        "pm10_ug_m3": 35.4,
        "ozone_ug_m3": 91.0,
        "nitrogen_dioxide_ug_m3": 24.0,
        "sulfur_dioxide_ug_m3": 8.0,
        "carbon_monoxide_mg_m3": 0.7,
    }
    assert dict(record.units) == {
        "aqi": "index",
        "pm2_5_ug_m3": "ug/m3",
        "pm10_ug_m3": "ug/m3",
        "ozone_ug_m3": "ug/m3",
        "nitrogen_dioxide_ug_m3": "ug/m3",
        "sulfur_dioxide_ug_m3": "ug/m3",
        "carbon_monoxide_mg_m3": "mg/m3",
    }
    assert record.source["air_quality_source"] == {"Id": "CN-001", "Name": "Xuhui"}


def test_current_air_quality_uses_official_date_as_complete_business_time() -> None:
    raw = air_payload()
    raw.pop("DateTime")

    record = Normalizer().normalize("current_air_quality", result(raw), LOCATION_KEY)[0]

    assert record.business_time == "2026-08-24T15:00:00+08:00"
    assert record.status == "ok"
    assert "business_time" not in record.missing_fields


def test_indices_alerts_and_climo_keep_endpoint_specific_values() -> None:
    normalizer = Normalizer()

    index_record = normalizer.normalize("indices_1day", result([index_payload()]), LOCATION_KEY)[0]
    assert dict(index_record.values) == {
        "index_id": 3,
        "name": "户外运动指数",
        "value": 2,
        "category": "良好",
        "category_value": 1,
        "text": "适宜运动",
        "local_date_time": "2026-08-24T07:00:00+08:00",
    }

    alert_record = normalizer.normalize("alerts", result([alert_payload()]), LOCATION_KEY)[0]
    assert dict(alert_record.values) == {
        "alert_id": 998,
        "type": "高温",
        "level": "黄色",
        "source": "上海市气象局",
        "start_time": "2026-08-24T10:00:00+08:00",
        "end_time": "2026-08-24T18:00:00+08:00",
        "summary": "高温预警",
        "text": "避免长时间户外运动",
    }

    climo_record = normalizer.normalize("climo_actuals", result([climo_payload()]), LOCATION_KEY)[0]
    assert climo_record.values["date"] == "2025-08-24"
    assert climo_record.values["epoch_date"] == 1755993600
    assert climo_record.values["actuals"] == climo_payload()["Actuals"]


def test_missing_required_core_field_marks_partial_and_calculates_completeness() -> None:
    raw = air_payload()
    raw.pop("ParticulateMatter2_5")

    record = Normalizer().normalize("current_air_quality", result(raw), LOCATION_KEY)[0]

    assert record.status == "partial"
    assert record.missing_fields == ("pm2_5_ug_m3",)
    assert record.completeness == pytest.approx(7 / 8)
    assert "pm2_5_ug_m3" not in record.values


@pytest.mark.parametrize(
    ("endpoint", "empty_payload"),
    [
        ("current_conditions", []),
        ("historical_24", []),
        ("hourly_weather_24", []),
        ("current_air_quality", {}),
        ("hourly_air_quality_24", {"LocationKey": LOCATION_KEY, "Forecasts": []}),
        ("indices_1day", []),
        ("indices_5day", []),
        ("alerts", []),
        ("climo_actuals", []),
    ],
)
def test_empty_collection_returns_one_no_data_record(endpoint: str, empty_payload: object) -> None:
    record = Normalizer().normalize(endpoint, result(empty_payload), LOCATION_KEY)[0]

    assert record.status == "no_data"
    assert record.business_time is None
    assert record.completeness == 0.0
    assert record.values == {}
    assert record.raw_data == {}


@pytest.mark.parametrize(
    ("endpoint", "invalid_payload"),
    [
        ("current_conditions", {}),
        ("historical_24", {}),
        ("hourly_weather_24", {}),
        ("current_air_quality", []),
        ("hourly_air_quality_24", {}),
        ("indices_1day", {}),
        ("indices_5day", {}),
        ("alerts", {}),
        ("climo_actuals", {}),
        ("current_conditions", ["not-an-object"]),
    ],
)
def test_rejects_invalid_v1_response_shapes(endpoint: str, invalid_payload: object) -> None:
    with pytest.raises(ResponseShapeError):
        Normalizer().normalize(endpoint, result(invalid_payload), LOCATION_KEY)


def test_expired_response_is_stale_and_expires_is_utc_iso() -> None:
    record = Normalizer().normalize(
        "current_conditions",
        result([weather_payload()], expires="Sun, 24 Aug 2026 07:59:59 GMT"),
        LOCATION_KEY,
    )[0]

    assert record.status == "stale"
    assert record.valid_until == "2026-08-24T07:59:59+00:00"


@pytest.mark.parametrize(
    ("local_source_id", "source_status"),
    [(7, "expected_local_source"), (99, "unexpected_local_source")],
)
def test_keeps_weather_data_while_classifying_local_source(
    local_source_id: int, source_status: str
) -> None:
    record = Normalizer().normalize(
        "current_conditions",
        result([weather_payload(local_source_id=local_source_id)]),
        LOCATION_KEY,
    )[0]

    assert record.status == "ok"
    assert record.source["local_source_id"] == local_source_id
    assert record.source["source_status"] == source_status
    assert record.values["temperature_c"] == 31.2


def test_models_are_immutable_and_to_dict_is_json_serializable() -> None:
    point = SamplingPoint("xuhui", "徐汇滨江", 121.47, 31.18)
    record = Normalizer().normalize(
        "current_conditions", result([weather_payload()]), LOCATION_KEY
    )[0]

    with pytest.raises(FrozenInstanceError):
        point.name = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.status = "error"  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.values["temperature_c"] = 0  # type: ignore[index]

    serialized = record.to_dict()
    assert serialized["probe_point_ids"] == []
    assert serialized["missing_fields"] == []
    assert (
        json.loads(json.dumps(serialized, ensure_ascii=False))["raw_data"]["WeatherText"] == "多云"
    )


def test_unknown_endpoint_is_an_explicit_shape_error() -> None:
    with pytest.raises(ResponseShapeError, match="unknown_endpoint"):
        Normalizer().normalize("unknown_endpoint", result([]), LOCATION_KEY)
