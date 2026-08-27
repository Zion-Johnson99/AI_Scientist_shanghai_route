import pytest

from weather_api_data.coordinates import (
    CoordinateError,
    gcj02_to_wgs84,
    utm51_to_wgs84,
    wgs84_to_utm51,
)


def test_gcj02_to_wgs84_applies_expected_shanghai_offset() -> None:
    longitude, latitude = gcj02_to_wgs84(121.4737, 31.2304)

    assert longitude == pytest.approx(121.469176, abs=0.00002)
    assert latitude == pytest.approx(31.232342, abs=0.00002)


def test_utm51_round_trip_is_stable_within_centimetres() -> None:
    easting, northing = wgs84_to_utm51(121.469176, 31.232342)
    longitude, latitude = utm51_to_wgs84(easting, northing)

    assert longitude == pytest.approx(121.469176, abs=1e-7)
    assert latitude == pytest.approx(31.232342, abs=1e-7)


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(181.0, 31.2), (121.4, 91.0), (float("nan"), 31.2)],
)
def test_coordinate_functions_reject_invalid_values(longitude: float, latitude: float) -> None:
    with pytest.raises(CoordinateError):
        gcj02_to_wgs84(longitude, latitude)
