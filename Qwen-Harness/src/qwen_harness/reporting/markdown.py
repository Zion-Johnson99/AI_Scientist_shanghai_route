"""Markdown 报告渲染（设计文档 01 §19.2）。

由 ``generate_report_artifacts`` 生成三份报告：

- ``reports/scientific_plan.md``：科研计划全文（标题/摘要/方法/实验/结果/引用/局限/可复现）；
- ``reports/experiment_report.md``：实验报告十节结构（研究问题与假设、数据快照、
  预设画像与约束、基线与模型、指标与公式、结果表、失败案例、反馈迭代、支持状态、局限与下一步）；
- ``reports/reproducibility.md``：复现命令、环境与哈希。

数据全部来自运行产物；缺失处以“—”或缺失说明呈现，不伪造数字。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .scientific_plan import (
    PLAN_RELATIVE,
    SCIENTIFIC_BOUNDARIES,
    build_scientific_plan,
    write_scientific_plan,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

SCIENTIFIC_PLAN_MD = "reports/scientific_plan.md"
EXPERIMENT_REPORT_MD = "reports/experiment_report.md"
REPRODUCIBILITY_MD = "reports/reproducibility.md"

STATUS_LABELS = {
    "supported": "支持",
    "partially_supported": "部分支持",
    "unsupported": "不支持",
    "inconclusive": "证据不足",
    "error": "执行错误",
}


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.{digits}f}"


def _read_json(context: "WorkflowContext", relative: str) -> dict[str, Any]:
    data = context.store.read_json(relative)
    return data if isinstance(data, dict) else {}


def _ensure_plan(context: "WorkflowContext") -> dict[str, Any]:
    plan = _read_json(context, PLAN_RELATIVE)
    if plan:
        return plan
    model = build_scientific_plan(context)
    write_scientific_plan(context, model)
    return model.model_dump(mode="json")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def _metrics_summary(context: "WorkflowContext") -> dict[str, Any]:
    return _read_json(context, "reports/metrics_summary.json") or _read_json(context, "experiments/metrics_summary.json")


def _manifest_field(context: "WorkflowContext", key: str) -> str:
    manifest = _read_json(context, "run_manifest.json")
    value = manifest.get(key)
    return str(value) if value else "—"


def _experiment_results(context: "WorkflowContext") -> dict[str, Any]:
    return _read_json(context, "experiments/experiment_results.json")


def _hypothesis_statement(context: "WorkflowContext") -> str:
    selected_id = ""
    review = context.read_stage_output("hypothesis_selection")
    if isinstance(review, dict) and isinstance(review.get("selected_hypothesis_id"), str):
        selected_id = review["selected_hypothesis_id"]
    generation = context.read_stage_output("hypothesis_generation")
    if isinstance(generation, dict):
        if not selected_id and isinstance(generation.get("recommended_hypothesis_id"), str):
            selected_id = generation["recommended_hypothesis_id"]
        for item in generation.get("hypotheses") or []:
            if isinstance(item, dict) and item.get("hypothesis_id") == selected_id and item.get("statement"):
                return f"{item['statement']}（{selected_id}）"
    return "（假设阶段输出缺失，未生成假设陈述）"


def _iterations(context: "WorkflowContext") -> list[dict[str, Any]]:
    iterations: list[dict[str, Any]] = []
    root = context.store.run_dir / "iterations"
    if root.is_dir():
        for child in sorted(root.iterdir()):
            decision_path = child / "decision.json"
            if not child.is_dir() or not decision_path.is_file():
                continue
            try:
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(decision, dict):
                iterations.append({"iteration": child.name, "status": decision.get("status"), "reason": decision.get("reason")})
    return iterations


def render_scientific_plan_md(plan: dict[str, Any]) -> str:
    """科研计划全文 Markdown（所有字段来自 ScientificPlan 载荷）。"""
    results = plan.get("results") if isinstance(plan.get("results"), dict) else {}
    reproducibility = plan.get("reproducibility") if isinstance(plan.get("reproducibility"), dict) else {}
    experiments = plan.get("experiments") if isinstance(plan.get("experiments"), dict) else {}
    reference_lines = [
        f"{index}. {ref.get('title', '—')}（{', '.join(ref.get('authors') or []) or '作者未知'}，"
        f"{ref.get('year') or '年份未知'}）source_id={ref.get('source_id', '—')}"
        + (f" doi:{ref['doi']}" if ref.get("doi") else "")
        + (f" {ref['url']}" if ref.get("url") else "")
        for index, ref in enumerate(plan.get("references") or [], start=1)
    ] or ["（无已核验来源）"]
    lines = [
        f"# {plan.get('paper_title') or '科研计划'}",
        "",
        f"- run_id: {plan.get('run_id', '—')}",
        f"- 生成时间: {plan.get('generated_at', '—')}",
        f"- git_head: {plan.get('git_head') or '—'}",
        f"- schema_version: {plan.get('schema_version', '—')}",
        "",
        "## 摘要",
        str(plan.get("paper_abstract") or "—"),
        "",
        "## 问题陈述",
        str(plan.get("problem_statement") or "—"),
        "",
        "## 假设依据",
        str(plan.get("rationale") or "—"),
        "",
        "## 技术细节",
        *[f"- {item}" for item in plan.get("technical_details") or []],
        "",
        "## 数据集",
        "**来源**:",
        *[f"- {item}" for item in (plan.get("datasets") or {}).get("source") or []],
        "**目标产物**:",
        *[f"- {item}" for item in (plan.get("datasets") or {}).get("target") or []],
        "",
        "## 研究方法",
        *[f"- {item}" for item in plan.get("methods") or []],
        "",
        "## 实验设计",
        "**基线/变体**:",
        _table(
            ["编号", "名称", "选择规则", "必需字段"],
            [
                [spec.get("baseline_id", "—"), spec.get("name", "—"), spec.get("selection_rule", "—"), ", ".join(spec.get("required_fields") or [])]
                for spec in experiments.get("baselines") or []
            ],
        ),
        "**指标**:",
        _table(
            ["指标", "名称", "方向", "主指标", "公式", "数据来源"],
            [
                [
                    spec.get("metric_id", "—"), spec.get("name", "—"), spec.get("direction", "—"),
                    "是" if spec.get("primary") else "否", spec.get("formula", "—"), spec.get("data_source", "—"),
                ]
                for spec in experiments.get("metrics") or []
            ],
        ),
        "",
        "## 结果",
        f"支持状态: **{STATUS_LABELS.get(str(results.get('support_status')), '证据不足')}**（{results.get('support_status', 'inconclusive')}）",
        _table(
            ["指标", "数值"],
            [[key, _fmt(value)] for key, value in (results.get("key_rates") or {}).items()],
        ),
        "**负结果与数据质量**:",
        *[f"- {item}" for item in results.get("negative_results") or []],
        *[f"- {item}" for item in results.get("data_quality_notes") or []],
        "",
        "## 参考文献（仅已核验来源注册表）",
        *reference_lines,
        "",
        "## 证据映射",
        _table(
            ["证据卡", "已核验来源"],
            [[card, ", ".join(source_ids)] for card, source_ids in (plan.get("evidence_map") or {}).items()],
        ) if plan.get("evidence_map") else "（无证据卡）",
        "",
        "## 局限",
        *[f"- {item}" for item in plan.get("limitations") or []],
        "",
        "## 可复现性",
        "```",
        *[str(command) for command in reproducibility.get("commands") or []],
        "```",
        _table(
            ["项", "值"],
            [[key, str(value)] for key, value in (reproducibility.get("environment") or {}).items()],
        ),
        "",
        "## 数据快照哈希",
        _table(["数据", "sha256"], [[key, digest] for key, digest in (plan.get("data_snapshot_hashes") or {}).items()])
        if plan.get("data_snapshot_hashes")
        else "（无可用数据快照哈希）",
        "",
    ]
    return "\n".join(lines)


def render_experiment_report_md(context: "WorkflowContext", plan: dict[str, Any]) -> str:
    """实验报告（§19.2 十节结构）：基线对比、指标表、支持状态、数据限制。"""
    summary = _metrics_summary(context)
    results = _experiment_results(context)
    cells = results.get("cells") if isinstance(results.get("cells"), list) else []
    registry = results.get("variants_registry") if isinstance(results.get("variants_registry"), dict) else {}
    plan_block = results.get("plan") if isinstance(results.get("plan"), dict) else {}
    profiles = results.get("profiles") if isinstance(results.get("profiles"), list) else []
    interpretation = context.read_stage_output("experiment_analysis") or {}
    plan_results = plan.get("results") if isinstance(plan.get("results"), dict) else {}
    status = str(summary.get("support_status") or plan_results.get("support_status") or "inconclusive")
    failed = [cell for cell in cells if cell.get("status") not in {"ready", None}]
    generated_ats = sorted({str(cell.get("data_generated_at")) for cell in cells if cell.get("data_generated_at")})
    comparisons = summary.get("comparisons") if isinstance(summary.get("comparisons"), dict) else {}
    comparison_rows: list[list[str]] = []
    for variant_id, block in comparisons.items():
        for metric_id, metric in block.items():
            paired = metric.get("paired") if isinstance(metric.get("paired"), dict) else {}
            win = paired.get("win") if isinstance(paired.get("win"), dict) else {}
            interval = paired.get("ci_95")
            comparison_rows.append(
                [
                    variant_id, metric_id, str(paired.get("pairs", 0)),
                    _fmt(metric.get("m1_or_variant_mean")), _fmt(metric.get("b0_mean")),
                    _fmt(paired.get("mean_difference")),
                    f"[{_fmt(interval[0])}, {_fmt(interval[1])}]" if isinstance(interval, list) and len(interval) == 2 else "—",
                    _fmt(win.get("rate")),
                ]
            )

    failed_lines = [
        f"- {cell.get('case_id')}×{cell.get('variant_id')}: {cell.get('status')}"
        + (f" — {(cell.get('messages') or [''])[0]}" if cell.get("messages") else "")
        for cell in failed
    ] or ["- 无失败案例"]
    iteration_lines = [
        f"- {item['iteration']}: {item.get('status', '—')}（{item.get('reason', '—')}）"
        for item in _iterations(context)
    ] or [f"- 无反馈迭代记录（当前为第 {context.state.iteration} 轮，状态 {context.state.status}）"]

    lines = [
        "# 实验报告：多目标环境暴露约束与个性化路线选择",
        "",
        "## 1. 研究问题与假设",
        f"- 研究问题: {context.goal.question or context.goal.title}",
        f"- 预注册假设: {_hypothesis_statement(context)}",
        "",
        "## 2. 数据快照",
        f"- run_id: {context.run_id}；git_head: {_manifest_field(context, 'git_head')}",
        f"- 结果来源: {summary.get('provenance', results.get('provenance', '—'))}；致命数据错误: {summary.get('fatal_data_errors', '—')}",
        f"- 候选数据生成时间: {', '.join(generated_ats) if generated_ats else '—'}",
        f"- 模块预检状态: {json.dumps(summary.get('module_statuses') or results.get('module_statuses') or {}, ensure_ascii=False)}",
        "",
        "## 3. 预设画像与约束",
        _table(
            ["案例", "模式", "目标", "目标距离(m)", "偏差容忍", "搜索半径(m)"],
            [
                [
                    str((profile.get("profile") or profile).get("case_id", profile.get("case_id", "—"))),
                    str((profile.get("profile") or profile).get("mode", "—")),
                    str((profile.get("profile") or profile).get("goal", "—")),
                    _fmt((profile.get("profile") or profile).get("target_distance_m"), 0),
                    _fmt((profile.get("profile") or profile).get("distance_tolerance_ratio")),
                    _fmt((profile.get("profile") or profile).get("search_radius_m"), 0),
                ]
                for profile in profiles
            ],
        ) if profiles else "（实验计划缺少画像记录）",
        f"- 全局约束: 绕路上限 {plan_block.get('detour_limit', '—')}，目标距离偏差容忍 {plan_block.get('target_distance_tolerance', '—')}",
        "",
        "## 4. 基线与模型（预注册，冻结）",
        _table(
            ["变体", "名称", "选择规则", "权重来源"],
            [
                [item.get("variant_id", "—"), item.get("name", "—"), item.get("selection_rule", "—"), item.get("weights_source", "—")]
                for item in registry.get("variants") or []
                if isinstance(item, dict)
            ],
        ) if registry.get("variants") else "（变体注册表缺失）",
        "",
        "## 5. 指标与公式",
        _table(
            ["指标", "名称", "方向", "主指标", "公式"],
            [
                [
                    spec.get("metric_id", "—"), spec.get("name", "—"), spec.get("direction", "—"),
                    "是" if spec.get("primary") else "否", spec.get("formula", "—"),
                ]
                for spec in (plan.get("experiments") or {}).get("metrics") or []
            ],
        ) if (plan.get("experiments") or {}).get("metrics") else "（指标规格缺失：结果不依赖单一 base_score，见 metrics_summary.metric_names）",
        "",
        "## 6. 结果表",
        "**总体率**:",
        _table(
            ["指标", "数值"],
            [
                [key, _fmt(summary.get(key))]
                for key in (
                    "detour_pass_rate", "environment_win_rate", "preference_win_rate",
                    "constraint_pass_rate", "no_candidate_rate", "reference_verification_rate",
                    "mean_data_reliability_m1",
                )
            ],
        ),
        "**配对比较（变体 vs B0；env_risk 已按“越低越好”翻转口径呈现胜率）**:",
        _table(
            ["变体", "指标", "配对数", "变体均值", "B0 均值", "均值差", "95% CI", "胜率"],
            comparison_rows,
        ) if comparison_rows else "（无就绪配对单元，无法计算配对统计）",
        "",
        "## 7. 失败案例（如实记录，不伪造）",
        *failed_lines,
        "",
        "## 8. 反馈迭代",
        *iteration_lines,
        "",
        "## 9. 支持状态",
        f"- 判定: **{STATUS_LABELS.get(status, '证据不足')}**（{status}）",
        f"- 解释: {interpretation.get('interpretation') or '（解释缺失，判定依据见 metrics_summary 与 quality_gates.json 阈值）'}",
        "- 判定口径: 全部条件满足→supported；仅部分改善→partially_supported；方向相反→unsupported；证据不足→inconclusive",
        "",
        "## 10. 局限与下一步",
        *[f"- {item}" for item in SCIENTIFIC_BOUNDARIES],
        *[f"- 负结果: {item}" for item in interpretation.get("negative_results") or []],
        "- 下一步: 补充缺失候选单元、接入实测环境数据核验融合估计、扩大画像矩阵后复核阈值",
        "",
    ]
    return "\n".join(lines)


def render_reproducibility_md(context: "WorkflowContext", plan: dict[str, Any]) -> str:
    """复现报告：命令、环境与哈希。"""
    reproducibility = plan.get("reproducibility") if isinstance(plan.get("reproducibility"), dict) else {}
    statistics_block = reproducibility.get("statistics") or {}
    git_block = reproducibility.get("git") or {}
    lines = [
        "# 可复现性说明",
        "",
        "## 复现命令",
        "```",
        *[str(command) for command in reproducibility.get("commands") or []],
        "```",
        "",
        "## 运行环境",
        _table(
            ["项", "值"],
            [[key, str(value)] for key, value in (reproducibility.get("environment") or {}).items()],
        ),
        f"- 工作流: {json.dumps(reproducibility.get('workflow') or {}, ensure_ascii=False)}",
        f"- 统计: seed={statistics_block.get('seed', '—')}，bootstrap 迭代 {statistics_block.get('bootstrap_iterations', '—')}",
        f"- Git: 分支 {git_block.get('branch') or '—'}，HEAD {git_block.get('head') or '—'}，工作树干净={git_block.get('worktree_clean')}",
        "",
        "## 配置哈希",
        _table(["配置", "sha256"], [[key, digest] for key, digest in (reproducibility.get("config_hashes") or {}).items()])
        if reproducibility.get("config_hashes")
        else "（无配置哈希）",
        "",
        "## 技能哈希",
        _table(["技能", "sha256"], [[key, digest] for key, digest in (reproducibility.get("skills_hashes") or {}).items()])
        if reproducibility.get("skills_hashes")
        else "（无技能哈希）",
        "",
        "## 数据快照哈希",
        _table(["数据", "sha256"], [[key, digest] for key, digest in (plan.get("data_snapshot_hashes") or {}).items()])
        if plan.get("data_snapshot_hashes")
        else "（无可用数据快照哈希）",
        "",
        "## 结果产物",
        "- experiments/experiment_results.json",
        "- experiments/metrics_summary.json（与 reports/metrics_summary.json 内容一致）",
        "- reports/scientific_plan.json / scientific_plan.md / experiment_report.md",
        "- publish/research_harness_latest.json",
        "",
    ]
    return "\n".join(lines)


def generate_report_artifacts(context: "WorkflowContext") -> list[str]:
    """生成三份 Markdown 报告（幂等），返回运行目录相对路径列表。"""
    plan = _ensure_plan(context)
    outputs = {
        SCIENTIFIC_PLAN_MD: render_scientific_plan_md(plan),
        EXPERIMENT_REPORT_MD: render_experiment_report_md(context, plan),
        REPRODUCIBILITY_MD: render_reproducibility_md(context, plan),
    }
    for relative, text in outputs.items():
        context.store.write_bytes_atomic(relative, text.encode("utf-8"))
    context.emit("markdown_reports_ready", "三份 Markdown 报告已生成", details={"artifacts": sorted(outputs)})
    return sorted(outputs)
