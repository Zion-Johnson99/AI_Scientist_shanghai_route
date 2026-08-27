from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import cast

import pytest

from weather_api_data.zone_air_quality import (
    AirQualityZoneError,
    blend_pollutants,
    load_air_quality_probe_points,
    load_air_quality_zones,
    resolve_air_quality_zone,
)

ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "config" / "xuhui_air_quality_zones.json"
SAMPLING_PATH = ROOT / "config" / "xuhui_sampling_points.json"
POLLUTANTS = {
    "pm2_5_ug_m3",
    "pm10_ug_m3",
    "ozone_ug_m3",
    "nitrogen_dioxide_ug_m3",
    "sulfur_dioxide_ug_m3",
    "carbon_monoxide_mg_m3",
}


def _valid_point_ids() -> set[str]:
    rows = json.loads(SAMPLING_PATH.read_text(encoding="utf-8"))
    return {row["point_id"] for row in rows}


def _components() -> list[dict[str, object]]:
    return [
        {"district": "徐汇区", "point_id": "XH_ENT_0013", "weight": 0.5},
        {"district": "闵行区", "point_id": "XH_ENT_0014", "weight": 0.5},
    ]


def _record(seed: float, *, aqi: int) -> dict[str, object]:
    return {
        "values": {
            "aqi": aqi,
            "pm2_5_ug_m3": seed,
            "pm10_ug_m3": seed + 10,
            "ozone_ug_m3": seed + 20,
            "nitrogen_dioxide_ug_m3": seed + 30,
            "sulfur_dioxide_ug_m3": seed + 40,
            "carbon_monoxide_mg_m3": seed / 10,
        },
        "source": {"name": "fixture"},
    }


def test_config_declares_required_external_probe_points() -> None:
    raw_payload: object = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert isinstance(raw_payload, dict)
    payload = cast(dict[str, object], raw_payload)
    assert set(payload) == {"probe_points", "zones"}
    assert payload["probe_points"] == [
        {
            "point_id": "AQ_PROBE_MINHANG_WEST",
            "name": "闵行漕河泾西侧空气质量探针",
            "longitude": 121.386,
            "latitude": 31.177,
            "district": "闵行区",
        },
        {
            "point_id": "AQ_PROBE_MINHANG_SOUTH",
            "name": "闵行华泾南侧空气质量探针",
            "longitude": 121.433,
            "latitude": 31.096,
            "district": "闵行区",
        },
    ]


def test_external_probe_points_load_as_sampling_points() -> None:
    points = load_air_quality_probe_points(CONFIG_PATH)

    assert [(point.point_id, point.longitude, point.latitude) for point in points] == [
        ("AQ_PROBE_MINHANG_WEST", 121.386, 31.177),
        ("AQ_PROBE_MINHANG_SOUTH", 121.433, 31.096),
    ]


def test_zone_config_has_exact_names_and_strategy_counts() -> None:
    zones = load_air_quality_zones(CONFIG_PATH)

    assert [zone["name"] for zone in zones] == [
        "衡复西北边界（徐汇+长宁）",
        "衡复中东",
        "徐家汇—体育公园",
        "田林—桂林—康健",
        "漕河泾西缘（徐汇+闵行）",
        "漕河泾东—蒲汇塘",
        "植物园北—上海南站",
        "植物园南—华泾北",
        "华泾南缘（徐汇+闵行）",
        "龙华—西岸北",
        "西岸南—龙耀滨江",
    ]
    assert Counter(zone["source_strategy"] for zone in zones) == {
        "qweather_direct": 6,
        "district_blend": 3,
        "shanghai_station": 2,
    }


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected_zone_id"),
    [
        (121.4235, 31.2115, "hengfu_northwest_blend"),
        (121.4430, 31.2070, "hengfu_central_east"),
        (121.4380, 31.1900, "xujiahui_sports_station"),
        (121.4210, 31.1690, "tianlin_guilin_kangjian_station"),
        (121.3975, 31.1780, "caohejing_west_blend"),
        (121.4070, 31.1750, "caohejing_east_puhuitang"),
        (121.4270, 31.1580, "botanical_north_south_station"),
        (121.4350, 31.1500, "botanical_south_huajing_north"),
        (121.4140, 31.1400, "huajing_south_blend"),
        (121.4520, 31.1790, "longhua_westbund_north"),
        (121.4570, 31.1630, "westbund_south_longyao"),
    ],
)
def test_representative_coordinates_resolve_to_nearest_zone(
    longitude: float, latitude: float, expected_zone_id: str
) -> None:
    zones = load_air_quality_zones(CONFIG_PATH)

    resolved = resolve_air_quality_zone(longitude, latitude, zones)

    assert resolved["zone_id"] == expected_zone_id


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(181.0, 31.2), (-181.0, 31.2), (121.4, 91.0), (121.4, -91.0)],
)
def test_zone_resolution_rejects_coordinates_outside_wgs84(
    longitude: float, latitude: float
) -> None:
    with pytest.raises(AirQualityZoneError, match="WGS84"):
        resolve_air_quality_zone(longitude, latitude, load_air_quality_zones(CONFIG_PATH))


def test_zone_loader_rejects_invalid_blend_weight_sum(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["zones"][0]["blend_components"][0]["weight"] = 0.4
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AirQualityZoneError, match="权重之和应为 1"):
        load_air_quality_zones(path, valid_point_ids=_valid_point_ids())


def test_zone_loader_rejects_unknown_point_reference(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["zones"][1]["probe_point_ids"] = ["UNKNOWN"]
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AirQualityZoneError, match="未知采样点"):
        load_air_quality_zones(path, valid_point_ids=_valid_point_ids())


def test_zone_loader_rejects_invalid_external_probe_point(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["probe_points"][0]["longitude"] = 181.0
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AirQualityZoneError, match="WGS84"):
        load_air_quality_zones(path, valid_point_ids=_valid_point_ids())


def test_blend_pollutants_weights_six_concentrations_without_averaging_aqi() -> None:
    result = blend_pollutants(
        {
            "XH_ENT_0013": _record(10.0, aqi=40),
            "XH_ENT_0014": _record(20.0, aqi=100),
        },
        _components(),
    )

    assert result["status"] == "ok"
    assert result["is_estimated"] is True
    assert set(result["values"]) == POLLUTANTS
    assert result["values"] == {
        "pm2_5_ug_m3": 15.0,
        "pm10_ug_m3": 25.0,
        "ozone_ug_m3": 35.0,
        "nitrogen_dioxide_ug_m3": 45.0,
        "sulfur_dioxide_ug_m3": 55.0,
        "carbon_monoxide_mg_m3": 1.5,
    }
    assert "aqi" not in result["values"]
    assert result["components"][0]["record"] == _record(10.0, aqi=40)
    assert result["components"][0]["weight"] == 0.5


def test_blend_pollutants_recomputes_aqi_through_injected_calculator() -> None:
    calls: list[dict[str, float]] = []

    def calculate_aqi(values: dict[str, float]) -> int:
        calls.append(dict(values))
        return 73

    result = blend_pollutants(
        {
            "XH_ENT_0013": _record(10.0, aqi=10),
            "XH_ENT_0014": _record(20.0, aqi=200),
        },
        _components(),
        aqi_calculator=calculate_aqi,
    )

    assert result["values"]["aqi"] == 73
    assert calls == [{key: result["values"][key] for key in POLLUTANTS}]


def test_blend_pollutants_marks_one_missing_source_partial_and_normalizes_weight() -> None:
    available = _record(18.0, aqi=60)

    result = blend_pollutants({"XH_ENT_0013": available}, _components())

    assert result["status"] == "partial"
    assert result["missing_components"] == ["XH_ENT_0014"]
    assert result["values"]["pm2_5_ug_m3"] == 18.0
    assert result["components"] == [
        {
            "district": "徐汇区",
            "point_id": "XH_ENT_0013",
            "weight": 0.5,
            "record": available,
        }
    ]


def test_blend_pollutants_returns_no_data_when_all_sources_are_missing() -> None:
    result = blend_pollutants({}, _components())

    assert result == {
        "status": "no_data",
        "values": {},
        "components": [],
        "missing_components": ["XH_ENT_0013", "XH_ENT_0014"],
        "is_estimated": True,
    }
