# 徐汇路线构建器

_徐汇区 90 条运动路线、本地地图与接驳导航使用说明。_

---

## 📋 当前范围

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 路线数据 | 已完成 | 步行、跑步、骑行各 30 条，共 90 条已验收路线 |
| 地图与筛选 | 已完成 | 展示徐汇边界、路线、入口和沿途 POI |
| 接驳与网页内导航 | 已完成 | 支持地点输入、地图点选、步行或骑行接驳和实时定位 |
| 环境评分 | 待接入 | PM2.5、噪声、花粉及综合暴露评分目前为占位字段 |
| AI Scientist Agent | 待接入 | `agents_placeholder.py` 保留后续输入输出边界 |

## 🔑 申请高德 Key

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

> 📌 **本地调试：** 高德官方对 `INVALID_USER_DOMAIN` 的排查建议是清除域名白名单；后续发布固定域名时，再将实际域名逐行加入白名单。[^3]

> ⚠️ **Key 类型：** 本地网站选择 `Web端（JS API）`。`Web服务` Key 用于 Python 路线生成，两类 Key 的使用位置不同。

## 🚀 配置并启动网站

以下命令从仓库根目录执行。PowerShell 会交互式读取 Key，输入值不会写入命令历史；命令随后生成本地配置文件并启动静态网站。

```powershell
cd .\xuhui_route_builder
$amapJsKey = Read-Host "请输入高德 Web端 JS API Key"
$amapSecurityCode = Read-Host "请输入同一行的安全密钥"
@"
window.XUHUI_AMAP_JS_KEY = "$amapJsKey";
window.XUHUI_AMAP_JS_SECURITY_CODE = "$amapSecurityCode";
"@ | Set-Content -LiteralPath ".\web\local-amap-config.js" -Encoding utf8
Remove-Variable amapJsKey, amapSecurityCode
python -m http.server 8123
```

服务启动后，另开一个 PowerShell 窗口打开网页：

```powershell
Start-Process "http://127.0.0.1:8123/web/"
```

页面应显示步行、跑步、骑行各 30 条路线。切换到“路线导航”，设置用户位置并规划路径，即可检查高德 Key 和安全密钥是否生效。

`web/local-amap-config.js` 已由 `.gitignore` 排除。当前明文配置方式只服务于成员本地开发；高德在线生产环境推荐使用服务端代理保存安全密钥。[^4]

## ⚙️ 数据构建配置

浏览已有路线和使用导航只需要上一节的网页配置。重新解析地点、生成路线或刷新数据时，再复制 `.env.example`：

```powershell
Copy-Item .env.example .env
```

| 变量 | 用途 |
| --- | --- |
| `AMAP_WEB_SERVICE_KEY` | Python 步行和骑行路线生成 |
| `AMAP_JS_API_KEY` | 网页 JS API Key 的本地记录 |
| `AMAP_JS_SECURITY_CODE` | 网页安全密钥的本地记录 |
| `BAIDU_MAP_AK` | OSM 未命中或结果存在歧义时的地点检索兜底 |

地点解析链路为：已验收路线节点 → OSM 本地 POI 索引 → 百度地点检索 → 百度地理编码。高德负责路径规划和网页地图展示。

```powershell
$env:PYTHONPATH="src"
python -m xuhui_route_builder.cli build-osm-poi-index
python -m xuhui_route_builder.cli resolve-seeds --max-online-calls 50
python -m xuhui_route_builder.cli generate-routes
python -m xuhui_route_builder.cli validate-routes
```

## ✅ 验证

```powershell
python -m pytest tests -q
node --test tests/*.test.mjs
```

检查本地配置文件仍处于忽略状态：

```powershell
git check-ignore .\web\local-amap-config.js
```

预期输出为 `web/local-amap-config.js`。

## 🔧 常见问题

### 页面显示 0 条路线

服务启动目录有误时，日志会显示 `/data/web/...` 返回 `404`。按 `Ctrl+C` 停止服务，确认当前路径以 `xuhui_route_builder` 结尾，再运行 `python -m http.server 8123`。

### 地图空白或提示安全密钥错误

返回控制台确认复制的是同一行的 `Key` 和 `安全密钥`，并确认服务平台为 `Web端（JS API）`。重新运行配置命令后按 `Ctrl+F5` 刷新页面。

### 出现 INVALID_USER_DOMAIN

进入高德控制台，在该 Key 的“设置”中清除域名白名单，保存后重新加载本地网页。后续恢复在线部署时，将实际网站域名加入白名单。

## 🔗 参考资料

[^1]: 高德开放平台. “准备：地图 JS API 2.0.” 访问日期 2026-08-22. https://lbs.amap.com/api/javascript-api-v2/prerequisites

[^2]: 高德开放平台. “我的应用.” 访问日期 2026-08-22. https://console.amap.com/dev/key/app

[^3]: 高德开放平台. “接口返回 INVALID_USER_DOMAIN 怎么办？” 访问日期 2026-08-22. https://lbs.amap.com/faq/js-api/map-js-api/create-project/46515

[^4]: 高德开放平台. “JS API 安全密钥使用.” 访问日期 2026-08-22. https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode
