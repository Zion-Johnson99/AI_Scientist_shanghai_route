# Module Operations

## 操作 ID 与权限

| 操作 ID | 命令 | 默认权限 |
| --- | --- | --- |
| `route_snapshot` | 读取并哈希稳定产物 | 允许 |
| `route_validate_seeds` | `xuhui-route-builder validate-seeds` | 允许 |
| `route_validate_routes` | `xuhui-route-builder validate-routes` | 需要网络时显式授权 |
| `route_export_candidates` | `xuhui-route-builder export-candidates` | v1 禁用 |
| `route_generate` | `xuhui-route-builder generate-routes` | 高风险，v1 默认禁用 |

写入授权只来自显式工作流操作（操作 ID），不接受 CLI 通用开关（v1 不公开 `--allow-module-write`）。

## 快照规则（route_snapshot）

1. 复制以下稳定产物到 `runtime/runs/<run-id>/modules/route/snapshot/`（或记录路径与哈希）：
   `route_catalog.json`、`xuhui_routes.geojson`、`xuhui_entries.geojson`、`poi_catalog.json`、`access_cases.json`。
2. 记录每个文件的 SHA256 与当前 Git HEAD。
3. 实验迭代复用同一快照；需要新快照时显式记录原因与新哈希。

## RouteModuleResult 汇总项

- 总路线数与模式分布。
- 验收状态分布。
- 距离带分布。
- 几何与目录 ID 一致性。
- 数据哈希。
- 命令审计（`CommandAudit`）。
- 警告和阻塞项。

## 预检清单

- 文件存在、JSON/GeoJSON 可解析。
- 路线数为 90。
- `walk`、`run`、`bike` 各 30。
- 路线 ID 与 GeoJSON 一致。
- `validation_status`、`geometry_status` 和坐标字段满足现有契约。

## 深度修复分工

具体路线几何、重复、距离带、POI、视觉缺陷的修复规则由 `optimize-xuhui-routes` 负责；本 Skill 只负责接口、契约、命令与 Adapter 行为。两者同时加载时以 `optimize-xuhui-routes` 的数值门禁为准。
