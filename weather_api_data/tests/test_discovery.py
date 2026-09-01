from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from weather_api_data.advanced_client import AdvancedClient
from weather_api_data.discovery import DiscoveryError, DiscoveryService, load_sampling_points
from weather_api_data.http_client import HttpResult

CONFIG_PATH = Path(__file__).parents[1] / "config" / "xuhui_sampling_points.json"
FETCHED_AT = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
EXPECTED_POINTS = (
    ("XH_ENT_0001", "龙耀路地铁站滨江入口", 121.455241, 31.161142),
    ("XH_ENT_0002", "西岸艺术中心滨江入口", 121.460455, 31.170949),
    ("XH_ENT_0003", "上海植物园1号门", 121.43359, 31.151204),
    ("XH_ENT_0004", "上海植物园4号门", 121.427179, 31.156592),
    ("XH_ENT_0005", "桂江路中环绿廊入口", 121.415864, 31.152682),
    ("XH_ENT_0006", "康健园北门", 121.419668, 31.161681),
    ("XH_ENT_0007", "徐家汇公园入口", 121.437193, 31.200285),
    ("XH_ENT_0008", "徐家汇站12号口", 121.434187, 31.197381),
    ("XH_ENT_0009", "龙华烈士陵园一号门", 121.448321, 31.178317),
    ("XH_ENT_0010", "龙华寺广场", 121.449023, 31.174721),
    ("XH_ENT_0011", "衡山路8号入口", 121.441401, 31.206889),
    ("XH_ENT_0012", "武康大楼源点广场", 121.434086, 31.209575),
    ("XH_ENT_0013", "漕河泾开发区站入口", 121.399853, 31.177862),
    ("XH_ENT_0014", "漕河泾办公园区入口", 121.405956, 31.172366),
)


def http_result(payload: object) -> HttpResult:
    return HttpResult(payload=payload, status_code=200, expires=None, fetched_at=FETCHED_AT)


class FakeAdvancedClient(AdvancedClient):
    """用内存响应替代 AdvancedClient 的传输边界。"""

    def __init__(
        self,
        location_keys: list[str],
        air_sources: dict[str, str | None],
        *,
        location_payload_override: object | None = None,
        air_payload_override: object | None = None,
    ) -> None:
        self._location_keys = iter(location_keys)
        self._air_sources = air_sources
        self._location_payload_override = location_payload_override
        self._air_payload_override = air_payload_override
        self.geoposition_calls: list[tuple[float, float]] = []
        self.air_quality_calls: list[str] = []

    def geoposition(self, latitude: float, longitude: float) -> HttpResult:
        self.geoposition_calls.append((latitude, longitude))
        if self._location_payload_override is not None:
            return http_result(self._location_payload_override)
        location_key = next(self._location_keys)
        return http_result(
            {
                "Key": location_key,
                "LocalizedName": f"徐汇区-{location_key}",
                "AdministrativeArea": {"ID": "SH", "LocalizedName": "上海市"},
                "GeoPosition": {"Latitude": latitude, "Longitude": longitude},
            }
        )

    def current_air_quality(self, location_key: str) -> HttpResult:
        self.air_quality_calls.append(location_key)
        if self._air_payload_override is not None:
            return http_result(self._air_payload_override)
        source = self._air_sources[location_key]
        return http_result({} if source is None else {"Source": source})


def test_sampling_point_config_has_exact_real_entries_and_only_contract_keys() -> None:
    raw_object = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert isinstance(raw_object, list)
    raw = cast(list[dict[str, object]], raw_object)
    assert [tuple(item.values()) for item in raw] == list(EXPECTED_POINTS)
    assert all(set(item) == {"point_id", "name", "longitude", "latitude"} for item in raw)

    points = load_sampling_points(CONFIG_PATH)
    assert (
        tuple((point.point_id, point.name, point.longitude, point.latitude) for point in points)
        == EXPECTED_POINTS
    )


@pytest.mark.parametrize(
    "violation",
    ["extra_key", "duplicate_id", "invalid_longitude", "wrong_count"],
)
def test_sampling_point_loader_rejects_contract_violations(tmp_path: Path, violation: str) -> None:
    rows = [
        {
            "point_id": point_id,
            "name": name,
            "longitude": longitude,
            "latitude": latitude,
        }
        for point_id, name, longitude, latitude in EXPECTED_POINTS
    ]
    if violation == "extra_key":
        rows[0]["unexpected"] = True
    elif violation == "duplicate_id":
        rows[1]["point_id"] = rows[0]["point_id"]
    elif violation == "invalid_longitude":
        rows[0]["longitude"] = 181.0
    else:
        rows.pop()
    path = tmp_path / "points.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DiscoveryError):
        load_sampling_points(path)


def test_discovery_calls_14_locations_and_air_quality_once_per_unique_key() -> None:
    points = load_sampling_points(CONFIG_PATH)
    keys = ["LK-A"] * 5 + ["LK-B"] * 5 + ["LK-C"] * 4
    client = FakeAdvancedClient(keys, {"LK-A": "Source A", "LK-B": "Source B", "LK-C": "Source C"})

    discovered = DiscoveryService(client).discover(points)

    assert client.geoposition_calls == [(point.latitude, point.longitude) for point in points]
    assert client.air_quality_calls == ["LK-A", "LK-B", "LK-C"]
    assert discovered.status == "ok"
    assert [location.location_key for location in discovered.locations] == [
        "LK-A",
        "LK-B",
        "LK-C",
    ]
    assert discovered.locations[0].probe_point_ids == tuple(point.point_id for point in points[:5])
    assert discovered.locations[1].probe_point_ids == tuple(
        point.point_id for point in points[5:10]
    )
    assert discovered.locations[2].probe_point_ids == tuple(point.point_id for point in points[10:])


def test_discover_locations_only_geopositions_and_preserves_coverage() -> None:
    points = load_sampling_points(CONFIG_PATH)
    keys = ["LK-A"] * 5 + ["LK-B"] * 5 + ["LK-C"] * 4
    client = FakeAdvancedClient(keys, {})

    locations = DiscoveryService(client).discover_locations(points)

    assert client.geoposition_calls == [(point.latitude, point.longitude) for point in points]
    assert client.air_quality_calls == []
    assert [location.location_key for location in locations] == ["LK-A", "LK-B", "LK-C"]
    assert locations[0].probe_point_ids == tuple(point.point_id for point in points[:5])
    assert locations[1].probe_point_ids == tuple(point.point_id for point in points[5:10])
    assert locations[2].probe_point_ids == tuple(point.point_id for point in points[10:])


def test_discover_locations_accepts_live_single_object_payload() -> None:
    points = load_sampling_points(CONFIG_PATH)
    client = FakeAdvancedClient(
        ["unused"] * 14,
        {},
        location_payload_override={
            "Key": "974168",
            "LocalizedName": "徐汇区",
            "AdministrativeArea": {"ID": "SH", "LocalizedName": "上海市"},
            "GeoPosition": {"Latitude": 31.187, "Longitude": 121.441},
        },
    )

    locations = DiscoveryService(client).discover_locations(points)

    assert len(locations) == 1
    assert locations[0].location_key == "974168"
    assert locations[0].probe_point_ids == tuple(point.point_id for point in points)


def test_discovery_preserves_distinct_source_strings_and_location_coverage() -> None:
    points = load_sampling_points(CONFIG_PATH)
    keys = ["LK-A"] * 7 + ["LK-B"] * 7
    client = FakeAdvancedClient(keys, {"LK-A": "徐汇来源甲", "LK-B": "徐汇来源乙"})

    discovered = DiscoveryService(client).discover(points)

    assert [source.source for source in discovered.air_quality_sources] == [
        "徐汇来源甲",
        "徐汇来源乙",
    ]
    assert discovered.air_quality_sources[0].location_key == "LK-A"
    assert discovered.air_quality_sources[0].probe_point_ids == tuple(
        point.point_id for point in points[:7]
    )
    assert discovered.air_quality_sources[1].location_key == "LK-B"
    assert discovered.air_quality_sources[1].probe_point_ids == tuple(
        point.point_id for point in points[7:]
    )


def test_unknown_air_quality_source_is_explicit_partial_state() -> None:
    points = load_sampling_points(CONFIG_PATH)
    client = FakeAdvancedClient(["LK-A"] * 14, {"LK-A": None})

    discovered = DiscoveryService(client).discover(points)

    assert discovered.status == "partial"
    assert discovered.air_quality_sources[0].source is None
    assert discovered.air_quality_sources[0].source_status == "unknown"


def test_discovery_result_to_dict_is_json_serializable() -> None:
    points = load_sampling_points(CONFIG_PATH)
    client = FakeAdvancedClient(["LK-A"] * 14, {"LK-A": "Source A"})

    data = DiscoveryService(client).discover(points).to_dict()
    decoded = json.loads(json.dumps(data, ensure_ascii=False))

    assert decoded["status"] == "ok"
    assert decoded["locations"][0]["location_key"] == "LK-A"
    assert decoded["locations"][0]["administrative_area"]["ID"] == "SH"
    assert decoded["air_quality_sources"][0]["source"] == "Source A"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        ["not-an-object"],
        [{"LocalizedName": "徐汇区", "AdministrativeArea": {}, "GeoPosition": {}}],
        [{"Key": "LK-A", "LocalizedName": "徐汇区", "GeoPosition": {}}],
        [
            {
                "Key": "LK-A",
                "LocalizedName": "徐汇区",
                "AdministrativeArea": {},
                "GeoPosition": {"Latitude": "31.2", "Longitude": 121.4},
            }
        ],
    ],
)
def test_discovery_rejects_empty_or_malformed_location_payloads(payload: object) -> None:
    points = load_sampling_points(CONFIG_PATH)
    client = FakeAdvancedClient(
        ["unused"] * 14,
        {"unused": "Source"},
        location_payload_override=payload,
    )

    with pytest.raises(DiscoveryError):
        DiscoveryService(client).discover(points)


def test_discovery_rejects_non_object_air_quality_payload() -> None:
    points = load_sampling_points(CONFIG_PATH)
    client = FakeAdvancedClient(
        ["LK-A"] * 14,
        {"LK-A": "Source A"},
        air_payload_override=[],
    )

    with pytest.raises(DiscoveryError):
        DiscoveryService(client).discover(points)
