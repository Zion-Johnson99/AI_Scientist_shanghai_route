from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from weather_api_data.air_quality_integration import build_zone_air_quality_records


def _qweather_record(
    point_id: str,
    *,
    location_key: str,
    observed_at: str = "2026-08-25T09:00:00+08:00",
    pm25: float = 14.0,
) -> dict[str, object]:
    return {
        "location_key": location_key,
        "probe_point_ids": [point_id],
        "business_time": observed_at,
        "fetched_at": "2026-08-25T01:01:00+00:00",
        "status": "ok",
        "values": {
            "aqi": 35,
            "pm2_5_ug_m3": pm25,
            "pm10_ug_m3": 30.0,
            "ozone_ug_m3": 80.0,
            "nitrogen_dioxide_ug_m3": 20.0,
            "sulfur_dioxide_ug_m3": 5.0,
            "carbon_monoxide_mg_m3": 0.5,
        },
        "units": {
            "aqi": "index",
            "pm2_5_ug_m3": "ug/m3",
            "pm10_ug_m3": "ug/m3",
            "ozone_ug_m3": "ug/m3",
            "nitrogen_dioxide_ug_m3": "ug/m3",
            "sulfur_dioxide_ug_m3": "ug/m3",
            "carbon_monoxide_mg_m3": "mg/m3",
        },
    }


def _station_record(station_id: str, zone_id: str) -> dict[str, object]:
    return {
        "provider": "shanghai_sthj",
        "data_role": "station_observation",
        "spatial_basis": "station",
        "spatial_id": station_id,
        "zone_ids": [zone_id],
        "observed_at": "2026-08-25T09:00:00+08:00",
        "fetched_at": "2026-08-25T01:01:00+00:00",
        "values": {"aqi": 15, "pm2_5_ug_m3": 7.0, "pm2_5_iaqi": 10},
        "units": {"aqi": "index", "pm2_5_ug_m3": "ug/m3", "pm2_5_iaqi": "index"},
        "status": "ok",
        "is_estimated": False,
        "components": [],
        "source_url": "https://link.sthj.sh.gov.cn/hourly",
        "raw_data": {},
    }


def test_builds_same_twelve_fields_for_direct_station_and_blend() -> None:
    zones = (
        {
            "zone_id": "direct",
            "name": "直接区",
            "source_strategy": "qweather_direct",
            "probe_point_ids": ["P1"],
        },
        {
            "zone_id": "station",
            "name": "站点区",
            "source_strategy": "shanghai_station",
            "station_id": 80,
        },
        {
            "zone_id": "blend",
            "name": "融合区",
            "source_strategy": "district_blend",
            "blend_components": [
                {"district": "徐汇区", "point_id": "P1", "weight": 0.5},
                {"district": "闵行区", "point_id": "P2", "weight": 0.5},
            ],
        },
    )
    records = build_zone_air_quality_records(
        zones,
        (
            _qweather_record("P1", location_key="qweather:31.16,121.46"),
            _qweather_record("P2", location_key="qweather:31.18,121.39", pm25=20.0),
        ),
        (_station_record("80", "station"),),
        provider_base_url="https://example.qweatherapi.com",
    )

    expected_fields = {
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
    assert len(records) == 3
    assert all(set(record) == expected_fields for record in records)
    assert records[0]["provider"] == "qweather"
    assert records[0]["spatial_basis"] == "coordinate_1x1_km"
    assert records[0]["spatial_id"] == "qweather:31.16,121.46"
    assert records[0]["is_estimated"] is True
    assert records[0]["source_url"] == (
        "https://example.qweatherapi.com/airquality/v1/current/31.16/121.46"
    )
    assert records[1]["provider"] == "shanghai_sthj"
    assert records[1]["spatial_id"] == "80"
    assert records[2]["provider"] == "district_blend"
    assert records[2]["is_estimated"] is True
    blend_components = cast(Sequence[Mapping[str, object]], records[2]["components"])
    assert {component["provider"] for component in blend_components} == {"qweather"}
    blended_values = cast(Mapping[str, object], records[2]["values"])
    assert blended_values["pm2_5_ug_m3"] == 17.0
    assert blended_values["aqi"] == 30
    assert blended_values["aqi"] != 35


def test_direct_zone_with_multiple_probe_points_uses_configured_first_point() -> None:
    zone = {
        "zone_id": "direct",
        "name": "直接区",
        "source_strategy": "qweather_direct",
        "probe_point_ids": ["P1", "P2"],
    }

    record = build_zone_air_quality_records(
        (zone,),
        (
            _qweather_record("P1", location_key="qweather:31.16,121.46", pm25=11.0),
            _qweather_record("P2", location_key="qweather:31.17,121.45", pm25=99.0),
        ),
        (),
        provider_base_url="https://example.qweatherapi.com",
    )[0]

    assert record["spatial_id"] == "qweather:31.16,121.46"
    assert cast(Mapping[str, object], record["values"])["pm2_5_ug_m3"] == 11.0


def test_blend_rejects_different_observation_times_without_fabricating_value() -> None:
    zones = (
        {
            "zone_id": "blend",
            "name": "融合区",
            "source_strategy": "district_blend",
            "blend_components": [
                {"district": "徐汇区", "point_id": "P1", "weight": 0.5},
                {"district": "闵行区", "point_id": "P2", "weight": 0.5},
            ],
        },
    )
    records = build_zone_air_quality_records(
        zones,
        (
            _qweather_record("P1", location_key="qweather:31.16,121.46"),
            _qweather_record(
                "P2",
                location_key="qweather:31.18,121.39",
                observed_at="2026-08-25T10:00:00+08:00",
            ),
        ),
        (),
        provider_base_url="https://example.qweatherapi.com",
    )

    assert records[0]["status"] == "partial"
    assert records[0]["values"] == {}
    assert records[0]["observed_at"] is None
    components = cast(Sequence[Mapping[str, object]], records[0]["components"])
    assert {component["observed_at"] for component in components} == {
        "2026-08-25T09:00:00+08:00",
        "2026-08-25T10:00:00+08:00",
    }


def test_blend_rejects_missing_time_or_pollutant_without_fabricating_value() -> None:
    zone = {
        "zone_id": "blend",
        "name": "融合区",
        "source_strategy": "district_blend",
        "blend_components": [
            {"district": "徐汇区", "point_id": "P1", "weight": 0.5},
            {"district": "闵行区", "point_id": "P2", "weight": 0.5},
        ],
    }
    missing_time = _qweather_record("P2", location_key="qweather:31.18,121.39")
    missing_time["business_time"] = None
    missing_pollutant = _qweather_record("P2", location_key="qweather:31.18,121.39")
    cast(dict[str, object], missing_pollutant["values"]).pop("pm2_5_ug_m3")

    for invalid_record in (missing_time, missing_pollutant):
        result = build_zone_air_quality_records(
            (zone,),
            (
                _qweather_record("P1", location_key="qweather:31.16,121.46"),
                invalid_record,
            ),
            (),
            provider_base_url="https://example.qweatherapi.com",
        )[0]

        assert result["status"] == "partial"
        assert result["values"] == {}
        assert result["observed_at"] is None


def test_blend_rejects_equal_but_invalid_time_strings() -> None:
    zone = {
        "zone_id": "blend",
        "name": "融合区",
        "source_strategy": "district_blend",
        "blend_components": [
            {"district": "徐汇区", "point_id": "P1", "weight": 0.5},
            {"district": "闵行区", "point_id": "P2", "weight": 0.5},
        ],
    }
    first = _qweather_record("P1", location_key="qweather:31.16,121.46")
    second = _qweather_record("P2", location_key="qweather:31.18,121.39")
    first["business_time"] = "bad-time"
    second["business_time"] = "bad-time"

    result = build_zone_air_quality_records(
        (zone,),
        (first, second),
        (),
        provider_base_url="https://example.qweatherapi.com",
    )[0]

    assert result["status"] == "partial"
    assert result["values"] == {}


def test_missing_station_yields_auditable_no_data_record() -> None:
    zones = (
        {
            "zone_id": "station",
            "name": "站点区",
            "source_strategy": "shanghai_station",
            "station_id": 207,
        },
    )

    records = build_zone_air_quality_records(
        zones,
        (),
        (),
        provider_base_url="https://example.qweatherapi.com",
    )

    assert records[0]["status"] == "no_data"
    assert records[0]["spatial_id"] == "207"
    assert records[0]["values"] == {}
