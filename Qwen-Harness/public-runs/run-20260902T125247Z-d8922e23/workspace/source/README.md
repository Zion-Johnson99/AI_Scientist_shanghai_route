# 徐汇健康路线 · 第二轮独立工程

本目录是 Qwen-Harness 第二轮实验（`run-20260902T125247Z-d8922e23`）中从零构建的独立工程副本，
不引用仓库现有 `xuhui_route_builder`、`weather_api_data`、`evaluation_model_qwen`
的任何实现、数据或页面代码。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `routes/` | 路网图构建、闭环与单程搜索、几何度量、质量门禁、路线目录产物 |
| `environment/` | 54 格环境网格、公开气象与空气质量接入、路线暴露聚合、契约校验 |
| `evaluation/` | 五维打分、确定性推荐、两条基线、实验矩阵指标、本地评价 API |
| `xuhui_route_builder/` | 路线模块根，`data/web/` 存放路线与环境产物 |
| `weather_api_data/` | 环境数据项目根与适配器 |
| `evaluation_model_qwen/` | 评价项目根，`config/default_weights.json` 为默认权重 |
| `web/` | 完整本地网页产品，零外部依赖 |
| `scripts/` | 生成、质量门禁、本地服务、浏览器验收脚本 |
| `tests/` | 跨模块集成测试 |
| `node/` | Node 契约测试 |
| `harness_copy/` | Qwen-Harness 运行副本与离线复现入口 |

## 复现

```powershell
cd workspace/source
python reproduce.py --stage all
```

分阶段：`--stage routes|environment|evaluation|web|checks`。

## 本地网页

```powershell
pwsh ../../publish/launch-local.ps1
```

或手动：

```powershell
cd ../../publish/local-product
python -m http.server 8765
```

浏览器打开 <http://127.0.0.1:8765/index.html>。

## 边界

- 全部计算离线、确定性，无随机数、无付费大模型调用。
- 公开数据来源、访问时间、用途与许可记录在 `../../sources/source_registry.jsonl`。
- 环境噪声为确定性代理量（`dB_proxy`），不是实测声级。
- 接驳时间为直线距离乘 1.35 绕行系数的估算，未调用任何在线路径规划接口。
