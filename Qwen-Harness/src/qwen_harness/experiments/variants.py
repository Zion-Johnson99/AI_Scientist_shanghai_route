"""预注册实验变体与选择规则（设计文档 01 §16.2、§16.4）。

五个变体（B0-B3、M1）在 ``config/experiment_variants.json`` 中冻结：选择
规则、所需字段与权重来源在运行期不可被模型临时改动。本模块只负责读取与
校验冻结注册表，并按声明的选择规则从 ``score-candidates`` 的可行候选集中
为每个变体×画像单元选出候选；规则本身不接受任何运行期参数。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import Field, ValidationError

from ..errors import InputContractError
from ..models import BaselineSpec, StrictModel

#: 五个预注册变体（ID 冻结，顺序即报告顺序）。
VARIANT_IDS: tuple[str, ...] = (
    "B0_shortest_feasible",
    "B1_pm25_only",
    "B2_multi_environment",
    "B3_non_personalized",
    "M1_personalized_constrained",
)

#: 环境分量 -> score-candidates 的 environment_summary 字段名。
ENV_SUMMARY_KEYS: dict[str, str] = {"pm25": "pm2_5", "noise": "noise", "pollen": "pollen"}


class VariantSpec(StrictModel):
    """冻结注册表中一个变体的声明。"""

    variant_id: str
    name: str
    selection_rule: str
    required_fields: list[str] = Field(default_factory=list)
    weights_source: str


def _builtin_specs() -> dict[str, dict[str, Any]]:
    """与 experiment_variants.json 内容一致的兜底注册表（仅配置文件缺失时使用）。"""
    return {
        "B0_shortest_feasible": {
            "variant_id": "B0_shortest_feasible",
            "name": "最短可行基线",
            "selection_rule": "在可行候选中最小化目标距离偏差，其次最小化接驳距离，再按 route_id 字典序。",
            "required_fields": ["route.distance_m", "access_distance_m", "profile.target_distance_m"],
            "weights_source": "none:选择规则不使用权重",
        },
        "B1_pm25_only": {
            "variant_id": "B1_pm25_only",
            "name": "单一 PM2.5 基线",
            "selection_rule": "在目标距离偏差门禁内最小化 PM2.5 浓度；缺失候选不参与选择，全部缺失时回退 B0 并记录。",
            "required_fields": ["environment_summary.pm2_5.value", "route.distance_m", "profile.target_distance_m"],
            "weights_source": "none:单指标最小化",
        },
        "B2_multi_environment": {
            "variant_id": "B2_multi_environment",
            "name": "多环境非个性化基线",
            "selection_rule": "在目标距离偏差门禁内最小化预注册归一化的综合暴露风险，忽略个人兴趣。",
            "required_fields": [
                "environment_summary.pm2_5.value",
                "environment_summary.noise.value",
                "environment_summary.pollen.value",
                "route.distance_m",
                "profile.target_distance_m",
            ],
            "weights_source": "experiment_variants.json:exposure_risk_coefficients",
        },
        "B3_non_personalized": {
            "variant_id": "B3_non_personalized",
            "name": "默认权重非个性化基线",
            "selection_rule": "默认平衡权重，不提升敏感项与兴趣项；按 route_quality、sport_match、data_confidence 与 route_id 选择。",
            "required_fields": ["dimension_scores.route_quality", "dimension_scores.sport_match", "data_confidence"],
            "weights_source": "evaluation_module:config/default_weights.json(goal=balanced)",
        },
        "M1_personalized_constrained": {
            "variant_id": "M1_personalized_constrained",
            "name": "个性化约束模型",
            "selection_rule": "个性化综合分受目标距离偏差、接驳半径与绕路上限门禁约束；按匹配偏好数、base_score、data_confidence 与 route_id 选择。",
            "required_fields": [
                "base_score",
                "matched_preferences",
                "data_confidence",
                "access_distance_m",
                "route.distance_m",
                "profile.target_distance_m",
                "profile.interests",
            ],
            "weights_source": "derived_config.weights 覆盖下的评价模块权重（记录 weights_sha256）",
        },
    }


def _validate_entries(entries: Sequence[Any], origin: str) -> dict[str, dict[str, Any]]:
    ordered: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise InputContractError(f"{origin} 的 variants 条目必须是对象")
        try:
            spec = VariantSpec.model_validate(raw)
        except ValidationError as exc:
            raise InputContractError(f"{origin} 的变体声明字段无效: {exc}") from exc
        ordered[spec.variant_id] = dict(raw)
    if tuple(ordered) != VARIANT_IDS:
        raise InputContractError(
            f"{origin} 必须按顺序声明恰好五个预注册变体 {', '.join(VARIANT_IDS)}",
            suggested_action="恢复 config/experiment_variants.json 的冻结内容",
        )
    return ordered


def load_experiment_variants(config_path: Path) -> dict[str, Any]:
    """读取并校验冻结的变体注册表；配置文件缺失时回退内置声明并附带警告。"""
    if not config_path.is_file():
        return {
            "schema_version": "1.0",
            "pre_registration_note": f"config/experiment_variants.json 缺失，使用内置冻结声明兜底: {config_path}",
            "variants": list(_builtin_specs().values()),
        }
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputContractError(
            f"config/experiment_variants.json 无法解析: {exc}",
            suggested_action="恢复冻结的变体配置文件",
        ) from exc
    if not isinstance(data, dict) or str(data.get("schema_version", "")) != "1.0":
        raise InputContractError("experiment_variants.json 顶层必须是对象且 schema_version=1.0")
    _validate_entries(data.get("variants") or [], "experiment_variants.json")
    return data


def validate_plan_against_registry(plan_variants: Sequence[str], registry: dict[str, Any]) -> None:
    """实验计划声明的变体必须全部在冻结注册表内（不允许新增或改名）。"""
    known = {str(item.get("variant_id", "")) for item in registry.get("variants", []) if isinstance(item, dict)}
    unknown = sorted({str(name) for name in plan_variants} - known)
    if unknown:
        raise InputContractError(
            f"实验计划声明了未注册的变体: {', '.join(unknown)}",
            suggested_action="变体必须来自 config/experiment_variants.json 的预注册列表",
        )


def baseline_specs(registry: dict[str, Any]) -> list[BaselineSpec]:
    """把注册表转换为 BaselineSpec 列表（保持注册表顺序）。"""
    specs: list[BaselineSpec] = []
    for item in registry.get("variants", []):
        if not isinstance(item, dict):
            continue
        specs.append(
            BaselineSpec(
                baseline_id=str(item.get("variant_id", "")),
                name=str(item.get("name", "")),
                selection_rule=str(item.get("selection_rule", "")),
                required_fields=[str(field) for field in item.get("required_fields", [])],
            )
        )
    return specs


# ---------------------------------------------------------------------------
# 选择规则：输入为同一画像的可行候选（score-candidates 输出），输出至多一个
# ---------------------------------------------------------------------------
Candidate = dict[str, Any]


def _route_id(candidate: Candidate) -> str:
    route = candidate.get("route")
    if isinstance(route, dict):
        value = route.get("route_id")
        if isinstance(value, str):
            return value
    return ""


def _env_value(candidate: Candidate, key: str) -> float | None:
    summary = candidate.get("environment_summary")
    if not isinstance(summary, dict):
        return None
    block = summary.get(ENV_SUMMARY_KEYS[key])
    if not isinstance(block, dict):
        return None
    value = block.get("value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def candidate_env_risk(candidate: Candidate, normalization: dict[str, Any]) -> float | None:
    """按冻结归一化计算候选综合暴露风险；任一分量缺失时返回 None。"""
    from .metrics import composite_env_risk, exposure_values

    values = exposure_values(
        _env_value(candidate, "pm25"),
        _env_value(candidate, "noise"),
        _env_value(candidate, "pollen"),
    )
    return composite_env_risk(values, normalization)


def _within_target_gate(candidates: Sequence[Candidate], profile: dict[str, Any], tolerance: float) -> list[Candidate]:
    target = float(profile.get("target_distance_m") or 0.0)
    if target <= 0:
        return []
    kept: list[Candidate] = []
    for candidate in candidates:
        route = candidate.get("route")
        distance = float(route.get("distance_m", 0.0)) if isinstance(route, dict) else 0.0
        if abs(distance - target) / target <= tolerance:
            kept.append(candidate)
    return kept


def select_b0(candidates: Sequence[Candidate], profile: dict[str, Any], params: dict[str, Any]) -> tuple[Candidate | None, list[str]]:
    target = float(profile.get("target_distance_m") or 0.0)

    def key(candidate: Candidate) -> tuple:
        route = candidate.get("route") or {}
        distance = float(route.get("distance_m", 0.0)) if isinstance(route, dict) else 0.0
        deviation = abs(distance - target) / target if target > 0 else float("inf")
        access = candidate.get("access_distance_m")
        return (deviation, float("inf") if access is None else float(access), _route_id(candidate))

    ordered = sorted(candidates, key=key)
    return (ordered[0], []) if ordered else (None, [])


def select_b1(candidates: Sequence[Candidate], profile: dict[str, Any], params: dict[str, Any]) -> tuple[Candidate | None, list[str]]:
    tolerance = float(params["target_deviation"])
    gated = _within_target_gate(candidates, profile, tolerance)
    eligible = [c for c in gated if _env_value(c, "pm25") is not None]
    notes: list[str] = []
    if gated and not eligible:
        notes.append("所有候选的 PM2.5 缺失，B1 回退为 B0 最短可行规则（降级，不伪造数值）")
        return select_b0(candidates, profile, params)
    ordered = sorted(eligible, key=lambda c: (float(_env_value(c, "pm25") or 0.0), _route_id(c)))
    return (ordered[0], notes) if ordered else (None, notes)


def select_b2(candidates: Sequence[Candidate], profile: dict[str, Any], params: dict[str, Any]) -> tuple[Candidate | None, list[str]]:
    tolerance = float(params["target_deviation"])
    normalization = params["normalization"]
    gated = _within_target_gate(candidates, profile, tolerance)
    scored = [(candidate_env_risk(c, normalization), c) for c in gated]
    eligible = [(risk, c) for risk, c in scored if risk is not None]
    notes: list[str] = []
    if gated and not eligible:
        notes.append("所有候选的综合暴露风险不可计算（环境分量缺失），B2 回退为 B0 最短可行规则（降级，不伪造数值）")
        return select_b0(candidates, profile, params)
    eligible.sort(key=lambda item: (float(item[0]), _route_id(item[1])))
    return (eligible[0][1], notes) if eligible else (None, notes)


def select_b3(candidates: Sequence[Candidate], profile: dict[str, Any], params: dict[str, Any]) -> tuple[Candidate | None, list[str]]:
    def key(candidate: Candidate) -> tuple:
        dimensions = candidate.get("dimension_scores") if isinstance(candidate.get("dimension_scores"), dict) else {}
        quality = float(dimensions.get("route_quality") or 0.0)
        sport = float(dimensions.get("sport_match") or 0.0)
        confidence = float(candidate.get("data_confidence") or 0.0)
        return (-quality, -sport, -confidence, _route_id(candidate))

    ordered = sorted(candidates, key=key)
    return (ordered[0], []) if ordered else (None, [])


def select_m1(candidates: Sequence[Candidate], profile: dict[str, Any], params: dict[str, Any]) -> tuple[Candidate | None, list[str]]:
    tolerance = float(params["target_deviation"])
    detour_limit = float(params["detour_limit"])
    search_radius = profile.get("search_radius_m")
    target = float(profile.get("target_distance_m") or 0.0)

    def passes_gate(candidate: Candidate) -> bool:
        route = candidate.get("route") or {}
        distance = float(route.get("distance_m", 0.0)) if isinstance(route, dict) else 0.0
        if target <= 0 or abs(distance - target) / target > tolerance:
            return False
        access = candidate.get("access_distance_m")
        if search_radius is not None and access is not None and float(access) > float(search_radius):
            return False
        shortest = float(params["min_feasible_distance"]) if params.get("min_feasible_distance") else None
        if shortest and shortest > 0 and (distance - shortest) / shortest > detour_limit:
            return False
        return True

    def key(candidate: Candidate) -> tuple:
        matched = candidate.get("matched_preferences")
        hits = len(matched) if isinstance(matched, list) else 0
        base = float(candidate.get("base_score") or 0.0)
        confidence = float(candidate.get("data_confidence") or 0.0)
        return (-hits, -base, -confidence, _route_id(candidate))

    gated = [c for c in candidates if passes_gate(c)]
    notes: list[str] = []
    if candidates and not gated:
        notes.append("M1 距离门禁清空候选集，回退为无门禁个性化选择（降级记录，不伪造候选）")
        gated = list(candidates)
    ordered = sorted(gated, key=key)
    return (ordered[0], notes) if ordered else (None, notes)


SELECTION_RULES: dict[str, Callable[..., tuple[Candidate | None, list[str]]]] = {
    "B0_shortest_feasible": select_b0,
    "B1_pm25_only": select_b1,
    "B2_multi_environment": select_b2,
    "B3_non_personalized": select_b3,
    "M1_personalized_constrained": select_m1,
}


def apply_selection_rule(
    variant_id: str,
    candidates: Sequence[Candidate],
    profile: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Candidate | None, list[str]]:
    """执行冻结的选择规则；未知变体直接报契约错误。"""
    rule = SELECTION_RULES.get(variant_id)
    if rule is None:
        raise InputContractError(f"未知变体: {variant_id}", suggested_action="变体必须来自预注册列表")
    return rule(list(candidates), dict(profile), dict(params))
