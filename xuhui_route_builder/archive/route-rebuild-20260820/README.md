# 2026-08-20 路线重建历史归档

本目录保存步行、跑步和骑行路线逐条修复期间使用的专项脚本及回归测试，便于追溯 90 条路线的形成过程。

## 归档原因

- 重建脚本包含指定路线 ID、当日距离范围和逐条修复参数。
- 部分脚本依赖本地浏览器目标 ID、Playwright CLI 缓存和 8123 端口。
- 基线、终验和途经点同步按运动模式分别实现，存在较多重复结构。
- 对应测试服务于历史修复批次，未覆盖当前正式命令链的公共接口。

## 当前正式入口

正式路线工作流见 `xuhui_route_builder/tools/README.md`，核心入口包括：

1. `cache-route-batch`
2. `generate-routes`
3. `validate-routes`
4. `route_quality_gate.py`
5. `route_portfolio_gate.py`
6. `merge-service-pois`

正式入口读取路线种子和当前数据契约，批量限制、失败保护、几何门禁及 POI 发布逻辑均位于包内源码和项目技能脚本。

## 使用边界

- 本目录不参与默认 pytest 发现和正式发布。
- 本目录保留在 `zjx_route`，不进入 `develop`。
- 浏览器目标 ID、API 密钥、代理进程和运行缓存不写入归档。
- 需要追查某条路线的历史修复过程时，可结合 Git 提交记录阅读对应脚本和测试。
