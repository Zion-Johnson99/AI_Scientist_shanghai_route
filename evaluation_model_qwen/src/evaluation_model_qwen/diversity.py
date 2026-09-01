from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

from .models import Coordinate, ScoredRoute

EARTH_RADIUS_M = 6_371_008.8
Point = tuple[float, float]
Segment = tuple[Point, Point]


def select_diverse_candidates(
    candidates: Sequence[ScoredRoute],
    *,
    limit: int = 5,
    overlap_threshold: float = 0.9,
    tolerance_m: float = 50,
) -> list[ScoredRoute]:
    """按原排序贪心选取候选并跳过轨迹高度重合的路线。"""
    selected: list[ScoredRoute] = []
    for candidate in candidates:
        if any(
            _bidirectional_overlap(
                candidate.route.geometry_gcj02,
                existing.route.geometry_gcj02,
                tolerance_m,
            )
            >= overlap_threshold
            for existing in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) == limit:
            break
    return selected


def _bidirectional_overlap(
    first_coordinates: Sequence[Coordinate],
    second_coordinates: Sequence[Coordinate],
    tolerance_m: float,
) -> float:
    first = _points(first_coordinates)
    second = _points(second_coordinates)
    first_segments = list(itertools.pairwise(first))
    second_segments = list(itertools.pairwise(second))
    if not first_segments or not second_segments:
        return 0.0
    first_samples = _sample_polyline(first, 20)
    second_samples = _sample_polyline(second, 20)
    first_covered = sum(
        min(_point_segment_distance_m(point, segment) for segment in second_segments) <= tolerance_m
        for point in first_samples
    ) / len(first_samples)
    second_covered = sum(
        min(_point_segment_distance_m(point, segment) for segment in first_segments) <= tolerance_m
        for point in second_samples
    ) / len(second_samples)
    return min(first_covered, second_covered)


def _points(coordinates: Sequence[Coordinate]) -> list[Point]:
    return [(point.lng_gcj02, point.lat_gcj02) for point in coordinates]


def _sample_polyline(points: Sequence[Point], spacing_m: float) -> list[Point]:
    if not points:
        return []
    if len(points) == 1:
        return [points[0]]
    lengths = [_distance_m(first, second) for first, second in itertools.pairwise(points)]
    total = sum(lengths)
    if total == 0:
        return [points[0]]
    targets = [index * spacing_m for index in range(math.floor(total / spacing_m) + 1)]
    if total - targets[-1] > 0.01:
        targets.append(total)
    samples: list[Point] = []
    travelled = 0.0
    target_index = 0
    for (first, second), segment_length in zip(itertools.pairwise(points), lengths):
        while (
            target_index < len(targets)
            and targets[target_index] <= travelled + segment_length + 1e-9
        ):
            fraction = (
                0.0 if segment_length == 0 else (targets[target_index] - travelled) / segment_length
            )
            samples.append(
                (
                    first[0] + (second[0] - first[0]) * fraction,
                    first[1] + (second[1] - first[1]) * fraction,
                )
            )
            target_index += 1
        travelled += segment_length
    return samples


def _distance_m(first: Point, second: Point) -> float:
    first_lat = math.radians(first[1])
    second_lat = math.radians(second[1])
    delta_lat = second_lat - first_lat
    delta_lng = math.radians(second[0] - first[0])
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def _point_segment_distance_m(point: Point, segment: Segment) -> float:
    origin_lat = math.radians(point[1])
    scale_x = EARTH_RADIUS_M * math.cos(origin_lat) * math.pi / 180
    scale_y = EARTH_RADIUS_M * math.pi / 180
    first_x = (segment[0][0] - point[0]) * scale_x
    first_y = (segment[0][1] - point[1]) * scale_y
    second_x = (segment[1][0] - point[0]) * scale_x
    second_y = (segment[1][1] - point[1]) * scale_y
    delta_x = second_x - first_x
    delta_y = second_y - first_y
    denominator = delta_x * delta_x + delta_y * delta_y
    fraction = (
        0.0
        if denominator == 0
        else max(
            0.0,
            min(1.0, -(first_x * delta_x + first_y * delta_y) / denominator),
        )
    )
    return math.hypot(first_x + fraction * delta_x, first_y + fraction * delta_y)


__all__ = ["select_diverse_candidates"]
