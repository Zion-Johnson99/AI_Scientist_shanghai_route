"""天气、空气质量与多源环境数据命令行入口。"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import cast
from uuid import uuid4

import requests

from weather_api_data.archive import Archive
from weather_api_data.config import ConfigurationError, Settings
from weather_api_data.discovery import load_sampling_points
from weather_api_data.exporter import Exporter
from weather_api_data.exposure_pipeline import (
    build_static_exposure_from_project,
    probe_pollen_from_project,
    refresh_exposure_from_project,
)
from weather_api_data.history_store import HistoryStore, HistoryStoreError
from weather_api_data.http_client import ApiRequestError, CallLimitExceeded, HttpClient
from weather_api_data.noise_model import NoiseModelError
from weather_api_data.noise_pipeline import (
    build_noise_from_project,
    prepare_noise_history_from_project,
    probe_noise_from_project,
    refresh_noise_observations_from_project,
)
from weather_api_data.normalizer import ResponseShapeError
from weather_api_data.osm_features import SpatialFeatureError
from weather_api_data.pipeline import PipelineError, WeatherPipeline
from weather_api_data.pm25_fusion import (
    Pm25FusionError,
    fuse_latest_pm25_from_local_sources,
    fuse_pm25_forecast_from_local_sources,
    fuse_pm25_from_local_sources,
)
from weather_api_data.pollen_client import PollenApiError, PollenRunStopped
from weather_api_data.qweather_client import QWeatherApiError, QWeatherClient
from weather_api_data.qweather_discovery import QWeatherDiscoveryService
from weather_api_data.qweather_normalizer import QWeatherNormalizer
from weather_api_data.route_segments import RouteSegmentError
from weather_api_data.scheduler import run_scheduled_refresh
from weather_api_data.shanghai_noise_client import (
    ShanghaiNoiseRequestError,
    ShanghaiNoiseResponseError,
)
from weather_api_data.shanghai_sthj_client import ShanghaiSthjClient
from weather_api_data.standard_client import StandardClient
from weather_api_data.web_export import WebExportError, publish_web_dashboard
from weather_api_data.zone_air_quality import (
    load_air_quality_probe_points,
    load_air_quality_zones,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POINT_ID = "XH_ENT_0001"
_LOGGER = logging.getLogger("weather_api_data")


@dataclass(slots=True)
class Runtime:
    """管理一次 CLI 运行的客户端与本地资源。"""

    pipeline: WeatherPipeline
    session: requests.Session
    history_store: HistoryStore | None

    def close(self) -> None:
        if self.history_store is not None:
            self.history_store.close()
        self.session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weather-api-data")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config-check")
    subparsers.add_parser("dry-run")

    standard = subparsers.add_parser("probe-standard")
    standard.add_argument("--point-id", default=DEFAULT_POINT_ID)
    standard.add_argument("--confirm-standard-probe", action="store_true", required=True)

    qweather = subparsers.add_parser("probe-qweather")
    qweather.add_argument("--point-id", default=DEFAULT_POINT_ID)
    qweather.add_argument("--confirm-qweather-probe", action="store_true", required=True)

    validate = subparsers.add_parser("validate-point")
    validate.add_argument("--point-id", default=DEFAULT_POINT_ID)

    subparsers.add_parser("discover")
    subparsers.add_parser("refresh-weather")
    subparsers.add_parser("refresh")
    subparsers.add_parser("refresh-all")
    subparsers.add_parser("publish-web")
    scheduled = subparsers.add_parser("scheduled-refresh")
    scheduled.add_argument("--tier", choices=("weather", "hourly", "daily"), required=True)

    subparsers.add_parser("export")

    pollen_probe = subparsers.add_parser("probe-pollen")
    pollen_probe.add_argument("--grid-id", default="XH_PM25_G001")
    pollen_probe.add_argument("--confirm-pollen-probe", action="store_true", required=True)

    noise_probe = subparsers.add_parser("probe-noise")
    noise_probe.add_argument("--point-id", default="310104320001")
    noise_probe.add_argument("--confirm-noise-probe", action="store_true", required=True)
    subparsers.add_parser("prepare-noise-data")
    subparsers.add_parser("refresh-noise")
    build_noise = subparsers.add_parser("build-noise")
    build_noise.add_argument("--spatial-features", type=Path)

    refresh_exposure = subparsers.add_parser("refresh-exposure")
    refresh_exposure.add_argument("--spatial-features", type=Path)
    static_exposure = subparsers.add_parser("build-static-exposure")
    static_exposure.add_argument("--spatial-features", type=Path)

    fusion = subparsers.add_parser("fuse-pm25")
    fusion.add_argument("--at", required=True, metavar="ISO-8601")

    prune = subparsers.add_parser("prune-history")
    prune_mode = prune.add_mutually_exclusive_group(required=True)
    prune_mode.add_argument("--dry-run", action="store_true")
    prune_mode.add_argument("--apply", action="store_true")
    return parser


def build_runtime(settings: Settings, root: Path) -> Runtime:
    """根据已校验配置组装实际运行时。"""

    settings.validate_qweather()
    settings.validate_standard()
    paths = _runtime_paths(root)
    _configure_logging(paths["logs"])

    session = requests.Session()
    session.headers.update({"User-Agent": "weather-api-data/0.1.0"})
    qweather_http = HttpClient(
        session,
        settings,
        max_calls_per_run=settings.qweather_max_calls_per_run,
        connect_timeout_seconds=settings.qweather_connect_timeout_seconds,
        read_timeout_seconds=settings.qweather_read_timeout_seconds,
        max_retries=settings.qweather_max_retries,
        min_interval_seconds=settings.qweather_min_interval_seconds,
        jitter_max_seconds=0.0,
    )
    qweather = QWeatherClient(settings, qweather_http)
    history = HistoryStore(paths["database"]) if settings.history_enabled else None
    zone_path = root / "config" / "xuhui_air_quality_zones.json"
    points = (
        *load_sampling_points(root / "config" / "xuhui_sampling_points.json"),
        *load_air_quality_probe_points(zone_path),
    )
    air_quality_zones = load_air_quality_zones(zone_path)
    pipeline = WeatherPipeline(
        provider_client=qweather,
        standard_client=None,
        discovery_service=QWeatherDiscoveryService(),
        normalizer=QWeatherNormalizer(),
        archive=Archive(paths["archive"]),
        history_store=history,
        exporter=Exporter(paths["exports"]),
        cache_path=paths["cache"],
        sampling_points=points,
        station_client=ShanghaiSthjClient(session),
        air_quality_zones=air_quality_zones,
        provider_base_url=settings.qweather_api_host or "",
        reference_point_id=settings.qweather_reference_point_id,
        max_calls_per_run=settings.qweather_max_calls_per_run,
        call_count_fn=lambda: qweather_http.call_count,
    )
    return Runtime(pipeline=pipeline, session=session, history_store=history)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve(strict=False)
    env_file = args.env_file
    if not env_file.is_absolute():
        env_file = root / env_file
    settings = Settings.from_env(env_file)

    if args.command == "config-check":
        _print_json(_config_check(settings, root))
        return 0
    if args.command == "dry-run":
        _print_json(_dry_run(settings, root))
        return 0
    if args.command == "fuse-pm25":
        target_time = datetime.fromisoformat(args.at)
        if target_time.tzinfo is None or target_time.utcoffset() is None:
            raise ValueError("--at 需包含时区，例如 2026-08-25T17:00:00+08:00")
        _print_json(fuse_pm25_from_local_sources(root=root, target_time=target_time))
        return 0
    if args.command == "probe-pollen":
        _print_json(
            probe_pollen_from_project(
                settings=settings,
                root=root,
                grid_id=args.grid_id,
                confirmed=args.confirm_pollen_probe,
            )
        )
        return 0
    if args.command == "probe-standard":
        _print_json(
            _probe_standard_from_project(
                settings=settings,
                root=root,
                point_id=args.point_id,
                confirmed=args.confirm_standard_probe,
            )
        )
        return 0
    if args.command == "prepare-noise-data":
        _print_json(prepare_noise_history_from_project(root))
        return 0
    if args.command == "probe-noise":
        _print_json(
            probe_noise_from_project(
                settings=settings,
                root=root,
                point_id=args.point_id,
                confirmed=args.confirm_noise_probe,
            )
        )
        return 0
    if args.command == "refresh-noise":
        with requests.Session() as session:
            session.headers.update({"User-Agent": "weather-api-data/0.1.0"})
            _print_json(
                refresh_noise_observations_from_project(
                    settings=settings,
                    session=session,
                    root=root,
                )
            )
        return 0
    if args.command == "build-noise":
        _print_json(
            build_noise_from_project(
                root=root,
                spatial_features_path=args.spatial_features,
            )
        )
        return 0
    if args.command == "refresh-exposure":
        _print_json(
            refresh_exposure_from_project(
                settings=settings,
                root=root,
                spatial_features_path=args.spatial_features,
            )
        )
        return 0
    if args.command == "build-static-exposure":
        _print_json(
            build_static_exposure_from_project(
                root=root,
                spatial_features_path=args.spatial_features,
            )
        )
        return 0
    if args.command == "publish-web":
        _print_json(_publish_web_summary(root=root))
        return 0

    runtime = build_runtime(settings, root)
    try:
        pipeline = runtime.pipeline
        if args.command == "probe-qweather":
            if not args.confirm_qweather_probe:
                raise ValueError("probe-qweather 需要 --confirm-qweather-probe")
            output = pipeline.probe_qweather(args.point_id)
        elif args.command == "validate-point":
            output = pipeline.validate_point(args.point_id)
        elif args.command == "discover":
            output = pipeline.discover()
        elif args.command == "refresh-weather":
            output = pipeline.refresh_weather()
        elif args.command in {"refresh", "refresh-all"}:
            output = (
                _refresh_all(pipeline=pipeline, settings=settings, root=root)
                if args.command == "refresh-all"
                else _refresh_weather_and_pm25(pipeline=pipeline, root=root)
            )
        elif args.command == "scheduled-refresh":
            output = run_scheduled_refresh(
                tier=args.tier,
                runtime_dir=root / "runtime",
                weather_refresh=pipeline.refresh_weather,
                hourly_refresh=lambda: _refresh_weather_and_pm25(pipeline=pipeline, root=root),
                daily_refresh=lambda: _refresh_all(
                    pipeline=pipeline,
                    settings=settings,
                    root=root,
                ),
                publish=lambda: _publish_web_summary(root=root),
            )
        elif args.command == "export":
            output = {"status": "ok", "files": pipeline.export()}
        elif args.command == "prune-history":
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.history_retention_days)
            output = pipeline.prune_history(cutoff=cutoff, apply=args.apply)
        else:
            raise AssertionError(f"未处理的命令: {args.command}")
        _print_json(output)
        _LOGGER.info("命令完成 command=%s", args.command)
        return 2 if args.command == "scheduled-refresh" and output.get("status") == "fatal" else 0
    finally:
        runtime.close()


def console_main() -> int:
    """将可预期故障转为脱敏 JSON 错误与非零退出码。"""

    try:
        return main()
    except (
        ApiRequestError,
        CallLimitExceeded,
        ConfigurationError,
        HistoryStoreError,
        PipelineError,
        Pm25FusionError,
        PollenApiError,
        PollenRunStopped,
        NoiseModelError,
        RouteSegmentError,
        WebExportError,
        SpatialFeatureError,
        ResponseShapeError,
        QWeatherApiError,
        ShanghaiNoiseRequestError,
        ShanghaiNoiseResponseError,
        TypeError,
        OSError,
        ValueError,
    ) as error:
        _LOGGER.exception("命令执行失败 error_type=%s", type(error).__name__)
        _print_json(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "message": str(error),
            }
        )
        return 2


def _config_check(settings: Settings, root: Path) -> dict[str, object]:
    settings.validate_standard()
    settings.validate_pollen()
    settings.validate_shanghai_noise()
    if not root.is_dir():
        raise ConfigurationError(f"项目根目录不存在: {root}")
    paths = _runtime_paths(root)
    qweather_missing = [
        name
        for name, value in (
            ("QWEATHER_API_KEY", settings.qweather_api_key),
            ("QWEATHER_API_HOST", settings.qweather_api_host),
        )
        if not value
    ]
    if not settings.qweather_enabled:
        qweather_missing.insert(0, "QWEATHER_ENABLED=true")
    return {
        "status": "partial" if qweather_missing else "ok",
        "weather_provider": settings.weather_provider,
        "qweather_enabled": settings.qweather_enabled,
        "qweather_ready": not qweather_missing,
        "qweather_missing": qweather_missing,
        "qweather_api_host": settings.qweather_api_host,
        "qweather_reference_point_id": settings.qweather_reference_point_id,
        "qweather_hard_limit_per_run": settings.qweather_max_calls_per_run,
        "standard_base_url": settings.standard_base_url,
        "standard_enabled": settings.standard_enabled,
        "history_enabled": settings.history_enabled,
        "history_retention_days": settings.history_retention_days,
        "pollen_enabled": settings.pollen_enabled,
        "pollen_hard_limit_per_run": settings.pollen_max_calls_per_run,
        "shanghai_noise_enabled": settings.shanghai_noise_enabled,
        "shanghai_noise_ready": bool(settings.shanghai_noise_token),
        "shanghai_noise_api_url": settings.shanghai_noise_api_url,
        "shanghai_noise_hard_limit_per_run": settings.shanghai_noise_max_calls_per_run,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def _dry_run(settings: Settings, root: Path) -> dict[str, object]:
    settings.validate_pollen()
    settings.validate_shanghai_noise()
    paths = _runtime_paths(root)
    estimated_calls = {
        "probe-qweather": 2,
        "probe-standard": 1,
        "validate-point": 6,
        "discover": 0,
        "refresh-weather": 3,
        "refresh": 28,
        "refresh-all-qweather": 28,
        "refresh-all-pollen": 54,
        "probe-pollen": 1,
        "refresh-pollen-grid": 54,
        "probe-noise": 1,
        "refresh-noise": 4,
    }
    return {
        "status": "ok",
        "sampling_point_count": 16,
        "air_quality_zone_count": 11,
        "air_quality_strategy_counts": {
            "qweather_direct": 6,
            "district_blend": 3,
            "shanghai_station": 2,
        },
        "refresh_station_requests": 4,
        "estimated_calls": estimated_calls,
        "qweather_reference_point_id": settings.qweather_reference_point_id,
        "qweather_hard_limit_per_run": settings.qweather_max_calls_per_run,
        "refresh_retry_headroom": max(
            settings.qweather_max_calls_per_run - estimated_calls["refresh"],
            0,
        ),
        "hard_limit_behavior": (f"stop_before_attempt_{settings.qweather_max_calls_per_run + 1}"),
        "estimated_raw_bytes": {name: calls * 100_000 for name, calls in estimated_calls.items()},
        "output_paths": {name: str(path) for name, path in paths.items()},
    }


def _runtime_paths(root: Path) -> dict[str, Path]:
    runtime = root / "runtime"
    return {
        "runtime": runtime,
        "archive": runtime / "archive",
        "database": runtime / "history" / "weather.sqlite",
        "exports": runtime / "exports",
        "cache": runtime / "cache" / "refresh_cache.json",
        "logs": runtime / "logs",
    }


def _configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / "weather_api_data.log"
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve(strict=False) == target.resolve(strict=False)
        for handler in _LOGGER.handlers
    ):
        return
    handler = RotatingFileHandler(
        target,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)


def _probe_standard_from_project(
    *,
    settings: Settings,
    root: Path,
    point_id: str,
    confirmed: bool,
) -> dict[str, object]:
    """使用普通 Key 执行一次与主刷新隔离的定位探针。"""

    if not confirmed:
        raise ValueError("probe-standard 需要 --confirm-standard-probe")
    settings.validate_standard()
    points = load_sampling_points(root / "config" / "xuhui_sampling_points.json")
    point = next((item for item in points if item.point_id == point_id), None)
    if point is None:
        raise ValueError(f"未知采样点: {point_id}")
    with requests.Session() as session:
        session.headers.update({"User-Agent": "weather-api-data/0.1.0"})
        http = HttpClient(
            session,
            settings,
            max_calls_per_run=1,
            max_retries=0,
            min_interval_seconds=0.0,
            jitter_max_seconds=0.0,
        )
        client = StandardClient(settings, http)
        response = client.probe_geoposition(point.latitude, point.longitude)
    return {
        "status": "ok",
        "command": "probe-standard",
        "point_id": point.point_id,
        "http_status": response.status_code,
        "call_count": http.call_count,
        "standard_client_closed": client.closed,
    }


def _refresh_weather_and_pm25(*, pipeline: WeatherPipeline, root: Path) -> dict[str, object]:
    """刷新环境主链并生成当前与可用的未来 PM2.5 网格。"""

    refresh_report = pipeline.refresh()
    current_fusion = _attempt_pm25_fusion(
        "current",
        lambda: fuse_latest_pm25_from_local_sources(root=root),
        stale_output_path=(root / "runtime" / "exports" / "pm25_grid_latest.json"),
    )
    forecast_fusion = _attempt_pm25_fusion(
        "forecast_24h",
        lambda: fuse_pm25_forecast_from_local_sources(root=root),
        stale_output_path=(root / "runtime" / "exports" / "pm25_grid_forecast_24h.json"),
    )
    output = {
        **refresh_report,
        "pm25_grid_fusion": current_fusion,
        "pm25_forecast_fusion": forecast_fusion,
    }
    if any(result.get("status") == "error" for result in (current_fusion, forecast_fusion)):
        output["status"] = "partial"
    return output


def _refresh_all(
    *,
    pipeline: WeatherPipeline,
    settings: Settings,
    root: Path,
) -> dict[str, object]:
    """刷新天气、空气质量、PM2.5 以及每日多源暴露。"""

    output = _refresh_weather_and_pm25(pipeline=pipeline, root=root)
    exposure = _attempt_exposure(
        lambda: refresh_exposure_from_project(settings=settings, root=root),
        output_paths=(
            root / "runtime" / "exports" / "pollen_grid_scores.json",
            root / "runtime" / "exports" / "noise_segments.json",
            root / "runtime" / "exports" / "route_environment.json",
            root / "runtime" / "exports" / "grid_environment_latest.json",
        ),
    )
    output["exposure"] = exposure
    if exposure.get("status") in {"error", "partial"}:
        output["status"] = "partial"
    return output


def _publish_web_summary(*, root: Path) -> dict[str, object]:
    """发布网页数据包并返回适合任务日志记录的小型摘要。"""

    dashboard = publish_web_dashboard(root=root)
    metadata = dashboard.get("metadata")
    grids = dashboard.get("grids")
    routes = dashboard.get("routes")
    if (
        not isinstance(metadata, dict)
        or not isinstance(grids, dict)
        or not isinstance(routes, dict)
    ):
        raise WebExportError("environment_dashboard 缺少 metadata、grids 或 routes")
    metadata_mapping = cast(dict[str, object], metadata)
    grids_mapping = cast(dict[str, object], grids)
    routes_mapping = cast(dict[str, object], routes)
    status = metadata_mapping.get("status")
    if status not in {"ok", "partial", "stale"}:
        raise WebExportError("environment_dashboard.metadata.status 无效")
    return {
        "status": status,
        "output_path": str(
            root.parent / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json"
        ),
        "generated_at": metadata_mapping.get("generated_at"),
        "grid_count": grids_mapping.get("count"),
        "route_count": routes_mapping.get("count"),
    }


def _attempt_exposure(
    operation: Callable[[], dict[str, object]],
    *,
    output_paths: tuple[Path, ...],
) -> dict[str, object]:
    """运行花粉与噪声链路并隔离未被本轮更新的旧文件。"""

    try:
        return operation()
    except (
        CallLimitExceeded,
        PollenApiError,
        PollenRunStopped,
        NoiseModelError,
        RouteSegmentError,
        SpatialFeatureError,
        TypeError,
        OSError,
        ValueError,
    ) as error:
        _LOGGER.warning(
            "多源暴露刷新失败 error_type=%s message=%s",
            type(error).__name__,
            error,
        )
        result: dict[str, object] = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        quarantined = [
            str(target)
            for path in output_paths
            if (target := _quarantine_stale_output(path)) is not None
        ]
        if quarantined:
            result["stale_outputs_quarantined_to"] = quarantined
        return result


def _attempt_pm25_fusion(
    mode: str,
    operation: Callable[[], dict[str, object]],
    *,
    stale_output_path: Path,
) -> dict[str, object]:
    try:
        return operation()
    except Pm25FusionError as error:
        _LOGGER.warning(
            "PM2.5 融合不可用 mode=%s error_type=%s message=%s",
            mode,
            type(error).__name__,
            error,
        )
        result: dict[str, object] = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        quarantined = _quarantine_stale_output(stale_output_path)
        if quarantined is not None:
            result["stale_output_quarantined_to"] = str(quarantined)
        return result


def _quarantine_stale_output(path: Path) -> Path | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise OSError(f"旧融合输出路径类型异常: {path}")
    stale_dir = path.parent / "stale"
    stale_dir.mkdir(parents=True, exist_ok=True)
    target = stale_dir / f"{path.stem}.{uuid4().hex}{path.suffix}"
    path.replace(target)
    _LOGGER.info("旧融合输出已移入留档 source=%s target=%s", path, target)
    return target


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, default=str))


__all__ = ["Runtime", "build_parser", "build_runtime", "console_main", "main"]
