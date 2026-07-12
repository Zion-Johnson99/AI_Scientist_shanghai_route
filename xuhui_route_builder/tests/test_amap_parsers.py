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


def test_parse_direction_path_supports_real_v5_cost_and_step_fields() -> None:
    response = {
        "route": {
            "paths": [
                {
                    "distance": "497",
                    "cost": {"duration": "398"},
                    "steps": [
                        {
                            "instruction": "沿园路步行",
                            "road_name": "园路",
                            "step_distance": "497",
                            "polyline": "121.44,31.18;121.45,31.19",
                        }
                    ],
                }
            ]
        }
    }

    parsed = parse_direction_path(response)

    assert parsed.distance_m == 497
    assert parsed.duration_s == 398
    assert parsed.road_names == ["园路"]
    assert parsed.polyline_gcj02 == ["121.44,31.18", "121.45,31.19"]


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


def test_v2_route_requests_include_cost_and_polyline_fields(tmp_path, monkeypatch) -> None:
    client = AmapClient("test-key", cache_dir=tmp_path)
    captured = []

    def fake_request(endpoint, params):
        captured.append((endpoint, params))
        return object()

    monkeypatch.setattr(client, "request", fake_request)

    client.walking_v2("121.44,31.18", "121.45,31.19")
    client.bicycling_v2("121.44,31.18", "121.45,31.19")

    assert captured == [
        ("walking_v2", {"origin": "121.44,31.18", "destination": "121.45,31.19", "show_fields": "cost,polyline"}),
        ("bicycling_v2", {"origin": "121.44,31.18", "destination": "121.45,31.19", "show_fields": "cost,polyline"}),
    ]


def test_amap_client_retries_qps_limit_with_bounded_backoff(tmp_path, monkeypatch) -> None:
    payloads = [
        {"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"},
        {"status": "1", "info": "OK", "infocode": "10000", "pois": []},
    ]
    calls = []
    sleeps = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payloads[len(calls) - 1]

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("xuhui_route_builder.amap_client.requests.get", fake_get)
    client = AmapClient(
        "test-key",
        cache_dir=tmp_path,
        qps_retry_delays=(1.0, 2.0),
        sleep_fn=sleeps.append,
    )

    record = client.place_text_v5("星美术馆")

    assert record.status == "1"
    assert len(calls) == 2
    assert sleeps == [1.0]
