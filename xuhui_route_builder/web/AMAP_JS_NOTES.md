# 高德 JS API 2.0 接入说明

前端地图默认使用高德 JS API 2.0。仓库内不写真实 Key，页面加载时读取 `window.XUHUI_AMAP_JS_KEY`，缺省值为 `AMAP_JS_PLACEHOLDER_KEY`。

本地调试时可在浏览器控制台或本地未提交的 HTML 包装页中提前设置：

```html
<script>
  window.XUHUI_AMAP_JS_KEY = "你的高德 JS API Key";
  window.XUHUI_AMAP_JS_SECURITY_CODE = "你的高德安全密钥";
</script>
```

当前 Web 层只依赖本地 `route_catalog.json`、`xuhui_routes.geojson`、`xuhui_entries.geojson` 和 `xuhui_boundary.geojson` 完成候选路线筛选与绘制。`AMap.Geocoder`、`AMap.Driving`、`AMap.Walking`、`AMap.Riding` 已在地图层预留 hook，后续接入真实地理编码或路径规划时可从 `mapContext.serviceHooks` 取用。

启动状态只绘制高德底图和徐汇边界。搜索或点击“规划候选路线”后，页面才绘制匹配路线和相关入口；`community_node` 只随相关路线结果显示。
