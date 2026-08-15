import pytest
from pydantic import ValidationError

from xuhui_route_builder.models import RouteLocation, RouteNode, RouteSeed


def _location(name: str, lng: float, lat: float) -> RouteLocation:
    return RouteLocation(
        name=name,
        location_type="park_gate",
        lng_gcj02=lng,
        lat_gcj02=lat,
        source_url="https://www.xuhui.gov.cn/example",
    )


def _seed(*, route_shape: str, start: RouteLocation, end: RouteLocation) -> RouteSeed:
    return RouteSeed(
        seed_id="shape-test",
        route_name="路线形态测试",
        route_mode="walk",
        route_shape=route_shape,
        distance_level="3km",
        target_distance_m=3000,
        region_zone="徐汇区",
        start_hint=start.name,
        end_hint=end.name,
        start_location=start,
        end_location=end,
        waypoint_hints=[],
        tags=["测试"],
        reason="验证路线形态契约",
        source_name="徐汇区人民政府",
        source_url="https://www.xuhui.gov.cn/example",
        source_accessed_at="2026-08-15",
        confidence="高",
        ordered_nodes=[
            RouteNode(node_name=start.name, lng_gcj02=start.lng_gcj02, lat_gcj02=start.lat_gcj02),
            RouteNode(node_name=end.name, lng_gcj02=end.lng_gcj02, lat_gcj02=end.lat_gcj02),
        ],
        allowed_modes=["walk"],
        source_level="A",
        evidence_note="入口与道路节点已核实",
        access_restrictions=["按现场开放时间通行"],
        amenity_ids=[],
        geometry_action="regenerate",
    )


def test_strict_loop_requires_one_shared_start_end_location() -> None:
    shared = _location("上海植物园二号门", 121.447, 31.145)

    seed = _seed(route_shape="strict_loop", start=shared, end=shared)

    assert seed.start_location == seed.end_location


def test_strict_loop_rejects_distinct_end_location() -> None:
    start = _location("上海植物园二号门", 121.447, 31.145)
    end = _location("上海植物园四号门", 121.455, 31.151)

    with pytest.raises(ValidationError, match="strict_loop"):
        _seed(route_shape="strict_loop", start=start, end=end)


def test_one_way_rejects_same_start_end_location() -> None:
    shared = _location("龙华会", 121.454, 31.178)

    with pytest.raises(ValidationError, match="one_way"):
        _seed(route_shape="one_way", start=shared, end=shared)

