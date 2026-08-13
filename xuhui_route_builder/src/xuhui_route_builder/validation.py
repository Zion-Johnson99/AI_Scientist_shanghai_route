from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import requests

from .models import CandidateRoute, CoordinatePair, RouteMode

WgsPoint = tuple[float, float]
Segment = tuple[WgsPoint, WgsPoint]
EARTH_RADIUS_M = 6_371_008.8
DEFAULT_SNAP_TOLERANCE_M = 25
MAX_TARGET_DISTANCE_ERROR_RATIO = 0.15


def build_overpass_query(route: CandidateRoute, margin_m: float = 50) -> str:
    if margin_m < 0:
        raise ValueError("margin_m must be non-negative")
    points = _as_wgs_points(route.polyline_gcj02)
    if not points:
        raise ValueError(f"route {route.route_id} has no coordinates")
    min_lng, max_lng = min(point[0] for point in points), max(point[0] for point in points)
    min_lat, max_lat = min(point[1] for point in points), max(point[1] for point in points)
    centre_lat = (min_lat + max_lat) / 2
    lat_margin = margin_m / 111_320
    lng_margin = margin_m / (111_320 * max(math.cos(math.radians(centre_lat)), 0.01))
    bbox = f"{min_lat - lat_margin:.7f},{min_lng - lng_margin:.7f},{max_lat + lat_margin:.7f},{max_lng + lng_margin:.7f}"
    return f'[out:json][timeout:30];way["highway"]({bbox});(._;>;);out body;'


def parse_overpass_segments(payload: dict[str, Any], route_mode: RouteMode) -> list[Segment]:
    nodes = {
        int(item["id"]): (float(item["lon"]), float(item["lat"]))
        for item in payload.get("elements", [])
        if item.get("type") == "node" and {"id", "lon", "lat"} <= item.keys()
    }
    segments: list[Segment] = []
    for way in payload.get("elements", []):
        if way.get("type") != "way" or not _mode_allows(way.get("tags") or {}, route_mode):
            continue
        way_nodes = way.get("nodes") or []
        for first_id, second_id in zip(way_nodes, way_nodes[1:]):
            first = nodes.get(int(first_id))
            second = nodes.get(int(second_id))
            if first is not None and second is not None and first != second:
                segments.append((first, second))
    return segments


def compute_snap_ratio(
    points: Sequence[CoordinatePair | WgsPoint], segments: Sequence[Segment], tolerance_m: float = 20
) -> float:
    if not segments or tolerance_m < 0:
        return 0.0
    samples = _sample_polyline(_as_wgs_points(points), spacing_m=20)
    if not samples:
        return 0.0
    snapped = sum(min(_point_segment_distance_m(point, segment) for segment in segments) <= tolerance_m for point in samples)
    return snapped / len(samples)


def polyline_length_m(points: Sequence[CoordinatePair | WgsPoint]) -> float:
    wgs_points = _as_wgs_points(points)
    return sum(_distance_m(first, second) for first, second in zip(wgs_points, wgs_points[1:]))


def distance_error_ratio(route: CandidateRoute) -> float:
    if route.actual_distance_m <= 0:
        return math.inf
    return abs(polyline_length_m(route.polyline_gcj02) - route.actual_distance_m) / route.actual_distance_m


def validate_amap_raw_evidence(route: CandidateRoute, project_root: Path) -> list[str]:
    if route.geometry_source != "amap_direction":
        return []
    failures: list[str] = []
    allowed_root = (project_root / "data" / "raw" / "amap").resolve()
    endpoint = "bicycling_v2" if route.route_mode in {"bike", "bike_assist"} else "walking_v2"
    response_distances: list[int] = []
    response_endpoints: list[tuple[WgsPoint, WgsPoint]] = []
    for raw_path in route.raw_response_paths:
        path = Path(raw_path)
        resolved = (path if path.is_absolute() else project_root / path).resolve()
        if not resolved.is_relative_to(allowed_root):
            failures.append(f"高德原始响应不在项目原始数据目录：{raw_path}")
            continue
        if not resolved.is_file():
            failures.append(f"高德原始响应文件不存在：{raw_path}")
            continue
        if not resolved.name.startswith(f"{endpoint}_"):
            failures.append(f"高德原始响应接口类型错误：{resolved.name}")
            continue
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            paths = (payload.get("route") or {}).get("paths") or []
            if str(payload.get("status")) != "1":
                failures.append(f"高德原始响应 status 非成功：{resolved.name}")
                continue
            if not paths:
                failures.append(f"高德原始响应缺少路径：{resolved.name}")
                continue
            path_payload = paths[0]
            distance = int(float(path_payload.get("distance", 0)))
            points = _raw_path_points(path_payload)
            if distance <= 0 or len(points) < 2:
                failures.append(f"高德原始响应距离或几何无效：{resolved.name}")
                continue
            response_distances.append(distance)
            response_endpoints.append((points[0], points[-1]))
        except (AttributeError, json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            failures.append(f"高德原始响应无法解析：{resolved.name}: {exc}")
    if failures:
        return failures
    expected_segments = len(route.waypoint_names) - 1 if len(route.waypoint_names) >= 2 else None
    if expected_segments is not None and len(response_distances) != expected_segments:
        failures.append(f"高德原始响应分段数 {len(response_distances)} 与节点分段数 {expected_segments} 不一致")
    if not response_distances:
        failures.append("高德原始响应为空")
        return failures
    api_distance = sum(response_distances)
    if abs(api_distance - route.actual_distance_m) / route.actual_distance_m > 0.03:
        failures.append("高德原始响应距离与候选路线距离误差超过 3%")
    route_start = (route.polyline_gcj02[0].lng_gcj02, route.polyline_gcj02[0].lat_gcj02)
    route_end = (route.polyline_gcj02[-1].lng_gcj02, route.polyline_gcj02[-1].lat_gcj02)
    if _distance_m(route_start, response_endpoints[0][0]) > 30 or _distance_m(route_end, response_endpoints[-1][1]) > 30:
        failures.append("高德原始响应端点与候选路线几何不一致")
    return failures


def _raw_path_points(path_payload: dict[str, Any]) -> list[WgsPoint]:
    points: list[WgsPoint] = []
    for step in path_payload.get("steps") or []:
        for raw_point in str(step.get("polyline", "")).split(";"):
            if not raw_point:
                continue
            lng_text, lat_text = raw_point.split(",", 1)
            point = (float(lng_text), float(lat_text))
            if not points or points[-1] != point:
                points.append(point)
    return points


def validate_candidate(
    route: CandidateRoute,
    osm_payload: dict[str, Any],
    verified_at: datetime,
    network_version: str,
    evidence_failures: Sequence[str] = (),
    boundary_polygons: Sequence[Sequence[Sequence[float]]] = (),
) -> CandidateRoute:
    failures = list(evidence_failures)
    try:
        segments = parse_overpass_segments(osm_payload, route.route_mode)
    except (AttributeError, TypeError, ValueError) as exc:
        segments = []
        failures.append(f"OSM 数据格式异常：{exc}")
    snap_ratio = compute_snap_ratio(
        route.polyline_gcj02,
        segments,
        tolerance_m=DEFAULT_SNAP_TOLERANCE_M,
    )
    if route.geometry_source != "amap_direction" or route.geometry_status != "complete" or not route.raw_response_paths:
        failures.append("高德几何或原始响应不完整")
    if route.actual_distance_m <= 0 or route.duration_s <= 0:
        failures.append("距离或时长无效")
    valid_verified_at = verified_at.tzinfo is not None and verified_at.utcoffset() is not None
    if not valid_verified_at:
        failures.append("验证时间缺少时区")
    valid_network_version = bool(network_version and network_version.strip())
    if not valid_network_version:
        failures.append("路网版本为空")
    if not segments:
        failures.append("OSM 未返回可通行路段")
    elif snap_ratio < 0.98:
        failures.append(f"路网贴合率 {snap_ratio:.1%} 低于 98%")
    error_ratio = distance_error_ratio(route)
    if error_ratio > 0.03:
        failures.append(f"几何长度与 API 距离误差 {error_ratio:.1%} 超过 3%")
    target_error_ratio = abs(route.actual_distance_m - route.target_distance_m) / route.target_distance_m
    if target_error_ratio > MAX_TARGET_DISTANCE_ERROR_RATIO:
        failures.append(f"实际距离与目标距离误差 {target_error_ratio:.1%} 超过 15%")
    inside_ratio = None
    if boundary_polygons:
        inside_ratio = compute_route_inside_ratio(route.polyline_gcj02, boundary_polygons)
        endpoints_inside = all(
            _point_in_any_polygon((point.lng_wgs84, point.lat_wgs84), boundary_polygons)
            for point in (route.polyline_gcj02[0], route.polyline_gcj02[-1])
        )
        if not endpoints_inside:
            failures.append("起点或终点位于徐汇区外")
        if inside_ratio < 0.9:
            failures.append(f"轨迹徐汇区内比例 {inside_ratio:.1%} 低于 90%")

    update = {
        "validation_status": "needs_review" if failures else "accepted",
        "snap_ratio": snap_ratio,
        "network_source": network_version.strip() if valid_network_version else None,
        "verified_at": verified_at if valid_verified_at else None,
        "review_note": "；".join(failures) if failures else "OSM 贴路率和 API 距离误差检查通过",
        "route_inside_ratio": inside_ratio,
    }
    payload = route.model_dump()
    payload.update(update)
    return CandidateRoute.model_validate(payload)


def compute_route_inside_ratio(
    points: Sequence[CoordinatePair],
    boundary_polygons: Sequence[Sequence[Sequence[float]]],
    spacing_m: float = 20,
) -> float:
    samples = _sample_polyline(_as_wgs_points(points), spacing_m)
    if not samples:
        return 0.0
    inside = sum(_point_in_any_polygon(point, boundary_polygons) for point in samples)
    return inside / len(samples)


def _point_in_any_polygon(point: WgsPoint, polygons: Sequence[Sequence[Sequence[float]]]) -> bool:
    return any(_point_in_polygon(point, polygon) for polygon in polygons)


def _point_in_polygon(point: WgsPoint, ring: Sequence[Sequence[float]]) -> bool:
    x, y = point
    inside = False
    for index, first in enumerate(ring):
        second = ring[index - 1]
        x1, y1 = float(first[0]), float(first[1])
        x2, y2 = float(second[0]), float(second[1])
        if _point_on_segment(point, (x1, y1), (x2, y2)):
            return True
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def _point_on_segment(point: WgsPoint, first: WgsPoint, second: WgsPoint) -> bool:
    x, y = point
    x1, y1 = first
    x2, y2 = second
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    return abs(cross) <= 1e-10 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)


def geometry_signature(route: CandidateRoute, spacing_m: float = 20, precision: int = 5) -> tuple[WgsPoint, ...]:
    points = _as_wgs_points(route.polyline_gcj02)
    if points and points[-1] < points[0]:
        points.reverse()
    return tuple((round(lng, precision), round(lat, precision)) for lng, lat in _sample_polyline(points, spacing_m))


def find_duplicate_routes(
    routes: Iterable[CandidateRoute], *, overlap_threshold: float = 0.9, tolerance_m: float = 20
) -> dict[str, list[str]]:
    if not 0 <= overlap_threshold <= 1:
        raise ValueError("overlap_threshold must be between 0 and 1")
    route_list = list(routes)
    parents = list(range(len(route_list)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for index, route in enumerate(route_list):
        for candidate_index in range(index + 1, len(route_list)):
            candidate = route_list[candidate_index]
            if route.route_mode != candidate.route_mode:
                continue
            if geometry_signature(route) == geometry_signature(candidate) or _bidirectional_overlap(
                route, candidate, tolerance_m
            ) >= overlap_threshold:
                union(index, candidate_index)

    components: dict[int, list[str]] = {}
    for index, route in enumerate(route_list):
        components.setdefault(find(index), []).append(route.route_id)
    duplicates: dict[str, list[str]] = {}
    for route_ids in components.values():
        if len(route_ids) > 1:
            duplicates[route_ids[0]] = route_ids[1:]
    return duplicates


class OverpassClient:
    def __init__(
        self,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        *,
        timeout: float = 30,
        cache_dir: Path,
        session: Any = requests,
        method: Literal["get", "post"] = "post",
        user_agent: str = (
            "XuhuiRouteBuilder/0.1 (academic route validation; "
            "https://github.com/Zion-Johnson99/AI_Scientist_shanghai_route)"
        ),
    ) -> None:
        if method not in {"get", "post"}:
            raise ValueError("method must be get or post")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if not endpoint.startswith("https://"):
            raise ValueError("endpoint must use HTTPS")
        self.endpoint = endpoint
        self.timeout = timeout
        self.cache_dir = cache_dir
        self.session = session
        self.method = method
        self.user_agent = user_agent

    def query(self, query: str) -> dict[str, Any]:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{digest}.json"
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Overpass cache invalid: query_hash={digest}, path={cache_path}") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
                raise RuntimeError(f"Overpass cache invalid: query_hash={digest}, path={cache_path}")
            return payload
        try:
            request = self.session.get if self.method == "get" else self.session.post
            kwargs = {"params": {"data": query}} if self.method == "get" else {"data": {"data": query}}
            response = request(
                self.endpoint,
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Overpass request failed: method={self.method}, endpoint={self.endpoint}, "
                f"timeout={self.timeout}, query_hash={digest}"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
            raise RuntimeError(f"Overpass response invalid: endpoint={self.endpoint}, query_hash={digest}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.cache_dir, prefix=f".{digest}.", suffix=".tmp", delete=False
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False)
                temporary_path = handle.name
            os.replace(temporary_path, cache_path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return payload


def _mode_allows(tags: dict[str, Any], route_mode: RouteMode) -> bool:
    highway = str(tags.get("highway", ""))
    walk_highways = {
        "living_street", "residential", "service", "track", "footway", "path", "pedestrian", "steps",
        "cycleway", "unclassified", "tertiary", "secondary", "primary",
    }
    bike_highways = {
        "living_street", "residential", "service", "track", "footway", "path", "pedestrian", "cycleway",
        "unclassified", "tertiary", "secondary", "primary",
    }
    if tags.get("access") in {"no", "private"} or "construction" in tags or "proposed" in tags:
        return False
    if route_mode in {"walk", "run"}:
        return highway in walk_highways and tags.get("foot") not in {"no", "private"}
    if route_mode in {"bike", "bike_assist"}:
        if highway not in bike_highways or tags.get("bicycle") in {"no", "private"}:
            return False
        return True
    return False


def _as_wgs_points(points: Sequence[CoordinatePair | WgsPoint]) -> list[WgsPoint]:
    return [
        (float(point.lng_wgs84), float(point.lat_wgs84)) if isinstance(point, CoordinatePair) else (float(point[0]), float(point[1]))
        for point in points
    ]


def _sample_polyline(points: Sequence[WgsPoint], spacing_m: float) -> list[WgsPoint]:
    if not points:
        return []
    if len(points) == 1:
        return [points[0]]
    total = polyline_length_m(points)
    if total == 0:
        return [points[0]]
    targets = [index * spacing_m for index in range(math.floor(total / spacing_m) + 1)]
    if total - targets[-1] > 0.01:
        targets.append(total)
    samples: list[WgsPoint] = []
    travelled = 0.0
    target_index = 0
    for first, second in zip(points, points[1:]):
        segment_length = _distance_m(first, second)
        while target_index < len(targets) and targets[target_index] <= travelled + segment_length + 1e-9:
            fraction = 0 if segment_length == 0 else (targets[target_index] - travelled) / segment_length
            samples.append((first[0] + (second[0] - first[0]) * fraction, first[1] + (second[1] - first[1]) * fraction))
            target_index += 1
        travelled += segment_length
    return samples


def _distance_m(first: WgsPoint, second: WgsPoint) -> float:
    lat1, lat2 = math.radians(first[1]), math.radians(second[1])
    delta_lat = lat2 - lat1
    delta_lng = math.radians(second[0] - first[0])
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def _point_segment_distance_m(point: WgsPoint, segment: Segment) -> float:
    origin_lat = math.radians(point[1])
    scale_x = EARTH_RADIUS_M * math.cos(origin_lat) * math.pi / 180
    scale_y = EARTH_RADIUS_M * math.pi / 180
    ax, ay = (segment[0][0] - point[0]) * scale_x, (segment[0][1] - point[1]) * scale_y
    bx, by = (segment[1][0] - point[0]) * scale_x, (segment[1][1] - point[1]) * scale_y
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    fraction = 0.0 if denominator == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator))
    return math.hypot(ax + fraction * dx, ay + fraction * dy)


def _bidirectional_overlap(first: CandidateRoute, second: CandidateRoute, tolerance_m: float) -> float:
    first_points = _as_wgs_points(first.polyline_gcj02)
    second_points = _as_wgs_points(second.polyline_gcj02)
    first_segments = list(zip(first_points, first_points[1:]))
    second_segments = list(zip(second_points, second_points[1:]))
    if not first_segments or not second_segments:
        return 0.0
    first_samples = _sample_polyline(first_points, 20)
    second_samples = _sample_polyline(second_points, 20)
    first_covered = sum(
        min(_point_segment_distance_m(point, segment) for segment in second_segments) <= tolerance_m
        for point in first_samples
    ) / len(first_samples)
    second_covered = sum(
        min(_point_segment_distance_m(point, segment) for segment in first_segments) <= tolerance_m
        for point in second_samples
    ) / len(second_samples)
    return min(first_covered, second_covered)
