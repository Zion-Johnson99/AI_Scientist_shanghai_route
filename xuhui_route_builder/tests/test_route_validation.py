from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuhui_route_builder.models import CandidateRoute, CoordinatePair, RouteLocation, RouteNode
from xuhui_route_builder.validation import (
    OverpassClient,
    build_overpass_query,
    compute_snap_ratio,
    compute_route_inside_ratio,
    find_duplicate_routes,
    parse_overpass_segments,
    polyline_length_m,
    validate_candidate,
    validate_amap_raw_evidence,
)


def test_build_overpass_query_uses_wgs84_bbox_and_complete_nodes() -> None:
    route = _route([_point(121.44, 31.18), _point(121.442, 31.181)])

    query = build_overpass_query(route, margin_m=50)

    assert 'way["highway"]' in query
    assert "(._;>;);" in query
    assert "121.44" in query and "31.18" in query
    assert "121.445" not in query  # GCJ-02 longitude must not define the bbox.


def _point(lng: float, lat: float) -> CoordinatePair:
    return CoordinatePair(lng_gcj02=lng + 0.005, lat_gcj02=lat - 0.002, lng_wgs84=lng, lat_wgs84=lat)


def _route(
    points: list[CoordinatePair],
    *,
    route_id: str = "route",
    route_mode: str = "bike",
    distance_m: int | None = None,
) -> CandidateRoute:
    measured = round(polyline_length_m(points)) if distance_m is None else distance_m
    is_loop = len(points) >= 2 and points[0] == points[-1]
    start = RouteLocation(name="测试路线入口", location_type="public_space", lng_gcj02=points[0].lng_gcj02, lat_gcj02=points[0].lat_gcj02, source_url="https://example.com/start")
    end = RouteLocation(name="测试路线入口" if is_loop else "测试路线终点", location_type="public_space", lng_gcj02=points[-1].lng_gcj02, lat_gcj02=points[-1].lat_gcj02, source_url="https://example.com/end")
    return CandidateRoute(
        route_id=route_id,
        route_name="徐汇测试路线",
        route_mode=route_mode,
        route_shape="strict_loop" if is_loop else "one_way",
        target_distance_m=measured,
        actual_distance_m=measured,
        duration_s=300,
        start_entry_id="start",
        end_entry_id="end",
        start_location=start,
        end_location=end,
        ordered_nodes=[RouteNode(node_name=start.name, lng_gcj02=start.lng_gcj02, lat_gcj02=start.lat_gcj02), RouteNode(node_name=end.name, lng_gcj02=end.lng_gcj02, lat_gcj02=end.lat_gcj02)],
        amenity_ids=[],
        region_zone="徐汇区",
        polyline_gcj02=points,
        source_method="amap_segmented_direction",
        source_accessed_at="2026-08-13",
        geometry_source="amap_direction",
        geometry_status="complete",
        raw_response_paths=["raw/segment.json"],
        waypoint_names=["测试路线入口", "测试路线终点"],
    )


def _overpass() -> dict:
    return {
        "elements": [
            {"type": "node", "id": 1, "lon": 121.44, "lat": 31.18},
            {"type": "node", "id": 2, "lon": 121.441, "lat": 31.18},
            {"type": "node", "id": 3, "lon": 121.442, "lat": 31.18},
            {"type": "node", "id": 4, "lon": 121.443, "lat": 31.18},
            {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "residential"}},
            {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "footway"}},
            {"type": "way", "id": 12, "nodes": [3, 4], "tags": {"highway": "path", "bicycle": "yes"}},
        ]
    }


def test_parse_overpass_segments_applies_mode_access_rules() -> None:
    walk = parse_overpass_segments(_overpass(), "walk")
    bike = parse_overpass_segments(_overpass(), "bike")

    assert len(walk) == 3
    assert len(bike) == 3

    blocked = _overpass()
    blocked["elements"][4]["tags"] = {"highway": "residential", "foot": "private"}
    blocked["elements"][6]["tags"] = {"highway": "steps", "bicycle": "yes"}
    blocked["elements"][5]["tags"] = {"highway": "footway", "bicycle": "no"}
    assert len(parse_overpass_segments(blocked, "run")) == 2
    assert len(parse_overpass_segments(blocked, "bike")) == 1


@pytest.mark.parametrize("access", ["no", "private"])
def test_parse_overpass_segments_rejects_general_access_denials(access: str) -> None:
    payload = _overpass()
    payload["elements"][4]["tags"]["access"] = access
    assert len(parse_overpass_segments(payload, "walk")) == 2
    assert len(parse_overpass_segments(payload, "bike")) == 2


def test_parse_overpass_segments_rejects_lifecycle_and_unknown_highways() -> None:
    payload = _overpass()
    payload["elements"][4]["tags"] = {"highway": "construction", "construction": "residential"}
    payload["elements"][5]["tags"] = {"highway": "raceway", "bicycle": "yes"}
    payload["elements"][6]["tags"] = {"highway": "proposed", "proposed": "cycleway", "bicycle": "yes"}
    assert parse_overpass_segments(payload, "walk") == []
    assert parse_overpass_segments(payload, "bike") == []


@pytest.mark.parametrize("bicycle", ["yes", "designated", "permissive"])
def test_bike_accepts_explicitly_allowed_paths(bicycle: str) -> None:
    payload = _overpass()
    payload["elements"][5]["tags"]["bicycle"] = bicycle
    assert len(parse_overpass_segments(payload, "bike")) == 3


def test_snap_ratio_samples_long_segments_every_twenty_metres() -> None:
    points = [_point(121.44, 31.18), _point(121.442, 31.18)]
    segments = parse_overpass_segments(_overpass(), "walk")
    assert compute_snap_ratio(points, segments, tolerance_m=20) == 1.0
    shifted = [_point(121.44, 31.181), _point(121.442, 31.181)]
    assert compute_snap_ratio(shifted, segments, tolerance_m=20) == 0.0
    assert compute_snap_ratio(points, []) == 0.0


def test_validate_candidate_accepts_only_complete_supported_geometry() -> None:
    points = [_point(121.44, 31.18), _point(121.441, 31.18)]
    route = _route(points)
    checked = validate_candidate(route, _overpass(), datetime(2026, 7, 11, tzinfo=timezone.utc), "osm-test")

    assert checked.validation_status == "accepted"
    assert checked.snap_ratio == 1.0
    assert checked.network_source == "osm-test"
    assert checked.is_publishable()


def test_validate_candidate_uses_twenty_five_metre_urban_snap_tolerance() -> None:
    points = [_point(121.44, 31.1802), _point(121.441, 31.1802)]
    route = _route(points)

    checked = validate_candidate(route, _overpass(), datetime(2026, 7, 11, tzinfo=timezone.utc), "osm-test")

    assert checked.validation_status == "accepted"
    assert checked.snap_ratio == 1.0


def test_validate_candidate_reviews_target_distance_mismatch() -> None:
    points = [_point(121.44, 31.18), _point(121.441, 31.18)]
    route = _route(points).model_copy(update={"target_distance_m": 1000})

    checked = validate_candidate(route, _overpass(), datetime(2026, 7, 11, tzinfo=timezone.utc), "osm-test")

    assert checked.validation_status == "needs_review"
    assert "目标距离" in checked.review_note


def test_validate_candidate_requires_endpoints_and_ninety_percent_inside_xuhui() -> None:
    boundary = [[121.439, 31.179], [121.443, 31.179], [121.443, 31.181], [121.439, 31.181], [121.439, 31.179]]
    inside_route = _route([_point(121.44, 31.18), _point(121.442, 31.18)])
    outside_endpoint = _route([_point(121.44, 31.18), _point(121.444, 31.18)])

    assert compute_route_inside_ratio(inside_route.polyline_gcj02, [boundary]) == 1.0
    checked = validate_candidate(
        outside_endpoint,
        _overpass(),
        datetime(2026, 7, 11, tzinfo=timezone.utc),
        "osm-test",
        boundary_polygons=[boundary],
    )

    assert checked.validation_status == "needs_review"
    assert checked.route_inside_ratio is not None and checked.route_inside_ratio < 0.9
    assert "起点或终点位于徐汇区外" in checked.review_note
    assert "区内比例" in checked.review_note


def test_validate_amap_raw_evidence_requires_real_successful_direction_response(tmp_path: Path) -> None:
    points = [_point(121.44, 31.18), _point(121.441, 31.18)]
    route = _route(points)
    raw_dir = tmp_path / "data" / "raw" / "amap"
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "bicycling_v2_abc.json"
    raw_path.write_text(
        json.dumps({
            "status": "1",
            "route": {"paths": [{
                "distance": str(route.actual_distance_m),
                "steps": [{"polyline": "121.445,31.178;121.446,31.178"}],
            }]},
        }),
        encoding="utf-8",
    )
    route = route.model_copy(update={"raw_response_paths": [str(raw_path)], "waypoint_names": ["起点", "终点"]})

    assert validate_amap_raw_evidence(route, tmp_path) == []

    raw_path.write_text(json.dumps({"status": "0", "route": {"paths": []}}), encoding="utf-8")
    failures = validate_amap_raw_evidence(route, tmp_path)
    assert any("status" in failure for failure in failures)


def test_validate_amap_raw_evidence_rejects_missing_or_outside_paths(tmp_path: Path) -> None:
    route = _route([_point(121.44, 31.18), _point(121.441, 31.18)]).model_copy(
        update={"raw_response_paths": [str(tmp_path / "forged.json")]}
    )

    failures = validate_amap_raw_evidence(route, tmp_path)

    assert any("原始数据目录" in failure for failure in failures)


@pytest.mark.parametrize("failure", ["missing_osm", "low_snap", "distance_error", "zero_duration"])
def test_validate_candidate_sends_unverified_routes_to_review(failure: str) -> None:
    points = [_point(121.44, 31.18), _point(121.441, 31.18)]
    route = _route(points)
    payload = _overpass()
    if failure == "missing_osm":
        payload = {"elements": []}
    elif failure == "low_snap":
        route = _route([_point(121.44, 31.181), _point(121.441, 31.181)])
    elif failure == "distance_error":
        route = _route(points, distance_m=10)
    else:
        route = route.model_copy(update={"duration_s": 0})

    checked = validate_candidate(route, payload, datetime(2026, 7, 11, tzinfo=timezone.utc), "osm-test")
    assert checked.validation_status == "needs_review"
    assert checked.review_note
    assert not checked.is_publishable()


@pytest.mark.parametrize(
    ("payload", "verified_at", "network_version"),
    [
        ({"elements": [{"type": "way", "nodes": ["bad", 2], "tags": {"highway": "residential"}}]}, datetime.now(timezone.utc), "osm"),
        (_overpass(), datetime(2026, 7, 11), "osm"),
        (_overpass(), datetime.now(timezone.utc), "   "),
    ],
)
def test_validate_candidate_stably_reviews_invalid_validation_inputs(payload, verified_at, network_version) -> None:
    route = _route([_point(121.44, 31.18), _point(121.441, 31.18)])
    checked = validate_candidate(route, payload, verified_at, network_version)
    assert checked.validation_status == "needs_review"
    assert checked.review_note


def test_find_duplicate_routes_treats_reverse_and_densified_backbone_as_same() -> None:
    base = [_point(121.44, 31.18), _point(121.441, 31.18), _point(121.442, 31.18)]
    reverse = list(reversed(base))
    dense = [_point(121.44, 31.18), _point(121.4405, 31.18), _point(121.441, 31.18), _point(121.442, 31.18)]
    unique = [_point(121.44, 31.18), _point(121.44, 31.181)]
    duplicates = find_duplicate_routes(
        [_route(base, route_id="base"), _route(reverse, route_id="reverse"), _route(dense, route_id="dense"), _route(unique, route_id="unique")]
    )
    assert duplicates == {"base": ["reverse", "dense"]}


def test_find_duplicate_routes_ignores_identical_geometry_across_modes() -> None:
    points = [_point(121.44, 31.18), _point(121.441, 31.18), _point(121.442, 31.18)]

    duplicates = find_duplicate_routes(
        [
            _route(points, route_id="walk", route_mode="walk"),
            _route(points, route_id="run", route_mode="run"),
            _route(points, route_id="bike", route_mode="bike"),
        ]
    )

    assert duplicates == {}


def test_duplicate_routes_support_closed_loop_rotation_and_high_overlap() -> None:
    loop = [_point(121.44, 31.18), _point(121.441, 31.18), _point(121.441, 31.181), _point(121.44, 31.18)]
    rotated = [loop[1], loop[2], loop[0], loop[1]]
    mostly_same = [_point(121.44, 31.18), _point(121.441, 31.18), _point(121.441, 31.1811), _point(121.44, 31.18)]
    duplicates = find_duplicate_routes(
        [_route(loop, route_id="loop"), _route(rotated, route_id="rotated"), _route(mostly_same, route_id="overlap")]
    )
    assert duplicates == {"loop": ["rotated", "overlap"]}


def test_duplicate_routes_groups_transitive_similarity_chain(monkeypatch) -> None:
    overlaps = {frozenset({"a", "b"}), frozenset({"b", "c"})}
    monkeypatch.setattr(
        "xuhui_route_builder.validation._bidirectional_overlap",
        lambda first, second, tolerance: 1.0 if frozenset({first.route_id, second.route_id}) in overlaps else 0.0,
    )
    duplicates = find_duplicate_routes(
        [
            _route([_point(121.4400, 31.18), _point(121.4410, 31.18)], route_id="a"),
            _route([_point(121.4400, 31.19), _point(121.4410, 31.19)], route_id="b"),
            _route([_point(121.4400, 31.20), _point(121.4410, 31.20)], route_id="c"),
        ],
    )

    assert duplicates == {"a": ["b", "c"]}


def test_overpass_client_caches_and_wraps_request_errors(tmp_path) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"elements": []}

    class Session:
        calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    client = OverpassClient(cache_dir=tmp_path, session=session)
    assert client.query("[out:json];way(1);out;") == {"elements": []}
    assert client.query("[out:json];way(1);out;") == {"elements": []}
    assert session.calls == 1

    class BrokenSession:
        def post(self, *args, **kwargs):
            raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="Overpass request failed"):
        OverpassClient(cache_dir=tmp_path / "broken", session=BrokenSession()).query("new-query")

    class GetSession(Session):
        def get(self, *args, **kwargs):
            self.calls += 1
            assert kwargs["params"]["data"] == "get-query"
            return Response()

    assert OverpassClient(cache_dir=tmp_path / "get", session=GetSession(), method="get").query("get-query") == {
        "elements": []
    }


def test_overpass_client_sends_meaningful_user_agent(tmp_path) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"elements": []}

    class Session:
        def post(self, *args, **kwargs):
            assert "XuhuiRouteBuilder" in kwargs["headers"]["User-Agent"]
            assert "github.com/Zion-Johnson99/AI_Scientist_shanghai_route" in kwargs["headers"]["User-Agent"]
            return Response()

    client = OverpassClient(cache_dir=tmp_path, session=Session())

    assert client.query("[out:json];node(1);out;") == {"elements": []}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": "put"},
        {"timeout": 0},
        {"endpoint": "http://overpass.example/api"},
    ],
)
def test_overpass_client_rejects_unsafe_configuration(tmp_path, kwargs) -> None:
    with pytest.raises(ValueError):
        OverpassClient(cache_dir=tmp_path, **kwargs)


def test_overpass_client_reports_corrupt_cache_with_query_hash(tmp_path) -> None:
    query = "corrupt"
    digest = __import__("hashlib").sha256(query.encode()).hexdigest()
    tmp_path.joinpath(f"{digest}.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(RuntimeError, match=digest):
        OverpassClient(cache_dir=tmp_path).query(query)
