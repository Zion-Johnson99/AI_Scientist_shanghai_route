#!/usr/bin/env python3
"""Fast local topology gate for Xuhui route candidate JSON or GeoJSON."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


EARTH_RADIUS_M = 6_371_008.8
ROUND_DIGITS = 5
LOOP_ENDPOINT_MAX_M = 30.0
ONE_WAY_ENDPOINT_MIN_M = 200.0
MARKER_ENDPOINT_MAX_M = 30.0
RETRACE_RATIO_MAX = 0.02
RETRACE_EDGE_MAX_M = 30.0
DISTANCE_ERROR_MAX = 0.03
TARGET_ERROR_MAX = 0.15
ONE_WAY_CIRCUITY_MAX = 2.5
LOCAL_RETURN_RADIUS_M = 20.0
LOCAL_RETURN_PATH_MIN_M = 200.0
STRICT_LOOP_CLOSURE_MARGIN_M = 75.0


Point = tuple[float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit route shape, retraces, local loops, waypoints, and distance consistency."
    )
    parser.add_argument("routes", type=Path, help="Candidate-route JSON list or route GeoJSON")
    parser.add_argument("--route-id", action="append", default=[], help="Route ID to audit; repeat for a batch")
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    parser.add_argument("--report-only", action="store_true", help="Return success even when routes fail")
    return parser.parse_args()


def load_routes(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        routes = payload
    elif isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        routes = []
        for feature in payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            properties["_geometry"] = feature.get("geometry") or {}
            routes.append(properties)
    else:
        raise ValueError("routes input must be a JSON list or GeoJSON FeatureCollection")
    if not all(isinstance(route, dict) for route in routes):
        raise ValueError("every route must be an object")
    return routes


def route_id(route: dict[str, Any], index: int) -> str:
    return str(route.get("route_id") or route.get("seed_id") or f"route-{index + 1}")


def route_points(route: dict[str, Any]) -> list[Point]:
    raw_points = route.get("polyline_gcj02")
    if raw_points is None:
        geometry = route.get("_geometry") or route.get("geometry") or {}
        if geometry.get("type") != "LineString":
            return []
        raw_points = geometry.get("coordinates") or []
    points: list[Point] = []
    for item in raw_points or []:
        if isinstance(item, dict):
            lng, lat = item.get("lng_gcj02"), item.get("lat_gcj02")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            lng, lat = item[0], item[1]
        else:
            continue
        if _finite(lng) and _finite(lat):
            point = (float(lng), float(lat))
            if not points or point != points[-1]:
                points.append(point)
    return points


def audit_route(route: dict[str, Any], index: int) -> dict[str, Any]:
    identifier = route_id(route, index)
    mode = str(route.get("route_mode") or route.get("mode") or "")
    shape = str(route.get("route_shape") or "")
    points = route_points(route)
    failures: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"point_count": len(points)}

    if shape not in {"one_way", "strict_loop"}:
        failures.append(_failure("invalid_shape", f"route_shape={shape!r}"))
    if len(points) < 2:
        failures.append(_failure("missing_geometry", "轨迹少于两个有效坐标"))
        return _result(identifier, mode, shape, metrics, failures)

    segment_lengths = [distance_m(first, second) for first, second in zip(points, points[1:])]
    geometry_distance = sum(segment_lengths)
    endpoint_distance = distance_m(points[0], points[-1])
    metrics.update(
        geometry_distance_m=round(geometry_distance, 1),
        endpoint_distance_m=round(endpoint_distance, 1),
    )

    if shape == "strict_loop" and endpoint_distance > LOOP_ENDPOINT_MAX_M:
        failures.append(_failure("open_loop", f"闭环首尾相距 {endpoint_distance:.1f} 米"))
    if shape == "one_way" and endpoint_distance <= ONE_WAY_ENDPOINT_MIN_M:
        failures.append(_failure("weak_one_way", f"单程起终点仅相距 {endpoint_distance:.1f} 米"))
    if shape == "strict_loop":
        loop_topology = strict_loop_topology(points)
        metrics.update(loop_topology)
        if not loop_topology["single_simple_cycle"]:
            failures.append(
                _failure(
                    "false_loop_topology",
                    "轨迹虽闭合，但未形成单一简单环",
                )
            )

    retrace_ratio, longest_retrace = retrace_metrics(points, segment_lengths)
    metrics.update(
        retrace_ratio=round(retrace_ratio, 4),
        longest_retraced_edge_m=round(longest_retrace, 1),
    )
    if retrace_ratio > RETRACE_RATIO_MAX or longest_retrace >= RETRACE_EDGE_MAX_M:
        failures.append(
            _failure(
                "retraced_edges",
                f"重复边累计 {retrace_ratio:.1%}，最长 {longest_retrace:.1f} 米",
            )
        )

    branch_nodes = branch_like_nodes(points, shape)
    intersections = proper_segment_intersections(points, shape)
    metrics["branch_like_node_count"] = len(branch_nodes)
    metrics["proper_self_intersection_count"] = len(intersections)
    if branch_nodes or intersections:
        failures.append(
            _failure(
                "branch_or_self_intersection",
                f"检测到 {len(branch_nodes)} 个分叉节点、{len(intersections)} 个线段自交",
            )
        )

    uturn_count, longest_uturn = local_uturn_metrics(points)
    metrics.update(local_uturn_count=uturn_count, longest_local_uturn_m=round(longest_uturn, 1))
    if uturn_count:
        failures.append(_failure("local_uturn", f"检测到 {uturn_count} 个局部折返，最长 {longest_uturn:.1f} 米"))

    return_loops = local_return_loops(points, segment_lengths, shape)
    metrics["local_return_loop_count"] = len(return_loops)
    if return_loops:
        longest = max(item["path_distance_m"] for item in return_loops)
        failures.append(_failure("local_return_loop", f"检测到 {len(return_loops)} 个局部回环，最长 {longest:.1f} 米"))

    if shape == "one_way" and endpoint_distance > 0:
        circuity = geometry_distance / endpoint_distance
        metrics["one_way_circuity"] = round(circuity, 3)
        if circuity > ONE_WAY_CIRCUITY_MAX:
            failures.append(_failure("excessive_circuity", f"单程曲折系数 {circuity:.2f} 高于 {ONE_WAY_CIRCUITY_MAX:.2f}"))

    _audit_distance_fields(route, geometry_distance, metrics, failures)
    _audit_locations_and_nodes(route, points, mode, metrics, failures)
    return _result(identifier, mode, shape, metrics, failures)


def retrace_metrics(points: list[Point], lengths: list[float]) -> tuple[float, float]:
    keys = [_edge_key(first, second) for first, second in zip(points, points[1:])]
    counts = Counter(keys)
    seen: Counter[tuple[Point, Point]] = Counter()
    repeated_distance = 0.0
    longest = 0.0
    for key, length in zip(keys, lengths):
        seen[key] += 1
        if counts[key] > 1 and seen[key] > 1:
            repeated_distance += length
            longest = max(longest, length)
    total = sum(lengths)
    return (0.0 if total == 0 else repeated_distance / total), longest


def branch_like_nodes(points: list[Point], shape: str) -> list[Point]:
    adjacency: dict[Point, set[Point]] = defaultdict(set)
    for first, second in zip(points, points[1:]):
        first_key, second_key = _rounded(first), _rounded(second)
        if first_key == second_key:
            continue
        adjacency[first_key].add(second_key)
        adjacency[second_key].add(first_key)
    branch_nodes = [point for point, neighbors in adjacency.items() if len(neighbors) > 2]
    if shape == "strict_loop" and _rounded(points[0]) == _rounded(points[-1]):
        branch_nodes = [point for point in branch_nodes if point != _rounded(points[0]) or len(adjacency[point]) > 2]
    return branch_nodes


def strict_loop_topology(points: list[Point]) -> dict[str, int | bool]:
    """Check whether a closed route collapses to exactly one graph cycle."""
    keys = [_rounded(point) for point in points]
    if distance_m(points[0], points[-1]) <= LOOP_ENDPOINT_MAX_M:
        keys[-1] = keys[0]

    adjacency: dict[Point, set[Point]] = defaultdict(set)
    edges: set[tuple[Point, Point]] = set()
    for first, second in zip(keys, keys[1:]):
        if first == second:
            continue
        adjacency[first].add(second)
        adjacency[second].add(first)
        edges.add(_edge_key(first, second))

    unseen = set(adjacency)
    component_count = 0
    while unseen:
        component_count += 1
        stack = [unseen.pop()]
        while stack:
            current = stack.pop()
            neighbors = adjacency[current] & unseen
            unseen.difference_update(neighbors)
            stack.extend(neighbors)

    cycle_rank = len(edges) - len(adjacency) + component_count if adjacency else 0
    irregular_count = sum(len(neighbors) != 2 for neighbors in adjacency.values())
    single_cycle = component_count == 1 and cycle_rank == 1 and irregular_count == 0
    return {
        "single_simple_cycle": single_cycle,
        "topology_cycle_rank": cycle_rank,
        "topology_component_count": component_count,
        "non_degree_two_node_count": irregular_count,
    }


def proper_segment_intersections(points: list[Point], shape: str) -> list[tuple[int, int]]:
    """Return non-adjacent segment pairs with a proper interior crossing."""
    intersections: list[tuple[int, int]] = []
    segment_count = len(points) - 1
    for first_index in range(segment_count):
        first_start, first_end = points[first_index], points[first_index + 1]
        for second_index in range(first_index + 2, segment_count):
            if shape == "strict_loop" and first_index == 0 and second_index == segment_count - 1:
                continue
            second_start, second_end = points[second_index], points[second_index + 1]
            if _properly_intersects(first_start, first_end, second_start, second_end):
                intersections.append((first_index, second_index))
    return intersections


def _properly_intersects(first: Point, second: Point, third: Point, fourth: Point) -> bool:
    if (
        max(first[0], second[0]) <= min(third[0], fourth[0])
        or max(third[0], fourth[0]) <= min(first[0], second[0])
        or max(first[1], second[1]) <= min(third[1], fourth[1])
        or max(third[1], fourth[1]) <= min(first[1], second[1])
    ):
        return False
    first_side = _orientation(first, second, third)
    second_side = _orientation(first, second, fourth)
    third_side = _orientation(third, fourth, first)
    fourth_side = _orientation(third, fourth, second)
    return first_side * second_side < 0 and third_side * fourth_side < 0


def _orientation(first: Point, second: Point, third: Point) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (third[0] - first[0])


def local_uturn_metrics(points: list[Point]) -> tuple[int, float]:
    count = 0
    longest = 0.0
    for first, middle, last in zip(points, points[1:], points[2:]):
        first_leg = distance_m(first, middle)
        second_leg = distance_m(middle, last)
        if first_leg >= 15 and second_leg >= 15 and distance_m(first, last) <= 10:
            count += 1
            longest = max(longest, first_leg + second_leg)
    return count, longest


def local_return_loops(points: list[Point], lengths: list[float], shape: str) -> list[dict[str, float | int]]:
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    cell_size = 0.00025
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    loops: list[dict[str, float | int]] = []
    for index, point in enumerate(points):
        cell = (math.floor(point[0] / cell_size), math.floor(point[1] / cell_size))
        candidates: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.update(grid.get((cell[0] + dx, cell[1] + dy), ()))
        for previous in sorted(candidates):
            if index - previous <= 2:
                continue
            path_distance = cumulative[index] - cumulative[previous]
            if (
                shape == "strict_loop"
                and cumulative[previous] <= STRICT_LOOP_CLOSURE_MARGIN_M
                and cumulative[-1] - cumulative[index] <= STRICT_LOOP_CLOSURE_MARGIN_M
            ):
                continue
            if path_distance >= LOCAL_RETURN_PATH_MIN_M and distance_m(points[previous], point) <= LOCAL_RETURN_RADIUS_M:
                loops.append({"from_index": previous, "to_index": index, "path_distance_m": round(path_distance, 1)})
                break
        grid[cell].append(index)
    return loops


def _audit_distance_fields(
    route: dict[str, Any], geometry_distance: float, metrics: dict[str, Any], failures: list[dict[str, Any]]
) -> None:
    actual = route.get("actual_distance_m")
    target = route.get("target_distance_m")
    if _finite(actual) and float(actual) > 0:
        actual_value = float(actual)
        geometry_error = abs(actual_value - geometry_distance) / actual_value
        metrics["api_geometry_distance_error"] = round(geometry_error, 4)
        if geometry_error > DISTANCE_ERROR_MAX:
            failures.append(_failure("api_geometry_distance_mismatch", f"API 与几何距离误差 {geometry_error:.1%}"))
        if _finite(target) and float(target) > 0:
            target_error = abs(actual_value - float(target)) / float(target)
            metrics["target_distance_error"] = round(target_error, 4)
            if target_error > TARGET_ERROR_MAX:
                failures.append(_failure("target_distance_mismatch", f"实际与目标里程误差 {target_error:.1%}"))


def _audit_locations_and_nodes(
    route: dict[str, Any], points: list[Point], mode: str, metrics: dict[str, Any], failures: list[dict[str, Any]]
) -> None:
    start = _location_point(route.get("start_location"))
    end = _location_point(route.get("end_location"))
    if start:
        offset = distance_m(start, points[0])
        metrics["start_endpoint_offset_m"] = round(offset, 1)
        if offset > MARKER_ENDPOINT_MAX_M:
            failures.append(_failure("start_marker_offset", f"起点偏离轨迹首端 {offset:.1f} 米"))
    if end:
        offset = distance_m(end, points[-1])
        metrics["end_endpoint_offset_m"] = round(offset, 1)
        if offset > MARKER_ENDPOINT_MAX_M:
            failures.append(_failure("end_marker_offset", f"终点偏离轨迹末端 {offset:.1f} 米"))
    if start and end:
        marker_distance = distance_m(start, end)
        metrics["start_end_marker_distance_m"] = round(marker_distance, 1)
        shape = str(route.get("route_shape") or "")
        if shape == "strict_loop" and marker_distance > LOOP_ENDPOINT_MAX_M:
            failures.append(_failure("loop_marker_mismatch", f"闭环起终点标记相距 {marker_distance:.1f} 米"))
        if shape == "one_way" and marker_distance <= ONE_WAY_ENDPOINT_MIN_M:
            failures.append(_failure("weak_one_way_markers", f"单程起终点标记仅相距 {marker_distance:.1f} 米"))

    limit = 100.0 if mode == "bike" else 50.0
    distant: list[dict[str, Any]] = []
    node_points: list[tuple[str, Point]] = []
    for node in route.get("ordered_nodes") or []:
        point = _location_point(node)
        if not point:
            continue
        name = node.get("node_name") or node.get("name") or "未命名节点"
        node_points.append((name, point))
        offset = point_polyline_distance_m(point, points)
        if offset > limit:
            distant.append({"name": name, "offset_m": round(offset, 1)})
    metrics["distant_waypoints"] = distant
    if distant:
        failures.append(_failure("waypoint_offset", f"{len(distant)} 个途经点偏离轨迹走廊"))
    if node_points:
        first_node_offset = distance_m(node_points[0][1], points[0])
        last_node_offset = distance_m(node_points[-1][1], points[-1])
        metrics["first_node_endpoint_offset_m"] = round(first_node_offset, 1)
        metrics["last_node_endpoint_offset_m"] = round(last_node_offset, 1)
        if first_node_offset > limit or last_node_offset > limit:
            failures.append(
                _failure(
                    "node_order_endpoint_mismatch",
                    f"首末导航节点与轨迹端点偏移 {first_node_offset:.1f}/{last_node_offset:.1f} 米",
                )
            )


def point_polyline_distance_m(point: Point, points: list[Point]) -> float:
    return min(point_segment_distance_m(point, first, second) for first, second in zip(points, points[1:]))


def point_segment_distance_m(point: Point, first: Point, second: Point) -> float:
    origin_lat = math.radians(point[1])
    scale_x = EARTH_RADIUS_M * math.cos(origin_lat) * math.pi / 180
    scale_y = EARTH_RADIUS_M * math.pi / 180
    ax, ay = (first[0] - point[0]) * scale_x, (first[1] - point[1]) * scale_y
    bx, by = (second[0] - point[0]) * scale_x, (second[1] - point[1]) * scale_y
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    fraction = 0.0 if denominator == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator))
    return math.hypot(ax + fraction * dx, ay + fraction * dy)


def distance_m(first: Point, second: Point) -> float:
    lat1, lat2 = math.radians(first[1]), math.radians(second[1])
    delta_lat = lat2 - lat1
    delta_lng = math.radians(second[0] - first[0])
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def _edge_key(first: Point, second: Point) -> tuple[Point, Point]:
    return tuple(sorted((_rounded(first), _rounded(second))))  # type: ignore[return-value]


def _rounded(point: Point) -> Point:
    return round(point[0], ROUND_DIGITS), round(point[1], ROUND_DIGITS)


def _location_point(value: Any) -> Point | None:
    if not isinstance(value, dict):
        return None
    lng, lat = value.get("lng_gcj02"), value.get("lat_gcj02")
    if not (_finite(lng) and _finite(lat)):
        return None
    return float(lng), float(lat)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _failure(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _result(
    identifier: str, mode: str, shape: str, metrics: dict[str, Any], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "route_id": identifier,
        "route_mode": mode,
        "route_shape": shape,
        "status": "pass" if not failures else "fail",
        "metrics": metrics,
        "failures": failures,
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    routes = load_routes(args.routes)
    selected = set(args.route_id)
    indexed = [(index, route) for index, route in enumerate(routes) if not selected or route_id(route, index) in selected]
    found = {route_id(route, index) for index, route in indexed}
    missing = sorted(selected - found)
    if missing:
        raise ValueError(f"route IDs not found: {', '.join(missing)}")

    results = [audit_route(route, index) for index, route in indexed]
    failed = [result for result in results if result["status"] == "fail"]
    payload = {
        "routes_checked": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    if args.report:
        write_report(args.report, payload)
    print(f"routes_checked={payload['routes_checked']} passed={payload['passed']} failed={payload['failed']}")
    for result in failed:
        codes = ",".join(failure["code"] for failure in result["failures"])
        print(f"FAIL {result['route_id']}: {codes}")
    return 0 if args.report_only or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
