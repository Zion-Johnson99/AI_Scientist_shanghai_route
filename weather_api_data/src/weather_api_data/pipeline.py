"""和风天气刷新、WeatherCN 历史回填、入库与导出编排。"""

from __future__ import annotations

import calendar
import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from weather_api_data.air_quality_integration import build_zone_air_quality_records
from weather_api_data.archive import Archive
from weather_api_data.discovery import DiscoveryResult, LocationDiscovery
from weather_api_data.exporter import Exporter
from weather_api_data.history_store import HistoryStore
from weather_api_data.http_client import ApiRequestError, CallLimitExceeded, HttpResult
from weather_api_data.models import NormalizedRecord, SamplingPoint
from weather_api_data.normalizer import Normalizer, ResponseShapeError
from weather_api_data.qweather_client import QWeatherApiError
from weather_api_data.shanghai_sthj_client import (
    ShanghaiSthjBatchResult,
    ShanghaiSthjFetchResult,
    ShanghaiSthjRequestError,
    ShanghaiSthjResponseError,
)
from weather_api_data.shanghai_sthj_normalizer import normalize_station_observation

_ACTIVE_ENDPOINTS = (
    "current_conditions",
    "hourly_weather_24",
    "current_air_quality",
    "hourly_air_quality_24",
    "indices_3day",
    "alerts",
)
_LATEST_BUCKETS = {
    "current_conditions": "current_weather",
    "indices_3day": "daily_indices_3day",
    "alerts": "active_alerts",
}
_HOURLY_BUCKETS = {
    "hourly_weather_24": "weather_forecast_24h",
}
_CACHE_ENDPOINTS = (*_ACTIVE_ENDPOINTS, "point_air_quality")
_NEAR_EXPIRY_REFRESH_MARGINS = {
    "current_conditions": timedelta(minutes=5),
    "hourly_weather_24": timedelta(minutes=5),
    "current_air_quality": timedelta(minutes=5),
    "hourly_air_quality_24": timedelta(minutes=5),
    "indices_3day": timedelta(minutes=5),
    "alerts": timedelta(minutes=1),
}


class ProviderOperations(Protocol):
    def current_conditions(self, source_id: str) -> HttpResult: ...

    def hourly_weather_24(self, source_id: str) -> HttpResult: ...

    def current_air_quality(self, source_id: str) -> HttpResult: ...

    def hourly_air_quality_24(self, source_id: str) -> HttpResult: ...

    def indices_3day(self, source_id: str) -> HttpResult: ...

    def alerts(self, source_id: str) -> HttpResult: ...


class LegacyAdvancedOperations(Protocol):
    def current_conditions(self, location_key: str) -> HttpResult: ...

    def climo_actuals(self, location_key: str, year: int, month: int) -> HttpResult: ...


class DiscoveryOperations(Protocol):
    def discover(self, points: Sequence[SamplingPoint]) -> DiscoveryResult: ...

    def discover_locations(
        self,
        points: Sequence[SamplingPoint],
    ) -> tuple[LocationDiscovery, ...]: ...


class NormalizerOperations(Protocol):
    def normalize(
        self,
        endpoint: str,
        result: HttpResult,
        source_id: str,
        probe_point_ids: tuple[str, ...] = (),
    ) -> list[NormalizedRecord]: ...


class LegacyDiscoveryOperations(Protocol):
    def discover_locations(
        self,
        points: Sequence[SamplingPoint],
    ) -> tuple[LocationDiscovery, ...]: ...


class StandardOperations(Protocol):
    @property
    def closed(self) -> bool: ...

    def probe_geoposition(self, latitude: float, longitude: float) -> HttpResult: ...


class StationOperations(Protocol):
    def fetch_stations(self) -> ShanghaiSthjBatchResult: ...


class PipelineError(RuntimeError):
    """表示编排或本地状态违反明确契约。"""


class BackfillUnavailableError(PipelineError):
    """表示提供方无权限或无当月气候实测数据。"""

    def __init__(self, report: Mapping[str, object]) -> None:
        self.report = dict(report)
        super().__init__("提供方未返回可用的当月气候实测数据")


class WeatherPipeline:
    """在调用硬上限内组织和风天气活动链路。"""

    def __init__(
        self,
        *,
        provider_client: ProviderOperations,
        standard_client: StandardOperations | None,
        discovery_service: DiscoveryOperations,
        normalizer: NormalizerOperations,
        archive: Archive,
        history_store: HistoryStore | None,
        exporter: Exporter,
        cache_path: str | Path,
        sampling_points: Sequence[SamplingPoint],
        station_client: StationOperations,
        air_quality_zones: Sequence[Mapping[str, object]],
        provider_base_url: str,
        reference_point_id: str,
        legacy_advanced_client: LegacyAdvancedOperations | None = None,
        legacy_discovery_service: LegacyDiscoveryOperations | None = None,
        legacy_normalizer: Normalizer | None = None,
        max_calls_per_run: int = 80,
        now_fn: Callable[[], datetime] | None = None,
        call_count_fn: Callable[[], int] | None = None,
    ) -> None:
        if not sampling_points:
            raise ValueError("至少需要一个采样点")
        if max_calls_per_run <= 0:
            raise ValueError("max_calls_per_run 需大于 0")
        if len(air_quality_zones) != 11:
            raise ValueError("空气质量分区数量需为 11")
        if not provider_base_url.startswith("https://"):
            raise ValueError("活动提供方基础地址需使用 HTTPS")
        if reference_point_id not in {point.point_id for point in sampling_points}:
            raise ValueError(f"和风参考点不存在: {reference_point_id}")
        self._provider = provider_client
        self._standard = standard_client
        self._discovery = discovery_service
        self._normalizer = normalizer
        self._legacy_advanced = legacy_advanced_client
        self._legacy_discovery = legacy_discovery_service
        self._legacy_normalizer = legacy_normalizer
        self._archive = archive
        self._history = history_store
        self._exporter = exporter
        self._cache_path = Path(cache_path)
        self._points = tuple(sampling_points)
        self._station = station_client
        self._air_quality_zones = tuple(dict(zone) for zone in air_quality_zones)
        self._provider_base_url = provider_base_url.rstrip("/")
        self._reference_point_id = reference_point_id
        self._air_quality_point_ids = _air_quality_point_ids(self._air_quality_zones)
        self._max_calls_per_run = max_calls_per_run
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._call_count = call_count_fn or (lambda: 0)

    def probe_standard(self, point_id: str, *, confirmed: bool) -> dict[str, object]:
        """经显式确认后执行一次标准定位探针。"""

        if not confirmed:
            raise ValueError("probe-standard 需要 --confirm-standard-probe")
        if self._standard is None:
            raise PipelineError("标准客户端未配置")
        point = self._point(point_id)
        response = self._standard.probe_geoposition(point.latitude, point.longitude)
        return {
            "status": "ok",
            "command": "probe-standard",
            "point_id": point.point_id,
            "http_status": response.status_code,
            "call_count": 1,
            "standard_client_closed": self._standard.closed,
        }

    def probe_qweather(self, point_id: str) -> dict[str, object]:
        """执行和风当前天气与空气质量两次认证探针。"""

        start_calls = self._call_count()
        point = self._point(point_id)
        locations = self._discovery.discover_locations((point,))
        location = locations[0]
        records: list[NormalizedRecord] = []
        for endpoint, request in (
            (
                "current_conditions",
                lambda: self._provider.current_conditions(location.location_key),
            ),
            (
                "current_air_quality",
                lambda: self._provider.current_air_quality(location.location_key),
            ),
        ):
            response = request()
            records.extend(
                self._normalizer.normalize(
                    endpoint,
                    response,
                    location.location_key,
                    location.probe_point_ids,
                )
            )
        return {
            "status": _records_status(records),
            "command": "probe-qweather",
            "point_id": point.point_id,
            "location": location.to_dict(),
            "call_count": self._call_count() - start_calls,
            "records": [record.to_dict() for record in records],
        }

    def probe_advanced(self, point_id: str) -> dict[str, object]:
        """保留华风进阶定位与当前天气的独立探针。"""

        if (
            self._legacy_advanced is None
            or self._legacy_discovery is None
            or self._legacy_normalizer is None
        ):
            raise PipelineError("华风进阶探针未配置")
        start_calls = self._call_count()
        point = self._point(point_id)
        location = self._legacy_discovery.discover_locations((point,))[0]
        response = self._legacy_advanced.current_conditions(location.location_key)
        records = self._legacy_normalizer.normalize(
            "current_conditions",
            response,
            location.location_key,
            location.probe_point_ids,
        )
        return {
            "status": _records_status(records),
            "command": "probe-advanced",
            "point_id": point.point_id,
            "location": location.to_dict(),
            "call_count": self._call_count() - start_calls,
            "records": [record.to_dict() for record in records],
        }

    def validate_point(self, point_id: str) -> dict[str, object]:
        """对一个入口验证定位与八类实时业务端点。"""

        started = self._call_count()
        point = self._point(point_id)
        location = self._discovery.discover_locations((point,))[0]
        records: list[NormalizedRecord] = []
        errors: list[dict[str, object]] = []
        for endpoint, request in self._requests(location.location_key):
            try:
                response = request()
                self._archive.archive(
                    endpoint, location.location_key, response.fetched_at, response.payload
                )
                records.extend(
                    self._normalizer.normalize(
                        endpoint,
                        response,
                        location.location_key,
                        location.probe_point_ids,
                    )
                )
            except (ApiRequestError, QWeatherApiError, ResponseShapeError, ValueError) as error:
                errors.append(_safe_error(endpoint, location.location_key, error))
        written, skipped = self._write_records(records)
        quality_issues = _record_quality_issues(records)
        return {
            "status": "partial" if errors or quality_issues else "ok",
            "command": "validate-point",
            "point_id": point.point_id,
            "location": location.to_dict(),
            "call_count": self._call_count() - started,
            "records_written": written,
            "records_skipped": skipped,
            "quality_issues": quality_issues,
            "errors": errors,
        }

    def discover(self) -> dict[str, object]:
        """完成入口点到和风坐标来源的零网络发现。"""

        started = self._call_count()
        result = self._discovery.discover(self._points)
        reference_source_id = self._reference_source_id(result.locations)
        regions = self._regions_from_discovery(result, reference_source_id)
        cache = self._load_cache()
        cache["regions"] = regions
        report = {
            "status": result.status,
            "command": "discover",
            "call_count": self._call_count() - started,
            "location_count": len(result.locations),
            "reference_point_id": self._reference_point_id,
            "reference_source_id": reference_source_id,
        }
        cache["last_run_report"] = report
        self._save_cache(cache)
        return {**report, "regions": regions}

    def refresh(self) -> dict[str, object]:
        """重新定位并仅刷新已过 Expires 的业务端点。"""

        return self._run_tracked("refresh", self._refresh_run)

    def refresh_weather(self) -> dict[str, object]:
        """仅刷新参考来源的当前天气、24 小时天气与预警。"""

        return self._run_tracked("refresh-weather", self._refresh_weather_run)

    def _refresh_weather_run(self, run_id: str, started_at: str) -> dict[str, object]:
        started_calls = self._call_count()
        cache = self._load_cache()
        entries = _entries(cache)
        locations = self._discovery.discover_locations(self._points)
        reference_source_id = self._reference_source_id(locations)
        reference_location = next(
            location
            for location in locations
            if self._reference_point_id in location.probe_point_ids
        )
        requests = (
            (
                "current_conditions",
                lambda: self._provider.current_conditions(reference_source_id),
            ),
            (
                "hourly_weather_24",
                lambda: self._provider.hourly_weather_24(reference_source_id),
            ),
            ("alerts", lambda: self._provider.alerts(reference_source_id)),
        )
        fresh_records: list[NormalizedRecord] = []
        errors: list[dict[str, object]] = []
        cache_hits = 0

        for endpoint, request in requests:
            cache_key = _cache_key(endpoint, reference_source_id)
            refresh_margin = _NEAR_EXPIRY_REFRESH_MARGINS.get(endpoint, timedelta(0))
            cached = _unexpired_records(
                entries.get(cache_key),
                _aware_utc(self._now()),
                refresh_margin=refresh_margin,
            )
            if cached is not None:
                cache_hits += 1
                continue
            try:
                response = request()
                self._archive.archive(
                    endpoint,
                    reference_source_id,
                    response.fetched_at,
                    response.payload,
                )
                normalized = self._normalizer.normalize(
                    endpoint,
                    response,
                    reference_source_id,
                    reference_location.probe_point_ids,
                )
                serialized = [record.to_dict() for record in normalized]
                fresh_records.extend(normalized)
                entries[cache_key] = {
                    "valid_until": (
                        normalized[0].valid_until
                        if normalized
                        else _iso(response.fetched_at + timedelta(minutes=5))
                    ),
                    "records": serialized,
                }
            except (
                ApiRequestError,
                CallLimitExceeded,
                QWeatherApiError,
                ResponseShapeError,
                ValueError,
            ) as error:
                errors.append(_safe_error(endpoint, reference_source_id, error))

        written, skipped = self._write_records(fresh_records)
        now = _aware_utc(self._now())
        records_by_endpoint = _records_from_entries(entries, now)
        regions_value = cache.get("regions")
        if isinstance(regions_value, dict):
            regions = cast(dict[str, object], regions_value)
        else:
            regions = self._regions(
                locations,
                records_by_endpoint["current_air_quality"],
                reference_source_id,
            )
        quality_issues = _serialized_quality_issues(records_by_endpoint)
        report: dict[str, object] = {
            "status": (
                "partial"
                if errors or quality_issues or regions.get("status") == "partial"
                else "ok"
            ),
            "command": "refresh-weather",
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": _iso(self._now()),
            "call_count": self._call_count() - started_calls,
            "cache_hits": cache_hits,
            "location_count": len(locations),
            "reference_point_id": self._reference_point_id,
            "reference_source_id": reference_source_id,
            "records_written": written,
            "records_skipped": skipped,
            "quality_issues": quality_issues,
            "errors": errors,
        }
        self._attach_run_metrics(report, started_calls)
        cache["entries"] = entries
        cache["regions"] = regions
        cache["last_run_report"] = report
        self._save_cache(cache)
        self._export_documents(
            regions,
            records_by_endpoint,
            report,
            reference_source_id=reference_source_id,
        )
        return report

    def _refresh_run(self, run_id: str, started_at: str) -> dict[str, object]:
        started_calls = self._call_count()
        cache = self._load_cache()
        entries = _entries(cache)
        locations = self._discovery.discover_locations(self._points)
        reference_source_id = self._reference_source_id(locations)
        records_by_endpoint: dict[str, list[dict[str, object]]] = {
            endpoint: [] for endpoint in _CACHE_ENDPOINTS
        }
        fresh_records: list[NormalizedRecord] = []
        errors: list[dict[str, object]] = []
        cache_hits = 0
        halt_reason: str | None = None

        for location in locations:
            for endpoint, request in self._refresh_requests(location, reference_source_id):
                cache_key = _cache_key(endpoint, location.location_key)
                refresh_margin = _NEAR_EXPIRY_REFRESH_MARGINS.get(endpoint, timedelta(0))
                cached = _unexpired_records(
                    entries.get(cache_key),
                    _aware_utc(self._now()),
                    refresh_margin=refresh_margin,
                )
                if cached is not None:
                    records_by_endpoint[endpoint].extend(cached)
                    cache_hits += 1
                    continue
                try:
                    response = request()
                    self._archive.archive(
                        endpoint,
                        location.location_key,
                        response.fetched_at,
                        response.payload,
                    )
                    normalized = self._normalizer.normalize(
                        endpoint,
                        response,
                        location.location_key,
                        location.probe_point_ids,
                    )
                    serialized = [record.to_dict() for record in normalized]
                    records_by_endpoint[endpoint].extend(serialized)
                    fresh_records.extend(normalized)
                    entries[cache_key] = {
                        "valid_until": (
                            normalized[0].valid_until
                            if normalized
                            else _iso(response.fetched_at + timedelta(minutes=5))
                        ),
                        "records": serialized,
                    }
                except CallLimitExceeded as error:
                    errors.append(_safe_error(endpoint, location.location_key, error))
                    halt_reason = "call_limit_exceeded"
                    break
                except ApiRequestError as error:
                    errors.append(_safe_error(endpoint, location.location_key, error))
                    if error.status_code == 429:
                        halt_reason = "rate_limited"
                        break
                except (QWeatherApiError, ResponseShapeError, ValueError) as error:
                    errors.append(_safe_error(endpoint, location.location_key, error))
            if halt_reason is not None:
                break

        station_results: tuple[ShanghaiSthjFetchResult, ...] = ()
        station_records: list[dict[str, object]] = []
        station_request_count = 0
        try:
            station_batch = self._station.fetch_stations()
            station_results = station_batch.results
            station_request_count = station_batch.request_count
            errors.extend(_safe_station_error(error) for error in station_batch.errors)
            station_zone_ids = _station_zone_ids(self._air_quality_zones)
            station_records = [
                normalize_station_observation(
                    result,
                    zone_ids=station_zone_ids.get(result.station_id, ()),
                )
                for result in station_results
            ]
        except (ShanghaiSthjRequestError, ShanghaiSthjResponseError, ValueError) as error:
            station_request_count = 1
            errors.append(_safe_station_error(error))

        zone_records = list(
            build_zone_air_quality_records(
                self._air_quality_zones,
                records_by_endpoint["current_air_quality"],
                station_records,
                provider_base_url=self._provider_base_url,
            )
        )
        records_by_endpoint["point_air_quality"] = zone_records
        entries[_cache_key("point_air_quality", "zones")] = {
            "valid_until": _iso(self._now() + timedelta(hours=1)),
            "records": zone_records,
        }

        written, skipped = self._write_records(fresh_records)
        regions = self._regions(
            locations,
            records_by_endpoint["current_air_quality"],
            reference_source_id,
        )
        quality_issues = _serialized_quality_issues(records_by_endpoint)
        status = "ok"
        if halt_reason is not None:
            status = "error"
        elif errors or quality_issues or regions["status"] == "partial":
            status = "partial"
        report: dict[str, object] = {
            "status": status,
            "command": "refresh",
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": _iso(self._now()),
            "call_count": self._call_count() - started_calls,
            "cache_hits": cache_hits,
            "location_count": len(locations),
            "reference_point_id": self._reference_point_id,
            "reference_source_id": reference_source_id,
            "air_quality_zone_count": len(zone_records),
            "air_quality_strategy_counts": dict(
                Counter(str(zone["source_strategy"]) for zone in self._air_quality_zones)
            ),
            "station_request_count": station_request_count,
            "station_status_counts": dict(
                Counter(str(record["status"]) for record in station_records)
            ),
            "station_observations": [
                {
                    "station_id": record["spatial_id"],
                    "zone_ids": record["zone_ids"],
                    "observed_at": record["observed_at"],
                    "status": record["status"],
                    "values": record["values"],
                }
                for record in station_records
            ],
            "records_written": written,
            "records_skipped": skipped,
            "quality_issues": quality_issues,
            "errors": errors,
            "historical_pm2_5_2025": "unavailable_from_provider",
        }
        if halt_reason is not None:
            report["halt_reason"] = halt_reason
        self._attach_run_metrics(report, started_calls)
        cache["entries"] = entries
        cache["regions"] = regions
        cache["last_run_report"] = report
        self._save_cache(cache)
        self._export_documents(
            regions,
            records_by_endpoint,
            report,
            reference_source_id=reference_source_id,
        )
        return report

    def backfill(self, *, year: int, month: int) -> dict[str, object]:
        """按月回填 2025 年日级天气实测。"""

        if year != 2025:
            raise ValueError("首版回填年份固定为 2025")
        if not 1 <= month <= 12:
            raise ValueError("回填月份需位于 1 至 12")
        return self._run_tracked(
            "backfill",
            lambda run_id, started_at: self._backfill_run(year, month, run_id, started_at),
        )

    def _backfill_run(
        self, year: int, month: int, run_id: str, started_at: str
    ) -> dict[str, object]:
        if (
            self._legacy_advanced is None
            or self._legacy_discovery is None
            or self._legacy_normalizer is None
        ):
            raise PipelineError("华风进阶历史回填未配置")
        started_calls = self._call_count()
        locations = self._legacy_discovery.discover_locations(self._points)
        records: list[NormalizedRecord] = []
        records_by_location: dict[str, list[NormalizedRecord]] = {}
        for location in locations:
            try:
                response = self._legacy_advanced.climo_actuals(location.location_key, year, month)
                self._archive.archive(
                    "climo_actuals",
                    location.location_key,
                    response.fetched_at,
                    response.payload,
                )
                normalized = self._legacy_normalizer.normalize(
                    "climo_actuals",
                    response,
                    location.location_key,
                    location.probe_point_ids,
                )
            except ApiRequestError as error:
                if error.status_code in {401, 403}:
                    report = self._backfill_unavailable_report(
                        run_id, started_at, started_calls, year, month, error.status_code
                    )
                    raise BackfillUnavailableError(report) from error
                raise
            if all(record.status == "no_data" for record in normalized):
                records_by_location[location.location_key] = []
                continue
            records.extend(normalized)
            records_by_location[location.location_key] = normalized

        if not records:
            report = self._backfill_unavailable_report(
                run_id, started_at, started_calls, year, month, None
            )
            raise BackfillUnavailableError(report)

        written, skipped = self._write_records(records)
        days = calendar.monthrange(year, month)[1]
        expected_dates = {f"{year}-{month:02d}-{day:02d}" for day in range(1, days + 1)}
        dates_by_location: dict[str, dict[str, list[str]]] = {}
        for location in locations:
            location_records = records_by_location.get(location.location_key, [])
            received = {
                record.business_time[:10]
                for record in location_records
                if record.business_time is not None and len(record.business_time) >= 10
            }
            dates_by_location[location.location_key] = {
                "received_dates": sorted(received),
                "missing_dates": sorted(expected_dates - received),
            }
        missing_dates = sorted(
            {date for details in dates_by_location.values() for date in details["missing_dates"]}
        )
        received_dates = sorted(
            {date for details in dates_by_location.values() for date in details["received_dates"]}
        )
        report: dict[str, object] = {
            "status": "partial" if missing_dates else "ok",
            "command": "backfill",
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": _iso(self._now()),
            "year": year,
            "month": month,
            "call_count": self._call_count() - started_calls,
            "records_written": written,
            "records_skipped": skipped,
            "received_dates": received_dates,
            "missing_dates": missing_dates,
            "dates_by_location": dates_by_location,
            "historical_pm2_5_2025": "unavailable_from_provider",
        }
        self._attach_run_metrics(report, started_calls)
        return report

    def export(self) -> dict[str, Path]:
        """根据本地端点缓存原子生成四类业务 JSON。"""

        cache = self._load_cache()
        regions_value = cache.get("regions")
        if not isinstance(regions_value, dict):
            raise PipelineError("本地缓存缺少空间发现结果，请先运行 discover 或 refresh")
        regions = cast(dict[str, object], regions_value)
        reference_source_id = regions.get("reference_source_id")
        if not isinstance(reference_source_id, str) or not reference_source_id:
            raise PipelineError("本地缓存缺少和风参考来源")
        records_by_endpoint = _records_from_entries(_entries(cache), _aware_utc(self._now()))
        report_value = cache.get("last_run_report", {})
        if not isinstance(report_value, dict):
            raise PipelineError("本地缓存的 run_report 形状无效")
        report = dict(cast(dict[str, object], report_value))
        quality_issues = _serialized_quality_issues(records_by_endpoint)
        if quality_issues:
            if report.get("status") == "ok":
                report["status"] = "partial"
            report["export_quality_issues"] = quality_issues
        return self._export_documents(
            regions,
            records_by_endpoint,
            report,
            reference_source_id=reference_source_id,
        )

    def prune_history(self, *, cutoff: datetime, apply: bool) -> dict[str, object]:
        """检查或删除严格早于截止时间的本地历史。"""

        if self._history is None:
            raise PipelineError("历史库未启用")
        normalized = _aware_utc(cutoff)
        database_counts = self._history.prune_history(_iso(normalized), apply=apply)
        archive_result = self._archive.prune(normalized, apply=apply)
        return {
            "status": "ok",
            "command": "prune-history",
            "apply": apply,
            "cutoff": _iso(normalized),
            "database_records": sum(database_counts.values()),
            "database_tables": database_counts,
            "archive_files": archive_result.file_count,
            "archive_bytes": archive_result.total_bytes,
        }

    def _requests(self, location_key: str) -> tuple[tuple[str, Callable[[], HttpResult]], ...]:
        return (
            ("current_conditions", lambda: self._provider.current_conditions(location_key)),
            ("hourly_weather_24", lambda: self._provider.hourly_weather_24(location_key)),
            ("current_air_quality", lambda: self._provider.current_air_quality(location_key)),
            (
                "hourly_air_quality_24",
                lambda: self._provider.hourly_air_quality_24(location_key),
            ),
            ("indices_3day", lambda: self._provider.indices_3day(location_key)),
            ("alerts", lambda: self._provider.alerts(location_key)),
        )

    def _refresh_requests(
        self,
        location: LocationDiscovery,
        reference_source_id: str,
    ) -> tuple[tuple[str, Callable[[], HttpResult]], ...]:
        requests = dict(self._requests(location.location_key))
        selected: list[tuple[str, Callable[[], HttpResult]]] = []
        if location.location_key == reference_source_id:
            selected.extend(
                (endpoint, requests[endpoint])
                for endpoint in (
                    "current_conditions",
                    "hourly_weather_24",
                    "indices_3day",
                    "alerts",
                )
            )
        if self._air_quality_point_ids.intersection(location.probe_point_ids):
            selected.extend(
                (endpoint, requests[endpoint])
                for endpoint in ("current_air_quality", "hourly_air_quality_24")
            )
        return tuple(selected)

    def _regions(
        self,
        locations: Sequence[LocationDiscovery],
        air_records: Sequence[Mapping[str, object]],
        reference_source_id: str,
    ) -> dict[str, object]:
        sources: list[dict[str, object]] = []
        for location in locations:
            if not self._air_quality_point_ids.intersection(location.probe_point_ids):
                continue
            source_name: object = None
            for record in air_records:
                if record.get("location_key") != location.location_key:
                    continue
                source = record.get("source")
                if isinstance(source, Mapping):
                    source_mapping = cast(Mapping[str, object], source)
                    source_name = source_mapping.get("air_quality_source")
                    if source_name is not None:
                        break
            sources.append(
                {
                    "location_key": location.location_key,
                    "probe_point_ids": list(location.probe_point_ids),
                    "source": source_name,
                    "source_status": "ok"
                    if isinstance(source_name, str) and source_name.strip()
                    else "unknown",
                }
            )
        return {
            "status": "partial"
            if any(source["source_status"] == "unknown" for source in sources)
            else "ok",
            "coordinate_system": "WGS84",
            "provider": "qweather",
            "reference_point_id": self._reference_point_id,
            "reference_source_id": reference_source_id,
            "sampling_points": [
                {
                    "point_id": point.point_id,
                    "name": point.name,
                    "longitude": point.longitude,
                    "latitude": point.latitude,
                }
                for point in self._points
            ],
            "locations": [location.to_dict() for location in locations],
            "air_quality_sources": sources,
            "air_quality_zones": [dict(zone) for zone in self._air_quality_zones],
        }

    def _regions_from_discovery(
        self,
        result: DiscoveryResult,
        reference_source_id: str,
    ) -> dict[str, object]:
        return {
            "status": result.status,
            "coordinate_system": "WGS84",
            "provider": "qweather",
            "reference_point_id": self._reference_point_id,
            "reference_source_id": reference_source_id,
            "sampling_points": [
                {
                    "point_id": point.point_id,
                    "name": point.name,
                    "longitude": point.longitude,
                    "latitude": point.latitude,
                }
                for point in self._points
            ],
            "locations": [location.to_dict() for location in result.locations],
            "air_quality_sources": [source.to_dict() for source in result.air_quality_sources],
            "air_quality_zones": [dict(zone) for zone in self._air_quality_zones],
        }

    def _write_records(self, records: Sequence[NormalizedRecord]) -> tuple[dict[str, int], int]:
        writable = [record for record in records if record.business_time is not None]
        skipped = len(records) - len(writable)
        if self._history is None or not writable:
            return {}, skipped
        return self._history.write_records(writable), skipped

    def _export_documents(
        self,
        regions: Mapping[str, object],
        records_by_endpoint: Mapping[str, Sequence[Mapping[str, object]]],
        report: Mapping[str, object],
        *,
        reference_source_id: str,
    ) -> dict[str, Path]:
        latest: dict[str, object] = {
            bucket: list(records_by_endpoint.get(endpoint, ()))
            for endpoint, bucket in _LATEST_BUCKETS.items()
        }
        latest["reference_source_id"] = reference_source_id
        hourly: dict[str, object] = {
            bucket: list(records_by_endpoint.get(endpoint, ()))
            for endpoint, bucket in _HOURLY_BUCKETS.items()
        }
        hourly["reference_source_id"] = reference_source_id
        if self._history is None:
            history_window: dict[str, object] = {
                "records": [],
                "summary": {
                    "status": "no_data",
                    "expected_hours": 24,
                    "available_hours": 0,
                    "missing_hours": [],
                    "reason": "history_disabled",
                },
            }
        else:
            history_window = self._history.weather_observation_window_24h(
                end_at=self._now(),
                location_key=reference_source_id,
            )
        hourly["weather_history_24h"] = history_window["records"]
        hourly["weather_history_24h_summary"] = history_window["summary"]
        latest["xuhui_aqi"] = _project_location_field(
            records_by_endpoint.get("current_air_quality", ()),
            location_key=reference_source_id,
            field="aqi",
        )
        latest["point_air_quality"] = _without_value_fields(
            records_by_endpoint.get("point_air_quality", ()),
            {"aqi"},
        )
        hourly["xuhui_aqi_forecast_24h"] = _project_location_field(
            records_by_endpoint.get("hourly_air_quality_24", ()),
            location_key=reference_source_id,
            field="aqi",
        )
        hourly["xuhui_pm2_5_forecast_24h"] = _project_location_field(
            records_by_endpoint.get("hourly_air_quality_24", ()),
            location_key=reference_source_id,
            field="pm2_5_ug_m3",
        )
        return self._exporter.export(regions, latest, hourly, report, generated_at=self._now())

    def _point(self, point_id: str) -> SamplingPoint:
        for point in self._points:
            if point.point_id == point_id:
                return point
        raise ValueError(f"未找到采样点: {point_id}")

    def _reference_source_id(self, locations: Sequence[LocationDiscovery]) -> str:
        matches = [
            location.location_key
            for location in locations
            if self._reference_point_id in location.probe_point_ids
        ]
        if len(matches) != 1:
            raise PipelineError("和风参考点未解析到唯一坐标来源")
        return matches[0]

    def _start_run(self, command: str) -> tuple[str, str]:
        run_id = uuid4().hex
        started_at = _iso(self._now())
        if self._history is not None:
            self._history.start_run(run_id, started_at, {"command": command})
        return run_id, started_at

    def _finish_run(self, run_id: str, report: Mapping[str, object]) -> None:
        if self._history is not None:
            self._history.finish_run(
                run_id,
                _iso(self._now()),
                str(report.get("status", "error")),
                report,
            )

    def _run_tracked(
        self,
        command: str,
        operation: Callable[[str, str], dict[str, object]],
    ) -> dict[str, object]:
        started_calls = self._call_count()
        run_id, started_at = self._start_run(command)
        try:
            report = operation(run_id, started_at)
        except BackfillUnavailableError as error:
            self._attach_run_metrics(error.report, started_calls)
            self._record_report(error.report)
            self._finish_run(run_id, error.report)
            raise
        except Exception as error:
            failed_report: dict[str, object] = {
                "status": "failed",
                "command": command,
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": _iso(self._now()),
                "error_type": type(error).__name__,
                "message": str(error),
            }
            self._attach_run_metrics(failed_report, started_calls)
            self._finish_run(run_id, failed_report)
            raise
        self._attach_run_metrics(report, started_calls)
        self._record_report(report)
        self._finish_run(run_id, report)
        return report

    def _attach_run_metrics(self, report: dict[str, object], started_calls: int) -> None:
        used = self._call_count() - started_calls
        report.setdefault("call_count", used)
        report["quota"] = {
            "hard_limit": self._max_calls_per_run,
            "used": used,
            "remaining": max(self._max_calls_per_run - used, 0),
        }
        archive_files = 0
        archive_bytes = 0
        if self._archive.root_dir.exists():
            for path in self._archive.root_dir.rglob("*.json.gz"):
                if path.is_file() and not path.is_symlink():
                    archive_files += 1
                    archive_bytes += path.stat().st_size
        database_bytes = 0
        if self._history is not None and self._history.database_path.exists():
            database_bytes = self._history.database_path.stat().st_size
        cache_bytes = self._cache_path.stat().st_size if self._cache_path.exists() else 0
        report["disk_status"] = {
            "archive_files": archive_files,
            "archive_bytes": archive_bytes,
            "database_bytes": database_bytes,
            "cache_bytes": cache_bytes,
        }

    def _record_report(self, report: Mapping[str, object]) -> None:
        cache = self._load_cache()
        cache["last_run_report"] = dict(report)
        self._save_cache(cache)

    def _backfill_unavailable_report(
        self,
        run_id: str,
        started_at: str,
        started_calls: int,
        year: int,
        month: int,
        http_status: int | None,
    ) -> dict[str, object]:
        return {
            "status": "unavailable_from_provider",
            "command": "backfill",
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": _iso(self._now()),
            "year": year,
            "month": month,
            "http_status": http_status,
            "call_count": self._call_count() - started_calls,
            "missing_dates": [
                f"{year}-{month:02d}-{day:02d}"
                for day in range(1, calendar.monthrange(year, month)[1] + 1)
            ],
            "historical_pm2_5_2025": "unavailable_from_provider",
        }

    def _load_cache(self) -> dict[str, object]:
        if not self._cache_path.exists():
            return {"schema_version": "1.0", "entries": {}}
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PipelineError("端点缓存读取失败") from error
        if not isinstance(payload, dict):
            raise PipelineError("端点缓存顶层应为对象")
        return cast(dict[str, object], payload)

    def _save_cache(self, cache: Mapping[str, object]) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self._cache_path.parent,
                prefix=f".{self._cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(cache, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._cache_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


def _entries(cache: dict[str, object]) -> dict[str, object]:
    value = cache.get("entries")
    if value is None:
        value = {}
        cache["entries"] = value
    if not isinstance(value, dict):
        raise PipelineError("端点缓存 entries 应为对象")
    return cast(dict[str, object], value)


def _cache_key(endpoint: str, location_key: str) -> str:
    return f"{endpoint}|{location_key}"


def _unexpired_records(
    value: object,
    now: datetime,
    *,
    refresh_margin: timedelta = timedelta(0),
) -> list[dict[str, object]] | None:
    if not isinstance(value, dict):
        return None
    entry = cast(dict[str, object], value)
    valid_until = entry.get("valid_until")
    records = entry.get("records")
    if not isinstance(valid_until, str) or not isinstance(records, list):
        return None
    try:
        expiry = _aware_utc(datetime.fromisoformat(valid_until))
    except ValueError:
        return None
    if expiry <= now + refresh_margin:
        return None
    serialized: list[dict[str, object]] = []
    for record in cast(list[object], records):
        if not isinstance(record, dict):
            return None
        serialized.append(cast(dict[str, object], record))
    return serialized


def _records_from_entries(
    entries: Mapping[str, object], now: datetime
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {endpoint: [] for endpoint in _CACHE_ENDPOINTS}
    for key, value in entries.items():
        endpoint = key.partition("|")[0]
        if endpoint not in grouped or not isinstance(value, dict):
            continue
        entry = cast(dict[str, object], value)
        records = entry.get("records")
        if not isinstance(records, list):
            continue
        expired = _entry_is_expired(entry, now)
        for record in cast(list[object], records):
            if isinstance(record, dict):
                serialized = dict(cast(dict[str, object], record))
                if expired:
                    serialized["status"] = "stale"
                grouped[endpoint].append(serialized)
    return grouped


def _entry_is_expired(entry: Mapping[str, object], now: datetime) -> bool:
    valid_until = entry.get("valid_until")
    if not isinstance(valid_until, str):
        return False
    try:
        return _aware_utc(datetime.fromisoformat(valid_until)) <= now
    except ValueError:
        return True


def _records_status(records: Sequence[NormalizedRecord]) -> str:
    statuses = {record.status for record in records}
    if statuses <= {"ok"}:
        return "ok"
    if statuses <= {"no_data"}:
        return "no_data"
    return "partial"


def _project_location_field(
    records: Sequence[Mapping[str, object]],
    *,
    location_key: str,
    field: str,
) -> list[dict[str, object]]:
    projected_records: list[dict[str, object]] = []
    for record in records:
        if record.get("location_key") != location_key:
            continue
        values = record.get("values")
        units = record.get("units")
        value_mapping: Mapping[str, object] = (
            cast(Mapping[str, object], values) if isinstance(values, Mapping) else {}
        )
        unit_mapping: Mapping[str, object] = (
            cast(Mapping[str, object], units) if isinstance(units, Mapping) else {}
        )
        has_value = field in value_mapping and value_mapping[field] is not None
        projected = dict(record)
        projected["values"] = {field: value_mapping[field]} if has_value else {}
        projected["units"] = (
            {field: unit_mapping[field]} if has_value and field in unit_mapping else {}
        )
        projected["raw_data"] = {}
        projected["missing_fields"] = [] if has_value else [field]
        projected["completeness"] = 1.0 if has_value else 0.0
        if not has_value and projected.get("status") != "no_data":
            projected["status"] = "partial"
        projected_records.append(projected)
    return projected_records


def _without_value_fields(
    records: Sequence[Mapping[str, object]], fields: set[str]
) -> list[dict[str, object]]:
    projected_records: list[dict[str, object]] = []
    for record in records:
        projected = dict(record)
        projected["values"] = _mapping_without(record.get("values"), fields)
        projected["units"] = _mapping_without(record.get("units"), fields)
        components = record.get("components")
        if isinstance(components, list):
            projected_components: list[object] = []
            for component in cast(list[object], components):
                if not isinstance(component, Mapping):
                    projected_components.append(component)
                    continue
                projected_component = dict(cast(Mapping[str, object], component))
                projected_component["values"] = _mapping_without(
                    projected_component.get("values"), fields
                )
                projected_component["units"] = _mapping_without(
                    projected_component.get("units"), fields
                )
                projected_components.append(projected_component)
            projected["components"] = projected_components
        projected_records.append(projected)
    return projected_records


def _mapping_without(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in cast(Mapping[object, object], value).items()
        if str(key) not in fields
    }


def _record_quality_issues(records: Sequence[NormalizedRecord]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for record in records:
        if record.dataset_type == "weather_alert" and record.status == "no_data":
            continue
        if record.status != "ok":
            issues.append(
                {
                    "dataset_type": record.dataset_type,
                    "location_key": record.location_key,
                    "business_time": record.business_time,
                    "status": record.status,
                }
            )
    return issues


def _serialized_quality_issues(
    records_by_endpoint: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for endpoint, records in records_by_endpoint.items():
        for record in records:
            status = record.get("status")
            if endpoint == "alerts" and status == "no_data":
                continue
            if status != "ok":
                issues.append(
                    {
                        "endpoint": endpoint,
                        "location_key": record.get("location_key"),
                        "zone_ids": record.get("zone_ids"),
                        "business_time": record.get("business_time"),
                        "observed_at": record.get("observed_at"),
                        "status": status,
                    }
                )
    return issues


def _safe_error(endpoint: str, location_key: str, error: Exception) -> dict[str, object]:
    detail: dict[str, object] = {
        "endpoint": endpoint,
        "location_key": location_key,
        "error_type": type(error).__name__,
        "message": str(error),
    }
    if isinstance(error, ApiRequestError):
        detail["http_status"] = error.status_code
        detail["retry_after"] = error.retry_after
    if isinstance(error, QWeatherApiError):
        detail["provider_code"] = error.provider_code
    if isinstance(error, CallLimitExceeded):
        detail["max_calls"] = error.max_calls
    return detail


def _safe_station_error(error: Exception) -> dict[str, object]:
    detail: dict[str, object] = {
        "endpoint": "shanghai_sthj",
        "location_key": None,
        "error_type": type(error).__name__,
        "message": str(error),
    }
    if isinstance(error, (ShanghaiSthjRequestError, ShanghaiSthjResponseError)):
        detail["station_id"] = error.station_id
        detail["source_url"] = error.source_url
    if isinstance(error, ShanghaiSthjResponseError):
        detail["http_status"] = error.status_code
    return detail


def _station_zone_ids(
    zones: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for zone in zones:
        if zone.get("source_strategy") != "shanghai_station":
            continue
        station_id = str(zone.get("station_id"))
        zone_id = zone.get("zone_id")
        if isinstance(zone_id, str):
            grouped.setdefault(station_id, []).append(zone_id)
    return {station_id: tuple(zone_ids) for station_id, zone_ids in grouped.items()}


def _air_quality_point_ids(zones: Sequence[Mapping[str, object]]) -> frozenset[str]:
    point_ids: set[str] = set()
    for zone in zones:
        strategy = zone.get("source_strategy")
        if strategy == "qweather_direct":
            value = zone.get("probe_point_ids")
            if isinstance(value, list):
                point_ids.update(
                    item for item in cast(list[object], value) if isinstance(item, str)
                )
        elif strategy == "district_blend":
            value = zone.get("blend_components")
            if not isinstance(value, list):
                continue
            for component in cast(list[object], value):
                if not isinstance(component, Mapping):
                    continue
                point_id = cast(Mapping[str, object], component).get("point_id")
                if isinstance(point_id, str):
                    point_ids.add(point_id)
    return frozenset(point_ids)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat()


__all__ = ["BackfillUnavailableError", "PipelineError", "WeatherPipeline"]
