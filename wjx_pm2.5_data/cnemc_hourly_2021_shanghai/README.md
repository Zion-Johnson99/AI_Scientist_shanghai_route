## Shanghai hourly station PM2.5 data for 2021

Source dataset:
- CNEMC historical site observations archived on Zenodo
- Record: `https://zenodo.org/records/10823812`
- Source statement on the record page: historical monitoring data of air quality sites across China from CNEMC

This folder stores:
- `shanghai_pm25_hourly_2021_long.csv`: long-format hourly PM2.5 table for Shanghai stations
- `shanghai_pm25_hourly_2021_wide.csv`: wide-format hourly PM2.5 table, one station per column
- `shanghai_pm25_hourly_2021_summary.csv`: valid-hour and missing-hour summary by station
- `shanghai_station_metadata.csv`: Shanghai station codes and coordinates
- `station.xlsx`: full national station metadata file from the source archive

Coverage:
- Year: `2021`
- Time resolution: `hourly`
- Shanghai stations included: `10`

Data quality note:
- The extracted hourly table contains `8700` hourly timestamps
- A full non-leap year would have `8760` hours
- The missing `60` hours are missing in the source archive rather than from the extraction step
- Station `1146A` (`青浦淀山湖`) has only `1` valid hourly PM2.5 record in this archive

Local raw file kept outside the repo:
- `/public/Jbgs/wjx/cnemc_hourly_2021_shanghai/20210101-20211231_CNEMC.zip`

Why the raw zip is not in git:
- The national source zip is about `244 MB`
- That exceeds normal GitHub file size limits for direct git push
