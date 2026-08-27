# 面向上海城市户外运动的健康路线决策 AI Scientist

_徐汇区本地路线原型与多源环境数据说明，更新于 2026-08-27。_

---

## 当前能力

| 模块 | 状态 | 当前结果 |
| --- | --- | --- |
| 路线与 POI | 已完成 | 步行、跑步、骑行各 30 条，共 90 条已验收路线 |
| 本地地图与导航 | 已完成 | 支持筛选、路线展示、地点输入、地图点选、步行或骑行接驳和网页内导航 |
| 多源环境数据 | 已接入 | 和风天气、上海空气质量站点、CHAP PM2.5、Google 花粉和噪声代理已形成统一刷新与本地历史链路 |
| 环境网页展示 | 已接入 | 展示当前天气、AQI、预警、生活指数、24 小时天气与 AQI，以及 54 个环境网格和 90 条路线的 PM2.5、花粉、噪声结果 |
| 个性化排序 | 待完成 | 当前展示单项环境暴露，指标权重、多目标排序和推荐解释仍在开发 |
| AI Scientist 工作流 | 待完成 | 已保留 Agent 输入输出边界，假设、实验、验证和结果记录尚待串联 |
| 在线部署 | 暂停 | 当前采用团队成员本地运行方式 |

## 本地打开网页

当前工作树已有 `xuhui_route_builder/data/web/environment_dashboard.json` 时，执行：

```powershell
cd .\xuhui_route_builder
python -m http.server 8123
```

访问 [http://127.0.0.1:8123/web/](http://127.0.0.1:8123/web/)。高德 Key 的首次配置见 [徐汇路线构建器说明](./xuhui_route_builder/README.md)。

环境数据包缺失或需要更新时，先按 [多源环境数据说明](./weather_api_data/README.md) 配置本地环境并执行：

```powershell
cd .\weather_api_data
.\.venv\Scripts\weather-api-data.exe refresh-all
.\.venv\Scripts\weather-api-data.exe publish-web
```

## 数据口径

网页数据包包含 54 个约 1 km 环境网格和 90 条路线结果。PM2.5 属于网格空间估计，花粉属于日级网格背景，噪声属于约 100 m 路段的 0–100 风险代理。未来 PM2.5 在上海当前缺少上游污染物浓度，系统保留缺值；接驳路径环境状态为 `not_aggregated`。

数据状态以 `environment_dashboard.json` 内的 `generated_at` 和 `status` 为准。`partial` 表示部分来源或字段暂缺，`stale` 表示页面保留上一份可用快照并标注过期。

## 主要目录

| 路径 | 内容 |
| --- | --- |
| [`xuhui_route_builder/`](./xuhui_route_builder/) | 路线数据、构建工具、本地网页、导航和测试 |
| [`weather_api_data/`](./weather_api_data/) | 天气、空气质量、PM2.5、花粉、噪声、路线暴露、调度和网页数据发布 |
| [`.agents/skills/`](./.agents/skills/) | 项目共享技能与验证工具 |
| [`上海路线规划项目方案/`](./上海路线规划项目方案/) | 项目方案与研究设计材料 |

## 隐私边界

真实 Key、token 和成员环境配置仅保存在本机。`weather_api_data/.env`、`weather_api_data/runtime/`、`xuhui_route_builder/web/local-amap-config.js` 和 `xuhui_route_builder/data/web/environment_dashboard.json` 均由 Git 忽略。凭据不写入提交、README、Issue、PR、日志或网页数据包。

## 验证

路线与网页测试：

```powershell
cd .\xuhui_route_builder
.\.venv\Scripts\python.exe -m pytest tests -q
node --test tests/*.test.mjs
```

环境模块的 pytest、Ruff 和 Pyright 命令见 [多源环境数据说明](./weather_api_data/README.md)。
