"""Contract tests for the generated route artifacts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from xuhui_route_builder import route_builder

ROUTE_ID_PATTERN = re.compile(r"^XH_(WALK|RUN|BIKE)_\d{4}$")
LON_RANGE = (121.30, 121.55)
LAT_RANGE = (31.05, 31.30)
CANONICAL_CRS = "CRS84/WGS84 (lon,lat)"


@pytest.fixture(scope="module")
def result() -> route_builder.RouteModuleResult:
    return route_builder.build_result()


def test_core_artifacts_present(result: route_builder.RouteModuleResult) -> None:
    assert result.route_count > 0
    assert result.artifacts["data/web/route_catalog.json"] > 0
    assert result.artifacts["data/web/xuhui_routes.geojson"] > 0


def test_portfolio_composition(result: route_builder.RouteModuleResult) -> None:
    assert result.route_count == 90
    assert result.mode_counts == {"walk": 30, "run": 30, "bike": 30}
    assert result.accepted_count == 90
    assert result.needs_review_count == 0
    for mode, kinds in result.kind_counts.items():
        assert 14 <= kinds.get("strict_loop", 0) <= 16, mode
        assert kinds.get("strict_loop", 0) + kinds.get("one_way", 0) == 30, mode


def test_area_coverage(result: route_builder.RouteModuleResult) -> None:
    expected = {
        "west_bund",
        "longhua",
        "xujiahui",
        "hengfu",
        "shanghai_botanical_garden",
        "kangjian",
        "caohejing",
        "huajing",
    }
    assert expected <= set(result.area_counts)
    assert all(count >= 1 for count in result.area_counts.values())


def test_distance_band_counts(result: route_builder.RouteModuleResult) -> None:
    per_mode: dict[str, int] = {}
    for key, count in result.bucket_counts.items():
        mode = key.split(":", 1)[0] if ":" in key else key
        per_mode[mode] = per_mode.get(mode, 0) + count
        assert count == 10, key
    assert sorted(per_mode.values()) == [30, 30, 30]


def test_route_ids_unique_and_wellformed(result: route_builder.RouteModuleResult) -> None:
    ids = list(result.route_ids)
    assert len(ids) == len(set(ids))
    for route_id in ids:
        assert ROUTE_ID_PATTERN.match(route_id), route_id


def test_crs_declaration(result: route_builder.RouteModuleResult) -> None:
    assert result.crs == CANONICAL_CRS


def test_geojson_coordinates_in_district_bbox() -> None:
    payload = route_builder.load_routes_geojson()
    features = list(payload.get("features") or [])
    assert len(features) == 90
    catalog_ids = set(route_builder.build_result().route_ids)
    seen: set[str] = set()
    for feature in features:
        properties = feature.get("properties") or {}
        route_id = str(properties.get("route_id"))
        seen.add(route_id)
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        assert len(coords) >= 2, route_id
        for lon, lat in coords:
            assert LON_RANGE[0] <= float(lon) <= LON_RANGE[1], route_id
            assert LAT_RANGE[0] <= float(lat) <= LAT_RANGE[1], route_id
    assert seen == catalog_ids


def test_boundary_ring_closed_and_large() -> None:
    target: Path = route_builder.MODULE_ROOT / "data/web/xuhui_boundary.geojson"
    assert target.is_file()
    payload = route_builder._read_json(target)
    ring = payload["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) >= 100
    assert ring[0] == ring[-1]
