# 数据来源与加工口径

## 原始公开数据

| 数据 | 来源 | 获取方式 | 许可 | 用途 |
| --- | --- | --- | --- | --- |
| 徐汇区行政边界 | OpenStreetMap relation 1278188（`boundary=administrative`, `admin_level=6`, `name:zh=徐汇区`） | Overpass API 关系查询 | ODbL 1.0 | 区内比例、网格范围、地图首屏 |
| 道路网 | OpenStreetMap `highway=*` way | 官方 OSM API `/api/0.6/map?bbox=` 6×6 网格切片，超限自动细分 | ODbL 1.0 | 路网图、路线搜索、道路贴合 |
| POI（公园、入口、服务设施） | OpenStreetMap node/way 标签 | 同上 | ODbL 1.0 | 区域锚点、入口池、邻近服务 |
| 气象 | Open-Meteo Forecast API（免密钥） | `urllib` 直连，落盘为 `sources/open_meteo_forecast.json` | CC BY 4.0 | 温度、体感、湿度、风速、阵风、降水 |
| 空气质量 | Open-Meteo Air Quality API（免密钥） | `urllib` 直连，落盘为 `sources/open_meteo_air_quality.json` | CC BY 4.0 | PM2.5、US AQI |

逐条来源、URL、访问时间、用途与许可见 `../../sources/source_registry.jsonl`。

## 加工层级标注

每个产物字段都带 `provenance` 与 `status`，取值含义固定：

| provenance | 含义 |
| --- | --- |
| `public_osm_data_fetched_in_this_run` | 本次运行内抓取的 OSM 原始数据 |
| `public_api_measurement` | 免密钥公开 API 返回的观测/预报值 |
| `deterministic_computation` | 由上述原始数据确定性计算得出 |
| `deterministic_proxy_model` | 确定性代理模型，非实测 |
| `manual_setting` | 人工设定的常量或阈值 |
| `qoder_judgement` | 由 Qoder 会话作出的判断，非数据 |

| status | 含义 | 可靠度乘子 |
| --- | --- | --- |
| `measured` | 来自公开 API 的真实数值 | 1.00 |
| `derived` | 由原始数据确定性推导 | 0.90 |
| `estimated` | 代理模型估算 | 0.75 |
| `unavailable` | 缺失，值必须为 `null` | 不计入 |

## 明确不是实测的量

- `noise_proxy_db`：由主干道密度与路网密度经固定公式映射到 35–85 的代理量，单位写作 `dB_proxy` 以区别于实测声级。徐汇区无可公开下载的分时段实测噪声栅格，因此不声称实测。
- `traffic_exposure_0_1`：主干道密度的固定尺度归一化，代理量。
- `estimated_access_min`：直线距离 × 1.35 绕行系数 ÷ 4.8 km/h。未调用任何在线路径规划接口，`api_distance_provenance` 固定为 `not_applicable_no_credentials`。
- 速度常量 `walk 4.8 / run 9.0 / bike 18.0 km/h` 为 `manual_setting`。

## 缺失值口径

缺失一律写 JSON `null`，禁止用 0、-1、中位数或插值填充。
每个字段在 `environment_dashboard.json.missing_rate` 中给出缺失率，阈值 ≤ 0.10。
公开 API 未覆盖的字段进入 `excluded_fields` 并写明原因，不进入打分。
