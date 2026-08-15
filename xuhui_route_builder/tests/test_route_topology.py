from xuhui_route_builder.models import CandidateRoute, CoordinatePair, RouteLocation, RouteNode
from xuhui_route_builder.validation import topology_failures


def _point(lng: float, lat: float) -> CoordinatePair:
    return CoordinatePair(lng_gcj02=lng, lat_gcj02=lat, lng_wgs84=lng, lat_wgs84=lat)


def _location(name: str, lng: float, lat: float) -> RouteLocation:
    return RouteLocation(
        name=name,
        location_type="public_space",
        lng_gcj02=lng,
        lat_gcj02=lat,
        source_url="https://www.xuhui.gov.cn/example",
    )


def _route(points: list[CoordinatePair], route_shape: str) -> CandidateRoute:
    start = _location("起点", points[0].lng_gcj02, points[0].lat_gcj02)
    end_name = "起点" if route_shape == "strict_loop" else "终点"
    end = _location(end_name, points[-1].lng_gcj02, points[-1].lat_gcj02)
    return CandidateRoute(
        route_id="XH_TEST_0001",
        route_name="拓扑测试路线",
        route_mode="walk",
        route_shape=route_shape,
        target_distance_m=1000,
        actual_distance_m=1000,
        duration_s=600,
        start_entry_id="start",
        end_entry_id="end",
        start_location=start,
        end_location=end,
        ordered_nodes=[
            RouteNode(node_name=start.name, lng_gcj02=start.lng_gcj02, lat_gcj02=start.lat_gcj02),
            RouteNode(node_name=end.name, lng_gcj02=end.lng_gcj02, lat_gcj02=end.lat_gcj02),
        ],
        amenity_ids=[],
        region_zone="徐汇区",
        polyline_gcj02=points,
        source_method="amap_segmented_direction",
        source_accessed_at="2026-08-15",
        geometry_source="amap_direction",
        geometry_status="complete",
        raw_response_paths=["data/raw/amap/test.json"],
        waypoint_names=[start.name, end.name],
    )


def test_topology_rejects_visible_out_and_back_spur() -> None:
    route = _route(
        [
            _point(121.4400, 31.1800),
            _point(121.4410, 31.1800),
            _point(121.4420, 31.1800),
            _point(121.4410, 31.1800),
            _point(121.4410, 31.1810),
        ],
        "one_way",
    )

    failures = topology_failures(route)

    assert any("重复边" in failure or "折返" in failure for failure in failures)


def test_topology_accepts_clean_strict_loop() -> None:
    route = _route(
        [
            _point(121.4400, 31.1800),
            _point(121.4410, 31.1800),
            _point(121.4410, 31.1810),
            _point(121.4400, 31.1810),
            _point(121.4400, 31.1800),
        ],
        "strict_loop",
    )

    assert topology_failures(route) == []


def test_topology_rejects_open_geometry_labelled_as_strict_loop() -> None:
    route = _route(
        [_point(121.4400, 31.1800), _point(121.4410, 31.1800), _point(121.4410, 31.1810)],
        "strict_loop",
    )

    assert any("首尾" in failure for failure in topology_failures(route))
