# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

"""从可追踪本地空间图层或路线元数据提取噪声代理特征。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import geopandas as gpd
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from weather_api_data.coordinates import XUHUI_PROJECTED_CRS, wgs84_to_utm51
from weather_api_data.route_segments import RouteSegment

FeatureStatus = Literal["ok", "partial"]
_FEATURE_TYPES = {"road", "railway", "poi", "intersection", "green", "water", "acoustic_zone"}
_ROAD_CLASS_SCORES = {
    "motorway": 1.0,
    "trunk": 0.9,
    "primary": 0.8,
    "secondary": 0.65,
    "tertiary": 0.5,
    "residential": 0.35,
    "service": 0.25,
    "path": 0.1,
    "footway": 0.05,
    "cycleway": 0.05,
}
_ACOUSTIC_ZONE_SCORES = {"1": 0.2, "2": 0.4, "3": 0.65, "4a": 0.85, "4b": 1.0}


class SpatialFeatureError(RuntimeError):
    """表示本地空间特征文件缺少坐标系、来源或必要属性。"""


@dataclass(frozen=True, slots=True)
class CatalogFeature:
    feature_type: str
    source_id: str
    geometry: BaseGeometry
    properties: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SpatialFeatureCatalog:
    source_path: Path
    features: tuple[CatalogFeature, ...]


@dataclass(frozen=True, slots=True)
class SegmentSpatialFeatures:
    segment_id: str
    route_id: str
    road_class_score: float | None
    distance_pressure_score: float | None
    poi_pressure_score: float | None
    intersection_pressure_score: float | None
    acoustic_zone_score: float | None
    green_water_mitigation: float | None
    feature_values: Mapping[str, object]
    source_ids: tuple[str, ...]
    completeness: float
    status: FeatureStatus


def load_spatial_feature_catalog(path: Path) -> SpatialFeatureCatalog:
    """读取带 source_id 的本地 GeoJSON 并统一投影到 EPSG:32651。"""

    if not path.is_file():
        raise SpatialFeatureError(f"本地空间特征文件不存在: {path}")
    try:
        frame = gpd.read_file(path)
    except (OSError, ValueError) as error:
        raise SpatialFeatureError(f"读取本地空间特征文件失败: {path}") from error
    if frame.empty:
        raise SpatialFeatureError(f"本地空间特征文件为空: {path}")
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    frame = frame.to_crs(XUHUI_PROJECTED_CRS)

    features: list[CatalogFeature] = []
    for index in range(len(frame)):
        row_mapping = cast(Mapping[object, object], frame.iloc[index].to_dict())
        properties = {
            str(key): _plain_scalar(value)
            for key, value in row_mapping.items()
            if str(key) != "geometry"
        }
        feature_type = str(properties.get("feature_type", "")).strip()
        source_id = str(properties.get("source_id", "")).strip()
        if feature_type not in _FEATURE_TYPES:
            raise SpatialFeatureError(
                f"第 {index + 1} 个空间特征 feature_type 无效: {feature_type}"
            )
        if not source_id:
            raise SpatialFeatureError(f"第 {index + 1} 个空间特征缺少 source_id")
        geometry = cast(BaseGeometry, frame.geometry.iloc[index])
        if geometry.is_empty or not geometry.is_valid:
            raise SpatialFeatureError(f"空间特征 {source_id} 几何为空或无效")
        features.append(CatalogFeature(feature_type, source_id, geometry, properties))
    return SpatialFeatureCatalog(path.resolve(), tuple(features))


def extract_segment_features(
    segment: RouteSegment,
    catalog: SpatialFeatureCatalog | None,
    *,
    buffer_m: float = 100.0,
) -> SegmentSpatialFeatures:
    """计算道路、距离、POI、路口、功能区和绿地水体六组归一化特征。"""

    if not math.isfinite(buffer_m) or buffer_m <= 0:
        raise SpatialFeatureError("空间特征缓冲半径需为正的有限数值")
    if catalog is None:
        return _route_metadata_features(segment)

    line = LineString([wgs84_to_utm51(*coordinate) for coordinate in segment.coordinates_wgs84])
    midpoint_x, midpoint_y = wgs84_to_utm51(*segment.midpoint_wgs84)
    midpoint = Point(midpoint_x, midpoint_y)
    search_area = line.buffer(buffer_m)
    by_type = {
        feature_type: tuple(
            feature for feature in catalog.features if feature.feature_type == feature_type
        )
        for feature_type in _FEATURE_TYPES
    }
    source_ids: list[str] = [f"local_feature_catalog:{catalog.source_path.name}"]
    values: dict[str, object] = {"feature_catalog": str(catalog.source_path)}

    road_score: float | None = None
    nearby_roads = [
        (feature.geometry.distance(line), feature)
        for feature in by_type["road"]
        if feature.geometry.distance(line) <= 50.0
    ]
    if nearby_roads:
        _, road = min(nearby_roads, key=lambda item: item[0])
        road_class = str(road.properties.get("road_class", "")).lower()
        road_score = _ROAD_CLASS_SCORES.get(road_class)
        if road_score is not None:
            values["road_class"] = road_class
            source_ids.append(road.source_id)

    distance_candidates = [
        feature
        for feature in by_type["road"]
        if str(feature.properties.get("road_class", "")).lower() in {"motorway", "trunk", "primary"}
        or bool(feature.properties.get("elevated"))
    ] + list(by_type["railway"])
    distance_score: float | None = None
    if distance_candidates:
        nearest_distance_feature = min(
            distance_candidates, key=lambda item: item.geometry.distance(line)
        )
        nearest_distance = float(nearest_distance_feature.geometry.distance(line))
        distance_score = _clamp01(1.0 - nearest_distance / 500.0)
        values["nearest_major_road_rail_m"] = round(nearest_distance, 3)
        source_ids.append(nearest_distance_feature.source_id)

    poi_score: float | None = None
    if by_type["poi"]:
        nearby_pois = [
            feature for feature in by_type["poi"] if feature.geometry.intersects(search_area)
        ]
        poi_score = _clamp01(len(nearby_pois) / 5.0)
        values["poi_count_100m"] = len(nearby_pois)
        source_ids.extend(feature.source_id for feature in nearby_pois)

    intersection_score: float | None = None
    if by_type["intersection"]:
        intersections = [
            feature
            for feature in by_type["intersection"]
            if feature.geometry.intersects(search_area)
        ]
        intersection_score = _clamp01(len(intersections) / 5.0)
        values["intersection_count_100m"] = len(intersections)
        source_ids.extend(feature.source_id for feature in intersections)

    acoustic_score: float | None = None
    acoustic_matches = [
        feature for feature in by_type["acoustic_zone"] if feature.geometry.covers(midpoint)
    ]
    if acoustic_matches:
        acoustic = acoustic_matches[0]
        zone_class = str(acoustic.properties.get("zone_class", "")).lower()
        acoustic_score = _ACOUSTIC_ZONE_SCORES.get(zone_class)
        if acoustic_score is not None:
            values["acoustic_zone_class"] = zone_class
            source_ids.append(acoustic.source_id)

    green_water_score: float | None = None
    natural_features = by_type["green"] + by_type["water"]
    if natural_features:
        intersection_area = sum(
            feature.geometry.intersection(search_area).area
            for feature in natural_features
            if feature.geometry.intersects(search_area)
        )
        coverage = _clamp01(float(intersection_area / search_area.area))
        green_water_score = coverage
        values["green_water_coverage_100m"] = round(coverage, 6)
        source_ids.extend(
            feature.source_id
            for feature in natural_features
            if feature.geometry.intersects(search_area)
        )

    feature_scores = (
        road_score,
        distance_score,
        poi_score,
        intersection_score,
        acoustic_score,
        green_water_score,
    )
    completeness = sum(value is not None for value in feature_scores) / len(feature_scores)
    return SegmentSpatialFeatures(
        segment_id=segment.segment_id,
        route_id=segment.route_id,
        road_class_score=road_score,
        distance_pressure_score=distance_score,
        poi_pressure_score=poi_score,
        intersection_pressure_score=intersection_score,
        acoustic_zone_score=acoustic_score,
        green_water_mitigation=green_water_score,
        feature_values=values,
        source_ids=tuple(dict.fromkeys(source_ids)),
        completeness=round(completeness, 6),
        status="ok" if completeness == 1.0 else "partial",
    )


def _route_metadata_features(segment: RouteSegment) -> SegmentSpatialFeatures:
    properties = segment.source_properties
    road_names = _string_list(properties.get("road_names"))
    tags = _string_list(properties.get("tags")) + _string_list(properties.get("feature_tags"))
    road_score = _route_road_score(road_names)
    poi_score, poi_source_ids = _route_poi_score(properties.get("nearby_pois"))
    intersection_score = _route_intersection_score(properties)
    green_water_score = _route_green_water_score(road_names + tags)
    network_source = str(properties.get("network_source", "")).strip()
    source_ids = [f"route_metadata:{segment.route_id}"]
    if network_source:
        source_ids.append(network_source)
    source_ids.extend(poi_source_ids)
    values: dict[str, object] = {
        "baseline": "route_metadata",
        "road_names": list(road_names),
        "tags": list(tags),
        "distance_layer": "missing",
        "acoustic_zone_layer": "missing",
    }
    feature_scores = (road_score, None, poi_score, intersection_score, None, green_water_score)
    completeness = sum(value is not None for value in feature_scores) / len(feature_scores)
    return SegmentSpatialFeatures(
        segment_id=segment.segment_id,
        route_id=segment.route_id,
        road_class_score=road_score,
        distance_pressure_score=None,
        poi_pressure_score=poi_score,
        intersection_pressure_score=intersection_score,
        acoustic_zone_score=None,
        green_water_mitigation=green_water_score,
        feature_values=values,
        source_ids=tuple(dict.fromkeys(source_ids)),
        completeness=round(completeness, 6),
        status="partial",
    )


def _route_road_score(road_names: tuple[str, ...]) -> float | None:
    if not road_names:
        return None
    joined = " ".join(road_names)
    if any(token in joined for token in ("高速", "快速", "高架")):
        return 1.0
    if any(token in joined for token in ("绿道", "步道", "园内")):
        return 0.15
    if "大道" in joined:
        return 0.8
    if any(token in joined for token in ("路", "街")):
        return 0.55
    return 0.4


def _route_poi_score(value: object) -> tuple[float | None, tuple[str, ...]]:
    if not isinstance(value, list):
        return None, ()
    relevant = 0
    source_ids: list[str] = []
    for raw_poi in cast(list[object], value):
        if not isinstance(raw_poi, Mapping):
            continue
        poi = cast(Mapping[object, object], raw_poi)
        poi_type = str(poi.get("poi_type", "")).lower()
        if poi_type in {
            "bus",
            "subway",
            "transport",
            "shopping",
            "commercial",
            "market",
            "restaurant",
            "coffee",
        }:
            relevant += 1
        source_id = str(poi.get("source_id", "")).strip()
        if source_id:
            source_ids.append(source_id)
    return _clamp01(relevant / 5.0), tuple(source_ids)


def _route_intersection_score(properties: Mapping[str, object]) -> float | None:
    turn_count = properties.get("turn_count")
    distance_m = properties.get("actual_distance_m")
    if isinstance(turn_count, bool) or not isinstance(turn_count, (int, float)):
        return None
    if isinstance(distance_m, bool) or not isinstance(distance_m, (int, float)) or distance_m <= 0:
        return None
    turns_per_km = float(turn_count) / (float(distance_m) / 1000.0)
    return _clamp01(turns_per_km / 12.0)


def _route_green_water_score(values: tuple[str, ...]) -> float | None:
    if not values:
        return None
    joined = " ".join(values)
    natural_hits = sum(
        token in joined for token in ("绿道", "公园", "滨江", "滨水", "水岸", "植物园", "河")
    )
    return _clamp01(natural_hits / 3.0)


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in cast(list[object], value) if str(item).strip())


def _plain_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = [
    "SegmentSpatialFeatures",
    "SpatialFeatureCatalog",
    "SpatialFeatureError",
    "extract_segment_features",
    "load_spatial_feature_catalog",
]
