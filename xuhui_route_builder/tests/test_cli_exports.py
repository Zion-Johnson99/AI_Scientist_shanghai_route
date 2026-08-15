from __future__ import annotations

import json
from datetime import date, datetime, timezone
import sys

import pytest

from xuhui_route_builder import cli
from xuhui_route_builder.models import CandidateRoute, CoordinatePair, RouteLocation, RouteNode


def _candidate(index: int) -> CandidateRoute:
    start = RouteLocation(name=f"入口{index}", location_type="public_space", lng_gcj02=121.4, lat_gcj02=31.1, source_url="https://example.com/start")
    end = RouteLocation(name=f"终点{index}", location_type="public_space", lng_gcj02=121.401, lat_gcj02=31.1, source_url="https://example.com/end")
    return CandidateRoute(
        route_id=f"route-{index}", route_name=f"路线{index}", route_mode="walk", target_distance_m=100,
        route_shape="one_way", actual_distance_m=100, duration_s=80, start_entry_id="a", end_entry_id="b",
        start_location=start, end_location=end,
        ordered_nodes=[RouteNode(node_name=start.name, lng_gcj02=start.lng_gcj02, lat_gcj02=start.lat_gcj02), RouteNode(node_name=end.name, lng_gcj02=end.lng_gcj02, lat_gcj02=end.lat_gcj02)],
        amenity_ids=[], region_zone="徐汇",
        polyline_gcj02=[CoordinatePair(lng_gcj02=121.4, lat_gcj02=31.1, lng_wgs84=121.395, lat_wgs84=31.102),
                       CoordinatePair(lng_gcj02=121.401, lat_gcj02=31.1, lng_wgs84=121.396, lat_wgs84=31.102)],
        source_method="amap_segmented_direction", geometry_source="amap_direction", geometry_status="complete",
        raw_response_paths=[f"raw/{index}.json"],
    )


def test_generate_routes_partial_failure_preserves_old_candidates(tmp_path, monkeypatch, capsys) -> None:
    target = tmp_path / "data/interim/pilot_candidates.json"
    target.parent.mkdir(parents=True)
    target.write_text('[{"old": true}]', encoding="utf-8")
    seeds = [type("Seed", (), {"seed_id": f"seed-{i}", "route_mode": "walk", "geometry_action": "regenerate"})() for i in range(90)]
    monkeypatch.setattr(cli, "validate_seeds", lambda root: seeds)

    def generate(seed, client, index):
        if index == 2:
            raise ValueError("segment failed")
        return _candidate(index)

    monkeypatch.setattr(cli, "generate_candidate_from_seed", generate)
    with pytest.raises(RuntimeError, match=r"success=89.*failure=1"):
        cli.generate_routes(tmp_path, object())

    assert json.loads(target.read_text(encoding="utf-8")) == [{"old": True}]
    report = json.loads((tmp_path / "data/processed/route_generation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["success_count"] == 89 and report["failure_count"] == 1
    assert report["failures"][0]["seed_id"] == "seed-1"
    assert report["failures"][0]["mode"] == "walk"
    assert report["failures"][0]["exception_type"] == "ValueError"
    assert "generate_candidate_from_seed" in report["failures"][0]["traceback"]
    assert "route_generation_success=89 route_generation_failure=1" in capsys.readouterr().out


def test_generate_routes_with_no_success_preserves_old_candidates(tmp_path, monkeypatch) -> None:
    target = tmp_path / "data/interim/pilot_candidates.json"
    target.parent.mkdir(parents=True)
    target.write_text('[{"old": true}]', encoding="utf-8")
    seed = type("Seed", (), {"seed_id": "failed", "route_mode": "bike", "geometry_action": "regenerate"})()
    monkeypatch.setattr(cli, "validate_seeds", lambda root: [seed])
    monkeypatch.setattr(cli, "generate_candidate_from_seed", lambda *args: (_ for _ in ()).throw(RuntimeError("down")))

    with pytest.raises(RuntimeError, match=r"success=0.*failure=1"):
        cli.generate_routes(tmp_path, object())
    assert json.loads(target.read_text(encoding="utf-8")) == [{"old": True}]
    report = json.loads((tmp_path / "data/processed/route_generation_report.json").read_text(encoding="utf-8"))
    assert report["success_count"] == 0 and report["failure_count"] == 1


def test_generate_routes_candidate_write_failure_records_failed_batch(tmp_path, monkeypatch) -> None:
    seeds = [type("Seed", (), {"seed_id": f"seed-{i}", "route_mode": "walk", "geometry_action": "regenerate"})() for i in range(90)]
    monkeypatch.setattr(cli, "validate_seeds", lambda root: seeds)
    monkeypatch.setattr(cli, "generate_candidate_from_seed", lambda seed, client, index: _candidate(index))
    real_atomic_write = cli._atomic_write_json

    def fail_candidate_write(target, payload):
        if target.name == "pilot_candidates.json":
            raise OSError("disk full")
        real_atomic_write(target, payload)

    monkeypatch.setattr(cli, "_atomic_write_json", fail_candidate_write)

    with pytest.raises(RuntimeError, match=r"success=90.*failure=1"):
        cli.generate_routes(tmp_path, object())

    report = json.loads((tmp_path / "data/processed/route_generation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "failed"
    assert report["failure_count"] == 1
    assert report["failures"][0]["stage"] == "candidate_write"
    assert report["failures"][0]["exception_type"] == "OSError"


@pytest.mark.parametrize("old_payload", [b'[{"old":true}]', None])
def test_generate_routes_final_report_failure_rolls_back_candidates(tmp_path, monkeypatch, old_payload) -> None:
    candidate_path = tmp_path / "data/interim/pilot_candidates.json"
    if old_payload is not None:
        candidate_path.parent.mkdir(parents=True)
        candidate_path.write_bytes(old_payload)
    seeds = [type("Seed", (), {"seed_id": f"seed-{i}", "route_mode": "walk", "geometry_action": "regenerate"})() for i in range(90)]
    monkeypatch.setattr(cli, "validate_seeds", lambda root: seeds)
    monkeypatch.setattr(cli, "generate_candidate_from_seed", lambda seed, client, index: _candidate(index))
    real_atomic_write = cli._atomic_write_json
    report_writes = 0

    def fail_final_report(target, payload):
        nonlocal report_writes
        if target.name == "route_generation_report.json":
            report_writes += 1
            if report_writes == 2:
                raise OSError("report disk full")
        real_atomic_write(target, payload)

    monkeypatch.setattr(cli, "_atomic_write_json", fail_final_report)

    with pytest.raises(RuntimeError, match=r"report stage.*success=90.*failure=1") as caught:
        cli.generate_routes(tmp_path, object())

    assert isinstance(caught.value.__cause__, OSError)
    if old_payload is None:
        assert not candidate_path.exists()
    else:
        assert candidate_path.read_bytes() == old_payload
    report = json.loads((tmp_path / "data/processed/route_generation_report.json").read_text(encoding="utf-8"))
    assert report["batch_status"] == "preparing"


def test_main_dispatches_generate_routes(tmp_path, monkeypatch) -> None:
    settings = type(
        "Settings",
        (),
        {"project_root": object(), "raw_dir": tmp_path, "amap_web_service_key": "key"},
    )()
    client = object()
    calls = []
    monkeypatch.setattr(sys, "argv", ["xuhui-route-builder", "generate-routes"])
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "AmapClient", lambda key, raw_dir: client)
    monkeypatch.setattr(cli, "generate_routes", lambda project_root, received_client: calls.append((project_root, received_client)))

    cli.main()

    assert calls == [(settings.project_root, client)]


def test_main_rejects_removed_demo_commands(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["xuhui-route-builder", "export-demo"])
    with pytest.raises(SystemExit):
        cli.main()


def test_export_candidate_routes_writes_web_data_without_overwriting_0813_baseline(tmp_path) -> None:
    routes = [_candidate(index) for index in range(90)]
    for index, route in enumerate(routes):
        route.route_mode = ("walk", "run", "bike")[index // 30]
        route.source_accessed_at = date(2026, 8, 13)
        route.waypoint_names = [f"入口{index}", f"终点{index}"]
        route.validation_status = "accepted" if index < 6 else "needs_review"
        route.review_note = "严格验收通过" if index < 6 else "待复核路网贴合率"
        if index < 6:
            route.snap_ratio = 0.99
            route.network_source = "osm-test"
            route.verified_at = datetime(2026, 8, 13, tzinfo=timezone.utc)
    source = tmp_path / "data/processed/pilot_validated.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps([route.model_dump(mode="json") for route in routes], ensure_ascii=False), encoding="utf-8")

    cli.export_candidate_routes(tmp_path)

    catalog = json.loads((tmp_path / "data/web/route_catalog.json").read_text(encoding="utf-8"))
    features = json.loads((tmp_path / "data/web/xuhui_routes.geojson").read_text(encoding="utf-8"))
    assert len(catalog) == len(features["features"]) == 90
    assert sum(route["display_status"] == "严格验收" for route in catalog) == 6
    assert not (tmp_path / "0813徐汇区90条路线验收与考证清单.md").exists()
