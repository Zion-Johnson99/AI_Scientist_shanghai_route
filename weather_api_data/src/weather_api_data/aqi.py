"""依据 HJ 633-2026 计算实时空气质量分指数与 AQI。"""

from __future__ import annotations

import math
from collections.abc import Mapping

_IAQI_BREAKPOINTS = (0, 50, 100, 150, 200, 300, 400, 500)
_CONCENTRATION_BREAKPOINTS: dict[str, tuple[float, ...]] = {
    "sulfur_dioxide_ug_m3": (0, 150, 500, 650, 800),
    "nitrogen_dioxide_ug_m3": (0, 100, 200, 700, 1200, 2340, 3090, 3840),
    "carbon_monoxide_mg_m3": (0, 5, 10, 35, 60, 90, 120, 150),
    "ozone_ug_m3": (0, 160, 200, 300, 400, 800, 1000, 1200),
    "pm10_ug_m3": (0, 50, 120, 250, 350, 420, 500, 600),
    "pm2_5_ug_m3": (0, 35, 60, 115, 150, 250, 350, 500),
}


def calculate_iaqi(pollutant: str, concentration: float) -> int:
    """计算单项污染物实时空气质量分指数。"""

    breakpoints = _CONCENTRATION_BREAKPOINTS.get(pollutant)
    if breakpoints is None:
        raise ValueError(f"未知污染物字段: {pollutant}")
    value = float(concentration)
    if not math.isfinite(value) or value < 0:
        raise ValueError("污染物浓度需为非负有限数值")

    if pollutant == "sulfur_dioxide_ug_m3" and value > breakpoints[-1]:
        return 200
    if value >= breakpoints[-1]:
        return _IAQI_BREAKPOINTS[len(breakpoints) - 1]

    for index in range(1, len(breakpoints)):
        high_concentration = breakpoints[index]
        if value > high_concentration:
            continue
        low_concentration = breakpoints[index - 1]
        low_iaqi = _IAQI_BREAKPOINTS[index - 1]
        high_iaqi = _IAQI_BREAKPOINTS[index]
        interpolated = (high_iaqi - low_iaqi) / (high_concentration - low_concentration) * (
            value - low_concentration
        ) + low_iaqi
        return math.ceil(interpolated)
    raise AssertionError("空气质量分指数区间匹配失败")


def calculate_aqi(values: Mapping[str, object]) -> dict[str, object]:
    """按六项污染物中的最大 IAQI 生成 AQI 与首要污染物。"""

    iaqi: dict[str, int] = {}
    for pollutant in _CONCENTRATION_BREAKPOINTS:
        raw_value = values.get(pollutant)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            continue
        iaqi[pollutant] = calculate_iaqi(pollutant, float(raw_value))

    if not iaqi:
        return {
            "aqi": None,
            "primary_pollutants": [],
            "iaqi": {},
            "standard": "HJ 633-2026",
        }

    aqi = max(iaqi.values())
    primary = sorted(pollutant for pollutant, item in iaqi.items() if item == aqi)
    if aqi <= 50:
        primary = []
    return {
        "aqi": aqi,
        "primary_pollutants": primary,
        "iaqi": iaqi,
        "standard": "HJ 633-2026",
    }


__all__ = ["calculate_aqi", "calculate_iaqi"]
