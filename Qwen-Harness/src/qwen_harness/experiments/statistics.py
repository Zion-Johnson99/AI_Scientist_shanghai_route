"""确定性统计摘要与结果聚合（设计文档 01 §16.5）。

统计部分只使用标准库 ``statistics`` 与 ``random``，固定 seed 1234。
聚合部分把逐单元结果汇总为 metrics_summary（率、胜率、配对比较、负结果与
支持状态），支持状态复用 determine_support_status 冻结口径。预设画像不解释
为独立人群样本，不输出临床或人群外推结论。
"""

from __future__ import annotations

import random
import statistics
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ..models import ExperimentPlan, ResultInterpretation
from ..workflow.gates import determine_support_status

#: 全模块统一的确定性种子（设计文档 §16.5）。
DEFAULT_SEED = 1234
DEFAULT_BOOTSTRAP_ITERATIONS = 2000

#: metrics_summary 中进入结果解释高亮的关键率。
RATE_METRIC_IDS = (
    "detour_pass_rate",
    "environment_win_rate",
    "preference_win_rate",
    "constraint_pass_rate",
    "reference_verification_rate",
)

_CELL_READY = "ready"
_METRIC_NAMES = (
    "pm25_exposure", "pm25_health_score", "noise_proxy", "pollen_risk", "env_reliability",
    "target_deviation", "access_distance", "preference_hit_rate", "env_risk",
    "composite_score", "dimension_scores",
)


def summary_stats(values: Sequence[float]) -> dict[str, float | None]:
    """样本数、均值、中位数与四分位距（样本不足时对应项为 None）。"""
    data = [float(value) for value in values]
    if not data:
        return {"n": 0, "mean": None, "median": None, "iqr": None}
    median = statistics.median(data)
    if len(data) >= 2:
        quartiles = statistics.quantiles(data, n=4, method="inclusive")
        iqr = quartiles[2] - quartiles[0]
    else:
        iqr = None
    return {"n": len(data), "mean": statistics.fmean(data), "median": median, "iqr": iqr}


def win_rate(
    treatment: Sequence[float],
    baseline: Sequence[float],
) -> dict[str, float]:
    """配对胜率：严格更好记赢，相等记平（各计 0.5），更差记输。"""
    wins = ties = losses = 0
    for treated_value, baseline_value in zip(treatment, baseline, strict=True):
        if treated_value > baseline_value:
            wins += 1
        elif treated_value == baseline_value:
            ties += 1
        else:
            losses += 1
    total = wins + ties + losses
    rate = (wins + 0.5 * ties) / total if total else 0.0
    return {"wins": float(wins), "ties": float(ties), "losses": float(losses), "pairs": float(total), "rate": rate}


def paired_differences(treatment: Sequence[float], baseline: Sequence[float]) -> list[float]:
    """配对差值（处理 - 基线），长度与配对数一致。"""
    return [float(treated_value) - float(baseline_value) for treated_value, baseline_value in zip(treatment, baseline, strict=True)]


def mean_difference(treatment: Sequence[float], baseline: Sequence[float]) -> float | None:
    """配对均值差（处理 - 基线）；无配对时为 None。"""
    differences = paired_differences(treatment, baseline)
    return statistics.fmean(differences) if differences else None


def bootstrap_ci(
    differences: Sequence[float],
    *,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_SEED,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """配对差均值的百分位 bootstrap 置信区间；固定种子保证可复现。"""
    data = [float(value) for value in differences]
    if not data:
        return None
    if len(data) == 1:
        return (data[0], data[0])
    rng = random.Random(seed)
    size = len(data)
    means: list[float] = []
    for _ in range(max(1, int(iterations))):
        sample = [data[rng.randrange(size)] for _ in range(size)]
        means.append(statistics.fmean(sample))
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lower = means[max(0, min(len(means) - 1, round(alpha * (len(means) - 1))))]
    upper = means[max(0, min(len(means) - 1, round((1.0 - alpha) * (len(means) - 1))))]
    return (lower, upper)


def paired_comparison(
    treatment: Sequence[float],
    baseline: Sequence[float],
    *,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, object]:
    """一组配对比较的完整摘要：均值差、中位数差、胜率与 95% bootstrap 区间。"""
    differences = paired_differences(treatment, baseline)
    interval = bootstrap_ci(differences, iterations=iterations, seed=seed)
    return {
        "pairs": len(differences),
        "mean_difference": statistics.fmean(differences) if differences else None,
        "median_difference": statistics.median(differences) if differences else None,
        "win": win_rate(treatment, baseline),
        "differences_summary": summary_stats(differences),
        "ci_95": list(interval) if interval is not None else None,
        "seed": seed,
        "iterations": iterations,
    }


def pair_values(cell_records: Sequence[Mapping[str, Any]], variant_id: str, metric_path: str) -> dict[str, float]:
    """收集某变体全部就绪单元的指标值（按 case_id 索引，供配对比较）。"""
    values: dict[str, float] = {}
    for record in cell_records:
        if record.get("variant_id") != variant_id or record.get("status") != _CELL_READY:
            continue
        node: Any = record
        for part in metric_path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            values[str(record["case_id"])] = float(node)
    return values


def _detour_pass_rate(
    cell_records: Sequence[Mapping[str, Any]], detour_limit: float
) -> tuple[int, int]:
    """M1 相对 B0 的距离绕路配对通过数（返回 (通过数, 配对数)）。"""
    b0_by_case = {
        record["case_id"]: record
        for record in cell_records
        if record.get("variant_id") == "B0_shortest_feasible" and record.get("status") == _CELL_READY
    }
    passed = pairs_seen = 0
    for record in cell_records:
        if record.get("variant_id") != "M1_personalized_constrained" or record.get("status") != _CELL_READY:
            continue
        b0 = b0_by_case.get(record.get("case_id"))
        if b0 is None:
            continue
        d_m1 = (record.get("chosen") or {}).get("distance_m")
        d_b0 = (b0.get("chosen") or {}).get("distance_m")
        if d_m1 is None or d_b0 is None or float(d_b0) <= 0:
            continue
        pairs_seen += 1
        if (float(d_m1) - float(d_b0)) / float(d_b0) <= detour_limit:
            passed += 1
    return passed, pairs_seen


def aggregate_summary(
    cell_records: Sequence[Mapping[str, Any]],
    *,
    module_info: Mapping[str, Any],
    variant_ids: Sequence[str],
    detour_limit: float,
    target_tolerance: float,
    thresholds: Mapping[str, object],
    source_records: Mapping[str, Any],
    run_id: str,
    provenance: str,
) -> dict[str, Any]:
    """汇总率、胜率、配对统计与支持状态（阈值来自 quality_gates.json）。"""
    cells_total = len(cell_records)
    status_counts: dict[str, int] = {}
    for record in cell_records:
        status = str(record.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    no_candidate, missing = status_counts.get("no_candidate", 0), status_counts.get("missing", 0)
    paused, invalid = status_counts.get("paused", 0), status_counts.get("invalid", 0)

    m1_ready = [
        record
        for record in cell_records
        if record.get("variant_id") == "M1_personalized_constrained" and record.get("status") == _CELL_READY
    ]
    detour_pass, pairs_seen = _detour_pass_rate(cell_records, detour_limit)
    detour_pass_rate = detour_pass / pairs_seen if pairs_seen else 0.0

    def _pair_block(baseline_map: dict[str, float], variant_map: dict[str, float], flip: bool) -> dict[str, Any]:
        common = sorted(set(baseline_map) & set(variant_map))
        baseline = [baseline_map[case] for case in common]
        treatment = [variant_map[case] for case in common]
        # 环境风险越低越好：把“更低”翻转为“更高”后套用统一胜率/配对口径
        treated, base = ([-v for v in treatment], [-v for v in baseline]) if flip else (treatment, baseline)
        return {
            "m1_or_variant_mean": summary_stats(treatment)["mean"],
            "b0_mean": summary_stats(baseline)["mean"],
            "paired": paired_comparison(treated, base),
        }

    comparisons: dict[str, Any] = {}
    env_values = {variant: pair_values(cell_records, variant, "metrics.env_risk") for variant in variant_ids}
    pref_values = {variant: pair_values(cell_records, variant, "metrics.preference_hit_rate") for variant in variant_ids}
    env_win_rate = pref_win_rate = 0.0
    for variant in variant_ids:
        if variant == "B0_shortest_feasible":
            continue
        env_block = _pair_block(env_values["B0_shortest_feasible"], env_values[variant], flip=True)
        pref_block = _pair_block(pref_values["B0_shortest_feasible"], pref_values[variant], flip=False)
        comparisons[variant] = {"env_risk": env_block, "preference_hit_rate": pref_block}
        if variant == "M1_personalized_constrained":
            env_win_rate = float(env_block["paired"]["win"]["rate"])  # type: ignore[index]
            pref_win_rate = float(pref_block["paired"]["win"]["rate"])  # type: ignore[index]

    m1_metrics = [record.get("metrics") or {} for record in m1_ready]
    constraint_pass_rate = (
        sum(
            1
            for item in m1_metrics
            if item.get("target_deviation") is not None and float(item["target_deviation"]) <= target_tolerance
        )
        / len(m1_metrics)
        if m1_metrics
        else 0.0
    )
    reliability_values = [float(item["data_reliability"]) for item in m1_metrics if isinstance(item.get("data_reliability"), (int, float))]
    no_candidate_rate = no_candidate / cells_total if cells_total else 0.0
    verified = sum(1 for record in source_records.values() if getattr(record, "verification_status", None) == "verified")
    reference_verification_rate = verified / len(source_records) if source_records else 0.0

    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance,
        "metric_names": list(_METRIC_NAMES),
        "cells_total": cells_total,
        "cell_status_counts": status_counts,
        "no_candidate_rate": no_candidate_rate,
        "constraint_pass_rate": constraint_pass_rate,
        "detour_pass_rate": detour_pass_rate,
        "environment_win_rate": env_win_rate,
        "preference_win_rate": pref_win_rate,
        "reference_verification_rate": reference_verification_rate,
        "fatal_data_errors": module_info["fatal_data_errors"],
        "mean_data_reliability_m1": summary_stats(reliability_values)["mean"],
        **dict(thresholds),
        "comparisons": comparisons,
        "negative_results": {
            "no_candidate_cells": no_candidate, "missing_cells": missing,
            "paused_cells": paused, "invalid_cells": invalid,
        },
        "module_statuses": {m: r.get("preflight_status") for m, r in module_info["modules"].items()},
    }
    summary["support_status"] = determine_support_status(summary)
    return summary


def negative_results(summary: Mapping[str, Any], cell_records: Sequence[Mapping[str, Any]]) -> list[str]:
    """负结果清单：无候选/缺失/暂停单元与方向相反指标（无则明确声明）。"""
    items: list[str] = []
    negative = summary.get("negative_results") or {}
    if negative.get("no_candidate_cells"):
        items.append(f"{negative['no_candidate_cells']} 个变体×画像单元无候选（硬约束过滤后为空）")
    if negative.get("missing_cells"):
        items.append(f"{negative['missing_cells']} 个变体×画像单元缺少 score-candidates 输出")
    if negative.get("paused_cells"):
        items.append(f"{negative['paused_cells']} 个单元被风险评估暂停")
    if negative.get("invalid_cells"):
        items.append(f"{negative['invalid_cells']} 个候选文件无效")
    comparisons = summary.get("comparisons") or {}
    m1_block = comparisons.get("M1_personalized_constrained") or {}
    env_paired = (m1_block.get("env_risk") or {}).get("paired") or {}
    pref_paired = (m1_block.get("preference_hit_rate") or {}).get("paired") or {}
    if (env_paired.get("mean_difference") or 0) > 0:
        items.append("M1 相对 B0 的综合暴露风险升高（方向与假设相反）")
    if (pref_paired.get("mean_difference") or 0) < 0:
        items.append("M1 相对 B0 的偏好命中率下降（方向与假设相反）")
    failed_gate = sorted(
        str(record.get("case_id"))
        for record in cell_records
        if record.get("variant_id") == "M1_personalized_constrained"
        and record.get("status") == _CELL_READY
        and record.get("selection_gate_passed") is False
    )
    if failed_gate:
        items.append(f"M1 距离门禁未通过的画像: {', '.join(failed_gate)}")
    if not items:
        items.append("本次运行未观察到负结果")
    return items


def data_quality_notes(
    module_info: Mapping[str, Any], summary: Mapping[str, Any], cell_records: Sequence[Mapping[str, Any]]
) -> list[str]:
    """数据质量说明：来源、致命错误、模块预检降级与缺失单元（如实记录）。"""
    notes: list[str] = []
    notes.append(f"结果来源: {summary['provenance']}；致命数据错误 {summary['fatal_data_errors']} 个；来源核验率 {float(summary['reference_verification_rate']):.2f}")
    for module, record in module_info["modules"].items():
        if record["preflight_status"] == "partial":
            notes.append(f"模块 {module} 预检为 partial，相关指标需在解释时保留数据限制说明")
        for message in record["warnings"]:
            notes.append(f"{module}: {message}")
    missing_cells = [
        f"{record['case_id']}×{record['variant_id']}"
        for record in cell_records
        if record.get("status") == "missing"
    ]
    if missing_cells:
        notes.append(f"缺少候选输出的单元（已标记，不伪造）: {', '.join(missing_cells[:12])}")
    degraded = [
        f"{record['case_id']}×{record['variant_id']}: {message}"
        for record in cell_records
        for message in record.get("messages", [])
        if record.get("status") == _CELL_READY and message
    ]
    notes.extend(degraded[:8])
    return notes


def build_interpretation(
    summary: Mapping[str, Any],
    cell_records: Sequence[Mapping[str, Any]],
    module_info: Mapping[str, Any],
) -> ResultInterpretation:
    """按冻结阈值生成 ResultInterpretation（含负结果与数据质量说明）。"""
    status = str(summary.get("support_status", "inconclusive"))
    if status not in {"supported", "partially_supported", "unsupported", "inconclusive", "error"}:
        status = "inconclusive"
    interpretation = (
        f"按 quality_gates.json 预注册阈值：绕路通过率 {float(summary.get('detour_pass_rate', 0.0)):.2f}、"
        f"环境胜率 {float(summary.get('environment_win_rate', 0.0)):.2f}、"
        f"偏好胜率 {float(summary.get('preference_win_rate', 0.0)):.2f}、"
        f"参考核验率 {float(summary.get('reference_verification_rate', 0.0)):.2f}，支持状态判定为 {status}。"
        "预设画像为固定案例矩阵，不作为独立人群样本外推。"
    )
    highlights = [{"metric_id": metric_id, "value": summary.get(metric_id)} for metric_id in RATE_METRIC_IDS]
    highlights.append({"metric_id": "no_candidate_rate", "value": summary.get("no_candidate_rate")})
    ready_count = sum(1 for record in cell_records if record.get("status") == _CELL_READY)
    confidence = "medium" if ready_count >= 8 and summary.get("fatal_data_errors") == 0 else "low"
    return ResultInterpretation(
        status=status,  # type: ignore[arg-type]
        interpretation=interpretation,
        metric_highlights=highlights,
        negative_results=negative_results(summary, cell_records),
        data_quality_notes=data_quality_notes(module_info, summary, cell_records),
        confidence=confidence,
    )


def experiment_summary_payload(
    run_id: str,
    plan: ExperimentPlan,
    registry: Mapping[str, Any],
    cell_records: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    module_info: Mapping[str, Any],
    detour_limit: float,
    target_tolerance: float,
) -> dict[str, Any]:
    """experiments/experiment_results.json 的完整载荷。"""
    weights_hashes: dict[str, str] = {}
    for record in cell_records:
        digest = record.get("weights_sha256")
        if isinstance(digest, str) and digest:
            weights_hashes[str(record.get("variant_id", ""))] = digest
    module_hashes: dict[str, str] = {}
    for record in module_info["modules"].values():
        module_hashes.update(record.get("data_hashes", {}))
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": summary.get("generated_at"),
        "provenance": summary.get("provenance"),
        "profiles": [dict(item) for item in plan.profiles],
        "plan": {
            "hypothesis_id": plan.hypothesis_id, "variants": list(plan.variants),
            "detour_limit": detour_limit, "target_distance_tolerance": target_tolerance,
        },
        "variants_registry": dict(registry),
        "module_statuses": summary.get("module_statuses"),
        "data_hashes": {"modules": module_hashes, "weights_sha256": weights_hashes},
        "cells": [dict(record) for record in cell_records],
        "metrics_summary": dict(summary),
    }
