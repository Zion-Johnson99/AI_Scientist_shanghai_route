# 许可与署名

## OpenStreetMap（ODbL 1.0）

边界、路网、POI 均来自 OpenStreetMap 贡献者，采用 Open Database License 1.0。

按 ODbL 要求署名：

> 地图数据 © OpenStreetMap contributors, ODbL 1.0.
> https://www.openstreetmap.org/copyright

本目录内的产物为对 OSM 数据的加工结果（衍生数据库）。
分发时需保留本署名，并以 ODbL 1.0 或兼容条款共享衍生数据库。
未使用任何 OSM 官方瓦片服务或第三方瓦片 CDN。

## Open-Meteo（CC BY 4.0）

气象与空气质量数值来自 Open-Meteo 免费接口，采用 CC BY 4.0。

> Weather and air quality data by Open-Meteo.com, CC BY 4.0.
> https://open-meteo.com/en/terms

原始响应逐字保存在 `../../sources/open_meteo_forecast.json` 与
`../../sources/open_meteo_air_quality.json`，含抓取时间与请求 URL。

## 原创部分

`routes/`、`environment/`、`evaluation/`、`web/`、`scripts/`、`tests/`、`node/`
的全部代码、视觉设计、文案与交互结构为本次运行原创，
未复制仓库现有业务模块、第一轮生成源码或任何在线成品页面的
HTML、CSS、JavaScript、接口响应、GeoJSON 或静态资源。

## 未使用

- 无付费大模型 API 调用，无 DashScope / 百炼请求。
- 无商业地图密钥，无高德 / 百度 / Google Maps SDK。
- 无第三方前端库、字体或图标 CDN。
