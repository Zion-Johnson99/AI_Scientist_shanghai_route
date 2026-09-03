# score-candidates Contract

新增窄接口，用于实验候选导出。返回全部通过硬约束的可行候选，供实验矩阵使用。

## 命令

```powershell
uv run --directory evaluation_model_qwen evaluation-model-qwen score-candidates `
  --profile <profile.json> `
  --weights <weights.json> `
  --route-catalog <route_catalog.json> `
  --environment-dashboard <environment_dashboard.json> `
  --json
```

## 输出 JSON 结构

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

- `profile`：解析后的用户画像。
- `risk`：`evaluate_risk` 的风险评估（含暂停状态）。
- `data_generated_at`：环境数据生成时间。
- `candidate_count`：等于 `candidates` 长度。
- `candidates`：全部通过硬约束的候选，保留排序和维度分。
- `weights_sha256`：权重文件 SHA256，用于实验冻结与审计。

## 实现要求

- 复用现有 `load_data`（`loaders.py`）、`evaluate_risk`、`score_routes`（`scoring.py`）。
- 不复制评分逻辑。
- 不调用 Qwen。
- 不改变现有 `recommend` 行为。
- 新增 Pydantic 输出模型 `CandidateScoreResult` 和测试。

## 施工顺序

1. 先为当前缺口增加 CLI 失败测试。
2. 新建 `CandidateScoreResult`。
3. 增加 service 层函数，复用已有评分。
4. 接入 CLI。
5. 添加路径、Schema、暂停、无候选和全候选测试。

## 实验使用

- 每次实验冻结画像、权重与环境快照，并记录 `weights_sha256`。
- 基线与模型在同一候选集上比较。
- 千问审核需要时通过子进程环境变量覆盖 `QWEN_MODEL=qwen3.8-max`，不修改模块 `.env`。
