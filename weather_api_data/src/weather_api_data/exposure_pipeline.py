"""花粉、噪声与路线环境暴露的独立编排。"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import cast

import requests

from weather_api_data.config import Settings
from weather_api_data.exporter import export_exposure_documents
from weather_api_data.noise_model import build_noise_segments_document
from weather_api_data.noise_pipeline import refresh_noise_observations_from_project
from weather_api_data.pollen_client import PollenClient
from weather_api_data.pollen_model import (
    WeatherFactors,
    collect_pollen_grid_document,
    load_pollen_grid_points,
)
from weather_api_data.route_environment import build_route_environment_document


def weather_factors_from_documents(
    latest_document: Mapping[str, object],
    hourly_document: Mapping[str, object],
    *,
    location_key: str | None = None,
) -> dict[str, WeatherFactors]:
    """从标准化当前与逐小时天气文档生成日级花粉天气修正。"""

    resolved_location_key = location_key or _reference_source_id(
        latest_document,
        hourly_document,
    )
    forecast_records = _records(hourly_document.get("weather_forecast_24h"))
    current_records = _records(latest_document.get("current_weather"))
    factors = _aggregate_weather_by_date(
        forecast_records,
        location_key=resolved_location_key,
    )
    factors.update(
        _aggregate_weather_by_date(
            current_records,
            location_key=resolved_location_key,
        )
    )
    return factors


def _reference_source_id(
    latest_document: Mapping[str, object],
    hourly_document: Mapping[str, object],
) -> str:
    latest_source = latest_document.get("reference_source_id")
    hourly_source = hourly_document.get("reference_source_id")
    if not isinstance(latest_source, str) or not latest_source.strip():
        raise ValueError("当前环境文档缺少 reference_source_id")
    if latest_source != hourly_source:
        raise ValueError("当前与逐小时环境文档的 reference_source_id 不一致")
    return latest_source


def build_static_exposure_documents(
    *,
    output_dir: Path,
    routes_path: Path,
    pm25_grid_path: Path,
    noise_config_path: Path,
    spatial_features_path: Path | None = None,
    noise_calibration_path: Path | None = None,
    noise_observation_context: Mapping[str, object] | None = None,
    pollen_document: Mapping[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """生成本地噪声与路线聚合并复用已取得的花粉文档。"""

    pm25_document = _read_json(pm25_grid_path, "PM2.5 网格")
    noise_document = build_noise_segments_document(
        routes_path=routes_path,
        config_path=noise_config_path,
        spatial_features_path=spatial_features_path,
        calibration_path=noise_calibration_path,
        pm25_grid_path=pm25_grid_path,
    )
    if noise_observation_context is not None:
        noise_document["observation_context"] = dict(noise_observation_context)
    noise_segments = _records(noise_document.get("segments"))
    route_document = build_route_environment_document(
        route_segments=noise_segments,
        pm25_document=pm25_document,
        pollen_document=pollen_document,
        noise_segments=noise_segments,
        generated_at=generated_at,
    )
    grid_document = build_grid_environment_document(
        pm25_document=pm25_document,
        pollen_document=pollen_document,
        noise_document=noise_document,
        generated_at=generated_at,
    )
    documents: dict[str, Mapping[str, object]] = {
        "noise_segments.json": noise_document,
        "route_environment.json": route_document,
        "grid_environment_latest.json": grid_document,
    }
    if pollen_document is not None:
        documents["pollen_grid_scores.json"] = pollen_document
    paths = export_exposure_documents(
        output_dir,
        documents,
        generated_at=generated_at,
    )
    return {
        "status": route_document["status"],
        "route_count": route_document["route_count"],
        "segment_count": noise_document["segment_count"],
        "noise_status": noise_document["status"],
        "noise_calibration_status": noise_document["calibration_status"],
        "grid_environment_status": grid_document["status"],
        "pollen_status": pollen_document.get("status") if pollen_document else "no_data",
        "files": {name: str(path) for name, path in paths.items()},
    }


def build_grid_environment_document(
    *,
    pm25_document: Mapping[str, object],
    pollen_document: Mapping[str, object] | None,
    noise_document: Mapping[str, object],
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """按 PM2.5 网格汇总同日花粉和路线覆盖段噪声风险。"""

    pm25_grids = _records(pm25_document.get("grids"))
    target_time = str(pm25_document.get("target_time", ""))
    target_date = target_time[:10] if len(target_time) >= 10 else None
    pollen_records = _records(pollen_document.get("grid_scores")) if pollen_document else ()
    pollen_by_grid = {
        str(record.get("grid_id")): record
        for record in pollen_records
        if target_date is not None and record.get("forecast_date") == target_date
    }
    noise_by_grid: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for record in _records(noise_document.get("segments")):
        grid_id = record.get("pm25_grid_id")
        if isinstance(grid_id, str) and grid_id:
            noise_by_grid[grid_id].append(record)

    grids: list[dict[str, object]] = []
    for pm25_grid in pm25_grids:
        grid_id = str(pm25_grid.get("grid_id", ""))
        pollen = pollen_by_grid.get(grid_id)
        noise = _aggregate_grid_noise(noise_by_grid.get(grid_id, ()))
        grid_status = "ok"
        if pollen is None or pollen.get("status") != "ok" or noise["status"] != "ok":
            grid_status = "partial"
        grids.append(
            {
                **dict(pm25_grid),
                "pollen": dict(pollen) if pollen is not None else {"status": "no_data"},
                "noise": noise,
                "status": grid_status,
            }
        )
    return {
        "schema_version": "1.0",
        "dataset_type": "grid_environment_summary",
        "generated_at": (generated_at or datetime.now().astimezone()).isoformat(),
        "target_time": target_time or None,
        "pollen_forecast_date": target_date,
        "status": "partial" if any(grid["status"] != "ok" for grid in grids) else "ok",
        "grid_count": len(grids),
        "noise_semantics": "length_weighted_route_segments_within_assigned_pm25_grid",
        "grids": grids,
    }


def _aggregate_grid_noise(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not records:
        return {
            "status": "no_data",
            "estimated": True,
            "segment_count": 0,
            "route_count": 0,
            "covered_length_m": 0.0,
        }
    lengths = [_number(record.get("length_m"), "noise.length_m") for record in records]
    total_length = sum(lengths)
    if total_length <= 0:
        raise ValueError("噪声路线覆盖长度需大于 0")

    def weighted(name: str) -> float:
        values = [_number(record.get(name), f"noise.{name}") for record in records]
        return round(
            sum(value * length for value, length in zip(values, lengths, strict=True))
            / total_length,
            3,
        )

    scenario_names = ("daytime", "night", "weekday_offpeak", "weekday_peak")
    scenarios: dict[str, float] = {}
    for name in scenario_names:
        values = [
            _number(
                _mapping(record.get("scenario_risk_scores"), "scenario_risk_scores").get(name),
                name,
            )
            for record in records
        ]
        scenarios[name] = round(
            sum(value * length for value, length in zip(values, lengths, strict=True))
            / total_length,
            3,
        )
    confidence_order = {"low": 0, "medium": 1, "high": 2}
    confidence = min(
        (str(record.get("confidence", "low")) for record in records),
        key=lambda value: confidence_order.get(value, 0),
    )
    return {
        "status": "partial" if any(record.get("status") != "ok" for record in records) else "ok",
        "estimated": True,
        "noise_risk_score": weighted("noise_risk_score"),
        "scenario_risk_scores": scenarios,
        "segment_count": len(records),
        "route_count": len({str(record.get("route_id")) for record in records}),
        "covered_length_m": round(total_length, 3),
        "confidence": confidence,
    }


def refresh_exposure_from_local_sources(
    *,
    settings: Settings,
    session: requests.Session,
    output_dir: Path,
    routes_path: Path,
    pm25_grid_path: Path,
    pollen_model_path: Path,
    noise_config_path: Path,
    environment_latest_path: Path,
    environment_hourly_path: Path,
    spatial_features_path: Path | None = None,
    noise_calibration_path: Path | None = None,
    noise_observation_context: Mapping[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """执行独立 Google 预算并原子写出三类暴露文档。"""

    latest = _read_json(environment_latest_path, "当前环境")
    hourly = _read_json(environment_hourly_path, "逐小时环境")
    weather = weather_factors_from_documents(latest, hourly)
    client = PollenClient(session, settings)
    pollen_document = collect_pollen_grid_document(
        client=client,
        pm25_grid_path=pm25_grid_path,
        model_path=pollen_model_path,
        weather_by_date=weather,
        vegetation_by_grid={},
        generated_at=generated_at,
    )
    result = build_static_exposure_documents(
        output_dir=output_dir,
        routes_path=routes_path,
        pm25_grid_path=pm25_grid_path,
        noise_config_path=noise_config_path,
        spatial_features_path=spatial_features_path,
        noise_calibration_path=noise_calibration_path,
        noise_observation_context=noise_observation_context,
        pollen_document=pollen_document,
        generated_at=generated_at,
    )
    return {
        **result,
        "pollen_call_count": client.call_count,
        "pollen_grid_count": pollen_document["grid_count"],
        "pollen_forecast_date_count": pollen_document["forecast_date_count"],
    }


def probe_pollen_from_project(
    *,
    settings: Settings,
    root: Path,
    grid_id: str,
    confirmed: bool,
) -> dict[str, object]:
    """对一个现有 PM2.5 网格中心执行经确认的花粉探针。"""

    if not confirmed:
        raise ValueError("花粉探针需要 --confirm-pollen-probe")
    points = load_pollen_grid_points(root / "runtime" / "exports" / "pm25_grid_latest.json")
    point = next((item for item in points if item.grid_id == grid_id), None)
    if point is None:
        raise ValueError(f"未知花粉网格: {grid_id}")
    with requests.Session() as session:
        session.headers.update({"User-Agent": "weather-api-data/0.1.0"})
        client = PollenClient(session, settings)
        lookup = client.lookup(latitude=point.latitude, longitude=point.longitude, days=5)
    return {
        "status": lookup.status,
        "grid_id": point.grid_id,
        "longitude": point.longitude,
        "latitude": point.latitude,
        "call_count": client.call_count,
        "fetched_at": lookup.fetched_at.isoformat(),
        "expires": lookup.expires,
        "forecast_dates": [item.forecast_date for item in lookup.days],
        "pollen_types": {
            code: sorted({day.pollen_types[code].status for day in lookup.days})
            for code in ("GRASS", "TREE", "WEED")
        },
    }


def refresh_exposure_from_project(
    *,
    settings: Settings,
    root: Path,
    spatial_features_path: Path | None = None,
) -> dict[str, object]:
    """按项目约定路径刷新花粉、噪声与路线环境结果。"""

    paths = _project_paths(root)
    with requests.Session() as session:
        session.headers.update({"User-Agent": "weather-api-data/0.1.0"})
        noise_refresh = refresh_noise_observations_from_project(
            settings=settings,
            session=session,
            root=root,
        )
        observation_context = (
            _read_json(paths["noise_observation"], "噪声观测上下文")
            if paths["noise_observation"].is_file()
            else None
        )
        result = refresh_exposure_from_local_sources(
            settings=settings,
            session=session,
            output_dir=paths["exports"],
            routes_path=paths["routes"],
            pm25_grid_path=paths["pm25"],
            pollen_model_path=paths["pollen_model"],
            noise_config_path=paths["noise_model"],
            noise_calibration_path=paths["noise_calibration"],
            noise_observation_context=observation_context,
            environment_latest_path=paths["latest"],
            environment_hourly_path=paths["hourly"],
            spatial_features_path=_resolve_optional_path(root, spatial_features_path),
        )
        result["noise_observations"] = noise_refresh
        if noise_refresh.get("status") in {"error", "partial"}:
            result["status"] = "partial"
        return result


def build_static_exposure_from_project(
    *,
    root: Path,
    spatial_features_path: Path | None = None,
) -> dict[str, object]:
    """按项目约定路径生成无需网络的噪声与路线环境结果。"""

    paths = _project_paths(root)
    pollen_path = paths["exports"] / "pollen_grid_scores.json"
    pollen = _read_json(pollen_path, "花粉网格") if pollen_path.is_file() else None
    return build_static_exposure_documents(
        output_dir=paths["exports"],
        routes_path=paths["routes"],
        pm25_grid_path=paths["pm25"],
        noise_config_path=paths["noise_model"],
        noise_calibration_path=(
            paths["noise_calibration"] if paths["noise_calibration"].is_file() else None
        ),
        noise_observation_context=(
            _read_json(paths["noise_observation"], "噪声观测上下文")
            if paths["noise_observation"].is_file()
            else None
        ),
        spatial_features_path=_resolve_optional_path(root, spatial_features_path),
        pollen_document=pollen,
    )


def _resolve_optional_path(root: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else root / path


def _project_paths(root: Path) -> dict[str, Path]:
    resolved = root.resolve(strict=False)
    exports = resolved / "runtime" / "exports"
    return {
        "exports": exports,
        "routes": resolved.parent / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson",
        "pm25": exports / "pm25_grid_latest.json",
        "pollen_model": resolved / "config" / "pollen_model.json",
        "noise_model": resolved / "config" / "noise_model.json",
        "noise_calibration": (
            resolved
            / "noise_data"
            / "xuhui_noise_monitoring"
            / "xuhui_data"
            / "xuhui_noise_baseline.json"
        ),
        "noise_observation": exports / "noise_observation_latest.json",
        "latest": exports / "environment_latest.json",
        "hourly": exports / "environment_hourly.json",
    }


def _aggregate_weather_by_date(
    records: tuple[Mapping[str, object], ...],
    *,
    location_key: str,
) -> dict[str, WeatherFactors]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        if record.get("location_key") != location_key:
            continue
        business_date = _business_date(record.get("business_time"))
        if business_date is not None:
            grouped[business_date].append(record)
    result: dict[str, WeatherFactors] = {}
    for business_date, day_records in grouped.items():
        values = [_mapping(record.get("values"), "weather.values") for record in day_records]
        winds = _numbers(values, "wind_speed_kmh")
        precipitation = _numbers(values, "precipitation_mm")
        humidity = _numbers(values, "relative_humidity_pct")
        result[business_date] = WeatherFactors(
            wind_speed_kph=sum(winds) / len(winds) if winds else None,
            precipitation_mm=sum(precipitation) if precipitation else None,
            humidity_percent=sum(humidity) / len(humidity) if humidity else None,
        )
    return result


def _business_date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    candidate = value[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _numbers(values: list[Mapping[str, object]], name: str) -> list[float]:
    result: list[float] = []
    for value in values:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        result.append(float(item))
    return result


def _records(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("环境记录需为数组")
    records: list[Mapping[str, object]] = []
    for item in cast(list[object], value):
        records.append(_mapping(item, "环境记录"))
    return tuple(records)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} 需为对象")
    return cast(Mapping[str, object], value)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} 需为数值")
    return float(value)


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}文件无法读取: {path}") from error
    return dict(_mapping(value, label))


__all__ = [
    "build_grid_environment_document",
    "build_static_exposure_documents",
    "build_static_exposure_from_project",
    "probe_pollen_from_project",
    "refresh_exposure_from_local_sources",
    "refresh_exposure_from_project",
    "weather_factors_from_documents",
]
