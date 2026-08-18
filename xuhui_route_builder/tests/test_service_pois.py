from datetime import datetime, timezone

from xuhui_route_builder.models import (
    CandidateRoute,
    CoordinatePair,
    RouteLocation,
    RouteNode,
)
from xuhui_route_builder.service_pois import merge_verified_service_pois


def _accepted_route() -> CandidateRoute:
    start = RouteLocation(
        name="起点",
        location_type="public_space",
        lng_gcj02=121.44,
        lat_gcj02=31.18,
        source_url="https://example.com/start",
    )
    end = RouteLocation(
        name="终点",
        location_type="public_space",
        lng_gcj02=121.45,
        lat_gcj02=31.19,
        source_url="https://example.com/end",
    )
    return CandidateRoute(
        route_id="XH_WALK_0001",
        route_name="测试路线",
        route_mode="walk",
        route_shape="one_way",
        target_distance_m=1500,
        actual_distance_m=1500,
        duration_s=900,
        start_entry_id="start",
        end_entry_id="end",
        start_location=start,
        end_location=end,
        ordered_nodes=[
            RouteNode(node_name="起点", lng_gcj02=121.44, lat_gcj02=31.18),
            RouteNode(node_name="终点", lng_gcj02=121.45, lat_gcj02=31.19),
        ],
        amenity_ids=[],
        region_zone="徐汇区",
        polyline_gcj02=[
            CoordinatePair(
                lng_gcj02=121.44, lat_gcj02=31.18, lng_wgs84=121.435, lat_wgs84=31.182
            ),
            CoordinatePair(
                lng_gcj02=121.45, lat_gcj02=31.19, lng_wgs84=121.445, lat_wgs84=31.192
            ),
        ],
        source_method="amap_seed",
        geometry_source="amap_direction",
        geometry_status="complete",
        validation_status="accepted",
        snap_ratio=0.99,
        network_source="OSM 2026-08-17",
        verified_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
        review_note="验收通过",
        raw_response_paths=["data/raw/amap/walking.json"],
        source_accessed_at="2026-08-17",
        waypoint_names=["起点", "终点"],
    )


def test_merge_service_pois_publishes_only_open_verified_records() -> None:
    records = [
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "B001",
            "source_id": "amap:B001",
            "poi_name": "沿线咖啡",
            "poi_type": "coffee",
            "lng": 121.445,
            "lat": 31.185,
            "coordinate_system": "GCJ02",
            "source": "AMap cache",
            "query_time": "2026-08-17T08:00:00+08:00",
            "open_status": "08:00-22:00",
            "distance_to_route_m": 42,
            "verification_status": "verified",
            "evidence_path": "data/raw/amap/place.json",
        },
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "B002",
            "source_id": "amap:B002",
            "poi_name": "暂停营业厕所",
            "poi_type": "toilet",
            "lng": 121.446,
            "lat": 31.186,
            "coordinate_system": "GCJ02",
            "source": "AMap cache",
            "open_status": "暂停营业",
            "distance_to_route_m": 30,
            "verification_status": "verified",
        },
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "node/3",
            "source_id": "osm:node:3",
            "poi_name": "状态未知便利店",
            "poi_type": "convenience",
            "lng": 121.447,
            "lat": 31.187,
            "coordinate_system": "WGS84",
            "source": "OpenStreetMap",
            "open_status": "unknown",
            "distance_to_route_m": 20,
            "verification_status": "needs_review",
        },
    ]

    routes, feature_collection, report = merge_verified_service_pois(
        [_accepted_route()], [{"records": records}]
    )

    assert routes[0].amenity_ids == ["amap:B001"]
    assert routes[0].preference_hits == ["coffee"]
    assert routes[0].nearby_pois[0]["poi_name"] == "沿线咖啡"
    assert [
        feature["properties"]["poi_id"] for feature in feature_collection["features"]
    ] == ["amap:B001"]
    assert report["excluded"] == {
        "unverified": 1,
        "closed": 1,
        "unpublished_route": 0,
        "invalid": 0,
    }
