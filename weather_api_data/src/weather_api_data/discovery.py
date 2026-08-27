"""徐汇区采样点的 LocationKey 与空气质量来源发现。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from weather_api_data.advanced_client import AdvancedClient
from weather_api_data.models import SamplingPoint

_POINT_KEYS = {"point_id", "name", "longitude", "latitude"}
_EXPECTED_POINT_COUNT = 14
DiscoveryStatus = Literal["ok", "partial"]
SourceStatus = Literal["ok", "unknown"]


class DiscoveryError(ValueError):
    """采样点配置或发现响应违反明确契约。"""


@dataclass(frozen=True, slots=True)
class LocationDiscovery:
    """一个 LocationKey 及其覆盖的采样点。"""

    location_key: str
    location_name: str
    administrative_area: Mapping[str, object]
    geo_position: Mapping[str, object]
    probe_point_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "location_key": self.location_key,
            "location_name": self.location_name,
            "administrative_area": _plain_mapping(self.administrative_area),
            "geo_position": _plain_mapping(self.geo_position),
            "probe_point_ids": list(self.probe_point_ids),
        }


@dataclass(frozen=True, slots=True)
class AirQualitySourceDiscovery:
    """一个 LocationKey 返回的当前空气质量来源。"""

    location_key: str
    probe_point_ids: tuple[str, ...]
    source: str | None
    source_status: SourceStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "location_key": self.location_key,
            "probe_point_ids": list(self.probe_point_ids),
            "source": self.source,
            "source_status": self.source_status,
        }


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """一轮空间来源发现的可序列化结果。"""

    status: DiscoveryStatus
    locations: tuple[LocationDiscovery, ...]
    air_quality_sources: tuple[AirQualitySourceDiscovery, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "locations": [location.to_dict() for location in self.locations],
            "air_quality_sources": [source.to_dict() for source in self.air_quality_sources],
        }


@dataclass(slots=True)
class _MutableLocation:
    location_key: str
    location_name: str
    administrative_area: dict[str, object]
    geo_position: dict[str, object]
    probe_point_ids: list[str]


def load_sampling_points(path: str | Path) -> tuple[SamplingPoint, ...]:
    """从 JSON 加载且严格校验 14 个 WGS84 采样点。"""

    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiscoveryError(f"采样点配置读取失败: {config_path.name}") from error
    if not isinstance(payload, list):
        raise DiscoveryError("采样点配置顶层应为数组")

    rows = cast(list[object], payload)
    if len(rows) != _EXPECTED_POINT_COUNT:
        raise DiscoveryError(f"采样点数量应为 {_EXPECTED_POINT_COUNT}")

    points: list[SamplingPoint] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DiscoveryError(f"采样点第 {index} 项应为对象")
        item = cast(dict[str, object], row)
        if set(item) != _POINT_KEYS:
            raise DiscoveryError(f"采样点第 {index} 项字段与契约不一致")
        point_id = _nonempty_string(item["point_id"], f"采样点第 {index} 项 point_id")
        name = _nonempty_string(item["name"], f"采样点第 {index} 项 name")
        longitude = _coordinate(item["longitude"], -180.0, 180.0, "longitude")
        latitude = _coordinate(item["latitude"], -90.0, 90.0, "latitude")
        if point_id in seen_ids:
            raise DiscoveryError(f"采样点 ID 重复: {point_id}")
        seen_ids.add(point_id)
        points.append(SamplingPoint(point_id, name, longitude, latitude))
    return tuple(points)


class DiscoveryService:
    """按采样点发现 LocationKey 及其当前空气质量来源。"""

    def __init__(self, client: AdvancedClient) -> None:
        self._client = client

    def discover(self, points: Sequence[SamplingPoint]) -> DiscoveryResult:
        locations = self.discover_locations(points)
        sources = tuple(self._discover_source(location) for location in locations)
        status: DiscoveryStatus = (
            "partial" if any(source.source_status == "unknown" for source in sources) else "ok"
        )
        return DiscoveryResult(status=status, locations=locations, air_quality_sources=sources)

    def discover_locations(self, points: Sequence[SamplingPoint]) -> tuple[LocationDiscovery, ...]:
        """逐点定位并按 LocationKey 聚合覆盖关系。"""

        grouped: dict[str, _MutableLocation] = {}
        for point in points:
            response = self._client.geoposition(point.latitude, point.longitude)
            parsed = _parse_location(response.payload)
            existing = grouped.get(parsed.location_key)
            if existing is None:
                parsed.probe_point_ids.append(point.point_id)
                grouped[parsed.location_key] = parsed
            else:
                existing.probe_point_ids.append(point.point_id)

        return tuple(
            LocationDiscovery(
                location_key=location.location_key,
                location_name=location.location_name,
                administrative_area=location.administrative_area,
                geo_position=location.geo_position,
                probe_point_ids=tuple(location.probe_point_ids),
            )
            for location in grouped.values()
        )

    def _discover_source(self, location: LocationDiscovery) -> AirQualitySourceDiscovery:
        response = self._client.current_air_quality(location.location_key)
        source, source_status = _parse_air_source(response.payload)
        return AirQualitySourceDiscovery(
            location_key=location.location_key,
            probe_point_ids=location.probe_point_ids,
            source=source,
            source_status=source_status,
        )


def _parse_location(payload: object) -> _MutableLocation:
    if not isinstance(payload, dict) or not payload:
        raise DiscoveryError("定位响应顶层应为非空对象")
    location = cast(dict[str, object], payload)
    location_key = _nonempty_string(location.get("Key"), "定位 Key")
    location_name = _nonempty_string(location.get("LocalizedName"), "定位 LocalizedName")
    administrative_area = _object_field(location, "AdministrativeArea", "定位")
    geo_position = _object_field(location, "GeoPosition", "定位")
    _coordinate(geo_position.get("Longitude"), -180.0, 180.0, "GeoPosition.Longitude")
    _coordinate(geo_position.get("Latitude"), -90.0, 90.0, "GeoPosition.Latitude")
    return _MutableLocation(
        location_key=location_key,
        location_name=location_name,
        administrative_area=administrative_area,
        geo_position=geo_position,
        probe_point_ids=[],
    )


def _parse_air_source(payload: object) -> tuple[str | None, SourceStatus]:
    if not isinstance(payload, dict):
        raise DiscoveryError("当前空气质量响应顶层应为对象")
    response = cast(dict[str, object], payload)
    source = response.get("Source")
    if not isinstance(source, str) or not source.strip():
        return None, "unknown"
    return source, "ok"


def _object_field(item: Mapping[str, object], key: str, context: str) -> dict[str, object]:
    value = item.get(key)
    if not isinstance(value, dict):
        raise DiscoveryError(f"{context} {key} 应为对象")
    return dict(cast(dict[str, object], value))


def _nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError(f"{field_name} 应为非空字符串")
    return value


def _coordinate(value: object, minimum: float, maximum: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiscoveryError(f"{field_name} 应为数值")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise DiscoveryError(f"{field_name} 超出 WGS84 合法范围")
    return number


def _plain_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            result[key] = _plain_mapping(cast(Mapping[str, object], value))
        elif isinstance(value, tuple):
            result[key] = list(cast(tuple[object, ...], value))
        else:
            result[key] = value
    return result


__all__ = [
    "AirQualitySourceDiscovery",
    "DiscoveryError",
    "DiscoveryResult",
    "DiscoveryService",
    "LocationDiscovery",
    "load_sampling_points",
]
