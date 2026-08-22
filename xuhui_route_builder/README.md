# 徐汇路线构建器

第一阶段目标是把徐汇区运动路线原型打通：严格边界、入口点、150 条候选运动路线、POI 偏好、高德底图、路线选择和路线导航两个网页界面。

## 当前范围

- 已实现：配置读取、高德 WebService 客户端、基础数据模型、150 条候选路线生成、GeoJSON 导出、高德 JS API 地图原型、路线选择和路线导航切换界面。
- 暂缓：PM2.5、噪声、花粉评分模型；Qwen/百炼多 Agent；OSRM、GraphHopper、pgRouting 自建路由服务。
- 预留：`scoring_placeholder.py` 和 `agents_placeholder.py` 定义后续输入输出边界。

## 配置

Python 脚本读取高德 WebService Key 和百度服务端 AK。复制 `.env.example` 为 `.env`，填入本机密钥：

```powershell
Copy-Item .env.example .env
```

网页读取高德 JS API Key 和安全密钥。本机使用以下文件：

```text
web/local-amap-config.js
```

文件内容格式：

```javascript
window.XUHUI_AMAP_JS_KEY = "你的高德 JS API Key";
window.XUHUI_AMAP_JS_SECURITY_CODE = "你的高德安全密钥";
```

`web/local-amap-config.js` 已在 `.gitignore` 中忽略，真实 Key 只留在本地。仓库中保留 `.env.example` 作为配置模板。

### 百度服务端 AK

百度地点检索只作为 OSM 无结果或结果存在歧义时的兜底来源。AK 需要选择“服务端”类型，并在百度地图开放平台配置 IP 白名单；白名单填写运行 Python 脚本时访问国内站点所使用的公网 IPv4。代理软件可能对国内外站点采用不同出口，因此应以国内 IP 查询服务的结果为准，切换校园网、家庭网络、热点或代理规则后需要重新核对。

真实 AK 写入本地 `.env`：

```text
BAIDU_MAP_AK=你的百度服务端AK
```

AK、IP 白名单和本地缓存均不提交到仓库。百度接口返回 `status=0` 代表鉴权及请求成功；`status=210` 代表 IP 白名单未命中。

## 地点搜索逻辑

地点解析主链路为：已验收路线节点 → OSM 本地 POI 索引 → 百度地点检索 → 百度地理编码。高德继续负责路径规划和网页地图展示，不承担批量地点搜索。

1. `resolve-seeds` 先复用 `route_seeds.json` 中已有且带坐标的节点，减少重复查询并保护已验收数据。
2. `build-osm-poi-index` 通过一次 Overpass 查询获取徐汇区具名 POI，保存为本地索引；后续地点查询优先在这个索引中完成，不会为每个地点重复调用在线搜索服务。
3. 本地数据和 OSM 均未唯一命中时，才调用百度区域地点检索；地点检索仍未命中时，再调用百度地理编码。百度结果限定徐汇区行政代码或徐汇边界，并直接请求 GCJ-02 坐标，供高德地图和路径规划使用。

百度成功响应缓存在 `data/raw/baidu`，同一参数后续直接读取缓存。`resolve-seeds --max-online-calls 50` 将单次运行的百度联网请求限制为最多 50 次；需要完全离线解析时设为 `0`。解析过程失败时保留上一版已验收节点，避免错误结果覆盖现有路线数据。

## 常用命令

如果 8123 服务已经启动，直接打开地图网页：

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
Start-Process "http://127.0.0.1:8123/web/"
```

如果 8123 服务还没启动，先启动本地静态网页服务：

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
python -m http.server 8123
```

这个命令会占住当前 PowerShell 窗口。服务启动后，在浏览器打开 `http://127.0.0.1:8123/web/`，或另开一个 PowerShell 窗口运行 `Start-Process "http://127.0.0.1:8123/web/"`。

运行测试：

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
python -m pytest tests -q
```

生成并验证真实路线数据：

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
$env:PYTHONPATH="src"
python -m xuhui_route_builder.cli build-osm-poi-index
python -m xuhui_route_builder.cli resolve-seeds --max-online-calls 50
python -m xuhui_route_builder.cli generate-routes
python -m xuhui_route_builder.cli validate-routes
```

`generate-routes` 逐段调用高德步行或骑行路径，`validate-routes` 完成 OSM 贴路检查后更新网页路线。

## 路线重建与验收源码

比赛使用的正式链路为：路线种子 → 路径缓存或在线生成 → 几何验证 → 组合验收 → 真实 POI 合并 → Web 数据。各阶段源码、输入输出、失败保护和完整命令见 [`tools/README.md`](tools/README.md)。

核心实现位于 `src/xuhui_route_builder`，其中 `js_route_cache.py` 负责最多 5 条一批的高德 JS 路径缓存，`routes.py` 负责候选路线生成，`validation.py` 负责边界与道路证据验证，`service_pois.py` 负责真实 POI 合并。项目级几何和组合门禁位于 `.agents/skills/optimize-xuhui-routes/scripts`。

## 网页功能

`http://127.0.0.1:8123/web/` 默认进入路线选择界面。页面显示徐汇边界、候选路线、入口点和路线列表，可按片区、距离档、类型、关键词和途经偏好筛选，并直接点击候选路线查看地图高亮。

切换到路线导航界面后，可选择一条候选路线，输入出发地，规划到该路线运动入口的接驳路径。终点默认使用候选路线入口坐标，也可手动输入终点。
