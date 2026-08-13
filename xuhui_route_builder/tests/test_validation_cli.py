from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from xuhui_route_builder import cli
from xuhui_route_builder.models import CandidateRoute, CoordinatePair
from xuhui_route_builder.validation import polyline_length_m


def _candidate(
    index: int,
    *,
    route_mode: str = "walk",
    distance_m: int = 1500,
    source_level: str = "A",
    offset: float | None = None,
) -> CandidateRoute:
    latitude = 31.18 + (index * 0.002 if offset is None else offset)
    longitude_delta = distance_m / 95_000
    points = [
        CoordinatePair(lng_gcj02=121.445, lat_gcj02=latitude - 0.002, lng_wgs84=121.44, lat_wgs84=latitude),
        CoordinatePair(
            lng_gcj02=121.445 + longitude_delta,
            lat_gcj02=latitude - 0.002,
            lng_wgs84=121.44 + longitude_delta,
            lat_wgs84=latitude,
        ),
    ]
    distance = round(polyline_length_m(points))
    return CandidateRoute(
        route_id=f"route-{index}", route_name=f"路线{index}", route_mode=route_mode,
        target_distance_m=distance, actual_distance_m=distance, duration_s=300,
        start_entry_id="start", end_entry_id="end", region_zone="徐汇区", polyline_gcj02=points,
        source_method="amap_segmented_direction", geometry_source="amap_direction", geometry_status="complete",
        source_accessed_at="2026-08-13",
        raw_response_paths=[f"raw/{index}.json"], source_level=source_level,
    )


def _catalog_candidates() -> list[CandidateRoute]:
    specifications = {
        "walk": (1500, 2500, 4000),
        "run": (4000, 7000, 12000),
        "bike": (7000, 15000, 25000),
    }
    candidates = []
    index = 0
    for mode, distances in specifications.items():
        for distance in distances:
            for _ in range(10):
                candidates.append(_candidate(index, route_mode=mode, distance_m=distance))
                index += 1
    return candidates


def _payload(route: CandidateRoute, *, shifted: bool = False) -> dict:
    first, second = route.polyline_gcj02
    shift = 0.001 if shifted else 0
    return {"osm3s": {"timestamp_osm_base": "2026-07-12T00:00:00Z"}, "elements": [
        {"type": "node", "id": 1, "lon": first.lng_wgs84, "lat": first.lat_wgs84 + shift},
        {"type": "node", "id": 2, "lon": second.lng_wgs84, "lat": second.lat_wgs84 + shift},
        {"type": "way", "id": 3, "nodes": [1, 2], "tags": {"highway": "residential"}},
    ]}


class _Client:
    def __init__(
        self,
        candidates: list[CandidateRoute],
        *,
        low_index: int | None = None,
        low_indices: set[int] | None = None,
        error_index: int | None = None,
    ):
        self.candidates = candidates
        self.calls = 0
        self.low_indices = set(low_indices or set())
        if low_index is not None:
            self.low_indices.add(low_index)
        self.error_index = error_index

    def query(self, query: str) -> dict:
        index = self.calls
        self.calls += 1
        if index == self.error_index:
            raise RuntimeError("offline")
        return _payload(self.candidates[index], shifted=index in self.low_indices)


def _prepare(tmp_path, candidates: list[CandidateRoute]) -> None:
    interim = tmp_path / "data" / "interim"
    interim.mkdir(parents=True)
    raw_dir = tmp_path / "data" / "raw" / "amap"
    raw_dir.mkdir(parents=True)
    prepared = []
    for index, route in enumerate(candidates):
        endpoint = "bicycling_v2" if route.route_mode in {"bike", "bike_assist"} else "walking_v2"
        raw_path = raw_dir / f"{endpoint}_{index}.json"
        polyline = ";".join(f"{point.lng_gcj02},{point.lat_gcj02}" for point in route.polyline_gcj02)
        raw_path.write_text(json.dumps({
            "status": "1",
            "route": {"paths": [{"distance": str(route.actual_distance_m), "steps": [{"polyline": polyline}]}]},
        }), encoding="utf-8")
        prepared.append(route.model_copy(update={
            "raw_response_paths": [str(raw_path)],
            "waypoint_names": ["起点", "终点"],
        }))
    (interim / "pilot_candidates.json").write_text(
        json.dumps([route.model_dump(mode="json") for route in prepared], ensure_ascii=False), encoding="utf-8"
    )
    web = tmp_path / "data" / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "xuhui_boundary.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"district_name": "徐汇区"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [121.0, 30.9], [122.0, 30.9], [122.0, 31.5], [121.0, 31.5], [121.0, 30.9]
            ]]},
        }],
    }), encoding="utf-8")


def test_validate_routes_publishes_only_when_all_ninety_are_accepted_and_balanced(tmp_path) -> None:
    candidates = _catalog_candidates()
    _prepare(tmp_path, candidates)

    result = cli.validate_routes(tmp_path, _Client(candidates), datetime(2026, 7, 12, tzinfo=timezone.utc))

    assert len(result) == 90
    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert (report["accepted_count"], report["review_count"], report["rejected_count"]) == (90, 0, 0)
    assert report["mode_counts"] == {"walk": 30, "run": 30, "bike": 30}
    assert report["distance_band_counts"] == {
        "walk": {"short": 10, "medium": 10, "long": 10},
        "run": {"short": 10, "medium": 10, "long": 10},
        "bike": {"short": 10, "medium": 10, "long": 10},
    }
    assert report["network_version"] == "2026-07-12T00:00:00Z"
    assert len(json.loads((tmp_path / "data/web/route_catalog.json").read_text(encoding="utf-8"))) == 90


def test_validate_routes_preserves_web_files_when_one_route_needs_review(tmp_path) -> None:
    candidates = _catalog_candidates()
    _prepare(tmp_path, candidates)
    web = tmp_path / "data/web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "xuhui_routes.geojson").write_text("old geojson", encoding="utf-8")
    (web / "route_catalog.json").write_text("old catalog", encoding="utf-8")

    with pytest.raises(RuntimeError, match="existing web files preserved"):
        cli.validate_routes(
            tmp_path,
            _Client(candidates, low_index=3),
            datetime(2026, 7, 12, tzinfo=timezone.utc),
        )

    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["published_count"] == 0
    assert len(report["routes"]) == 90
    assert (web / "xuhui_routes.geojson").read_text(encoding="utf-8") == "old geojson"
    assert (web / "route_catalog.json").read_text(encoding="utf-8") == "old catalog"


@pytest.mark.parametrize(
    ("mode", "distance_m", "expected_band"),
    [
        ("walk", 1000, "short"), ("walk", 1999, "short"), ("walk", 2000, "medium"),
        ("walk", 3499, "medium"), ("walk", 3500, "long"), ("walk", 5000, "long"),
        ("run", 3000, "short"), ("run", 5000, "medium"), ("run", 10000, "long"), ("run", 15000, "long"),
        ("bike", 5000, "short"), ("bike", 10000, "medium"), ("bike", 20000, "long"), ("bike", 30000, "long"),
    ],
)
def test_distance_band_boundaries_are_non_overlapping(mode, distance_m, expected_band) -> None:
    assert cli._distance_band(mode, distance_m) == expected_band


@pytest.mark.parametrize(
    ("mode", "distance_m"),
    [("walk", 999), ("walk", 5001), ("run", 2999), ("run", 15001), ("bike", 4999), ("bike", 30001)],
)
def test_distance_band_rejects_out_of_range_distances(mode, distance_m) -> None:
    assert cli._distance_band(mode, distance_m) is None


@pytest.mark.parametrize("failure", ["low_snap", "overpass_error"])
def test_validate_routes_excludes_failed_network_check_and_reports_context(tmp_path, failure: str) -> None:
    candidates = _catalog_candidates()
    _prepare(tmp_path, candidates)
    web = tmp_path / "data/web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "xuhui_routes.geojson").write_text("old geojson", encoding="utf-8")
    (web / "route_catalog.json").write_text("old catalog", encoding="utf-8")
    client = _Client(candidates, low_index=2 if failure == "low_snap" else None, error_index=2 if failure == "overpass_error" else None)

    with pytest.raises(RuntimeError, match="existing web files preserved"):
        cli.validate_routes(tmp_path, client, datetime(2026, 7, 12, tzinfo=timezone.utc))

    assert (web / "route_catalog.json").read_text(encoding="utf-8") == "old catalog"
    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["published_count"] == 0
    if failure == "overpass_error":
        assert report["failures"][0]["route_id"] == "route-2"
        assert report["failures"][0]["mode"] == "walk"
        assert report["failures"][0]["type"] == "RuntimeError"
        assert report["failures"][0]["traceback"]


def test_validate_routes_keeps_best_source_and_downgrades_duplicates(tmp_path) -> None:
    candidates = _catalog_candidates()
    candidates[0] = _candidate(0, route_mode="walk", distance_m=1500, source_level="C")
    candidates[1] = candidates[0].model_copy(update={
        "route_id": "route-1",
        "route_name": "路线1",
        "source_level": "A",
        "raw_response_paths": ["raw/1.json"],
    })
    _prepare(tmp_path, candidates)

    with pytest.raises(RuntimeError, match="existing web files preserved"):
        cli.validate_routes(tmp_path, _Client(candidates), datetime(2026, 7, 12, tzinfo=timezone.utc))

    validated = json.loads((tmp_path / "data/processed/pilot_validated.json").read_text(encoding="utf-8"))
    by_id = {route["route_id"]: route for route in validated}
    assert by_id["route-1"]["validation_status"] == "accepted"
    assert by_id["route-0"]["validation_status"] == "needs_review"
    assert "重复" in by_id["route-0"]["review_note"]
    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["published_count"] == 0


def test_validate_routes_rolls_back_both_web_files_on_publish_failure(tmp_path, monkeypatch) -> None:
    candidates = _catalog_candidates()
    _prepare(tmp_path, candidates)
    web = tmp_path / "data/web"
    web.mkdir(parents=True, exist_ok=True)
    first, second = web / "xuhui_routes.geojson", web / "route_catalog.json"
    first.write_text("old geojson", encoding="utf-8")
    second.write_text("old catalog", encoding="utf-8")
    real_write = cli._atomic_write_json

    def fail_catalog(path, payload):
        if path == second:
            raise OSError("disk full")
        return real_write(path, payload)

    monkeypatch.setattr(cli, "_atomic_write_json", fail_catalog)
    with pytest.raises(RuntimeError, match="publish transaction failed"):
        cli.validate_routes(tmp_path, _Client(candidates), datetime(2026, 7, 12, tzinfo=timezone.utc))
    assert first.read_text(encoding="utf-8") == "old geojson"
    assert second.read_text(encoding="utf-8") == "old catalog"
    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["failures"][-1]["stage"] == "web_publish"


def test_validate_routes_rolls_back_web_and_records_failed_when_success_report_write_fails(tmp_path, monkeypatch) -> None:
    candidates = _catalog_candidates()
    _prepare(tmp_path, candidates)
    web = tmp_path / "data/web"
    web.mkdir(parents=True, exist_ok=True)
    first, second = web / "xuhui_routes.geojson", web / "route_catalog.json"
    first.write_text("old geojson", encoding="utf-8")
    second.write_text("old catalog", encoding="utf-8")
    real_write = cli._atomic_write_json

    def fail_success_report(path, payload):
        if path.name == "route_validation_report.json" and payload.get("batch_status") == "succeeded":
            raise OSError("report disk full")
        return real_write(path, payload)

    monkeypatch.setattr(cli, "_atomic_write_json", fail_success_report)
    with pytest.raises(RuntimeError, match="success report"):
        cli.validate_routes(tmp_path, _Client(candidates), datetime(2026, 7, 12, tzinfo=timezone.utc))
    assert first.read_text(encoding="utf-8") == "old geojson"
    assert second.read_text(encoding="utf-8") == "old catalog"
    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["failures"][-1]["stage"] == "success_report"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "exactly 90"),
        ([_candidate(index).model_dump(mode="json") for index in range(89)], "exactly 90"),
    ],
)
def test_validate_routes_records_candidate_preflight_failures(tmp_path, payload, message) -> None:
    interim = tmp_path / "data/interim"
    interim.mkdir(parents=True)
    (interim / "pilot_candidates.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        cli.validate_routes(tmp_path, object(), datetime(2026, 7, 12, tzinfo=timezone.utc))

    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["failures"][0]["stage"] == "candidate_preflight"
    assert report["failures"][0]["type"]


@pytest.mark.parametrize("failure", ["duplicate_id", "invalid_model"])
def test_validate_routes_audits_candidate_identity_and_model_failures(tmp_path, failure: str) -> None:
    payload = [_candidate(index).model_dump(mode="json") for index in range(90)]
    if failure == "duplicate_id":
        payload[1]["route_id"] = payload[0]["route_id"]
    else:
        payload[1].pop("route_name")
    interim = tmp_path / "data/interim"
    interim.mkdir(parents=True)
    (interim / "pilot_candidates.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception):
        cli.validate_routes(tmp_path, object(), datetime(2026, 7, 12, tzinfo=timezone.utc))

    report = json.loads((tmp_path / "data/processed/route_validation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["failures"][0]["stage"] == "candidate_preflight"


def test_main_dispatches_validate_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sys.argv", ["xuhui-route-builder", "validate-routes"])
    settings = type("Settings", (), {"project_root": tmp_path, "raw_dir": tmp_path / "data/raw"})()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    seen = {}
    monkeypatch.setattr(cli, "OverpassClient", lambda **kwargs: seen.setdefault("client_kwargs", kwargs) or object())
    monkeypatch.setattr(cli, "validate_routes", lambda root, client, verified_at=None: seen.update(root=root, verified_at=verified_at))

    cli.main()

    assert seen["root"] == tmp_path
    assert seen["client_kwargs"]["cache_dir"] == tmp_path / "data/raw/osm"
    assert seen["verified_at"].tzinfo == timezone.utc
