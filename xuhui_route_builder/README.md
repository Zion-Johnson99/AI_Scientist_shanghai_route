# 徐汇路线构建器

第一阶段目标是把徐汇区运动路线原型打通：行政区边界、入口点、人工路线种子、高德路径规划、接驳样例、Web GeoJSON 导出和静态地图查看。

## 当前范围

- 已实现：配置读取、高德 WebService 客户端、基础数据模型、路线种子、GeoJSON 导出、静态 Leaflet 地图原型。
- 暂缓：PM2.5、噪声、花粉评分模型；Qwen/百炼多 Agent；OSRM、GraphHopper、pgRouting 自建路由服务。
- 预留：`scoring_placeholder.py` 和 `agents_placeholder.py` 定义后续输入输出边界。

## 配置

复制 `.env.example` 为 `.env`，填入本机高德 Key：

```powershell
Copy-Item .env.example .env
```

真实 Key 只放 `.env` 或系统环境变量，仓库中只保留 `.env.example`。

## 常用命令

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
python -m pytest tests -q
$env:PYTHONPATH="src"
python -m xuhui_route_builder.cli export-samples
python -m http.server 8000
```

浏览器打开 `http://localhost:8000/web/index.html` 查看地图原型。
