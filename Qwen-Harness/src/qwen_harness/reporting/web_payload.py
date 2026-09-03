"""``web_payload`` 阶段处理器（设计文档 01 §19.3、§18.5）。

把一次运行的科研成果组装为 ``models.WebPayload`` 并写入
``publish/research_harness_latest.json``。该文件随后可由
``workflow.stages.publish_web_stage`` 原子复制到网页数据目录。

约束：

- 结论措辞统一为“当前候选集中的约束最优路线”。
- 脱敏：不出现绝对路径、密钥或内部推理文本；``artifacts`` 只放
  仓库相对路径或公开 URL。
- ``selected_route.route_id`` 若存在于 ``route_catalog.json`` 才填写，
  否则置空并降级说明。
- 支持状态读取 ``quality_gates.json`` 的 ``supported`` 阈值并复用
  ``workflow.gates.determine_support_status`` 的冻结口径。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..models import SelectedRoute, StageResult, WebPayload
from ..workflow.gates import determine_support_status

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

SELECTED_ROUTE_REASON = "当前候选集中的约束最优路线"
PAYLOAD_RELATIVE = "publish/research_harness_latest.json"
METRIC_LABELS: dict[str, tuple[str, str, str]] = {
    # metric_id -> (name, unit, direction)
    "detour_pass_rate": ("绕路约束通过率", "比例", "higher"),
    "environment_win_rate": ("环境改善胜率（M1 vs B0）", "比例", "higher"),
    "preference_win_rate": ("偏好命中率胜率（M1 vs B0）", "比例", "higher"),
    "constraint_pass_rate": ("约束通过率", "比例", "higher"),
    "no_candidate_rate": ("无候选率", "比例", "lower"),
    "mean_data_reliability_m1": ("M1 平均数据可靠度", "0-1", "higher"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(context: "WorkflowContext", relative: str) -> dict[str, Any] | None:
    data = context.store.read_json(relative)
    return data if isinstance(data, dict) else None


def _route_catalog_ids(context: "WorkflowContext") -> set[str]:
    catalog_path = context.paths.route_catalog_path
    if not catalog_path.is_file():
        return set()
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids: set[str] = set()
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("routes") if isinstance(data.get("routes"), list) else []
    else:
        rows = []
    for row in rows:
        if isinstance(row, dict):
            route_id = row.get("route_id") or row.get("id")
            if isinstance(route_id, str) and route_id:
                ids.add(route_id)
    return ids


def _metrics_summary(context: "WorkflowContext") -> dict[str, Any]:
    return (
        _load_json(context, "reports/metrics_summary.json")
        or _load_json(context, "experiments/metrics_summary.json")
        or {}
    )


def _selected_route(context: "WorkflowContext", catalog_ids: set[str]) -> SelectedRoute | None:
    """优先取 M1 的约束最优路线；route_id 需在路线目录中才对外展示。"""
    results = _load_json(context, "experiments/experiment_results.json") or {}
    cells = results.get("cells") if isinstance(results.get("cells"), list) else []
    for record in cells:
        if (
            not isinstance(record, dict)
            or record.get("variant_id") != "M1_personalized_constrained"
        ):
            continue
        if record.get("status") != "ready":
            continue
        chosen = record.get("chosen") if isinstance(record.get("chosen"), dict) else {}
        route_id = chosen.get("route_id")
        route_name = chosen.get("route_name") or ""
        if not (isinstance(route_id, str) and route_id):
            continue
        if catalog_ids and route_id not in catalog_ids:
            continue
        return SelectedRoute(
            route_id=route_id, route_name=str(route_name), reason=SELECTED_ROUTE_REASON
        )
    return None


def _build_key_metrics(summary: dict[str, Any]) -> list[dict[str, object]]:
    key_metrics: list[dict[str, object]] = []
    for metric_id, (name, unit, direction) in METRIC_LABELS.items():
        value = summary.get(metric_id)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            key_metrics.append(
                {
                    "metric_id": metric_id,
                    "name": name,
                    "value": round(float(value), 4),
                    "unit": unit,
                    "direction": direction,
                }
            )
    return key_metrics


def _build_baseline_comparison(summary: dict[str, Any]) -> list[dict[str, object]]:
    """以 M1 相对各基线（B0 为参照）的胜率/均值差作为基线对比摘要。"""
    comparison: list[dict[str, object]] = []
    comparisons = summary.get("comparisons") if isinstance(summary.get("comparisons"), dict) else {}
    for variant_id, block in comparisons.items():
        if not isinstance(block, dict):
            continue
        for metric_key, metric_label in (
            ("env_risk", "综合暴露风险"),
            ("preference_hit_rate", "偏好命中率"),
        ):
            metric = block.get(metric_key) if isinstance(block.get(metric_key), dict) else {}
            m1_mean = metric.get("m1_or_variant_mean")
            b0_mean = metric.get("b0_mean")
            if isinstance(m1_mean, (int, float)) and isinstance(b0_mean, (int, float)):
                comparison.append(
                    {
                        "baseline_id": variant_id,
                        "name": f"{variant_id} vs B0（{metric_label}）",
                        "metric_id": metric_key,
                        "value": round(float(m1_mean), 4),
                        "delta": round(float(m1_mean) - float(b0_mean), 4),
                    }
                )
    return comparison


def _build_iterations(context: "WorkflowContext") -> list[dict[str, object]]:
    """读取反馈迭代决策记录；无记录时回退到当前运行状态。"""
    iterations: list[dict[str, object]] = []
    iterations_root = context.store.run_dir / "iterations"
    if iterations_root.is_dir():
        for child in sorted(iterations_root.iterdir()):
            if not child.is_dir() or not child.name.startswith("iteration-"):
                continue
            decision_path = child / "decision.json"
            if not decision_path.is_file():
                continue
            try:
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(decision, dict):
                iterations.append(
                    {
                        "iteration": child.name.split("-", 1)[-1],
                        "status": decision.get("status"),
                        "reason": decision.get("reason"),
                    }
                )
    if not iterations:
        iterations.append(
            {
                "iteration": context.state.iteration,
                "status": context.state.status,
                "reason": "当前运行状态",
            }
        )
    return iterations


def _build_references(context: "WorkflowContext") -> list[dict[str, object]]:
    """引用只来自来源注册表，且仅保留已核验来源。

    注意：冻结的 PublishGate 绝对路径正则会把 ``https://`` 中的 ``s:/``
    误判为 Windows 盘符路径，故此处不携带 url 字段（完整 URL 保留在
    ``reports/scientific_plan.json`` 的参考文献中，供溯源使用）。
    """
    references: list[dict[str, object]] = []
    registry = context.source_registry()
    for source_id in sorted(registry):
        record = registry[source_id]
        if record.verification_status != "verified":
            continue
        references.append(
            {
                "source_id": record.source_id,
                "title": record.title,
                "year": record.year,
            }
        )
    return references


def _build_limitations(context: "WorkflowContext") -> list[str]:
    limitations = [
        "PM2.5 为网格/站点融合估计，不是站点实测或传感器实测值",
        "花粉为日级背景/代理指标，不是逐时实测浓度",
        "噪声为 0-100 风险代理，不是声级计实测",
        "接驳距离为 GCJ-02 直线估算，实际道路距离通常更长",
        "预设画像为固定案例矩阵，不解释为独立人群样本，不外推临床或人群结论",
    ]
    summary = _metrics_summary(context)
    negative = (
        summary.get("negative_results") if isinstance(summary.get("negative_results"), dict) else {}
    )
    if negative.get("no_candidate_cells"):
        limitations.append(f"存在 {negative['no_candidate_cells']} 个无候选单元，已如实记录")
    if negative.get("missing_cells"):
        limitations.append(
            f"存在 {negative['missing_cells']} 个缺少候选输出的单元，相关指标标记缺失"
        )
    return limitations


def _build_artifacts(context: "WorkflowContext") -> list[str]:
    """artifacts 只使用仓库相对路径（运行目录位于仓库内）。"""
    artifacts: list[str] = []
    try:
        run_dir_rel = context.store.run_dir.relative_to(context.repo_root)
    except ValueError:
        return artifacts
    base = run_dir_rel.as_posix()
    for relative in (
        "reports/scientific_plan.json",
        "reports/scientific_plan.md",
        "reports/experiment_report.md",
        "reports/reproducibility.md",
        "experiments/experiment_results.json",
        "experiments/metrics_summary.json",
    ):
        artifacts.append(f"{base}/{relative}")
    return artifacts


def _support_status(context: "WorkflowContext", summary: dict[str, Any]) -> str:
    """支持状态：优先取状态机结论，其次按 quality_gates 阈值现算。"""
    conclusion = context.conclusion_status or context.state.final_support_status
    if conclusion in {"supported", "partially_supported", "unsupported", "inconclusive", "error"}:
        return conclusion
    if summary:
        return determine_support_status(summary)
    return "inconclusive"


def _resolve_hypothesis(context: "WorkflowContext") -> str:
    """从假设阶段输出解析被选中假设的陈述；缺失时回退研究目标。"""
    selected_id: str | None = None
    review = context.read_stage_output("hypothesis_selection")
    if isinstance(review, dict):
        candidate = review.get("selected_hypothesis_id")
        if isinstance(candidate, str) and candidate:
            selected_id = candidate
    generation = context.read_stage_output("hypothesis_generation")
    if isinstance(generation, dict):
        items = (
            generation.get("hypotheses") if isinstance(generation.get("hypotheses"), list) else []
        )
        if selected_id is None and isinstance(generation.get("recommended_hypothesis_id"), str):
            selected_id = generation["recommended_hypothesis_id"]
        for item in items:
            if isinstance(item, dict) and item.get("hypothesis_id") == selected_id:
                statement = item.get("statement")
                if isinstance(statement, str) and statement.strip():
                    return statement
    return context.goal.desired_outcome or context.goal.question


def stage_handler(context: "WorkflowContext") -> StageResult:
    """组装 WebPayload 并写入运行目录的 publish/ 下。"""
    warnings: list[str] = []
    summary = _metrics_summary(context)
    if not summary:
        warnings.append("缺少 metrics_summary，支持状态与关键指标降级为 inconclusive/空")

    from . import markdown  # 延迟导入：先保证 payload 组装不受报告渲染影响

    try:
        markdown.generate_report_artifacts(context)
    except Exception as exc:  # noqa: BLE001 - 报告渲染失败不阻断 payload
        warnings.append(f"Markdown 报告生成失败（不阻断发布）: {exc}")

    status = _support_status(context, summary)
    catalog_ids = _route_catalog_ids(context)
    selected_route = _selected_route(context, catalog_ids)
    if selected_route is None:
        warnings.append("未能在路线目录中定位 M1 约束最优路线，selected_route 置空")

    payload = WebPayload(
        schema_version="1.0",
        run_id=context.run_id,
        generated_at=_utc_now(),
        status=status,  # type: ignore[arg-type]
        research_question=context.goal.question or context.goal.title,
        hypothesis=_resolve_hypothesis(context),
        selected_route=selected_route,
        key_metrics=_build_key_metrics(summary),
        baseline_comparison=_build_baseline_comparison(summary),
        iterations=_build_iterations(context),
        references=_build_references(context),
        limitations=_build_limitations(context),
        artifacts=_build_artifacts(context),
    )
    context.store.write_json_atomic(PAYLOAD_RELATIVE, payload.model_dump(mode="json"))
    context.emit(
        "web_payload_ready",
        "网页 payload 已写入 publish/，最终门禁通过后生成本地交付包",
        details={"status": status},
    )
    return StageResult(
        stage="web_payload",
        status="passed",
        summary=f"网页 payload 就绪（status={status}）",
        output=payload.model_dump(mode="json"),
        artifacts=[PAYLOAD_RELATIVE],
        warnings=warnings,
    )
