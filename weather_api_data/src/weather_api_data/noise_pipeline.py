"""上海噪声历史基线与 API 观测的独立刷新编排。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import requests

from weather_api_data.archive import Archive
from weather_api_data.config import Settings
from weather_api_data.exporter import export_exposure_documents
from weather_api_data.noise_model import build_noise_segments_document
from weather_api_data.noise_observations import (
    XUHUI_NOISE_POINT_IDS,
    build_noise_calibration,
    write_noise_data_products,
)
from weather_api_data.shanghai_noise_client import (
    ShanghaiNoiseClient,
    ShanghaiNoiseRequestError,
    ShanghaiNoiseResponseError,
)


def build_noise_from_project(
    *,
    root: Path,
    spatial_features_path: Path | None = None,
) -> dict[str, object]:
    """独立生成噪声路段结果且不依赖 PM2.5 输出。"""

    calibration_path = _prepare_historical_calibration(root)
    resolved_spatial_path = spatial_features_path
    if resolved_spatial_path is not None and not resolved_spatial_path.is_absolute():
        resolved_spatial_path = root / resolved_spatial_path
    document = build_noise_segments_document(
        routes_path=(root.parent / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"),
        config_path=root / "config" / "noise_model.json",
        spatial_features_path=resolved_spatial_path,
        calibration_path=calibration_path,
    )
    observation_path = root / "runtime" / "exports" / "noise_observation_latest.json"
    if observation_path.is_file():
        context = json.loads(observation_path.read_text(encoding="utf-8"))
        if isinstance(context, Mapping):
            document["observation_context"] = dict(cast(Mapping[str, object], context))
    output_path = export_exposure_documents(
        root / "runtime" / "exports",
        {"noise_segments.json": document},
    )["noise_segments.json"]
    return {
        "status": document["status"],
        "route_count": document["route_count"],
        "segment_count": document["segment_count"],
        "calibration_status": document["calibration_status"],
        "output_path": str(output_path),
    }


def prepare_noise_history_from_project(root: Path) -> dict[str, object]:
    """按项目固定目录生成徐汇历史噪声观测和基线。"""

    calibration_path = _prepare_historical_calibration(root)
    calibration = cast(
        Mapping[str, object],
        json.loads(calibration_path.read_text(encoding="utf-8")),
    )
    return {
        "status": calibration.get("status", "no_data"),
        "observation_count": calibration.get("observation_count", 0),
        "station_count": calibration.get("station_count", 0),
        "calibration_path": str(calibration_path),
        "observations_path": str(calibration_path.parent / "xuhui_noise_observations.csv"),
    }


def probe_noise_from_project(
    *,
    settings: Settings,
    root: Path,
    point_id: str,
    confirmed: bool,
) -> dict[str, object]:
    """对一个徐汇噪声站点执行经确认的十条观测探针。"""

    if not confirmed:
        raise ValueError("噪声探针需要 --confirm-noise-probe")
    if point_id not in XUHUI_NOISE_POINT_IDS:
        raise ValueError(f"未知徐汇噪声点位: {point_id}")
    settings.validate_shanghai_noise()
    token = settings.shanghai_noise_token
    assert token is not None
    with requests.Session() as session:
        session.headers.update({"User-Agent": "weather-api-data/0.1.0"})
        result = ShanghaiNoiseClient(
            session,
            token=token,
            endpoint=settings.shanghai_noise_api_url,
            timeout=(
                settings.shanghai_noise_connect_timeout_seconds,
                settings.shanghai_noise_read_timeout_seconds,
            ),
        ).fetch(
            limit=10,
            query_fields={"pointid": point_id, "jhpt_delete": "0"},
        )
    Archive(root / "runtime" / "archive" / "noise").archive(
        "shanghai_noise_probe",
        f"xuhui_{point_id}",
        result.fetched_at,
        {
            "code": result.api_code,
            "message": result.api_message,
            "total": result.total,
            "status": result.status,
            "data": [dict(item.raw_data) for item in result.observations],
        },
    )
    return {
        "status": result.status,
        "point_id": point_id,
        "total": result.total,
        "page_count": len(result.observations),
        "call_count": 1,
        "fetched_at": result.fetched_at.isoformat(),
    }


def refresh_noise_observations_from_project(
    *,
    settings: Settings,
    session: requests.Session,
    root: Path,
    generated_at: datetime | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """准备历史校准并在启用时低频拉取徐汇四站 API 观测。"""

    calibration_path = _prepare_historical_calibration(root)
    if not settings.shanghai_noise_enabled:
        return {
            "status": "disabled",
            "api_status": "disabled",
            "call_count": 0,
            "historical_calibration_path": str(calibration_path),
            "calibration_applied": True,
        }
    settings.validate_shanghai_noise()
    token = settings.shanghai_noise_token
    assert token is not None
    client = ShanghaiNoiseClient(
        session,
        token=token,
        endpoint=settings.shanghai_noise_api_url,
        timeout=(
            settings.shanghai_noise_connect_timeout_seconds,
            settings.shanghai_noise_read_timeout_seconds,
        ),
    )
    archive = Archive(root / "runtime" / "archive" / "noise")
    records: list[Mapping[str, object]] = []
    fetched_at = generated_at or datetime.now(timezone.utc)
    call_count = 0
    try:
        for index, point_id in enumerate(XUHUI_NOISE_POINT_IDS):
            if call_count >= settings.shanghai_noise_max_calls_per_run:
                break
            call_count += 1
            result = client.fetch(
                limit=settings.shanghai_noise_page_size,
                query_fields={"pointid": point_id, "jhpt_delete": "0"},
            )
            records.extend(item.raw_data for item in result.observations)
            archive.archive(
                "shanghai_noise_observations",
                f"xuhui_{point_id}",
                result.fetched_at,
                {
                    "code": result.api_code,
                    "message": result.api_message,
                    "provider_message": result.provider_message,
                    "total": result.total,
                    "status": result.status,
                    "data": [dict(item.raw_data) for item in result.observations],
                },
            )
            if index < len(XUHUI_NOISE_POINT_IDS) - 1:
                sleep_fn(settings.shanghai_noise_min_interval_seconds)
    except (ShanghaiNoiseRequestError, ShanghaiNoiseResponseError) as error:
        context = _context_document(
            status="error",
            calibration=None,
            fetched_at=fetched_at,
            settings=settings,
            call_count=call_count,
            error=error,
        )
        output_path = _write_context(root, context, fetched_at)
        return {
            "status": "error",
            "api_status": "error",
            "call_count": call_count,
            "error_type": type(error).__name__,
            "historical_calibration_path": str(calibration_path),
            "observation_context_path": str(output_path),
            "calibration_applied": True,
        }

    calibration = build_noise_calibration(records)
    api_status = _freshness_status(calibration, fetched_at, settings.shanghai_noise_max_age_hours)
    context = _context_document(
        status=api_status,
        calibration=calibration,
        fetched_at=fetched_at,
        settings=settings,
        call_count=call_count,
    )
    output_path = _write_context(root, context, fetched_at)
    return {
        "status": "ok" if api_status == "ok" else "partial",
        "api_status": api_status,
        "call_count": call_count,
        "observation_count": calibration["observation_count"],
        "station_count": calibration["station_count"],
        "historical_calibration_path": str(calibration_path),
        "observation_context_path": str(output_path),
        "calibration_applied": True,
    }


def _prepare_historical_calibration(root: Path) -> Path:
    source = (
        root
        / "noise_data"
        / "xuhui_noise_monitoring"
        / "origin_data"
        / "shanghai_noise_monitoring.csv"
    )
    processed = root / "noise_data" / "xuhui_noise_monitoring" / "xuhui_data"
    calibration = processed / "xuhui_noise_baseline.json"
    observations = processed / "xuhui_noise_observations.csv"
    if (
        not calibration.is_file()
        or not observations.is_file()
        or source.stat().st_mtime > calibration.stat().st_mtime
    ):
        return write_noise_data_products(source, processed).calibration_path
    return calibration


def _freshness_status(
    calibration: Mapping[str, object],
    fetched_at: datetime,
    max_age_hours: int,
) -> str:
    status = str(calibration.get("status", "no_data"))
    if status == "no_data":
        return status
    baseline = calibration.get("district_baseline")
    if not isinstance(baseline, Mapping):
        return "no_data"
    baseline_mapping = cast(Mapping[object, object], baseline)
    observed_to = baseline_mapping.get("observed_to")
    if not isinstance(observed_to, str):
        return "no_data"
    observed_at = datetime.fromisoformat(observed_to)
    now = fetched_at if fetched_at.tzinfo is not None else fetched_at.replace(tzinfo=timezone.utc)
    if now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc) > timedelta(
        hours=max_age_hours
    ):
        return "stale"
    return status


def _context_document(
    *,
    status: str,
    calibration: Mapping[str, object] | None,
    fetched_at: datetime,
    settings: Settings,
    call_count: int,
    error: Exception | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "1.0",
        "dataset_type": "noise_observation_context",
        "status": status,
        "source": "shanghai_open_data:O5485687412025006",
        "source_url": settings.shanghai_noise_api_url,
        "fetched_at": fetched_at.isoformat(),
        "expires_at": (
            fetched_at + timedelta(hours=settings.shanghai_noise_max_age_hours)
        ).isoformat(),
        "call_count": call_count,
        "calibration_applied_to_segments": False,
        "limitations": [
            "public API observations are monitoring-station context",
            "road-segment scores retain the historical baseline and spatial proxy features",
        ],
    }
    if calibration is not None:
        document["observation_count"] = calibration["observation_count"]
        document["station_count"] = calibration["station_count"]
        document["district_baseline"] = calibration["district_baseline"]
        document["quality"] = calibration["quality"]
    if error is not None:
        document["error_type"] = type(error).__name__
    return document


def _write_context(root: Path, document: Mapping[str, object], generated_at: datetime) -> Path:
    paths = export_exposure_documents(
        root / "runtime" / "exports",
        {"noise_observation_latest.json": document},
        generated_at=generated_at,
    )
    return paths["noise_observation_latest.json"]


__all__ = [
    "build_noise_from_project",
    "prepare_noise_history_from_project",
    "probe_noise_from_project",
    "refresh_noise_observations_from_project",
]
