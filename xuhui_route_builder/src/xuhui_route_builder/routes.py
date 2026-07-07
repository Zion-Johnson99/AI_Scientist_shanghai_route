from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .geo import polyline_to_coordinate_pairs
from .models import CandidateRoute, DirectionPath, RouteSeed
from .scoring_placeholder import attach_score_placeholder


def load_route_seeds(seed_path: Path) -> list[RouteSeed]:
    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("route_seeds.json must be a list")
    return [RouteSeed(**item) for item in raw]


def parse_direction_path(response: dict[str, Any]) -> DirectionPath:
    path = _first_path(response)
    steps = path.get("steps") or []
    polyline: list[str] = []
    road_names: list[str] = []
    instructions: list[str] = []
    for step in steps:
        if step.get("road") and step["road"] not in road_names:
            road_names.append(step["road"])
        if step.get("instruction"):
            instructions.append(step["instruction"])
        for point in str(step.get("polyline", "")).split(";"):
            if point and (not polyline or polyline[-1] != point):
                polyline.append(point)
    return DirectionPath(
        distance_m=int(float(path.get("distance", 0))),
        duration_s=int(float(path.get("duration", 0))),
        polyline_gcj02=polyline,
        road_names=road_names,
        instructions=instructions,
    )


def candidate_from_seed(seed: RouteSeed, direction: DirectionPath, index: int) -> CandidateRoute:
    prefix = "RUN" if seed.route_mode == "run" else "WALK" if seed.route_mode == "walk" else "BIKE"
    route = CandidateRoute(
        route_id=f"XH_{prefix}_{index:04d}",
        route_name=seed.route_name,
        route_mode=seed.route_mode,
        target_distance_m=seed.target_distance_m,
        actual_distance_m=direction.distance_m,
        duration_s=direction.duration_s,
        start_entry_id=f"{seed.seed_id}_start",
        end_entry_id=f"{seed.seed_id}_end",
        region_zone=seed.region_zone,
        polyline_gcj02=polyline_to_coordinate_pairs(direction.polyline_gcj02),
        tags=seed.tags,
        source_method="amap_seed",
        road_names=direction.road_names,
        turn_count=max(0, len(direction.instructions) - 1),
    )
    return attach_score_placeholder(route)


def _first_path(response: dict[str, Any]) -> dict[str, Any]:
    route_paths = ((response.get("route") or {}).get("paths")) or []
    if route_paths:
        return route_paths[0]
    data_paths = ((response.get("data") or {}).get("paths")) or []
    if data_paths:
        return data_paths[0]
    raise ValueError("Amap direction response has no path")
