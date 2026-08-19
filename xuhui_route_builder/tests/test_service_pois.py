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
            "related_route_ids": ["XH_WALK_0001"],
            "poi_id": "B005",
            "source_id": "amap:B005",
            "poi_name": "公园开放入口",
            "poi_type": "park_gate",
            "lng": 121.444,
            "lat": 31.184,
            "coordinate_system": "GCJ02",
            "source": "AMap cache",
            "query_time": "2026-08-17T08:00:00+08:00",
            "open_status": "06:00-22:00",
            "distance_to_route_m": 20,
            "verification_status": "verified",
            "evidence_path": "data/raw/amap/place.json",
        },
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "B004",
            "source_id": "amap:B004",
            "poi_name": "远离路线的咖啡",
            "poi_type": "coffee",
            "lng": 121.47,
            "lat": 31.21,
            "coordinate_system": "GCJ02",
            "source": "AMap cache",
            "query_time": "2026-08-17T08:00:00+08:00",
            "open_status": "08:00-22:00",
            "distance_to_route_m": 10,
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

    assert routes[0].amenity_ids == ["amap:B001", "amap:B005"]
    assert routes[0].preference_hits == ["coffee", "park_gate"]
    assert routes[0].validation_status == "accepted"
    assert routes[0].nearby_pois[0]["poi_name"] == "沿线咖啡"
    assert routes[0].nearby_pois[0]["distance_m"] < 1
    assert [
        feature["properties"]["poi_id"] for feature in feature_collection["features"]
    ] == ["amap:B001", "amap:B005"]
    assert report["excluded"] == {
        "unverified": 1,
        "closed": 1,
        "unpublished_route": 0,
        "invalid": 0,
        "outside_corridor": 1,
    }


def test_merge_service_pois_keeps_route_accepted_with_one_verified_preference() -> None:
    record = {
        "route_id": "XH_WALK_0001",
        "poi_id": "B001",
        "source_id": "amap:B001",
        "poi_name": "沿线咖啡",
        "poi_type": "coffee",
        "lng": 121.445,
        "lat": 31.185,
        "coordinate_system": "GCJ02",
        "source": "AMap cache",
        "open_status": "08:00-22:00",
        "verification_status": "verified",
    }

    routes, feature_collection, report = merge_verified_service_pois(
        [_accepted_route()], [{"records": [record]}]
    )

    assert routes[0].validation_status == "accepted"
    assert routes[0].preference_hits == ["coffee"]
    assert routes[0].amenity_ids == ["amap:B001"]
    assert routes[0].nearby_pois[0]["poi_name"] == "沿线咖啡"
    assert len(feature_collection["features"]) == 1
    assert report["published_association_count"] == 1


def test_merge_service_pois_recomputes_document_pois_against_all_routes_of_mode() -> (
    None
):
    original = _accepted_route()
    old_route = original.model_copy(
        update={
            "polyline_gcj02": [
                point.model_copy(
                    update={
                        "lng_gcj02": point.lng_gcj02 + 0.02,
                        "lng_wgs84": point.lng_wgs84 + 0.02,
                    }
                )
                for point in original.polyline_gcj02
            ]
        }
    )
    new_route = original.model_copy(update={"route_id": "XH_WALK_0002"})
    record = {
        "route_id": "XH_WALK_0001",
        "poi_id": "B001",
        "source_id": "amap:B001",
        "poi_name": "重建后沿线咖啡",
        "poi_type": "coffee",
        "lng": 121.445,
        "lat": 31.185,
        "coordinate_system": "GCJ02",
        "source": "AMap cache",
        "open_status": "08:00-22:00",
        "verification_status": "verified",
    }

    routes, _, _ = merge_verified_service_pois(
        [old_route, new_route],
        [{"route_filter": {"route_mode": "walk"}, "records": [record]}],
    )

    by_id = {route.route_id: route for route in routes}
    assert by_id["XH_WALK_0001"].nearby_pois == []
    assert by_id["XH_WALK_0002"].nearby_pois[0]["poi_name"] == "重建后沿线咖啡"


def test_verified_park_gate_cache_is_reused_across_route_modes() -> None:
    record = {
        "route_id": "XH_BIKE_0061",
        "poi_id": "PARK-SHARED",
        "source_id": "amap:PARK-SHARED",
        "poi_name": "跨运动类型公园入口",
        "poi_type": "park_gate",
        "lng": 121.445,
        "lat": 31.185,
        "coordinate_system": "GCJ02",
        "source": "AMap entrance cache",
        "open_status": "07:00-21:00",
        "verification_status": "verified",
    }

    routes, _, _ = merge_verified_service_pois(
        [_accepted_route()],
        [{"metadata": {"route_mode": "bike"}, "records": [record]}],
    )

    assert routes[0].nearby_pois[0]["poi_name"] == "跨运动类型公园入口"


def test_same_physical_facility_is_deduplicated_across_source_ids() -> None:
    common = {
        "route_id": "XH_WALK_0001",
        "poi_name": "同一公园入口",
        "poi_type": "park_gate",
        "lng": 121.445,
        "lat": 31.185,
        "coordinate_system": "GCJ02",
        "source": "verified source",
        "open_status": "07:00-21:00",
        "verification_status": "verified",
    }
    first = {**common, "poi_id": "official:gate", "source_id": "official:gate"}
    second = {**common, "poi_id": "entry:gate", "source_id": "entry:gate"}

    routes, feature_collection, report = merge_verified_service_pois(
        [_accepted_route()], [{"records": [first, second]}]
    )

    assert routes[0].amenity_ids == ["official:gate"]
    assert len(feature_collection["features"]) == 1
    assert report["published_association_count"] == 1


def test_merge_service_pois_classifies_direct_and_nearby_park_gates() -> None:
    records = [
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "PARK-DIRECT",
            "source_id": "amap:PARK-DIRECT",
            "poi_name": "沿线公园入口",
            "poi_type": "park_gate",
            "lng": 121.4454,
            "lat": 31.1846,
            "coordinate_system": "GCJ02",
            "source": "AMap cache + 公园官方入口",
            "source_accessed_at": "2026-08-19T08:00:00+08:00",
            "open_status": "06:00-22:00",
            "verification_status": "verified",
            "evidence_path": "data/raw/amap/park-direct.json",
        },
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "PARK-NEARBY",
            "source_id": "amap:PARK-NEARBY",
            "poi_name": "邻近公园入口",
            "poi_type": "park_gate",
            "lng": 121.4461,
            "lat": 31.1839,
            "coordinate_system": "GCJ02",
            "source": "AMap cache + 公园官方入口",
            "source_accessed_at": "2026-08-19T08:00:00+08:00",
            "open_status": "06:00-22:00",
            "verification_status": "verified",
            "access_status": "verified_walkable",
            "evidence_path": "data/raw/amap/park-nearby.json",
        },
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "PARK-BLOCKED",
            "source_id": "amap:PARK-BLOCKED",
            "poi_name": "隔河公园入口",
            "poi_type": "park_gate",
            "lng": 121.4462,
            "lat": 31.1838,
            "coordinate_system": "GCJ02",
            "source": "AMap cache + 公园官方入口",
            "source_accessed_at": "2026-08-19T08:00:00+08:00",
            "open_status": "06:00-22:00",
            "verification_status": "verified",
            "access_status": "blocked",
            "evidence_path": "data/raw/amap/park-blocked.json",
        },
        {
            "route_id": "XH_WALK_0001",
            "poi_id": "PARK-FAR",
            "source_id": "amap:PARK-FAR",
            "poi_name": "远处公园入口",
            "poi_type": "park_gate",
            "lng": 121.447,
            "lat": 31.183,
            "coordinate_system": "GCJ02",
            "source": "AMap cache + 公园官方入口",
            "source_accessed_at": "2026-08-19T08:00:00+08:00",
            "open_status": "06:00-22:00",
            "verification_status": "verified",
            "access_status": "verified_walkable",
            "evidence_path": "data/raw/amap/park-far.json",
        },
    ]

    routes, feature_collection, report = merge_verified_service_pois(
        [_accepted_route()], [{"records": records}]
    )

    nearby = {item["poi_name"]: item for item in routes[0].nearby_pois}
    assert nearby["沿线公园入口"]["route_relation"] == "along_route"
    assert nearby["邻近公园入口"]["route_relation"] == "nearby"
    assert 100 < nearby["邻近公园入口"]["distance_m"] <= 200
    assert "隔河公园入口" not in nearby
    assert "远处公园入口" not in nearby
    assert routes[0].preference_hits == ["park_gate"]
    assert len(feature_collection["features"]) == 2
    assert report["excluded"]["blocked_access"] == 1
