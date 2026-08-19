from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = PROJECT_ROOT / "data/interim/pilot_candidates.json"
SEED_PATH = PROJECT_ROOT / "data/seeds/route_seeds.json"
RESEARCH_PATH = PROJECT_ROOT / "data/seeds/research/walk_route_optimization_0815.json"

# These indices are existing AMap segment boundaries on the accepted geometry.
WAYPOINT_REPLACEMENTS: dict[str, list[tuple[int, str]]] = {
    "XH_WALK_0009": [
        (0, "康健园北门外桂林西街"),
        (1, "钦州南路与桂林路交叉口"),
        (3, "桂林路与冠生园路交叉口"),
        (4, "冠生园路与柳州路交叉口"),
        (6, "康健园北门外桂林西街"),
    ],
    "XH_WALK_0013": [
        (0, "龙川北路与罗城路交叉口"),
        (2, "龙川北路与石龙路交叉口"),
        (4, "石龙路与东泉路交叉口"),
        (6, "东泉路与罗城路交叉口"),
        (8, "龙川北路与罗城路交叉口"),
    ],
    "XH_WALK_0014": [
        (0, "衡山路与乌鲁木齐南路交叉口"),
        (1, "乌鲁木齐南路与淮海中路交叉口"),
        (3, "常熟路与五原路交叉口"),
        (4, "乌鲁木齐中路与复兴西路交叉口"),
        (7, "衡山路与乌鲁木齐南路交叉口"),
    ],
}


def _read(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected JSON list: {path}")
    return payload


def _write(path: Path, payload: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _clean_candidate_nodes(routes: list[dict[str, Any]]) -> None:
    by_id = {route["route_id"]: route for route in routes}
    for route_id, replacements in WAYPOINT_REPLACEMENTS.items():
        route = by_id.get(route_id)
        if route is None:
            continue
        old_nodes = route["ordered_nodes"]
        if not any("实测" in node.get("node_name", "") for node in old_nodes):
            continue
        new_nodes: list[dict[str, Any]] = []
        for node_index, node_name in replacements:
            node = deepcopy(old_nodes[node_index])
            node["node_name"] = node_name
            node["node_type"] = (
                "landmark"
                if "公园" in node_name or "广场" in node_name
                else "road_intersection"
            )
            new_nodes.append(node)
        route["ordered_nodes"] = new_nodes
        route["waypoint_names"] = [node["node_name"] for node in new_nodes]


def _sync_seed_nodes(
    candidates: list[dict[str, Any]],
    seeds: list[dict[str, Any]],
) -> None:
    walk_routes = [route for route in candidates if route["route_mode"] == "walk"]
    walk_seeds = [seed for seed in seeds if seed["route_mode"] == "walk"]
    if len(walk_routes) != 30 or len(walk_seeds) != 30:
        raise ValueError("walk route and seed counts must both equal 30")
    for route, seed in zip(walk_routes, walk_seeds, strict=True):
        nodes = deepcopy(route["ordered_nodes"])
        if route["route_shape"] == "strict_loop":
            nodes[-1] = deepcopy(nodes[0])
        seed["route_name"] = route["route_name"]
        seed["route_shape"] = route["route_shape"]
        seed["target_distance_m"] = route["actual_distance_m"]
        seed["start_location"] = {
            **deepcopy(route["start_location"]),
            "name": nodes[0]["node_name"],
            "lng_gcj02": nodes[0]["lng_gcj02"],
            "lat_gcj02": nodes[0]["lat_gcj02"],
        }
        seed["end_location"] = (
            deepcopy(seed["start_location"])
            if route["route_shape"] == "strict_loop"
            else {
                **deepcopy(route["end_location"]),
                "name": nodes[-1]["node_name"],
                "lng_gcj02": nodes[-1]["lng_gcj02"],
                "lat_gcj02": nodes[-1]["lat_gcj02"],
            }
        )
        seed["start_hint"] = nodes[0]["node_name"]
        seed["end_hint"] = nodes[-1]["node_name"]
        seed["ordered_nodes"] = nodes
        seed["waypoint_hints"] = [node["node_name"] for node in nodes[1:-1]]
        seed["preference_hits"] = []


def _sync_research_nodes(
    candidates: list[dict[str, Any]],
    research_routes: list[dict[str, Any]],
) -> None:
    by_id = {route["route_id"]: route for route in candidates}
    for record in research_routes:
        route = by_id[record["route_id"]]
        nodes = deepcopy(route["ordered_nodes"])
        if route["route_shape"] == "strict_loop":
            nodes[-1] = deepcopy(nodes[0])
        record["route_name"] = route["route_name"]
        record["route_shape"] = route["route_shape"]
        record["target_distance_m"] = route["actual_distance_m"]
        record["start_location"] = {
            "name": nodes[0]["node_name"],
            "lng_gcj02": nodes[0]["lng_gcj02"],
            "lat_gcj02": nodes[0]["lat_gcj02"],
            "source": "高德步行原始路径与本地几何门禁",
        }
        record["end_location"] = {
            "name": nodes[-1]["node_name"],
            "lng_gcj02": nodes[-1]["lng_gcj02"],
            "lat_gcj02": nodes[-1]["lat_gcj02"],
            "source": "高德步行原始路径与本地几何门禁",
        }
        record["ordered_nodes"] = [
            {
                "name": node["node_name"],
                "lng_gcj02": node["lng_gcj02"],
                "lat_gcj02": node["lat_gcj02"],
            }
            for node in nodes
        ]
        record["waypoint_names"] = [node["node_name"] for node in nodes[1:-1]]
        record["preference_hits"] = []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    candidates = _read(CANDIDATE_PATH)
    seeds = _read(SEED_PATH)
    research_routes = _read(RESEARCH_PATH)
    _clean_candidate_nodes(candidates)
    _sync_seed_nodes(candidates, seeds)
    _sync_research_nodes(candidates, research_routes)

    if args.apply:
        _write(CANDIDATE_PATH, candidates)
        _write(SEED_PATH, seeds)
        _write(RESEARCH_PATH, research_routes)
    print("walk waypoints synchronized: 30 routes")


if __name__ == "__main__":
    main()
