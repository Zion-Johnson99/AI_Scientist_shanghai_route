from datetime import datetime, timezone

from xuhui_route_builder.exporters import build_feature_collection, build_route_catalog
from xuhui_route_builder.models import CandidateRoute, CoordinatePair, EntryPoint


def test_build_feature_collection_returns_geojson() -> None:
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

    collection = build_feature_collection([entry])

    assert collection["type"] == "FeatureCollection"
    assert collection["features"][0]["properties"]["entry_id"] == "XH_ENT_0001"
    assert collection["features"][0]["geometry"]["coordinates"] == [121.45, 31.17]


def test_build_route_catalog_keeps_score_placeholder() -> None:
    route = CandidateRoute(
        route_id="XH_RUN_3K_0001",
        route_name="徐汇滨江舒心跑",
        route_mode="run",
        target_distance_m=3000,
        actual_distance_m=3050,
        duration_s=1200,
        start_entry_id="XH_ENT_0001",
        end_entry_id="XH_ENT_0001",
        region_zone="徐汇滨江",
        polyline_gcj02=[
            CoordinatePair(lng_gcj02=121.45, lat_gcj02=31.17, lng_wgs84=121.445, lat_wgs84=31.172),
            CoordinatePair(lng_gcj02=121.46, lat_gcj02=31.16, lng_wgs84=121.455, lat_wgs84=31.162),
        ],
        tags=["滨江", "夜跑"],
        source_method="seed",
        geometry_source="audited_import",
        geometry_status="complete",
        validation_status="accepted",
        snap_ratio=0.99,
        network_source="osm-test",
        verified_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
        review_note="测试验收通过",
    )

    catalog = build_route_catalog([route])

    assert catalog[0]["route_id"] == "XH_RUN_3K_0001"
    assert catalog[0]["future_score"] is None
    assert "后续评分" in catalog[0]["score_note"]


def test_build_route_catalog_exports_navigation_and_preference_metadata() -> None:
    route = CandidateRoute(
        route_id="XH_WALK_REAL_0001",
        route_name="衡复音乐街区 Citywalk",
        route_mode="walk",
        target_distance_m=2600,
        actual_distance_m=2600,
        duration_s=2080,
        start_entry_id="XH_ENT_0011",
        end_entry_id="XH_ENT_0012",
        region_zone="衡复风貌区",
        polyline_gcj02=[
            CoordinatePair(lng_gcj02=121.446, lat_gcj02=31.205, lng_wgs84=121.441, lat_wgs84=31.207),
            CoordinatePair(lng_gcj02=121.4387, lat_gcj02=31.2077, lng_wgs84=121.4337, lat_wgs84=31.2097),
        ],
        tags=["音乐", "历史建筑"],
        source_method="real_route_seed",
        geometry_source="amap_direction",
        geometry_status="complete",
        source_level="A",
        waypoint_names=["衡山路8号", "东平路", "上海音乐学院"],
        nearby_pois=[{"poi_id": "XH_POI_0001", "poi_type": "coffee", "poi_name": "咖啡", "distance_m": 80}],
        preference_hits=["coffee"],
        validation_status="accepted",
        snap_ratio=0.99,
        network_source="osm-test",
        verified_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
        review_note="测试验收通过",
        raw_response_paths=["raw/segment-1.json"],
    )

    catalog = build_route_catalog([route])

    assert catalog[0]["geometry_source"] == "amap_direction"
    assert catalog[0]["source_level"] == "A"
    assert catalog[0]["waypoint_names"] == ["衡山路8号", "东平路", "上海音乐学院"]
    assert catalog[0]["nearby_pois"][0]["poi_type"] == "coffee"
    assert catalog[0]["preference_hits"] == ["coffee"]
