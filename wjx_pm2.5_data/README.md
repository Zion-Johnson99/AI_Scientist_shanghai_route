## PM2.5 1 km data

Source dataset:
- CHAP `ChinaHighPM2.5: Daily Seamless 1 km Ground-Level PM2.5 Dataset for China (2000-2021)`
- Record: `https://zenodo.org/records/6398971`
- Downloaded file: `CHAP_PM2.5_D1K_2021_V4.rar`

This folder currently stores:
- `CHAP_PM2.5_D1K_2021_shanghai_daily.nc`: Shanghai daily PM2.5 subset for all of 2021
- `cnemc_hourly_2021_shanghai/`: Shanghai hourly station PM2.5 tables for 2021

Data fields:
- Variable: `PM2.5`
- Resolution: `1 km`
- Time meaning: `daily grids from 2021-01-01 to 2021-12-31`

Subset bounding box used for Shanghai:
- Longitude: `120.85` to `122.15`
- Latitude: `30.65` to `31.90`

Local raw files were also saved outside the repo at:
- `/public/Jbgs/wjx/CHAP_PM2.5_D1K_2021_V4.rar`
- `/public/Jbgs/wjx/CHAP_PM2.5_D1K_2021_extracted/`
- `/public/Jbgs/wjx/CHAP_PM2.5_D1K_2021_shanghai_daily.nc`

Updated data availability check on `2026-08-13`:
- CHAP has a newer Zenodo record `ChinaHighPM2.5 (2022-Present)`: `https://zenodo.org/records/15208529`
- That newer record is marked `restricted`, so the files were not directly downloadable in this environment
- The latest publicly downloadable daily 1 km dataset we could actually fetch here is still the `2021` release above
