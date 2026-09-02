"""原始指标与派生指标计算（设计文档 01 §16.3、§16.4）。

指标输入只来自 ``score-candidates`` 的真实候选输出（维度分、
``environment_summary``、接驳距离、数据可信度）与冻结归一化配置；
缺失数据一律记为 ``None`` 并在报告中标记，不伪造数值。

科学边界（进入所有报告与 limitations）：

- PM2.5 为网格/站点融合估计，不是站点实测或传感器实测；
- 噪声为 0-100 风险代理，不是声级计实测；
- 花粉为日级背景/代理，不是逐时实测浓度。

综合分（``base_score``）只作为记录指标之一，结论判定依赖预注册门禁
而非综合分。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Sequence

from ..models import BaselineSpec, MetricSpec

DIMENSION_NAMES: tuple[str, ...] = (
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "interest_service",
)


@dataclass(frozen=True)
class CellMetrics:
    """一个变体×画像单元的选中候选指标；``None`` 表示数据缺失。"""

    pm25_value: float | None
    pm25_health_score: float | None
    noise_proxy: float | None
    pollen_risk: float | None
    pm25_risk: float | None
    noise_risk: float | None
    pollen_risk_norm: float | None
    env_risk: float | None
    data_reliability: float | None
    target_deviation: float | None
    access_distance_m: float | None
    preference_hit_rate: float | None
    composite_score: float | None
    dimension_scores: dict[str, float]


def metric_specs() -> list[MetricSpec]:
    """预注册指标表（主指标 + 辅助指标；维度分另列于 dimension_scores）。"""
    rows: list[tuple[str, str, str, str, bool, str]] = [
        (
            "pm25_exposure",
            "PM2.5 暴露",
            "lower",
            "选中候选 environment_summary.pm2_5.value，网格/站点融合估计（µg/m³）",
            False,
            "weather_api_data 环境快照 -> score-candidates",
        ),
        (
            "pm25_health_score",
            "PM2.5 健康分",
            "higher",
            "(1 - R_pm25) * 100；R_pm25 为 experiment_variants.json 冻结分段线性归一化",
            False,
            "experiment_variants.json:normalization.pm25_breakpoints_ug_m3",
        ),
        (
            "noise_proxy",
            "噪声风险代理",
            "lower",
            "选中候选 environment_summary.noise.value，0-100 风险代理（非实测声级）",
            False,
            "weather_api_data noise_model -> score-candidates",
        ),
        (
            "pollen_risk",
            "花粉风险",
            "lower",
            "选中候选 environment_summary.pollen.value，日级背景/代理（0-100）",
            False,
            "weather_api_data pollen_model -> score-candidates",
        ),
        (
            "env_reliability",
            "数据可靠度",
            "higher",
            "选中候选 data_confidence，评价模块按 status/confidence/estimated 计算",
            False,
            "score-candidates data_confidence",
        ),
        (
            "target_deviation",
            "目标距离偏差",
            "target",
            "|d_route - d_target| / d_target，预注册上限 0.15",
            True,
            "route_catalog.json + 预设画像",
        ),
        (
            "access_distance",
            "接驳距离",
            "lower",
            "GCJ-02 直线接驳距离（米），实际道路距离通常更长",
            False,
            "score-candidates access_distance_m",
        ),
        (
            "preference_hit_rate",
            "偏好命中率",
            "higher",
            "F_pref = |请求兴趣 ∩ 匹配偏好| / max(1, |请求兴趣|)",
            True,
            "score-candidates matched_preferences",
        ),
        (
            "env_risk",
            "综合暴露风险",
            "lower",
            "R_env = alpha*R_pm25 + beta*R_noise + gamma*R_pollen，系数冻结于 experiment_variants.json",
            True,
            "environment_summary + experiment_variants.json:exposure_risk_coefficients",
        ),
        (
            "composite_score",
            "综合分",
            "higher",
            "base_score（五维加权减风险惩罚），仅作参考记录，不作为唯一结论依据",
            False,
            "score-candidates base_score",
        ),
    ]
    return [
        MetricSpec(metric_id=mid, name=name, direction=direction, formula=formula, primary=primary, data_source=source)
        for mid, name, direction, formula, primary, source in rows
    ]


def baseline_specs(plan_baselines: Sequence[Any] | None = None) -> list[BaselineSpec]:
    """把计划中的基线声明规范化为 BaselineSpec 列表。"""
    specs: list[BaselineSpec] = []
    for item in plan_baselines or []:
        if isinstance(item, BaselineSpec):
            specs.append(item)
        elif isinstance(item, dict):
            specs.append(
                BaselineSpec(
                    baseline_id=str(item.get("baseline_id", "")),
                    name=str(item.get("name", "")),
                    selection_rule=str(item.get("selection_rule", "")),
                    required_fields=[str(field) for field in item.get("required_fields", [])],
                )
            )
    return specs


def piecewise_linear(value: float, points: Sequence[Sequence[float]]) -> float:
    """冻结分段线性插值；低于首节点取首节点值，高于末节点取末节点值。"""
    ordered = sorted(((float(x), float(y)) for x, y in points), key=lambda pair: pair[0])
    if not ordered:
        raise ValueError("分段线性归一化节点为空")
    if value <= ordered[0][0]:
        return ordered[0][1]
    if value >= ordered[-1][0]:
        return ordered[-1][1]
    for (x0, y0), (x1, y1) in pairwise(ordered):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            ratio = (value - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return ordered[-1][1]


def pm25_risk_normalized(pm25_value: float | None, normalization: dict[str, Any]) -> float | None:
    """PM2.5 浓度按冻结分段归一化到 0-1 风险（缺失返回 None）。"""
    if pm25_value is None:
        return None
    points = normalization.get("pm25_breakpoints_ug_m3") or [[0, 0.0], [250, 1.0]]
    return piecewise_linear(float(pm25_value), points)


def exposure_values(
    pm25_value: float | None, noise_value: float | None, pollen_value: float | None
) -> dict[str, float | None]:
    """三个暴露分量的 0-1 风险归一化（噪声/花粉为 0-100 代理除以冻结量程）。"""
    noise_risk = None if noise_value is None else max(0.0, min(1.0, float(noise_value) / 100.0))
    pollen_risk = None if pollen_value is None else max(0.0, min(1.0, float(pollen_value) / 100.0))
    return {"pm25": pm25_value, "noise": noise_risk, "pollen": pollen_risk}


def composite_env_risk(values: dict[str, float | None], normalization: dict[str, Any]) -> float | None:
    """R_env = alpha*R_pm25 + beta*R_noise + gamma*R_pollen；任一分量缺失返回 None。"""
    pm25 = pm25_risk_normalized(values.get("pm25"), normalization)
    noise = values.get("noise")
    pollen = values.get("pollen")
    if pm25 is None or noise is None or pollen is None:
        return None
    alpha = float(normalization.get("alpha_pm25", 0.5))
    beta = float(normalization.get("beta_noise", 0.3))
    gamma = float(normalization.get("gamma_pollen", 0.2))
    return alpha * pm25 + beta * float(noise) + gamma * float(pollen)


def preference_hit_rate(matched: Sequence[str] | None, requested: Sequence[str] | None) -> float:
    """F_pref = |请求 ∩ 匹配| / max(1, |请求|)。"""
    requested_set = {str(item) for item in (requested or [])}
    matched_set = {str(item) for item in (matched or [])}
    return len(requested_set & matched_set) / max(1, len(requested_set))


def _summary_value(environment_summary: Any, key: str) -> float | None:
    if not isinstance(environment_summary, dict):
        return None
    block = environment_summary.get(key)
    if not isinstance(block, dict):
        return None
    value = block.get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def compute_cell_metrics(
    candidate: dict[str, Any],
    profile: dict[str, Any],
    normalization: dict[str, Any],
) -> CellMetrics:
    """从选中候选与画像计算该单元的全部指标（缺失记 None）。"""
    route = candidate.get("route") if isinstance(candidate.get("route"), dict) else {}
    summary = candidate.get("environment_summary")
    pm25 = _summary_value(summary, "pm2_5")
    noise = _summary_value(summary, "noise")
    pollen = _summary_value(summary, "pollen")
    pm25_risk = pm25_risk_normalized(pm25, normalization)
    values = exposure_values(pm25, noise, pollen)
    env_risk = composite_env_risk(values, normalization)
    distance = route.get("distance_m")
    target = float(profile.get("target_distance_m") or 0.0)
    deviation = abs(float(distance) - target) / target if distance is not None and target > 0 else None
    access = candidate.get("access_distance_m")
    dimensions = candidate.get("dimension_scores") if isinstance(candidate.get("dimension_scores"), dict) else {}
    normalized_dims = {
        str(name): float(dimensions[name]) for name in DIMENSION_NAMES if isinstance(dimensions.get(name), (int, float))
    }
    return CellMetrics(
        pm25_value=pm25,
        pm25_health_score=None if pm25_risk is None else (1.0 - pm25_risk) * 100.0,
        noise_proxy=noise,
        pollen_risk=pollen,
        pm25_risk=pm25_risk,
        noise_risk=values["noise"],
        pollen_risk_norm=values["pollen"],
        env_risk=env_risk,
        data_reliability=(
            float(candidate["data_confidence"])
            if isinstance(candidate.get("data_confidence"), (int, float))
            else None
        ),
        target_deviation=deviation,
        access_distance_m=float(access) if access is not None else None,
        preference_hit_rate=preference_hit_rate(candidate.get("matched_preferences"), profile.get("interests")),
        composite_score=(
            float(candidate["base_score"]) if isinstance(candidate.get("base_score"), (int, float)) else None
        ),
        dimension_scores=normalized_dims,
    )


def constraint_checks(
    candidate: dict[str, Any],
    profile: dict[str, Any],
    *,
    detour_limit: float,
    target_tolerance: float,
    min_feasible_distance: float | None,
) -> dict[str, Any]:
    """距离类约束审计：目标偏差、接驳半径、绕路上限与综合通过状态。"""
    route = candidate.get("route") if isinstance(candidate.get("route"), dict) else {}
    distance = route.get("distance_m")
    target = float(profile.get("target_distance_m") or 0.0)
    deviation = abs(float(distance) - target) / target if distance is not None and target > 0 else None
    target_ok = deviation is not None and deviation <= target_tolerance

    access_ok: bool | None = None
    access = candidate.get("access_distance_m")
    search_radius = profile.get("search_radius_m")
    if search_radius is not None:
        access_ok = access is None or float(access) <= float(search_radius)

    detour_ratio: float | None = None
    if distance is not None and min_feasible_distance and min_feasible_distance > 0:
        detour_ratio = (float(distance) - min_feasible_distance) / min_feasible_distance
    detour_ok = detour_ratio is None or detour_ratio <= detour_limit

    return {
        "target_deviation": deviation,
        "target_ok": target_ok,
        "access_ok": access_ok,
        "detour_ratio": detour_ratio,
        "detour_ok": detour_ok,
        "constraint_pass": bool(target_ok and detour_ok and access_ok is not False),
    }
