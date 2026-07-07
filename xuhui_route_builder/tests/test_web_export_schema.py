from pathlib import Path

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
        polyline_gcj02=[CoordinatePair(lng_gcj02=121.45, lat_gcj02=31.17, lng_wgs84=121.445, lat_wgs84=31.172)],
        tags=["滨江", "夜跑"],
        source_method="seed",
    )

    catalog = build_route_catalog([route])

    assert catalog[0]["route_id"] == "XH_RUN_3K_0001"
    assert catalog[0]["future_score"] is None
    assert "后续评分" in catalog[0]["score_note"]
