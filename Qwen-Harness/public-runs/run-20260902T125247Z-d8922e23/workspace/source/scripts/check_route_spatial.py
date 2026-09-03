"""Gate 90 条路线的空间质量与组合门禁检查.

This check reads the *shipped* artifacts — ``route_catalog.json``,
``xuhui_routes.geojson`` and the district boundary — and re-derives every spatial
metric from the GeoJSON coordinates. It deliberately does not trust the metric
columns already sitting in the catalog.

That distinction is the whole point. The catalog was written by the same pipeline
that generated the routes, so a bug in the generator that mis-measured a route
would also write the mis-measured number into the catalog, and a check that read
the catalog would report the bug as a pass. Reconstructing a ``RouteInput`` from
the geometry and pushing it back through ``gates.evaluate_route`` makes the
shipped artifact answer for itself: the numbers in the catalog have to agree with
a fresh measurement of the coordinates the catalog ships.

Thresholds are imported from ``routes.gates`` and band definitions from
``routes.catalog`` rather than restated here, so this file cannot drift into
checking a looser contract than the generator was built against.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
CHECKS_DIR: Path = RUN_ROOT / "checks"

#: Run as ``python scripts/check_route_spatial.py``, so sys.path[0] is scripts/
#: and the first-party packages one level up are invisible without this.
sys.path.insert(0, str(SOURCE_ROOT))

from routes.catalog import BANDS_KM  # noqa: E402
from routes.gates import (  # noqa: E402
    IN_DISTRICT_MIN_RATIO,
    LOOP_COUNT_RANGE,
    MIN_GEOMETRY_COORDS,
    ROAD_SNAP_MIN_RATIO,
    ROUTES_PER_BAND,
    ROUTES_PER_MODE,
    SAME_MODE_OVERLAP_MAX,
    RouteInput,
    evaluate_route,
)
from routes.geometry import Coord, overlap_ratio  # noqa: E402

WEB_DIR: Path = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web"
CATALOG_PATH: Path = WEB_DIR / "route_catalog.json"
GEOJSON_PATH: Path = WEB_DIR / "xuhui_routes.geojson"
BOUNDARY_PATH: Path = RUN_ROOT / "sources" / "xuhui_boundary.geojson"

#: The eight areas the contract requires the portfolio to cover.
REQUIRED_AREAS: tuple[str, ...] = (
    "west_bund",
    "longhua",
    "xujiahui",
    "hengfu",
    "shanghai_botanical_garden",
    "kangjian",
    "caohejing",
    "huajing",
)

EXPECTED_TOTAL = 90

#: Agreement tolerance between a re-derived metric and the value the catalog
#: stored for it. Non-zero because the catalog rounds to a fixed number of
#: digits and simplifies the polyline before writing.
AGREEMENT_TOLERANCE = 0.02


def load_json(path: Path) -> Any:
    """Read one JSON artifact, reporting a missing file rather than raising."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def catalog_entries(payload: Any) -> list[dict[str, Any]]:
    """Accept either a bare list or the wrapped artifact form."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("routes", "catalog", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def boundary_ring(payload: Any) -> list[Coord]:
    """Extract the district ring from the boundary GeoJSON."""
    if not isinstance(payload, dict):
        return []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        rings = geometry.get("coordinates") or []
        if geometry.get("type") == "Polygon" and rings:
            return [(float(point[0]), float(point[1])) for point in rings[0]]
    return []


def geometry_by_id(payload: Any) -> dict[str, list[Coord]]:
    """Map route id to its shipped LineString coordinates."""
    out: dict[str, list[Coord]] = {}
    if not isinstance(payload, dict):
        return out
    for feature in payload.get("features", []):
        route_id = str(feature.get("id") or (feature.get("properties") or {}).get("route_id") or "")
        geometry = feature.get("geometry") or {}
        if not route_id or geometry.get("type") != "LineString":
            continue
        out[route_id] = [(float(point[0]), float(point[1])) for point in geometry.get("coordinates") or []]
    return out


def rebuild_input(entry: dict[str, Any], coords: list[Coord]) -> RouteInput:
    """Reconstruct a gate input from shipped fields plus re-read geometry."""
    start = entry.get("start_marker") or entry.get("start") or list(coords[0])
    end = entry.get("end_marker") or entry.get("end") or list(coords[-1])
    return RouteInput(
        route_id=str(entry.get("route_id", "")),
        mode=str(entry.get("mode", "")),
        kind=str(entry.get("kind", "")),
        target_m=float(entry.get("target_distance_m") or 0.0),
        coords=coords,
        band=int(entry.get("band") or 0),
        area=str(entry.get("area") or ""),
        navigation_nodes=int(entry.get("navigation_nodes") or 2),
        start_marker=(float(start[0]), float(start[1])),
        end_marker=(float(end[0]), float(end[1])),
        waypoints=(),
        long_distance=bool(entry.get("long_distance", False)),
    )


def disagreement(entry: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    """Report catalog metrics that a fresh measurement does not reproduce."""
    found: list[str] = []
    for key in ("in_district_ratio", "road_snapping_ratio", "endpoint_offset_m", "circuity"):
        stored = entry.get(key)
        fresh = metrics.get(key)
        if not isinstance(stored, (int, float)) or not isinstance(fresh, (int, float)):
            continue
        scale = max(abs(stored), abs(fresh), 1.0)
        if abs(float(stored) - float(fresh)) / scale > AGREEMENT_TOLERANCE:
            found.append(f"{entry.get('route_id')}:{key} catalog={stored} recomputed={round(float(fresh), 4)}")
    for key in ("repeated_edge_count", "proper_self_intersection_count", "local_uturn_count"):
        stored = entry.get(key)
        fresh = metrics.get(key)
        if isinstance(stored, int) and isinstance(fresh, int) and stored != fresh:
            found.append(f"{entry.get('route_id')}:{key} catalog={stored} recomputed={fresh}")
    return found


def pairwise_overlap(coords_by_id: dict[str, list[Coord]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within-mode geometric overlap at the contract tolerance."""
    by_mode: dict[str, list[tuple[str, list[Coord]]]] = {}
    for entry in entries:
        route_id = str(entry.get("route_id", ""))
        coords = coords_by_id.get(route_id)
        if coords:
            by_mode.setdefault(str(entry.get("mode", "")), []).append((route_id, coords))
    violations: list[dict[str, Any]] = []
    for mode, group in by_mode.items():
        for index, (first_id, first) in enumerate(group):
            for second_id, second in group[index + 1 :]:
                ratio = max(overlap_ratio(first, second), overlap_ratio(second, first))
                if ratio >= SAME_MODE_OVERLAP_MAX:
                    violations.append(
                        {"mode": mode, "route_a": first_id, "route_b": second_id, "overlap_ratio": round(ratio, 4)}
                    )
    return violations


def main() -> int:
    """Re-derive the spatial gate from shipped artifacts and write the check."""
    failures: list[str] = []
    notes: list[str] = []

    catalog_payload = load_json(CATALOG_PATH)
    geojson_payload = load_json(GEOJSON_PATH)
    boundary_payload = load_json(BOUNDARY_PATH)

    for label, payload, path in (
        ("route_catalog.json", catalog_payload, CATALOG_PATH),
        ("xuhui_routes.geojson", geojson_payload, GEOJSON_PATH),
        ("xuhui_boundary.geojson", boundary_payload, BOUNDARY_PATH),
    ):
        if payload is None:
            failures.append(f"missing_artifact:{label}")
            notes.append(f"{label} not found at {path.relative_to(RUN_ROOT).as_posix()}")

    entries = catalog_entries(catalog_payload)
    coords_by_id = geometry_by_id(geojson_payload)
    boundary = boundary_ring(boundary_payload)

    if not boundary:
        failures.append("boundary_ring_unavailable")
    if len(coords_by_id) < MIN_GEOMETRY_COORDS:
        failures.append("geojson_geometry_unavailable")

    counts_by_mode: dict[str, int] = {}
    counts_by_band: dict[str, int] = {}
    counts_by_kind: dict[str, int] = {}
    counts_by_status: dict[str, int] = {}
    area_coverage: dict[str, int] = {area: 0 for area in REQUIRED_AREAS}
    crs_values: set[str] = set()
    route_failures: list[dict[str, Any]] = []
    disagreements: list[str] = []
    ids: list[str] = []

    for entry in entries:
        route_id = str(entry.get("route_id", ""))
        ids.append(route_id)
        mode = str(entry.get("mode", ""))
        kind = str(entry.get("kind", ""))
        band = int(entry.get("band") or 0)
        counts_by_mode[mode] = counts_by_mode.get(mode, 0) + 1
        counts_by_band[f"{mode}:band{band}"] = counts_by_band.get(f"{mode}:band{band}", 0) + 1
        counts_by_kind[f"{mode}:{kind}"] = counts_by_kind.get(f"{mode}:{kind}", 0) + 1
        status = str(entry.get("status", ""))
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        area = str(entry.get("area") or "")
        area_coverage[area] = area_coverage.get(area, 0) + 1
        crs_values.add(str(entry.get("crs", "")))

        coords = coords_by_id.get(route_id)
        if not coords:
            route_failures.append({"route_id": route_id, "failures": ["geometry_not_in_geojson"]})
            continue
        if boundary:
            result = evaluate_route(rebuild_input(entry, coords), boundary)
            if result.failures or result.status != "accepted":
                route_failures.append(
                    {"route_id": route_id, "status": result.status, "failures": list(result.failures)}
                )
            disagreements.extend(disagreement(entry, result.metrics))

    if len(ids) != EXPECTED_TOTAL:
        failures.append(f"total_route_count:{len(ids)}")
    if len(ids) != len(set(ids)):
        failures.append("duplicate_route_id")

    for mode, bands in BANDS_KM.items():
        if counts_by_mode.get(mode, 0) != ROUTES_PER_MODE:
            failures.append(f"mode_count:{mode}={counts_by_mode.get(mode, 0)}")
        for band_index in range(len(bands)):
            got = counts_by_band.get(f"{mode}:band{band_index}", 0)
            if got != ROUTES_PER_BAND:
                failures.append(f"band_count:{mode}:{band_index}={got}")
        loops = counts_by_kind.get(f"{mode}:strict_loop", 0)
        if not LOOP_COUNT_RANGE[0] <= loops <= LOOP_COUNT_RANGE[1]:
            failures.append(f"loop_count_range:{mode}={loops}")

    for area in REQUIRED_AREAS:
        if area_coverage.get(area, 0) < 1:
            failures.append(f"missing_area:{area}")

    if counts_by_status.get("accepted", 0) != len(ids):
        failures.append(f"not_all_accepted:{counts_by_status}")
    if counts_by_status.get("needs_review", 0):
        failures.append(f"needs_review_present:{counts_by_status['needs_review']}")

    if len(crs_values) != 1 or not next(iter(crs_values), ""):
        failures.append(f"crs_declaration_inconsistent:{sorted(crs_values)}")

    overlap_violations = pairwise_overlap(coords_by_id, entries)
    if overlap_violations:
        failures.append(f"same_mode_overlap:{len(overlap_violations)}")

    if route_failures:
        failures.append(f"routes_failing_spatial_gate:{len(route_failures)}")
    if disagreements:
        failures.append(f"catalog_metric_disagreement:{len(disagreements)}")

    payload: dict[str, Any] = {
        "check": "route_spatial_quality",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rule": "90 条路线的空间与组合门禁，全部指标从已发布的 GeoJSON 几何重新推导",
        "method": "recompute_from_shipped_geometry",
        "artifacts": {
            "route_catalog": CATALOG_PATH.relative_to(RUN_ROOT).as_posix(),
            "routes_geojson": GEOJSON_PATH.relative_to(RUN_ROOT).as_posix(),
            "boundary": BOUNDARY_PATH.relative_to(RUN_ROOT).as_posix(),
        },
        "thresholds": {
            "expected_total": EXPECTED_TOTAL,
            "routes_per_mode": ROUTES_PER_MODE,
            "routes_per_band": ROUTES_PER_BAND,
            "loop_count_range": list(LOOP_COUNT_RANGE),
            "in_district_min_ratio": IN_DISTRICT_MIN_RATIO,
            "road_snap_min_ratio": ROAD_SNAP_MIN_RATIO,
            "same_mode_overlap_max": SAME_MODE_OVERLAP_MAX,
            "bands_km": {mode: [list(band) for band in bands] for mode, bands in BANDS_KM.items()},
            "catalog_agreement_tolerance": AGREEMENT_TOLERANCE,
        },
        "passed": not failures,
        "route_count": len(ids),
        "counts_by_mode": counts_by_mode,
        "counts_by_band": counts_by_band,
        "counts_by_kind": counts_by_kind,
        "counts_by_status": counts_by_status,
        "area_coverage": area_coverage,
        "crs_values": sorted(crs_values),
        "boundary_vertex_count": len(boundary),
        "failures": failures,
        "routes_failing_spatial_gate": route_failures[:50],
        "catalog_metric_disagreements": disagreements[:50],
        "same_mode_overlap_violations": overlap_violations[:50],
        "notes": notes,
    }

    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    (CHECKS_DIR / "route_spatial_quality.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for item in failures[:20]:
        print(f"FAIL {item}")
    for item in route_failures[:10]:
        print(f"  route {item['route_id']} -> {item.get('failures')}")
    for item in disagreements[:10]:
        print(f"  disagree {item}")
    print(
        f"routes={len(ids)} accepted={counts_by_status.get('accepted', 0)} "
        f"modes={counts_by_mode} overlap_violations={len(overlap_violations)}"
    )
    print(f"ROUTE_SPATIAL_QUALITY_PASSED={str(not failures).lower()}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
