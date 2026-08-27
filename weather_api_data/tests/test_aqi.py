from __future__ import annotations

import pytest

from weather_api_data.aqi import calculate_aqi, calculate_iaqi

IAQI_BREAKPOINTS = (0, 50, 100, 150, 200, 300, 400, 500)
CONCENTRATION_BREAKPOINTS = {
    "sulfur_dioxide_ug_m3": (0, 150, 500, 650, 800),
    "nitrogen_dioxide_ug_m3": (0, 100, 200, 700, 1200, 2340, 3090, 3840),
    "carbon_monoxide_mg_m3": (0, 5, 10, 35, 60, 90, 120, 150),
    "ozone_ug_m3": (0, 160, 200, 300, 400, 800, 1000, 1200),
    "pm10_ug_m3": (0, 50, 120, 250, 350, 420, 500, 600),
    "pm2_5_ug_m3": (0, 35, 60, 115, 150, 250, 350, 500),
}
BREAKPOINT_CASES = [
    (pollutant, concentration, IAQI_BREAKPOINTS[index])
    for pollutant, concentrations in CONCENTRATION_BREAKPOINTS.items()
    for index, concentration in enumerate(concentrations)
]


@pytest.mark.parametrize(
    ("pollutant", "concentration", "expected"),
    BREAKPOINT_CASES,
)
def test_calculate_iaqi_uses_hj_633_2026_realtime_breakpoints(
    pollutant: str, concentration: float, expected: int
) -> None:
    assert calculate_iaqi(pollutant, concentration) == expected


def test_calculate_iaqi_interpolates_and_rounds_up() -> None:
    assert calculate_iaqi("pm2_5_ug_m3", 47.6) == 76


def test_sulfur_dioxide_realtime_iaqi_is_capped_at_200() -> None:
    assert calculate_iaqi("sulfur_dioxide_ug_m3", 900.0) == 200


def test_calculate_aqi_uses_maximum_iaqi_and_lists_ties() -> None:
    result = calculate_aqi(
        {
            "pm2_5_ug_m3": 60,
            "pm10_ug_m3": 120,
            "ozone_ug_m3": 160,
            "nitrogen_dioxide_ug_m3": 50,
            "sulfur_dioxide_ug_m3": 20,
            "carbon_monoxide_mg_m3": 1,
        }
    )

    assert result["aqi"] == 100
    assert result["primary_pollutants"] == ["pm10_ug_m3", "pm2_5_ug_m3"]
    assert result["standard"] == "HJ 633-2026"


def test_calculate_aqi_skips_missing_and_rejects_negative_values() -> None:
    result = calculate_aqi({"pm2_5_ug_m3": None, "ozone_ug_m3": 80})
    assert result["aqi"] == 25
    assert result["primary_pollutants"] == []

    with pytest.raises(ValueError, match="浓度"):
        calculate_iaqi("pm2_5_ug_m3", -1)


def test_calculate_iaqi_rejects_unknown_pollutant() -> None:
    with pytest.raises(ValueError, match="污染物"):
        calculate_iaqi("unknown", 1)
