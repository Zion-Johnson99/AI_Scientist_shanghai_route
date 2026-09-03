"""Keyless Open-Meteo fetcher for the four Xuhui sample points.

Standard library only. Raw responses are stored verbatim under ``sources/``
and two registry lines (SRC-009, SRC-010) are appended. If a field comes back
all-null it is reported as unavailable, never backfilled.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_ROOT = Path(__file__).resolve().parents[3]
SOURCES_DIR = RUN_ROOT / "sources"
FORECAST_ARTIFACT = SOURCES_DIR / "open_meteo_forecast.json"
AIR_QUALITY_ARTIFACT = SOURCES_DIR / "open_meteo_air_quality.json"
REGISTRY_PATH = SOURCES_DIR / "source_registry.jsonl"

FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_ENDPOINT = "https://air-quality-api.open-meteo.com/v1/air-quality"

FORECAST_HOURLY = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,"
    "precipitation,wind_speed_10m,wind_gusts_10m"
)
AIR_QUALITY_HOURLY = "pm2_5,us_aqi"

SAMPLE_POINTS: dict[str, tuple[float, float]] = {
    "centroid": (121.4370, 31.1885),
    "northwest": (121.4050, 31.2080),
    "east": (121.4620, 31.1900),
    "south": (121.4300, 31.1150),
}

FORECAST_FIELD_TO_KEY: dict[str, str] = {
    "temperature_2m": "temperature_c",
    "apparent_temperature": "feels_like_c",
    "relative_humidity_2m": "humidity_pct",
    "precipitation": "precipitation_mm",
    "wind_speed_10m": "wind_speed_kmh",
    "wind_gusts_10m": "wind_gust_kmh",
}
AIR_QUALITY_FIELD_TO_KEY: dict[str, str] = {
    "pm2_5": "pm25_ug_m3",
    "us_aqi": "aqi_us",
}

MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_S = 30.0
USER_AGENT = "AI-Scientist-Xuhui-Environment/1.0 (research run; contact: local)"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_url(endpoint: str, lon: float, lat: float, hourly: str) -> str:
    query = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "hourly": hourly,
            "timezone": "Asia/Shanghai",
            "forecast_days": "2",
        }
    )
    return f"{endpoint}?{query}"


def fetch_json(url: str) -> tuple[dict[str, Any] | None, str | None]:
    """GET a URL with up to 3 attempts; return (payload, error_message)."""
    last_error: str | None = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(2.0**attempt)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
                return payload, None
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            http.client.HTTPException,
            OSError,
        ) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return None, last_error


def fetch_service(endpoint: str, hourly: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Fetch every sample point; return (url_map, response_map, failures)."""
    url_map: dict[str, str] = {}
    response_map: dict[str, Any] = {}
    failures: list[str] = []
    for name, (lon, lat) in SAMPLE_POINTS.items():
        url = build_url(endpoint, lon, lat, hourly)
        url_map[name] = url
        payload, error = fetch_json(url)
        if payload is None:
            failures.append(f"{name}: {error}")
        else:
            response_map[name] = payload
    return url_map, response_map, failures


def save_wrapper(path: Path, url_map: dict[str, str], response_map: dict[str, Any]) -> None:
    wrapper = {"fetched_at": _utc_now_iso(), "url": url_map, "response": response_map}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(wrapper, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def append_registry(entries: list[dict[str, Any]]) -> list[str]:
    """Append entries whose source_id is not yet registered; return added ids."""
    existing_ids: set[str] = set()
    if REGISTRY_PATH.exists():
        for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record: dict[str, Any] = json.loads(line)
            existing_ids.add(str(record.get("source_id")))
    added: list[str] = []
    with REGISTRY_PATH.open("a", encoding="utf-8") as handle:
        for entry in entries:
            source_id = str(entry["source_id"])
            if source_id in existing_ids:
                continue
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            added.append(source_id)
    return added


def field_availability(wrapper: dict[str, Any], field_map: dict[str, str]) -> dict[str, bool]:
    """True per contract key when at least one non-null value exists anywhere."""
    available: dict[str, bool] = {key: False for key in field_map.values()}
    response_map = wrapper.get("response")
    if not isinstance(response_map, dict):
        return available
    for payload in response_map.values():
        if not isinstance(payload, dict):
            continue
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            continue
        for api_field, key in field_map.items():
            series = hourly.get(api_field)
            if isinstance(series, list) and any(value is not None for value in series):
                available[key] = True
    return available


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fetch_public", description=__doc__)
    parser.add_argument("--skip-registry", action="store_true", help="do not append registry lines")
    args = parser.parse_args(argv)

    accessed_at = _utc_now_iso()
    forecast_urls, forecast_responses, forecast_failures = fetch_service(
        FORECAST_ENDPOINT, FORECAST_HOURLY
    )
    air_urls, air_responses, air_failures = fetch_service(AIR_QUALITY_ENDPOINT, AIR_QUALITY_HOURLY)

    total_points = len(SAMPLE_POINTS) * 2
    failed_points = len(forecast_failures) + len(air_failures)

    if forecast_responses:
        save_wrapper(FORECAST_ARTIFACT, forecast_urls, forecast_responses)
    if air_responses:
        save_wrapper(AIR_QUALITY_ARTIFACT, air_urls, air_responses)

    if not args.skip_registry:
        entries: list[dict[str, Any]] = []
        if forecast_responses:
            entries.append(
                {
                    "source_id": "SRC-009",
                    "title": "Open-Meteo Forecast API - hourly weather for 4 Xuhui sample points",
                    "url": build_url(FORECAST_ENDPOINT, *SAMPLE_POINTS["centroid"], FORECAST_HOURLY),
                    "endpoint": FORECAST_ENDPOINT,
                    "endpoint_urls": forecast_urls,
                    "kind": "public_api_measurement",
                    "data_kind": "public_api_measurement",
                    "publisher": "Open-Meteo.com",
                    "licence": "CC BY 4.0 (Open-Meteo)",
                    "access_status": "accessed" if not forecast_failures else "partial",
                    "accessed_at": accessed_at,
                    "purpose": "Measured hourly weather (temperature, feels-like, humidity, precipitation, wind, gusts) assigned to the 54-cell environment grid by nearest sample point.",
                    "local_artifact": "sources/open_meteo_forecast.json",
                }
            )
        if air_responses:
            entries.append(
                {
                    "source_id": "SRC-010",
                    "title": "Open-Meteo Air Quality API - hourly pm2_5 and us_aqi for 4 Xuhui sample points",
                    "url": build_url(AIR_QUALITY_ENDPOINT, *SAMPLE_POINTS["centroid"], AIR_QUALITY_HOURLY),
                    "endpoint": AIR_QUALITY_ENDPOINT,
                    "endpoint_urls": air_urls,
                    "kind": "public_api_measurement",
                    "data_kind": "public_api_measurement",
                    "publisher": "Open-Meteo.com",
                    "licence": "CC BY 4.0 (Open-Meteo)",
                    "access_status": "accessed" if not air_failures else "partial",
                    "accessed_at": accessed_at,
                    "purpose": "Measured hourly PM2.5 and US AQI assigned to the 54-cell environment grid by nearest sample point.",
                    "local_artifact": "sources/open_meteo_air_quality.json",
                }
            )
        added = append_registry(entries)
        print(f"registry appended: {added if added else 'nothing (ids already present)'}")

    forecast_availability = field_availability(
        {"response": forecast_responses}, FORECAST_FIELD_TO_KEY
    )
    air_availability = field_availability({"response": air_responses}, AIR_QUALITY_FIELD_TO_KEY)
    print(f"points fetched: {total_points - failed_points}/{total_points}")
    print(f"weather fields with real values: {sorted(k for k, v in forecast_availability.items() if v)}")
    print(f"weather fields all-null: {sorted(k for k, v in forecast_availability.items() if not v)}")
    print(f"air fields with real values: {sorted(k for k, v in air_availability.items() if v)}")
    print(f"air fields all-null: {sorted(k for k, v in air_availability.items() if not v)}")
    for failure in [*forecast_failures, *air_failures]:
        print(f"FAILED {failure}", file=sys.stderr)

    if failed_points == total_points:
        print(
            "network entirely unavailable: no Open-Meteo response could be fetched; "
            "downstream modules must run in degraded mode (status=unavailable)",
            file=sys.stderr,
        )
        return 2
    if failed_points:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
