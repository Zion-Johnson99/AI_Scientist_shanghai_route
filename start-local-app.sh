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
  "$route_python" - "$dashboard_path" "$action" <<'PY'
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

path = Path(sys.argv[1])
action = sys.argv[2]


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

refresh_environment() {
  local tier update_time
  tier="$(dashboard_info tier)"
  if [[ -z "$tier" ]]; then
    update_time="$(dashboard_info time)"
    echo "环境数据未更新，上次更新时间：$update_time。"
    return
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
  update_time="$(dashboard_info time)"
  echo "环境数据已更新，更新时间：$update_time。"
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

refresh_environment

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
    if ! refresh_environment; then
      echo "警告：运行期间环境数据刷新失败，继续使用上一份数据。" >&2
    fi
  fi
done
