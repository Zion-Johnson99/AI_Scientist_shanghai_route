from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = PROJECT_ROOT / "data/interim/pilot_candidates.json"
PROCESSED_PATH = PROJECT_ROOT / "data/processed/pilot_validated.json"
SEED_PATH = PROJECT_ROOT / "data/seeds/route_seeds.json"
RESEARCH_PATH = PROJECT_ROOT / "data/seeds/research/bike_route_optimization_0815.json"
PLACEHOLDER_PATTERN = re.compile(r"实测|(?:节点|node)[-_ ]*\d+$|^\d+$", re.IGNORECASE)


def _read(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError(f"expected JSON list: {path}")
    return payload


def _write(path: Path, payload: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _bike_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [route for route in routes if route.get("route_mode") == "bike"]
    if len(selected) != 30:
        raise ValueError(f"expected 30 bike routes, got {len(selected)}")
    return selected


def _assert_real_node_names(routes: list[dict[str, Any]]) -> None:
    invalid: list[str] = []
    for route in routes:
        for node in route.get("ordered_nodes", []):
            name = str(node.get("node_name", "")).strip()
            if not name or PLACEHOLDER_PATTERN.search(name):
                invalid.append(f"{route['route_id']}:{name or '<empty>'}")
    if invalid:
        raise ValueError(f"bike routes contain placeholder nodes: {', '.join(invalid)}")


def _sync_metadata_only_targets(candidates: list[dict[str, Any]]) -> None:
    route = next(
        (
            item
            for item in candidates
            if item.get("route_mode") == "bike" and item.get("route_id") == "XH_BIKE_0068"
        ),
        None,
    )
    if route is None:
        raise ValueError("missing metadata-only route XH_BIKE_0068")
    route["target_distance_m"] = route["actual_distance_m"]
    route["distance_error_m"] = 0


def _sync_seed_nodes(
    candidates: list[dict[str, Any]],
    seeds: list[dict[str, Any]],
    research_routes: list[dict[str, Any]] | None = None,
) -> None:
    bike_routes = _bike_routes(candidates)
    bike_seeds = _bike_routes(seeds)
    _assert_real_node_names(bike_routes)
    route_id_by_seed_id = {
        record["seed_id"]: record["route_id"]
        for record in research_routes or []
        if record.get("seed_id") and record.get("route_id")
    }
    for route, seed in zip(bike_routes, bike_seeds, strict=True):
        seed_route_id = seed.get("route_id") or route_id_by_seed_id.get(
            seed.get("seed_id")
        )
        if route["route_id"] != seed_route_id:
            raise ValueError(
                f"bike route order mismatch: {route['route_id']} != {seed_route_id}"
            )
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
    candidates: list[dict[str, Any]], research_routes: list[dict[str, Any]]
) -> None:
    bike_routes = _bike_routes(candidates)
    if len(research_routes) != 30:
        raise ValueError(f"expected 30 bike research routes, got {len(research_routes)}")
    by_id = {route["route_id"]: route for route in bike_routes}
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
            "source": "高德骑行原始路径与本地几何门禁",
        }
        record["end_location"] = {
            "name": nodes[-1]["node_name"],
            "lng_gcj02": nodes[-1]["lng_gcj02"],
            "lat_gcj02": nodes[-1]["lat_gcj02"],
            "source": "高德骑行原始路径与本地几何门禁",
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


def _sync_candidate_pois(
    candidates: list[dict[str, Any]], published: list[dict[str, Any]]
) -> None:
    published_by_id = {
        route["route_id"]: route
        for route in published
        if route.get("route_mode") == "bike"
    }
    for candidate in candidates:
        if candidate.get("route_mode") != "bike":
            continue
        route_id = candidate["route_id"]
        source = published_by_id.get(route_id)
        if source is None:
            raise ValueError(f"missing published bike route: {route_id}")
        if candidate.get("actual_distance_m") != source.get(
            "actual_distance_m"
        ) or candidate.get("polyline_gcj02") != source.get("polyline_gcj02"):
            raise ValueError(f"bike route geometry mismatch: {route_id}")
        for field in (
            "nearby_pois",
            "amenity_ids",
            "preference_hits",
            "preference_search_status",
        ):
            candidate[field] = deepcopy(
                source.get(field, [] if field != "preference_search_status" else {})
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    candidates = _read(CANDIDATE_PATH)
    published = _read(PROCESSED_PATH)
    seeds = _read(SEED_PATH)
    research_routes = _read(RESEARCH_PATH)
    _sync_metadata_only_targets(candidates)
    _sync_metadata_only_targets(published)
    _sync_candidate_pois(candidates, published)
    _sync_seed_nodes(candidates, seeds, research_routes)
    _sync_research_nodes(candidates, research_routes)

    if args.apply:
        _write(CANDIDATE_PATH, candidates)
        _write(PROCESSED_PATH, published)
        _write(SEED_PATH, seeds)
        _write(RESEARCH_PATH, research_routes)
    print("bike waypoints synchronized: 30 routes")


if __name__ == "__main__":
    main()
