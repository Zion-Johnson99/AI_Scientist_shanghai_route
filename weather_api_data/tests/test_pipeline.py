from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from weather_api_data.archive import Archive
from weather_api_data.discovery import LocationDiscovery, load_sampling_points
from weather_api_data.exporter import Exporter
from weather_api_data.history_store import HistoryStore
from weather_api_data.http_client import ApiRequestError, CallLimitExceeded, HttpResult
from weather_api_data.normalizer import Normalizer
from weather_api_data.pipeline import BackfillUnavailableError, WeatherPipeline
from weather_api_data.qweather_discovery import QWeatherDiscoveryService, qweather_source_id
from weather_api_data.qweather_normalizer import QWeatherNormalizer
from weather_api_data.shanghai_sthj_client import (
    ShanghaiSthjBatchResult,
    ShanghaiSthjFetchResult,
)
from weather_api_data.zone_air_quality import (
    load_air_quality_probe_points,
    load_air_quality_zones,
)

ROOT = Path(__file__).parents[1]
CONFIG_DIR = ROOT / "config"
QWEATHER_FIXTURE = ROOT / "tests" / "fixtures" / "qweather_responses.json"
UTC_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
SHANGHAI = timezone(timedelta(hours=8))
REFERENCE_POINT_ID = "XH_ENT_0009"
REFERENCE_SOURCE_ID = "qweather:31.18,121.45"


def _result(payload: object, *, fetched_at: datetime = UTC_NOW) -> HttpResult:
    return HttpResult(payload=payload, status_code=200, expires=None, fetched_at=fetched_at)


def _load_qweather_fixtures() -> dict[str, object]:
    payload: object = json.loads(QWEATHER_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


class FakeQWeatherClient:
    def __init__(
        self,
        *,
        fetched_at: datetime = UTC_NOW,
        failure: ApiRequestError | CallLimitExceeded | None = None,
    ) -> None:
        self.fixtures = _load_qweather_fixtures()
        self.fetched_at = fetched_at
        self.failure = failure
        self.calls: list[tuple[str, str]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _call(self, endpoint: str, source_id: str, fixture_name: str) -> HttpResult:
        self.calls.append((endpoint, source_id))
        if endpoint == "current_conditions" and self.failure is not None:
            raise self.failure
        return _result(self.fixtures[fixture_name], fetched_at=self.fetched_at)

    def current_conditions(self, source_id: str) -> HttpResult:
        return self._call("current_conditions", source_id, "current_conditions")

    def hourly_weather_24(self, source_id: str) -> HttpResult:
        return self._call("hourly_weather_24", source_id, "hourly_weather_24")

    def current_air_quality(self, source_id: str) -> HttpResult:
        return self._call("current_air_quality", source_id, "current_air_quality")

    def hourly_air_quality_24(self, source_id: str) -> HttpResult:
        return self._call(
            "hourly_air_quality_24",
            source_id,
            "hourly_air_quality_24",
        )

    def indices_3day(self, source_id: str) -> HttpResult:
        return self._call("indices_3day", source_id, "indices_3day")

    def alerts(self, source_id: str) -> HttpResult:
        return self._call("alerts", source_id, "alerts_empty")


class FakeLegacyAdvancedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail_climo: ApiRequestError | None = None

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def mark_geoposition(self, point_id: str) -> None:
        self.calls.append(("geoposition", point_id))

    def current_conditions(self, location_key: str) -> HttpResult:
        self.calls.append(("current_conditions", location_key))
        return _result([_legacy_weather("2026-08-26T20:00:00+08:00")])

    def climo_actuals(self, location_key: str, year: int, month: int) -> HttpResult:
        self.calls.append(("climo_actuals", (location_key, year, month)))
        if self.fail_climo is not None:
            raise self.fail_climo
        return _result(
            [
                {
                    "Date": f"{year}-{month:02d}-01",
                    "EpochDate": 1_735_689_600,
                    "Actuals": {"HighTemperature": {"Metric": {"Value": 30.0}}},
                }
            ]
        )


class FakeLegacyDiscovery:
    def __init__(self, client: FakeLegacyAdvancedClient) -> None:
        self.client = client

    def discover_locations(
        self,
        points: Sequence[object],
    ) -> tuple[LocationDiscovery, ...]:
        point_ids: list[str] = []
        for point in points:
            point_id = str(getattr(point, "point_id"))
            self.client.mark_geoposition(point_id)
            point_ids.append(point_id)
        return (
            LocationDiscovery(
                location_key="974168",
                location_name="徐汇区",
                administrative_area={"LocalizedName": "上海市"},
                geo_position={"Longitude": 121.45, "Latitude": 31.18},
                probe_point_ids=tuple(point_ids),
            ),
        )


class FakeStandardClient:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def probe_geoposition(self, latitude: float, longitude: float) -> HttpResult:
        del latitude, longitude
        self.calls += 1
        self.closed = True
        return _result([{"Key": "101024100"}])


class FakeStationClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_stations(self) -> ShanghaiSthjBatchResult:
        self.calls += 1
        payload = {
            "100": [{"lstAqi": "2026-08-26T20:00:00+08:00", "aqi": 23}],
            "101": [
                {
                    "lstAqi": "2026-08-26T20:00:00+08:00",
                    "value": 0.007,
                    "aqi": 10,
                }
            ],
        }
        results = [
            ShanghaiSthjFetchResult(
                station_id=station_id,
                latest_time="2026-08-26T20:00:00+08:00",
                status_code=200,
                payload=payload,
                fetched_at=UTC_NOW,
                source_url="https://link.sthj.sh.gov.cn/hourly",
                status="ok",
            )
            for station_id in ("80", "207")
        ]
        results.append(
            ShanghaiSthjFetchResult(
                station_id="1",
                latest_time="2026-08-26T20:00:00+08:00",
                status_code=404,
                payload=None,
                fetched_at=UTC_NOW,
                source_url="https://link.sthj.sh.gov.cn/hourly",
                status="no_data",
            )
        )
        return ShanghaiSthjBatchResult(results=tuple(results), errors=(), request_count=4)


def _legacy_weather(business_time: str) -> dict[str, object]:
    return {
        "LocalObservationDateTime": business_time,
        "WeatherText": "多云",
        "WeatherIcon": 4,
        "Temperature": {"Metric": {"Value": 30.0}},
        "RelativeHumidity": 65,
        "RealFeelTemperature": {"Metric": {"Value": 33.0}},
        "Wind": {
            "Direction": {"Degrees": 120},
            "Speed": {"Metric": {"Value": 10.0}},
        },
        "WindGust": {"Speed": {"Metric": {"Value": 18.0}}},
        "Pressure": {"Metric": {"Value": 1008.0}},
        "Visibility": {"Metric": {"Value": 16.0}},
        "UVIndex": 3,
        "PrecipitationSummary": {"Precipitation": {"Metric": {"Value": 0.0}}},
        "PrecipitationProbability": 20,
        "LocalSource": {"Id": 7, "Name": "华风爱科"},
    }


@dataclass(slots=True)
class PipelineBundle:
    pipeline: WeatherPipeline
    provider: FakeQWeatherClient
    station: FakeStationClient
    legacy: FakeLegacyAdvancedClient
    standard: FakeStandardClient
    store: HistoryStore
    cache_path: Path
    export_dir: Path

    def close(self) -> None:
        self.store.close()


def _build_pipeline(
    tmp_path: Path,
    *,
    now: datetime = UTC_NOW,
    provider: FakeQWeatherClient | None = None,
) -> PipelineBundle:
    active = provider or FakeQWeatherClient(fetched_at=now)
    legacy = FakeLegacyAdvancedClient()
    standard = FakeStandardClient()
    store = HistoryStore(tmp_path / "history.sqlite")
    zone_path = CONFIG_DIR / "xuhui_air_quality_zones.json"
    points = (
        *load_sampling_points(CONFIG_DIR / "xuhui_sampling_points.json"),
        *load_air_quality_probe_points(zone_path),
    )
    cache_path = tmp_path / "refresh_cache.json"
    export_dir = tmp_path / "exports"
    station = FakeStationClient()
    instance = WeatherPipeline(
        provider_client=active,
        standard_client=standard,
        discovery_service=QWeatherDiscoveryService(),
        normalizer=QWeatherNormalizer(),
        legacy_advanced_client=legacy,
        legacy_discovery_service=FakeLegacyDiscovery(legacy),
        legacy_normalizer=Normalizer(),
        archive=Archive(tmp_path / "archive"),
        history_store=store,
        exporter=Exporter(export_dir),
        cache_path=cache_path,
        sampling_points=points,
        station_client=station,
        air_quality_zones=load_air_quality_zones(zone_path),
        provider_base_url="https://fixture.qweatherapi.com",
        reference_point_id=REFERENCE_POINT_ID,
        max_calls_per_run=80,
        now_fn=lambda: now,
        call_count_fn=lambda: active.call_count + legacy.call_count,
    )
    return PipelineBundle(
        pipeline=instance,
        provider=active,
        station=station,
        legacy=legacy,
        standard=standard,
        store=store,
        cache_path=cache_path,
        export_dir=export_dir,
    )


@pytest.fixture
def bundle(tmp_path: Path) -> Iterator[Sequence[PipelineBundle]]:
    value = _build_pipeline(tmp_path)
    try:
        yield (value,)
    finally:
        value.close()


def _only(bundle_fixture: Sequence[PipelineBundle]) -> PipelineBundle:
    assert len(bundle_fixture) == 1
    return bundle_fixture[0]


def test_discover_is_zero_network_and_persists_reference_source_id(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    report = value.pipeline.discover()

    assert report["status"] == "ok"
    assert report["call_count"] == 0
    assert report["location_count"] == 16
    assert report["reference_point_id"] == REFERENCE_POINT_ID
    assert report["reference_source_id"] == REFERENCE_SOURCE_ID
    assert value.provider.calls == []
    assert value.legacy.calls == []
    regions = cast(Mapping[str, object], report["regions"])
    assert regions["provider"] == "qweather"
    assert regions["reference_source_id"] == REFERENCE_SOURCE_ID


def test_refresh_uses_endpoint_specific_topology_and_reuses_empty_alert_cache(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    first = value.pipeline.refresh()

    assert first["status"] == "ok"
    assert first["call_count"] == 28
    assert first["cache_hits"] == 0
    assert first["reference_source_id"] == REFERENCE_SOURCE_ID
    assert first["quota"] == {"hard_limit": 80, "used": 28, "remaining": 52}
    assert Counter(endpoint for endpoint, _source_id in value.provider.calls) == {
        "current_conditions": 1,
        "hourly_weather_24": 1,
        "indices_3day": 1,
        "alerts": 1,
        "current_air_quality": 12,
        "hourly_air_quality_24": 12,
    }
    weather_sources = {
        source_id
        for endpoint, source_id in value.provider.calls
        if endpoint in {"current_conditions", "hourly_weather_24", "indices_3day", "alerts"}
    }
    assert weather_sources == {REFERENCE_SOURCE_ID}
    assert value.legacy.calls == []

    latest = json.loads((value.export_dir / "environment_latest.json").read_text("utf-8"))
    hourly = json.loads((value.export_dir / "environment_hourly.json").read_text("utf-8"))
    assert len(latest["daily_indices_3day"]) == 3
    assert latest["active_alerts"] == []
    assert len(latest["xuhui_aqi"]) == 1
    assert len(latest["point_air_quality"]) == 11
    summary = hourly["weather_history_24h_summary"]
    assert summary["status"] == "partial"
    assert summary["expected_hours"] == 24
    assert summary["available_hours"] == 1
    assert len(summary["missing_hours"]) == 23

    second = value.pipeline.refresh()

    assert second["status"] == "ok"
    assert second["call_count"] == 0
    assert second["cache_hits"] == 28
    assert len(value.provider.calls) == 28
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    alert_entry = cache["entries"][f"alerts|{REFERENCE_SOURCE_ID}"]
    assert alert_entry["records"] == []
    assert alert_entry["valid_until"] is not None


def test_refresh_updates_current_aqi_when_cache_is_about_to_expire(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    for key, entry in cache["entries"].items():
        if key.startswith("current_air_quality|"):
            entry["valid_until"] = (UTC_NOW + timedelta(seconds=4)).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()

    report = value.pipeline.refresh()

    assert report["call_count"] == 12
    assert report["cache_hits"] == 16
    assert Counter(endpoint for endpoint, _source_id in value.provider.calls) == {
        "current_air_quality": 12,
    }


def test_refresh_updates_hourly_aqi_when_cache_is_about_to_expire(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    for key, entry in cache["entries"].items():
        if key.startswith("hourly_air_quality_24|"):
            entry["valid_until"] = (UTC_NOW + timedelta(seconds=4)).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()

    report = value.pipeline.refresh()

    assert report["call_count"] == 12
    assert report["cache_hits"] == 16
    assert Counter(endpoint for endpoint, _source_id in value.provider.calls) == {
        "hourly_air_quality_24": 12,
    }


def test_refresh_updates_weather_when_cache_is_about_to_expire(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    for endpoint in ("current_conditions", "hourly_weather_24"):
        cache["entries"][f"{endpoint}|{REFERENCE_SOURCE_ID}"]["valid_until"] = (
            UTC_NOW + timedelta(minutes=4)
        ).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()

    report = value.pipeline.refresh()

    assert report["call_count"] == 2
    assert report["cache_hits"] == 26
    assert Counter(endpoint for endpoint, _source_id in value.provider.calls) == {
        "current_conditions": 1,
        "hourly_weather_24": 1,
    }


def test_refresh_updates_indices_when_cache_is_about_to_expire(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    cache["entries"][f"indices_3day|{REFERENCE_SOURCE_ID}"]["valid_until"] = (
        UTC_NOW + timedelta(minutes=4)
    ).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()

    report = value.pipeline.refresh()

    assert report["call_count"] == 1
    assert report["cache_hits"] == 27
    assert value.provider.calls == [("indices_3day", REFERENCE_SOURCE_ID)]


def test_refresh_weather_only_updates_reference_weather_and_preserves_full_export(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    for endpoint in ("current_conditions", "hourly_weather_24", "alerts"):
        cache["entries"][f"{endpoint}|{REFERENCE_SOURCE_ID}"]["valid_until"] = (
            UTC_NOW - timedelta(minutes=1)
        ).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()
    station_calls = value.station.calls

    first = value.pipeline.refresh_weather()

    assert first["status"] == "ok"
    assert first["command"] == "refresh-weather"
    assert first["call_count"] == 3
    assert first["cache_hits"] == 0
    assert first["quota"] == {"hard_limit": 80, "used": 3, "remaining": 77}
    assert value.provider.calls == [
        ("current_conditions", REFERENCE_SOURCE_ID),
        ("hourly_weather_24", REFERENCE_SOURCE_ID),
        ("alerts", REFERENCE_SOURCE_ID),
    ]
    assert value.station.calls == station_calls
    latest = json.loads((value.export_dir / "environment_latest.json").read_text("utf-8"))
    hourly = json.loads((value.export_dir / "environment_hourly.json").read_text("utf-8"))
    assert latest["active_alerts"] == []
    assert len(latest["daily_indices_3day"]) == 3
    assert len(latest["xuhui_aqi"]) == 1
    assert len(latest["point_air_quality"]) == 11
    assert hourly["weather_forecast_24h"]
    assert hourly["xuhui_aqi_forecast_24h"]

    value.provider.calls.clear()
    second = value.pipeline.refresh_weather()

    assert second["status"] == "ok"
    assert second["call_count"] == 0
    assert second["cache_hits"] == 3
    assert value.provider.calls == []
    assert value.station.calls == station_calls


def test_refresh_weather_updates_near_expiry_weather_cache(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    for endpoint in ("current_conditions", "hourly_weather_24"):
        cache["entries"][f"{endpoint}|{REFERENCE_SOURCE_ID}"]["valid_until"] = (
            UTC_NOW + timedelta(minutes=4)
        ).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()

    report = value.pipeline.refresh_weather()

    assert report["call_count"] == 2
    assert report["cache_hits"] == 1
    assert value.provider.calls == [
        ("current_conditions", REFERENCE_SOURCE_ID),
        ("hourly_weather_24", REFERENCE_SOURCE_ID),
    ]


def test_refresh_weather_updates_near_expiry_alert_cache(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.pipeline.refresh()
    cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
    cache["entries"][f"alerts|{REFERENCE_SOURCE_ID}"]["valid_until"] = (
        UTC_NOW + timedelta(seconds=30)
    ).isoformat()
    value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
    value.provider.calls.clear()

    report = value.pipeline.refresh_weather()

    assert report["call_count"] == 1
    assert report["cache_hits"] == 2
    assert value.provider.calls == [("alerts", REFERENCE_SOURCE_ID)]


def test_refresh_weather_failure_is_partial_and_keeps_stale_snapshot(tmp_path: Path) -> None:
    provider = FakeQWeatherClient()
    value = _build_pipeline(tmp_path, provider=provider)
    try:
        value.pipeline.refresh()
        cache = json.loads(value.cache_path.read_text(encoding="utf-8"))
        for endpoint in ("current_conditions", "hourly_weather_24", "alerts"):
            cache["entries"][f"{endpoint}|{REFERENCE_SOURCE_ID}"]["valid_until"] = (
                UTC_NOW - timedelta(minutes=1)
            ).isoformat()
        value.cache_path.write_text(json.dumps(cache), encoding="utf-8")
        provider.calls.clear()
        provider.failure = ApiRequestError("current_conditions", 503)
        station_calls = value.station.calls

        report = value.pipeline.refresh_weather()

        assert report["status"] == "partial"
        assert report["call_count"] == 3
        assert report["cache_hits"] == 0
        assert cast(Sequence[Mapping[str, object]], report["errors"])[0]["endpoint"] == (
            "current_conditions"
        )
        assert value.station.calls == station_calls
        latest = json.loads((value.export_dir / "environment_latest.json").read_text("utf-8"))
        current = cast(Sequence[Mapping[str, object]], latest["current_weather"])
        assert current[0]["status"] == "stale"
        assert len(latest["daily_indices_3day"]) == 3
        assert len(latest["point_air_quality"]) == 11
    finally:
        value.close()


def test_export_reads_complete_24_hour_weather_window_from_sqlite(tmp_path: Path) -> None:
    end_at = datetime(2026, 8, 27, 9, 30, tzinfo=SHANGHAI)
    value = _build_pipeline(tmp_path, now=end_at)
    try:
        value.pipeline.discover()
        base = QWeatherNormalizer().normalize(
            "current_conditions",
            _result(_load_qweather_fixtures()["current_conditions"]),
            REFERENCE_SOURCE_ID,
            (REFERENCE_POINT_ID,),
        )[0]
        start = datetime(2026, 8, 26, 10, tzinfo=SHANGHAI)
        value.store.write_records(
            [
                replace(
                    base,
                    business_time=(start + timedelta(hours=offset)).isoformat(),
                    fetched_at=(start + timedelta(hours=offset, minutes=1)).isoformat(),
                    values={**dict(base.values), "temperature_c": float(offset)},
                )
                for offset in range(24)
            ]
        )
        value.pipeline.export()

        hourly = json.loads((value.export_dir / "environment_hourly.json").read_text("utf-8"))
        assert len(hourly["weather_history_24h"]) == 24
        assert hourly["weather_history_24h_summary"] == {
            "status": "ok",
            "expected_hours": 24,
            "available_hours": 24,
            "missing_hours": [],
        }
    finally:
        value.close()


def test_qweather_and_legacy_probes_remain_separate(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    qweather = value.pipeline.probe_qweather(REFERENCE_POINT_ID)
    advanced = value.pipeline.probe_advanced(REFERENCE_POINT_ID)
    with pytest.raises(ValueError, match="confirm"):
        value.pipeline.probe_standard(REFERENCE_POINT_ID, confirmed=False)
    standard = value.pipeline.probe_standard(REFERENCE_POINT_ID, confirmed=True)

    assert qweather["status"] == "ok"
    assert qweather["call_count"] == 2
    assert [endpoint for endpoint, _source_id in value.provider.calls] == [
        "current_conditions",
        "current_air_quality",
    ]
    assert advanced["status"] == "ok"
    assert advanced["call_count"] == 2
    assert [endpoint for endpoint, _context in value.legacy.calls] == [
        "geoposition",
        "current_conditions",
    ]
    assert standard["call_count"] == 1
    assert standard["standard_client_closed"] is True


def test_legacy_backfill_is_retained_and_deduplicates_one_location(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    report = value.pipeline.backfill(year=2025, month=8)

    assert report["status"] == "partial"
    assert report["call_count"] == 17
    assert cast(Mapping[str, int], report["records_written"])["climate_actuals"] == 1
    assert len(cast(Sequence[object], report["missing_dates"])) == 30
    assert Counter(endpoint for endpoint, _context in value.legacy.calls) == {
        "geoposition": 16,
        "climo_actuals": 1,
    }
    assert value.provider.calls == []


def test_legacy_backfill_denial_is_auditable_and_year_remains_locked(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    value.legacy.fail_climo = ApiRequestError("climo_actuals", 403)

    with pytest.raises(BackfillUnavailableError) as captured:
        value.pipeline.backfill(year=2025, month=8)

    assert captured.value.report["status"] == "unavailable_from_provider"
    assert captured.value.report["http_status"] == 403
    assert captured.value.report["call_count"] == 17
    with pytest.raises(ValueError, match="2025"):
        value.pipeline.backfill(year=2024, month=8)


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        (ApiRequestError("current_conditions", 429, retry_after="60"), "rate_limited"),
        (CallLimitExceeded("current_conditions", 80), "call_limit_exceeded"),
    ],
)
def test_refresh_stops_after_provider_wide_limit(
    tmp_path: Path,
    failure: ApiRequestError | CallLimitExceeded,
    expected_reason: str,
) -> None:
    provider = FakeQWeatherClient(failure=failure)
    value = _build_pipeline(tmp_path, provider=provider)
    try:
        report = value.pipeline.refresh()

        assert report["status"] == "error"
        assert report["halt_reason"] == expected_reason
        assert not any(endpoint == "alerts" for endpoint, _source_id in provider.calls)
    finally:
        value.close()


def test_corrupt_cache_finishes_run_as_failed(tmp_path: Path) -> None:
    value = _build_pipeline(tmp_path)
    try:
        value.cache_path.write_text("{broken", encoding="utf-8")

        with pytest.raises(Exception, match="缓存读取失败"):
            value.pipeline.refresh()

        row = (
            sqlite3.connect(value.store.database_path)
            .execute("SELECT status, finished_at FROM runs")
            .fetchone()
        )
        assert row is not None
        assert row[0] == "failed"
        assert row[1] is not None
    finally:
        value.close()


def test_prune_uses_strict_365_day_boundary(
    bundle: Sequence[PipelineBundle],
) -> None:
    value = _only(bundle)
    cutoff = UTC_NOW - timedelta(days=365)
    report = value.pipeline.prune_history(cutoff=cutoff, apply=False)

    assert report["apply"] is False
    assert report["database_records"] == 0
    assert report["archive_files"] == 0


def test_reference_source_matches_configured_point() -> None:
    points = load_sampling_points(CONFIG_DIR / "xuhui_sampling_points.json")
    reference = next(point for point in points if point.point_id == REFERENCE_POINT_ID)

    assert qweather_source_id(reference.latitude, reference.longitude) == REFERENCE_SOURCE_ID
