from __future__ import annotations

import pytest

from weather_api_data.models import SamplingPoint
from weather_api_data.qweather_discovery import (
    QWEATHER_AIR_QUALITY_SOURCE,
    QWeatherDiscoveryService,
    qweather_source_id,
)


def point(point_id: str, longitude: float, latitude: float) -> SamplingPoint:
    return SamplingPoint(
        point_id=point_id,
        name=point_id,
        longitude=longitude,
        latitude=latitude,
    )


def test_source_id_uses_latitude_longitude_order_and_half_up_rounding() -> None:
    assert qweather_source_id(31.155, 121.455) == "qweather:31.16,121.46"


def test_discover_locations_groups_points_by_two_decimal_coordinates() -> None:
    service = QWeatherDiscoveryService()

    locations = service.discover_locations(
        (
            point("P1", 121.456, 31.164),
            point("P2", 121.459, 31.161),
            point("P3", 121.431, 31.151),
        )
    )

    assert [location.location_key for location in locations] == [
        "qweather:31.16,121.46",
        "qweather:31.15,121.43",
    ]
    assert locations[0].probe_point_ids == ("P1", "P2")
    assert locations[0].geo_position == {"Latitude": 31.16, "Longitude": 121.46}


def test_discover_returns_existing_contract_with_explicit_qweather_source() -> None:
    result = QWeatherDiscoveryService().discover((point("P1", 121.456, 31.164),))

    assert result.status == "ok"
    assert result.locations[0].administrative_area == {
        "provider": "qweather",
        "spatial_product": "coordinate_1x1_km",
    }
    assert result.air_quality_sources[0].to_dict() == {
        "location_key": "qweather:31.16,121.46",
        "probe_point_ids": ["P1"],
        "source": QWEATHER_AIR_QUALITY_SOURCE,
        "source_status": "ok",
    }


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (float("nan"), 121.45),
        (91.0, 121.45),
        (31.16, 181.0),
    ],
)
def test_source_id_rejects_invalid_wgs84_coordinates(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError, match="WGS84"):
        qweather_source_id(latitude, longitude)


def test_discover_rejects_duplicate_point_ids() -> None:
    points = (
        point("P1", 121.45, 31.16),
        point("P1", 121.46, 31.17),
    )

    with pytest.raises(ValueError, match="point_id 重复"):
        QWeatherDiscoveryService().discover_locations(points)
