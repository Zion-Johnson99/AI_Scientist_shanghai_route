"""Deterministic construction of the 90-route Xuhui portfolio.

Inputs are exactly two public artifacts fetched in this run: the OSM
administrative ring for 徐汇区 and the OSM highway ways covering its bounding
box. No repository route data, no online product asset and no model call takes
part. Running this module twice over the same inputs yields identical routes,
because every choice is made by sorting on real geometry rather than by sampling.

Three properties are guaranteed by construction rather than by post-hoc repair:

* A ``strict_loop`` is the union of an outbound shortest path and a return
  shortest path computed with every outbound interior node blocked, so the ring
  is one connected component of cycle rank 1 with every node at degree 2. That
  rules out double loops, dumbbells, gourds and long stems.
* The road graph is clipped to the district before any search runs, so paths
  cannot drift outside 徐汇区 and the in-district ratio stays high.
* The return leg is additionally penalised for running beside the outbound
  corridor. Wide Xuhui roads are mapped as one way per carriageway about ten
  metres apart; without this penalty the two legs would be parallel and the
  local-return-loop gate would fire.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .areas import AREA_IDS, ResolvedArea, attach_nodes, nearest_area, resolve_areas
from .gates import (
    DISTANCE_BANDS_PER_MODE,
    LOCAL_RETURN_PATH_MIN_M,
    LOCAL_RETURN_RADIUS_M,
    LOCAL_UTURN_CLOSE_M,
    LOCAL_UTURN_MIN_LEG_M,
    LOOP_COUNT_RANGE,
    LOOP_ENDPOINT_MAX_M,
    ONE_WAY_CIRCUITY_MAX,
    ONE_WAY_ENDPOINT_MIN_M,
    ROUND_DIGITS,
    ROUTES_PER_BAND,
    ROUTES_PER_MODE,
    SAME_MODE_OVERLAP_MAX,
    STRICT_LOOP_CLOSURE_MARGIN_M,
    TARGET_ERROR_MAX,
    RouteGateResult,
    RouteInput,
    evaluate_portfolio,
    evaluate_route,
)
from .geometry import (
    CRS_WGS84,
    Coord,
    Ring,
    bbox,
    circuity,
    endpoint_offset_m,
    haversine_m,
    local_return_loops,
    overlap_ratio,
    point_in_ring,
    polyline_length_m,
    repeated_undirected_edges,
    retrace_segments,
)
from .road_graph import RoadGraph, prune_to_largest_component
from .search import (
    FoundRoute,
    coords_from_edges,
    dijkstra,
    make_route,
    pick_one_way,
    reconstruct,
)
from .simplify import douglas_peucker

MODES: tuple[str, ...] = ("walk", "run", "bike")

#: Distance bands in kilometres, taken verbatim from the quality contract:
#: G-04 walk, G-05 run, G-06 bike.
BANDS_KM: dict[str, Sequence[tuple[float, float]]] = {
    "walk": ((0.5, 2.0), (2.0, 3.5), (3.5, 5.0)),
    "run": ((1.0, 5.0), (5.0, 10.0), (10.0, 15.0)),
    "bike": ((5.0, 10.0), (10.0, 20.0), (20.0, 30.0)),
}

#: Design distance for each band is its midpoint. With ``SEARCH_TOLERANCE`` the
#: acceptance window stays strictly inside the band, so the band derived from
#: the actual distance always equals the design band and the 15% distance gate
#: always passes with margin. No tolerance relaxation is ever needed.
SEARCH_TOLERANCE = TARGET_ERROR_MAX * 0.92

SIMPLIFY_TOLERANCE_M = 5.0
CORRIDOR_PENALTY = 6.0
USED_EDGE_PENALTY = 3.0
CORRIDOR_RADIUS_M = 25.0
CORRIDOR_CELL_DEG = 0.0004
#: Qoder judgement, not a skill threshold. The skill defines distinctness only as
#: pairwise geometric overlap at 0.90, which still runs after this screen. Measuring
#: against the union of every accepted sibling is far stricter, and by the time bike
#: band-2 runs that union covers most of a 470.883 km network that ten 25 km routes
#: must share with the 225 km bands 0 and 1 already consumed. Measured response:
#: 0.45 gave 82 routes with bike band-2 at 2, 0.70 gave 86 with band-2 at 6 and the
#: loop-count gate cleared. Kept under the 0.90 pairwise ceiling on purpose.
EDGE_CONTAINMENT_MAX = 0.80
TURNAROUND_LIMIT = 16
ONE_WAY_CANDIDATE_LIMIT = 80
ANCHOR_POOL_LIMIT = 2000
SPREAD_ANCHOR_COUNT = 8
RETRY_ANCHOR_COUNT = 24
LOOP_BASE_FACTOR = 0.78
ONE_WAY_BASE_FACTOR = 1.20
CIRCUITY_PRESCREEN = ONE_WAY_CIRCUITY_MAX * 0.96
KIND_PER_BAND = ROUTES_PER_BAND // 2

#: The sweep's return-leg Dijkstra is unbounded, because a metre budget cannot be
#: combined with a corridor weight (see ``build_loop``). These two limits are what
#: keep a failing slot from turning into minutes of search.
SWEEP_TURNAROUND_LIMIT = 10
SWEEP_ENDPOINT_LIMIT = 40
SWEEP_TURNAROUND_HIGH_FACTOR = 0.55

#: Qoder judgement, not a skill threshold. Bike band-2 (20-30 km one-way) is the
#: only slot family whose feasibility is bounded by anchor eccentricity rather than
#: by road supply: ``build_sweep_one_way`` returns before searching whenever no node
#: sits ``low / CIRCUITY_PRESCREEN`` away, which for the 21.55 km floor is 8.98 km in
#: an 8.5 by 13.3 km district, so only anchors near the northern or southern extreme
#: qualify. Two probes measured what happens after that gate
#: (commands/probe_bike_band2.json, commands/probe_bike_band2_ordering.json): of the
#: 16 bike anchors 7 early-out and 9 qualify, and of those 9 only 3 hold a feasible
#: 25 km pair anywhere -- the other six return zero hits in 300 scans AND zero in
#: their full windows, so no budget, ordering or anchor count can rescue them. The
#: binding constraint on the three that do work is where the first feasible
#: turnaround sits in the scan order: ranking longest-outbound-first puts it at rank
#: 44/6/44, so the old 48-entry prefix found 1/0/30 of the 66/18/285 pairs those
#: anchors hold. Ranking by proximity to half the target instead puts it at rank
#: 13/9/1, which is why ``_attempt`` now passes ``ideal_outbound`` for this family
#: and why the budget can stay modest: 120 covers the first hit by roughly 9x and
#: yields about 15 feasible pairs per anchor at ~15 ms of plain Dijkstra each.
LONG_BIKE_SWEEP_TURNAROUND_LIMIT = 120
LONG_BIKE_SWEEP_ENDPOINT_LIMIT = 160
LONG_BIKE_TURNAROUND_HIGH_FACTOR = 0.75
#: How many screen rejections the long-bike sweep tolerates before giving up on an
#: anchor. Measured on the 2026-09-02 regeneration: raising the turnaround budget to
#: 120 and ordering by proximity to half the target lifted ``bike:b2:candidates`` from
#: 22 to 38, yet the portfolio stayed at 86 routes because
#: ``bike:b2:screen:local_return_loop`` went 0 -> 22 and ``screen:edge_containment``
#: held at 10 -- all 16 new candidates died in ``_attempt``'s screens, and one
#: rejection threw away the entire anchor's supply. Only 3 of the 9 anchors that clear
#: the eccentricity prescreen hold any feasible 25 km pair at all (66/285/333 pairs),
#: so an anchor is far too scarce to spend on a single candidate. Screening inside the
#: sweep instead lets it keep walking turnarounds and endpoints until one survives.
#: 48 bounds the added cost: ``local_return_loops`` breaks at 4x its 200 m floor, so it
#: is cheap, and only the ``evaluate_route`` probe is O(boundary x coords).
SWEEP_SCREEN_ACCEPT_LIMIT = 48

ID_PREFIX = {"walk": "XH_WALK", "run": "XH_RUN", "bike": "XH_BIKE"}
ID_OFFSET = {"walk": 0, "run": ROUTES_PER_MODE, "bike": ROUTES_PER_MODE * 2}

BoundaryBox = tuple[float, float, float, float]


def band_targets(mode: str) -> tuple[float, ...]:
    """Design distance in metres for each band of ``mode`` (the band midpoint)."""
    return tuple((low + high) * 500.0 for low, high in BANDS_KM[mode])


@dataclass(frozen=True, slots=True)
class Slot:
    """One of the 30 positions a mode's portfolio has to fill."""

    index: int
    band: int
    kind: str
    target_m: float
    area_id: str


def slot_plan(mode: str, area_ids: Sequence[str] = AREA_IDS) -> list[Slot]:
    """Five loops plus five one-ways in each of the three bands.

    That is ten routes per band and fifteen loops per mode, which sits inside the
    14-16 ``strict_loop`` window the contract asks for. Area ids are handed out
    round-robin over the thirty slots, so every one of the eight named areas is
    the preferred start anchor of three or four slots per mode.
    """
    targets = band_targets(mode)
    slots: list[Slot] = []
    cursor = 0
    for band in range(DISTANCE_BANDS_PER_MODE):
        for kind in ("strict_loop", "one_way"):
            for _ in range(KIND_PER_BAND):
                slots.append(
                    Slot(
                        index=len(slots),
                        band=band,
                        kind=kind,
                        target_m=targets[band],
                        area_id=area_ids[cursor % len(area_ids)],
                    )
                )
                cursor += 1
    return slots


@dataclass(slots=True)
class GeneratedRoute:
    route_id: str
    mode: str
    kind: str
    plan_kind: str
    band: int
    area: str
    anchor_area_id: str
    target_m: float
    actual_distance_m: float
    coords: list[Coord]
    edge_path: list[int]
    anchor_key: int
    anchor_origin: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Portfolio:
    routes: list[GeneratedRoute]
    inputs: list[RouteInput]
    results: list[RouteGateResult]
    portfolio: dict[str, Any]
    areas: list[ResolvedArea]
    boundary: Ring
    graph_stats: dict[str, dict[str, Any]]
    area_coverage: dict[str, int]
    kind_counts: dict[str, int]
    band_counts: dict[str, dict[int, int]]
    attempts: dict[str, int]
    kind_swaps: list[dict[str, Any]]
    unfilled_slots: list[dict[str, Any]]
    log: list[str] = field(default_factory=list)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def boundary_ring(feature: dict[str, Any]) -> Ring:
    """Longest outer ring of a Polygon or MultiPolygon boundary feature."""
    geometry = feature.get("geometry") or {}
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    rings: list[Ring] = []
    if kind == "Polygon":
        rings = [_as_ring(ring) for ring in coordinates]
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            rings.extend(_as_ring(ring) for ring in polygon)
    rings = [ring for ring in rings if len(ring) >= 4]
    if not rings:
        raise ValueError(f"boundary feature has no usable ring (type={kind})")
    return max(rings, key=polyline_length_m)


def _as_ring(raw: Sequence[Sequence[float]]) -> Ring:
    return tuple((float(point[0]), float(point[1])) for point in raw)


def boundary_from_geojson(payload: dict[str, Any]) -> Ring:
    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = payload.get("features") or []
        if not features:
            raise ValueError("boundary FeatureCollection is empty")
        return boundary_ring(features[0])
    if kind == "Feature":
        return boundary_ring(payload)
    return boundary_ring({"geometry": payload})


def district_graph(
    payload: dict[str, Any],
    mode: str,
    boundary: Ring,
    box: BoundaryBox,
    sample_count: int = 5,
) -> RoadGraph:
    """Rebuild a graph holding only the ways that mostly lie inside ``boundary``.

    Ways are re-added through ``RoadGraph.add_way`` rather than deleted from an
    already built graph, so every internal index stays consistent. A way is kept
    when a majority of up to ``sample_count`` evenly spaced vertices fall inside
    the district ring.
    """
    declared = payload.get("crs") or CRS_WGS84
    graph = RoadGraph(mode, crs=declared)
    west, south, east, north = box
    for element in payload.get("elements", []):
        if element.get("type") != "way":
            continue
        geometry = element.get("geometry") or []
        if len(geometry) < 2:
            continue
        lons = [point["lon"] for point in geometry]
        lats = [point["lat"] for point in geometry]
        if max(lons) < west or min(lons) > east:
            continue
        if max(lats) < south or min(lats) > north:
            continue
        stride = max(1, len(geometry) // sample_count)
        samples = geometry[::stride][:sample_count]
        if not samples:
            continue
        inside = sum(1 for point in samples if point_in_ring((point["lon"], point["lat"]), boundary))
        if inside * 2 < len(samples):
            continue
        graph.add_way(int(element.get("id", 0)), geometry, element.get("tags") or {})
    prune_to_largest_component(graph)
    return graph


@dataclass(slots=True)
class EdgeIndex:
    """Uniform grid over edge midpoints, used for the corridor penalty."""

    cell: float
    grid: dict[tuple[int, int], list[int]]
    midpoints: dict[int, Coord]


def build_edge_index(graph: RoadGraph, cell: float = CORRIDOR_CELL_DEG) -> EdgeIndex:
    grid: dict[tuple[int, int], list[int]] = {}
    midpoints: dict[int, Coord] = {}
    for edge_id, edge in graph.edges.items():
        coords = edge.coords
        if not coords:
            continue
        mid = coords[len(coords) // 2]
        midpoints[edge_id] = mid
        key = (math.floor(mid[0] / cell), math.floor(mid[1] / cell))
        grid.setdefault(key, []).append(edge_id)
    return EdgeIndex(cell=cell, grid=grid, midpoints=midpoints)


def corridor_edges(index: EdgeIndex, coords: Sequence[Coord], radius_m: float) -> set[int]:
    """Edge ids whose midpoint lies within ``radius_m`` of the outbound corridor."""
    hits: set[int] = set()
    cell = index.cell
    for lon, lat in coords:
        centre_x = math.floor(lon / cell)
        centre_y = math.floor(lat / cell)
        for delta_x in (-1, 0, 1):
            for delta_y in (-1, 0, 1):
                for edge_id in index.grid.get((centre_x + delta_x, centre_y + delta_y), ()):
                    if edge_id in hits:
                        continue
                    if haversine_m((lon, lat), index.midpoints[edge_id]) <= radius_m:
                        hits.add(edge_id)
    return hits


def corridor_weight(graph: RoadGraph, penalised: set[int], used_edges: dict[int, int]):  # type: ignore[no-untyped-def]
    """Cost function that pushes the return leg away from the outbound corridor."""

    def weight(edge_id: int) -> float:
        cost = graph.edges[edge_id].length_m
        if edge_id in penalised:
            cost *= CORRIDOR_PENALTY
        if used_edges.get(edge_id, 0):
            cost *= USED_EDGE_PENALTY
        return cost

    return weight


def anchor_pool(graph: RoadGraph, boundary: Ring, box: BoundaryBox) -> list[int]:
    """Junction nodes inside the district, deterministically subsampled."""
    west, south, east, north = box
    pool: list[int] = []
    for key, coord in graph.nodes.items():
        if graph.degree(key) < 3:
            continue
        if not west <= coord[0] <= east or not south <= coord[1] <= north:
            continue
        if not point_in_ring(coord, boundary):
            continue
        pool.append(key)
    pool.sort()
    if len(pool) > ANCHOR_POOL_LIMIT:
        stride = len(pool) / ANCHOR_POOL_LIMIT
        pool = [pool[int(position * stride)] for position in range(ANCHOR_POOL_LIMIT)]
    return pool


def spread_anchors(graph: RoadGraph, pool: Sequence[int], count: int) -> list[int]:
    """Farthest-point sampling, so generic anchors cover the district evenly."""
    if not pool:
        return []
    picked = [pool[0]]
    remaining = sorted(pool[1:])
    while len(picked) < count and remaining:
        best_key = -1
        best_distance = -1.0
        for key in remaining:
            coord = graph.nodes[key]
            distance = min(haversine_m(coord, graph.nodes[chosen]) for chosen in picked)
            if distance > best_distance:
                best_distance = distance
                best_key = key
        if best_key < 0:
            break
        picked.append(best_key)
        remaining.remove(best_key)
    return picked


def anchor_order(
    anchors: Sequence[tuple[int, str]], preferred_area_id: str
) -> list[tuple[int, str]]:
    """Preferred area anchor first, then the other areas, then spread anchors."""
    by_area: dict[str, list[tuple[int, str]]] = {}
    for entry in anchors:
        origin = entry[1]
        if origin.startswith("area:"):
            by_area.setdefault(origin[5:], []).append(entry)
    ordered = list(by_area.get(preferred_area_id, ()))
    for area_id in AREA_IDS:
        if area_id == preferred_area_id:
            continue
        ordered.extend(by_area.get(area_id, ()))
    ordered.extend(entry for entry in anchors if entry[1] == "spread")
    ordered.extend(entry for entry in anchors if not entry[1].startswith("area:"))
    seen: set[int] = set()
    unique: list[tuple[int, str]] = []
    for key, origin in ordered:
        if key in seen:
            continue
        seen.add(key)
        unique.append((key, origin))
    return unique


def cheap_screen(route: FoundRoute, target_m: float, tolerance: float) -> str | None:
    """Linear-cost rejection before the expensive full gate evaluation."""
    coords = route.coords
    if len(coords) < 3:
        return "too_few_coords"
    low = target_m * (1.0 - tolerance)
    high = target_m * (1.0 + tolerance)
    if not low <= route.length_m <= high:
        return "length_outside_window"
    offset = endpoint_offset_m(coords)
    if route.kind == "strict_loop":
        if offset > LOOP_ENDPOINT_MAX_M:
            return "open_loop"
    elif offset <= ONE_WAY_ENDPOINT_MIN_M:
        return "weak_one_way"
    elif circuity(coords) > CIRCUITY_PRESCREEN:
        return "excessive_circuity"
    repeats, repeated_m, longest_m = repeated_undirected_edges(
        coords, tolerance_deg=10 ** (-ROUND_DIGITS)
    )
    if repeats or repeated_m > 0.0 or longest_m > 0.0:
        return "repeated_edge"
    if retrace_segments(coords, min_leg_m=LOCAL_UTURN_MIN_LEG_M, close_m=LOCAL_UTURN_CLOSE_M):
        return "local_uturn"
    margin = STRICT_LOOP_CLOSURE_MARGIN_M if route.kind == "strict_loop" else 0.0
    returns = local_return_loops(
        coords,
        min_path_m=LOCAL_RETURN_PATH_MIN_M,
        close_m=LOCAL_RETURN_RADIUS_M,
        closure_margin_m=margin,
    )
    if returns:
        return "local_return_loop"
    return None


def edge_containment(route: FoundRoute, accepted_edges: set[int]) -> float:
    """Share of this route's road edges already spent by accepted siblings."""
    if not route.edge_path:
        return 1.0
    shared = sum(1 for edge_id in route.edge_path if edge_id in accepted_edges)
    return shared / len(route.edge_path)


def build_loop(
    graph: RoadGraph,
    index: EdgeIndex,
    anchor_key: int,
    target_m: float,
    tolerance: float,
    used_edges: dict[int, int],
    attempts_limit: int = TURNAROUND_LIMIT,
) -> FoundRoute | None:
    """Simple cycle of about ``target_m``: outbound path plus disjoint return."""
    low = target_m * (1.0 - tolerance)
    high = target_m * (1.0 + tolerance)
    base = dijkstra(graph, anchor_key, max_distance_m=target_m * LOOP_BASE_FACTOR)
    out_low = max(120.0, low * 0.34)
    out_high = high * 0.62
    origin = graph.nodes[anchor_key]
    turnarounds = [
        node
        for node, distance in base.dist.items()
        if node != anchor_key and out_low <= distance <= out_high
    ]
    # A closed ring is roughly twice the outbound leg, so aim the turnaround at
    # half the target first; straight-line separation only breaks ties, to keep
    # the ring open without chasing turnarounds that cannot be closed at all.
    turnarounds.sort(
        key=lambda node: (
            abs(2.0 * base.dist[node] - target_m),
            -haversine_m(origin, graph.nodes[node]),
            node,
        )
    )
    for turn in turnarounds[:attempts_limit]:
        out_nodes, out_edges = reconstruct(base, turn)
        if len(out_edges) < 3:
            continue
        out_coords = coords_from_edges(graph, out_nodes, out_edges)
        interior = set(out_nodes[1:-1])
        penalised = corridor_edges(index, out_coords, CORRIDOR_RADIUS_M)
        weight = corridor_weight(graph, penalised, used_edges)
        # No distance bound here: with a corridor weight the accumulated cost is
        # up to CORRIDOR_PENALTY times the true length, so a metre budget would
        # make the anchor unreachable on penalised roads. ``blocked`` alone keeps
        # the ring simple, and the graph is finite.
        back = dijkstra(graph, turn, blocked=interior, weight_fn=weight)
        back_nodes, back_edges = reconstruct(back, anchor_key)
        if len(back_edges) < 3:
            continue
        ring_nodes = out_nodes + back_nodes[1:]
        ring_edges = out_edges + back_edges
        route = make_route(graph, ring_nodes, ring_edges, "strict_loop", turnaround=turn)
        if low <= route.length_m <= high:
            return route
    return None


def one_way_candidates(
    graph: RoadGraph,
    anchor_key: int,
    base,  # type: ignore[no-untyped-def]
    target_m: float,
    tolerance: float,
    limit: int = ONE_WAY_CANDIDATE_LIMIT,
) -> list[int]:
    """Nodes inside the distance window, farthest straight-line separation first."""
    low = target_m * (1.0 - tolerance)
    high = target_m * (1.0 + tolerance)
    origin = graph.nodes[anchor_key]
    scored: list[tuple[float, int]] = []
    for node, distance in base.dist.items():
        if node == anchor_key or not low <= distance <= high:
            continue
        scored.append((-haversine_m(origin, graph.nodes[node]), node))
    scored.sort()
    return [node for _score, node in scored[:limit]]


def build_one_way(
    graph: RoadGraph,
    anchor_key: int,
    target_m: float,
    tolerance: float,
    used_edges: dict[int, int],
) -> FoundRoute | None:
    base = dijkstra(graph, anchor_key, max_distance_m=target_m * ONE_WAY_BASE_FACTOR)
    candidates = one_way_candidates(graph, anchor_key, base, target_m, tolerance)
    if not candidates:
        return None
    return pick_one_way(graph, base, anchor_key, target_m, tolerance, candidates, used_edges)


def build_sweep_one_way(
    graph: RoadGraph,
    index: EdgeIndex,
    anchor_key: int,
    target_m: float,
    tolerance: float,
    used_edges: dict[int, int],
    attempts_limit: int = SWEEP_TURNAROUND_LIMIT,
    endpoint_limit: int = SWEEP_ENDPOINT_LIMIT,
    turnaround_high_factor: float = SWEEP_TURNAROUND_HIGH_FACTOR,
    ideal_outbound: bool = False,
    screen: Callable[[FoundRoute, list[Coord]], str | None] | None = None,
    on_reject: Callable[[str], None] | None = None,
    accept_limit: int = SWEEP_SCREEN_ACCEPT_LIMIT,
) -> FoundRoute | None:
    """Open U-shaped arc of about ``target_m`` for distances no shortest path spans.

    ``build_one_way`` needs a node whose shortest-path distance already equals the
    target, which caps it at the network eccentricity: about 15 km over Xuhui's
    470 km bike graph in an 8.5 by 13.3 km district. A 25 km one-way therefore has
    no candidate for any anchor, and no amount of tolerance or anchor tuning can
    create one. Here the outbound leg runs to a turnaround and an interior-blocked
    second leg continues to a distant endpoint instead of closing the ring, so the
    reachable length roughly doubles while ``blocked`` still keeps every node, and
    therefore every edge, used at most once.

    What makes this hard rather than merely long is the circuity gate: a route of
    at least ``low`` metres has to end ``low / CIRCUITY_PRESCREEN`` metres from its
    start, so an anchor near the middle of an 8.5 km wide district has no reachable
    endpoint at all. The eccentricity test below discards those anchors for a few
    thousand distance calls instead of a full graph sweep.
    """
    low = target_m * (1.0 - tolerance)
    high = target_m * (1.0 + tolerance)
    origin = graph.nodes[anchor_key]
    min_separation = low / CIRCUITY_PRESCREEN
    #: Computed once per anchor: ``origin`` never moves, so the turnaround loop and
    #: the endpoint ranking can both read straight-line reach instead of measuring
    #: the same few thousand pairs again for every candidate.
    separation = {node: haversine_m(origin, coord) for node, coord in graph.nodes.items()}
    if max(separation.values(), default=0.0) < min_separation:
        return None
    base = dijkstra(graph, anchor_key, max_distance_m=target_m * LOOP_BASE_FACTOR)
    turnarounds = [
        node
        for node, distance in base.dist.items()
        if node != anchor_key and low * 0.40 <= distance <= high * turnaround_high_factor
    ]
    #: Longest outbound first leaves the smallest remaining budget, and a
    #: vertex-disjoint leg of a few kilometres is far easier to find than the
    #: fifteen a short outbound leg would demand. That reasoning is sound but it
    #: makes the ordering the worst possible one to truncate: measured on this
    #: run's bike graph (commands/probe_bike_band2.json and
    #: commands/probe_bike_band2_ordering.json), a 48-entry prefix of the
    #: longest-first list finds 1/0/30 feasible turnarounds on the three anchors
    #: that have any, where those same anchors' full windows hold 66/18/285.
    #: Ordering on proximity to half the target instead reaches the first feasible
    #: turnaround at scan rank 13/9/1 rather than 44/6/44, which is what lets a
    #: bounded budget reach the supply at all. Both orderings are equally blind on
    #: the other six qualified anchors - zero hits in 300 scans and zero in the
    #: full window - so this buys reach, not better geometry.
    if ideal_outbound:
        ideal_out = target_m * 0.5
        turnarounds.sort(key=lambda node: (abs(base.dist[node] - ideal_out), node))
    else:
        turnarounds.sort(key=lambda node: (-base.dist[node], node))
    #: Rejections the endpoint loop may absorb before this anchor is abandoned. It counts
    #: candidates screened, not turnarounds walked, so a turnaround whose every endpoint
    #: fails costs the same as one whose first endpoint fails.
    screened_out = 0
    for turn in turnarounds[:attempts_limit]:
        out_nodes, out_edges = reconstruct(base, turn)
        if len(out_edges) < 3:
            continue
        # ``base`` carries no weight_fn, so its distance is the true length in metres.
        out_length = base.dist[turn]
        needed = low - out_length
        excess = high - out_length
        # The anchor is blocked too: a return leg through the start would make the
        # arc a ring plus a tail, which is the long-stem shape the contract rejects.
        blocked = set(out_nodes[1:-1]) | {anchor_key}
        # Two sweeps from one source, and only the plain one decides feasibility.
        # Weighted cost cannot rank by length: a 6x corridor penalty makes a short
        # detour beside the outbound leg cost more than a long clean leg, so the
        # first version of this search reconstructed endpoints that were all far too
        # short and missed every 25 km candidate. The weighted sweep survives only
        # as a ratio, ranking candidates that stay off the outbound corridor and off
        # edges sibling routes already consumed.
        plain = dijkstra(graph, turn, blocked=blocked)
        #: The circuity predicate has to use the route's TOTAL length, because that is
        #: what the acceptance check below divides by the endpoint separation. Testing
        #: the return leg alone, or a constant ``low / CIRCUITY_PRESCREEN`` floor, looks
        #: equivalent but is not: an accepted route may be as long as ``high``, so
        #: endpoints between the two floors passed the filter and were then rejected,
        #: which is how the first exact-length version of this search lost three bike
        #: one-way slots it had previously filled.
        endpoints = [
            node
            for node, length in plain.dist.items()
            if node != turn
            and needed <= length <= excess
            and out_length + length <= separation[node] * CIRCUITY_PRESCREEN
        ]
        #: Corridor setup is deferred to here because the plain sweep above rejects
        #: the overwhelming majority of turnarounds outright, and a second full
        #: graph sweep plus a corridor query on each of them is the single largest
        #: cost in the long-bike search.
        if not endpoints:
            continue
        out_coords = coords_from_edges(graph, out_nodes, out_edges)
        penalised = corridor_edges(index, out_coords, CORRIDOR_RADIUS_M)
        weighted = dijkstra(graph, turn, blocked=blocked, weight_fn=corridor_weight(graph, penalised, used_edges))
        #: Cheapest detour first. The ratio is 1.0 for a leg that touches neither the
        #: outbound corridor nor an edge a sibling route already consumed, and grows to
        #: 6.0 and 3.0 respectively, so ranking on it is what keeps the reconstruction
        #: inside the edge-containment screen. Ranking on separation instead picks the
        #: most district-spanning legs, which are precisely the ones that reuse edges.
        endpoints.sort(
            key=lambda node: (
                weighted.dist.get(node, float("inf")) / plain.dist[node],
                -separation[node],
                node,
            )
        )
        for end in endpoints[:endpoint_limit]:
            back_nodes, back_edges = reconstruct(plain, end)
            if len(back_edges) < 3:
                continue
            route = make_route(graph, out_nodes + back_nodes[1:], out_edges + back_edges, "one_way")
            if not low <= route.length_m <= high:
                continue
            if route.length_m / separation[end] > CIRCUITY_PRESCREEN:
                continue
            if screen is None:
                return route
            #: Screening lives here rather than in ``_attempt`` because a rejection used
            #: to cost the whole anchor. Measured on the 2026-09-02 regeneration: raising
            #: the turnaround budget to 120 and ordering by proximity to half the target
            #: lifted ``bike:b2:candidates`` from 22 to 38, yet the portfolio stayed at 86
            #: routes because ``bike:b2:screen:local_return_loop`` went 0 -> 22 -- every new
            #: candidate was killed once, in ``_attempt``, and the sweep had already returned.
            #: Only 3 of the 9 anchors that clear the eccentricity prescreen hold any
            #: feasible 25 km pair (66/285/333 of them), so an anchor is far too scarce to
            #: spend on a single geometry. ``local_return_loops`` breaks once it has walked
            #: 4x its 200 m floor, so what it flags is this pair grazing the outbound
            #: corridor, not a property of every 25 km arc, and the next turnaround can pass.
            candidate_coords = douglas_peucker(route.coords, SIMPLIFY_TOLERANCE_M)
            reason = screen(route, candidate_coords)
            if reason is None:
                route.coords = candidate_coords
                return route
            screened_out += 1
            if on_reject is not None:
                on_reject(reason)
            if screened_out >= accept_limit:
                return None
    return None


def assign_route_ids(routes_by_mode: dict[str, list[GeneratedRoute]]) -> list[GeneratedRoute]:
    """XH_WALK_0001-0030, XH_RUN_0031-0060, XH_BIKE_0061-0090."""
    ordered: list[GeneratedRoute] = []
    for mode in MODES:
        offset = ID_OFFSET[mode]
        for position, route in enumerate(routes_by_mode.get(mode, []), start=1):
            route.route_id = f"{ID_PREFIX[mode]}_{offset + position:04d}"
            ordered.append(route)
    return ordered


#: Bounding-box slack in degrees, about 50 m, so the prefilter can never skip a
#: pair that ``overlap_ratio`` at 25 m tolerance would have flagged.
OVERLAP_BBOX_PAD_DEG = 0.0005


def worst_sibling_overlap(
    coords: Sequence[Coord], siblings: Sequence[Sequence[Coord]]
) -> float:
    """Worst share of one polyline running within 25 m of an accepted sibling.

    Both directions are measured: ``gates.same_mode_overlap`` only tests
    ``(first, second)`` in list order, and the ratio is asymmetric when the two
    routes differ in length, so the candidate has to survive whichever order the
    portfolio gate happens to see it in.
    """
    if not siblings:
        return 0.0
    box = bbox(coords)
    worst = 0.0
    for sibling in siblings:
        other = bbox(sibling)
        if (
            box[2] + OVERLAP_BBOX_PAD_DEG < other[0]
            or box[0] - OVERLAP_BBOX_PAD_DEG > other[2]
            or box[3] + OVERLAP_BBOX_PAD_DEG < other[1]
            or box[1] - OVERLAP_BBOX_PAD_DEG > other[3]
        ):
            continue
        ratio = max(overlap_ratio(coords, sibling), overlap_ratio(sibling, coords))
        if ratio > worst:
            worst = ratio
        if worst >= SAME_MODE_OVERLAP_MAX:
            return worst
    return worst


def _screen_reason(
    found: FoundRoute,
    simplified: list[Coord],
    *,
    mode: str,
    kind: str,
    slot: Slot,
    boundary: Ring,
    accepted_edges: set[int],
    long_bike: bool,
    include_overlap: bool = True,
    accepted_coords: Sequence[list[Coord]] = (),
) -> str | None:
    """Return the attempt-counter key for the first screen this route fails, else None.

    Pure: it mutates no counter, so the caller decides whether a rejection is worth
    recording. ``build_sweep_one_way`` calls it on every candidate it builds and keeps
    scanning on a rejection; ``_attempt`` calls it once more on whatever comes back,
    with the geometric-overlap test included.
    """
    screened = cheap_screen(found, slot.target_m, SEARCH_TOLERANCE)
    if screened is not None:
        return f"screen:{screened}"
    #: ``accepted_edges`` is per mode, so this measures the candidate against the
    #: union of every accepted sibling. For the long bike family that is arithmetic
    #: rather than similarity: the whole bike graph is 470.9 km (probe
    #: ``commands/probe_bike_band2_ordering.json``), ten 21.5-28.5 km arcs need
    #: 215-285 km of it and the mode asks for 440-510 km in total, so the union
    #: covers nearly every edge whatever the candidate is. The 2026-09-02
    #: regeneration lost 634 of its 770 bike band-2 candidates here; skipping it for
    #: the long bike family moves that counter to ``bike:b2:screen:edge_containment =
    #: 0`` and hands the decision to the contract's own pairwise test below, which
    #: then rejects 26 (``bike:b2:screen:geometric_overlap``, was 9). Union
    #: containment was never the real constraint — it was a proxy that measured
    #: arithmetic, and removing it replaced a false rejection with a true one.
    if not long_bike:
        containment = edge_containment(found, accepted_edges)
        if containment > EDGE_CONTAINMENT_MAX:
            return "screen:edge_containment"
    # Edge ids cannot see the opposite carriageway of a dual road: the two
    # directions are separate OSM ways, so a sibling running back beside this
    # one shares almost nothing by id while measuring a full geometric overlap.
    if include_overlap and (
        worst_sibling_overlap(simplified, accepted_coords) >= SAME_MODE_OVERLAP_MAX
    ):
        return "screen:geometric_overlap"
    probe = RouteInput(
        route_id="probe",
        mode=mode,
        kind=kind,
        target_m=slot.target_m,
        coords=simplified,
        band=slot.band,
        area="",
        navigation_nodes=2,
        start_marker=simplified[0],
        end_marker=simplified[-1],
        waypoints=(),
        long_distance=long_bike,
    )
    gate = evaluate_route(probe, boundary)
    if gate.failures:
        return "gate:" + ",".join(sorted(gate.failures))
    return None


def _attempt(
    graph: RoadGraph,
    index: EdgeIndex,
    slot: Slot,
    kind: str,
    anchors: Sequence[tuple[int, str]],
    accepted_edges: set[int],
    accepted_coords: Sequence[list[Coord]],
    used_edges: dict[int, int],
    attempts: dict[str, int],
    boundary: Ring,
) -> tuple[FoundRoute, list[Coord], int, str] | None:
    """Try each anchor in order; return the first route that survives screening."""
    #: Every reason is counted twice: once flat, once under this slot's mode and
    #: band. The flat totals say how hard the run worked overall; the tagged ones
    #: say *where* it failed. A portfolio that fills walk and run perfectly and
    #: leaves the long bike slots empty produces the same blended totals either
    #: way, and the blended number cannot distinguish "the search found nothing"
    #: from "the search found routes that a screen then rejected" — which are
    #: opposite problems needing opposite fixes.
    tag = f"{graph.mode}:b{slot.band}"
    #: Bike band-2 (20-30 km) is searched with deeper limits; see the constants.
    long_bike = graph.mode == "bike" and slot.band == DISTANCE_BANDS_PER_MODE - 1

    def bump(reason: str) -> None:
        attempts[reason] = attempts.get(reason, 0) + 1
        attempts[f"{tag}:{reason}"] = attempts.get(f"{tag}:{reason}", 0) + 1

    def sweep_screen(candidate: FoundRoute, candidate_coords: list[Coord]) -> str | None:
        #: Overlap is tested here as well as in ``_attempt`` below, so a rejection
        #: costs one candidate instead of the whole anchor. That matters only for
        #: this family, and only because of how scarce its anchors are: 7 of the 16
        #: bike anchors fail the eccentricity prescreen outright and 6 of the 9 that
        #: pass hold no feasible 25 km pair at all, so three anchors carry the entire
        #: band-2 one-way supply (66/285/333 pairs, ``commands/probe_bike_band2.json``
        #: and ``commands/probe_bike_band2_ordering.json``). While overlap was excluded
        #: here the sweep returned its first screen-clean candidate, ``_attempt`` found
        #: it overlapped an accepted sibling (``bike:b2:screen:geometric_overlap`` = 26
        #: of 35 candidates, the binding rejection for this family once the
        #: ``long_bike`` containment guard moved the decision to the pairwise test), and
        #: the ``continue`` below spent the rest of that anchor's supply to move on to
        #: an anchor that has none. Four 25 km one-way slots stayed empty and the mode
        #: finished at 27 routes.
        #:
        #: The cost is bounded by ``SWEEP_SCREEN_ACCEPT_LIMIT``, which counts screened
        #: candidates rather than endpoints walked, so an anchor attempt pays at most
        #: that many ``worst_sibling_overlap`` calls at a measured mean 0.0415 s and max
        #: 0.064 s on band-2 geometry (``commands/probe_overlap_grid.json``). Most
        #: anchor attempts pay none: the plain sweep at ``build_sweep_one_way`` rejects
        #: the overwhelming majority of turnarounds before a candidate exists.
        #: ``_attempt`` re-runs the same test on whatever comes back, so this changes
        #: recall and cost only, never what is accepted.
        return _screen_reason(
            candidate,
            candidate_coords,
            mode=graph.mode,
            kind="one_way",
            slot=slot,
            boundary=boundary,
            accepted_edges=accepted_edges,
            long_bike=long_bike,
            include_overlap=True,
            accepted_coords=accepted_coords,
        )

    for anchor_key, origin in anchors:
        bump("anchor_tries")
        if kind == "strict_loop":
            found = build_loop(graph, index, anchor_key, slot.target_m, SEARCH_TOLERANCE, used_edges)
        else:
            found = build_one_way(
                graph, anchor_key, slot.target_m, SEARCH_TOLERANCE, used_edges
            )
            if found is None:
                found = build_sweep_one_way(
                    graph,
                    index,
                    anchor_key,
                    slot.target_m,
                    SEARCH_TOLERANCE,
                    used_edges,
                    attempts_limit=(
                        LONG_BIKE_SWEEP_TURNAROUND_LIMIT if long_bike else SWEEP_TURNAROUND_LIMIT
                    ),
                    endpoint_limit=(
                        LONG_BIKE_SWEEP_ENDPOINT_LIMIT if long_bike else SWEEP_ENDPOINT_LIMIT
                    ),
                    turnaround_high_factor=(
                        LONG_BIKE_TURNAROUND_HIGH_FACTOR
                        if long_bike
                        else SWEEP_TURNAROUND_HIGH_FACTOR
                    ),
                    ideal_outbound=long_bike,
                    screen=sweep_screen if long_bike else None,
                    on_reject=bump if long_bike else None,
                    accept_limit=SWEEP_SCREEN_ACCEPT_LIMIT,
                )
        if found is None:
            bump("search_miss")
            continue
        bump("candidates")
        simplified = douglas_peucker(found.coords, SIMPLIFY_TOLERANCE_M)
        #: For the long-bike family the sweep has already run these predicates minus
        #: the geometric-overlap test on every candidate it built, so this call is a
        #: confirmation rather than the first look. For every other slot it is the only
        #: look, exactly as before.
        reason = _screen_reason(
            found,
            simplified,
            mode=graph.mode,
            kind=kind,
            slot=slot,
            boundary=boundary,
            accepted_edges=accepted_edges,
            long_bike=long_bike,
            accepted_coords=accepted_coords,
        )
        if reason is not None:
            bump(reason)
            continue
        attempts["accepted"] += 1
        found.coords = simplified
        return found, simplified, anchor_key, origin
    return None


def _mode_anchors(
    graph: RoadGraph, areas: Sequence[ResolvedArea], boundary: Ring, box: BoundaryBox
) -> tuple[list[tuple[int, str]], list[int]]:
    pool = anchor_pool(graph, boundary, box)
    generic = spread_anchors(graph, pool, SPREAD_ANCHOR_COUNT)
    anchors = [(area.node_key, f"area:{area.area_id}") for area in areas if area.node_key is not None]
    anchors.extend((key, "spread") for key in generic)
    return anchors, pool


def _retry_anchors(pool: Sequence[int], count: int = RETRY_ANCHOR_COUNT) -> list[tuple[int, str]]:
    if not pool:
        return []
    stride = max(1, len(pool) // count)
    return [(pool[position], "retry") for position in range(0, len(pool), stride)][:count]


def generate_portfolio(sources_dir: Path) -> Portfolio:
    """Build, gate and score the full 90-route portfolio from the run's sources."""
    boundary = boundary_from_geojson(load_json(sources_dir / "xuhui_boundary.geojson"))
    highways = load_json(sources_dir / "osm_xuhui_highways.json")
    pois = load_json(sources_dir / "osm_xuhui_pois.json")
    box = bbox(list(boundary))

    areas = resolve_areas(list(pois.get("elements") or []), boundary)
    log: list[str] = [
        f"boundary_ring_vertices={len(boundary)}",
        f"boundary_bbox={tuple(round(value, 6) for value in box)}",
        f"crs={highways.get('crs') or CRS_WGS84}",
    ]

    attempts: dict[str, int] = {
        "anchor_tries": 0,
        "search_miss": 0,
        "candidates": 0,
        "accepted": 0,
    }
    kind_swaps: list[dict[str, Any]] = []
    unfilled: list[dict[str, Any]] = []
    graph_stats: dict[str, dict[str, Any]] = {}
    routes_by_mode: dict[str, list[GeneratedRoute]] = {mode: [] for mode in MODES}

    for mode in MODES:
        graph = district_graph(highways, mode, boundary, box)
        graph_stats[mode] = graph.stats()
        attach_nodes(areas, graph)
        anchors, pool = _mode_anchors(graph, areas, boundary, box)
        index = build_edge_index(graph)
        retries = _retry_anchors(pool)
        accepted_edges: set[int] = set()
        accepted_coords: list[list[Coord]] = []
        used_edges: dict[int, int] = {}
        log.append(
            f"{mode}: nodes={graph_stats[mode]['node_count']} "
            f"edges={graph_stats[mode]['edge_count']} anchors={len(anchors)} pool={len(pool)}"
        )

        slots = slot_plan(mode)
        #: Bike attempts its band-2 one-ways before any other bike slot; everything else
        #: keeps the planned order. Two cheaper explanations have already been measured
        #: and ruled out. Reordering band 2 so its one-ways picked ahead of its own five
        #: 21-27 km rings moved nothing (88 routes and 601
        #: ``screen:geometric_overlap`` rejections both ways), so the band's loops are not
        #: the competitor. Widening the screening window from ``SWEEP_SCREEN_ACCEPT_LIMIT``
        #: 48 to 400 let the sweep examine roughly 2800 more band-2 candidates and reject
        #: all of them -- 564 ``screen:local_uturn`` and 1284
        #: ``gate:branch_or_self_intersection``, neither of which appeared at 48 -- while
        #: ``bike:b2:candidates`` stayed at 11 and the portfolio at 88, for double the
        #: stage time (290 s -> 556 s). So the extra geometry is not merely crowded, it
        #: is topologically broken once other routes are on the board.
        #:
        #: The remaining competitor is the twenty bike band-0 and band-1 routes, which are
        #: accepted into ``accepted_edges``/``accepted_coords``/``used_edges`` before band
        #: 2 ever runs and fragment the long north-south corridors a 25 km one-way needs.
        #: Only three of the sixteen bike anchors hold a feasible 25 km pair at all
        #: (66/285/333 pairs, ``commands/probe_bike_band2.json``), and the district bbox
        #: spans just 8.1 km x 13.2 km, so those corridors are the whole supply.
        #:
        #: Measured: the hoist fills all 90 slots with no kind swap and no unfilled
        #: slot, bike lands on exactly 15 loops and 15 one-ways, and the stage gets
        #: faster rather than slower, 290 s -> 112 s, because band 2 stops burning
        #: 210 anchor tries and needs 55 (``route_catalog.json``
        #: ``generation_diagnostics.attempts``). Bands 0 and 1 pay nothing for the
        #: empty graph -- both still fill 10 of 10 -- because loops are the steerable
        #: kind: ``build_loop`` weights its return leg through ``corridor_weight``
        #: against ``used_edges``.
        #: Only the attempt sequence moves: ``slots`` stays in ``slot_plan`` order and
        #: ``filled`` is keyed by ``slot.index``, so ``assign_route_ids`` below hands
        #: out the same ids either way. An unfilled one-way slot is still converted to
        #: a loop by the swap pass, and an unfilled loop slot converts down to a
        #: one-way until bike reaches the 14-loop ``LOOP_COUNT_RANGE`` floor.
        if mode == "bike":
            last_band = DISTANCE_BANDS_PER_MODE - 1
            first = [
                slot for slot in slots if slot.band == last_band and slot.kind == "one_way"
            ]
            middle = [slot for slot in slots if slot.band != last_band]
            last = [
                slot
                for slot in slots
                if slot.band == last_band and slot.kind != "one_way"
            ]
            attempt_order = first + middle + last
        else:
            attempt_order = slots
        pending: list[tuple[Slot, str]] = [(slot, slot.kind) for slot in attempt_order]
        filled: dict[int, GeneratedRoute] = {}
        loop_count = sum(1 for _slot, kind in pending if kind == "strict_loop")

        for pass_name, anchor_set in (("primary", anchors), ("retry", anchors + retries)):
            if not pending:
                break
            still_pending: list[tuple[Slot, str]] = []
            for slot, kind in pending:
                ordered = anchor_order(anchor_set, slot.area_id)
                outcome = _attempt(
                    graph,
                    index,
                    slot,
                    kind,
                    ordered,
                    accepted_edges,
                    accepted_coords,
                    used_edges,
                    attempts,
                    boundary,
                )
                if outcome is None:
                    still_pending.append((slot, kind))
                    continue
                found, simplified, anchor_key, origin = outcome
                area_id = nearest_area(simplified[0], areas)
                accepted_edges.update(found.edge_path)
                accepted_coords.append(simplified)
                for edge_id in found.edge_path:
                    used_edges[edge_id] = used_edges.get(edge_id, 0) + 1
                filled[slot.index] = GeneratedRoute(
                    route_id="pending",
                    mode=mode,
                    kind=kind,
                    plan_kind=slot.kind,
                    band=slot.band,
                    area=area_id,
                    anchor_area_id=slot.area_id,
                    target_m=slot.target_m,
                    actual_distance_m=polyline_length_m(simplified),
                    coords=simplified,
                    edge_path=list(found.edge_path),
                    anchor_key=anchor_key,
                    anchor_origin=origin,
                    metrics=dict(found.diagnostics),
                )
                log.append(
                    f"{mode} slot{slot.index} {kind} band{slot.band} -> {origin} "
                    f"{found.length_m:.0f} m ({pass_name})"
                )
            pending = still_pending

        # Last resort: swap the kind of a slot that no anchor could fill, keeping
        # the band total at ten and the mode loop total inside 14-16.
        for slot, kind in pending:
            swapped = "one_way" if kind == "strict_loop" else "strict_loop"
            if swapped == "strict_loop" and loop_count >= LOOP_COUNT_RANGE[1]:
                continue
            if swapped == "one_way" and loop_count <= LOOP_COUNT_RANGE[0]:
                continue
            ordered = anchor_order(anchors + retries, slot.area_id)
            outcome = _attempt(
                graph,
                index,
                slot,
                swapped,
                ordered,
                accepted_edges,
                accepted_coords,
                used_edges,
                attempts,
                boundary,
            )
            if outcome is None:
                continue
            found, simplified, anchor_key, origin = outcome
            area_id = nearest_area(simplified[0], areas)
            accepted_edges.update(found.edge_path)
            accepted_coords.append(simplified)
            for edge_id in found.edge_path:
                used_edges[edge_id] = used_edges.get(edge_id, 0) + 1
            if swapped == "strict_loop":
                loop_count += 1
            else:
                loop_count -= 1
            filled[slot.index] = GeneratedRoute(
                route_id="pending",
                mode=mode,
                kind=swapped,
                plan_kind=slot.kind,
                band=slot.band,
                area=area_id,
                anchor_area_id=slot.area_id,
                target_m=slot.target_m,
                actual_distance_m=polyline_length_m(simplified),
                coords=simplified,
                edge_path=list(found.edge_path),
                anchor_key=anchor_key,
                anchor_origin=origin,
                metrics=dict(found.diagnostics),
            )
            kind_swaps.append(
                {
                    "mode": mode,
                    "slot_index": slot.index,
                    "band": slot.band,
                    "planned_kind": slot.kind,
                    "actual_kind": swapped,
                    "reason": "no anchor produced an acceptable route of the planned kind",
                }
            )
            log.append(f"{mode} slot{slot.index} kind swap {slot.kind} -> {swapped}")

        for slot in slots:
            route = filled.get(slot.index)
            if route is None:
                unfilled.append(
                    {
                        "mode": mode,
                        "slot_index": slot.index,
                        "band": slot.band,
                        "planned_kind": slot.kind,
                        "target_m": slot.target_m,
                        "preferred_area_id": slot.area_id,
                    }
                )
                log.append(f"{mode} slot{slot.index} UNFILLED")
                continue
            routes_by_mode[mode].append(route)

    routes = assign_route_ids(routes_by_mode)
    inputs: list[RouteInput] = []
    for route in routes:
        inputs.append(
            RouteInput(
                route_id=route.route_id,
                mode=route.mode,
                kind=route.kind,
                target_m=route.target_m,
                coords=route.coords,
                band=route.band,
                area=route.area,
                navigation_nodes=2,
                start_marker=route.coords[0],
                end_marker=route.coords[-1],
                waypoints=(),
                long_distance=(route.mode == "bike" and route.band == DISTANCE_BANDS_PER_MODE - 1),
            )
        )
    results = [evaluate_route(item, boundary) for item in inputs]
    for route, result in zip(routes, results, strict=True):
        route.metrics.update(
            {key: value for key, value in result.metrics.items() if key not in route.metrics}
        )

    portfolio = evaluate_portfolio(inputs, results, AREA_IDS, BANDS_KM)
    area_coverage: dict[str, int] = {area_id: 0 for area_id in AREA_IDS}
    kind_counts: dict[str, int] = {"strict_loop": 0, "one_way": 0}
    band_counts: dict[str, dict[int, int]] = {mode: {} for mode in MODES}
    for route in routes:
        area_coverage[route.area] = area_coverage.get(route.area, 0) + 1
        kind_counts[route.kind] = kind_counts.get(route.kind, 0) + 1
        per_band = band_counts[route.mode]
        per_band[route.band] = per_band.get(route.band, 0) + 1
    log.append(
        f"portfolio routes={len(routes)} accepted={portfolio.get('accepted_count')} "
        f"failures={portfolio.get('failures')}"
    )

    return Portfolio(
        routes=routes,
        inputs=inputs,
        results=results,
        portfolio=portfolio,
        areas=list(areas),
        boundary=boundary,
        graph_stats=graph_stats,
        area_coverage=area_coverage,
        kind_counts=kind_counts,
        band_counts=band_counts,
        attempts=attempts,
        kind_swaps=kind_swaps,
        unfilled_slots=unfilled,
        log=log,
    )
