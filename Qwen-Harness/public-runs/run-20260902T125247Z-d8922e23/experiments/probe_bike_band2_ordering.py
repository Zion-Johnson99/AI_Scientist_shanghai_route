"""Decide the turnaround ordering for bike band-2 (20-30 km) one-way slots.

Probe 1 established two facts. First, the longest-outbound-first prefix that
``build_sweep_one_way`` iterates sees almost nothing: over the whole window the
same anchors admit 66 / 18 / 285 / 333 feasible (turnaround, endpoint) pairs
while the first 48 entries admit 1 / 0 / 30 / 1. Second, the pairs the prefix
does find sit at circuity 2.35-2.38, hard against the 2.4 prescreen ceiling,
while the pairs found over the whole window sit at 2.00-2.23. A route that
detours to 2.4x the straight-line span runs beside its own outbound leg, which
is exactly what the edge-containment screen rejects. So raising the attempt
limit buys supply of the wrong kind.

This probe tests the ordering hypothesis directly: does sorting turnarounds by
distance from the symmetric half-target (``target * 0.5``) surface feasible,
low-circuity pairs within a small, affordable budget? It reports, per anchor and
per ordering, how many turnarounds had to be scanned before the first feasible
pair appeared and the best circuity reached inside that budget.

Read-only. It reuses the generator's own setup so the numbers describe the real
search. Writes JSON to stdout. No file is modified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RUN_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = RUN_ROOT / "workspace" / "source"
sys.path.insert(0, str(SOURCE_ROOT))

from routes.areas import attach_nodes  # noqa: E402
from routes.generator import (  # noqa: E402
    CIRCUITY_PRESCREEN,
    LONG_BIKE_TURNAROUND_HIGH_FACTOR,
    LOOP_BASE_FACTOR,
    SEARCH_TOLERANCE,
    _mode_anchors,
    band_targets,
    boundary_from_geojson,
    build_edge_index,
    district_graph,
    load_json,
    resolve_areas,
)
from routes.geometry import bbox, haversine_m  # noqa: E402
from routes.search import dijkstra, reconstruct  # noqa: E402

#: Per-ordering scan budget. Probe 1 showed a full window scan costs 15 ms per
#: unbounded Dijkstra, so 300 turnarounds is about 4.5 s per anchor per ordering.
SCAN_BUDGET = 300
#: Stop early once this many feasible turnarounds are in hand; the first-hit rank
#: is the decision-relevant number, not the full census.
HIT_TARGET = 5
#: Symmetric there-and-back outbound length the new ordering aims at.
IDEAL_OUT_FACTOR = 0.5


def scan(
    graph: Any,
    anchor_key: int,
    order: list[int],
    base: Any,
    separation: dict[int, float],
    low: float,
    high: float,
) -> dict[str, Any]:
    """Walk ``order`` until ``HIT_TARGET`` feasible turnarounds or ``SCAN_BUDGET``."""
    scanned = 0
    hits = 0
    first_hit_rank: int | None = None
    first_hit: dict[str, Any] | None = None
    lowest_circuity: dict[str, Any] | None = None
    out_lengths: list[float] = []

    for turn in order[:SCAN_BUDGET]:
        out_nodes, out_edges = reconstruct(base, turn)
        if len(out_edges) < 3:
            continue
        scanned += 1
        out_length = base.dist[turn]
        out_lengths.append(out_length)
        needed = low - out_length
        excess = high - out_length
        if excess <= 0:
            continue
        blocked = set(out_nodes[1:-1]) | {anchor_key}
        plain = dijkstra(graph, turn, blocked=blocked)
        ends = [
            node
            for node, length in plain.dist.items()
            if node != turn
            and needed <= length <= excess
            and out_length + length <= separation[node] * CIRCUITY_PRESCREEN
        ]
        if not ends:
            continue
        hits += 1
        ends.sort(key=lambda n: (-separation[n], n))
        end = ends[0]
        total = out_length + plain.dist[end]
        record = {
            "turn_node": turn,
            "out_length_m": round(out_length, 1),
            "return_length_m": round(plain.dist[end], 1),
            "total_m": round(total, 1),
            "separation_end_m": round(separation[end], 1),
            "circuity": round(total / separation[end], 3),
            "endpoint_candidates": len(ends),
            "found_at_scanned": scanned,
        }
        if first_hit is None:
            first_hit_rank = scanned
            first_hit = record
        if lowest_circuity is None or record["circuity"] < lowest_circuity["circuity"]:
            lowest_circuity = record
        if hits >= HIT_TARGET:
            break

    return {
        "scanned": scanned,
        "hits": hits,
        "first_hit_rank": first_hit_rank,
        "first_hit": first_hit,
        "lowest_circuity_hit": lowest_circuity,
        "out_length_min_m": round(min(out_lengths), 1) if out_lengths else None,
        "out_length_max_m": round(max(out_lengths), 1) if out_lengths else None,
    }


def main() -> int:
    sources = RUN_ROOT / "sources"
    boundary = boundary_from_geojson(load_json(sources / "xuhui_boundary.geojson"))
    highways = load_json(sources / "osm_xuhui_highways.json")
    pois = load_json(sources / "osm_xuhui_pois.json")
    box = bbox(list(boundary))
    areas = resolve_areas(list(pois.get("elements") or []), boundary)

    graph = district_graph(highways, "bike", boundary, box)
    attach_nodes(areas, graph)
    anchors, pool = _mode_anchors(graph, areas, boundary, box)
    build_edge_index(graph)

    target_m = band_targets("bike")[2]
    low = target_m * (1.0 - SEARCH_TOLERANCE)
    high = target_m * (1.0 + SEARCH_TOLERANCE)
    ideal_out = target_m * IDEAL_OUT_FACTOR
    min_separation = low / CIRCUITY_PRESCREEN

    report: dict[str, Any] = {
        "mode": "bike",
        "band": 2,
        "target_m": target_m,
        "low_m": round(low, 1),
        "high_m": round(high, 1),
        "ideal_out_m": round(ideal_out, 1),
        "min_separation_m": round(min_separation, 1),
        "base_cap_m": round(target_m * LOOP_BASE_FACTOR, 1),
        "circuity_prescreen": CIRCUITY_PRESCREEN,
        "scan_budget": SCAN_BUDGET,
        "hit_target": HIT_TARGET,
        "graph": graph.stats(),
        "anchor_count": len(anchors),
        "pool_count": len(pool),
        "anchors": [],
    }

    qualified = 0
    ideal_first_ranks: list[int] = []
    longest_first_ranks: list[int] = []

    for anchor_key, origin in anchors:
        coord = graph.nodes[anchor_key]
        separation = {
            node: haversine_m(coord, other) for node, other in graph.nodes.items()
        }
        max_sep = max(separation.values(), default=0.0)
        entry: dict[str, Any] = {"origin": origin, "anchor_key": anchor_key}
        if max_sep < min_separation:
            entry["early_out"] = True
            entry["max_separation_m"] = round(max_sep, 1)
            report["anchors"].append(entry)
            continue
        qualified += 1
        entry["early_out"] = False
        entry["max_separation_m"] = round(max_sep, 1)

        base = dijkstra(graph, anchor_key, max_distance_m=target_m * LOOP_BASE_FACTOR)
        window = [
            node
            for node, distance in base.dist.items()
            if node != anchor_key
            and low * 0.40 <= distance <= high * LONG_BIKE_TURNAROUND_HIGH_FACTOR
        ]
        entry["turnarounds_in_window"] = len(window)

        ideal_order = sorted(window, key=lambda n: (abs(base.dist[n] - ideal_out), n))
        longest_order = sorted(window, key=lambda n: (-base.dist[n], n))

        entry["ideal_first"] = scan(
            graph, anchor_key, ideal_order, base, separation, low, high
        )
        entry["longest_first"] = scan(
            graph, anchor_key, longest_order, base, separation, low, high
        )
        if entry["ideal_first"]["first_hit_rank"] is not None:
            ideal_first_ranks.append(entry["ideal_first"]["first_hit_rank"])
        if entry["longest_first"]["first_hit_rank"] is not None:
            longest_first_ranks.append(entry["longest_first"]["first_hit_rank"])
        report["anchors"].append(entry)

    report["qualified_anchors_examined"] = qualified
    report["ideal_first_first_hit_ranks"] = ideal_first_ranks
    report["longest_first_first_hit_ranks"] = longest_first_ranks
    report["ideal_first_hit_anchor_count"] = len(ideal_first_ranks)
    report["longest_first_hit_anchor_count"] = len(longest_first_ranks)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
