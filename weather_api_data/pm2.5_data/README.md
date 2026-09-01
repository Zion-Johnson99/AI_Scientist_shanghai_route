# PM2.5 数据说明

本目录保存 CHAP ChinaHighPM2.5 的日均 1 km 网格估算数据。数据来源于 Zenodo，采用 CC BY 4.0 许可。

## 2025 年徐汇区数据

目录：`xuhui_pm2.5_2025_1km/`

- `origin_data/CHAP_PM2.5_D1K_2025_V4.rar`：2025 年全国原始压缩包，约 2.69 GB，仅保留在本地，不随 Git 上传。
- `xuhui_data/CHAP_PM2.5_D1K_2025_xuhui_V4.nc`：从原始数据中裁剪得到的徐汇区 NetCDF 文件，约 70 KB，可随 Git 上传。
- 时间范围：2025 年 1 月 1 日至 2025 年 12 月 31 日，共 365 天。
- 时间粒度：日均值。
- 空间粒度：1 km 网格；按网格中心是否落入徐汇区边界筛选，共保留 54 个有效网格。
- 主要变量：`pm2_5_ug_m3` 为 PM2.5 浓度，单位为 μg/m³；`xuhui_mask` 标记徐汇区有效网格。
- 数据来源：[Zenodo 记录 21770406](https://zenodo.org/records/21770406)，版本 V4。

## 2021 年上海数据

文件：`CHAP_PM2.5_D1K_2021_shanghai_daily.nc`

该文件为 CHAP ChinaHighPM2.5 2021 年上海区域日均 1 km 网格数据，时间范围为 2021 年 1 月 1 日至 12 月 31 日，共 365 天，主要变量为 `PM2.5`。数据来源：[Zenodo 记录 6398971](https://zenodo.org/records/6398971)。
