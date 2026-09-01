# 面向上海城市户外运动的健康路线决策 AI Scientist

_徐汇区路线原型、多源环境数据与个性化推荐说明，更新于 2026-09-01。_

---

## 在线访问

[打开徐汇户外健康地图](https://zion-johnson99.github.io/AI_Scientist_shanghai_route/)

## 当前能力

| 模块 | 状态 | 当前结果 |
| --- | --- | --- |
| 路线与 POI | 已完成 | 步行、跑步、骑行各 30 条，共 90 条已验收路线 |
| 本地地图与导航 | 已完成 | 支持筛选、路线展示、地点输入、地图点选、步行或骑行接驳和网页内导航 |
| 多源环境数据 | 已接入 | 和风天气、上海空气质量站点、CHAP PM2.5、Google 花粉和噪声代理已形成统一刷新与本地历史链路 |
| 环境网页展示 | 已接入 | 展示当前天气、AQI、预警、生活指数、24 小时天气与 AQI，以及 54 个环境网格和 90 条路线的 PM2.5、花粉、噪声结果 |
| 个性化排序 | 已接入 | 支持硬约束、五维评分、首选与两条备选；可使用本地 Python 排序或千问个性化审核 |
| AI Scientist 工作流 | 待完成 | 已保留 Agent 输入输出边界，假设、实验、验证和结果记录尚待串联 |
| 在线部署 | 已上线 | GitHub Pages 提供公开网页，GitHub Actions 按计划更新环境数据 |

## 本地启动完整应用

首次使用前，分别按[评价与千问服务说明](./evaluation_model_qwen/README.md)和[徐汇路线构建器说明](./xuhui_route_builder/README.md)完成依赖与地图 Key 配置。

日常启动在仓库根目录执行一条命令。默认使用本地 Python 排序，不消耗千问额度。

Windows 使用 PowerShell：

```powershell
.\start-local-app.ps1
```

启用千问个性化审核：

```powershell
.\start-local-app.ps1 -UseQwen
```

macOS 或 Linux 使用 Bash：

```bash
bash ./start-local-app.sh
```

启用千问个性化审核：

```bash
bash ./start-local-app.sh --use-qwen
```

两个脚本的启动职责和端口一致，虚拟环境路径分别使用 Windows 的 `.venv\Scripts\` 与 macOS/Linux 的 `.venv/bin/`。每台机器需独立安装项目依赖和配置本地 `.env`。

脚本会先从 `xuhui_route_builder/.env` 生成已忽略的本地网页地图配置，再同时管理环境数据刷新、推荐 API 和静态网页，通过健康检查后自动打开 [http://127.0.0.1:8123/web/](http://127.0.0.1:8123/web/)。启动时按数据新鲜度选择刷新层级：天气和预警临近 15 分钟有效期时执行 `weather`，AQI 与当前 PM2.5 超过 1 小时执行 `hourly`，花粉、噪声和生活指数失效时执行 `daily`。运行期间每 30 分钟复查一次，每次刷新后也会间隔 30 分钟再尝试；命令窗口只显示本次是否更新及数据更新时间。单次上游更新失败会保留上一份数据并在命令窗口告警。

命令窗口保持运行；按 `Ctrl+C` 会统一停止由本次命令启动的服务。切换本地或千问模式前，先结束上一条启动命令。千问鉴权、限流、网络或输出校验异常时，推荐服务会回退到本地 Python 排序。

环境数据包缺失或需要更新时，先按 [多源环境数据说明](./weather_api_data/README.md) 配置本地环境并执行：

```powershell
cd .\weather_api_data
.\.venv\Scripts\weather-api-data.exe refresh-all
.\.venv\Scripts\weather-api-data.exe publish-web
```

页面显示“暂时没有完成推荐”时，先访问 [推荐服务健康检查](http://127.0.0.1:8124/api/v1/health)。该地址无法打开通常表示统一启动命令已经退出，或 8124 端口被其他程序占用。启动日志保存在 `evaluation_model_qwen/runtime/local-app/`。

## 数据口径

网页数据包包含 54 个约 1 km 环境网格和 90 条路线结果。PM2.5 属于网格空间估计，花粉属于日级网格背景，噪声属于约 100 m 路段的 0–100 风险代理。未来 PM2.5 在上海当前缺少上游污染物浓度，系统保留缺值；接驳路径环境状态为 `not_aggregated`。

数据状态以 `environment_dashboard.json` 内的 `generated_at` 和 `status` 为准。`partial` 表示部分来源或字段暂缺，`stale` 表示页面保留上一份可用快照并标注过期。

## 主要目录

| 路径 | 内容 |
| --- | --- |
| [`xuhui_route_builder/`](./xuhui_route_builder/) | 路线数据、构建工具、本地网页、导航和测试 |
| [`weather_api_data/`](./weather_api_data/) | 天气、空气质量、PM2.5、花粉、噪声、路线暴露、调度和网页数据发布 |
| [`evaluation_model_qwen/`](./evaluation_model_qwen/) | 路线硬约束、五维评分、千问审核、推荐 API 和审计记录 |
| [`.agents/skills/`](./.agents/skills/) | 项目共享技能与验证工具 |
| [`上海路线规划项目方案/`](./上海路线规划项目方案/) | 项目方案与研究设计材料 |

## 隐私边界

真实 Key、token 和成员环境配置保存在本机 `.env` 或云端加密 Secrets 中。`weather_api_data/.env`、`weather_api_data/runtime/`、`evaluation_model_qwen/.env`、`evaluation_model_qwen/runtime/`、`xuhui_route_builder/.env`、`xuhui_route_builder/web/local-amap-config.js`、`xuhui_route_builder/web/local-tencent-config.js` 和 `xuhui_route_builder/data/web/environment_dashboard.json` 均由 Git 忽略。凭据不写入提交、README、Issue、PR、日志或网页数据包。

## 验证

路线与网页测试：

```powershell
cd .\xuhui_route_builder
.\.venv\Scripts\python.exe -m pytest tests -q
node --test tests/*.test.mjs
```

环境模块的 pytest、Ruff 和 Pyright 命令见 [多源环境数据说明](./weather_api_data/README.md)。

评价与推荐服务的 pytest、Ruff 和 Pyright 命令见 [评价与千问服务说明](./evaluation_model_qwen/README.md)。
