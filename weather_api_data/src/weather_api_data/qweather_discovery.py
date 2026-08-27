"""基于 WGS84 坐标的和风天气零网络来源发现。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from weather_api_data.discovery import (
    AirQualitySourceDiscovery,
    DiscoveryResult,
    LocationDiscovery,
)
from weather_api_data.models import SamplingPoint
from weather_api_data.qweather_client import (
    coordinates_from_source_id,
    qweather_source_id,
)

QWEATHER_AIR_QUALITY_SOURCE = "QWeather 1x1 km coordinate product"


@dataclass(slots=True)
class _SourceGroup:
    source_id: str
    latitude: float
    longitude: float
    probe_point_ids: list[str]


class QWeatherDiscoveryService:
    """按和风支持的两位小数坐标聚合采样点并保持零网络请求。"""

    def discover(self, points: Sequence[SamplingPoint]) -> DiscoveryResult:
        locations = self.discover_locations(points)
        sources = tuple(
            AirQualitySourceDiscovery(
                location_key=location.location_key,
                probe_point_ids=location.probe_point_ids,
                source=QWEATHER_AIR_QUALITY_SOURCE,
                source_status="ok",
            )
            for location in locations
        )
        return DiscoveryResult(status="ok", locations=locations, air_quality_sources=sources)

    def discover_locations(self, points: Sequence[SamplingPoint]) -> tuple[LocationDiscovery, ...]:
        """将采样点按量化后的纬度、经度聚合为稳定来源。"""

        grouped: dict[str, _SourceGroup] = {}
        seen_point_ids: set[str] = set()
        for point in points:
            if not point.point_id.strip():
                raise ValueError("采样点 point_id 为空")
            if point.point_id in seen_point_ids:
                raise ValueError(f"采样点 point_id 重复: {point.point_id}")
            seen_point_ids.add(point.point_id)

            source_id = qweather_source_id(point.latitude, point.longitude)
            latitude_text, longitude_text = coordinates_from_source_id(source_id)
            latitude = float(latitude_text)
            longitude = float(longitude_text)
            existing = grouped.get(source_id)
            if existing is None:
                grouped[source_id] = _SourceGroup(
                    source_id=source_id,
                    latitude=latitude,
                    longitude=longitude,
                    probe_point_ids=[point.point_id],
                )
            else:
                existing.probe_point_ids.append(point.point_id)

        return tuple(
            LocationDiscovery(
                location_key=group.source_id,
                location_name=group.source_id,
                administrative_area={
                    "provider": "qweather",
                    "spatial_product": "coordinate_1x1_km",
                },
                geo_position={
                    "Latitude": group.latitude,
                    "Longitude": group.longitude,
                },
                probe_point_ids=tuple(group.probe_point_ids),
            )
            for group in grouped.values()
        )


__all__ = [
    "QWEATHER_AIR_QUALITY_SOURCE",
    "QWeatherDiscoveryService",
    "qweather_source_id",
]
