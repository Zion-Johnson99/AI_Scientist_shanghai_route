"""Graph search primitives used by the Xuhui route generator.

All distances are metres computed from real OSM geometry. Nothing here reads or
depends on the repository's existing route data; the only inputs are the road
graph built in this run and the district boundary fetched in this run.
"""

from __future__ import annotations

import heapq
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from .geometry import Coord, haversine_m, polyline_length_m
from .road_graph import RoadGraph

WeightFn = Callable[[int], float]


@dataclass(slots=True)
class DijkstraResult:
    source: int
    dist: dict[int, float]
    prev: dict[int, tuple[int, int]]


@dataclass(slots=True)
class FoundRoute:
    node_path: list[int]
    edge_path: list[int]
    coords: list[Coord]
    length_m: float
    kind: str
    turnaround: int | None = None
    diagnostics: dict[str, float | int | bool] = field(default_factory=dict)


def dijkstra(
    graph: RoadGraph,
    source: int,
    blocked: Iterable[int] | None = None,
    weight_fn: WeightFn | None = None,
    max_distance_m: float | None = None,
) -> DijkstraResult:
    """Single-source shortest path over the undirected road graph.

    ``blocked`` removes interior nodes (used to force a vertex-disjoint return
    leg so that an out-and-back becomes a genuine simple cycle). ``weight_fn``
    maps an edge id to a non-negative cost, letting the generator steer away from
    edges already consumed by sibling routes without changing true lengths.
    """
    if source not in graph.nodes:
        return DijkstraResult(source=source, dist={}, prev={})
    blocked_set = set(blocked or ())
    blocked_set.discard(source)
    dist: dict[int, float] = {source: 0.0}
    prev: dict[int, tuple[int, int]] = {}
    heap: list[tuple[float, int]] = [(0.0, source)]
    settled: set[int] = set()
    while heap:
        cost, node = heapq.heappop(heap)
        if node in settled:
            continue
        settled.add(node)
        if max_distance_m is not None and cost > max_distance_m:
            continue
        for neighbour, edge_id in graph.adjacency.get(node, ()):
            if neighbour in blocked_set:
                continue
            edge = graph.edges[edge_id]
            step = edge.length_m if weight_fn is None else weight_fn(edge_id)
            candidate = cost + step
            if candidate < dist.get(neighbour, float("inf")):
                dist[neighbour] = candidate
                prev[neighbour] = (node, edge_id)
                heapq.heappush(heap, (candidate, neighbour))
    return DijkstraResult(source=source, dist=dist, prev=prev)


def reconstruct(result: DijkstraResult, target: int) -> tuple[list[int], list[int]]:
    """Return (node_path, edge_path) from source to target, or empty lists."""
    if target not in result.dist and target != result.source:
        return [], []
    nodes = [target]
    edges: list[int] = []
    cursor = target
    guard = 0
    while cursor != result.source:
        if cursor not in result.prev:
            return [], []
        parent, edge_id = result.prev[cursor]
        edges.append(edge_id)
        nodes.append(parent)
        cursor = parent
        guard += 1
        if guard > 200_000:
            return [], []
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def true_length(graph: RoadGraph, edge_path: Sequence[int]) -> float:
    return float(sum(graph.edges[edge_id].length_m for edge_id in edge_path))


def coords_from_edges(
    graph: RoadGraph, node_path: Sequence[int], edge_path: Sequence[int]
) -> list[Coord]:
    """Stitch oriented way geometries into a single continuous polyline."""
    coords: list[Coord] = []
    for index, edge_id in enumerate(edge_path):
        edge = graph.edges[edge_id]
        segment = list(edge.oriented_coords(node_path[index]))
        if coords and segment and segment[0] == coords[-1]:
            segment = segment[1:]
        coords.extend(segment)
    if not coords and node_path:
        coords = [graph.nodes[node_path[0]]]
    return coords


def make_route(graph: RoadGraph, node_path: Sequence[int], edge_path: Sequence[int], kind: str, **extra: object) -> FoundRoute:
    coords = coords_from_edges(graph, node_path, edge_path)
    length = polyline_length_m(coords) if coords else 0.0
    diagnostics: dict[str, float | int | bool] = {
        "edge_sum_m": round(true_length(graph, edge_path), 2),
        "node_count": len(node_path),
    }
    diagnostics.update({k: v for k, v in extra.items() if isinstance(v, (int, float, bool))})
    turnaround = extra.get("turnaround")
    return FoundRoute(
        node_path=list(node_path),
        edge_path=list(edge_path),
        coords=coords,
        length_m=length,
        kind=kind,
        turnaround=turnaround if isinstance(turnaround, int) else None,
        diagnostics=diagnostics,
    )


def band_of(value_m: float, bands: Sequence[tuple[float, float]]) -> int:
    for index, (low, high) in enumerate(bands):
        if low * 1000.0 <= value_m < high * 1000.0:
            return index
    return -1


def pick_one_way(
    graph: RoadGraph,
    result: DijkstraResult,
    source: int,
    target_m: float,
    tolerance: float,
    candidates: Sequence[int],
    used_edges: dict[int, int] | None = None,
) -> FoundRoute | None:
    """Choose a destination whose true graph distance lands inside the band.

    Preference order: inside the distance window, then maximal straight-line
    separation from the start (avoids meandering stubs), then minimal reuse of
    edges already spent by sibling routes.
    """
    low = target_m * (1.0 - tolerance)
    high = target_m * (1.0 + tolerance)
    used = used_edges or {}
    scored: list[tuple[float, int]] = []
    for node in candidates:
        if node == source or node not in result.dist:
            continue
        dist_m = result.dist[node]
        if not (low <= dist_m <= high):
            continue
        node_path, edge_path = reconstruct(result, node)
        if len(edge_path) < 4:
            continue
        reuse = sum(used.get(edge_id, 0) for edge_id in edge_path)
        straight = haversine_m(graph.nodes[source], graph.nodes[node])
        score = reuse * 400.0 - straight
        scored.append((score, node))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    best = scored[0][1]
    node_path, edge_path = reconstruct(result, best)
    return make_route(graph, node_path, edge_path, "one_way")


def find_loop(
    graph: RoadGraph,
    source: int,
    target_m: float,
    tolerance: float,
    result: DijkstraResult | None = None,
    weight_fn: WeightFn | None = None,
    rng: random.Random | None = None,
    attempts: int = 24,
) -> FoundRoute | None:
    """Build a genuine simple cycle of roughly ``target_m`` metres.

    The outbound leg is a shortest path source -> t. The return leg is a shortest
    path t -> source computed with every interior outbound node blocked, so the
    two legs are vertex-disjoint apart from their shared endpoints. The union is
    therefore one connected component with cycle rank 1 and every node of degree
    2, which rules out double loops, dumbbells, gourd shapes and long stems by
    construction rather than by post-hoc filtering.
    """
    base = result if result is not None else dijkstra(graph, source)
    low = target_m * (1.0 - tolerance)
    high = target_m * (1.0 + tolerance)
    out_low = max(120.0, low * 0.34)
    out_high = high * 0.62
    turnarounds = [
        (dist_m, node)
        for node, dist_m in base.dist.items()
        if node != source and out_low <= dist_m <= out_high
    ]
    if not turnarounds:
        return None
    # Prefer turnarounds far from the start in a straight line: that pushes the
    # ring open instead of producing a tight out-and-back hairpin.
    turnarounds.sort(
        key=lambda item: (-haversine_m(graph.nodes[source], graph.nodes[item[1]]), item[0])
    )
    picks = turnarounds[: max(attempts * 3, 12)]
    if rng is not None:
        rng.shuffle(picks)
    for _, turn in picks[:attempts]:
        out_nodes, out_edges = reconstruct(base, turn)
        if len(out_edges) < 3:
            continue
        interior = set(out_nodes[1:-1])
        back = dijkstra(graph, turn, blocked=interior, weight_fn=weight_fn)
        back_nodes, back_edges = reconstruct(back, source)
        if len(back_edges) < 3:
            continue
        ring_nodes = out_nodes + back_nodes[1:]
        ring_edges = out_edges + back_edges
        route = make_route(
            graph,
            ring_nodes,
            ring_edges,
            "strict_loop",
            turnaround=turn,
            outbound_m=round(true_length(graph, out_edges), 2),
            return_m=round(true_length(graph, back_edges), 2),
        )
        if low <= route.length_m <= high:
            return route
    return None


def relax_until(
    graph: RoadGraph,
    builder: Callable[[float], FoundRoute | None],
    target_m: float,
    tolerance: float,
    ladder: Sequence[float] = (1.0, 1.35, 1.7, 2.2),
) -> FoundRoute | None:
    """Widen the acceptance window step by step before giving up."""
    for factor in ladder:
        route = builder(tolerance * factor)
        if route is not None:
            return route
    return None
