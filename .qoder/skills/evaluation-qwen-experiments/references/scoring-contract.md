# Scoring Contract

## 职责边界

- Python 负责：硬约束过滤、风险暂停判定、五维基础分、数据可靠度降权、候选排序。
- Qwen 只负责：审核候选与生成自然语言解释；不重算硬约束，不修改候选 ID 或分数。
- 千问服务异常：回退本地 Python 排序，保留推荐结果与完整审计。

## 五维评分

维度顺序固定（与 `scoring.py` 一致）：

1. `environment_health`
2. `sport_match`
3. `access_convenience`
4. `route_quality`
5. `interest_service`

权重来自 `config/default_weights.json` 的 `goal_weights`（按目标意图：`balanced`、`health_environment`、`distance_training`、`relax`、`scenery`、`family`、`nearby`）。

## 环境子权重与健康分

- `environment_weights`：`pm2_5=45`、`noise=35`、`pollen=20`。
- 敏感项加成：`sensitivity_boost=30`。
- 缺指标默认分：`missing_metric_score=50.0`。
- 核心兴趣权重下限：`core_interest_weight_floor=60.0`。

## 数据可靠度

| 机制 | 取值 |
| --- | --- |
| `status_reliability` | `ok=1.0`、`partial=0.7`、`stale=0.0`、`no_data=0.0`、`error=0.0` |
| `confidence_reliability` | `high=1.0` … `low=0.5`（含中文别名） |
| `estimated_reliability` | `0.9` |

可靠度用于降权与标记；`stale`/`error` 数据不得静默参与排序。

## 风险暂停阈值（`risk_thresholds`）

- 降水：警告 2.5 mm，暂停 10.0 mm。
- 体感温度：警告 35°C，暂停 40°C。
- 阵风：警告 40 km/h，暂停 62 km/h。
- AQI：警告 100，敏感人群暂停 150，全员暂停 200。
- 预警惩罚：蓝色 8 分、黄色 15 分。

命中暂停阈值时输出暂停结论，不强行推荐。

## 表述边界

- 最优路线 = 当前候选集中的约束最优，不宣称全路网全局最优。
- PM2.5 为网格/站点融合估计；花粉为日级背景/代理；噪声为 0-100 风险代理，非实时分贝。
