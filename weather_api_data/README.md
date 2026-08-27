# weather_api_data 徐汇多源环境数据接入

本模块以和风天气作为活动气象提供方，围绕参考点 `XH_ENT_0009` 获取天气实况、未来 24 小时天气、3 日生活指数和天气预警。空气质量请求只覆盖 11 区输出实际引用的坐标来源，并与上海站点、CHAP 历史网格共同生成区级和 54 格 PM2.5 结果。所有在线响应进入 GZIP 归档、SQLite 历史库和业务 JSON；端点测试默认读取本地 fixture，网络请求数为 0。

生产刷新固定使用和风天气。WeatherCN 普通 Key 仅保留为独立单点探针，不参与主刷新、历史积累或多源融合；进阶 Key、Secret、探针和回填入口已退出生产链路。

---

## 1. 当前主链

活动数据链路为：和风参考点与空气质量使用点 → 统一标准化 → SQLite 与环境 JSON → PM2.5 空间融合 → 路线多源暴露。

- 天气、生活指数、预警：只请求参考点 `XH_ENT_0009`
- 空气质量：只请求 11 区配置实际引用的和风坐标；两个上海站点继续独立采集
- 过去 24 小时天气：从本地 SQLite 选择上海本地最近 24 个整点的真实观测
- PM2.5：保留当前 11 区输出与 54 个 1 km 网格；中国地区未来 24 小时只有 AQI

参考点会解析为稳定的 `qweather:纬度,经度` 来源标识，并写入 `environment_regions.json`、`environment_latest.json` 和 `environment_hourly.json` 的 `reference_source_id`。

## 2. 启动前配置

先复制配置模板：

```powershell
Copy-Item .env.example .env
```

用户需要在本地 `.env` 填入以下两项：

```dotenv
QWEATHER_API_KEY=
QWEATHER_API_HOST=
```

`QWEATHER_API_HOST` 填写和风控制台分配的账户专属 HTTPS Host，域名以 `.qweatherapi.com` 结尾，省略路径、端口和查询参数。客户端通过请求头 `X-QW-Api-Key` 发送 Key；Key 不进入 URL、日志、归档、fixture 或 Git。Host 作为请求基址和无凭据来源地址保存。

活动配置保持以下值：

```dotenv
WEATHER_PROVIDER=qweather
QWEATHER_ENABLED=true
QWEATHER_MAX_CALLS_PER_RUN=80
QWEATHER_REFERENCE_POINT_ID=XH_ENT_0009
```

WeatherCN 普通 Key 探针配置保持独立：

```dotenv
WEATHERCN_STANDARD_API_KEY=
WEATHERCN_STANDARD_ENABLED=false
```

真实凭据只放在本地 `.env`。`WEATHERCN_STANDARD_ENABLED` 默认保持 `false`，标准接口仅在显式探针期间启用。

上海公共数据噪声接口默认关闭。截图中出现过的 token 已暴露，替换后再写入本地 `.env`：

```dotenv
SHANGHAI_NOISE_ENABLED=true
SHANGHAI_NOISE_TOKEN=替换后的token
SHANGHAI_NOISE_API_URL=https://data.sh.gov.cn/interface/O5485687412025006/59015
SHANGHAI_NOISE_PAGE_SIZE=100
SHANGHAI_NOISE_MAX_CALLS_PER_RUN=4
SHANGHAI_NOISE_MAX_AGE_HOURS=48
```

## 3. 安装与配置检查

在 `D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop\weather_api_data` 执行：

```powershell
python -m pip install -e ".[dev,chap]"
weather-api-data config-check
weather-api-data dry-run
```

`config-check` 校验活动提供方、凭据存在性、专属 Host、历史保留期和单轮调用上限。`dry-run` 全程零网络请求，当前基准刷新约 28 次和风调用，单轮独立硬上限为 80 次，基准余量为 52 次。重试计入调用数，第 81 次尝试前会受控停止。

## 4. 一条命令完整刷新

填好和风 Key 与专属 Host 后，先执行固定参考点探针：

```powershell
weather-api-data probe-qweather --point-id XH_ENT_0009 --confirm-qweather-probe
```

探针通过后运行完整主链：

```powershell
weather-api-data refresh-all
```

`refresh-all` 依次刷新和风天气、11 区空气质量、上海站点、当前 54 格 PM2.5、54 格花粉、上海噪声观测、路线段噪声和路线多源暴露。噪声接口每轮最多调用四个徐汇点位；`total=0` 会记录为 `no_data` 并保留历史校准与静态空间模型。

### API 凭据调用量与实测耗时

以下基准来自 2026-08-27 14:41–14:43 的一次真实 `refresh-all`。当轮和风缓存命中 1 次，实际网络请求为 27 次；完全冷启动按 28 次估算。代码中的单轮上限用于控制一次命令的请求规模，供应商账户的日/月额度以各自控制台为准。

| 凭据或接口 | 单轮实测 | 单轮代码上限 | 每天完整刷新 1 次 | 30 天完整刷新 30 次 |
| --- | ---: | ---: | ---: | ---: |
| 和风 `QWEATHER_API_KEY` | 27 次 | 80 次 | 27–28 次 | 810–840 次 |
| Google `POLLEN_API_KEY` | 54 次 | 60 次 | 54 次 | 1,620 次 |
| 上海噪声 `SHANGHAI_NOISE_TOKEN` | 4 次 | 4 次 | 4 次 | 120 次 |
| 上海空气质量站点公开接口 | 4 次 | 独立计数 | 4 次 | 120 次 |
| 合计 | 89 次 | 分来源控制 | 89–90 次 | 2,670–2,700 次 |

本次完整命令耗时 96.679 秒，各阶段记录如下：

| 阶段 | 调用量 | 实测耗时 |
| --- | ---: | ---: |
| 天气、空气质量、上海站点与当前 PM2.5 融合 | 和风 27 次、上海站点 4 次 | 19.946 秒 |
| 上海噪声观测 | 4 次 | 约 2.4 秒 |
| 54 格花粉、网格暴露、7,366 个路段和 90 条路线导出 | Google 花粉 54 次及本地计算 | 约 74.3 秒 |
| 完整 `refresh-all` | 89 次网络请求 | 96.679 秒 |

地图服务采用分层刷新：天气与预警每 15 分钟，空气质量、上海站点和当前 PM2.5 每小时，花粉、噪声与路线暴露每天一次。天气层会按 `valid_until` 复用 24 小时预报缓存。小时层按每天 23 次 `refresh` 加 1 次 `refresh-all` 估算，和风为 648–672 次/天、19,440–20,160 次/30 天；Google 花粉为 54 次/天、1,620 次/30 天；上海噪声为 4 次/天、120 次/30 天；上海站点为 96 次/天、2,880 次/30 天。天气层额外调用量取决于当前天气、预警和预报缓存到期时间。

地图页面读取最近一次原子写出的 JSON，后台定时任务负责刷新。页面加载与 `refresh-all` 的 96.679 秒后台耗时相互分离。若每小时执行完整 `refresh-all`，30 天网络请求约为 64,080–64,800 次，会重复消耗日级花粉和历史噪声接口额度。

WeatherCN 普通 Key 探针保持独立：

```powershell
weather-api-data probe-standard --point-id XH_ENT_0001 --confirm-standard-probe
```

以下命令用于单项诊断和本地重建：

```powershell
weather-api-data probe-pollen --grid-id XH_PM25_G001 --confirm-pollen-probe
weather-api-data prepare-noise-data
weather-api-data probe-noise --point-id 310104320001 --confirm-noise-probe
weather-api-data refresh-noise
weather-api-data build-noise
weather-api-data refresh-exposure
weather-api-data build-static-exposure
weather-api-data build-static-exposure --spatial-features config/noise_spatial_features.geojson
```

`refresh-exposure` 使用独立的花粉与噪声调用预算；`build-noise` 只依赖路线、噪声模型配置和历史校准，可在 PM2.5 输出暂缺时单独生成 `noise_segments.json`。`build-static-exposure` 读取完整本地环境文件。示例 GeoJSON 路径需要替换为实际图层文件。

### 分层自动刷新与网页数据包

手动运行三档调度命令：

```powershell
weather-api-data scheduled-refresh --tier weather
weather-api-data scheduled-refresh --tier hourly
weather-api-data scheduled-refresh --tier daily
```

调度器使用 `runtime/scheduled_refresh.lock` 防止并发，运行状态原子写入 `runtime/scheduler_state.json`。刷新结果为 `partial` 时继续发布可用数据；刷新失败且已有网页快照时保留旧数据并标记 `stale`。

单独生成网页数据包：

```powershell
weather-api-data publish-web
```

输出为 `xuhui_route_builder/data/web/environment_dashboard.json`。该文件包含天气、预警、AQI、生活指数、24 小时预报、5 日花粉、54 个环境网格和 90 条路线环境结果。54 个 PM2.5 网格是基础空间数据；发布器读取后端 `noise_segments.json` 的网格归属与路段长度，使用当前 54 网格重新计算 90 条路线的长度加权 PM2.5，并保留日档花粉与噪声结果。接驳路径环境聚合状态固定为 `not_aggregated`。

Windows 本机安装、查看和卸载计划任务：

```powershell
.\scripts\install_windows_tasks.ps1 -Action Install
.\scripts\install_windows_tasks.ps1 -Action Status
.\scripts\install_windows_tasks.ps1 -Action Uninstall
```

三个任务分别在每 15 分钟、每小时第 2 分钟和每天 06:07 运行。任务支持错过后补跑、失败重试和重复实例拦截。GitHub Actions 工作流 `.github/workflows/environment-refresh.yml` 当前仅支持手动触发；仓库公开后再配置定时触发。工作流从 GitHub Secrets 读取和风、花粉和噪声凭据，生成 Pages artifact，不写入 Git 历史。

## 5. 本地输出与历史

`runtime/` 整体受 `.gitignore` 保护：

- `runtime/archive/`：递归脱敏的 GZIP 原始响应
- `noise_data/`：上海噪声历史 CSV、徐汇清洗观测和历史校准基线
- `runtime/history/weather.sqlite`：天气、空气质量、预报、指数、预警和气候实测历史库
- `runtime/cache/refresh_cache.json`：业务端点有效期缓存
- `runtime/exports/environment_regions.json`：采样点、11 区配置、活动提供方和参考来源
- `runtime/exports/environment_latest.json`：天气实况、3 日生活指数、预警、当前 AQI 与 11 区污染物
- `runtime/exports/environment_hourly.json`：未来 24 小时天气与 AQI、本地近 24 小时天气观测
- `runtime/exports/pm25_grid_latest.json`：当前 54 格 PM2.5 估计
- `runtime/exports/pm25_grid_forecast_24h.json`：仅在上游提供未来 PM2.5 浓度时生成
- `runtime/exports/grid_environment_latest.json`：54 格 PM2.5、同日花粉和网格内路线覆盖段噪声汇总
- `runtime/exports/route_environment.json`：按 `route_id` 汇总的路线多源暴露

每次成功获取参考点天气实况后都会写入 SQLite。导出窗口按上海本地最近 24 个整点选取记录，同一小时优先选择业务时间较新的记录，业务时间相同再选择获取时间较新的记录。窗口只返回真实观测并列出缺失小时，未积满 24 小时时状态为 `partial`，没有记录时状态为 `no_data`。

## 6. 当前数据契约

| 数据 | 本地入口 | 空间口径 | 时间口径 |
| --- | --- | --- | --- |
| 天气实况 | `current_weather` | 参考点 `XH_ENT_0009` | 当前观测 |
| 过去 24 小时天气 | `weather_history_24h` 与摘要 | 参考来源 | 上海本地最近 24 个整点 |
| 未来 24 小时天气 | `weather_forecast_24h` | 参考来源 | 未来 24 小时逐小时 |
| 生活指数 | `daily_indices_3day` | 参考来源 | 未来 3 天 |
| 天气预警 | `active_alerts` | 参考来源 | 当前有效预警 |
| 当前综合 AQI | `xuhui_aqi` | 参考来源投影 | 当前观测 |
| 当前污染物 | `point_air_quality` | 11 个空气质量输出区 | 当前观测与融合结果 |
| 未来 AQI | `xuhui_aqi_forecast_24h` | 参考来源与 AQ 实际使用点 | 中国地区未来 24 小时逐小时仅有 AQI |
| 未来 PM2.5 | `xuhui_pm2_5_forecast_24h` | 依赖和风小时污染物浓度 | 中国地区当前缺值，状态保留 `partial` |
| 当前 PM2.5 网格 | `pm25_grid_latest.json` | 54 个 1 km 网格 | 最新参考观测时刻 |
| 未来 PM2.5 网格 | `pm25_grid_forecast_24h.json` | 24 小时 × 54 格 | 中国地区当前缺少输入，未生成 |
| 花粉风险 | `pollen_grid_scores.json` | 54 个网格中心 | 当天及未来最多 4 天 |
| 噪声风险 | `noise_segments.json` | 路线约 100 米稳定路段 | 静态及时段情景 |
| 噪声观测上下文 | `noise_observation_latest.json` | 徐汇四个监测点位 | API 最新可用观测 |
| 路线多源暴露 | `route_environment.json` | 按 `route_id` 汇总 | 各来源业务时间 |

## 7. PM2.5 当前与未来空间输出

`refresh-all` 使用 `environment_regions.json` 顶层 `reference_source_id` 查询 SQLite 参考观测与预报。当前链路为：和风参考点 PM2.5 → 2025 年同月 CHAP 空间偏差中位数 → 徐家汇站和冠生园路 458 号站残差距离加权 → 54 格均值回归参考点。未来链路仅在上游返回 24 条唯一逐小时 PM2.5 预报时生成每小时 54 格和 11 区结果。

输出统一记录 `provider=qweather` 与真实 `source_id`。网格值属于空间估计，同一网格内相邻道路共享数值；未来网格缺少同期站点实测残差，全部标记为预测估计。54 格、11 区、站点完整性或参考来源一致性校验失败时，融合会停止写出。

和风官方[中国空气质量说明](https://dev.qweather.com/docs/api/air-quality/china-aqi/)明确，中国地区的空气质量预报暂不支持污染物详细数据。本项目在上海目前只能获取未来 24 小时 AQI，未来 PM2.5 浓度没有返回；AQI 无法可靠反推 PM2.5，代码保留缺值。

2026 年 8 月 26 日 19:52 的真实验证中，12 个 AQ 坐标的 24 小时预报均返回 AQI，`pollutants` 均为空数组。系统保留 AQI 为 `partial` 记录，PM2.5 与其他污染物保留缺值，未来 54 格融合报告 `error`；当前 54 格与已成功环境输出继续交付，整体状态为 `partial`。同名旧预测文件会移入 `runtime/exports/stale/` 留档，刷新报告记录具体路径。

## 8. 花粉、噪声与路线暴露

花粉链路为：54 个 PM2.5 网格中心 → Google Pollen 日值 → 风速、降雨和湿度修正 → `pollen_grid_scores.json`。Google Key 只写入本地 `.env`，首轮真实调用前先运行单点探针。

噪声链路分为两部分：上海历史观测 → 徐汇四站清洗与 LAeq 中位数基线 → 20% 全区尺度锚定；GCJ-02 路线 → WGS84 → EPSG:32651 米制切段 → 80% 道路、距离、POI、路口、声功能区和绿地水体特征 → `noise_segments.json`。结果继续输出 0–100 风险与四类时段情景，`estimated=true`。公开数据缺少站点坐标，路线局部排序仍依赖空间代理特征，输出中不含路段分贝值。

路线聚合按稳定 `segment_id` 将 PM2.5 网格、花粉网格和噪声路段按实际长度汇总到 `route_environment.json`。任一来源缺失时，对应路线状态保留 `partial`。

区域展示时，花粉按相同 `grid_id` 和日期读取约 1 km 日值；噪声按 `pm25_grid_id` 汇总落入该网格的路线段，并按 `length_m` 加权计算静态与分时风险。该值属于网格内路线覆盖段代理，继续保留 `estimated=true`、覆盖段数量、覆盖长度和置信度。

## 9. 历史清理

```powershell
weather-api-data prune-history --dry-run
weather-api-data prune-history --apply
```

清理边界为当前 UTC 时间减去 365 天。严格早于边界的 SQLite 业务记录和 GZIP 归档进入清理集，等于边界的数据保留。

## 10. 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pyright --pythonpath .\.venv\Scripts\python.exe
rg -n -I "(QWEATHER_API_KEY=[^< ]{16,}|WEATHERCN_.*(KEY|SECRET)=[^< ]{16,}|POLLEN_API_KEY=[^< ]{16,}|SHANGHAI_NOISE_TOKEN=[^< ]{16,}|(X-QW-Api-Key|X-Gw-API-Key|accessKey)[^A-Za-z0-9]{1,8}[A-Za-z0-9+/=_-]{20,})" . -g "!.env" -g "!.env.example" -g "!README.md" -g "!相关文档/**" -g "!tests/**" -g "!runtime/**" -g "!.venv/**"
```

自动测试覆盖和风专属 Host 与认证头、稳定来源标识、坐标顺序、单位与时间标准化、硬上限、超时与重试、脱敏、11 区空气质量、24 小时历史窗口、54 格当前与未来 PM2.5、SQLite 事务、原子导出、缓存和历史清理边界。
