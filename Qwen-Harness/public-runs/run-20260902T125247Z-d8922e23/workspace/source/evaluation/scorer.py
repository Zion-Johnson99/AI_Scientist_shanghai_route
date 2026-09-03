"""Deterministic five-dimension route scoring; every value is computed offline from run artifacts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .weights import DIMENSION_LABELS_ZH, DIMENSIONS

PROVENANCE = "deterministic_computation"
EARTH_RADIUS_M = 6_371_008.8

#: Access leg model shared with the route builder: straight-line distance times
#: a fixed detour factor, walked at 4.8 km/h. Declared as a deterministic
#: estimate, never presented as an online routing-API result.
ACCESS_DETOUR_FACTOR = 1.35
ACCESS_SPEED_KMH = 4.8
ACCESS_PROVENANCE = "deterministic_estimate: straight_line_x1.35_at_4.8kmh"
ACCESS_MIN_BEST = 0.0
ACCESS_MIN_WORST = 45.0

RELIABILITY_MULTIPLIERS: dict[str, float] = {
    "measured": 1.0,
    "derived": 0.9,
    "estimated": 0.75,
}

RISK_SEVERITY: dict[str, int] = {"normal": 0, "caution": 1, "pause": 2, "stop": 3}
RISK_BY_SEVERITY: tuple[str, ...] = ("normal", "caution", "pause", "stop")
RISK_LABELS_ZH: dict[str, str] = {
    "normal": "正常",
    "caution": "需注意",
    "pause": "建议暂停",
    "stop": "建议停止",
    "unknown": "未知",
}

#: Fixed normalisation ranges for environment indicators, chosen from the
#: dashboard risk thresholds (pm25 stop=150, aqi stop=200 stretched to 300 for
#: headroom, noise 40-85 dB covering quiet park to arterial road, green/water
#: ratios capped at plausible cell maxima). best maps to 100, worst maps to 0.
ENV_INDICATORS: tuple[dict[str, Any], ...] = (
    {"key": "pm25_ug_m3", "best": 0.0, "worst": 150.0, "weight": 0.30, "unit": "ug/m3", "label_zh": "PM2.5"},
    {"key": "aqi_us", "best": 0.0, "worst": 300.0, "weight": 0.20, "unit": "aqi", "label_zh": "AQI"},
    {"key": "noise_proxy_db", "best": 40.0, "worst": 85.0, "weight": 0.20, "unit": "dB", "label_zh": "噪声代理"},
    {"key": "traffic_exposure_0_1", "best": 0.0, "worst": 1.0, "weight": 0.15, "unit": "0-1", "label_zh": "交通暴露"},
    {"key": "green_ratio_0_1", "best": 0.60, "worst": 0.0, "weight": 0.10, "unit": "0-1", "label_zh": "绿地率"},
    {"key": "water_ratio_0_1", "best": 0.30, "worst": 0.0, "weight": 0.05, "unit": "0-1", "label_zh": "水体率"},
)

QUALITY_BASE_INDICATORS: tuple[dict[str, Any], ...] = (
    {"key": "in_district_ratio", "best": 1.0, "worst": 0.80, "weight": 0.18, "unit": "0-1", "label_zh": "区内占比"},
    {"key": "road_snapping_ratio", "best": 1.0, "worst": 0.50, "weight": 0.14, "unit": "0-1", "label_zh": "路网贴合率"},
    {"key": "abs_distance_error", "best": 0.0, "worst": 0.15, "weight": 0.16, "unit": "ratio", "label_zh": "距离偏差"},
    {"key": "repeated_edge_count", "best": 0.0, "worst": 10.0, "weight": 0.12, "unit": "count", "label_zh": "重复边数"},
    {"key": "proper_self_intersection_count", "best": 0.0, "worst": 10.0, "weight": 0.12, "unit": "count", "label_zh": "自交叉数"},
    {"key": "local_uturn_count", "best": 0.0, "worst": 10.0, "weight": 0.10, "unit": "count", "label_zh": "掉头数"},
    {"key": "local_return_loop_count", "best": 0.0, "worst": 5.0, "weight": 0.08, "unit": "count", "label_zh": "折返环数"},
)

#: Kind-conditional quality indicator: loops are judged by how well the
#: endpoints close, one-way routes by circuity against the straight line.
QUALITY_KIND_INDICATORS: dict[str, dict[str, Any]] = {
    "strict_loop": {"key": "endpoint_offset_m", "best": 0.0, "worst": 300.0, "weight": 0.10, "unit": "m", "label_zh": "起终点偏移"},
    "one_way": {"key": "circuity", "best": 1.0, "worst": 2.0, "weight": 0.10, "unit": "ratio", "label_zh": "迂回度"},
}

SPORT_MATCH_KIND_WEIGHT = 0.4
SPORT_MATCH_DISTANCE_WEIGHT = 0.6
LOOP_PREFERRED_SPORTS: frozenset[str] = frozenset({"walk", "run"})

SCENIC_AREAS: frozenset[str] = frozenset({"shanghai_botanical_garden", "hengfu", "west_bund"})
URBAN_AREAS: frozenset[str] = frozenset({"xujiahui", "caohejing", "longhua"})

TAG_RULES: dict[str, str] = {
    "riverside": "water",
    "waterfront": "water",
    "river": "water",
    "滨江": "water",
    "西岸": "water",
    "水岸": "water",
    "park": "park",
    "parks": "park",
    "公园": "park",
    "绿地": "park",
    "quiet": "quiet",
    "silence": "quiet",
    "安静": "quiet",
    "低噪": "quiet",
    "scenic": "scenic",
    "landscape": "scenic",
    "风景": "scenic",
    "景观": "scenic",
    "shade": "shade",
    "shady": "shade",
    "林荫": "shade",
    "遮荫": "shade",
    "urban": "urban",
    "city": "urban",
    "城市": "urban",
    "市区": "urban",
    "商圈": "urban",
}


def haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    """Great-circle distance in metres between two [lon, lat] points."""
    lon1, lat1 = float(a[0]), float(a[1])
    lon2, lat2 = float(b[0]), float(b[1])
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    h = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def clamp(value: float, low: float, high: float) -> float:
    """Clip a value into [low, high]."""
    return max(low, min(high, value))


def normalize_linear(value: float, best: float, worst: float) -> float:
    """Linear 0..100 score where best maps to 100 and worst maps to 0."""
    if worst == best:
        return 100.0
    return clamp((worst - value) / (worst - best), 0.0, 1.0) * 100.0


def as_float(value: Any) -> float | None:
    """Coerce JSON scalars to float, rejecting bools and nulls."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number
    return None


def exposure_item(exposure: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Fetch one dashboard exposure entry as a dict, tolerating absence."""
    item = exposure.get(key)
    return item if isinstance(item, dict) else {}


def exposure_value(exposure: Mapping[str, Any], key: str) -> float | None:
    """Numeric value of one exposure field, or None when missing/unavailable."""
    return as_float(exposure_item(exposure, key).get("value"))


def access_minutes(straight_line_m: float) -> float:
    """Estimated door-to-route access minutes using the fixed detour model."""
    return (straight_line_m * ACCESS_DETOUR_FACTOR / 1000.0) / ACCESS_SPEED_KMH * 60.0


def _weighted_mean_dimension(
    specs: Sequence[Mapping[str, Any]],
    raw_values: Mapping[str, float | None],
    units: Mapping[str, str],
    provenances: Mapping[str, str],
    empty_reason_zh: str,
    reason_head_zh: str,
) -> dict[str, Any]:
    """Weighted mean of normalised sub-scores; missing indicators are excluded and renormalised."""
    contributors: list[dict[str, Any]] = []
    missing: list[str] = []
    present_weight = 0.0
    for spec in specs:
        key = str(spec["key"])
        value = raw_values.get(key)
        if value is None:
            missing.append(key)
            continue
        normalised = normalize_linear(value, float(spec["best"]), float(spec["worst"]))
        contributors.append(
            {
                "indicator": key,
                "raw_value": round(value, 4),
                "unit": units.get(key, str(spec.get("unit", ""))),
                "normalised": round(normalised, 3),
                "weight": float(spec["weight"]),
                "provenance": provenances.get(key, str(spec.get("provenance", PROVENANCE))),
            }
        )
        present_weight += float(spec["weight"])
    if not contributors:
        return {
            "score": None,
            "status": "unavailable",
            "contributors": [],
            "missing_indicators": missing,
            "reason_zh": empty_reason_zh,
        }
    score = sum(item["normalised"] * item["weight"] for item in contributors) / present_weight
    status = "ok" if not missing else "partial"
    parts = [
        f"{_label_of(specs, item['indicator'])} {item['raw_value']:g} {item['unit']}（归一化 {item['normalised']:.1f}）"
        for item in contributors[:3]
    ]
    reason = f"{reason_head_zh} {score:.1f} 分：" + "、".join(parts)
    if missing:
        reason += f"；缺失 {len(missing)} 项（{'、'.join(missing)}）已剔除并按剩余权重重归一"
    reason += "。"
    return {
        "score": round(score, 3),
        "status": status,
        "contributors": contributors,
        "missing_indicators": missing,
        "reason_zh": reason,
    }


def _label_of(specs: Sequence[Mapping[str, Any]], key: str) -> str:
    for spec in specs:
        if spec.get("key") == key:
            return str(spec.get("label_zh", key))
    return key


def score_environment(exposure: Mapping[str, Any]) -> dict[str, Any]:
    """Dimension 1: environment health from dashboard route exposure."""
    raw_values: dict[str, float | None] = {}
    units: dict[str, str] = {}
    provenances: dict[str, str] = {}
    for spec in ENV_INDICATORS:
        key = str(spec["key"])
        item = exposure_item(exposure, key)
        raw_values[key] = as_float(item.get("value"))
        units[key] = str(item.get("unit") or spec["unit"])
        provenances[key] = str(item.get("provenance") or "environment_dashboard")
    return _weighted_mean_dimension(
        ENV_INDICATORS,
        raw_values,
        units,
        provenances,
        empty_reason_zh="环境暴露指标全部缺失，该维度记为空并从总分权重中剔除，不用任何虚构中值代替。",
        reason_head_zh="环境健康",
    )


def score_route_quality(route: Mapping[str, Any]) -> dict[str, Any]:
    """Dimension 4: route quality from the catalog's own gate metrics."""
    kind = str(route.get("kind", ""))
    specs: list[dict[str, Any]] = [dict(spec) for spec in QUALITY_BASE_INDICATORS]
    extra = QUALITY_KIND_INDICATORS.get(kind)
    if extra is not None:
        specs.append(dict(extra))
    raw_values: dict[str, float | None] = {}
    for spec in specs:
        key = str(spec["key"])
        if key == "abs_distance_error":
            error = as_float(route.get("distance_error"))
            raw_values[key] = abs(error) if error is not None else None
        else:
            raw_values[key] = as_float(route.get(key))
    units = {str(spec["key"]): str(spec["unit"]) for spec in specs}
    provenances = {str(spec["key"]): "route_catalog_gate_metrics" for spec in specs}
    return _weighted_mean_dimension(
        specs,
        raw_values,
        units,
        provenances,
        empty_reason_zh="路线质量指标全部缺失，该维度记为空并从总分权重中剔除。",
        reason_head_zh="路线质量",
    )


def score_sport_match(
    route: Mapping[str, Any],
    sport: str,
    band_range_km: tuple[float, float] | None,
    prefer_loop: bool | None,
) -> dict[str, Any]:
    """Dimension 2: kind fit plus distance fit inside the requested band."""
    mode = str(route.get("mode", ""))
    if mode != sport:
        return {
            "score": 0.0,
            "status": "ok",
            "contributors": [],
            "missing_indicators": [],
            "reason_zh": f"运动方式不匹配：请求 {sport}，路线为 {mode}，该路线不应进入候选。",
        }
    kind = str(route.get("kind", ""))
    loop_wanted = prefer_loop if prefer_loop is not None else sport in LOOP_PREFERRED_SPORTS
    if kind == "strict_loop":
        kind_score = 100.0 if loop_wanted else 60.0
    else:
        kind_score = 40.0 if loop_wanted else 100.0
    kind_reason = "闭环路线符合环线偏好" if (kind == "strict_loop" and loop_wanted) else (
        "单程路线符合单程偏好" if (kind != "strict_loop" and not loop_wanted) else (
            "闭环路线但请求更偏向单程" if kind == "strict_loop" else "单程路线但请求更偏好环线"
        )
    )
    distance_m = as_float(route.get("actual_distance_m"))
    contributors: list[dict[str, Any]] = [
        {
            "indicator": "kind",
            "raw_value": kind,
            "unit": "strict_loop|one_way",
            "normalised": round(kind_score, 3),
            "weight": SPORT_MATCH_KIND_WEIGHT,
            "provenance": "route_catalog:kind",
        }
    ]
    missing: list[str] = []
    band_text = ""
    if band_range_km is None or distance_m is None:
        missing.append("band_range_km" if band_range_km is None else "actual_distance_m")
        distance_score: float | None = None
    else:
        low_m, high_m = band_range_km[0] * 1000.0, band_range_km[1] * 1000.0
        band_text = f"{band_range_km[0]:g}–{band_range_km[1]:g} km"
        if low_m <= distance_m <= high_m:
            distance_score = 100.0
        else:
            width = max(high_m - low_m, 1.0)
            overshoot = (low_m - distance_m) if distance_m < low_m else (distance_m - high_m)
            distance_score = max(0.0, 100.0 * (1.0 - overshoot / width))
        contributors.append(
            {
                "indicator": "actual_distance_m",
                "raw_value": round(distance_m, 1),
                "unit": "m",
                "normalised": round(distance_score, 3),
                "weight": SPORT_MATCH_DISTANCE_WEIGHT,
                "provenance": "route_catalog:actual_distance_m",
            }
        )
    if distance_score is None:
        score = kind_score
        reason = f"运动匹配 {score:.1f} 分：{kind_reason}；未提供距离带或距离缺失，距离子项剔除后按剩余权重重归一。"
        status = "partial"
    else:
        total_weight = SPORT_MATCH_KIND_WEIGHT + SPORT_MATCH_DISTANCE_WEIGHT
        score = (
            kind_score * SPORT_MATCH_KIND_WEIGHT + distance_score * SPORT_MATCH_DISTANCE_WEIGHT
        ) / total_weight
        reason = (
            f"运动匹配 {score:.1f} 分：{kind_reason}（{kind_score:.0f}），"
            f"实测 {distance_m:.0f} m 对请求距离带 {band_text}"
            f"（距离子项 {distance_score:.0f}）。"
        )
        status = "ok"
    return {
        "score": round(score, 3),
        "status": status,
        "contributors": contributors,
        "missing_indicators": missing,
        "reason_zh": reason,
    }


def score_access(
    origin_coord: Sequence[float] | None,
    route: Mapping[str, Any],
    origin_name: str | None,
) -> tuple[dict[str, Any], float | None, float | None]:
    """Dimension 3: access convenience from origin to route start; also returns (minutes, metres)."""
    start = route.get("start")
    if origin_coord is None or not isinstance(start, (list, tuple)) or len(start) < 2:
        reason = (
            "未提供起点坐标，接驳便利维度记为空并从总分权重中剔除。"
            if origin_coord is None
            else "路线缺少起点坐标，接驳便利维度记为空。"
        )
        return (
            {
                "score": None,
                "status": "unavailable",
                "contributors": [],
                "missing_indicators": ["origin" if origin_coord is None else "start"],
                "reason_zh": reason,
            },
            None,
            None,
        )
    straight_m = haversine_m(origin_coord, [float(start[0]), float(start[1])])
    minutes = access_minutes(straight_m)
    normalised = normalize_linear(minutes, ACCESS_MIN_BEST, ACCESS_MIN_WORST)
    where = f"起点“{origin_name}”" if origin_name else "请求起点"
    reason = (
        f"接驳便利 {normalised:.1f} 分：{where}到路线起点直线 {straight_m:.0f} m，"
        f"按绕行系数 {ACCESS_DETOUR_FACTOR} 与 {ACCESS_SPEED_KMH} km/h 估算约 {minutes:.1f} 分钟"
        f"（0 分钟=100 分，45 分钟=0 分线性归一）。"
    )
    dimension = {
        "score": round(normalised, 3),
        "status": "ok",
        "contributors": [
            {
                "indicator": "estimated_access_min",
                "raw_value": round(minutes, 3),
                "unit": "min",
                "normalised": round(normalised, 3),
                "weight": 1.0,
                "provenance": ACCESS_PROVENANCE,
            }
        ],
        "missing_indicators": [],
        "reason_zh": reason,
    }
    return dimension, round(minutes, 3), round(straight_m, 1)


def _pref_rule_water(route: Mapping[str, Any], exposure: Mapping[str, Any]) -> tuple[float | None, str]:
    area = str(route.get("area", ""))
    name = str(route.get("area_name_zh", ""))
    if area == "west_bund" or "滨江" in name or "西岸" in name:
        return 1.0, f"路线位于{name}，属滨江岸线场景"
    water = exposure_value(exposure, "water_ratio_0_1")
    if water is None:
        return None, "缺少水体覆盖率数据"
    if water >= 0.05:
        return 1.0, f"沿线水体覆盖率 {water:.3f}，明显临水"
    if water >= 0.02:
        return 0.5, f"沿线水体覆盖率 {water:.3f}，仅部分临水"
    return 0.0, f"沿线水体覆盖率 {water:.3f}，基本不临水"


def _pref_rule_park(route: Mapping[str, Any], exposure: Mapping[str, Any]) -> tuple[float | None, str]:
    relation = route.get("park_relation")
    if isinstance(relation, dict) and relation:
        label = str(relation.get("name_zh", "公园"))
        if relation.get("relation") == "along_route":
            return 1.0, f"路线经过{label}（{relation.get('label', '公园入口')}）"
        return 0.8, f"路线邻近{label}（{relation.get('label', '邻近公园')}）"
    name = str(route.get("area_name_zh", ""))
    if "植物园" in name or "公园" in name or "康健园" in name:
        return 0.9, f"路线位于{name}，绿地场景明确"
    green = exposure_value(exposure, "green_ratio_0_1")
    if green is None:
        return None, "缺少绿地覆盖率数据且无公园关联记录"
    if green >= 0.25:
        return 0.6, f"沿线绿地覆盖率 {green:.3f}，公园感较强"
    return 0.2, f"沿线绿地覆盖率 {green:.3f}，公园特征弱"


def _pref_rule_quiet(route: Mapping[str, Any], exposure: Mapping[str, Any]) -> tuple[float | None, str]:
    noise = exposure_value(exposure, "noise_proxy_db")
    if noise is not None:
        if noise <= 55.0:
            return 1.0, f"噪声代理 {noise:.1f} dB，环境安静"
        if noise <= 62.0:
            return 0.7, f"噪声代理 {noise:.1f} dB，较安静"
        if noise <= 70.0:
            return 0.4, f"噪声代理 {noise:.1f} dB，一般"
        return 0.0, f"噪声代理 {noise:.1f} dB，偏吵"
    traffic = exposure_value(exposure, "traffic_exposure_0_1")
    if traffic is None:
        return None, "噪声与交通暴露数据均缺失"
    if traffic <= 0.15:
        return 0.8, f"交通暴露 {traffic:.2f}，推断较安静"
    if traffic <= 0.30:
        return 0.5, f"交通暴露 {traffic:.2f}，推断一般"
    return 0.1, f"交通暴露 {traffic:.2f}，推断偏吵"


def _pref_rule_scenic(route: Mapping[str, Any], exposure: Mapping[str, Any]) -> tuple[float | None, str]:
    signals: list[str] = []
    satisfaction = 0.0
    green = exposure_value(exposure, "green_ratio_0_1")
    water = exposure_value(exposure, "water_ratio_0_1")
    if green is not None and green >= 0.15:
        satisfaction += 0.4
        signals.append(f"绿地率 {green:.2f}")
    if water is not None and water >= 0.02:
        satisfaction += 0.3
        signals.append(f"水体率 {water:.2f}")
    relation = route.get("park_relation")
    if isinstance(relation, dict) and relation:
        satisfaction += 0.3
        signals.append(str(relation.get("label", "公园关联")))
    if str(route.get("area", "")) in SCENIC_AREAS:
        satisfaction += 0.3
        signals.append(str(route.get("area_name_zh", "")))
    if not signals:
        if green is None and water is None:
            return None, "景观相关数据缺失"
        return 0.0, "无绿地、水体、公园或风貌区景观信号"
    return min(1.0, satisfaction), "景观信号：" + "、".join(signals)


def _pref_rule_shade(route: Mapping[str, Any], exposure: Mapping[str, Any]) -> tuple[float | None, str]:
    green = exposure_value(exposure, "green_ratio_0_1")
    if green is None:
        return None, "缺少绿地覆盖率数据，无法估计林荫"
    if green >= 0.30:
        return 1.0, f"绿地覆盖率 {green:.3f}，林荫充足（代理）"
    if green >= 0.15:
        return 0.6, f"绿地覆盖率 {green:.3f}，有一定林荫（代理）"
    if green >= 0.05:
        return 0.3, f"绿地覆盖率 {green:.3f}，林荫有限（代理）"
    return 0.0, f"绿地覆盖率 {green:.3f}，基本无林荫（代理）"


def _pref_rule_urban(route: Mapping[str, Any], exposure: Mapping[str, Any]) -> tuple[float | None, str]:
    area = str(route.get("area", ""))
    name = str(route.get("area_name_zh", ""))
    if area in URBAN_AREAS:
        return 1.0, f"路线位于{name}，城市建成区场景"
    density = exposure_value(exposure, "road_density_km_per_km2")
    services = route.get("nearby_services")
    service_count = len(services) if isinstance(services, list) else 0
    if density is not None:
        if density >= 25.0:
            return 0.8, f"路网密度 {density:.1f} km/km²，城市特征强"
        if density >= 15.0:
            return 0.5, f"路网密度 {density:.1f} km/km²，城市特征中等"
    if service_count >= 2:
        return 0.6, f"起点 150 m 内有 {service_count} 处补给服务，城市便利性好"
    if density is None and service_count == 0:
        return 0.2, "城市信号弱：路网密度缺失且无就近服务"
    return 0.2, "城市信号弱"


PREF_RULES: dict[str, Any] = {
    "water": _pref_rule_water,
    "park": _pref_rule_park,
    "quiet": _pref_rule_quiet,
    "scenic": _pref_rule_scenic,
    "shade": _pref_rule_shade,
    "urban": _pref_rule_urban,
}


def score_user_preference(
    route: Mapping[str, Any],
    preferences: Sequence[str],
    exposure: Mapping[str, Any],
) -> dict[str, Any]:
    """Dimension 5: satisfaction of the request's stated preference tags."""
    tags = [str(tag).strip() for tag in preferences if str(tag).strip()]
    if not tags:
        return {
            "score": None,
            "status": "unavailable",
            "contributors": [],
            "missing_indicators": [],
            "reason_zh": "请求未给出偏好标签，该维度记为空并从总分权重中剔除，不做臆测。",
        }
    contributors: list[dict[str, Any]] = []
    unrecognised: list[str] = []
    no_data: list[str] = []
    evidences: list[str] = []
    for tag in tags:
        rule_name = TAG_RULES.get(tag.lower(), TAG_RULES.get(tag))
        if rule_name is None:
            unrecognised.append(tag)
            continue
        satisfaction, evidence = PREF_RULES[rule_name](route, exposure)
        if satisfaction is None:
            no_data.append(tag)
            continue
        contributors.append(
            {
                "indicator": f"pref:{tag}",
                "raw_value": round(satisfaction, 3),
                "unit": "satisfaction_0_1",
                "normalised": round(satisfaction * 100.0, 3),
                "weight": 1.0,
                "provenance": f"preference_rule:{rule_name}",
            }
        )
        evidences.append(f"{tag}：{evidence}")
    if not contributors:
        detail = "、".join(no_data) if no_data else "、".join(unrecognised)
        return {
            "score": None,
            "status": "unavailable",
            "contributors": [],
            "missing_indicators": no_data,
            "reason_zh": f"偏好标签（{detail}）缺少可核对的数据，该维度记为空并从总分权重中剔除。",
        }
    score = 100.0 * sum(item["raw_value"] for item in contributors) / len(contributors)
    for item in contributors:
        item["weight"] = round(1.0 / len(contributors), 6)
    if no_data or unrecognised:
        status = "partial"
    else:
        status = "ok"
    reason = f"用户偏好 {score:.1f} 分（{len(contributors)}/{len(tags)} 个标签可核对）：" + "；".join(evidences[:3])
    if no_data:
        reason += f"；{'、'.join(no_data)} 缺数据已剔除"
    if unrecognised:
        reason += f"；{'、'.join(unrecognised)} 为未识别标签"
    reason += "。"
    return {
        "score": round(score, 3),
        "status": status,
        "contributors": contributors,
        "missing_indicators": no_data,
        "unrecognised_tags": unrecognised,
        "reason_zh": reason,
    }


def field_severity(value: float | None, thresholds: Mapping[str, Any]) -> str:
    """Worst risk level for one numeric field against its thresholds."""
    if value is None or not isinstance(thresholds, Mapping):
        return "unknown"
    stop = as_float(thresholds.get("stop"))
    pause = as_float(thresholds.get("pause"))
    caution = as_float(thresholds.get("caution"))
    if stop is not None and value >= stop:
        return "stop"
    if pause is not None and value >= pause:
        return "pause"
    if caution is not None and value >= caution:
        return "caution"
    return "normal"


def worst_severity(levels: Sequence[str]) -> str:
    """Highest severity among risk levels; 'unknown' when nothing is known."""
    known = [level for level in levels if level in RISK_SEVERITY]
    if not known:
        return "unknown"
    return RISK_BY_SEVERITY[max(RISK_SEVERITY[level] for level in known)]


def route_risk(
    dash_route: Mapping[str, Any] | None,
    exposure: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Per-route risk: trust the dashboard's risk block, else recompute from exposures."""
    field_risk: dict[str, str] = {}
    if dash_route is not None:
        risk_block = dash_route.get("risk")
        if isinstance(risk_block, dict):
            field_risk = {str(key): str(level) for key, level in risk_block.items()}
    if not field_risk and isinstance(thresholds, Mapping):
        for key, spec in thresholds.items():
            if not isinstance(spec, dict):
                continue
            field_risk[str(key)] = field_severity(exposure_value(exposure, str(key)), spec)
    overall = "unknown"
    if dash_route is not None and isinstance(dash_route.get("overall_risk"), str):
        overall = str(dash_route["overall_risk"])
    elif field_risk:
        overall = worst_severity(list(field_risk.values()))
    pause_fields = sorted(key for key, level in field_risk.items() if level in ("pause", "stop"))
    stop_fields = sorted(key for key, level in field_risk.items() if level == "stop")
    return {
        "overall_risk": overall,
        "risk_pause": overall in ("pause", "stop") or bool(stop_fields) or bool(pause_fields),
        "field_risk": field_risk,
        "pause_fields": pause_fields,
        "stop_fields": stop_fields,
    }


def data_reliability(exposure: Mapping[str, Any]) -> tuple[float, int]:
    """Product of per-field reliability multipliers over dashboard fields with a usable status."""
    product = 1.0
    used = 0
    for item in exposure.values():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", ""))
        multiplier = RELIABILITY_MULTIPLIERS.get(status)
        if multiplier is None:
            continue
        product *= multiplier
        used += 1
    if used == 0:
        #: No field carries a verifiable status, so reliability is reported as 0
        #: instead of the vacuous empty product 1.0.
        return 0.0, 0
    return round(product, 6), used


def combine_dimensions(
    dimensions: Mapping[str, dict[str, Any]],
    weights: Mapping[str, float],
) -> tuple[float | None, dict[str, Any]]:
    """Renormalise weights over scorable dimensions and build the score breakdown."""
    breakdown: dict[str, Any] = {}
    available_weight = sum(
        float(weights[key]) for key in DIMENSIONS if dimensions[key].get("score") is not None
    )
    total: float | None = None
    if available_weight > 0.0:
        total = 0.0
    for key in DIMENSIONS:
        dimension = dimensions[key]
        weight = float(weights[key])
        score = dimension.get("score")
        #: An excluded (null-score) dimension has its weight redistributed over
        #: the remaining ones, so its own effective weight is zero.
        effective = (
            weight / available_weight if available_weight > 0.0 and score is not None else 0.0
        )
        breakdown[key] = {
            "score": score,
            "weight": weight,
            "weight_effective": round(effective, 6),
            "status": str(dimension.get("status", "unavailable")),
            "contributors": list(dimension.get("contributors", [])),
            "missing_indicators": list(dimension.get("missing_indicators", [])),
            "reason_zh": str(dimension.get("reason_zh", "")),
        }
        if total is not None and score is not None:
            total += float(score) * effective
    return (round(total, 3) if total is not None else None), breakdown


def score_route(
    route: Mapping[str, Any],
    dash_route: Mapping[str, Any] | None,
    origin_coord: Sequence[float] | None,
    request_ctx: Mapping[str, Any],
    weights: Mapping[str, float],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Score one catalog route against the request context; returns score fields only."""
    exposure_raw = dash_route.get("exposure") if dash_route is not None else None
    exposure: Mapping[str, Any] = exposure_raw if isinstance(exposure_raw, dict) else {}
    sport = str(request_ctx.get("sport", ""))
    band_range = request_ctx.get("band_range_km")
    prefer_loop = request_ctx.get("prefer_loop")
    preferences_raw = request_ctx.get("preferences") or []
    preferences = [str(tag) for tag in preferences_raw] if isinstance(preferences_raw, Sequence) else []

    dimensions: dict[str, dict[str, Any]] = {}
    dimensions["environment_health"] = score_environment(exposure)
    dimensions["sport_match"] = score_sport_match(
        route,
        sport,
        (float(band_range[0]), float(band_range[1])) if band_range is not None else None,
        bool(prefer_loop) if prefer_loop is not None else None,
    )
    access_dimension, access_min, straight_m = score_access(
        origin_coord, route, request_ctx.get("origin_name")
    )
    dimensions["access_convenience"] = access_dimension
    dimensions["route_quality"] = score_route_quality(route)
    dimensions["user_preference"] = score_user_preference(route, preferences, exposure)

    total_score, breakdown = combine_dimensions(dimensions, weights)
    risk = route_risk(dash_route, exposure, thresholds)
    reliability, reliability_fields = data_reliability(exposure)
    missing_fields = sorted(
        {
            str(key)
            for key in dimensions["environment_health"]["missing_indicators"]
        }
    )
    return {
        "score_breakdown": breakdown,
        "total_score": total_score,
        "overall_risk": risk["overall_risk"],
        "overall_risk_zh": RISK_LABELS_ZH.get(risk["overall_risk"], risk["overall_risk"]),
        "risk_pause": bool(risk["risk_pause"]),
        "risk_fields": risk["field_risk"],
        "pause_fields": risk["pause_fields"],
        "stop_fields": risk["stop_fields"],
        "data_reliability": reliability,
        "data_reliability_fields": reliability_fields,
        "estimated_access_min": access_min,
        "estimated_access_m": (
            round(access_min * ACCESS_SPEED_KMH / 60.0 * 1000.0, 1) if access_min is not None else None
        ),
        "straight_line_m": straight_m,
        "missing_fields": missing_fields,
        "provenance": PROVENANCE,
    }


def recommendation_reason_zh(candidate: Mapping[str, Any], rank: int) -> str:
    """Template reason built from the candidate's actual numbers."""
    breakdown = candidate.get("score_breakdown")
    breakdown = breakdown if isinstance(breakdown, dict) else {}
    contributions: list[tuple[float, str, float]] = []
    for key in DIMENSIONS:
        dimension = breakdown.get(key)
        if not isinstance(dimension, dict):
            continue
        score = as_float(dimension.get("score"))
        effective = as_float(dimension.get("weight_effective"))
        if score is None or effective is None:
            continue
        contributions.append((score * effective, DIMENSION_LABELS_ZH.get(key, key), score))
    contributions.sort(key=lambda item: (-item[0], item[1]))
    top = "、".join(f"{name} {score:.0f} 分" for _, name, score in contributions[:2])
    total = as_float(candidate.get("total_score"))
    distance = as_float(candidate.get("actual_distance_m"))
    access_min = as_float(candidate.get("estimated_access_min"))
    risk_zh = str(candidate.get("overall_risk_zh", "未知"))
    parts = [f"排名第 {rank}，总分 {total:.1f}" if total is not None else f"排名第 {rank}，总分不可用"]
    if top:
        parts.append(f"主要贡献：{top}")
    if distance is not None:
        parts.append(f"实测 {distance / 1000.0:.2f} km（{candidate.get('band_label_zh', '')}）")
    parts.append(f"接驳约 {access_min:.0f} 分钟" if access_min is not None else "未提供起点，接驳未计算")
    parts.append(f"风险等级：{risk_zh}")
    return "；".join(parts) + "。"


def scored_catalog_summary(
    catalog: Mapping[str, Any] | None,
    dashboard: Mapping[str, Any] | None,
    weights: Mapping[str, float],
) -> dict[str, Any]:
    """Request-independent scoring (environment + quality) for every accepted route."""
    routes = catalog.get("routes") if isinstance(catalog, Mapping) else None
    route_list = [item for item in routes if isinstance(item, dict)] if isinstance(routes, list) else []
    dash_routes = dashboard_route_map(dashboard)
    thresholds = dashboard.get("risk_thresholds") if isinstance(dashboard, Mapping) else None
    thresholds_map: Mapping[str, Any] = thresholds if isinstance(thresholds, dict) else {}
    summaries: list[dict[str, Any]] = []
    for route in route_list:
        dash_route = dash_routes.get(str(route.get("route_id", "")))
        exposure_raw = dash_route.get("exposure") if dash_route is not None else None
        exposure: Mapping[str, Any] = exposure_raw if isinstance(exposure_raw, dict) else {}
        environment = score_environment(exposure)
        quality = score_route_quality(route)
        null_dimension = {
            "score": None,
            "status": "unavailable",
            "contributors": [],
            "missing_indicators": [],
            "reason_zh": "",
        }
        #: combine_dimensions renormalises over dimensions with a non-null
        #: score, so the request-dependent three drop out automatically.
        total, _ = combine_dimensions(
            {
                "environment_health": environment,
                "sport_match": dict(null_dimension),
                "access_convenience": dict(null_dimension),
                "route_quality": quality,
                "user_preference": dict(null_dimension),
            },
            weights,
        )
        risk = route_risk(dash_route, exposure, thresholds_map)
        reliability, _ = data_reliability(exposure)
        summaries.append(
            {
                "route_id": route.get("route_id"),
                "name_zh": route.get("name_zh"),
                "mode": route.get("mode"),
                "kind": route.get("kind"),
                "band_label_zh": route.get("band_label_zh"),
                "actual_distance_m": route.get("actual_distance_m"),
                "area": route.get("area"),
                "area_name_zh": route.get("area_name_zh"),
                "status": route.get("status"),
                "environment_health": environment.get("score"),
                "route_quality": quality.get("score"),
                "catalog_score": total,
                "overall_risk": risk["overall_risk"],
                "data_reliability": reliability,
                "missing_fields": environment.get("missing_indicators", []),
            }
        )
    return {
        "provenance": PROVENANCE,
        "note_zh": "目录级评分仅覆盖与请求无关的环境健康与路线质量两维，权重按两维重归一。",
        "route_count": len(summaries),
        "routes": summaries,
    }


def dashboard_route_map(dashboard: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    """Index dashboard route entries by route_id."""
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(dashboard, Mapping):
        return result
    routes = dashboard.get("routes")
    if not isinstance(routes, list):
        return result
    for item in routes:
        if isinstance(item, dict) and isinstance(item.get("route_id"), str):
            result[str(item["route_id"])] = item
    return result
