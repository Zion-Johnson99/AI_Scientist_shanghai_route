# 徐汇路线构建器

_徐汇区 90 条运动路线、本地地图与接驳导航使用说明。_

---

## 当前范围

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 路线数据 | 已完成 | 步行、跑步、骑行各 30 条，共 90 条已验收路线 |
| 地图与筛选 | 已完成 | 展示徐汇边界、路线、入口和沿途 POI |
| 接驳与网页内导航 | 已完成 | 支持地点输入、地图点选、步行或骑行接驳和实时定位 |
| 环境评分 | 待接入 | PM2.5、噪声、花粉及综合暴露评分目前为占位字段 |
| AI Scientist Agent | 待接入 | `agents_placeholder.py` 保留后续输入输出边界 |

## 申请高德 Key

本地网页使用 `Web端（JS API）` Key 和同一行显示的安全密钥。高德官方流程为：进入应用管理、创建应用、添加 Key，并将服务平台设置为 `Web端（JS API）`。[^1]

1. 打开[高德开放平台控制台](https://console.amap.com/dev/key/app)并登录。
2. 点击“创建新应用”。应用名称可填写 `徐汇健康路线`，应用类型按实际研究场景选择。
3. 在新应用中点击“添加 Key”，按下表填写。

| 控制台字段 | 建议填写 |
| --- | --- |
| **Key 名称** | `xuhui_local` |
| **服务平台** | `Web端（JS API）` |
| **域名白名单** | 本地调试阶段留空 |

4. 阅读并同意控制台列出的服务条款，点击“提交”。
5. 在应用列表中复制该行的 `Key` 与 `安全密钥`。新创建的 JS API Key 需配套安全密钥使用。[^2]

本地调试说明：高德官方对 `INVALID_USER_DOMAIN` 的排查建议是清除域名白名单；后续发布固定域名时，再将实际域名逐行加入白名单。[^3]

Key 类型说明：本地网站选择 `Web端（JS API）`。`Web服务` Key 用于 Python 路线生成，两类 Key 的使用位置不同。

## 统一配置地图 Key

首次使用时，在 `xuhui_route_builder` 目录复制本地配置模板，再填写高德、腾讯和百度 Key：

```powershell
cd .\xuhui_route_builder
Copy-Item .env.example .env
```

| 变量 | 用途 |
| --- | --- |
| `AMAP_WEB_SERVICE_KEY` | Python 步行和骑行路线生成 |
| `AMAP_JS_API_KEY` | 网页地图、定位和接驳导航 |
| `AMAP_JS_SECURITY_CODE` | 高德 JS API 安全配置 |
| `TENCENT_SEARCH_KEY` | 用户位置输入框的上海地点联想 |
| `BAIDU_MAP_AK` | OSM 未命中或结果存在歧义时的地点检索兜底 |

仓库根目录的 `start-local-app.ps1` 和 `start-local-app.sh` 会读取该 `.env`，生成 `web/local-amap-config.js` 与 `web/local-tencent-config.js`。两个生成文件和 `.env` 均由 Git 忽略；生成文件只包含浏览器运行所需的高德 JS 配置与腾讯搜索 Key，高德 Web 服务 Key 和百度 AK 留在 `.env`。[^4]

## 运行网站

使用仓库根目录统一启动脚本时，地图配置会自动生成。单独启动路线网站时，先生成网页配置，再启动静态服务：

```powershell
cd .\xuhui_route_builder
.\.venv\Scripts\python.exe .\src\xuhui_route_builder\web_map_config.py --env-file .env --web-root web
.\.venv\Scripts\python.exe -m http.server 8123
```

服务启动后，另开一个 PowerShell 窗口执行：

```powershell
Start-Process "http://127.0.0.1:8123/web/"
```

页面应显示步行、跑步、骑行各 30 条路线。切换到“路线导航”，设置用户位置并规划路径，即可检查高德 Key 和安全密钥是否生效。

## 数据构建配置

浏览已有路线和使用导航会读取生成后的网页配置。重新解析地点、生成路线或刷新数据时，同一份 `.env` 继续为 Python 提供高德 Web 服务 Key 和百度 AK。地点解析依次使用已验收路线节点、OSM 本地 POI 索引、百度地点检索和百度地理编码；高德负责路径规划和网页地图展示。

```powershell
$env:PYTHONPATH="src"
python -m xuhui_route_builder.cli build-osm-poi-index
python -m xuhui_route_builder.cli resolve-seeds --max-online-calls 50
python -m xuhui_route_builder.cli generate-routes
python -m xuhui_route_builder.cli validate-routes
```

## 路线重建与验收源码

比赛使用的正式链路为：路线种子 → 路径缓存或在线生成 → 几何验证 → 组合验收 → 真实 POI 合并 → Web 数据。各阶段源码、输入输出、失败保护和完整命令见 [`tools/README.md`](tools/README.md)。

核心实现位于 `src/xuhui_route_builder`，其中 `js_route_cache.py` 负责最多 5 条一批的高德 JS 路径缓存，`routes.py` 负责候选路线生成，`validation.py` 负责边界与道路证据验证，`service_pois.py` 负责真实 POI 合并。项目级几何和组合门禁位于 `.agents/skills/optimize-xuhui-routes/scripts`。

## 验证

```powershell
python -m pytest tests -q
node --test tests/*.test.mjs
```

检查本地配置文件仍处于忽略状态：

```powershell
git check-ignore .\web\local-amap-config.js
```

预期输出为 `web/local-amap-config.js`。

## 常见问题

### 页面显示 0 条路线

服务启动目录有误时，日志会显示 `/data/web/...` 返回 `404`。按 `Ctrl+C` 停止服务，确认当前路径以 `xuhui_route_builder` 结尾，再运行 `python -m http.server 8123`。

### 地图空白或提示安全密钥错误

返回控制台确认复制的是同一行的 `Key` 和 `安全密钥`，并确认服务平台为 `Web端（JS API）`。重新运行配置命令后按 `Ctrl+F5` 刷新页面。

### 出现 INVALID_USER_DOMAIN

进入高德控制台，在该 Key 的“设置”中清除域名白名单，保存后重新加载本地网页。后续恢复在线部署时，将实际网站域名加入白名单。

## 参考资料

[^1]: 高德开放平台. “准备：地图 JS API 2.0.” 访问日期 2026-08-22. https://lbs.amap.com/api/javascript-api-v2/prerequisites

[^2]: 高德开放平台. “我的应用.” 访问日期 2026-08-22. https://console.amap.com/dev/key/app

[^3]: 高德开放平台. “接口返回 INVALID_USER_DOMAIN 怎么办？” 访问日期 2026-08-22. https://lbs.amap.com/faq/js-api/map-js-api/create-project/46515

[^4]: 高德开放平台. “JS API 安全密钥使用.” 访问日期 2026-08-22. https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode
