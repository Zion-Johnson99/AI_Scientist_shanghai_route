---
name: weather-environment-pipeline
description: Pre-flight, refresh, read, and interpret multi-source environment data in weather_api_data (weather, AQI, fused PM2.5 grid, pollen, noise proxy, route exposure) for the Shanghai Xuhui healthy-route AI Scientist. Use for config-check/dry-run/scheduled-refresh tiers/publish-web commands, environment snapshots, partial/stale/estimated semantics, last-known-good fallback, environment_dashboard.json validation, or the Harness EnvironmentDataAdapter.
---

# 多源环境数据流水线

## Outcome

让 Harness 能预检、刷新、读取和正确解释天气、AQI、PM2.5、花粉、噪声与路线暴露数据；所有报告保留数据语义字段，缺数据时如实标记而不造数。

## When to use

- 运行环境模块预检（`config-check`、`dry-run`）与分层刷新。
- 读取或校验环境快照与 `environment_dashboard.json`。
- 解释 PM2.5/花粉/噪声数据的语义与限制。
- 处理缺 Key、上游异常、`partial`/`stale` 回退。
- Harness EnvironmentDataAdapter 的快照与预检行为。

## Authoritative files

```text
weather_api_data/src/weather_api_data/cli.py
weather_api_data/src/weather_api_data/pipeline.py
weather_api_data/src/weather_api_data/pm25_fusion.py
weather_api_data/src/weather_api_data/pollen_model.py
weather_api_data/src/weather_api_data/noise_model.py
weather_api_data/src/weather_api_data/route_environment.py
weather_api_data/src/weather_api_data/web_export.py
weather_api_data/config/
weather_api_data/tests/
weather_api_data/runtime/exports/
xuhui_route_builder/data/web/environment_dashboard.json
```

## Inputs

- 刷新层级：`weather`、`hourly`、`daily`（需要网络与对应 Key）或 `none`（使用 last-known-good）。
- 环境授权状态：是否允许网络、是否缺 Key。
- 快照路径：见 [references/snapshot-files.md](references/snapshot-files.md)。
- 校验对象：`environment_dashboard.json`（默认）或指定路径。

## Outputs

- 刷新产物：`weather_api_data/runtime/exports/` 下的 JSON 快照（见 references/snapshot-files.md）。
- 网页数据包：`xuhui_route_builder/data/web/environment_dashboard.json`（`publish-web` 生成）。
- `ModuleResult`（`modules/environment/result.json`）：status、输入/输出产物、数据哈希、命令审计、警告与错误；部分文件缺失时返回 `partial` 并列出缺失项。
- 所有报告保留字段：`business_time`、`valid_until`、`status`、`spatial_scale`、`estimated`、`confidence`、`unit`。

## Workflow

1. 先 `config-check`，再 `dry-run`；两者通过后才刷新。
2. 按授权层级执行 `scheduled-refresh --tier ...`；无网络或无 Key 时使用最近一份有效快照并记录原因。
3. 刷新后执行 `publish-web` 生成网页数据包。
4. 运行 `python .qoder/skills/weather-environment-pipeline/scripts/verify_environment_snapshot.py` 校验 dashboard。
5. 实验迭代冻结当前环境快照；后续需要新快照时显式记录新旧哈希与原因。
6. 报告中逐项保留数据语义字段，缺失如实标记。

## Allowed operations

- 读取 `weather_api_data/runtime/exports/` 与 `xuhui_route_builder/data/web/` 产物。
- 执行固定命令（见 Commands）；命令以 `cli.py` 实际子命令为准。
- 复制快照到 run 目录并记录哈希。
- 不修改模块源码；不手动编辑共享数据文件（单一写入者为 `publish-web`）。
- 网络调用仅在显式授权后执行，并记录调用状态、重试和错误。

## Commands

```powershell
uv run --directory weather_api_data --frozen weather-api-data config-check
uv run --directory weather_api_data --frozen weather-api-data dry-run
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier weather
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier hourly
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier daily
uv run --directory weather_api_data --frozen weather-api-data publish-web

# dashboard 快照自检
python .qoder/skills/weather-environment-pipeline/scripts/verify_environment_snapshot.py
```

## Quality gates

- `config-check` 与 `dry-run` 先于刷新执行。
- dashboard 顶层含 `current`、`forecast`、`grids`、`metadata`、`routes`；`routes` 覆盖 90 条路线且 `route_id` 与路线目录一致。
- 时间字段（`generated_at`、`business_time`、`fetched_at`）可解析；`status` 在枚举内。
- 每个环境块带单位与 `estimated` 标记；缺失率被计算并报告。
- 快照与报告中不含绝对路径、Key 或其他敏感字段。
- 缺 Key 时使用 last-known-good，不创建填充值；`partial`/`stale`/`estimated` 如实标记。

## Failure handling

- 缺 Key：使用 last-known-good 快照，status 记 `stale`/`partial` 并给出 `stale_reason`，不创建伪数据。
- 上游异常：记录错误类型、来源、尝试次数与回退快照。
- API 硬限额、429、超时簇：触发停止，保留参数与错误上下文。
- 部分文件缺失（首次刷新前）：返回 `partial` 并列出缺失项。
- 未来 PM2.5 缺值：保留缺值，不从 AQI 反推浓度。

## Stop conditions

- API 硬限额、429 或超时簇出现。
- 需要创建填充值或伪数据才能继续。
- 刷新未获网络授权却被要求联网。
- 快照包含绝对路径或敏感字段。
- 输出把网格 PM2.5 说成道路实测值，或把 0-100 噪声代理说成实时分贝。

## Handoff

报告：刷新层级与结果状态；快照文件清单与哈希；缺失率与缺失字段；回退行为与 `stale_reason`；命令审计；`verify_environment_snapshot.py` 结果；剩余风险。数据语义细节见：

- [references/data-semantics.md](references/data-semantics.md)：PM2.5/花粉/噪声语义与报告字段
- [references/refresh-fallback.md](references/refresh-fallback.md)：刷新层级、网络与回退规则
- [references/snapshot-files.md](references/snapshot-files.md)：快照文件清单
