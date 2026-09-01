import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xuhui_route_builder.place_resolver import (
    HybridPlaceResolver,
    _load_osm_candidates,
)


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _resolver(
    tmp_path: Path, client, *, max_online_calls: int = 50
) -> HybridPlaceResolver:
    local_path = _write_json(
        tmp_path / "route_seeds.json",
        [
            {
                "ordered_nodes": [
                    {
                        "node_name": "上海植物园3号门",
                        "poi_id": "AMAP1",
                        "lng_gcj02": 121.44,
                        "lat_gcj02": 31.14,
                    }
                ]
            }
        ],
    )
    osm_path = _write_json(
        tmp_path / "osm_poi_index.json",
        {
            "pois": [
                {
                    "osm_type": "node",
                    "osm_id": 7,
                    "name": "康健园",
                    "lng_wgs84": 121.42,
                    "lat_wgs84": 31.17,
                }
            ]
        },
    )
    boundary_path = _write_json(
        tmp_path / "boundary.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [121.3, 31.0],
                                [121.6, 31.0],
                                [121.6, 31.3],
                                [121.3, 31.3],
                                [121.3, 31.0],
                            ]
                        ],
                    },
                    "properties": {},
                }
            ],
        },
    )
    return HybridPlaceResolver(
        client,
        local_seed_path=local_path,
        osm_index_path=osm_path,
        boundary_path=boundary_path,
        max_online_calls=max_online_calls,
    )


def test_osm_index_uses_type_error_for_non_list_payload(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "osm_poi_index.json", {"pois": {}})

    with pytest.raises(TypeError, match="OSM POI index invalid"):
        _load_osm_candidates(source)


def test_resolver_prefers_local_then_osm_without_baidu(tmp_path: Path) -> None:
    class Client:
        def place_region(self, *args, **kwargs):
            raise AssertionError("Baidu should not be called")

    resolver = _resolver(tmp_path, Client())

    local, _ = resolver.resolve(
        "上海植物园3号门", "上海植物园3号门", "AMAP1", "seed", 0
    )
    osm, _ = resolver.resolve("康健园", "康健园", None, "seed", 1)

    assert local.poi_id == "AMAP1"
    assert osm.poi_id == "osm:node/7"
    assert osm.lng_gcj02 != osm.lng_wgs84


def test_osm_name_can_replace_missing_provider_specific_poi_id(tmp_path: Path) -> None:
    class Client:
        def place_region(self, *args, **kwargs):
            raise AssertionError("Baidu should not be called")

    resolver = _resolver(tmp_path, Client())

    node, _ = resolver.resolve("康健园", "康健园", "missing-amap-id", "seed", 1)

    assert node.poi_id == "osm:node/7"


def test_resolver_uses_baidu_gcj02_result_for_unresolved_place(tmp_path: Path) -> None:
    class Client:
        def place_region(self, query, region, *, allow_network):
            return SimpleNamespace(
                status=0,
                message="ok",
                raw_path="raw/baidu/place.json",
                cache_hit=False,
                payload={
                    "results": [
                        {
                            "uid": "BD1",
                            "name": query,
                            "adcode": 310104,
                            "location": {"lng": 121.45, "lat": 31.18},
                        }
                    ]
                },
            )

    resolver = _resolver(tmp_path, Client())

    node, raw_path = resolver.resolve("新地点", "新地点", None, "seed", 2)

    assert node.poi_id == "baidu:BD1"
    assert node.lng_gcj02 == 121.45
    assert raw_path == "raw/baidu/place.json"
    assert resolver.online_calls == 1


def test_resolver_stops_before_uncached_request_when_budget_is_zero(
    tmp_path: Path,
) -> None:
    class Client:
        def place_region(self, query, region, *, allow_network):
            assert allow_network is False
            raise RuntimeError("Baidu network request budget exhausted")

    resolver = _resolver(tmp_path, Client(), max_online_calls=0)

    with pytest.raises(ValueError, match="budget exhausted"):
        resolver.resolve("新地点", "新地点", None, "seed", 2)
