from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from xuhui_route_builder.exporters import build_route_catalog, build_route_feature_collection
from xuhui_route_builder.models import CandidateRoute, CoordinatePair, RouteNode, RouteSeed


def _route(route_id: str, validation_status: str) -> CandidateRoute:
    return CandidateRoute(
        route_id=route_id,
        route_name="真实路线",
        route_mode="walk",
        target_distance_m=1000,
        actual_distance_m=1020,
        duration_s=800,
        start_entry_id="start",
        end_entry_id="end",
        region_zone="徐汇区",
        polyline_gcj02=[
            CoordinatePair(lng_gcj02=121.44, lat_gcj02=31.19, lng_wgs84=121.435, lat_wgs84=31.192),
            CoordinatePair(lng_gcj02=121.45, lat_gcj02=31.18, lng_wgs84=121.445, lat_wgs84=31.182),
        ],
        source_method="amap_segmented_direction",
        source_accessed_at="2026-08-13",
        geometry_source="amap_direction",
        geometry_status="complete",
        validation_status=validation_status,
        snap_ratio=0.99,
        network_source="osm-2026-07-11",
        verified_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
        review_note="路网检查通过",
        raw_response_paths=["raw/segment-1.json"],
        waypoint_names=["真实路线入口", "真实路线终点"],
    )


def test_route_seed_supports_structured_nodes_and_evidence_fields() -> None:
    node = RouteNode(
        node_name="上海植物园一号门",
        poi_id="B001",
        lng_gcj02=121.4382,
        lat_gcj02=31.1493,
        lng_wgs84=121.4332,
        lat_wgs84=31.1513,
    )
    seed = RouteSeed(
        seed_id="botanical-walk",
        route_name="植物园步行线",
        route_mode="walk",
        distance_level="2km",
        target_distance_m=2000,
        region_zone="上海植物园",
        start_hint="一号门",
        end_hint="一号门",
        reason="官方游览节点",
        source_name="上海植物园",
        source_url="https://www.shbg.org/",
        source_accessed_at="2026-08-13",
        confidence="高",
        ordered_nodes=[node, RouteNode(node_name="上海植物园三号门", poi_id="B003")],
        allowed_modes=["walk", "run"],
        source_level="A",
        evidence_note="节点来自官方导览资料",
        access_restrictions=["开放时间内通行"],
    )

    assert seed.ordered_nodes[0].poi_id == "B001"
    assert seed.allowed_modes == ["walk", "run"]
    assert seed.source_level == "A"
    assert seed.source_accessed_at.isoformat() == "2026-08-13"
    assert seed.evidence_note
    assert seed.access_restrictions == ["开放时间内通行"]


def test_candidate_route_defaults_to_unverified_geometry() -> None:
    route = CandidateRoute(
        route_id="pending",
        route_name="待生成路线",
        route_mode="walk",
        target_distance_m=1000,
        actual_distance_m=0,
        duration_s=0,
        start_entry_id="start",
        end_entry_id="end",
        region_zone="徐汇区",
        polyline_gcj02=[],
        source_method="route_seed",
    )

    assert route.geometry_source == "not_generated"
    assert route.geometry_status == "not_generated"
    assert route.validation_status == "pending"
    assert route.snap_ratio is None
    assert route.raw_response_paths == []


def test_exporters_only_include_accepted_routes() -> None:
    accepted = _route("accepted", "accepted")
    pending = _route("pending", "pending")
    needs_review = _route("needs-review", "needs_review")

    features = build_route_feature_collection([accepted, pending, needs_review])
    catalog = build_route_catalog([accepted, pending, needs_review])

    assert [feature["properties"]["route_id"] for feature in features["features"]] == ["accepted"]
    assert [item["route_id"] for item in catalog] == ["accepted"]
    assert catalog[0]["geometry_status"] == "complete"
    assert catalog[0]["validation_status"] == "accepted"
    assert catalog[0]["raw_response_paths"] == ["raw/segment-1.json"]


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"geometry_status": "partial"}, "geometry_status"),
        ({"polyline_gcj02": []}, "polyline_gcj02"),
        ({"snap_ratio": 0.97}, "snap_ratio"),
        ({"network_source": None}, "network_source"),
        ({"verified_at": datetime(2026, 7, 11)}, "verified_at"),
        ({"review_note": ""}, "review_note"),
        ({"raw_response_paths": []}, "raw_response_paths"),
    ],
)
def test_accepted_route_rejects_incomplete_verification(update: dict, message: str) -> None:
    payload = _route("valid", "accepted").model_dump()
    payload.update(update)

    with pytest.raises(ValidationError, match=message):
        CandidateRoute(**payload)


def test_accepted_route_requires_two_distinct_coordinates() -> None:
    payload = _route("valid", "accepted").model_dump()
    payload["polyline_gcj02"] = [payload["polyline_gcj02"][0], payload["polyline_gcj02"][0]]

    with pytest.raises(ValidationError, match="distinct"):
        CandidateRoute(**payload)


def test_exporters_recheck_publishable_state_after_unvalidated_update() -> None:
    forged = _route("forged", "accepted").model_copy(update={"snap_ratio": 0.2})

    assert build_route_feature_collection([forged])["features"] == []
    assert build_route_catalog([forged]) == []


def test_route_without_start_waypoint_name_is_not_publishable() -> None:
    missing_name = _route("missing-name", "accepted").model_copy(update={"waypoint_names": []})

    assert missing_name.is_publishable() is False
    assert build_route_catalog([missing_name]) == []


@pytest.mark.parametrize(
    "node",
    [
        {"node_name": "无定位节点"},
        {"node_name": "缺纬度", "lng_gcj02": 121.4},
        {"node_name": "经度越界", "lng_gcj02": 181, "lat_gcj02": 31.2},
        {"node_name": "纬度越界", "lng_gcj02": 121.4, "lat_gcj02": 91},
    ],
)
def test_route_node_rejects_missing_partial_or_out_of_range_location(node: dict) -> None:
    with pytest.raises(ValidationError):
        RouteNode(**node)


def test_route_node_accepts_poi_id_without_coordinates() -> None:
    assert RouteNode(node_name="入口", poi_id="B001").poi_id == "B001"


def test_structured_seed_requires_two_nodes_and_matching_allowed_mode() -> None:
    payload = {
        "seed_id": "seed",
        "route_name": "路线",
        "route_mode": "walk",
        "distance_level": "1km",
        "target_distance_m": 1000,
        "region_zone": "徐汇区",
        "start_hint": "起点",
        "end_hint": "终点",
        "reason": "证据",
        "source_name": "官方",
        "source_url": "https://example.com",
        "source_accessed_at": "2026-08-13",
        "confidence": "高",
        "source_level": "A",
    }
    node = RouteNode(node_name="入口", poi_id="B001")

    with pytest.raises(ValidationError, match="ordered_nodes"):
        RouteSeed(**payload, ordered_nodes=[node], allowed_modes=["walk"])
    with pytest.raises(ValidationError, match="allowed_modes"):
        RouteSeed(**payload, ordered_nodes=[node, node], allowed_modes=["run"])
    with pytest.raises(ValidationError, match="partial"):
        RouteSeed(**payload, ordered_nodes=[], allowed_modes=["walk"])


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RouteNode(node_name="入口", poi_id="B001", legacy_field=True)


def test_candidate_source_level_uses_abc_scale() -> None:
    payload = _route("valid", "accepted").model_dump()
    payload["source_level"] = "official"

    with pytest.raises(ValidationError, match="source_level"):
        CandidateRoute(**payload)


@pytest.mark.parametrize("geometry_source", ["fake", "not_generated"])
def test_accepted_route_rejects_unapproved_geometry_source(geometry_source: str) -> None:
    payload = _route("invalid-source", "accepted").model_dump()
    payload["geometry_source"] = geometry_source

    with pytest.raises(ValidationError, match="geometry_source"):
        CandidateRoute(**payload)


def test_audited_import_can_be_accepted_without_amap_raw_responses() -> None:
    payload = _route("audited", "accepted").model_dump()
    payload["geometry_source"] = "audited_import"
    payload["raw_response_paths"] = []

    route = CandidateRoute(**payload)

    assert route.is_publishable()
    assert build_route_catalog([route])[0]["geometry_source"] == "audited_import"
