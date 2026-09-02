# Refresh & Fallback

## 固定命令

```powershell
uv run --directory weather_api_data --frozen weather-api-data config-check
uv run --directory weather_api_data --frozen weather-api-data dry-run
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier weather
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier hourly
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier daily
uv run --directory weather_api_data --frozen weather-api-data publish-web
```

## 刷新层级映射（Harness）

| 选项 | 命令 |
| --- | --- |
| `weather` | `scheduled-refresh --tier weather` |
| `hourly` | `scheduled-refresh --tier hourly` |
| `daily` | `scheduled-refresh --tier daily` |
| `none` | 使用 last-known-good 快照 |

## 顺序与前置

- `config-check` 和 `dry-run` 必须先于刷新执行。
- 刷新的非 `none` 值要求网络授权与对应 Key。

## 回退规则

- 缺 Key：使用 last-known-good，不创建填充值；记录 `stale`/`partial` 与 `stale_reason`。
- 上游异常：记录错误类型、来源、尝试次数与回退快照。
- API 硬限额、429、超时簇：触发停止，保留参数、缓存状态与错误上下文。
- 每次实验冻结环境快照；后续迭代需要新快照时显式记录新旧哈希与原因。

## 在线更新背景

公开网站采用分层更新：Cloudflare 每 15 分钟触发天气主刷新，GitHub Actions 提供错峰备份、小时级空气质量更新和每日完整更新。单个来源异常时保留上一份可用结果并标注状态。
