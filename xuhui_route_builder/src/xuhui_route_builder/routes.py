from __future__ import annotations

import itertools
import json
import unicodedata
from pathlib import Path
from typing import Any

from .geo import polyline_to_coordinate_pairs
from .models import CandidateRoute, DirectionPath, RouteNode, RouteSeed
from .scoring_placeholder import attach_score_placeholder


def load_route_seeds(seed_path: Path) -> list[RouteSeed]:
    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("route_seeds.json must be a list")
    return [RouteSeed(**item) for item in raw]


def parse_direction_path(response: dict[str, Any]) -> DirectionPath:
    path = _first_path(response)
    steps = path.get("steps") or []
    polyline: list[str] = []
    road_names: list[str] = []
    instructions: list[str] = []
    for step in steps:
        road_name = step.get("road") or step.get("road_name")
        if road_name and road_name not in road_names:
            road_names.append(road_name)
        if step.get("instruction"):
            instructions.append(step["instruction"])
        for point in str(step.get("polyline", "")).split(";"):
            if point and (not polyline or polyline[-1] != point):
                polyline.append(point)
    return DirectionPath(
        distance_m=int(float(path.get("distance", 0))),
        duration_s=int(float(path.get("duration") or (path.get("cost") or {}).get("duration") or 0)),
        polyline_gcj02=polyline,
        road_names=road_names,
        instructions=instructions,
    )


def candidate_from_seed(seed: RouteSeed, direction: DirectionPath, index: int) -> CandidateRoute:
    prefix = "RUN" if seed.route_mode == "run" else "WALK" if seed.route_mode == "walk" else "BIKE"
    coordinates = polyline_to_coordinate_pairs(direction.polyline_gcj02)
    if not coordinates:
        raise ValueError(f"generated route has no geometry: seed_id={seed.seed_id}")
    start_coordinate, end_coordinate = coordinates[0], coordinates[-1]
    start_location = seed.start_location.model_copy(
        update={"lng_gcj02": start_coordinate.lng_gcj02, "lat_gcj02": start_coordinate.lat_gcj02}
    )
    end_location = seed.end_location.model_copy(
        update={"lng_gcj02": end_coordinate.lng_gcj02, "lat_gcj02": end_coordinate.lat_gcj02}
    )
    ordered_nodes = list(seed.ordered_nodes)
    ordered_nodes[0] = ordered_nodes[0].model_copy(
        update={"lng_gcj02": start_coordinate.lng_gcj02, "lat_gcj02": start_coordinate.lat_gcj02}
    )
    ordered_nodes[-1] = ordered_nodes[-1].model_copy(
        update={"lng_gcj02": end_coordinate.lng_gcj02, "lat_gcj02": end_coordinate.lat_gcj02}
    )
    route = CandidateRoute(
        route_id=f"XH_{prefix}_{index:04d}",
        route_name=seed.route_name,
        route_mode=seed.route_mode,
        route_shape=seed.route_shape,
        target_distance_m=seed.target_distance_m,
        actual_distance_m=direction.distance_m,
        duration_s=direction.duration_s,
        start_entry_id=f"{seed.seed_id}_start",
        end_entry_id=f"{seed.seed_id}_end",
        start_location=start_location,
        end_location=end_location,
        ordered_nodes=ordered_nodes,
        amenity_ids=seed.amenity_ids,
        popular_area_ids=seed.popular_area_ids,
        preference_search_status=seed.preference_search_status,
        preference_hits=seed.preference_hits,
        region_zone=seed.region_zone,
        polyline_gcj02=coordinates,
        tags=seed.tags,
        source_method="amap_seed",
        road_names=direction.road_names,
        turn_count=max(0, len(direction.instructions) - 1),
        source_name=seed.source_name,
        source_url=seed.source_url,
        source_accessed_at=seed.source_accessed_at,
        confidence=seed.confidence,
        distance_error_m=abs(direction.distance_m - seed.target_distance_m),
        loop_flag=seed.route_shape == "strict_loop",
        source_level=seed.source_level,
        waypoint_names=[node.node_name for node in seed.ordered_nodes] or [seed.start_hint, *seed.waypoint_hints, seed.end_hint],
        review_note=_review_note(seed),
    )
    return attach_score_placeholder(route)


def _is_loop(seed: RouteSeed) -> bool:
    if len(seed.ordered_nodes) < 2:
        return False
    first, last = seed.ordered_nodes[0], seed.ordered_nodes[-1]
    if first.poi_id and last.poi_id:
        return first.poi_id == last.poi_id
    return (
        first.lng_gcj02 is not None
        and first.lat_gcj02 is not None
        and first.lng_gcj02 == last.lng_gcj02
        and first.lat_gcj02 == last.lat_gcj02
    )


def resolve_seed_nodes(seed: RouteSeed, client: Any) -> RouteSeed:
    resolved_nodes: list[RouteNode] = []
    poi_raw_paths: list[str] = []
    for node_index, node in enumerate(seed.ordered_nodes):
        if node.lng_gcj02 is not None and node.lat_gcj02 is not None:
            resolved_nodes.append(node)
            continue
        resolved, raw_path = resolve_node_query(
            expected_name=node.node_name,
            query=node.node_name,
            client=client,
            expected_poi_id=node.poi_id,
            seed_id=seed.seed_id,
            node_index=node_index,
        )
        resolved_nodes.append(resolved)
        poi_raw_paths.append(raw_path)
    evidence_parts = [seed.evidence_note.strip(), *(f"POI解析响应: {path}" for path in poi_raw_paths)]
    start_node, end_node = resolved_nodes[0], resolved_nodes[-1]
    return seed.model_copy(
        update={
            "ordered_nodes": resolved_nodes,
            "start_location": seed.start_location.model_copy(
                update={"lng_gcj02": start_node.lng_gcj02, "lat_gcj02": start_node.lat_gcj02, "poi_id": start_node.poi_id}
            ),
            "end_location": seed.end_location.model_copy(
                update={"lng_gcj02": end_node.lng_gcj02, "lat_gcj02": end_node.lat_gcj02, "poi_id": end_node.poi_id}
            ),
            "evidence_note": "；".join(part for part in evidence_parts if part),
        }
    )


def resolve_node_query(
    expected_name: str,
    query: str,
    client: Any,
    expected_poi_id: str | None,
    seed_id: str,
    node_index: int,
) -> tuple[RouteNode, str]:
    context = f"seed_id={seed_id} node_index={node_index} node_name={expected_name} query={query}"
    try:
        record = client.place_text_v5(query, region="310104")
        if str(record.status) != "1":
            raise ValueError(f"status={record.status!r}")
        if not str(record.raw_path).strip():
            raise ValueError("raw_path is empty")
        try:
            resolved = _resolve_unique_poi_node(expected_name, expected_poi_id, record.payload.get("pois") or [])
            return resolved, str(record.raw_path)
        except ValueError:
            if expected_poi_id is not None:
                raise
            geocode_record = client.geocode(f"上海市徐汇区{query}", city="上海")
            if str(geocode_record.status) != "1" or not str(geocode_record.raw_path).strip():
                raise
            resolved = _resolve_unique_geocode_node(expected_name, geocode_record.payload.get("geocodes") or [])
            return resolved, str(geocode_record.raw_path)
    except Exception as exc:
        raise ValueError(f"Amap POI resolution failed: {context}: {exc}") from exc


def generate_candidate_from_seed(seed: RouteSeed, client: Any, index: int) -> CandidateRoute:
    nodes = seed.ordered_nodes
    if len(nodes) < 2 or any(node.lng_gcj02 is None or node.lat_gcj02 is None for node in nodes):
        raise ValueError("RouteSeed requires at least two resolved nodes")

    mode = "bike" if seed.route_mode in {"bike", "bike_assist"} else "walking"
    paths: list[DirectionPath] = []
    raw_response_paths: list[str] = []
    for segment_index, (origin_node, destination_node) in enumerate(itertools.pairwise(nodes), start=1):
        origin = _node_location(origin_node)
        destination = _node_location(destination_node)
        context = f"segment={segment_index} mode={mode} origin={origin} destination={destination}"
        try:
            record = client.bicycling_v2(origin, destination) if mode == "bike" else client.walking_v2(origin, destination)
            if str(record.status) != "1":
                raise ValueError(f"status={record.status!r}")
            if not str(record.raw_path).strip():
                raise ValueError("raw_path is empty")
            path = parse_direction_path(record.payload)
            if path.distance_m <= 0:
                raise ValueError("distance must be positive")
            if path.duration_s <= 0:
                raise ValueError("duration must be positive")
            if len(path.polyline_gcj02) < 2:
                raise ValueError("geometry has fewer than two points")
        except Exception as exc:
            raise ValueError(f"Amap direction failed: {context}: {exc}") from exc
        paths.append(path)
        raw_response_paths.append(str(record.raw_path))

    direction = DirectionPath(
        distance_m=sum(path.distance_m for path in paths),
        duration_s=sum(path.duration_s for path in paths),
        polyline_gcj02=_merge_unique([path.polyline_gcj02 for path in paths]),
        road_names=_merge_unique([path.road_names for path in paths]),
        instructions=_merge_unique([path.instructions for path in paths]),
    )
    route = candidate_from_seed(seed, direction, index)
    route.source_method = "amap_segmented_direction"
    route.geometry_source = "amap_direction"
    route.geometry_status = "complete"
    route.validation_status = "pending"
    route.network_source = f"amap_{mode}_v2"
    route.raw_response_paths = raw_response_paths
    return route


def preserve_candidate_geometry(seed: RouteSeed, previous: dict[str, Any], index: int) -> CandidateRoute:
    prefix = "RUN" if seed.route_mode == "run" else "WALK" if seed.route_mode == "walk" else "BIKE"
    points = previous["polyline_gcj02"]
    waypoint_names = previous.get("waypoint_names") or [seed.start_location.name, seed.end_location.name]
    previous_loop = bool(previous.get("loop_flag"))
    start_name = waypoint_names[0]
    end_name = start_name if previous_loop else waypoint_names[-1]
    start_location = seed.start_location.model_copy(
        update={"name": start_name, "lng_gcj02": points[0]["lng_gcj02"], "lat_gcj02": points[0]["lat_gcj02"]}
    )
    end_point = points[0] if previous_loop else points[-1]
    end_location = seed.end_location.model_copy(
        update={"name": end_name, "lng_gcj02": end_point["lng_gcj02"], "lat_gcj02": end_point["lat_gcj02"]}
    )
    protected_nodes = [
        RouteNode(node_name=start_name, lng_gcj02=start_location.lng_gcj02, lat_gcj02=start_location.lat_gcj02),
        RouteNode(node_name=end_name, lng_gcj02=end_location.lng_gcj02, lat_gcj02=end_location.lat_gcj02),
    ]
    payload = {
        **previous,
        "route_id": f"XH_{prefix}_{index:04d}",
        "route_name": seed.route_name,
        "route_mode": seed.route_mode,
        "route_shape": "strict_loop" if previous_loop else "one_way",
        "target_distance_m": seed.target_distance_m,
        "start_entry_id": f"{seed.seed_id}_start",
        "end_entry_id": f"{seed.seed_id}_end",
        "start_location": start_location.model_dump(mode="json"),
        "end_location": end_location.model_dump(mode="json"),
        "ordered_nodes": [node.model_dump(mode="json") for node in protected_nodes],
        "amenity_ids": seed.amenity_ids,
        "popular_area_ids": seed.popular_area_ids,
        "preference_search_status": seed.preference_search_status,
        "preference_hits": seed.preference_hits,
        "region_zone": seed.region_zone,
        "tags": seed.tags,
        "source_name": seed.source_name,
        "source_url": seed.source_url,
        "source_accessed_at": seed.source_accessed_at.isoformat(),
        "confidence": seed.confidence,
        "source_level": seed.source_level,
        "distance_error_m": abs(int(previous["actual_distance_m"]) - seed.target_distance_m),
        "loop_flag": previous_loop,
        "waypoint_names": waypoint_names,
        "source_method": "protected_geometry",
        "validation_status": "pending",
        "snap_ratio": None,
        "route_inside_ratio": None,
        "verified_at": None,
        "review_note": _review_note(seed),
    }
    return CandidateRoute.model_validate(payload)


def _first_path(response: dict[str, Any]) -> dict[str, Any]:
    route_paths = ((response.get("route") or {}).get("paths")) or []
    if route_paths:
        return route_paths[0]
    data_paths = ((response.get("data") or {}).get("paths")) or []
    if data_paths:
        return data_paths[0]
    raise ValueError("Amap direction response has no path")


def _resolve_unique_poi_node(expected_name: str, expected_poi_id: str | None, pois: list[dict[str, Any]]) -> RouteNode:
    valid: list[tuple[RouteNode, dict[str, Any]]] = []
    for poi in pois:
        location = poi.get("location")
        if not location:
            continue
        try:
            lng_text, lat_text = str(location).split(",", 1)
            valid.append(
                (
                    RouteNode(
                        node_name=expected_name,
                        poi_id=str(poi.get("id") or "") or None,
                        lng_gcj02=float(lng_text),
                        lat_gcj02=float(lat_text),
                    ),
                    poi,
                )
            )
        except (TypeError, ValueError):
            continue
    if not valid:
        raise ValueError("no valid POI location")
    in_xuhui = [(node, poi) for node, poi in valid if str(poi.get("adcode", "")) == "310104"]
    if not in_xuhui:
        raise ValueError("adcode must be 310104")
    if expected_poi_id is not None:
        matches = [node for node, poi in in_xuhui if str(poi.get("id", "")) == expected_poi_id]
    else:
        matches = [
            node
            for node, poi in in_xuhui
            if _normalize_poi_text(poi.get("name")) == _normalize_poi_text(expected_name)
        ]
        if not matches:
            normalized_expected = _normalize_poi_text(expected_name)
            contained = [
                (node, _normalize_poi_text(poi.get("name")))
                for node, poi in in_xuhui
                if normalized_expected in _normalize_poi_text(poi.get("name"))
            ]
            if contained:
                shortest = min(len(name) for _, name in contained)
                matches = [node for node, name in contained if len(name) == shortest]
        if not matches:
            expected_roads = _road_name_set(expected_name)
            if len(expected_roads) >= 2:
                matches = [node for node, poi in in_xuhui if _road_name_set(poi.get("name")) == expected_roads]
        if not matches:
            normalized_expected = _normalize_poi_text(expected_name)
            matches = [
                node
                for node, poi in in_xuhui
                if _normalize_poi_text(poi.get("address")).startswith(normalized_expected)
            ]
    if len(matches) == 1:
        return matches[0]
    if len(in_xuhui) > 1:
        raise ValueError(f"ambiguous POI results: {len(in_xuhui)} valid candidates")
    if not matches:
        raise ValueError("name does not match node_name and POI id does not match")
    raise ValueError(f"ambiguous POI results: {len(matches)} matching candidates")


def _resolve_unique_geocode_node(expected_name: str, geocodes: list[dict[str, Any]]) -> RouteNode:
    matches: dict[tuple[float, float], RouteNode] = {}
    for geocode in geocodes:
        if str(geocode.get("adcode", "")) != "310104" or not geocode.get("location"):
            continue
        try:
            lng_text, lat_text = str(geocode["location"]).split(",", 1)
            lng, lat = float(lng_text), float(lat_text)
            matches[(lng, lat)] = RouteNode(node_name=expected_name, lng_gcj02=lng, lat_gcj02=lat)
        except (TypeError, ValueError):
            continue
    if len(matches) != 1:
        raise ValueError(f"geocode requires one Xuhui match, got {len(matches)}")
    return next(iter(matches.values()))


def _normalize_poi_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(normalized.split())


def _road_name_set(value: Any) -> set[str]:
    text = _normalize_poi_text(value).replace("交叉口", "").replace("路口", "")
    return {part + "路" for part in text.replace("与", "").split("路") if part}


def _node_location(node: RouteNode) -> str:
    return f"{node.lng_gcj02},{node.lat_gcj02}"


def _merge_unique(groups: list[list[str]]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for value in group:
            if value and (not merged or merged[-1] != value):
                merged.append(value)
    return merged


def _review_note(seed: RouteSeed) -> str:
    parts = [seed.evidence_note.strip()]
    if seed.access_restrictions:
        parts.append("通行限制：" + "；".join(seed.access_restrictions))
    return "；".join(part for part in parts if part)
