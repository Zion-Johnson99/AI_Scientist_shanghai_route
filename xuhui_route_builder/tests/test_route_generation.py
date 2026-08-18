from types import SimpleNamespace

import pytest

from xuhui_route_builder.models import DirectionPath, RouteLocation, RouteNode, RouteSeed
from xuhui_route_builder.routes import (
    candidate_from_seed,
    generate_candidate_from_seed,
    preserve_candidate_geometry,
    resolve_node_query,
    resolve_seed_nodes,
)


def _seed(mode: str = "run", nodes: list[RouteNode] | None = None, route_shape: str = "one_way") -> RouteSeed:
    route_nodes = nodes or [
        RouteNode(node_name="起点", lng_gcj02=121.44, lat_gcj02=31.18),
        RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19),
    ]
    first, last = route_nodes[0], route_nodes[-1]
    start = RouteLocation(name=first.node_name, location_type="public_space", lng_gcj02=first.lng_gcj02 or 121.44, lat_gcj02=first.lat_gcj02 or 31.18, source_url="https://www.shanghai.gov.cn/example")
    end = RouteLocation(name=last.node_name, location_type="public_space", lng_gcj02=last.lng_gcj02 or 121.45, lat_gcj02=last.lat_gcj02 or 31.19, source_url="https://www.shanghai.gov.cn/example")
    return RouteSeed(
        seed_id="pilot",
        route_name="真实母线",
        route_mode=mode,
        route_shape=route_shape,
        distance_level="3km",
        target_distance_m=3000,
        region_zone="徐汇滨江",
        start_hint=start.name,
        end_hint=end.name,
        start_location=start,
        end_location=end,
        waypoint_hints=["途经点"],
        tags=["滨江"],
        reason="官方路线",
        source_name="上海市政府",
        source_url="https://www.shanghai.gov.cn/example",
        source_accessed_at="2026-08-13",
        confidence="高",
        ordered_nodes=route_nodes,
        allowed_modes=[mode],
        source_level="A",
        evidence_note="官方给出地标顺序",
        access_restrictions=["开放时间内通行"],
        amenity_ids=[],
        geometry_action="regenerate",
    )


class FakeClient:
    def __init__(self) -> None:
        self.place_calls: list[str] = []
        self.direction_calls: list[tuple[str, str, str]] = []

    def place_text_v5(self, name: str, region: str = "310104"):
        self.place_calls.append(name)
        return SimpleNamespace(
            payload={"pois": [{"id": "bad", "location": ""}, {"id": "B001", "name": name, "adcode": "310104", "location": "121.46,31.20"}]},
            raw_path="raw/place.json",
            status="1",
        )

    def walking_v2(self, origin: str, destination: str):
        self.direction_calls.append(("walking", origin, destination))
        number = len(self.direction_calls)
        return SimpleNamespace(
            payload={
                "route": {
                    "paths": [
                        {
                            "distance": "1000",
                            "duration": "600",
                            "steps": [
                                {
                                    "road": f"道路{number}",
                                    "instruction": f"前往节点{number}",
                                    "polyline": "121.440000,31.180000;121.445000,31.185000"
                                    if number == 1
                                    else "121.445000,31.185000;121.450000,31.190000",
                                }
                            ],
                        }
                    ]
                }
            },
            raw_path=f"raw/walk-{number}.json",
            status="1",
        )

    def bicycling_v2(self, origin: str, destination: str):
        self.direction_calls.append(("bike", origin, destination))
        number = len(self.direction_calls)
        return SimpleNamespace(
            payload={
                "route": {
                    "paths": [
                        {
                            "distance": "1200",
                            "duration": "500",
                            "steps": [{"road": "骑行道", "instruction": "骑行", "polyline": f"{origin};{destination}"}],
                        }
                    ]
                }
            },
            raw_path=f"raw/bike-{number}.json",
            status="1",
        )


def test_resolve_seed_nodes_preserves_existing_gcj_coordinates() -> None:
    client = FakeClient()
    seed = _seed()

    resolved = resolve_seed_nodes(seed, client)

    assert resolved.ordered_nodes == seed.ordered_nodes
    assert client.place_calls == []


def test_resolve_seed_nodes_uses_first_valid_place_result() -> None:
    client = FakeClient()
    resolved, _ = resolve_node_query("待解析入口", "待解析入口", client, None, "pilot", 0)

    assert resolved.poi_id == "B001"
    assert resolved.lng_gcj02 == 121.46
    assert resolved.lat_gcj02 == 31.20


def test_resolve_node_query_uses_explicit_poi_id_to_disambiguate_same_name() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1",
        raw_path="raw/place.json",
        payload={
            "pois": [
                {"id": "A", "name": "同名交叉口", "adcode": "310104", "location": "121.44,31.18"},
                {"id": "B", "name": "同名交叉口", "adcode": "310104", "location": "121.45,31.19"},
            ]
        },
    )

    node, _ = resolve_node_query("同名交叉口", "同名交叉口", client, "B", "seed", 0)

    assert node.poi_id == "B"


def test_resolve_node_query_accepts_one_unique_address_prefix_match() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1",
        raw_path="raw/place.json",
        payload={
            "pois": [
                {
                    "id": "ADDRESS",
                    "name": "城市会客厅",
                    "address": "淮海中路1209号(常熟路地铁站步行170米)",
                    "adcode": "310104",
                    "location": "121.452937,31.213617",
                },
                {
                    "id": "OTHER",
                    "name": "淮海中路",
                    "address": "徐汇区",
                    "adcode": "310104",
                    "location": "121.456655,31.215841",
                },
            ]
        },
    )

    node, _ = resolve_node_query("淮海中路1209号", "淮海中路1209号", client, None, "seed", 0)

    assert node.poi_id == "ADDRESS"


def test_resolve_node_query_accepts_one_unique_normalized_containment_match() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1",
        raw_path="raw/place.json",
        payload={
            "pois": [
                {
                    "id": "FORMAL",
                    "name": "上海植物园-兰室",
                    "address": "龙吴路1111号上海植物园内",
                    "adcode": "310104",
                    "location": "121.446205,31.146753",
                },
                {
                    "id": "OTHER",
                    "name": "上海植物园",
                    "address": "龙吴路1111号",
                    "adcode": "310104",
                    "location": "121.444271,31.147478",
                },
            ]
        },
    )

    node, _ = resolve_node_query("兰室", "上海植物园兰室", client, None, "seed", 0)

    assert node.poi_id == "FORMAL"


def test_resolve_node_query_falls_back_to_unique_xuhui_geocode() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1", raw_path="raw/place.json", payload={"pois": []}
    )
    client.geocode = lambda address, city="上海": SimpleNamespace(
        status="1",
        raw_path="raw/geocode.json",
        payload={
            "geocodes": [
                {
                    "formatted_address": "上海市徐汇区龙腾大道龙耀路",
                    "adcode": "310104",
                    "location": "121.459,31.159",
                }
            ]
        },
    )

    node, raw_path = resolve_node_query("龙腾大道龙耀路口", "龙腾大道龙耀路", client, None, "seed", 0)

    assert node.lng_gcj02 == 121.459
    assert node.lat_gcj02 == 31.159
    assert raw_path == "raw/geocode.json"


def test_resolve_node_query_deduplicates_identical_geocode_records() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1", raw_path="raw/place.json", payload={"pois": []}
    )
    duplicate = {
        "formatted_address": "上海市徐汇区桂林路",
        "adcode": "310104",
        "location": "121.416867,31.172599",
    }
    client.geocode = lambda address, city="上海": SimpleNamespace(
        status="1", raw_path="raw/geocode.json", payload={"geocodes": [duplicate, duplicate, duplicate]}
    )

    node, _ = resolve_node_query("桂林路", "桂林路", client, None, "seed", 0)

    assert node.lng_gcj02 == 121.416867


def test_resolve_node_query_matches_reversed_intersection_name() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1",
        raw_path="raw/place.json",
        payload={"pois": [{
            "id": "CROSS",
            "name": "云锦路与龙耀路交叉口",
            "adcode": "310104",
            "location": "121.459280,31.161845",
        }]},
    )

    node, _ = resolve_node_query("龙耀路与云锦路交叉口", "龙耀路云锦路", client, None, "seed", 0)

    assert node.poi_id == "CROSS"


def test_resolve_node_query_uses_unique_shortest_containment_match() -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(
        status="1",
        raw_path="raw/place.json",
        payload={"pois": [
            {"id": "MAIN", "name": "Gate M西岸梦中心", "adcode": "310104", "location": "121.465,31.161"},
            {"id": "PARKING", "name": "Gate M西岸梦中心地下停车场", "adcode": "310104", "location": "121.465,31.160"},
        ]},
    )

    node, _ = resolve_node_query("西岸梦中心", "西岸梦中心", client, None, "seed", 0)

    assert node.poi_id == "MAIN"


@pytest.mark.parametrize("pois", [[], [{"id": "bad", "location": "oops"}], [{"id": "bad", "location": "181,31"}]])
def test_resolve_seed_nodes_rejects_missing_or_invalid_places(pois: list[dict]) -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": SimpleNamespace(payload={"pois": pois}, raw_path="raw/place.json", status="1")
    seed = _seed(nodes=[RouteNode(node_name="待解析入口", poi_id="placeholder"), RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19)])

    with pytest.raises(ValueError, match="待解析入口"):
        resolve_seed_nodes(seed, client)


def test_generate_candidate_stitches_segments_and_preserves_evidence() -> None:
    nodes = [
        RouteNode(node_name="起点", lng_gcj02=121.44, lat_gcj02=31.18),
        RouteNode(node_name="途经点", lng_gcj02=121.445, lat_gcj02=31.185),
        RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19),
    ]
    client = FakeClient()

    seed = _seed(nodes=nodes).model_copy(update={
        "popular_area_ids": ["west_bund"],
        "preference_search_status": {
            "coffee": "verified",
            "park_gate": "verified",
            "toilet": "no_verified_match",
            "convenience": "needs_review",
        },
        "preference_hits": ["coffee", "park_gate"],
    })
    route = generate_candidate_from_seed(seed, client, 7)

    assert route.route_id == "XH_RUN_0007"
    assert route.actual_distance_m == 2000
    assert route.distance_error_m == abs(2000 - route.target_distance_m)
    assert route.loop_flag is False
    assert route.duration_s == 1200
    assert len(route.polyline_gcj02) == 3
    assert route.road_names == ["道路1", "道路2"]
    assert route.raw_response_paths == ["raw/walk-1.json", "raw/walk-2.json"]
    assert route.geometry_source == "amap_direction"
    assert route.geometry_status == "complete"
    assert route.validation_status == "pending"
    assert route.network_source == "amap_walking_v2"
    assert route.source_name == "上海市政府"
    assert route.source_url == "https://www.shanghai.gov.cn/example"
    assert route.source_accessed_at.isoformat() == "2026-08-13"
    assert route.confidence == "高"
    assert route.source_level == "A"
    assert route.waypoint_names == ["起点", "途经点", "终点"]
    assert route.popular_area_ids == ["west_bund"]
    assert route.preference_search_status["park_gate"] == "verified"
    assert route.preference_hits == ["coffee", "park_gate"]
    assert "开放时间内通行" in route.review_note
    assert "官方给出地标顺序" in route.review_note
    assert [call[0] for call in client.direction_calls] == ["walking", "walking"]


def test_generate_candidate_rejects_unresolved_or_failed_segments() -> None:
    client = FakeClient()
    unresolved = _seed(nodes=[RouteNode(node_name="入口", poi_id="B001"), RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19)])
    with pytest.raises(ValueError, match="resolved"):
        generate_candidate_from_seed(unresolved, client, 1)

    client.walking_v2 = lambda _origin, _destination: SimpleNamespace(payload={"route": {"paths": []}}, raw_path="raw/fail.json", status="1")
    with pytest.raises(ValueError, match=r"segment=1.*mode=walking.*origin=.*destination="):
        generate_candidate_from_seed(_seed(), client, 1)


def test_candidate_from_seed_keeps_source_fields() -> None:
    direction = DirectionPath(distance_m=100, duration_s=60, polyline_gcj02=["121.44,31.18", "121.45,31.19"])

    route = candidate_from_seed(_seed(), direction, 1)

    assert route.source_name == "上海市政府"
    assert route.source_url == "https://www.shanghai.gov.cn/example"
    assert route.confidence == "高"
    assert route.source_level == "A"
    assert route.waypoint_names == ["起点", "终点"]


def test_candidate_from_seed_snaps_endpoint_markers_to_generated_geometry() -> None:
    direction = DirectionPath(
        distance_m=100,
        duration_s=60,
        polyline_gcj02=["121.4405,31.1805", "121.4495,31.1895"],
    )

    route = candidate_from_seed(_seed(), direction, 1)

    assert (route.start_location.lng_gcj02, route.start_location.lat_gcj02) == (121.4405, 31.1805)
    assert (route.end_location.lng_gcj02, route.end_location.lat_gcj02) == (121.4495, 31.1895)
    assert (route.ordered_nodes[0].lng_gcj02, route.ordered_nodes[0].lat_gcj02) == (121.4405, 31.1805)
    assert (route.ordered_nodes[-1].lng_gcj02, route.ordered_nodes[-1].lat_gcj02) == (121.4495, 31.1895)


def test_candidate_from_seed_marks_same_poi_as_loop() -> None:
    node = RouteNode(node_name="环线入口", poi_id="LOOP", lng_gcj02=121.44, lat_gcj02=31.18)
    seed = _seed(nodes=[node, node], route_shape="strict_loop")
    direction = DirectionPath(distance_m=100, duration_s=60, polyline_gcj02=["121.44,31.18", "121.441,31.18"])

    route = candidate_from_seed(seed, direction, 1)

    assert route.loop_flag is True


def test_preserve_candidate_geometry_updates_semantics_without_changing_polyline() -> None:
    node = RouteNode(node_name="保护入口", poi_id="LOOP", lng_gcj02=121.44, lat_gcj02=31.18)
    seed = _seed(nodes=[node, node], route_shape="strict_loop")
    previous = candidate_from_seed(
        seed,
        DirectionPath(distance_m=500, duration_s=300, polyline_gcj02=["121.44,31.18", "121.441,31.181", "121.44,31.18"]),
        33,
    ).model_dump(mode="json")
    old_geometry = previous["polyline_gcj02"]

    preserved = preserve_candidate_geometry(seed, previous, 33)

    assert preserved.polyline_gcj02[0].model_dump(mode="json") == old_geometry[0]
    assert preserved.polyline_gcj02[-1].model_dump(mode="json") == old_geometry[-1]
    assert preserved.route_shape == "strict_loop"
    assert preserved.start_location == preserved.end_location
    assert preserved.validation_status == "pending"


def test_resolve_seed_nodes_passes_xuhui_region_and_rejects_ambiguous_pois() -> None:
    calls: list[tuple[str, str]] = []

    def ambiguous(name: str, region: str = ""):
        calls.append((name, region))
        return SimpleNamespace(
            payload={
                "pois": [
                    {"id": "A", "name": "同名入口A", "adcode": "310104", "location": "121.44,31.18"},
                    {"id": "B", "name": "同名入口B", "adcode": "310104", "location": "121.45,31.19"},
                ]
            },
            raw_path="raw/place.json",
            status="1",
        )

    client = FakeClient()
    client.place_text_v5 = ambiguous
    seed = _seed(nodes=[RouteNode(node_name="待解析入口", poi_id="placeholder"), RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19)])

    with pytest.raises(ValueError, match=r"seed_id=pilot.*node_index=0.*待解析入口.*ambiguous"):
        resolve_seed_nodes(seed, client)
    assert calls == [("待解析入口", "310104")]


def test_resolve_seed_nodes_wraps_client_error_with_node_context() -> None:
    client = FakeClient()

    def fail(_name: str, region: str = "310104"):
        raise RuntimeError("network down")

    client.place_text_v5 = fail
    seed = _seed(nodes=[RouteNode(node_name="待解析入口", poi_id="placeholder"), RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19)])

    with pytest.raises(ValueError, match=r"seed_id=pilot.*node_index=0.*待解析入口") as exc_info:
        resolve_seed_nodes(seed, client)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (
            SimpleNamespace(
                payload={"pois": [{"id": "B001", "name": "待解析入口", "adcode": "310105", "location": "121.46,31.20"}]},
                raw_path="raw/place.json",
                status="1",
            ),
            "adcode",
        ),
        (
            SimpleNamespace(
                payload={"pois": [{"id": "B001", "name": "其他入口", "adcode": "310104", "location": "121.46,31.20"}]},
                raw_path="raw/place.json",
                status="1",
            ),
            "name",
        ),
        (
            SimpleNamespace(
                payload={"pois": [{"id": "B001", "name": "待解析入口", "adcode": "310104", "location": "121.46,31.20"}]},
                raw_path="raw/place.json",
                status="0",
            ),
            "status",
        ),
        (
            SimpleNamespace(
                payload={"pois": [{"id": "B001", "name": "待解析入口", "adcode": "310104", "location": "121.46,31.20"}]},
                raw_path="",
                status="1",
            ),
            "raw_path",
        ),
    ],
)
def test_resolve_seed_nodes_rejects_untrusted_single_poi_records(record, message: str) -> None:
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": record
    seed = _seed(nodes=[RouteNode(node_name="待解析入口", poi_id="placeholder"), RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19)])

    with pytest.raises(ValueError, match=rf"seed_id=pilot.*{message}"):
        resolve_seed_nodes(seed, client)


def test_resolve_seed_nodes_accepts_normalized_name_or_exact_poi_id_and_records_raw_paths() -> None:
    responses = iter(
        [
            SimpleNamespace(
                payload={"pois": [{"id": "A001", "name": " 待解析 入口 ", "adcode": "310104", "location": "121.46,31.20"}]},
                raw_path="raw/place-1.json",
                status="1",
            ),
            SimpleNamespace(
                payload={"pois": [{"id": "B002", "name": "地图别名", "adcode": "310104", "location": "121.47,31.21"}]},
                raw_path="raw/place-2.json",
                status="1",
            ),
        ]
    )
    client = FakeClient()
    client.place_text_v5 = lambda _name, region="310104": next(responses)
    seed = _seed(
        nodes=[
            RouteNode(node_name="待解析入口", poi_id="A001"),
            RouteNode(node_name="第二入口", poi_id="B002"),
        ]
    )

    resolved = resolve_seed_nodes(seed, client)

    assert [node.poi_id for node in resolved.ordered_nodes] == ["A001", "B002"]
    assert "POI解析响应: raw/place-1.json" in resolved.evidence_note
    assert "POI解析响应: raw/place-2.json" in resolved.evidence_note


@pytest.mark.parametrize(("mode", "expected_call"), [("walk", "walking"), ("run", "walking"), ("bike", "bike"), ("bike_assist", "bike")])
def test_generate_candidate_uses_only_the_route_mode_endpoint(mode: str, expected_call: str) -> None:
    client = FakeClient()

    route = generate_candidate_from_seed(_seed(mode=mode), client, 1)

    assert [call[0] for call in client.direction_calls] == [expected_call]
    assert route.network_source == f"amap_{expected_call}_v2"


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (SimpleNamespace(status="0", payload={"route": {"paths": []}}, raw_path="raw/fail.json"), "status"),
        (SimpleNamespace(status="1", payload={"route": {"paths": []}}, raw_path=""), "raw_path"),
        (
            SimpleNamespace(
                status="1",
                payload={"route": {"paths": [{"distance": "0", "duration": "10", "steps": [{"polyline": "121.44,31.18;121.45,31.19"}]}]}},
                raw_path="raw/zero.json",
            ),
            "distance",
        ),
        (
            SimpleNamespace(
                status="1",
                payload={"route": {"paths": [{"distance": "10", "duration": "0", "steps": [{"polyline": "121.44,31.18;121.45,31.19"}]}]}},
                raw_path="raw/zero.json",
            ),
            "duration",
        ),
    ],
)
def test_generate_candidate_rejects_unsuccessful_or_incomplete_records(record, message: str) -> None:
    client = FakeClient()
    client.walking_v2 = lambda _origin, _destination: record

    with pytest.raises(ValueError, match=rf"segment=1.*mode=walking.*{message}"):
        generate_candidate_from_seed(_seed(), client, 1)


def test_generate_candidate_wraps_second_segment_request_error_with_full_context() -> None:
    client = FakeClient()
    original = client.walking_v2

    def fail_second(origin: str, destination: str):
        if len(client.direction_calls) == 1:
            raise RuntimeError("quota exceeded")
        return original(origin, destination)

    client.walking_v2 = fail_second
    seed = _seed(
        nodes=[
            RouteNode(node_name="起点", lng_gcj02=121.44, lat_gcj02=31.18),
            RouteNode(node_name="途经点", lng_gcj02=121.445, lat_gcj02=31.185),
            RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19),
        ]
    )

    with pytest.raises(ValueError, match=r"segment=2.*mode=walking.*origin=121.445,31.185.*destination=121.45,31.19") as exc_info:
        generate_candidate_from_seed(seed, client, 1)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
