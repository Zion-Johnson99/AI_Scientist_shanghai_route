# 徐汇路线构建器

第一阶段目标是把徐汇区运动路线原型打通：严格边界、入口点、150 条候选运动路线、POI 偏好、接驳样例、高德底图和静态地图查看。

## 当前范围

- 已实现：配置读取、高德 WebService 客户端、基础数据模型、150 条演示路线生成、GeoJSON 导出、高德 JS API 地图原型。
- 暂缓：PM2.5、噪声、花粉评分模型；Qwen/百炼多 Agent；OSRM、GraphHopper、pgRouting 自建路由服务。
- 预留：`scoring_placeholder.py` 和 `agents_placeholder.py` 定义后续输入输出边界。

## 配置

复制 `.env.example` 为 `.env`，填入本机高德 WebService Key：

```powershell
Copy-Item .env.example .env
```

真实 Key 放 `.env`、系统环境变量或本地浏览器 URL 参数，仓库中保留 `.env.example`。

## 常用命令

```powershell
cd D:\SJTU\交大\揭榜挂帅\AI_Scientist\xuhui_route_builder
python -m pytest tests -q
$env:PYTHONPATH="src"
python -m xuhui_route_builder.cli export-demo
python -m http.server 8000
```

浏览器打开以下地址查看地图原型：

```text
http://localhost:8000/web/?amapKey=你的高德JSKey&amapSecurity=你的安全密钥
```

页面初始只显示高德底图和徐汇边界。点击“规划候选路线”或输入关键词后，页面再绘制匹配路线和相关入口点。
