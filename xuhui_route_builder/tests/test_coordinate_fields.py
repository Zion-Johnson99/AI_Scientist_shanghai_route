from xuhui_route_builder.geo import gcj02_to_wgs84, wgs84_to_gcj02
from xuhui_route_builder.models import (
    CandidateRoute,
    CoordinatePair,
    EntryPoint,
    RouteLocation,
    RouteNode,
)


def test_wgs84_gcj02_round_trip_stays_within_small_tolerance() -> None:
    gcj_lng, gcj_lat = wgs84_to_gcj02(121.445, 31.172)
    wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)

    assert abs(wgs_lng - 121.445) < 0.00001
    assert abs(wgs_lat - 31.172) < 0.00001


def test_entry_point_requires_both_coordinate_systems() -> None:
    entry = EntryPoint(
        entry_id="XH_ENT_0001",
        entry_name="徐汇滨江入口",
        entry_type="riverside_access",
        region_zone="徐汇滨江",
        lng_gcj02=121.45,
        lat_gcj02=31.17,
        lng_wgs84=121.445,
        lat_wgs84=31.172,
        source_url="https://example.com",
        confidence=5,
    )

    data = entry.model_dump()

    assert {"lng_gcj02", "lat_gcj02", "lng_wgs84", "lat_wgs84"}.issubset(data)


def test_candidate_route_polyline_keeps_both_coordinate_systems() -> None:
    shared = RouteLocation(name="徐汇滨江入口", location_type="riverside_access", lng_gcj02=121.45, lat_gcj02=31.17, source_url="https://example.com")
    route = CandidateRoute(
        route_id="XH_RUN_3K_0001",
        route_name="徐汇滨江舒心跑",
        route_mode="run",
        route_shape="strict_loop",
        target_distance_m=3000,
        actual_distance_m=3050,
        duration_s=1200,
        start_entry_id="XH_ENT_0001",
        end_entry_id="XH_ENT_0001",
        start_location=shared,
        end_location=shared,
        ordered_nodes=[RouteNode(node_name=shared.name, lng_gcj02=shared.lng_gcj02, lat_gcj02=shared.lat_gcj02), RouteNode(node_name=shared.name, lng_gcj02=shared.lng_gcj02, lat_gcj02=shared.lat_gcj02)],
        amenity_ids=[],
        region_zone="徐汇滨江",
        polyline_gcj02=[
            CoordinatePair(
                lng_gcj02=121.45, lat_gcj02=31.17, lng_wgs84=121.445, lat_wgs84=31.172
            )
        ],
        tags=["滨江"],
        source_method="seed",
    )

    first = route.polyline_gcj02[0].model_dump()

    assert first["lng_gcj02"] == 121.45
    assert first["lng_wgs84"] == 121.445
