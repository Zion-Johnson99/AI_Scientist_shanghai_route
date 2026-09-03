# Snapshot Files

快照文件清单（对应 01 设计文档 §15.3）。部分文件在首次刷新前可能缺失；Adapter 返回 `partial` 并列出缺失项。

## 环境模块导出（`weather_api_data/runtime/exports/`）

```text
environment_latest.json          # 当前天气、AQI、生活指数、预警
environment_hourly.json          # 未来 24 小时逐小时序列
grid_environment_latest.json     # 54 个约 1 km 网格的环境量
pollen_grid_scores.json          # 网格花粉日级背景
noise_segments.json              # 约 100 m 路段噪声风险代理
route_environment.json           # 90 条路线的暴露汇总
```

## 网页数据包

```text
xuhui_route_builder/data/web/environment_dashboard.json
```

## dashboard 顶层结构

```text
current     # 当前天气、AQI、生活指数、预警
forecast    # 未来 24 小时逐小时序列
grids       # 网格环境（count / items / status）
metadata    # schema_version、generated_at、status、stale_reason、source_files 等
routes      # count / items / status；items 覆盖 90 条路线
```

## 路线环境条目字段

每个 `routes.items[]` 含：`route_id`、`status`、`pm2_5`、`noise`、`pollen_daily`、`access_route_environment`、`segment_count`、`total_length_m`。

- `pm2_5` / `noise`：对象，含 `business_time`、`status`、`spatial_scale`、`estimated`、`confidence`、`unit`、`value`、`coverage_ratio`、`fetched_at`、`expires_at`、`source`。
- `pollen_daily`：按日对象数组，字段同上。
- `access_route_environment`：接驳路径环境，当前为 `not_computed` / `not_aggregated`。

## 用途

- 实验引擎读取路线环境作为评分输入。
- 网页读取 `environment_dashboard.json` 展示环境面板与路线详情。
- Harness 快照复制这些文件到 run 目录并记录 SHA256。
