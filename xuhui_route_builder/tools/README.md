# 路线重建与验收主链路

比赛交付采用包内源码和项目级质量门禁。正式链路为：路线种子 → 路径缓存或在线生成 → 几何验证 → 组合验收 → 真实 POI 合并 → Web 数据。

## 源码职责

| 阶段 | 正式源码 | 输入与输出 |
| --- | --- | --- |
| 路线种子 | `data/seeds/route_seeds.json`、`routes.py` | 读取真实入口、途经点、运动模式和路线形态 |
| 浏览器路径缓存 | `js_route_cache.py` | 按最多 5 条路线缓存高德 JS 步行或骑行分段响应 |
| 路线生成 | `cli.py`、`routes.py` | 生成 `data/interim/pilot_candidates.json` |
| 几何验证 | `validation.py`、`route_quality_gate.py` | 检查边界、距离、折返、分支、自交和环线拓扑 |
| 组合验收 | `route_portfolio_gate.py` | 检查三种运动各 30 条、距离档、路线形态和 POI 审计 |
| POI 发布 | `service_pois.py`、`exporters.py` | 合并已核验 POI，更新 Web 路线与 POI 目录 |

包内源码位于 `src/xuhui_route_builder`。两级质量门禁位于仓库根目录 `.agents/skills/optimize-xuhui-routes/scripts`。

## 正式命令

以下命令从仓库根目录执行：

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist
$routePython = ".\xuhui_route_builder\.venv\Scripts\python.exe"
$env:PYTHONPATH = ".\xuhui_route_builder\src"
```

先检查 90 条路线种子：

```powershell
& $routePython -m xuhui_route_builder.cli validate-seeds
```

默认生成流程读取 `.env` 中的高德 WebService Key，并复用 `data/raw/amap` 缓存：

```powershell
& $routePython -m xuhui_route_builder.cli generate-routes
& $routePython -m xuhui_route_builder.cli validate-routes
```

需要通过已加载高德 JS API 的浏览器补充原始分段缓存时，使用最多 5 条路线一批的命令：

```powershell
& $routePython -m xuhui_route_builder.cli cache-route-batch `
  --target-id "浏览器目标ID" `
  --route-id XH_RUN_0031 `
  --route-id XH_RUN_0032 `
  --proxy-url http://127.0.0.1:3456
```

该入口依赖本地 CDP 代理和已经加载高德地图的浏览器页面。目标 ID、代理进程和浏览器状态属于本地运行环境，不写入仓库。

对最终验证数据运行几何质量门禁：

```powershell
& $routePython .\.agents\skills\optimize-xuhui-routes\scripts\route_quality_gate.py `
  .\xuhui_route_builder\data\processed\pilot_validated.json
```

随后运行完整组合验收：

```powershell
& $routePython .\.agents\skills\optimize-xuhui-routes\scripts\route_portfolio_gate.py `
  .\xuhui_route_builder\data\processed\pilot_validated.json `
  --web-catalog .\xuhui_route_builder\data\web\route_catalog.json `
  --require-all-accepted `
  --require-poi-audit-clean
```

新的核验 POI 文档放入 `data/interim/poi` 后执行发布：

```powershell
& $routePython -m xuhui_route_builder.cli merge-service-pois
```

`merge-service-pois` 只接收带稳定来源且核验状态为 `verified` 的 POI，并保持 POI 信息与导航几何分离。

## 失败处理

- 任一路线几何门禁失败时，停止组合验收和 Web 发布。
- 浏览器缓存命令拒绝超过 5 条的批次，并对无效响应进行一次重试。
- POI 缺少稳定来源或核验状态时，保留真实空结果。
- 发布写入使用临时文件和替换操作；失败时保留上一版正式数据。

## 自动测试

```powershell
cd .\xuhui_route_builder
.venv\Scripts\python.exe -m pytest tests -q
node --test tests/*.test.mjs
```

默认测试覆盖路径缓存、路线生成、拓扑门禁、事务化发布、POI 合并、Web 数据契约和导航交互。历史逐条修复脚本不参与正式测试发现。
