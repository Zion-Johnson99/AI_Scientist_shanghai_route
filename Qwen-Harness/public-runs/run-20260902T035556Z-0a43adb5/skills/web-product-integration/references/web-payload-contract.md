# Web Payload Contract

发布文件：`xuhui_route_builder/data/web/research_harness_latest.json`（由 `qwen-harness publish <run-id>` 在 PublishGate 通过后原子写入）。

## Schema（01 设计文档 §19.3）

```json
{
  "schema_version": "1.0",
  "run_id": "...",
  "generated_at": "...",
  "status": "supported",
  "research_question": "...",
  "hypothesis": "...",
  "selected_route": {
    "route_id": "...",
    "route_name": "...",
    "reason": "..."
  },
  "key_metrics": [],
  "baseline_comparison": [],
  "iterations": [],
  "references": [],
  "limitations": [],
  "artifacts": []
}
```

## 字段规则

- `status`：`supported` | `partially_supported` | `unsupported` | `inconclusive`。
- `selected_route.route_id` 必须存在于当前 `route_catalog.json`；结论表述为“当前候选集中的约束最优路线”。
- `key_metrics` / `baseline_comparison` / `iterations`：脱敏摘要与关键指标；基线对比含变体 ID（B0–B3、M1）。
- `references`：引用链接，HTTPS 或明确本地来源。
- `limitations`：数据限制与代理变量说明（网格估计、0-100 噪声代理、候选集边界）。
- `artifacts`：只放仓库相对路径或公开 URL。

## PublishGate 检查

- `scientific_plan.json` 通过 Schema。
- 网页 payload 无敏感信息和绝对路径。
- 选中路线 ID 存在于当前 `route_catalog.json`。
- 引用 URL 为 HTTPS 或明确本地来源。
- 前端契约测试通过。

## 页面行为

- 数据文件存在且通过 Schema：展示“AI Scientist 实验”入口。
- 数据缺失或状态为错误：隐藏入口，不影响地图与推荐。
- 页面禁止展示本地绝对路径、模型密钥、内部日志和完整自由文本。
