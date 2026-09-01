# 徐汇户外健康地图：路线与导航

_浏览徐汇区户外路线，查看沿途环境，并从当前位置前往路线起点。_

---

## 模块介绍

本模块是项目的路线与地图产品，已收录 90 条徐汇区户外运动路线，其中步行、跑步、骑行各 30 条。用户可按运动方式和距离浏览路线，也可结合个性偏好、沿途环境与接驳距离获得推荐。

![徐汇户外健康地图产品首页](../docs/images/readme/product-overview.png)
*图 1：产品首页提供路线推荐、90 条路线浏览和徐汇区环境概览*

## 主要功能

| 功能 | 使用体验 |
| --- | --- |
| **路线库** | 覆盖徐汇滨江、龙华、衡复风貌区、上海植物园、康健园、漕河泾等区域 |
| **路线筛选** | 按步行、跑步、骑行和距离范围快速缩小路线列表 |
| **路线详情** | 查看距离、时长、路线形态、起终点、沿途地点、推荐优点和出行建议 |
| **环境信息** | 展示天气、AQI、生活指数，以及路线 PM2.5、花粉和噪声风险 |
| **地点搜索** | 支持上海地点联想、设备定位和地图点选，快速设置出发位置 |
| **接驳导航** | 从已选位置规划步行或骑行接驳，并在网页中查看路径和分步指引 |
| **千问推荐** | 连接评价模块后，可通过筛选条或千问路线助手获取个性化推荐 |

![路线详情与沿途环境信息](../docs/images/readme/route-detail.png)
*图 2：路线详情集中展示路径、沿途环境、推荐理由和“前往起点”入口*

## 快速体验

需要 Python 3.10 或更高版本，并已安装 [uv](https://docs.astral.sh/uv/)。从仓库根目录执行：

```powershell
cd .\xuhui_route_builder
uv sync
Copy-Item .env.example .env
```

打开 `.env`，填写网页运行需要的三项配置：

| 配置项 | 用途 |
| --- | --- |
| `AMAP_JS_API_KEY` | 显示高德地图并规划接驳路径 |
| `AMAP_JS_SECURITY_CODE` | 配套高德 JS API Key 的安全配置 |
| `TENCENT_SEARCH_KEY` | 提供上海地点搜索与联想 |

高德配置在[高德开放平台控制台](https://console.amap.com/dev/key/app)创建，服务平台选择 `Web端（JS API）`；腾讯搜索 Key 在[腾讯位置服务控制台](https://lbs.qq.com/dev/console/home)创建。真实 Key 保存在本地 `.env`，公开仓库只保留填写模板。

完成项目其他模块的首次配置后，回到仓库根目录统一启动：

```powershell
cd ..
.\start-local-app.ps1
```

启动脚本会打开 `http://127.0.0.1:8123/web/`，并同时连接环境数据与本地推荐服务。体验千问推荐时使用：

```powershell
.\start-local-app.ps1 -UseQwen
```

## 单独运行路线网站

只查看路线与地图时，可单独生成网页配置并启动静态服务：

```powershell
cd .\xuhui_route_builder
.\.venv\Scripts\python.exe .\src\xuhui_route_builder\web_map_config.py --env-file .env --web-root web
.\.venv\Scripts\python.exe -m http.server 8123
```

浏览器打开 `http://127.0.0.1:8123/web/`。该模式直接读取仓库中已发布的路线和环境数据；千问推荐需另行启动 `evaluation_model_qwen` API。

## 进阶：重建与验收路线

日常浏览、筛选和导航直接使用已验收的 90 条路线，无需重新生成。维护路线库时，`AMAP_WEB_SERVICE_KEY` 用于在线路径生成，`BAIDU_MAP_AK` 用于地点检索补充；完整的数据链路、命令和质量门禁见 [`tools/README.md`](tools/README.md)。

## 验证

先安装开发验证工具：

```powershell
uv sync --extra dev
```

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
node --test tests/*.test.mjs
```

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 页面显示 0 条路线 | 确认静态服务从 `xuhui_route_builder` 目录启动，并访问 `/web/` |
| 地图空白 | 核对高德 JS API Key 与安全密钥来自同一应用，再重新生成网页配置 |
| 地点搜索无结果 | 核对 `TENCENT_SEARCH_KEY`、网络状态和腾讯控制台中的服务配置 |
