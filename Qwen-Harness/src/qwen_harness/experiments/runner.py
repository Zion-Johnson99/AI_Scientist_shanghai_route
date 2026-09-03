"""``experiment_analysis`` 阶段处理器（设计文档 01 §16）。

汇总四模块 ``ModuleResult`` 与 ``score-candidates`` 候选，按预注册变体×画像
计算指标，产出：

- ``experiments/experiment_results.json``：逐单元结果（选中候选、指标、约束审计、选择降级记录）；
- ``experiments/metrics_summary.json`` 与 ``reports/metrics_summary.json``
  （后者供 ``final_validation`` 的 ResultGate 读取，内容一致）；
- 阶段输出为 ``ResultInterpretation``，支持状态由
  ``workflow.gates.determine_support_status`` 按 quality_gates.json 阈值判定。

率、胜率、配对统计与解释由 ``experiments.statistics`` 的聚合函数完成。

候选单元文件契约（EvaluationModelAdapter 写入，缺失时明确标记而不伪造）：

- 规范位置 ``experiments/score_candidates/{case_id}__{variant_id}.json``；
- 或 ``modules/evaluation`` ModuleResult 的 ``output_artifacts`` 指向的 JSON；
- 内容为 score-candidates 输出（profile / risk / data_generated_at /
  candidate_count / candidates / weights_sha256），可带顶层
  ``variant_id`` / ``case_id`` 或 ``cells`` 列表（元素含这两个键）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models import ExperimentPlan, ModuleResult, StageResult
from .metrics import compute_cell_metrics, constraint_checks
from .statistics import aggregate_summary, build_interpretation, experiment_summary_payload
from .variants import apply_selection_rule, load_experiment_variants, validate_plan_against_registry

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

MODULE_KEYS: tuple[str, ...] = ("route", "environment", "evaluation", "web")
CELLS_DIR = "experiments/score_candidates"
REQUIRED_CELL_KEYS = ("profile", "risk", "candidates")
CELL_STATUS_READY = "ready"
CELL_STATUS_NO_CANDIDATE = "no_candidate"
CELL_STATUS_PAUSED = "paused"
CELL_STATUS_MISSING = "missing"
CELL_STATUS_INVALID = "invalid"


def _module_records(context: "WorkflowContext") -> dict[str, Any]:
    """读取四模块的 preflight 与执行 ModuleResult、哈希、警告与致命错误数。"""
    modules_dir = context.store.run_dir / "modules"
    records: dict[str, Any] = {}
    fatal = 0
    for module in MODULE_KEYS:
        preflight_status = None
        preflight_path = modules_dir / module / "preflight.json"
        if preflight_path.is_file():
            try:
                preflight_status = ModuleResult.model_validate_json(
                    preflight_path.read_text(encoding="utf-8")
                ).status
            except Exception as exc:  # noqa: BLE001 - 损坏记录降级为警告
                context.emit(
                    "module_record_invalid",
                    f"{module}/preflight.json 无法解析: {exc}",
                    status="warning",
                )
        results: list[ModuleResult] = []
        if modules_dir.is_dir() and (modules_dir / module).is_dir():
            for path in sorted((modules_dir / module).glob("*.json")):
                if path.name == "preflight.json":
                    continue
                try:
                    results.append(
                        ModuleResult.model_validate_json(path.read_text(encoding="utf-8"))
                    )
                except Exception as exc:  # noqa: BLE001
                    context.emit(
                        "module_record_invalid", f"{path.name} 无法解析: {exc}", status="warning"
                    )
        hashes: dict[str, str] = {}
        warnings: list[str] = []
        errors: list[str] = []
        for result in results:
            hashes.update(result.data_hashes)
            warnings.extend(result.warnings)
            errors.extend(result.errors)
        statuses = [result.status for result in results]
        if preflight_status is not None:
            statuses.append(preflight_status)
        is_fatal = preflight_status is None or "error" in statuses
        if is_fatal:
            fatal += 1
        records[module] = {
            "preflight_seen": preflight_status is not None,
            "preflight_status": preflight_status,
            "statuses": statuses,
            "data_hashes": hashes,
            "warnings": warnings,
            "errors": errors,
            "fatal": is_fatal,
        }
    return {"modules": records, "fatal_data_errors": fatal}


def _collect_candidate_files(context: "WorkflowContext", canonical: list[Path]) -> list[Path]:
    """候选单元文件：规范目录优先，其次 evaluation ModuleResult 的 output_artifacts。"""
    files: list[Path] = list(canonical)
    extras: list[Path] = []
    evaluation_dir = context.store.run_dir / "modules" / "evaluation"
    if evaluation_dir.is_dir():
        for path in sorted(evaluation_dir.glob("*.json")):
            try:
                result = ModuleResult.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 非 ModuleResult 文件跳过
                continue
            for artifact in result.output_artifacts:
                candidate = Path(str(artifact))
                resolved = (
                    candidate if candidate.is_absolute() else (context.store.run_dir / candidate)
                )
                if resolved.is_file():
                    extras.append(resolved)
    canonical_resolved = {path.resolve() for path in files if path.is_file()}
    for path in extras:
        try:
            if path.resolve() not in canonical_resolved:
                files.append(path)
        except OSError:
            files.append(path)
    return files


def _register_cell(
    cells: list[dict[str, Any]],
    warnings: list[str],
    body: dict[str, Any],
    variant: str | None,
    case: str | None,
    origin: str,
    variant_order: dict[str, int],
    cases: dict[str, dict[str, Any]],
) -> None:
    """解析单个候选单元体：定位 case/variant，校验必备字段并登记状态。"""
    variant_id = variant or (
        body.get("variant_id") if isinstance(body.get("variant_id"), str) else None
    )
    case_id = case or (body.get("case_id") if isinstance(body.get("case_id"), str) else None)
    if not variant_id and "__" in origin:
        stem = origin.rsplit(".", 1)[0]
        parts = stem.split("__")
        if len(parts) == 2 and parts[0] and parts[1]:
            case_id, variant_id = case_id or parts[0], parts[1]
    if not case_id:
        profile = body.get("profile")
        if isinstance(profile, dict) and isinstance(profile.get("case_id"), str):
            case_id = profile["case_id"]
    if not variant_id or not case_id:
        warnings.append(f"无法定位候选单元的 case_id/variant_id，跳过: {origin}")
        return
    if str(variant_id) not in variant_order:
        warnings.append(f"候选单元使用未注册变体，跳过: {variant_id}")
        return
    if cases and case_id not in cases:
        warnings.append(f"候选单元引用未声明画像，跳过: {case_id}")
        return
    missing = [key for key in REQUIRED_CELL_KEYS if key not in body]
    if missing:
        cells.append(
            {
                "case_id": case_id,
                "variant_id": variant_id,
                "status": CELL_STATUS_INVALID,
                "messages": [f"候选文件缺少字段: {', '.join(missing)}"],
                "source_file": origin,
            }
        )
        return
    cells.append(
        {
            "case_id": case_id,
            "variant_id": variant_id,
            "status": CELL_STATUS_READY,
            "data": body,
            "source_file": origin,
        }
    )


def _index_cells(
    context: "WorkflowContext",
    registry: dict[str, Any],
    cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """解析全部候选单元文件，并为缺失的变体×画像组合补 missing 记录。"""
    variant_order = {
        str(item.get("variant_id", "")): position
        for position, item in enumerate(registry.get("variants", []))
        if isinstance(item, dict)
    }
    cells: list[dict[str, Any]] = []
    warnings: list[str] = []
    cells_root = context.store.run_dir / CELLS_DIR
    canonical = sorted(cells_root.glob("*.json")) if cells_root.is_dir() else []
    for path in _collect_candidate_files(context, canonical):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            cells.append(
                {
                    "case_id": path.stem,
                    "variant_id": "unknown",
                    "status": CELL_STATUS_INVALID,
                    "messages": [f"候选文件不可读: {exc}"],
                    "source_file": path.name,
                }
            )
            continue
        if not isinstance(raw, dict):
            warnings.append(f"候选文件顶层不是对象，跳过: {path.name}")
            continue
        declared_variant = raw.get("variant_id") if isinstance(raw.get("variant_id"), str) else None
        if isinstance(raw.get("cells"), list):
            for entry in raw["cells"]:
                if isinstance(entry, dict):
                    entry_case = (
                        entry.get("case_id") if isinstance(entry.get("case_id"), str) else None
                    )
                    _register_cell(
                        cells,
                        warnings,
                        entry,
                        declared_variant,
                        entry_case,
                        path.name,
                        variant_order,
                        cases,
                    )
        else:
            declared_case = raw.get("case_id") if isinstance(raw.get("case_id"), str) else None
            _register_cell(
                cells,
                warnings,
                raw,
                declared_variant,
                declared_case,
                path.name,
                variant_order,
                cases,
            )

    known = {(cell["case_id"], cell["variant_id"]) for cell in cells}
    for case_id in cases or {}:
        for variant_id in variant_order:
            if (case_id, variant_id) not in known:
                cells.append(
                    {
                        "case_id": case_id,
                        "variant_id": variant_id,
                        "status": CELL_STATUS_MISSING,
                        "messages": ["未找到该变体×画像的 score-candidates 输出（缺数据，不伪造）"],
                    }
                )
    cells.sort(
        key=lambda cell: (
            str(cell.get("case_id", "")),
            variant_order.get(str(cell.get("variant_id", "")), 99),
        )
    )
    return {"cells": cells, "warnings": warnings}


def _apply_selection(
    cells: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    registry: dict[str, Any],
    detour_limit: float,
    target_tolerance: float,
) -> list[dict[str, Any]]:
    """对就绪单元执行冻结选择规则，计算指标与约束审计。"""
    coefficients = registry.get("exposure_risk_coefficients")
    normalization: dict[str, Any] = dict(coefficients) if isinstance(coefficients, dict) else {}
    normalization_block = registry.get("normalization")
    if isinstance(normalization_block, dict):
        normalization.update(normalization_block)
    out: list[dict[str, Any]] = []
    for cell in cells:
        record: dict[str, Any] = {
            "case_id": cell["case_id"],
            "variant_id": cell["variant_id"],
            "status": cell["status"],
        }
        if cell["status"] != CELL_STATUS_READY:
            record["messages"] = list(cell.get("messages", []))
            out.append(record)
            continue
        data = cell["data"]
        candidates = data.get("candidates") or []
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        profile_body = cases.get(cell["case_id"], {}).get("profile", {}) or profile
        record["profile"] = profile_body or profile
        record["candidate_count"] = len(candidates)
        record["risk_status"] = (
            (data.get("risk") or {}).get("status") if isinstance(data.get("risk"), dict) else None
        )
        record["data_generated_at"] = data.get("data_generated_at")
        record["weights_sha256"] = data.get("weights_sha256")
        record["source_file"] = cell.get("source_file")
        messages: list[str] = list(cell.get("messages", []))
        if record["risk_status"] == "paused":
            record["status"] = CELL_STATUS_PAUSED
            messages.append("风险评估为暂停状态：候选不参与选择与胜率统计")
        if not candidates:
            record["status"] = CELL_STATUS_NO_CANDIDATE
            messages.append("无候选：硬约束过滤后候选集为空（如实记录，不编造路线）")
            record["messages"] = messages
            out.append(record)
            continue

        distances = [
            float(candidate["route"].get("distance_m"))
            for candidate in candidates
            if isinstance(candidate.get("route"), dict)
            and isinstance(candidate["route"].get("distance_m"), (int, float))
        ]
        min_feasible = min(distances) if distances else None
        params = {
            "detour_limit": detour_limit,
            "target_deviation": target_tolerance,
            "min_feasible_distance": min_feasible,
            "normalization": normalization,
        }
        chosen, notes = apply_selection_rule(
            cell["variant_id"], candidates, profile_body or profile, params
        )
        messages.extend(notes)
        if chosen is None:
            record["status"] = CELL_STATUS_NO_CANDIDATE
            messages.append("选择规则未选出候选")
            record["messages"] = messages
            out.append(record)
            continue
        route = chosen.get("route") or {}
        record["status"] = CELL_STATUS_READY
        record["chosen"] = {
            "route_id": route.get("route_id"),
            "route_name": route.get("route_name"),
            "distance_m": route.get("distance_m"),
            "access_distance_m": chosen.get("access_distance_m"),
            "base_score": chosen.get("base_score"),
            "data_confidence": chosen.get("data_confidence"),
            "matched_preferences": chosen.get("matched_preferences"),
            "dimension_scores": chosen.get("dimension_scores"),
            "environment_summary": chosen.get("environment_summary"),
        }
        cell_metrics = compute_cell_metrics(chosen, profile_body or profile, normalization)
        record["metrics"] = {
            "pm25_value": cell_metrics.pm25_value,
            "pm25_health_score": cell_metrics.pm25_health_score,
            "noise_proxy": cell_metrics.noise_proxy,
            "pollen_risk": cell_metrics.pollen_risk,
            "pm25_risk": cell_metrics.pm25_risk,
            "noise_risk": cell_metrics.noise_risk,
            "pollen_risk_norm": cell_metrics.pollen_risk_norm,
            "env_risk": cell_metrics.env_risk,
            "data_reliability": cell_metrics.data_reliability,
            "target_deviation": cell_metrics.target_deviation,
            "access_distance_m": cell_metrics.access_distance_m,
            "preference_hit_rate": cell_metrics.preference_hit_rate,
            "composite_score": cell_metrics.composite_score,
        }
        record["dimension_scores"] = cell_metrics.dimension_scores
        record["constraints"] = constraint_checks(
            chosen,
            profile_body or profile,
            detour_limit=detour_limit,
            target_tolerance=target_tolerance,
            min_feasible_distance=min_feasible,
        )
        record["selection_gate_passed"] = bool(record["constraints"]["constraint_pass"])
        record["messages"] = messages
        out.append(record)
    return out


def stage_handler(context: "WorkflowContext") -> StageResult:
    """experiment_analysis 阶段：汇总模块结果与候选，计算指标并落盘。"""
    plan = context.read_stage_output_model("experiment_design", ExperimentPlan)
    registry = load_experiment_variants(context.paths.config_dir / "experiment_variants.json")
    validate_plan_against_registry(plan.variants, registry)
    derived = context.read_derived_config()
    warnings: list[str] = []
    note = registry.get("pre_registration_note")
    if isinstance(note, str) and "兜底" in note:
        warnings.append(note)
    if isinstance(derived.get("weights"), dict) and derived["weights"]:
        warnings.append("反馈迭代曾调整注册权重（记录于派生配置，候选文件携带对应 weights_sha256）")
    detour_limit = float(derived.get("detour_limit") or plan.detour_limit)
    target_tolerance = float(plan.target_distance_tolerance)
    cases = {
        str(item.get("case_id", "")): dict(item)
        for item in plan.profiles
        if isinstance(item, dict) and item.get("case_id")
    }

    module_info = _module_records(context)
    indexed = _index_cells(context, registry, cases)
    warnings.extend(indexed["warnings"])
    cell_records = _apply_selection(
        indexed["cells"], cases, registry, detour_limit, target_tolerance
    )
    if not any(record.get("status") == CELL_STATUS_READY for record in cell_records):
        warnings.append(
            "没有任何就绪的候选单元：全部指标标记缺失，支持状态判为 inconclusive（不伪造数据）"
        )
    variant_ids = [
        str(item.get("variant_id", ""))
        for item in registry.get("variants", [])
        if isinstance(item, dict)
    ]
    summary = aggregate_summary(
        cell_records,
        module_info=module_info,
        variant_ids=variant_ids,
        detour_limit=detour_limit,
        target_tolerance=target_tolerance,
        thresholds=dict(context.quality_gates.get("supported", {})),
        source_records=context.source_registry(),
        run_id=context.run_id,
        provenance="offline_fixtures" if context.options.offline else "module_outputs",
    )

    results_payload = experiment_summary_payload(
        context.run_id,
        plan,
        registry,
        cell_records,
        summary,
        module_info,
        detour_limit,
        target_tolerance,
    )
    context.store.write_json_atomic("experiments/experiment_results.json", results_payload)
    context.store.write_json_atomic("experiments/metrics_summary.json", summary)
    context.store.write_json_atomic("reports/metrics_summary.json", summary)

    interpretation = build_interpretation(summary, cell_records, module_info)
    ready_count = sum(1 for record in cell_records if record.get("status") == CELL_STATUS_READY)
    context.emit(
        "experiment_results_ready",
        f"支持状态 {interpretation.status}；就绪单元 {ready_count}",
        details={
            "provenance": summary.get("provenance"),
            "cells_total": summary.get("cells_total"),
            "fatal_data_errors": summary.get("fatal_data_errors"),
        },
    )
    return StageResult(
        stage="experiment_analysis",
        status="passed",
        summary=f"实验分析完成: 单元 {summary.get('cells_total')} 个，就绪 {ready_count} 个，支持状态 {interpretation.status}",
        output=interpretation.model_dump(mode="json"),
        artifacts=[
            "experiments/experiment_results.json",
            "experiments/metrics_summary.json",
            "reports/metrics_summary.json",
        ],
        warnings=warnings,
    )
