"""徐汇路线空间计算使用的坐标转换。"""

from __future__ import annotations

import math

from pyproj import Transformer

WGS84_CRS = "EPSG:4326"
XUHUI_PROJECTED_CRS = "EPSG:32651"

_SEMI_MAJOR_AXIS = 6378245.0
_ECCENTRICITY_SQUARED = 0.006693421622965943
_WGS84_TO_UTM51 = Transformer.from_crs(WGS84_CRS, XUHUI_PROJECTED_CRS, always_xy=True)
_UTM51_TO_WGS84 = Transformer.from_crs(XUHUI_PROJECTED_CRS, WGS84_CRS, always_xy=True)


class CoordinateError(ValueError):
    """表示经纬度或投影坐标超出可计算范围。"""


def gcj02_to_wgs84(longitude: float, latitude: float) -> tuple[float, float]:
    """将中国境内的 GCJ-02 坐标近似反解为 WGS84。"""

    _validate_longitude_latitude(longitude, latitude)
    if not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271):
        raise CoordinateError("GCJ-02 坐标需位于中国大陆有效范围内")
    delta_longitude, delta_latitude = _gcj_delta(longitude, latitude)
    return longitude - delta_longitude, latitude - delta_latitude


def wgs84_to_utm51(longitude: float, latitude: float) -> tuple[float, float]:
    """把 WGS84 经度、纬度投影到 EPSG:32651 米制坐标。"""

    _validate_longitude_latitude(longitude, latitude)
    easting, northing = _WGS84_TO_UTM51.transform(longitude, latitude)
    if not math.isfinite(easting) or not math.isfinite(northing):
        raise CoordinateError("WGS84 到 EPSG:32651 的投影结果无效")
    return float(easting), float(northing)


def utm51_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """把 EPSG:32651 米制坐标反投影到 WGS84。"""

    if not math.isfinite(easting) or not math.isfinite(northing):
        raise CoordinateError("EPSG:32651 坐标需为有限数值")
    longitude, latitude = _UTM51_TO_WGS84.transform(easting, northing)
    _validate_longitude_latitude(float(longitude), float(latitude))
    return float(longitude), float(latitude)


def _validate_longitude_latitude(longitude: float, latitude: float) -> None:
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise CoordinateError("经纬度需为有限数值")
    if not -180.0 <= longitude <= 180.0 or not -90.0 <= latitude <= 90.0:
        raise CoordinateError("经纬度超出有效范围")


def _gcj_delta(longitude: float, latitude: float) -> tuple[float, float]:
    latitude_offset = _transform_latitude(longitude - 105.0, latitude - 35.0)
    longitude_offset = _transform_longitude(longitude - 105.0, latitude - 35.0)
    radian_latitude = latitude / 180.0 * math.pi
    magic = math.sin(radian_latitude)
    magic = 1 - _ECCENTRICITY_SQUARED * magic * magic
    square_root_magic = math.sqrt(magic)
    latitude_offset = (
        latitude_offset
        * 180.0
        / ((_SEMI_MAJOR_AXIS * (1 - _ECCENTRICITY_SQUARED)) / (magic * square_root_magic) * math.pi)
    )
    longitude_offset = (
        longitude_offset
        * 180.0
        / (_SEMI_MAJOR_AXIS / square_root_magic * math.cos(radian_latitude) * math.pi)
    )
    return longitude_offset, latitude_offset


def _transform_latitude(x_value: float, y_value: float) -> float:
    result = (
        -100.0
        + 2.0 * x_value
        + 3.0 * y_value
        + 0.2 * y_value * y_value
        + 0.1 * x_value * y_value
        + 0.2 * math.sqrt(abs(x_value))
    )
    result += (
        (20.0 * math.sin(6.0 * x_value * math.pi) + 20.0 * math.sin(2.0 * x_value * math.pi))
        * 2.0
        / 3.0
    )
    result += (
        (20.0 * math.sin(y_value * math.pi) + 40.0 * math.sin(y_value / 3.0 * math.pi)) * 2.0 / 3.0
    )
    return (
        result
        + (160.0 * math.sin(y_value / 12.0 * math.pi) + 320 * math.sin(y_value * math.pi / 30.0))
        * 2.0
        / 3.0
    )


def _transform_longitude(x_value: float, y_value: float) -> float:
    result = (
        300.0
        + x_value
        + 2.0 * y_value
        + 0.1 * x_value * x_value
        + 0.1 * x_value * y_value
        + 0.1 * math.sqrt(abs(x_value))
    )
    result += (
        (20.0 * math.sin(6.0 * x_value * math.pi) + 20.0 * math.sin(2.0 * x_value * math.pi))
        * 2.0
        / 3.0
    )
    result += (
        (20.0 * math.sin(x_value * math.pi) + 40.0 * math.sin(x_value / 3.0 * math.pi)) * 2.0 / 3.0
    )
    return (
        result
        + (150.0 * math.sin(x_value / 12.0 * math.pi) + 300.0 * math.sin(x_value / 30.0 * math.pi))
        * 2.0
        / 3.0
    )


__all__ = [
    "WGS84_CRS",
    "XUHUI_PROJECTED_CRS",
    "CoordinateError",
    "gcj02_to_wgs84",
    "utm51_to_wgs84",
    "wgs84_to_utm51",
]
