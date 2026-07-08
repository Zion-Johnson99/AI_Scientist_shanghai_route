# 徐汇路线构建器

第一阶段目标是把徐汇区运动路线原型打通：严格边界、入口点、150 条候选运动路线、POI 偏好、高德底图、路线选择和路线导航两个网页界面。

## 当前范围

- 已实现：配置读取、高德 WebService 客户端、基础数据模型、150 条候选路线生成、GeoJSON 导出、高德 JS API 地图原型、路线选择和路线导航切换界面。
- 暂缓：PM2.5、噪声、花粉评分模型；Qwen/百炼多 Agent；OSRM、GraphHopper、pgRouting 自建路由服务。
- 预留：`scoring_placeholder.py` 和 `agents_placeholder.py` 定义后续输入输出边界。

## 配置

Python 脚本读取高德 WebService Key。复制 `.env.example` 为 `.env`，填入本机高德 WebService Key：

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

重新导出演示数据：

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
$env:PYTHONPATH="src"
python -m xuhui_route_builder.cli export-demo
```

## 网页功能

`http://127.0.0.1:8123/web/` 默认进入路线选择界面。页面显示徐汇边界、候选路线、入口点和路线列表，可按片区、距离档、类型、关键词和途经偏好筛选，并直接点击候选路线查看地图高亮。

切换到路线导航界面后，可选择一条候选路线，输入出发地，规划到该路线运动入口的接驳路径。终点默认使用候选路线入口坐标，也可手动输入终点。
