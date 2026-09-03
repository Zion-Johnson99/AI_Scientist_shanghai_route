"""科研计划组装（设计文档 01 §19.1）。

从运行产物确定性地组装 ``models.ScientificPlan`` 并写入
``reports/scientific_plan.json``：

- Problem Statement / Rationale 取自 problem_framing、hypothesis 阶段输出；
- Technical Details / Methods / Experiments 取自预注册变体注册表与
  experiment_design 的 ExperimentPlan；
- References 只来自来源注册表，且仅保留已核验（verified）来源；
- evidence_map 来自证据卡（claims 与来源逐条对应）；
- reproducibility 含复现命令、环境、配置/技能哈希；
- data_snapshot_hashes 来自运行清单的模块数据哈希与模块执行哈希；
- limitations 固定声明科研边界（融合估计/代理指标，不声称实测）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..experiments.metrics import metric_specs
from ..experiments.statistics import DEFAULT_BOOTSTRAP_ITERATIONS, DEFAULT_SEED
from ..experiments.variants import load_experiment_variants
from ..models import (
    BaselineSpec,
    ExperimentPlan,
    PlanDatasets,
    PlanExperiments,
    PlanReference,
    ScientificPlan,
    StageResult,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..workflow.engine import WorkflowContext

PLAN_RELATIVE = "reports/scientific_plan.json"

#: 固定科研边界声明：报告与网页措辞必须包含，不得声称实测。
SCIENTIFIC_BOUNDARIES: tuple[str, ...] = (
    "PM2.5 暴露为网格/站点融合估计，不是站点实测或传感器实测值",
    "花粉为日级背景/代理指标，不是逐时实测浓度",
    "噪声为 0-100 风险代理，不是声级计实测",
    "接驳距离为 GCJ-02 直线估算，实际道路距离通常更长",
    "预设画像为固定案例矩阵，不解释为独立人群样本，不外推临床或人群结论",
)

PAPER_TITLE = (
    "多目标环境暴露约束与个性化城市健身出行路线选择：基于上海徐汇预设画像矩阵的预注册对照实验"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(context: "WorkflowContext", relative: str) -> dict[str, Any] | None:
    data = context.store.read_json(relative)
    return data if isinstance(data, dict) else None


def _metrics_summary(context: "WorkflowContext") -> dict[str, Any]:
    return (
        _read_json(context, "reports/metrics_summary.json")
        or _read_json(context, "experiments/metrics_summary.json")
        or {}
    )


def _experiment_results(context: "WorkflowContext") -> dict[str, Any]:
    return _read_json(context, "experiments/experiment_results.json") or {}


def _problem_frame(context: "WorkflowContext") -> dict[str, Any]:
    frame = context.read_stage_output("problem_framing")
    return frame if isinstance(frame, dict) else {}


def _hypothesis_info(context: "WorkflowContext") -> dict[str, str]:
    """解析被选假设（hypothesis_id / statement / mechanism / rationale）。"""
    selected_id = ""
    rationale = ""
    review = context.read_stage_output("hypothesis_selection")
    if isinstance(review, dict):
        if isinstance(review.get("selected_hypothesis_id"), str):
            selected_id = review["selected_hypothesis_id"]
        if isinstance(review.get("selection_rationale"), str):
            rationale = review["selection_rationale"]
    generation = context.read_stage_output("hypothesis_generation")
    if isinstance(generation, dict):
        if not selected_id and isinstance(generation.get("recommended_hypothesis_id"), str):
            selected_id = generation["recommended_hypothesis_id"]
        if not rationale and isinstance(generation.get("selection_rationale"), str):
            rationale = generation["selection_rationale"]
        for item in generation.get("hypotheses") or []:
            if isinstance(item, dict) and item.get("hypothesis_id") == selected_id:
                return {
                    "hypothesis_id": selected_id,
                    "statement": str(item.get("statement") or ""),
                    "mechanism": str(item.get("mechanism") or ""),
                    "rationale": rationale,
                }
    return {"hypothesis_id": selected_id, "statement": "", "mechanism": "", "rationale": rationale}


def _references(context: "WorkflowContext") -> list[PlanReference]:
    """引用只来自来源注册表，且仅保留已核验来源。"""
    references: list[PlanReference] = []
    registry = context.source_registry()
    for source_id in sorted(registry):
        record = registry[source_id]
        if record.verification_status != "verified":
            continue
        references.append(
            PlanReference(
                source_id=record.source_id,
                title=record.title,
                authors=list(record.authors),
                year=record.year,
                doi=record.doi,
                pmid=record.pmid,
                url=record.url,
            )
        )
    return references


def _evidence_map(context: "WorkflowContext") -> dict[str, list[str]]:
    """证据卡 -> 已核验来源映射（逐卡聚合，未核验来源剔除）。"""
    registry = context.source_registry()
    verified = {
        source_id
        for source_id, record in registry.items()
        if record.verification_status == "verified"
    }
    evidence_map: dict[str, list[str]] = {}
    for card in context.store.load_evidence_cards():
        source_ids = set(card.source_ids)
        for claim in card.claims:
            source_ids.add(claim.source_id)
        kept = sorted(source_ids & verified)
        if kept:
            evidence_map[card.card_id] = kept
    return evidence_map


def _datasets(context: "WorkflowContext", results: dict[str, Any]) -> PlanDatasets:
    """数据来源（模块数据快照+已核验文献）与目标产物（运行目录相对路径）。"""
    source: list[str] = []
    for key in sorted(context.manifest.module_data_hashes):
        source.append(f"模块数据快照: {key}")
    module_hashes = (results.get("data_hashes") or {}).get("modules") or {}
    for key in sorted(module_hashes):
        if key not in context.manifest.module_data_hashes:
            source.append(f"模块执行输出: {key}")
    registry = context.source_registry()
    for source_id in sorted(registry):
        record = registry[source_id]
        if record.verification_status == "verified":
            source.append(f"已核验来源: {record.title}（{record.source_id}）")
    target = [
        "experiments/experiment_results.json",
        "experiments/metrics_summary.json",
        "reports/metrics_summary.json",
        "reports/scientific_plan.json",
        "publish/research_harness_latest.json",
    ]
    return PlanDatasets(source=source or ["无可用模块数据快照（缺数据，如实记录）"], target=target)


def _technical_details(context: "WorkflowContext", plan_block: dict[str, Any]) -> list[str]:
    """变体选择规则、权重来源、风险合成系数与归一化口径（全部预注册）。"""
    registry = load_experiment_variants(context.paths.config_dir / "experiment_variants.json")
    coefficients = registry.get("exposure_risk_coefficients") or {}
    details = [
        f"综合暴露风险 R_env = α·R_pm25 + β·R_noise + γ·R_pollen，系数预注册于 config/experiment_variants.json"
        f"（α={coefficients.get('alpha_pm25')}, β={coefficients.get('beta_noise')}, γ={coefficients.get('gamma_pollen')}）",
        "PM2.5 风险归一化采用预注册分段线性断点（0-250 µg/m³）；噪声/花粉按 0-100 刻度线性归一",
        "候选评分基于五维分数：environment_health / sport_match / access_convenience / route_quality / interest_service",
        f"距离约束：绕路上限 {plan_block.get('detour_limit')}，目标距离偏差容忍 {plan_block.get('target_distance_tolerance')}",
        "统计口径：配对胜率 (wins+0.5×ties)/pairs、配对差均值、百分位 bootstrap 95% CI，seed=1234",
    ]
    for item in registry.get("variants", []):
        if isinstance(item, dict):
            details.append(
                f"变体 {item.get('variant_id')}（{item.get('name')}）：{item.get('selection_rule')}；"
                f"权重来源 {item.get('weights_source')}"
            )
    return details


def _methods(context: "WorkflowContext", profile_count: int) -> list[str]:
    return [
        f"预设画像矩阵：{profile_count} 个固定案例（步行/跑步/骑行 × 健康/景观/便利/均衡目标），目标时间由快照时间加固定偏移解析",
        "五个预注册变体（B0-B3 基线 + M1 个性化约束），选择规则冻结于 config/experiment_variants.json，运行中不改",
        "候选来自 score-candidates 输出（硬约束过滤后的路线候选集）；缺失单元标记 missing，不伪造",
        "指标层：PM2.5 暴露（网格/站点融合估计）、噪声 0-100 风险代理、花粉日级背景/代理、目标距离偏差、接驳距离、偏好命中率、数据可靠度、约束通过率、综合评分",
        "统计层：配对比较、均值差、95% bootstrap 置信区间与胜率（标准库实现，seed=1234）",
        "支持状态按 quality_gates.json 预注册阈值判定（supported / partially_supported / unsupported / inconclusive）",
    ]


def _paper_abstract(summary: dict[str, Any], hypothesis: dict[str, str], status_label: str) -> str:
    """确定性摘要：只陈述设计与观测到的指标，不做人群外推。"""
    negative = summary.get("negative_results") or {}
    return (
        "背景与目的：城市健身出行路线选择需同时满足距离约束与环境健康暴露最小化。"
        f"本研究的预注册假设为：{hypothesis.get('statement') or '个性化环境约束可在距离门禁内改善路线环境暴露与偏好匹配'}。"
        "方法：在徐汇区路线目录上，以固定预设画像矩阵与五个预注册变体（B0-B3、M1）执行对照选择实验；"
        "PM2.5 采用网格/站点融合估计，噪声与花粉为代理指标。"
        f"结果：支持状态判定为 {status_label}；"
        f"绕路通过率 {_fmt(summary.get('detour_pass_rate'))}、环境胜率 {_fmt(summary.get('environment_win_rate'))}、"
        f"偏好胜率 {_fmt(summary.get('preference_win_rate'))}；"
        f"无候选单元 {negative.get('no_candidate_cells', 0)} 个、缺失单元 {negative.get('missing_cells', 0)} 个（如实记录）。"
        "结论受限于估计与代理指标，不构成临床或人群层面结论。"
    )


def _results_block(
    context: "WorkflowContext", summary: dict[str, Any], results: dict[str, Any]
) -> dict[str, Any]:
    interpretation = context.read_stage_output("experiment_analysis") or {}
    return {
        "support_status": summary.get("support_status", "inconclusive"),
        "key_rates": {
            key: summary.get(key)
            for key in (
                "detour_pass_rate",
                "environment_win_rate",
                "preference_win_rate",
                "constraint_pass_rate",
                "no_candidate_rate",
                "reference_verification_rate",
                "mean_data_reliability_m1",
            )
        },
        "cells_total": summary.get("cells_total"),
        "cell_status_counts": summary.get("cell_status_counts") or {},
        "comparisons": summary.get("comparisons") or {},
        "negative_results": interpretation.get("negative_results") or [],
        "data_quality_notes": interpretation.get("data_quality_notes") or [],
        "interpretation": interpretation.get("interpretation")
        or summary.get("support_status")
        or "inconclusive",
        "provenance": results.get("provenance") or summary.get("provenance"),
    }


def _reproducibility(context: "WorkflowContext") -> dict[str, Any]:
    manifest = context.manifest
    return {
        "commands": [
            "qwen-harness doctor",
            "qwen-harness run --workflow full-research --goal-file <goal.json> --approval-mode critical --max-iterations 2",
            "qwen-harness validate --scope all",
            f"qwen-harness report {context.run_id}",
        ],
        "workflow": {"name": manifest.workflow_name, "offline": manifest.offline},
        "environment": {
            "python_version": manifest.python_version,
            "platform": manifest.platform,
            "harness_version": manifest.harness_version,
            "model_name": manifest.model_name,
            "temperature": manifest.temperature,
            "seed": manifest.seed,
        },
        "statistics": {"seed": DEFAULT_SEED, "bootstrap_iterations": DEFAULT_BOOTSTRAP_ITERATIONS},
        "config_hashes": dict(manifest.config_hashes),
        "skills_hashes": dict(manifest.skills_hashes),
        "git": {
            "branch": manifest.git_branch,
            "head": manifest.git_head,
            "worktree_clean": manifest.worktree_clean,
        },
    }


def _data_snapshot_hashes(context: "WorkflowContext", results: dict[str, Any]) -> dict[str, str]:
    """数据快照哈希：运行清单模块数据哈希 + 模块执行记录哈希。"""
    hashes: dict[str, str] = dict(context.manifest.module_data_hashes)
    module_hashes = (results.get("data_hashes") or {}).get("modules") or {}
    for key, digest in module_hashes.items():
        if isinstance(digest, str) and digest:
            hashes[key] = digest
    return dict(sorted(hashes.items()))


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.{digits}f}"


def build_scientific_plan(context: "WorkflowContext") -> ScientificPlan:
    """从运行产物组装 ScientificPlan（全部字段可追溯，不伪造引用）。"""
    frame = _problem_frame(context)
    hypothesis = _hypothesis_info(context)
    summary = _metrics_summary(context)
    results = _experiment_results(context)
    plan_block = results.get("plan") or {}
    profiles = results.get("profiles") or []
    status = str(summary.get("support_status", "inconclusive"))
    status_label = {
        "supported": "支持",
        "partially_supported": "部分支持",
        "unsupported": "不支持",
        "inconclusive": "证据不足",
        "error": "执行错误",
    }.get(status, "证据不足")

    problem_statement = str(
        frame.get("problem_statement") or context.goal.question or context.goal.title
    )
    rationale_bits = [
        hypothesis.get("rationale") or "",
        hypothesis.get("mechanism") or "",
        " ".join(frame.get("assumptions") or [])
        if isinstance(frame.get("assumptions"), list)
        else "",
    ]
    rationale = (
        "；".join(bit for bit in rationale_bits if bit)
        or "依据问题界定与证据卡的既定假设生成流程选出候选假设。"
    )

    baselines_payload = results.get("variants_registry") or {}
    baselines = [
        BaselineSpec(
            baseline_id=str(item.get("variant_id", "")),
            name=str(item.get("name", "")),
            selection_rule=str(item.get("selection_rule", "")),
            required_fields=list(item.get("required_fields") or []),
        )
        for item in baselines_payload.get("variants", [])
        if isinstance(item, dict)
    ]
    experiments = PlanExperiments(baselines=baselines, metrics=metric_specs())
    design = context.read_stage_output("experiment_design")
    if isinstance(design, dict):
        try:
            design_plan = ExperimentPlan.model_validate(design)
            experiments = PlanExperiments(
                baselines=design_plan.baselines or baselines,
                metrics=design_plan.metrics or metric_specs(),
            )
        except Exception:  # noqa: BLE001 - 设计输出损坏时回退注册表基线与冻结指标
            context.emit(
                "plan_contract_degraded",
                "experiment_design 输出不符合契约，回退注册表基线",
                status="warning",
            )

    limitations = list(SCIENTIFIC_BOUNDARIES)
    if isinstance(frame.get("scope_boundaries"), list):
        limitations.extend(str(item) for item in frame["scope_boundaries"])
    negative = summary.get("negative_results") or {}
    if negative.get("missing_cells"):
        limitations.append(
            f"存在 {negative['missing_cells']} 个缺少候选输出的单元，相关指标标记缺失（不伪造）"
        )

    return ScientificPlan(
        run_id=context.run_id,
        git_head=context.manifest.git_head or "",
        problem_statement=problem_statement,
        rationale=rationale,
        technical_details=_technical_details(context, plan_block),
        datasets=_datasets(context, results),
        paper_title=PAPER_TITLE,
        paper_abstract=_paper_abstract(summary, hypothesis, status_label),
        methods=_methods(context, len(profiles)),
        experiments=experiments,
        results=_results_block(context, summary, results),
        references=_references(context),
        evidence_map=_evidence_map(context),
        limitations=limitations,
        reproducibility=_reproducibility(context),
        data_snapshot_hashes=_data_snapshot_hashes(context, results),
        generated_at=_utc_now(),
    )


def write_scientific_plan(context: "WorkflowContext", plan: ScientificPlan) -> str:
    context.store.write_json_atomic(PLAN_RELATIVE, plan.model_dump(mode="json"))
    return PLAN_RELATIVE


def stage_handler(context: "WorkflowContext") -> StageResult:
    """可选接线：确定性生成 scientific_plan.json（供 scientific_report 阶段使用）。"""
    warnings: list[str] = []
    if not _metrics_summary(context):
        warnings.append("缺少 metrics_summary：结果块与支持状态降级为证据不足")
    if not _experiment_results(context):
        warnings.append("缺少 experiment_results：画像与技术细节按可得输入降级")
    plan = build_scientific_plan(context)
    write_scientific_plan(context, plan)
    context.emit(
        "scientific_plan_ready",
        f"科研计划已写入 {PLAN_RELATIVE}",
        details={"references": len(plan.references), "evidence_entries": len(plan.evidence_map)},
    )
    return StageResult(
        stage="scientific_report",
        status="passed",
        summary=f"科研计划就绪（引用 {len(plan.references)} 条，证据映射 {len(plan.evidence_map)} 项）",
        output=plan.model_dump(mode="json"),
        artifacts=[PLAN_RELATIVE],
        warnings=warnings,
    )
