from __future__ import annotations

from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

from .models import RouteRecord, UserProfile


class ScoringError(ValueError):
    """评分输入不满足可计算条件。"""


def validate_target_time(target_time: datetime, generated_at: datetime) -> None:
    """目标时刻只允许位于数据生成时刻至未来 24 小时。"""
    if target_time.tzinfo is None or generated_at.tzinfo is None:
        raise ScoringError("目标时间和数据生成时间需包含时区")
    if target_time < generated_at or target_time > generated_at + timedelta(hours=24):
        raise ScoringError("目标时间需位于现在到未来 24 小时内")


def haversine_gcj02(
    lng1: float,
    lat1: float,
    lng2: float,
    lat2: float,
) -> float:
    """计算两个 GCJ-02 坐标间的球面直线距离, 单位为米。"""
    radius_m = 6_371_008.8
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = lat2_rad - lat1_rad
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lng / 2) ** 2
    return 2 * radius_m * asin(sqrt(value))


def filter_candidates(
    routes: list[RouteRecord], profile: UserProfile
) -> list[tuple[RouteRecord, float | None]]:
    """执行路线验收、方式、距离、形态、区域和半径硬过滤。"""
    candidates: list[tuple[RouteRecord, float | None]] = []
    for route in routes:
        if route.validation_status != "accepted" or route.geometry_status != "complete":
            continue
        if route.route_mode != profile.route_mode:
            continue
        if not profile.distance_min_m <= route.distance_m <= profile.distance_max_m:
            continue
        if profile.route_shape != "any" and route.route_shape != profile.route_shape:
            continue
        if profile.area_ids and not (
            set(profile.area_ids).intersection(route.popular_area_ids)
            or route.region_zone in profile.area_ids
        ):
            continue

        access_distance_m: float | None = None
        if profile.origin is not None:
            access_distance_m = haversine_gcj02(
                profile.origin.lng_gcj02,
                profile.origin.lat_gcj02,
                route.start_location.lng_gcj02,
                route.start_location.lat_gcj02,
            )
            if profile.search_radius_m is not None and access_distance_m > profile.search_radius_m:
                continue
        candidates.append((route, access_distance_m))
    return candidates
