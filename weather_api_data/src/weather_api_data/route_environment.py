"""按实际路段长度汇总多源路线环境暴露。"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import cast
from zoneinfo import ZoneInfo

from weather_api_data.models import (
    Confidence,
    RouteEnvironmentRecord,
    RouteExposureMetric,
    Status,
)

MAX_POLLEN_FORECAST_DAYS = 5


class RouteEnvironmentError(ValueError):
    """表示路线聚合输入缺少必需字段或包含冲突记录。"""


def build_route_environment_document(
    *,
    route_segments: Iterable[object],
    pm25_document: Mapping[str, object] | None,
    pollen_document: Mapping[str, object] | None,
    noise_segments: Iterable[object],
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """把路线段、PM2.5 网格、花粉网格和噪声段汇总成网页数据契约。"""

    generated = generated_at or datetime.now().astimezone()
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise RouteEnvironmentError("generated_at 需要包含时区")

    segments_by_route = _group_segments(route_segments)
    if not segments_by_route:
        raise RouteEnvironmentError("route_segments 为空")

    pm25_by_grid = _pm25_grid_values(pm25_document)
    pollen_by_date_grid = _pollen_grid_values(pollen_document)
    noise_by_segment = _noise_values(noise_segments)
    records: list[RouteEnvironmentRecord] = []
    for route_id in sorted(segments_by_route):
        segments = segments_by_route[route_id]
        pm25 = _aggregate_pm25(segments, pm25_by_grid, pm25_document)
        pollen = _aggregate_pollen(segments, pollen_by_date_grid, pollen_document, generated)
        noise = _aggregate_noise(segments, noise_by_segment, generated)
        route_status: Status = (
            "ok"
            if pm25.status == "ok"
            and pollen
            and all(metric.status == "ok" for metric in pollen)
            and noise.status == "ok"
            else "partial"
        )
        records.append(
            RouteEnvironmentRecord(
                route_id=route_id,
                segment_count=len(segments),
                total_length_m=round(sum(_length(segment) for segment in segments), 6),
                status=route_status,
                pm2_5=pm25,
                pollen_daily=pollen,
                noise=noise,
            )
        )

    document_status: Status = (
        "ok" if all(record.status == "ok" for record in records) else "partial"
    )
    return {
        "schema_version": "1.0",
        "dataset_type": "route_environment",
        "generated_at": generated.isoformat(),
        "route_count": len(records),
        "status": document_status,
        "routes": [record.to_dict() for record in records],
    }


def _group_segments(route_segments: Iterable[object]) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = defaultdict(list)
    seen_segment_ids: set[str] = set()
    for segment in route_segments:
        segment_id = _required_string(segment, "segment_id")
        route_id = _required_string(segment, "route_id")
        _length(segment)
        if segment_id in seen_segment_ids:
            raise RouteEnvironmentError(f"segment_id 重复: {segment_id}")
        seen_segment_ids.add(segment_id)
        grouped[route_id].append(segment)
    for segments in grouped.values():
        segments.sort(key=lambda item: _required_int(item, "segment_index"))
    return dict(grouped)


def _pm25_grid_values(
    document: Mapping[str, object] | None,
) -> dict[str, tuple[float, bool]]:
    if document is None:
        return {}
    result: dict[str, tuple[float, bool]] = {}
    for item in _mapping_list(document.get("grids"), "pm25_document.grids"):
        grid_id = _required_string(item, "grid_id")
        if grid_id in result:
            raise RouteEnvironmentError(f"PM2.5 grid_id 重复: {grid_id}")
        value = _required_float(item, "pm2_5_ug_m3")
        result[grid_id] = (value, bool(item.get("is_estimated", True)))
    return result


def _pollen_grid_values(
    document: Mapping[str, object] | None,
) -> dict[str, dict[str, Mapping[str, object]]]:
    if document is None:
        return {}
    result: dict[str, dict[str, Mapping[str, object]]] = defaultdict(dict)
    for item in _mapping_list(document.get("grid_scores"), "pollen_document.grid_scores"):
        grid_id = _required_string(item, "grid_id")
        forecast_date = _required_string(item, "forecast_date")
        if grid_id in result[forecast_date]:
            raise RouteEnvironmentError(f"花粉 grid_id/date 重复: {grid_id}/{forecast_date}")
        result[forecast_date][grid_id] = item
    return dict(result)


def _noise_values(noise_segments: Iterable[object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in noise_segments:
        segment_id = _required_string(item, "segment_id")
        if segment_id in result:
            raise RouteEnvironmentError(f"噪声 segment_id 重复: {segment_id}")
        result[segment_id] = item
    return result


def _aggregate_pm25(
    segments: list[object],
    values_by_grid: Mapping[str, tuple[float, bool]],
    document: Mapping[str, object] | None,
) -> RouteExposureMetric:
    weighted: list[tuple[float, float]] = []
    estimated: list[bool] = []
    for segment in segments:
        grid_id = _optional_string(segment, "pm25_grid_id")
        if grid_id is None or grid_id not in values_by_grid:
            continue
        value, is_estimated = values_by_grid[grid_id]
        weighted.append((value, _length(segment)))
        estimated.append(is_estimated)
    coverage = _coverage(weighted, segments)
    if not weighted:
        return _empty_metric(unit="ug/m3", spatial_scale="about_1km_grid_estimate")

    quality = _optional_mapping(document.get("quality")) if document is not None else None
    confidence = _confidence(quality.get("confidence") if quality is not None else None)
    calibration = _optional_mapping(document.get("calibration")) if document is not None else None
    active_station_count = calibration.get("active_station_count") if calibration is not None else 2
    uses_station_correction = (
        isinstance(active_station_count, int)
        and not isinstance(active_station_count, bool)
        and active_station_count >= 2
    )
    fusion_status = _status(document.get("status", "ok")) if document is not None else "no_data"
    metric_status: Status = "ok" if coverage == 1.0 and fusion_status == "ok" else "partial"
    sources = (
        ("qweather", "shanghai_sthj", "CHAP") if uses_station_correction else ("qweather", "CHAP")
    )
    return RouteExposureMetric(
        value=_weighted_mean(weighted),
        unit="ug/m3",
        source=sources,
        business_time=_optional_document_string(document, "target_time"),
        fetched_at=_optional_document_string(document, "generated_at"),
        expires_at=_optional_document_string(document, "expires_at"),
        spatial_scale=str(document.get("spatial_basis", "about_1km_grid_estimate"))
        if document is not None
        else "about_1km_grid_estimate",
        status=metric_status,
        confidence=confidence if coverage == 1.0 else "low",
        estimated=any(estimated),
        coverage_ratio=coverage,
    )


def _aggregate_pollen(
    segments: list[object],
    values_by_date_grid: Mapping[str, Mapping[str, Mapping[str, object]]],
    document: Mapping[str, object] | None,
    generated_at: datetime,
) -> tuple[RouteExposureMetric, ...]:
    if document is None:
        return ()
    fallback_source = _source_tuple(document.get("source"))
    local_date = generated_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    window_end = local_date + timedelta(days=MAX_POLLEN_FORECAST_DAYS - 1)
    metrics: list[RouteExposureMetric] = []
    forecast_dates = [
        forecast_date
        for forecast_date in sorted(values_by_date_grid)
        if local_date <= _parse_forecast_date(forecast_date) <= window_end
    ]
    for forecast_date in forecast_dates:
        values_by_grid = values_by_date_grid[forecast_date]
        weighted: list[tuple[float, float]] = []
        statuses: list[Status] = []
        confidences: list[Confidence] = []
        estimated: list[bool] = []
        sources: set[str] = set()
        for segment in segments:
            grid_id = _optional_string(segment, "pm25_grid_id")
            item = values_by_grid.get(grid_id) if grid_id is not None else None
            if item is None or item.get("status") in {"no_data", "error"}:
                continue
            weighted.append((_required_float(item, "pollen_risk_score"), _length(segment)))
            statuses.append(_status(item.get("status")))
            confidences.append(_confidence(item.get("confidence")))
            estimated.append(bool(item.get("estimated", True)))
            sources.update(_source_tuple(item.get("source")))
        if not weighted:
            continue
        coverage = _coverage(weighted, segments)
        value = _weighted_mean(weighted)
        metric_status: Status = (
            "ok" if coverage == 1.0 and all(status == "ok" for status in statuses) else "partial"
        )
        metrics.append(
            RouteExposureMetric(
                value=value,
                unit="0-100 risk index",
                source=tuple(sorted(sources)) if sources else fallback_source,
                business_time=forecast_date,
                fetched_at=_optional_document_string(document, "generated_at"),
                expires_at=_forecast_expiry(forecast_date),
                spatial_scale=f"about_{_spatial_resolution(document)}m_grid_sample",
                status=metric_status,
                confidence=_minimum_confidence(confidences) if metric_status == "ok" else "low",
                estimated=any(estimated),
                coverage_ratio=coverage,
                risk_level=_risk_level(value),
            )
        )
    return tuple(metrics)


def _aggregate_noise(
    segments: list[object],
    values_by_segment: Mapping[str, object],
    generated_at: datetime,
) -> RouteExposureMetric:
    weighted: list[tuple[float, float]] = []
    statuses: list[Status] = []
    confidences: list[Confidence] = []
    estimated: list[bool] = []
    sources: set[str] = set()
    scenario_values: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for segment in segments:
        item = values_by_segment.get(_required_string(segment, "segment_id"))
        if item is None or _field(item, "status") in {"no_data", "error"}:
            continue
        length = _length(segment)
        weighted.append((_required_float(item, "static_risk_score"), length))
        statuses.append(_status(_field(item, "status")))
        confidences.append(_confidence(_field(item, "confidence")))
        estimated.append(bool(_field(item, "estimated", True)))
        sources.update(_source_tuple(_field(item, "source_ids", ())))
        scenarios = _optional_mapping(_field(item, "scenario_risk_scores"))
        if scenarios is not None:
            for scenario, score in scenarios.items():
                scenario_values[scenario].append((_float(score, f"scenario {scenario}"), length))
    coverage = _coverage(weighted, segments)
    if not weighted:
        return _empty_metric(
            unit="0-100 risk index",
            spatial_scale="about_100m_road_segment_proxy",
        )
    value = _weighted_mean(weighted)
    metric_status: Status = (
        "ok" if coverage == 1.0 and all(status == "ok" for status in statuses) else "partial"
    )
    return RouteExposureMetric(
        value=value,
        unit="0-100 risk index",
        source=tuple(sorted(sources)),
        business_time="static_scenario",
        fetched_at=generated_at.isoformat(),
        expires_at=None,
        spatial_scale="about_100m_road_segment_proxy",
        status=metric_status,
        confidence=_minimum_confidence(confidences) if metric_status == "ok" else "low",
        estimated=any(estimated),
        coverage_ratio=coverage,
        risk_level=_risk_level(value),
        scenarios={
            scenario: _weighted_mean(values) for scenario, values in sorted(scenario_values.items())
        },
    )


def _empty_metric(*, unit: str, spatial_scale: str) -> RouteExposureMetric:
    return RouteExposureMetric(
        value=None,
        unit=unit,
        source=(),
        business_time=None,
        fetched_at=None,
        expires_at=None,
        spatial_scale=spatial_scale,
        status="no_data",
        confidence="low",
        estimated=True,
        coverage_ratio=0.0,
    )


def _coverage(weighted: list[tuple[float, float]], segments: list[object]) -> float:
    covered_length = sum(length for _, length in weighted)
    total_length = sum(_length(segment) for segment in segments)
    return round(covered_length / total_length, 6)


def _weighted_mean(values: list[tuple[float, float]]) -> float:
    length = sum(weight for _, weight in values)
    return round(sum(value * weight for value, weight in values) / length, 6)


def _forecast_expiry(forecast_date: str) -> str:
    try:
        value = date.fromisoformat(forecast_date)
    except ValueError as exc:
        raise RouteEnvironmentError(f"forecast_date 不是 ISO 日期: {forecast_date}") from exc
    shanghai_timezone = timezone(timedelta(hours=8))
    return datetime.combine(value, time(23, 59, 59), tzinfo=shanghai_timezone).isoformat()


def _parse_forecast_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise RouteEnvironmentError(f"forecast_date 不是 ISO 日期: {value}") from error


def _spatial_resolution(document: Mapping[str, object]) -> int:
    value = document.get("spatial_resolution_m", 1000)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RouteEnvironmentError("pollen_document.spatial_resolution_m 需要为正数")
    return round(value)


def _risk_level(value: float) -> str:
    if value < 34:
        return "low"
    if value < 67:
        return "medium"
    return "high"


def _minimum_confidence(values: list[Confidence]) -> Confidence:
    rank: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}
    return min(values, key=rank.__getitem__) if values else "low"


def _confidence(value: object) -> Confidence:
    return cast(Confidence, value) if value in {"high", "medium", "low"} else "low"


def _status(value: object) -> Status:
    valid = {"ok", "partial", "stale", "no_data", "error"}
    return cast(Status, value) if value in valid else "partial"


def _source_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part for part in value.split("+") if part)
    if isinstance(value, list):
        items = cast(list[object], value)
        return tuple(sorted({str(item) for item in items if str(item)}))
    if isinstance(value, tuple):
        items = cast(tuple[object, ...], value)
        return tuple(sorted({str(item) for item in items if str(item)}))
    return ()


def _length(record: object) -> float:
    length = _required_float(record, "length_m")
    if length <= 0:
        raise RouteEnvironmentError("length_m 需要大于 0")
    return length


def _field(record: object, name: str, default: object = None) -> object:
    if isinstance(record, Mapping):
        mapping = cast(Mapping[object, object], record)
        return mapping.get(name, default)
    return getattr(record, name, default)


def _required_string(record: object, name: str) -> str:
    value = _field(record, name)
    if not isinstance(value, str) or not value:
        raise RouteEnvironmentError(f"{name} 需要为非空字符串")
    return value


def _optional_string(record: object, name: str) -> str | None:
    value = _field(record, name)
    return value if isinstance(value, str) and value else None


def _required_int(record: object, name: str) -> int:
    value = _field(record, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouteEnvironmentError(f"{name} 需要为整数")
    return value


def _required_float(record: object, name: str) -> float:
    return _float(_field(record, name), name)


def _float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouteEnvironmentError(f"{name} 需要为数值")
    result = float(value)
    if not math.isfinite(result):
        raise RouteEnvironmentError(f"{name} 需要为有限数值")
    return result


def _mapping_list(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise RouteEnvironmentError(f"{name} 需要为数组")
    result: list[Mapping[str, object]] = []
    for item in cast(list[object], value):
        if not isinstance(item, Mapping):
            raise RouteEnvironmentError(f"{name} 的元素需要为对象")
        result.append(cast(Mapping[str, object], item))
    return tuple(result)


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _optional_document_string(
    document: Mapping[str, object] | None,
    name: str,
) -> str | None:
    if document is None:
        return None
    value = document.get(name)
    return value if isinstance(value, str) and value else None


__all__ = ["RouteEnvironmentError", "build_route_environment_document"]
