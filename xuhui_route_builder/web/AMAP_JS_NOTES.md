# 高德 JS API 后续接入说明

第一阶段网页使用 Leaflet 读取本地 GeoJSON，避免浏览器暴露 WebService Key。

后续切换到高德 JS API 2.0 时，前端只使用 `AMAP_JS_API_KEY` 加载地图。安全密钥 `AMAP_JS_SECURITY_CODE` 按高德官方建议放在服务端代理中处理，生产环境不写进前端源码。

WebService API 的行政区、POI 和路径规划仍由 Python 或后端代理调用，继续使用 `AMAP_WEB_SERVICE_KEY`。
