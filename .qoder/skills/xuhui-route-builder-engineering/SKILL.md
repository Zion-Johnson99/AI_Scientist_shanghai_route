---
name: xuhui-route-builder-engineering
description: Module-level engineering for xuhui_route_builder (90 accepted Xuhui walk/run/bike routes) in the AI Scientist harness. Use for route data contracts, validate-seeds/validate-routes/export-candidates commands, RouteModuleResult, route snapshots and hashing, Harness RouteBuilderAdapter operations and permissions, catalog/GeoJSON ID consistency, or coordinating with optimize-xuhui-routes for geometry and POI defects.
---

# 路线模块工程

## Outcome

让 Harness 安全地读取、验收、快照和按需维护路线模块，并向实验引擎提供稳定的 90 条路线契约。科研运行默认只读与验收，不生成新路线。

## When to use

- Harness 路线 Adapter 的预检、快照、验收命令与结果解释。
- 路线目录、GeoJSON、入口、POI、接驳样例的数据契约检查。
- 路线模块命令的使用与权限判断。
- 发现具体路线几何/重复/距离带/POI/视觉缺陷时，同时加载本 Skill 与 `optimize-xuhui-routes`：本 Skill 管接口与契约，`optimize-xuhui-routes` 管 90 条路线的深度修复规则。

## Authoritative files

```text
xuhui_route_builder/src/xuhui_route_builder/models.py
xuhui_route_builder/src/xuhui_route_builder/validation.py
xuhui_route_builder/src/xuhui_route_builder/cli.py
xuhui_route_builder/data/web/route_catalog.json
xuhui_route_builder/data/web/xuhui_routes.geojson
xuhui_route_builder/data/web/xuhui_entries.geojson
xuhui_route_builder/data/web/poi_catalog.json
xuhui_route_builder/data/web/access_cases.json
xuhui_route_builder/tests/
.qoder/skills/optimize-xuhui-routes/
```

## Inputs

- 操作 ID（见 Allowed operations 表）。
- 路线目录路径（默认 `xuhui_route_builder/data/web/`）。
- 是否允许网络。
- Adapter 内部模块写入授权：只接受显式工作流操作来源，不接受 CLI 通用开关。
- run 输出目录（`runtime/runs/<run-id>/modules/route/`）。

## Outputs

`RouteModuleResult`（写入 `modules/route/result.json`）：

- 总路线数与模式分布（90；walk/run/bike 各 30）。
- 验收状态分布（`validation_status`）。
- 距离带分布。
- 几何与目录 ID 一致性。
- 数据文件哈希（SHA256）。
- 命令审计（`CommandAudit` 列表）。
- 警告和阻塞项。

## Workflow

1. 读取权威文件，确认数据文件存在且可解析。
2. 运行预检：文件存在、90 条、三模式各 30、目录与 GeoJSON 的 `route_id` 一致、`validation_status`/`geometry_status`/坐标字段满足契约。
3. 运行 `python .qoder/skills/xuhui-route-builder-engineering/scripts/verify_route_catalog.py` 记录基线。
4. 按操作 ID 执行命令；每次命令记录 `CommandAudit`。
5. 快照稳定产物：复制数据文件到 run 目录并记录 SHA256 与 Git HEAD。
6. 汇总警告与阻塞项，输出 `RouteModuleResult`。

## Allowed operations

| 操作 ID | 命令 | 默认权限 |
| --- | --- | --- |
| `route_snapshot` | 读取并哈希稳定产物 | 允许 |
| `route_validate_seeds` | `xuhui-route-builder validate-seeds` | 允许 |
| `route_validate_routes` | `xuhui-route-builder validate-routes` | 需要网络时显式授权 |
| `route_export_candidates` | `xuhui-route-builder export-candidates` | v1 禁用 |
| `route_generate` | `xuhui-route-builder generate-routes` | 高风险，v1 默认禁用 |

修改边界：

- 科研运行默认不生成路线；实验使用稳定的 90 条路线快照。
- 路线修复先写测试，再修改种子、生成或验证逻辑。
- 不为命中 POI 改变路线几何。
- 保留 GCJ-02 与 WGS84 的明确声明；边界/距离/最近路线计算前统一坐标系。

## Commands

```powershell
uv run --directory xuhui_route_builder --frozen xuhui-route-builder validate-seeds
uv run --directory xuhui_route_builder --frozen xuhui-route-builder validate-routes
uv run --directory xuhui_route_builder --frozen xuhui-route-builder export-candidates
uv run --directory xuhui_route_builder --frozen --extra dev pytest -q
node --test xuhui_route_builder/tests/*.test.mjs

# 数据契约自检
python .qoder/skills/xuhui-route-builder-engineering/scripts/verify_route_catalog.py
```

## Quality gates

- 90 条路线；每种模式 30 条（`route_mode` 为 walk/run/bike）。
- 路线目录与 GeoJSON 的 `route_id` 一致且无重复。
- 全部路线 `validation_status == accepted`。
- 选中最优路线存在且通过验收。
- 快照记录 SHA256 与 Git HEAD。
- 模式级交接前通过 `optimize-xuhui-routes` 的 portfolio gate（几何、距离带、形状平衡、重复、占位名）。

## Failure handling

- 数据文件缺失或不可解析：`status=error`，列出缺失项，不继续后续操作。
- 路线数或模式分布不符：阻塞，报告差异；不自动重生成。
- 几何验收失败：路线退回骨干设计（见 `optimize-xuhui-routes`），先于 POI 与显示工作。
- 网络命令（`validate-routes` 涉及在线核验）未获授权：标记 `skipped` 并说明原因。
- 上游地图服务 429/超时簇：停止该来源，保留路线 ID、参数、缓存状态和错误上下文。

## Stop conditions

- 路线数、距离带、形状平衡、重复或占位名不匹配，阻塞模式交接。
- 需要 `route_export_candidates` 或 `route_generate` 但 v1 已禁用——上报而不是绕过。
- 出现用修改几何来凑 POI 命中的改动。
- 坐标系声明缺失或混用未转换。
- 视觉验收存疑的路线仍标 `accepted`（应为 `needs_review`）。

## Handoff

报告：模式分布、验收状态、距离带分布、目录/几何 ID 一致性、数据哈希、命令审计、警告与阻塞项、快照路径与 Git HEAD。深度几何与 POI 问题的处置记录随 `optimize-xuhui-routes` 一并交接。细节见：

- [references/route-data-contract.md](references/route-data-contract.md)：数据文件与字段契约
- [references/module-operations.md](references/module-operations.md)：操作 ID、权限与快照规则
- [references/failure-modes.md](references/failure-modes.md)：常见失败与处置
