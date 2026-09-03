---
name: evaluation-qwen-experiments
description: Hard constraints, five-dimension scoring, candidate export, baseline experiment matrix, Qwen review, and result auditing for evaluation_model_qwen in the AI Scientist harness. Use for environment_health/sport_match/access_convenience/route_quality/interest_service scoring, recommend --offline, the new score-candidates narrow interface, baseline variants B0/B1/B2/B3/M1, support-status gates, or validating score-candidates JSON output.
---

# 评价模块与实验

## Outcome

指导评价模块的硬约束、五维评分、候选导出、基线矩阵、千问审核和结果审计；为 Harness 实验引擎提供完整可行候选与可复现的评分契约。

## When to use

- 运行或解释 `recommend` 推荐链路与五维评分。
- 施工或使用新窄接口 `score-candidates`（实验候选导出）。
- 设计、执行和审计基线实验矩阵（B0–B3、M1）。
- 处理千问服务异常时的 Python 回退与审计。
- 判定支持状态（supported/partially_supported/unsupported/inconclusive）。

## Authoritative files

```text
evaluation_model_qwen/src/evaluation_model_qwen/models.py
evaluation_model_qwen/src/evaluation_model_qwen/constraints.py
evaluation_model_qwen/src/evaluation_model_qwen/scoring.py      # evaluate_risk / score_routes
evaluation_model_qwen/src/evaluation_model_qwen/loaders.py      # load_data
evaluation_model_qwen/src/evaluation_model_qwen/service.py      # recommend / 回退
evaluation_model_qwen/src/evaluation_model_qwen/qwen_client.py
evaluation_model_qwen/src/evaluation_model_qwen/cli.py          # api-check / recommend（score-candidates 施工位置）
evaluation_model_qwen/config/default_weights.json
evaluation_model_qwen/examples/profile_walk.json
evaluation_model_qwen/tests/
```

## Inputs

- 用户画像 `UserProfile`（运动方式、目标距离、区域、敏感项、兴趣偏好、出发点）。
- 权重文件（默认 `config/default_weights.json`）。
- 路线目录 `route_catalog.json` 与环境数据 `environment_dashboard.json`。
- 实验变体配置（Harness `config/experiment_variants.json`），运行前冻结。

## Outputs

- `recommend`：首选 + 备选推荐、推荐理由、风险提醒、审计记录。
- `score-candidates`（新窄接口）：

```json
{
  "profile": {},
  "risk": {},
  "data_generated_at": "...",
  "candidate_count": 0,
  "candidates": [],
  "weights_sha256": "..."
}
```

- 实验结果：原始指标、维度分、数据可靠度、约束状态；统计摘要（中位数、IQR、胜率、配对差值、固定 seed 1234 的 bootstrap 区间）。

## Workflow

1. 先用 `recommend --offline --json` 确认现有链路可复现。
2. 施工 `score-candidates` 时：先写 CLI 失败测试 → 新建 `CandidateScoreResult` → service 层复用 `load_data`/`evaluate_risk`/`score_routes` → 接入 CLI → 补路径/Schema/暂停/无候选/全候选测试。
3. 实验运行冻结画像、权重与环境快照；记录 `weights_sha256`。
4. 对每个画像运行基线矩阵（B0–B3、M1），输出全部可行候选。
5. 计算原始指标与派生指标；统计摘要只用标准库、固定 seed。
6. 按预注册门禁判定支持状态；负结果、无候选、缺失数据进入报告。
7. 用 `python .qoder/skills/evaluation-qwen-experiments/scripts/verify_score_candidates_output.py` 校验输出结构。

## Allowed operations

- 读取评价模块代码、配置、样例画像与测试。
- 运行固定命令（见 Commands）与测试。
- 新增 `score-candidates` 接口与其测试（属于已批准的最小仓库接线）。
- 不复制 `score_routes` 逻辑；不修改 `recommend` 现有行为。
- 实验需要千问审核时通过子进程环境变量覆盖 `QWEN_MODEL=qwen3.8-max`，不修改模块 `.env`。

## Commands

```powershell
uv run --directory evaluation_model_qwen evaluation-model-qwen api-check
uv run --directory evaluation_model_qwen evaluation-model-qwen recommend --profile examples/profile_walk.json --offline --json

# 新窄接口（施工后）
uv run --directory evaluation_model_qwen evaluation-model-qwen score-candidates `
  --profile <profile.json> --weights <weights.json> `
  --route-catalog <route_catalog.json> --environment-dashboard <environment_dashboard.json> --json

# 模块验证
uv run --directory evaluation_model_qwen --extra dev pytest -q
uv run --directory evaluation_model_qwen --extra dev ruff check .

# 输出结构自检
python .qoder/skills/evaluation-qwen-experiments/scripts/verify_score_candidates_output.py <output.json>
```

## Quality gates

- 五个维度齐全：`environment_health`、`sport_match`、`access_convenience`、`route_quality`、`interest_service`。
- Python 负责硬约束、风险暂停和基础分；Qwen 只审核候选与生成解释，不重算硬约束、不修改候选 ID。
- `score-candidates` 复用 `load_data`/`evaluate_risk`/`score_routes`，返回全部通过硬约束的候选（保留排序和维度分），不调用 Qwen，不改变 `recommend`。
- 基线规则由 Harness 预注册，模型无法临时改动。
- 结果同时报告原始指标、维度分、数据可靠度和约束状态；综合效用不作为唯一验证指标。
- 权重变化记录 before/after。
- 千问服务异常时保留 Python 结果和完整审计。

## Failure handling

- 千问服务异常：自动回退本地 Python 排序，返回推荐并记录降级。
- 风险暂停（降水、体感温度、阵风、AQI 超阈值）：输出暂停结论，不强行推荐。
- 环境数据过期或 `status=error/no_data`：按 `status_reliability`/`confidence_reliability` 降权并标记；不隐藏。
- 无候选：如实报告无候选率，不编造路线。
- 实验指标无改善或数据质量下降：按反馈规则停止迭代。

## Stop conditions

- 实验逻辑复制 `score_routes`。
- Qwen 输出修改硬约束或候选 ID。
- 评价使用过期数据却未标记。
- 最终结论只依据 `base_score`。
- 权重变化未记录 before/after。
- 预设画像案例被解释为独立人群样本或外推临床结论。

## Handoff

报告：接口状态（`recommend` 与 `score-candidates`）、实验变体与冻结快照、各画像候选数与约束通过率、原始/派生指标、统计摘要、支持状态与门禁对照、千问调用与回退记录、剩余风险。细节见：

- [references/scoring-contract.md](references/scoring-contract.md)：硬约束、五维评分、可靠度
- [references/score-candidates-contract.md](references/score-candidates-contract.md)：新窄接口契约与施工顺序
- [references/experiment-matrix.md](references/experiment-matrix.md)：基线、指标与支持门禁
