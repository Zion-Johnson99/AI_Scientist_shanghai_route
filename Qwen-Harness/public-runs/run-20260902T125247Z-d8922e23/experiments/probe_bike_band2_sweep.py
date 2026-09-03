"""Measure why bike band-2 (20-30 km) one-way slots stay empty.

Read-only diagnostic. It reuses the generator's own setup so the numbers describe
the real search, then answers one question per anchor: does ``build_sweep_one_way``
fail because no feasible (turnaround, endpoint) pair exists, or because the pair
that exists sits outside the first ``attempts_limit`` entries of a list sorted
longest-outbound-first?

Writes JSON to stdout. No file is modified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RUN_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = RUN_ROOT / "workspace" / "source"
sys.path.insert(0, str(SOURCE_ROOT))

from routes.generator import (  # noqa: E402
    CIRCUITY_PRESCREEN,
    LONG_BIKE_SWEEP_TURNAROUND_LIMIT,
    LONG_BIKE_TURNAROUND_HIGH_FACTOR,
    LOOP_BASE_FACTOR,
    SEARCH_TOLERANCE,
    SWEEP_TURNAROUND_HIGH_FACTOR,
    SWEEP_TURNAROUND_LIMIT,
    _mode_anchors,
    band_targets,
    boundary_from_geojson,
    build_edge_index,
    district_graph,
    load_json,
    resolve_areas,
)
from routes.areas import attach_nodes  # noqa: E402
from routes.geometry import bbox, haversine_m  # noqa: E402
from routes.search import dijkstra, reconstruct  # noqa: E402


def stride_pick(items: list[int], limit: int) -> list[int]:
    """Evenly spaced sample across the whole sorted list, longest-first order kept."""
    if limit >= len(items):
        return list(items)
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def feasible_pairs(
    graph: Any,
    anchor_key: int,
    target_m: float,
    turnarounds: list[int],
    base: Any,
    separation: dict[int, float],
    low: float,
    high: float,
) -> dict[str, Any]:
    """Count turnarounds that admit at least one circuity-legal endpoint."""
    hits = 0
    best: dict[str, Any] | None = None
    out_lengths: list[float] = []
    for turn in turnarounds:
        out_nodes, _out_edges = reconstruct(base, turn)
        if len(_out_edges) < 3:
            continue
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
        if ends:
            hits += 1
            ends.sort(key=lambda n: (-separation[n], n))
            end = ends[0]
            total = out_length + plain.dist[end]
            if best is None or total > float(best["total_m"]):
                best = {
                    "turn_node": turn,
                    "out_length_m": round(out_length, 1),
                    "end_node": end,
                    "return_length_m": round(plain.dist[end], 1),
                    "total_m": round(total, 1),
                    "separation_end_m": round(separation[end], 1),
                    "circuity": round(total / separation[end], 3),
                    "endpoint_candidates": len(ends),
                }
    return {
        "turnarounds_tried": len(turnarounds),
        "turnarounds_with_endpoint": hits,
        "out_length_min_m": round(min(out_lengths), 1) if out_lengths else None,
        "out_length_max_m": round(max(out_lengths), 1) if out_lengths else None,
        "best": best,
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
    min_separation = low / CIRCUITY_PRESCREEN

    report: dict[str, Any] = {
        "mode": "bike",
        "band": 2,
        "target_m": target_m,
        "low_m": round(low, 1),
        "high_m": round(high, 1),
        "min_separation_m": round(min_separation, 1),
        "base_cap_m": round(target_m * LOOP_BASE_FACTOR, 1),
        "circuity_prescreen": CIRCUITY_PRESCREEN,
        "graph": graph.stats(),
        "anchor_count": len(anchors),
        "pool_count": len(pool),
        "anchors": [],
    }

    qualified = 0
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
            if node != anchor_key and low * 0.40 <= distance <= high * 0.75
        ]
        window.sort(key=lambda node: (-base.dist[node], node))
        entry["turnarounds_in_window"] = len(window)

        entry["prefix_10"] = feasible_pairs(
            graph, anchor_key, target_m, window[:SWEEP_TURNAROUND_LIMIT],
            base, separation, low, high,
        )
        entry["prefix_48"] = feasible_pairs(
            graph, anchor_key, target_m, window[:LONG_BIKE_SWEEP_TURNAROUND_LIMIT],
            base, separation, low, high,
        )
        entry["stride_48"] = feasible_pairs(
            graph, anchor_key, target_m,
            stride_pick(window, LONG_BIKE_SWEEP_TURNAROUND_LIMIT),
            base, separation, low, high,
        )
        entry["all_turnarounds"] = feasible_pairs(
            graph, anchor_key, target_m, window, base, separation, low, high,
        )
        report["anchors"].append(entry)
        if qualified >= 6:
            break

    report["qualified_anchors_examined"] = qualified
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
