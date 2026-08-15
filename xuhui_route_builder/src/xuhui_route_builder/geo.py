from __future__ import annotations

import math
from typing import Any

from .models import CoordinatePair

EE = 0.00669342162296594323
A = 6378245.0


def parse_lng_lat(value: str) -> CoordinatePair:
    lng_text, lat_text = value.split(",", 1)
    lng = float(lng_text)
    lat = float(lat_text)
    wgs_lng, wgs_lat = gcj02_to_wgs84(lng, lat)
    return CoordinatePair(
        lng_gcj02=lng, lat_gcj02=lat, lng_wgs84=wgs_lng, lat_wgs84=wgs_lat
    )


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    if _outside_china(lng, lat):
        return lng, lat
    wgs_lng, wgs_lat = lng, lat
    for _ in range(3):
        estimated_lng, estimated_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        wgs_lng += lng - estimated_lng
        wgs_lat += lat - estimated_lat
    return round(wgs_lng, 6), round(wgs_lat, 6)


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if _outside_china(lng, lat):
        return lng, lat
    dlng, dlat = _coordinate_offset(lng, lat)
    return round(lng + dlng, 6), round(lat + dlat, 6)


def _coordinate_offset(lng: float, lat: float) -> tuple[float, float]:
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (A / sqrt_magic * math.cos(radlat) * math.pi)
    return dlng, dlat


def parse_amap_boundary(response: dict[str, Any]) -> dict[str, Any]:
    districts = response.get("districts") or []
    if not districts:
        raise ValueError("Amap district response has no districts")
    district = districts[0]
    polyline = district.get("polyline")
    if not polyline:
        raise ValueError("Amap district response has no polyline")
    polygon_text = polyline.split("|")[0]
    ring = [
        [float(lng), float(lat)]
        for lng, lat in (point.split(",", 1) for point in polygon_text.split(";"))
    ]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    center = parse_lng_lat(district.get("center", "0,0"))
    return {
        "type": "Feature",
        "properties": {
            "district_name": district.get("name"),
            "adcode": district.get("adcode"),
            "citycode": district.get("citycode"),
            "level": district.get("level"),
            "center_lng_gcj02": center.lng_gcj02,
            "center_lat_gcj02": center.lat_gcj02,
            "center_lng_wgs84": center.lng_wgs84,
            "center_lat_wgs84": center.lat_wgs84,
            "source_api": "amap.district",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [ring],
        },
    }


def polyline_to_coordinate_pairs(polyline: list[str]) -> list[CoordinatePair]:
    return [parse_lng_lat(point) for point in polyline]


def _outside_china(lng: float, lat: float) -> bool:
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(lng: float, lat: float) -> float:
    ret = (
        -100.0
        + 2.0 * lng
        + 3.0 * lat
        + 0.2 * lat * lat
        + 0.1 * lng * lat
        + 0.2 * math.sqrt(abs(lng))
    )
    ret += (
        (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi))
        * 2.0
        / 3.0
    )
    ret += (
        (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi))
        * 2.0
        / 3.0
    )
    ret += (
        (160.0 * math.sin(lat / 12.0 * math.pi) + 320 * math.sin(lat * math.pi / 30.0))
        * 2.0
        / 3.0
    )
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = (
        300.0
        + lng
        + 2.0 * lat
        + 0.1 * lng * lng
        + 0.1 * lng * lat
        + 0.1 * math.sqrt(abs(lng))
    )
    ret += (
        (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi))
        * 2.0
        / 3.0
    )
    ret += (
        (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi))
        * 2.0
        / 3.0
    )
    ret += (
        (
            150.0 * math.sin(lng / 12.0 * math.pi)
            + 300.0 * math.sin(lng / 30.0 * math.pi)
        )
        * 2.0
        / 3.0
    )
    return ret
