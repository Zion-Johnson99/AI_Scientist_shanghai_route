#!/usr/bin/env bash
set -Eeuo pipefail

use_qwen=0
case "${1:-}" in
  "") ;;
  --use-qwen) use_qwen=1 ;;
  *)
    echo "用法：bash ./start-local-app.sh [--use-qwen]" >&2
    exit 2
    ;;
esac
if (( $# > 1 )); then
  echo "用法：bash ./start-local-app.sh [--use-qwen]" >&2
  exit 2
fi

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
evaluation_root="$repository_root/evaluation_model_qwen"
route_root="$repository_root/xuhui_route_builder"
weather_root="$repository_root/weather_api_data"
api_executable="$evaluation_root/.venv/bin/evaluation-model-qwen-api"
route_python="$route_root/.venv/bin/python"
weather_executable="$weather_root/.venv/bin/weather-api-data"
weather_env_file="$weather_root/.env"
dashboard_path="$route_root/data/web/environment_dashboard.json"
runtime_root="$evaluation_root/runtime/local-app"
api_health_url="http://127.0.0.1:8124/api/v1/health"
web_url="http://127.0.0.1:8123/web/"
environment_check_interval_seconds=1800
startup_cache_max_age_minutes=30
started_pids=()

if [[ ! -x "$api_executable" ]]; then
  echo "缺少推荐服务，请先在 evaluation_model_qwen 目录运行 uv sync --extra dev。" >&2
  exit 1
fi
if [[ ! -x "$route_python" ]]; then
  echo "缺少路线模块的 Python 虚拟环境。" >&2
  exit 1
fi
mkdir -p "$runtime_root"

dashboard_info() {
  local action="$1"
  "$route_python" - "$dashboard_path" "$action" "$startup_cache_max_age_minutes" <<'PY'
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

path = Path(sys.argv[1])
action = sys.argv[2]
max_age_minutes = int(sys.argv[3])


def parse_time(value):
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def expired(record, now, margin_minutes=0):
    if not isinstance(record, dict):
        return True
    if record.get("status") in {"stale", "no_data"}:
        return True
    valid_until = parse_time(record.get("valid_until") or record.get("expires_at"))
    return valid_until is not None and valid_until <= now + timedelta(minutes=margin_minutes)


def load_dashboard():
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


dashboard = load_dashboard()
if action == "time":
    value = dashboard.get("metadata", {}).get("generated_at") if dashboard else None
    timestamp = parse_time(value)
    print(timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S") if timestamp else "未知")
    raise SystemExit

if action == "startup-cache-fresh":
    value = dashboard.get("metadata", {}).get("generated_at") if dashboard else None
    timestamp = parse_time(value)
    if timestamp is None:
        print("false")
        raise SystemExit
    age_seconds = (datetime.now().astimezone() - timestamp).total_seconds()
    print(str(0 <= age_seconds < max_age_minutes * 60).lower())
    raise SystemExit

if dashboard is None:
    print("daily")
    raise SystemExit

now = datetime.now().astimezone()
current = dashboard.get("current", {})
life_indices = current.get("life_indices") or []
routes = dashboard.get("routes", {}).get("items") or []
if not life_indices or not routes or any(expired(item, now) for item in life_indices):
    print("daily")
    raise SystemExit

route = routes[0]
noise_time = parse_time((route.get("noise") or {}).get("fetched_at"))
pollen = [
    item
    for item in (route.get("pollen_daily") or [])
    if item.get("business_time") == now.date().isoformat()
]
if (
    noise_time is None
    or noise_time <= now - timedelta(hours=24)
    or not pollen
    or expired(pollen[0], now)
):
    print("daily")
    raise SystemExit

pm25_time = parse_time((route.get("pm2_5") or {}).get("business_time"))
if (
    expired(current.get("aqi"), now, margin_minutes=5)
    or pm25_time is None
    or pm25_time <= now - timedelta(hours=1)
):
    print("hourly")
elif expired(current.get("weather"), now, margin_minutes=5):
    print("weather")
PY
}

print_refresh_summary() {
  local mode="${1:-refresh}"
  "$route_python" - \
    "$runtime_root/environment-refresh.stdout.log" \
    "$dashboard_path" \
    "$mode" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

report_path = Path(sys.argv[1])
dashboard_path = Path(sys.argv[2])
mode = sys.argv[3]


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"环境数据刷新结果无法解析：{error}") from error


def local_time(value):
    if value is None:
        return "未知"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def number(value, digits):
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "未知"


dashboard = load_json(dashboard_path)
if mode == "refresh":
    report = load_json(report_path)
    run_status = str(report.get("status", "未知"))
    publish_status = str((report.get("publish") or {}).get("status", "未知"))
    update_time = local_time((dashboard.get("metadata") or {}).get("generated_at"))
    if publish_status == "stale":
        print(
            f"警告：环境数据未生成新快照，继续使用上次数据，"
            f"更新时间：{update_time}。",
            file=sys.stderr,
        )
    else:
        print(f"环境数据已发布，状态：{run_status}，更新时间：{update_time}。")
    if run_status == "partial":
        print(
            "警告：本轮部分环境数据源已降级，"
            "详情见下方站点摘要和刷新日志。",
            file=sys.stderr,
        )
    fusion = (report.get("refresh") or {}).get("pm25_grid_fusion") or {}
else:
    fusion = (dashboard.get("metadata") or {}).get("pm2_5_fusion") or {}
stations = fusion.get("stations") or []
if not stations:
    print("警告：本轮未返回 PM2.5 站点时间与权重。", file=sys.stderr)
for station in stations:
    station_id = station.get("station_id", "未知")
    age_minutes = station.get("age_minutes")
    print(
        f"站点 {station_id}：观测时间 {local_time(station.get('observed_at'))}，"
        f"滞后 {number(age_minutes, 0)} 分钟，"
        f"时间权重 {number(station.get('temporal_weight_factor'), 3)}，"
        f"网格权重范围 {number(station.get('grid_weight_min'), 3)}-"
        f"{number(station.get('grid_weight_max'), 3)}。"
    )
    if not station.get("included", False):
        print(
            f"警告：站点 {station_id} 滞后已达 24 小时，本轮已剔除。",
            file=sys.stderr,
        )
    elif isinstance(age_minutes, (int, float)) and age_minutes > 180:
        print(
            f"警告：站点 {station_id} 滞后超过 3 小时，"
            "本轮已降低融合权重。",
            file=sys.stderr,
        )
PY
}

refresh_environment() {
  local mode="${1:-continuous}" tier update_time
  tier="$(dashboard_info tier)"
  if (
    [[ "$mode" == "startup" ]] \
    && [[ -z "$tier" ]] \
    && [[ "$(dashboard_info startup-cache-fresh)" == "true" ]]
  ); then
    update_time="$(dashboard_info time)"
    echo "环境数据缓存仍有效，更新时间：$update_time。"
    print_refresh_summary "cache"
    return 0
  elif [[ "$mode" == "startup" && "$tier" != "daily" ]]; then
    tier="hourly"
  elif [[ -z "$tier" ]]; then
    return 0
  fi
  if [[ ! -x "$weather_executable" ]]; then
    echo "缺少环境数据服务，请先在 weather_api_data 目录完成依赖安装。" >&2
    return 1
  fi
  if [[ ! -f "$weather_env_file" ]]; then
    echo "缺少 weather_api_data/.env，无法更新环境数据。" >&2
    return 1
  fi
  if ! "$weather_executable" \
    --root "$weather_root" \
    --env-file "$weather_env_file" \
    scheduled-refresh --tier "$tier" \
    >"$runtime_root/environment-refresh.stdout.log" \
    2>"$runtime_root/environment-refresh.stderr.log"
  then
    echo "环境数据刷新失败，日志目录：$runtime_root" >&2
    return 1
  fi
  if [[ ! -f "$dashboard_path" ]]; then
    echo "环境数据更新后缺少网页数据包，日志目录：$runtime_root" >&2
    return 1
  fi
  print_refresh_summary
}

http_ready() {
  "$route_python" - "$1" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=2) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
}

health_value() {
  "$route_python" - "$api_health_url" "$1" <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=3) as response:
    health = json.load(response)
value = health["qwen"][sys.argv[2]]
print(str(value).lower() if isinstance(value, bool) else value)
PY
}

assert_port_available() {
  local port="$1" service_name="$2"
  if ! "$route_python" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

with socket.socket() as sock:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
PY
  then
    echo "$service_name 启动失败：端口 $port 已被占用。" >&2
    exit 1
  fi
}

wait_service_ready() {
  local uri="$1" pid="$2" service_name="$3"
  local attempt
  for attempt in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "$service_name 启动后提前退出。" >&2
      exit 1
    fi
    if http_ready "$uri"; then
      return
    fi
    sleep 0.5
  done
  echo "$service_name 在 15 秒内没有通过健康检查：$uri" >&2
  exit 1
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  local pid
  for pid in "${started_pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${started_pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  if (( ${#started_pids[@]} > 0 )); then
    echo "本次启动的本地服务已停止。"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

refresh_environment "startup"

offline_mode=1
mode_label="本地 Python 排序"
if (( use_qwen == 1 )); then
  offline_mode=0
  mode_label="千问审核，异常时回退本地排序"
fi

if http_ready "$api_health_url"; then
  existing_offline="$(health_value offline)"
  requested_offline="true"
  if (( use_qwen == 1 )); then
    requested_offline="false"
  fi
  if [[ "$existing_offline" != "$requested_offline" ]]; then
    echo "推荐服务正在使用另一种运行模式，请先在原命令窗口按 Ctrl+C，再重新执行当前命令。" >&2
    exit 1
  fi
  echo "推荐服务已运行，继续复用 8124 端口。"
else
  assert_port_available 8124 "推荐服务"
  EVALUATION_MODEL_QWEN_OFFLINE="$offline_mode" \
    "$api_executable" --host 127.0.0.1 --port 8124 \
    >"$runtime_root/api.stdout.log" \
    2>"$runtime_root/api.stderr.log" &
  api_pid=$!
  started_pids+=("$api_pid")
  wait_service_ready "$api_health_url" "$api_pid" "推荐服务"
  echo "推荐服务已启动：$mode_label"
fi

if (( use_qwen == 1 )) && [[ "$(health_value configured)" != "true" ]]; then
  echo "警告：千问配置尚未完成，当前请求会回退到本地 Python 排序。" >&2
fi

if http_ready "$web_url"; then
  echo "网页服务已运行，继续复用 8123 端口。"
else
  assert_port_available 8123 "网页服务"
  (
    cd "$route_root"
    exec "$route_python" "-m" "http.server" "8123" --bind 127.0.0.1
  ) >"$runtime_root/web.stdout.log" 2>"$runtime_root/web.stderr.log" &
  web_pid=$!
  started_pids+=("$web_pid")
  wait_service_ready "$web_url" "$web_pid" "网页服务"
  echo "网页服务已启动。"
fi

echo "正在打开 $web_url"
if command -v open >/dev/null 2>&1; then
  open "$web_url" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$web_url" >/dev/null 2>&1 || true
fi

echo "完整本地应用正在运行。按 Ctrl+C 统一停止本次启动的服务。"
next_environment_check=$(( $(date +%s) + environment_check_interval_seconds ))
while true; do
  sleep 1
  for pid in "${started_pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "本地服务进程 $pid 已退出，日志目录：$runtime_root" >&2
      exit 1
    fi
  done
  now_epoch="$(date +%s)"
  if (( now_epoch >= next_environment_check )); then
    next_environment_check=$(( now_epoch + environment_check_interval_seconds ))
    if ! refresh_environment "continuous"; then
      echo "警告：运行期间环境数据刷新失败，继续使用上一份数据。" >&2
    fi
  fi
done
