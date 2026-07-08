from xuhui_route_builder.amap_client import AmapClient
from xuhui_route_builder.geo import parse_amap_boundary, parse_lng_lat
from xuhui_route_builder.routes import parse_direction_path


def test_parse_lng_lat_uses_gcj02_order() -> None:
    coord = parse_lng_lat("121.436100,31.176300")

    assert coord.lng_gcj02 == 121.4361
    assert coord.lat_gcj02 == 31.1763
    assert coord.lng_wgs84 != 0
    assert coord.lat_wgs84 != 0


def test_parse_amap_boundary_returns_polygon_feature() -> None:
    response = {
        "status": "1",
        "districts": [
            {
                "name": "徐汇区",
                "adcode": "310104",
                "center": "121.436100,31.176300",
                "polyline": "121.40,31.15;121.45,31.15;121.45,31.20;121.40,31.20;121.40,31.15",
            }
        ],
    }

    feature = parse_amap_boundary(response)

    assert feature["type"] == "Feature"
    assert feature["properties"]["adcode"] == "310104"
    assert feature["geometry"]["type"] == "Polygon"
    assert len(feature["geometry"]["coordinates"][0]) == 5


def test_parse_direction_path_extracts_distance_duration_and_polyline() -> None:
    response = {
        "status": "1",
        "route": {
            "paths": [
                {
                    "distance": "1200",
                    "duration": "900",
                    "steps": [
                        {
                            "instruction": "沿龙腾大道向南步行",
                            "road": "龙腾大道",
                            "distance": "600",
                            "polyline": "121.45,31.17;121.46,31.16",
                        },
                        {
                            "instruction": "到达徐汇滨江",
                            "road": "",
                            "distance": "600",
                            "polyline": "121.46,31.16;121.47,31.15",
                        },
                    ],
                }
            ]
        },
    }

    parsed = parse_direction_path(response)

    assert parsed.distance_m == 1200
    assert parsed.duration_s == 900
    assert parsed.polyline_gcj02 == ["121.45,31.17", "121.46,31.16", "121.47,31.15"]
    assert parsed.road_names == ["龙腾大道"]


def test_amap_client_builds_expected_service_params(tmp_path) -> None:
    client = AmapClient("test-key", cache_dir=tmp_path)

    url, params = client.prepare_request("district", {"keywords": "徐汇区"})

    assert url.endswith("/v3/config/district")
    assert params["key"] == "test-key"
    assert params["keywords"] == "徐汇区"
    assert params["output"] == "JSON"


def test_amap_client_builds_v5_poi_and_v2_route_params(tmp_path) -> None:
    client = AmapClient("test-key", cache_dir=tmp_path)

    poi_url, poi_params = client.prepare_request("place_text_v5", {"keywords": "咖啡", "region": "310104"})
    walk_url, walk_params = client.prepare_request(
        "walking_v2",
        {"origin": "121.4388,31.1955", "destination": "121.4418,31.1984"},
    )

    assert poi_url.endswith("/v5/place/text")
    assert poi_params["region"] == "310104"
    assert poi_params["key"] == "test-key"
    assert walk_url.endswith("/v5/direction/walking")
    assert walk_params["origin"] == "121.4388,31.1955"
