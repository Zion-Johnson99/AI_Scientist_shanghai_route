"""读取 GCJ-02 路线并在徐汇本地米制坐标系中稳定切段。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from shapely.geometry import LineString
from shapely.ops import substring

from weather_api_data.coordinates import (
    WGS84_CRS,
    XUHUI_PROJECTED_CRS,
    gcj02_to_wgs84,
    utm51_to_wgs84,
    wgs84_to_utm51,
)


class RouteSegmentError(RuntimeError):
    """表示路线或 PM2.5 网格文件不满足空间处理契约。"""


@dataclass(frozen=True, slots=True)
class RouteSegment:
    """使用 WGS84 几何的约 100 米路线计算段。"""

    segment_id: str
    route_id: str
    segment_index: int
    length_m: float
    coordinates_wgs84: tuple[tuple[float, float], ...]
    midpoint_wgs84: tuple[float, float]
    pm25_grid_id: str | None
    source_properties: Mapping[str, object]
    pm25_grid_distance_m: float | None = None
    pm25_grid_source: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "route_id": self.route_id,
            "segment_index": self.segment_index,
            "length_m": self.length_m,
            "geometry": {
                "type": "LineString",
                "coordinates": [list(coordinate) for coordinate in self.coordinates_wgs84],
                "crs": WGS84_CRS,
            },
            "midpoint_wgs84": {
                "longitude": self.midpoint_wgs84[0],
                "latitude": self.midpoint_wgs84[1],
            },
            "pm25_grid_id": self.pm25_grid_id,
            "pm25_grid_distance_m": self.pm25_grid_distance_m,
            "pm25_grid_source": self.pm25_grid_source,
        }


@dataclass(frozen=True, slots=True)
class _Pm25GridCenter:
    grid_id: str
    easting: float
    northing: float


def load_route_segments(
    routes_path: Path,
    *,
    target_length_m: float = 100.0,
) -> tuple[RouteSegment, ...]:
    """读取 GeoJSON 中全部 LineString 路线并按目标米制长度切分。"""

    if not math.isfinite(target_length_m) or target_length_m <= 0:
        raise RouteSegmentError("路线目标切段长度需为正的有限数值")
    document = _read_json(routes_path, "路线文件")
    if document.get("type") != "FeatureCollection":
        raise RouteSegmentError("路线文件顶层 type 需为 FeatureCollection")
    raw_features = document.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise RouteSegmentError("路线文件缺少 features")

    segments: list[RouteSegment] = []
    route_ids: set[str] = set()
    for raw_feature in cast(list[object], raw_features):
        feature = _mapping(raw_feature, "路线 feature")
        properties = _mapping(feature.get("properties"), "路线 properties")
        route_id = str(properties.get("route_id", "")).strip()
        if not route_id:
            raise RouteSegmentError("路线缺少 route_id")
        if route_id in route_ids:
            raise RouteSegmentError(f"路线 route_id 重复: {route_id}")
        route_ids.add(route_id)
        geometry = _mapping(feature.get("geometry"), f"路线 {route_id} geometry")
        if geometry.get("type") != "LineString":
            raise RouteSegmentError(f"路线 {route_id} geometry 需为 LineString")
        coordinates = _coordinates(geometry.get("coordinates"), route_id)
        segments.extend(_split_route(route_id, coordinates, properties, target_length_m))
    return tuple(segments)


def assign_pm25_grids(
    segments: Sequence[RouteSegment],
    pm25_grid_path: Path,
    *,
    max_distance_m: float = 1500.0,
) -> tuple[RouteSegment, ...]:
    """把路线段中点关联到最近 PM2.5 网格中心并保留米制误差。"""

    if not math.isfinite(max_distance_m) or max_distance_m <= 0:
        raise RouteSegmentError("PM2.5 网格关联距离上限需为正的有限数值")
    centers = _load_pm25_centers(pm25_grid_path)
    source = str(pm25_grid_path.resolve())
    assigned: list[RouteSegment] = []
    for segment in segments:
        midpoint_x, midpoint_y = wgs84_to_utm51(*segment.midpoint_wgs84)
        nearest = min(
            centers,
            key=lambda center: math.hypot(
                center.easting - midpoint_x,
                center.northing - midpoint_y,
            ),
        )
        distance = math.hypot(nearest.easting - midpoint_x, nearest.northing - midpoint_y)
        if distance > max_distance_m:
            assigned.append(
                replace(
                    segment,
                    pm25_grid_id=None,
                    pm25_grid_distance_m=round(distance, 3),
                    pm25_grid_source=source,
                )
            )
            continue
        assigned.append(
            replace(
                segment,
                pm25_grid_id=nearest.grid_id,
                pm25_grid_distance_m=round(distance, 3),
                pm25_grid_source=source,
            )
        )
    return tuple(assigned)


def build_route_segments_document(
    routes_path: Path,
    *,
    target_length_m: float = 100.0,
    pm25_grid_path: Path | None = None,
    pm25_grid_max_distance_m: float = 1500.0,
) -> dict[str, object]:
    """构建可直接 JSON 序列化的路线切段文档。"""

    segments = load_route_segments(routes_path, target_length_m=target_length_m)
    if pm25_grid_path is not None:
        segments = assign_pm25_grids(
            segments,
            pm25_grid_path,
            max_distance_m=pm25_grid_max_distance_m,
        )
    route_count = len({segment.route_id for segment in segments})
    unmatched = sum(segment.pm25_grid_id is None for segment in segments)
    return {
        "schema_version": "1.0",
        "dataset_type": "route_segments",
        "status": "partial" if pm25_grid_path is not None and unmatched else "ok",
        "source_path": str(routes_path.resolve()),
        "source_crs": "GCJ-02",
        "geometry_crs": WGS84_CRS,
        "analysis_crs": XUHUI_PROJECTED_CRS,
        "target_segment_length_m": target_length_m,
        "route_count": route_count,
        "segment_count": len(segments),
        "pm25_grid_source": str(pm25_grid_path.resolve()) if pm25_grid_path else None,
        "pm25_grid_max_distance_m": pm25_grid_max_distance_m if pm25_grid_path else None,
        "pm25_grid_unmatched_segments": unmatched if pm25_grid_path else None,
        "segments": [segment.to_dict() for segment in segments],
    }


def _split_route(
    route_id: str,
    coordinates_gcj02: tuple[tuple[float, float], ...],
    properties: Mapping[str, object],
    target_length_m: float,
) -> tuple[RouteSegment, ...]:
    coordinates_wgs84 = tuple(gcj02_to_wgs84(*coordinate) for coordinate in coordinates_gcj02)
    projected = LineString([wgs84_to_utm51(*coordinate) for coordinate in coordinates_wgs84])
    if projected.is_empty or projected.length <= 0:
        raise RouteSegmentError(f"路线 {route_id} 的米制几何长度无效")
    count = max(1, math.ceil(projected.length / target_length_m))
    tail_length = projected.length - (count - 1) * target_length_m
    minimum_tail_length = min(10.0, target_length_m * 0.1)
    if count > 1 and tail_length < minimum_tail_length:
        count -= 1
    segments: list[RouteSegment] = []
    for index in range(count):
        start = min(index * target_length_m, projected.length)
        end = projected.length if index == count - 1 else (index + 1) * target_length_m
        geometry = substring(projected, start, end)
        if not isinstance(geometry, LineString) or geometry.length <= 0:
            raise RouteSegmentError(f"路线 {route_id} 第 {index + 1} 段几何无效")
        wgs84_coordinates = tuple(
            (round(longitude, 7), round(latitude, 7))
            for longitude, latitude in (
                utm51_to_wgs84(float(x_value), float(y_value))
                for x_value, y_value in geometry.coords
            )
        )
        midpoint = geometry.interpolate(0.5, normalized=True)
        midpoint_wgs84 = utm51_to_wgs84(float(midpoint.x), float(midpoint.y))
        segments.append(
            RouteSegment(
                segment_id=f"{route_id}_S{index + 1:04d}",
                route_id=route_id,
                segment_index=index + 1,
                length_m=round(float(geometry.length), 3),
                coordinates_wgs84=wgs84_coordinates,
                midpoint_wgs84=(round(midpoint_wgs84[0], 7), round(midpoint_wgs84[1], 7)),
                pm25_grid_id=None,
                source_properties=dict(properties),
            )
        )
    return tuple(segments)


def _load_pm25_centers(path: Path) -> tuple[_Pm25GridCenter, ...]:
    document = _read_json(path, "PM2.5 网格文件")
    raw_grids = document.get("grids")
    if not isinstance(raw_grids, list) or not raw_grids:
        raise RouteSegmentError("PM2.5 网格文件缺少 grids")
    centers: list[_Pm25GridCenter] = []
    grid_ids: set[str] = set()
    for raw_grid in cast(list[object], raw_grids):
        grid = _mapping(raw_grid, "PM2.5 grid")
        grid_id = str(grid.get("grid_id", "")).strip()
        if not grid_id or grid_id in grid_ids:
            raise RouteSegmentError(f"PM2.5 grid_id 缺失或重复: {grid_id}")
        grid_ids.add(grid_id)
        longitude = _number(grid.get("longitude"), f"网格 {grid_id} longitude")
        latitude = _number(grid.get("latitude"), f"网格 {grid_id} latitude")
        easting, northing = wgs84_to_utm51(longitude, latitude)
        centers.append(_Pm25GridCenter(grid_id, easting, northing))
    return tuple(centers)


def _coordinates(value: object, route_id: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        raise RouteSegmentError(f"路线 {route_id} 至少需要两个坐标点")
    raw_coordinates = cast(list[object], value)
    if len(raw_coordinates) < 2:
        raise RouteSegmentError(f"路线 {route_id} 至少需要两个坐标点")
    coordinates: list[tuple[float, float]] = []
    for index, raw_coordinate in enumerate(raw_coordinates):
        if not isinstance(raw_coordinate, list):
            raise RouteSegmentError(f"路线 {route_id} 第 {index + 1} 个坐标格式无效")
        coordinate = cast(list[object], raw_coordinate)
        if len(coordinate) < 2:
            raise RouteSegmentError(f"路线 {route_id} 第 {index + 1} 个坐标格式无效")
        coordinates.append(
            (
                _number(coordinate[0], f"路线 {route_id} longitude"),
                _number(coordinate[1], f"路线 {route_id} latitude"),
            )
        )
    return tuple(coordinates)


def _read_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise RouteSegmentError(f"{label}不存在: {path}")
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RouteSegmentError(f"{label}读取失败: {path}") from error
    if not isinstance(decoded, dict):
        raise RouteSegmentError(f"{label}顶层需为对象")
    return cast(dict[str, object], decoded)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RouteSegmentError(f"{label}需为对象")
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouteSegmentError(f"{label}需为数值")
    result = float(value)
    if not math.isfinite(result):
        raise RouteSegmentError(f"{label}需为有限数值")
    return result


__all__ = [
    "RouteSegment",
    "RouteSegmentError",
    "assign_pm25_grids",
    "build_route_segments_document",
    "load_route_segments",
]
