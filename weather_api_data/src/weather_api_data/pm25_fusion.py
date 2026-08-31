# pyright: reportUnknownMemberType=false

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import numpy.typing as npt
import xarray as xr

REQUIRED_STATION_IDS = ("80", "207")
STATION_WARN_AGE_MINUTES = 180
MAX_STATION_AGE_MINUTES = 24 * 60
FloatArray = npt.NDArray[np.float64]


class Pm25FusionError(RuntimeError):
    """表示 PM2.5 融合输入缺失、过期或结构异常。"""


@dataclass(frozen=True, slots=True)
class _Station:
    station_id: str
    longitude: float
    latitude: float
    observed_at: datetime
    pm2_5_ug_m3: float
    age_minutes: float
    temporal_weight_factor: float
    included: bool


@dataclass(frozen=True, slots=True)
class _ForecastAnchor:
    forecast_at: datetime
    fetched_at: str
    pm2_5_ug_m3: float


@dataclass(frozen=True, slots=True)
class _ZoneAnchor:
    zone_id: str
    name: str
    longitude: float
    latitude: float


class _MonthlyPrior(TypedDict):
    longitude: FloatArray
    latitude: FloatArray
    anomaly: FloatArray
    days: int
    source_version: str


def build_pm25_grid_estimate(
    *,
    chap_path: Path,
    history_path: Path,
    latest_path: Path,
    zones_path: Path,
    reference_source_id: str,
    target_time: datetime,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """用指定时刻的和风参考源、两站观测与 CHAP 月度偏差生成网格估计。"""

    _require_aware(target_time, "target_time")
    reference_source_id = _required_source_id(reference_source_id)
    generated = generated_at or datetime.now().astimezone()
    _require_aware(generated, "generated_at")
    anchor = _load_reference_anchor(history_path, target_time, reference_source_id)
    stations = _load_stations(latest_path, zones_path, target_time)
    prior = _load_monthly_prior(chap_path, target_time.month)

    longitude = prior["longitude"]
    latitude = prior["latitude"]
    anomalies = prior["anomaly"]
    anchor_value = _pm25(anchor.get("pm2_5_ug_m3"), "和风参考源")

    station_anomalies: dict[str, float] = {}
    station_residuals: dict[str, float] = {}
    for station in stations:
        historical_anomaly = _idw_value(
            station.longitude,
            station.latitude,
            longitude,
            latitude,
            anomalies,
        )
        expected = anchor_value + historical_anomaly
        residual = station.pm2_5_ug_m3 - expected
        station_anomalies[station.station_id] = historical_anomaly
        station_residuals[station.station_id] = residual

    active_stations = tuple(station for station in stations if station.included)
    station_grid_weights: dict[str, list[float]] = {station.station_id: [] for station in stations}
    if len(active_stations) >= 2:
        station_longitude = np.asarray(
            [station.longitude for station in active_stations], dtype=np.float64
        )
        station_latitude = np.asarray(
            [station.latitude for station in active_stations], dtype=np.float64
        )
        station_residual = np.asarray(
            [station_residuals[station.station_id] for station in active_stations],
            dtype=np.float64,
        )
        station_time_weight = np.asarray(
            [station.temporal_weight_factor for station in active_stations],
            dtype=np.float64,
        )
        correction_values: list[float] = []
        for grid_longitude, grid_latitude in zip(longitude, latitude, strict=True):
            normalized_weights = _idw_weights(
                float(grid_longitude),
                float(grid_latitude),
                station_longitude,
                station_latitude,
                station_time_weight,
            )
            correction_values.append(float(np.sum(normalized_weights * station_residual)))
            for station, weight in zip(active_stations, normalized_weights, strict=True):
                station_grid_weights[station.station_id].append(float(weight))
        corrections = np.asarray(correction_values, dtype=np.float64)
    else:
        corrections = np.zeros_like(anomalies, dtype=np.float64)
    corrections -= float(corrections.mean())

    station_details: list[dict[str, object]] = []
    for station in stations:
        grid_weights = station_grid_weights[station.station_id]
        station_details.append(
            {
                "station_id": station.station_id,
                "longitude": station.longitude,
                "latitude": station.latitude,
                "observed_at": station.observed_at.isoformat(),
                "age_minutes": round(station.age_minutes, 3),
                "pm2_5_ug_m3": station.pm2_5_ug_m3,
                "historical_monthly_anomaly_ug_m3": round(station_anomalies[station.station_id], 6),
                "residual_ug_m3": round(station_residuals[station.station_id], 6),
                "temporal_weight_factor": round(station.temporal_weight_factor, 6),
                "included": station.included,
                "exclusion_reason": (None if station.included else "age_at_least_24_hours"),
                "grid_weight_min": round(min(grid_weights), 6) if grid_weights else 0.0,
                "grid_weight_mean": (
                    round(float(np.mean(grid_weights)), 6) if grid_weights else 0.0
                ),
                "grid_weight_max": round(max(grid_weights), 6) if grid_weights else 0.0,
            }
        )

    degraded_stations = [
        station
        for station in stations
        if not station.included or station.temporal_weight_factor < 1.0
    ]
    status = "partial" if degraded_stations or len(active_stations) < 2 else "ok"
    warnings = [
        (
            f"station_{station.station_id}_excluded_at_24_hours"
            if not station.included
            else f"station_{station.station_id}_age_exceeds_3_hours"
        )
        for station in degraded_stations
    ]

    estimates = anchor_value + anomalies + corrections
    estimates = _nonnegative_with_anchor_mean(estimates, anchor_value)

    grids: list[dict[str, object]] = []
    for index, (grid_longitude, grid_latitude, anomaly, correction, estimate) in enumerate(
        zip(longitude, latitude, anomalies, corrections, estimates, strict=True),
        start=1,
    ):
        grids.append(
            {
                "grid_id": f"XH_PM25_G{index:03d}",
                "longitude": round(float(grid_longitude), 6),
                "latitude": round(float(grid_latitude), 6),
                "pm2_5_ug_m3": round(float(estimate), 6),
                "api_anchor_ug_m3": anchor_value,
                "historical_monthly_anomaly_ug_m3": round(float(anomaly), 6),
                "station_correction_ug_m3": round(float(correction), 6),
                "is_estimated": True,
            }
        )

    return {
        "status": status,
        "schema_version": "1.0",
        "dataset_type": "pm25_grid_estimate",
        "dataset_role": "operational",
        "spatial_basis": "grid_1km",
        "temporal_resolution": "current_estimate",
        "provider": "qweather",
        "source_id": reference_source_id,
        "target_time": target_time.isoformat(),
        "generated_at": generated.isoformat(),
        "grid_count": len(grids),
        "anchor": anchor,
        "historical_prior": {
            "provider": "CHAP",
            "dataset": "ChinaHighPM2.5",
            "source_version": prior["source_version"],
            "year": 2025,
            "month": target_time.month,
            "days": prior["days"],
            "method": "monthly_median_daily_spatial_anomaly",
        },
        "stations": station_details,
        "warnings": warnings,
        "calibration": {
            "method": "qweather_anchor_plus_chap_monthly_anomaly_plus_station_idw_residual",
            "station_warn_age_minutes": STATION_WARN_AGE_MINUTES,
            "station_max_age_minutes": MAX_STATION_AGE_MINUTES,
            "station_time_weight_method": "linear_after_180_minutes_to_zero_at_1440_minutes",
            "active_station_count": len(active_stations),
            "mean_constraint": "grid_mean_equals_qweather_reference_anchor",
        },
        "quality": {
            "status": "estimated",
            "confidence": "medium" if status == "ok" else "low",
            "limitations": [
                "CHAP spatial prior is a 2025 daily 1 km estimate",
                "two stations constrain only a broad local residual surface",
                "1 km grid estimates do not represent road-side measurements",
            ],
        },
        "grids": grids,
    }


def build_pm25_grid_forecast(
    *,
    chap_path: Path,
    hourly_path: Path,
    zones_path: Path,
    reference_source_id: str,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """用徐汇逐小时 PM2.5 预报锚点和 CHAP 月度偏差生成 24 小时空间估计。"""

    generated = generated_at or datetime.now().astimezone()
    _require_aware(generated, "generated_at")
    reference_source_id = _required_source_id(reference_source_id)
    anchors = _load_forecast_anchors(hourly_path, reference_source_id)
    zones = _load_zone_anchors(zones_path)
    priors = {month: _load_monthly_prior(chap_path, month) for month in _forecast_months(anchors)}
    forecasts: list[dict[str, object]] = []

    for anchor in anchors:
        prior = priors[anchor.forecast_at.month]
        estimates = _nonnegative_with_anchor_mean(
            anchor.pm2_5_ug_m3 + prior["anomaly"],
            anchor.pm2_5_ug_m3,
        )
        grids = _forecast_grids(anchor.pm2_5_ug_m3, prior, estimates)
        zone_estimates = _forecast_zones(zones, grids)
        forecasts.append(
            {
                "forecast_at": anchor.forecast_at.isoformat(),
                "fetched_at": anchor.fetched_at,
                "provider": "qweather",
                "source_id": reference_source_id,
                "api_anchor_ug_m3": anchor.pm2_5_ug_m3,
                "grids": grids,
                "zones": zone_estimates,
            }
        )

    first_prior = priors[anchors[0].forecast_at.month]
    return {
        "schema_version": "1.0",
        "dataset_type": "pm25_grid_forecast",
        "dataset_role": "operational",
        "spatial_basis": "grid_1km_and_zone_anchor",
        "temporal_resolution": "hourly_forecast_24h",
        "provider": "qweather",
        "source_id": reference_source_id,
        "generated_at": generated.isoformat(),
        "forecast_count": len(forecasts),
        "grid_count": len(first_prior["longitude"]),
        "zone_count": len(zones),
        "historical_priors": [
            {
                "provider": "CHAP",
                "dataset": "ChinaHighPM2.5",
                "source_version": priors[month]["source_version"],
                "year": 2025,
                "month": month,
                "days": priors[month]["days"],
                "method": "monthly_median_daily_spatial_anomaly",
            }
            for month in sorted(priors)
        ],
        "calibration": {
            "method": "qweather_forecast_anchor_plus_chap_monthly_anomaly",
            "mean_constraint": "each_hour_grid_mean_equals_qweather_reference_forecast",
            "zone_method": "nearest_grid_to_zone_anchor",
        },
        "quality": {
            "status": "estimated",
            "confidence": "medium",
            "limitations": [
                "CHAP spatial prior is a 2025 daily 1 km estimate",
                "future station observations are unavailable for residual correction",
                "1 km grid forecasts do not represent road-side measurements",
            ],
        },
        "forecasts": forecasts,
    }


def fuse_pm25_from_local_sources(*, root: Path, target_time: datetime) -> dict[str, object]:
    """读取固定本地来源并原子写出网页后续可消费的最新 PM2.5 网格。"""

    resolved_root = root.resolve(strict=False)
    reference_source_id = _load_reference_source_id(
        resolved_root / "runtime" / "exports" / "environment_regions.json"
    )
    document = build_pm25_grid_estimate(
        chap_path=resolved_root
        / "pm2.5_data"
        / "xuhui_pm2.5_2025_1km"
        / "xuhui_data"
        / "CHAP_PM2.5_D1K_2025_xuhui_V4.nc",
        history_path=resolved_root / "runtime" / "history" / "weather.sqlite",
        latest_path=resolved_root / "runtime" / "exports" / "environment_latest.json",
        zones_path=resolved_root / "config" / "xuhui_air_quality_zones.json",
        reference_source_id=reference_source_id,
        target_time=target_time,
    )
    output_path = resolved_root / "runtime" / "exports" / "pm25_grid_latest.json"
    _atomic_json(output_path, document)
    grids = cast(list[dict[str, object]], document["grids"])
    values = [_pm25(grid.get("pm2_5_ug_m3"), "融合网格") for grid in grids]
    stations = cast(list[dict[str, object]], document["stations"])
    return {
        "status": document["status"],
        "provider": "qweather",
        "source_id": reference_source_id,
        "target_time": document["target_time"],
        "grid_count": len(grids),
        "grid_mean_pm2_5_ug_m3": round(float(np.mean(values)), 6),
        "grid_min_pm2_5_ug_m3": min(values),
        "grid_max_pm2_5_ug_m3": max(values),
        "station_observed_at": [station["observed_at"] for station in stations],
        "stations": stations,
        "warnings": document["warnings"],
        "output_path": str(output_path),
    }


def fuse_pm25_forecast_from_local_sources(*, root: Path) -> dict[str, object]:
    """读取刷新导出并原子写出未来 24 小时 PM2.5 网格与区域估计。"""

    resolved_root = root.resolve(strict=False)
    reference_source_id = _load_reference_source_id(
        resolved_root / "runtime" / "exports" / "environment_regions.json"
    )
    document = build_pm25_grid_forecast(
        chap_path=resolved_root
        / "pm2.5_data"
        / "xuhui_pm2.5_2025_1km"
        / "xuhui_data"
        / "CHAP_PM2.5_D1K_2025_xuhui_V4.nc",
        hourly_path=resolved_root / "runtime" / "exports" / "environment_hourly.json",
        zones_path=resolved_root / "config" / "xuhui_air_quality_zones.json",
        reference_source_id=reference_source_id,
    )
    output_path = resolved_root / "runtime" / "exports" / "pm25_grid_forecast_24h.json"
    _atomic_json(output_path, document)
    forecasts = cast(list[dict[str, object]], document["forecasts"])
    return {
        "status": "ok",
        "provider": "qweather",
        "source_id": reference_source_id,
        "forecast_count": document["forecast_count"],
        "grid_count": document["grid_count"],
        "zone_count": document["zone_count"],
        "forecast_start": forecasts[0]["forecast_at"],
        "forecast_end": forecasts[-1]["forecast_at"],
        "output_path": str(output_path),
    }


def fuse_latest_pm25_from_local_sources(*, root: Path) -> dict[str, object]:
    """选择和风参考源的最新观测时刻并生成 PM2.5 网格。"""

    resolved_root = root.resolve(strict=False)
    reference_source_id = _load_reference_source_id(
        resolved_root / "runtime" / "exports" / "environment_regions.json"
    )
    target_time = _latest_reference_target_time(
        resolved_root / "runtime" / "history" / "weather.sqlite",
        reference_source_id,
    )
    return fuse_pm25_from_local_sources(root=resolved_root, target_time=target_time)


def _load_reference_source_id(regions_path: Path) -> str:
    regions = _read_json(regions_path, "环境区域数据")
    return _required_source_id(regions.get("reference_source_id"))


def _required_source_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Pm25FusionError("reference_source_id 缺失")
    return value


def _latest_reference_target_time(history_path: Path, reference_source_id: str) -> datetime:
    if not history_path.is_file():
        raise Pm25FusionError(f"空气质量历史库不存在: {history_path}")
    try:
        with sqlite3.connect(history_path) as connection:
            row = connection.execute(
                """
                SELECT business_time
                FROM air_quality_observations
                WHERE location_key = ? AND status = 'ok'
                ORDER BY business_time DESC, fetched_at DESC
                LIMIT 1
                """,
                (reference_source_id,),
            ).fetchone()
    except sqlite3.Error as error:
        raise Pm25FusionError(f"读取空气质量历史库失败: {history_path}") from error
    if row is None:
        raise Pm25FusionError(f"参考源 {reference_source_id} 缺少可用于自动融合的 PM2.5 数据")
    return _parse_aware(row[0], "和风参考源 business_time")


def _load_reference_anchor(
    history_path: Path,
    target_time: datetime,
    reference_source_id: str,
) -> dict[str, object]:
    if not history_path.is_file():
        raise Pm25FusionError(f"空气质量历史库不存在: {history_path}")
    try:
        with sqlite3.connect(history_path) as connection:
            row = connection.execute(
                """
                SELECT record_json
                FROM air_quality_observations
                WHERE location_key = ? AND business_time = ? AND status = 'ok'
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                (reference_source_id, target_time.isoformat()),
            ).fetchone()
    except sqlite3.Error as error:
        raise Pm25FusionError(f"读取空气质量历史库失败: {history_path}") from error
    if row is None:
        raise Pm25FusionError(
            f"参考源 {reference_source_id} 缺少精确时刻数据: {target_time.isoformat()}"
        )
    decoded = json.loads(str(row[0]))
    if not isinstance(decoded, dict):
        raise Pm25FusionError("和风参考源记录顶层需为对象")
    record = cast(dict[str, object], decoded)
    values = record.get("values")
    if not isinstance(values, dict):
        raise Pm25FusionError("和风参考源记录缺少 values")
    typed_values = cast(dict[str, object], values)
    pm2_5 = _pm25(typed_values.get("pm2_5_ug_m3"), "和风参考源")
    return {
        "provider": "qweather",
        "source_id": reference_source_id,
        "observed_at": target_time.isoformat(),
        "pm2_5_ug_m3": pm2_5,
        "aqi": typed_values.get("aqi"),
        "source": record.get("source", {}),
    }


def _load_stations(
    latest_path: Path, zones_path: Path, target_time: datetime
) -> tuple[_Station, ...]:
    latest = _read_json(latest_path, "环境最新数据")
    zones_document = _read_json(zones_path, "空气质量分区配置")
    raw_records = latest.get("point_air_quality")
    raw_zones = zones_document.get("zones")
    if not isinstance(raw_records, list) or not isinstance(raw_zones, list):
        raise Pm25FusionError("站点数据或分区配置结构异常")
    records = cast(list[object], raw_records)
    zones = cast(list[object], raw_zones)

    station_coordinates: dict[str, tuple[float, float]] = {}
    for raw_zone in zones:
        zone = _mapping(raw_zone)
        if zone is None or zone.get("source_strategy") != "shanghai_station":
            continue
        station_id = str(zone.get("station_id"))
        anchor = _mapping(zone.get("anchor"))
        if anchor is None or str(anchor.get("crs", "")).upper() != "WGS84":
            raise Pm25FusionError(f"站点 {station_id} 缺少 WGS84 anchor")
        station_coordinates[station_id] = (
            _coordinate(anchor.get("longitude"), f"站点 {station_id} longitude"),
            _coordinate(anchor.get("latitude"), f"站点 {station_id} latitude"),
        )

    by_id: dict[str, dict[str, object]] = {}
    for raw_record in records:
        record = _mapping(raw_record)
        if (
            record is not None
            and record.get("provider") == "shanghai_sthj"
            and record.get("spatial_basis") == "station"
        ):
            by_id[str(record.get("spatial_id"))] = record
    stations: list[_Station] = []
    for station_id in REQUIRED_STATION_IDS:
        record = by_id.get(station_id)
        coordinates = station_coordinates.get(station_id)
        if record is None or coordinates is None:
            raise Pm25FusionError(f"缺少上海站点 {station_id} 数据或坐标")
        observed_at = _parse_aware(record.get("observed_at"), f"站点 {station_id} observed_at")
        age_minutes = (target_time - observed_at).total_seconds() / 60
        if age_minutes < 0:
            raise Pm25FusionError(f"站点 {station_id} 观测时间晚于融合目标时刻")
        values = _mapping(record.get("values"))
        if values is None:
            raise Pm25FusionError(f"站点 {station_id} 缺少 values")
        stations.append(
            _Station(
                station_id=station_id,
                longitude=coordinates[0],
                latitude=coordinates[1],
                observed_at=observed_at,
                pm2_5_ug_m3=_pm25(values.get("pm2_5_ug_m3"), f"站点 {station_id}"),
                age_minutes=age_minutes,
                temporal_weight_factor=_station_time_weight(age_minutes),
                included=age_minutes < MAX_STATION_AGE_MINUTES,
            )
        )
    return tuple(stations)


def _load_monthly_prior(chap_path: Path, month: int) -> _MonthlyPrior:
    if not chap_path.is_file():
        raise Pm25FusionError(f"CHAP 文件不存在: {chap_path}")
    try:
        with xr.open_dataset(chap_path, engine="h5netcdf") as dataset:
            required = {"pm2_5_ug_m3", "xuhui_mask"}
            if not required.issubset(dataset.data_vars):
                raise Pm25FusionError(f"CHAP 文件缺少变量: {sorted(required)}")
            monthly = dataset["pm2_5_ug_m3"].where(dataset["time"].dt.month == month, drop=True)
            if monthly.sizes.get("time", 0) == 0:
                raise Pm25FusionError(f"CHAP 文件缺少 {month} 月数据")
            mask = np.asarray(dataset["xuhui_mask"].values, dtype=bool)
            values = np.asarray(monthly.values, dtype=np.float64)
            valid_values = np.asarray(values[:, mask], dtype=np.float64)
            daily_mean = np.mean(valid_values, axis=1)
            daily_anomaly = valid_values - daily_mean[:, np.newaxis]
            valid_anomaly = np.asarray(np.median(daily_anomaly, axis=0), dtype=np.float64)
            valid_anomaly -= float(valid_anomaly.mean())
            latitude_grid, longitude_grid = np.meshgrid(
                np.asarray(dataset["lat"].values, dtype=np.float64),
                np.asarray(dataset["lon"].values, dtype=np.float64),
                indexing="ij",
            )
            longitude = np.asarray(longitude_grid[mask], dtype=np.float64)
            latitude = np.asarray(latitude_grid[mask], dtype=np.float64)
            source_version = str(dataset.attrs.get("source_version", "unknown"))
            days = int(monthly.sizes["time"])
    except (OSError, ValueError) as error:
        raise Pm25FusionError(f"读取 CHAP 文件失败: {chap_path}") from error
    if not np.isfinite(valid_anomaly).all():
        raise Pm25FusionError("CHAP 月度空间偏差包含无效值")
    return {
        "longitude": longitude,
        "latitude": latitude,
        "anomaly": valid_anomaly,
        "days": days,
        "source_version": source_version,
    }


def _load_forecast_anchors(
    hourly_path: Path,
    reference_source_id: str,
) -> tuple[_ForecastAnchor, ...]:
    document = _read_json(hourly_path, "环境逐小时数据")
    raw_records = document.get("xuhui_pm2_5_forecast_24h")
    if not isinstance(raw_records, list):
        raise Pm25FusionError("徐汇 PM2.5 预报需为 24 条，当前为 0 条")
    records = cast(list[object], raw_records)
    if len(records) != 24:
        count = len(records)
        raise Pm25FusionError(f"徐汇 PM2.5 预报需为 24 条，当前为 {count} 条")

    anchors: list[_ForecastAnchor] = []
    for index, raw_record in enumerate(records):
        record = _mapping(raw_record)
        if record is None:
            raise Pm25FusionError(f"徐汇 PM2.5 预报第 {index} 条结构异常")
        if record.get("location_key") != reference_source_id:
            raise Pm25FusionError(f"徐汇 PM2.5 预报第 {index} 条 reference_source_id 异常")
        if record.get("status") != "ok":
            raise Pm25FusionError(f"徐汇 PM2.5 预报第 {index} 条状态异常")
        values = _mapping(record.get("values"))
        if values is None:
            raise Pm25FusionError(f"徐汇 PM2.5 预报第 {index} 条缺少 values")
        fetched_at = record.get("fetched_at")
        if not isinstance(fetched_at, str) or not fetched_at:
            raise Pm25FusionError(f"徐汇 PM2.5 预报第 {index} 条缺少 fetched_at")
        anchors.append(
            _ForecastAnchor(
                forecast_at=_parse_aware(
                    record.get("business_time"),
                    f"徐汇 PM2.5 预报第 {index} 条 forecast_at",
                ),
                fetched_at=fetched_at,
                pm2_5_ug_m3=_pm25(values.get("pm2_5_ug_m3"), "徐汇 PM2.5 预报"),
            )
        )

    anchors.sort(key=lambda item: item.forecast_at)
    times = [anchor.forecast_at for anchor in anchors]
    if len(set(times)) != len(times):
        raise Pm25FusionError("徐汇 PM2.5 预报时间重复")
    if any((later - earlier).total_seconds() != 3600 for earlier, later in pairwise(times)):
        raise Pm25FusionError("徐汇 PM2.5 预报时间需按连续 1 小时排列")
    return tuple(anchors)


def _forecast_months(anchors: tuple[_ForecastAnchor, ...]) -> tuple[int, ...]:
    return tuple(sorted({anchor.forecast_at.month for anchor in anchors}))


def _load_zone_anchors(zones_path: Path) -> tuple[_ZoneAnchor, ...]:
    document = _read_json(zones_path, "空气质量分区配置")
    raw_zones = document.get("zones")
    if not isinstance(raw_zones, list) or not raw_zones:
        raise Pm25FusionError("空气质量分区配置缺少 zones")
    zones: list[_ZoneAnchor] = []
    for index, raw_zone in enumerate(cast(list[object], raw_zones)):
        zone = _mapping(raw_zone)
        if zone is None:
            raise Pm25FusionError(f"空气质量分区第 {index} 条结构异常")
        zone_id = zone.get("zone_id")
        name = zone.get("name", zone_id)
        anchor = _mapping(zone.get("anchor"))
        if not isinstance(zone_id, str) or not zone_id or not isinstance(name, str) or not name:
            raise Pm25FusionError(f"空气质量分区第 {index} 条缺少标识或名称")
        if anchor is None or str(anchor.get("crs", "")).upper() != "WGS84":
            raise Pm25FusionError(f"空气质量分区 {zone_id} 缺少 WGS84 anchor")
        zones.append(
            _ZoneAnchor(
                zone_id=zone_id,
                name=name,
                longitude=_coordinate(anchor.get("longitude"), f"分区 {zone_id} longitude"),
                latitude=_coordinate(anchor.get("latitude"), f"分区 {zone_id} latitude"),
            )
        )
    return tuple(zones)


def _forecast_grids(
    anchor: float,
    prior: _MonthlyPrior,
    estimates: FloatArray,
) -> list[dict[str, object]]:
    return [
        {
            "grid_id": f"XH_PM25_G{index:03d}",
            "longitude": round(float(longitude), 6),
            "latitude": round(float(latitude), 6),
            "pm2_5_ug_m3": round(float(estimate), 6),
            "api_anchor_ug_m3": anchor,
            "historical_monthly_anomaly_ug_m3": round(float(anomaly), 6),
            "is_estimated": True,
        }
        for index, (longitude, latitude, anomaly, estimate) in enumerate(
            zip(
                prior["longitude"],
                prior["latitude"],
                prior["anomaly"],
                estimates,
                strict=True,
            ),
            start=1,
        )
    ]


def _forecast_zones(
    zones: tuple[_ZoneAnchor, ...],
    grids: list[dict[str, object]],
) -> list[dict[str, object]]:
    grid_longitude = np.asarray(
        [_coordinate(grid.get("longitude"), "预报网格 longitude") for grid in grids],
        dtype=np.float64,
    )
    grid_latitude = np.asarray(
        [_coordinate(grid.get("latitude"), "预报网格 latitude") for grid in grids],
        dtype=np.float64,
    )
    estimates: list[dict[str, object]] = []
    for zone in zones:
        distances = _distance_m(
            zone.longitude,
            zone.latitude,
            grid_longitude,
            grid_latitude,
        )
        nearest = grids[int(np.argmin(distances))]
        estimates.append(
            {
                "zone_id": zone.zone_id,
                "name": zone.name,
                "longitude": zone.longitude,
                "latitude": zone.latitude,
                "pm2_5_ug_m3": nearest["pm2_5_ug_m3"],
                "grid_id": nearest["grid_id"],
                "method": "nearest_grid_to_zone_anchor",
                "is_estimated": True,
            }
        )
    return estimates


def _idw_value(
    target_longitude: float,
    target_latitude: float,
    source_longitude: FloatArray,
    source_latitude: FloatArray,
    source_values: FloatArray,
) -> float:
    weights = _idw_weights(
        target_longitude,
        target_latitude,
        source_longitude,
        source_latitude,
        np.ones_like(source_values, dtype=np.float64),
    )
    return float(np.sum(weights * source_values))


def _idw_weights(
    target_longitude: float,
    target_latitude: float,
    source_longitude: FloatArray,
    source_latitude: FloatArray,
    source_factors: FloatArray,
) -> FloatArray:
    distances = _distance_m(
        target_longitude,
        target_latitude,
        source_longitude,
        source_latitude,
    )
    weights = source_factors / np.square(np.maximum(distances, 250.0))
    weight_sum = float(np.sum(weights))
    if weight_sum <= 0:
        raise Pm25FusionError("站点融合权重无效")
    return np.asarray(weights / weight_sum, dtype=np.float64)


def _station_time_weight(age_minutes: float) -> float:
    if age_minutes <= STATION_WARN_AGE_MINUTES:
        return 1.0
    if age_minutes >= MAX_STATION_AGE_MINUTES:
        return 0.0
    remaining = MAX_STATION_AGE_MINUTES - age_minutes
    span = MAX_STATION_AGE_MINUTES - STATION_WARN_AGE_MINUTES
    return remaining / span


def _distance_m(
    target_longitude: float,
    target_latitude: float,
    source_longitude: FloatArray,
    source_latitude: FloatArray,
) -> FloatArray:
    earth_radius_m = 6_371_000.0
    longitude_delta = np.radians(source_longitude - target_longitude)
    latitude_delta = np.radians(source_latitude - target_latitude)
    mean_latitude = np.radians((source_latitude + target_latitude) / 2)
    return earth_radius_m * np.hypot(longitude_delta * np.cos(mean_latitude), latitude_delta)


def _nonnegative_with_anchor_mean(values: FloatArray, anchor: float) -> FloatArray:
    nonnegative = np.maximum(values, 0.0)
    current_mean = float(nonnegative.mean())
    if current_mean <= 0:
        raise Pm25FusionError("网格估计均值无效")
    return nonnegative * (anchor / current_mean)


def _read_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise Pm25FusionError(f"{label}不存在: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Pm25FusionError(f"读取{label}失败: {path}") from error
    if not isinstance(value, dict):
        raise Pm25FusionError(f"{label}顶层需为对象")
    return cast(dict[str, object], value)


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _atomic_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(document, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_aware(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise Pm25FusionError(f"{label} 缺失")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise Pm25FusionError(f"{label} 格式无效: {value}") from error
    _require_aware(parsed, label)
    return parsed


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise Pm25FusionError(f"{label} 需包含时区")


def _pm25(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise Pm25FusionError(f"{label} PM2.5 缺失")
    converted = float(value)
    if not math.isfinite(converted) or not 0 <= converted <= 1_000:
        raise Pm25FusionError(f"{label} PM2.5 超出有效范围: {converted}")
    return converted


def _coordinate(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise Pm25FusionError(f"{label} 缺失")
    converted = float(value)
    if not math.isfinite(converted):
        raise Pm25FusionError(f"{label} 无效")
    return converted


__all__ = [
    "MAX_STATION_AGE_MINUTES",
    "STATION_WARN_AGE_MINUTES",
    "Pm25FusionError",
    "build_pm25_grid_estimate",
    "build_pm25_grid_forecast",
    "fuse_latest_pm25_from_local_sources",
    "fuse_pm25_forecast_from_local_sources",
    "fuse_pm25_from_local_sources",
]
