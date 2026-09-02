"""实验矩阵与结果解释（设计文档 01 §16）。

- ``profiles``：10 个固定预设画像案例（步行/跑步/骑行 × 健康/景观/便利/均衡）
  与目标时间解析（快照时间 + 固定偏移，兼容 evaluation_model_qwen UserProfile）；
- ``variants``：五个预注册变体（B0-B3 基线 + M1 个性化约束）与冻结选择规则，
  注册表来自 ``config/experiment_variants.json``；
- ``metrics``：暴露与代理指标（PM2.5 网格/站点融合估计、噪声 0-100 风险代理、
  花粉日级背景/代理、目标距离偏差、接驳距离、偏好命中率、数据可靠度、约束通过率、
  综合评分）——结果口径不依赖单一 base_score；
- ``statistics``：seed=1234 的确定性统计（配对比较、均值差、95% bootstrap CI、胜率）
  与 metrics_summary 聚合（支持状态复用冻结门禁口径）；
- ``runner``：``experiment_analysis`` 阶段处理器，产出
  ``experiments/experiment_results.json`` 与 ``metrics_summary.json``
  （同时写入 ``reports/`` 供 ResultGate 读取）。

预设画像为固定案例矩阵，不解释为独立人群样本，不外推临床或人群结论；
缺失数据一律如实标记（missing / no_candidate），不伪造。
"""

from __future__ import annotations

from . import metrics, profiles, statistics, variants
from .metrics import (
    DIMENSION_NAMES,
    CellMetrics,
    composite_env_risk,
    compute_cell_metrics,
    constraint_checks,
    metric_specs,
    pm25_risk_normalized,
    preference_hit_rate,
)
from .profiles import (
    PRESET_CASES,
    dump_profiles_json,
    ensure_case_coverage,
    render_case_profiles,
    resolve_target_time,
)
from .runner import MODULE_KEYS, stage_handler
from .statistics import (
    DEFAULT_BOOTSTRAP_ITERATIONS,
    DEFAULT_SEED,
    aggregate_summary,
    bootstrap_ci,
    build_interpretation,
    experiment_summary_payload,
    paired_comparison,
    summary_stats,
    win_rate,
)
from .variants import (
    VARIANT_IDS,
    VariantSpec,
    apply_selection_rule,
    candidate_env_risk,
    load_experiment_variants,
    validate_plan_against_registry,
)

__all__ = [
    "DEFAULT_BOOTSTRAP_ITERATIONS",
    "DEFAULT_SEED",
    "DIMENSION_NAMES",
    "MODULE_KEYS",
    "PRESET_CASES",
    "VARIANT_IDS",
    "CellMetrics",
    "VariantSpec",
    "aggregate_summary",
    "apply_selection_rule",
    "bootstrap_ci",
    "build_interpretation",
    "candidate_env_risk",
    "composite_env_risk",
    "compute_cell_metrics",
    "constraint_checks",
    "dump_profiles_json",
    "ensure_case_coverage",
    "experiment_summary_payload",
    "load_experiment_variants",
    "metric_specs",
    "metrics",
    "paired_comparison",
    "pm25_risk_normalized",
    "preference_hit_rate",
    "profiles",
    "render_case_profiles",
    "resolve_target_time",
    "stage_handler",
    "statistics",
    "summary_stats",
    "validate_plan_against_registry",
    "variants",
    "win_rate",
]
