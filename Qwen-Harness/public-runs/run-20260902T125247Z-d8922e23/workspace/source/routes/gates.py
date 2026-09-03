"""Formal spatial and portfolio gates for the Xuhui route portfolio.

Every numeric constant below is quoted verbatim from the project quality contract
(``skills/quality_threshold_contract.md``, transcribed from
``.qoder/skills/optimize-xuhui-routes``). Values the skill does not define are
marked ``not_defined_in_skill`` instead of being invented here.

Two gates cannot be measured in this run and are reported honestly rather than
being silently dropped:

* ``api_geometry_distance_mismatch`` (AMap distance vs geometry, <= 3%) requires a
  paid routing credential that this run is forbidden to read -> ``not_applicable``.
* ``road_snapping`` on doubtful segments requires an external routing service;
  here every vertex comes from an OSM way of the passable road graph, so the value
  is reported as ``construction_guaranteed`` with ratio 1.0 and that provenance
  string attached.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .geometry import (
    Coord,
    circuity,
    endpoint_offset_m,
    haversine_m,
    in_district_ratio,
    local_return_loops,
    overlap_ratio,
    polyline_length_m,
    repeated_undirected_edges,
    retrace_segments,
    self_intersection_count,
)

EARTH_RADIUS_M = 6_371_008.8
TARGET_ERROR_MAX = 0.15
DISTANCE_ERROR_MAX = 0.03
LOOP_ENDPOINT_MAX_M = 30.0
MARKER_ENDPOINT_MAX_M = 30.0
STRICT_LOOP_CLOSURE_MARGIN_M = 75.0
ONE_WAY_ENDPOINT_MIN_M = 200.0
RETRACE_RATIO_MAX = 0.02
RETRACE_EDGE_MAX_M = 30.0
ROUND_DIGITS = 5
LOCAL_UTURN_MIN_LEG_M = 15.0
LOCAL_UTURN_CLOSE_M = 10.0
LOCAL_RETURN_PATH_MIN_M = 200.0
LOCAL_RETURN_RADIUS_M = 20.0
ONE_WAY_CIRCUITY_MAX = 2.5
WAYPOINT_OFFSET_M = {"walk": 50.0, "run": 50.0, "bike": 100.0}
IN_DISTRICT_MIN_RATIO = 0.90
ROAD_SNAP_MIN_RATIO = 0.98
SAME_MODE_OVERLAP_MAX = 0.90
MIN_GEOMETRY_COORDS = 2
NAV_NODE_RANGE = (2, 6)
NAV_NODE_LONG_BIKE_MAX = 8
LOOP_COUNT_RANGE = (14, 16)
ROUTES_PER_MODE = 30
ROUTES_PER_BAND = 10
DISTANCE_BANDS_PER_MODE = 3

NOT_DEFINED_IN_SKILL = "not_defined_in_skill"


@dataclass(slots=True)
class RouteInput:
    route_id: str
    mode: str
    kind: str
    target_m: float
    coords: list[Coord]
    band: int
    area: str
    navigation_nodes: int = 2
    start_marker: Coord | None = None
    end_marker: Coord | None = None
    waypoints: Sequence[Coord] = ()
    long_distance: bool = False


@dataclass(slots=True)
class RouteGateResult:
    route_id: str
    mode: str
    kind: str
    area: str
    band: int
    metrics: dict[str, float | int | str | None]
    failures: list[str] = field(default_factory=list)
    status: str = "accepted"

    @property
    def passed(self) -> bool:
        return not self.failures and self.status == "accepted"


def _failure(result: RouteGateResult, code: str) -> None:
    if code not in result.failures:
        result.failures.append(code)


def evaluate_route(route: RouteInput, boundary: Sequence[Coord]) -> RouteGateResult:
    coords = route.coords
    result = RouteGateResult(
        route_id=route.route_id,
        mode=route.mode,
        kind=route.kind,
        area=route.area,
        band=route.band,
        metrics={
            "coordinate_count": len(coords),
            "crs": "CRS84/WGS84 (lon,lat)",
            "earth_radius_m": EARTH_RADIUS_M,
        },
    )

    if len(coords) < MIN_GEOMETRY_COORDS:
        _failure(result, "missing_geometry")
        result.status = "rejected"
        return result

    length_m = polyline_length_m(coords)
    target_error = abs(length_m - route.target_m) / route.target_m if route.target_m else 1.0
    in_ratio = in_district_ratio(coords, boundary)
    repeated_count, repeated_total_m, repeated_longest_m = repeated_undirected_edges(
        coords, tolerance_deg=10 ** (-ROUND_DIGITS)
    )
    repeated_ratio = repeated_total_m / length_m if length_m else 0.0
    uturns = retrace_segments(
        coords, min_leg_m=LOCAL_UTURN_MIN_LEG_M, close_m=LOCAL_UTURN_CLOSE_M
    )
    returns = local_return_loops(
        coords,
        min_path_m=LOCAL_RETURN_PATH_MIN_M,
        close_m=LOCAL_RETURN_RADIUS_M,
        closure_margin_m=STRICT_LOOP_CLOSURE_MARGIN_M if route.kind == "strict_loop" else 0.0,
    )
    self_intersections = self_intersection_count(coords)
    end_offset = endpoint_offset_m(coords)
    circ = circuity(coords)

    result.metrics.update(
        {
            "length_m": round(length_m, 2),
            "target_m": round(route.target_m, 2),
            "target_error": round(target_error, 6),
            "in_district_ratio": round(in_ratio, 6),
            "road_snapping_ratio": 1.0,
            "road_snapping_provenance": "construction_guaranteed",
            "api_distance_error": None,
            "api_distance_provenance": "not_applicable_no_credentials",
            "repeated_edge_count": repeated_count,
            "repeated_edge_total_m": round(repeated_total_m, 2),
            "repeated_edge_ratio": round(repeated_ratio, 6),
            "repeated_edge_longest_m": round(repeated_longest_m, 2),
            "local_uturn_count": uturns,
            "local_return_loop_count": returns,
            "proper_self_intersection_count": self_intersections,
            "endpoint_offset_m": round(end_offset, 2),
            "circuity": round(circ, 4),
            "navigation_node_count": route.navigation_nodes,
            "dumbbell_shape_threshold": NOT_DEFINED_IN_SKILL,
            "long_stem_threshold": NOT_DEFINED_IN_SKILL,
            "dead_end_threshold": NOT_DEFINED_IN_SKILL,
        }
    )

    if target_error > TARGET_ERROR_MAX:
        _failure(result, "target_distance_error")
    if in_ratio < IN_DISTRICT_MIN_RATIO:
        _failure(result, "outside_district_ratio")
    if repeated_ratio > RETRACE_RATIO_MAX:
        _failure(result, "retraced_edges")
    if repeated_longest_m >= RETRACE_EDGE_MAX_M:
        _failure(result, "retraced_edges_long")
    if uturns:
        _failure(result, "local_uturn")
    if returns:
        _failure(result, "local_return_loop")
    if self_intersections:
        _failure(result, "branch_or_self_intersection")

    if route.kind == "strict_loop":
        if end_offset > LOOP_ENDPOINT_MAX_M:
            _failure(result, "open_loop")
    elif route.kind == "one_way":
        if end_offset <= ONE_WAY_ENDPOINT_MIN_M:
            _failure(result, "weak_one_way")
        if circ > ONE_WAY_CIRCUITY_MAX:
            _failure(result, "excessive_circuity")
    else:
        _failure(result, "unknown_route_kind")

    offset_limit = WAYPOINT_OFFSET_M.get(route.mode, 50.0)
    for index, point in enumerate(route.waypoints):
        deviation = min(haversine_m(point, coord) for coord in coords) if coords else 0.0
        if deviation > offset_limit:
            _failure(result, "waypoint_offset")
            result.metrics[f"waypoint_offset_m_{index}"] = round(deviation, 2)
            break

    start_marker = route.start_marker if route.start_marker is not None else coords[0]
    end_marker = route.end_marker if route.end_marker is not None else coords[-1]
    if haversine_m(start_marker, coords[0]) > MARKER_ENDPOINT_MAX_M:
        _failure(result, "start_marker_offset")
    if haversine_m(end_marker, coords[-1]) > MARKER_ENDPOINT_MAX_M:
        _failure(result, "end_marker_offset")

    nav_max = NAV_NODE_LONG_BIKE_MAX if route.long_distance else NAV_NODE_RANGE[1]
    if not (NAV_NODE_RANGE[0] <= route.navigation_nodes <= nav_max):
        _failure(result, "navigation_node_count")

    if result.failures:
        result.status = "needs_review" if len(result.failures) <= 2 else "rejected"
    return result


def signature(coords: Sequence[Coord], digits: int = ROUND_DIGITS) -> tuple[tuple[float, float], ...]:
    return tuple((round(lon, digits), round(lat, digits)) for lon, lat in coords)


def duplicate_pairs(results: Sequence[RouteGateResult], inputs: Sequence[RouteInput]) -> list[dict[str, str]]:
    """Detect identical and reverse-identical trajectories across the portfolio."""
    lookup: dict[tuple[tuple[float, float], ...], str] = {}
    pairs: list[dict[str, str]] = []
    for route, _ in zip(inputs, results, strict=True):
        forward = signature(route.coords)
        backward = tuple(reversed(forward))
        for variant, label in ((forward, "identical"), (backward, "reverse_identical")):
            existing = lookup.get(variant)
            if existing is not None and existing != route.route_id:
                pairs.append({"a": existing, "b": route.route_id, "relation": label})
        lookup.setdefault(forward, route.route_id)
    return pairs


def same_mode_overlap(
    inputs: Sequence[RouteInput], tolerance_m: float = 25.0
) -> list[dict[str, float | str]]:
    """Pairwise trajectory overlap inside each mode (must stay below 90%)."""
    violations: list[dict[str, float | str]] = []
    by_mode: dict[str, list[RouteInput]] = {}
    for route in inputs:
        by_mode.setdefault(route.mode, []).append(route)
    for mode, group in sorted(by_mode.items()):
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                ratio = overlap_ratio(first.coords, second.coords, tolerance_m=tolerance_m)
                if ratio >= SAME_MODE_OVERLAP_MAX:
                    violations.append(
                        {
                            "mode": mode,
                            "a": first.route_id,
                            "b": second.route_id,
                            "overlap_ratio": round(ratio, 4),
                            "threshold": SAME_MODE_OVERLAP_MAX,
                        }
                    )
    return violations


def evaluate_portfolio(
    inputs: Sequence[RouteInput],
    results: Sequence[RouteGateResult],
    areas: Sequence[str],
    bands: dict[str, Sequence[tuple[float, float]]],
) -> dict[str, object]:
    counts_by_mode: dict[str, int] = {}
    counts_by_band: dict[str, int] = {}
    counts_by_kind: dict[str, int] = {}
    counts_by_status: dict[str, int] = {}
    area_coverage: dict[str, int] = {area: 0 for area in areas}
    for route, result in zip(inputs, results, strict=True):
        counts_by_mode[route.mode] = counts_by_mode.get(route.mode, 0) + 1
        counts_by_band[f"{route.mode}:band{route.band}"] = (
            counts_by_band.get(f"{route.mode}:band{route.band}", 0) + 1
        )
        counts_by_kind[f"{route.mode}:{route.kind}"] = counts_by_kind.get(f"{route.mode}:{route.kind}", 0) + 1
        counts_by_status[result.status] = counts_by_status.get(result.status, 0) + 1
        area_coverage[route.area] = area_coverage.get(route.area, 0) + 1

    failures: list[str] = []
    ids = [route.route_id for route in inputs]
    if len(ids) != len(set(ids)):
        failures.append("duplicate_route_id")
    if len(ids) != 90:
        failures.append("total_route_count")
    for mode, expected_bands in bands.items():
        if counts_by_mode.get(mode, 0) != ROUTES_PER_MODE:
            failures.append(f"mode_count:{mode}")
        for band_index in range(len(expected_bands)):
            if counts_by_band.get(f"{mode}:band{band_index}", 0) != ROUTES_PER_BAND:
                failures.append(f"band_count:{mode}:{band_index}")
        loops = counts_by_kind.get(f"{mode}:strict_loop", 0)
        if not (LOOP_COUNT_RANGE[0] <= loops <= LOOP_COUNT_RANGE[1]):
            failures.append(f"loop_count_range:{mode}")
    missing_areas = sorted(area for area, count in area_coverage.items() if count < 1)
    if missing_areas:
        failures.append("popular_area_coverage_gap")
    if counts_by_status.get("needs_review", 0) or counts_by_status.get("rejected", 0):
        failures.append("unaccepted_routes_present")

    duplicates = duplicate_pairs(results, inputs)
    overlaps = same_mode_overlap(inputs)
    if duplicates:
        failures.append("duplicate_or_reverse_duplicate_trajectory")
    if overlaps:
        failures.append("same_mode_overlap_above_threshold")

    return {
        "route_count": len(ids),
        "counts_by_mode": counts_by_mode,
        "counts_by_band": counts_by_band,
        "counts_by_kind": counts_by_kind,
        "counts_by_status": counts_by_status,
        "area_coverage": area_coverage,
        "missing_areas": missing_areas,
        "duplicate_pairs": duplicates,
        "same_mode_overlap_violations": overlaps,
        "failures": failures,
        "passed": not failures,
        "thresholds": {
            "routes_per_mode": ROUTES_PER_MODE,
            "routes_per_band": ROUTES_PER_BAND,
            "loop_count_range": list(LOOP_COUNT_RANGE),
            "in_district_min_ratio": IN_DISTRICT_MIN_RATIO,
            "road_snap_min_ratio": ROAD_SNAP_MIN_RATIO,
            "same_mode_overlap_max": SAME_MODE_OVERLAP_MAX,
            "target_error_max": TARGET_ERROR_MAX,
            "api_distance_error_max": DISTANCE_ERROR_MAX,
            "loop_endpoint_max_m": LOOP_ENDPOINT_MAX_M,
            "marker_endpoint_max_m": MARKER_ENDPOINT_MAX_M,
            "strict_loop_closure_margin_m": STRICT_LOOP_CLOSURE_MARGIN_M,
            "one_way_endpoint_min_m": ONE_WAY_ENDPOINT_MIN_M,
            "retrace_ratio_max": RETRACE_RATIO_MAX,
            "retrace_edge_max_m": RETRACE_EDGE_MAX_M,
            "round_digits": ROUND_DIGITS,
            "one_way_circuity_max": ONE_WAY_CIRCUITY_MAX,
            "waypoint_offset_m": WAYPOINT_OFFSET_M,
            "nav_node_range": list(NAV_NODE_RANGE),
            "nav_node_long_bike_max": NAV_NODE_LONG_BIKE_MAX,
            "min_geometry_coords": MIN_GEOMETRY_COORDS,
        },
    }
