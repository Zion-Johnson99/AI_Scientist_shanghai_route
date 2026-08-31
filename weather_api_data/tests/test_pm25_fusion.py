# pyright: reportUnknownMemberType=false

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import xarray as xr

from weather_api_data import pm25_fusion

REFERENCE_SOURCE_ID = "qweather:31.190,121.438"


def _write_chap(path: Path) -> None:
    dataset = xr.Dataset(
        data_vars={
            "pm2_5_ug_m3": (
                ("time", "lat", "lon"),
                np.array(
                    [
                        [[10.0, 12.0], [8.0, np.nan]],
                        [[20.0, 22.0], [18.0, np.nan]],
                    ],
                    dtype=np.float32,
                ),
            ),
            "xuhui_mask": (
                ("lat", "lon"),
                np.array([[1, 1], [1, 0]], dtype=np.uint8),
            ),
        },
        coords={
            "time": np.array(["2025-08-01", "2025-08-02"], dtype="datetime64[ns]"),
            "lat": np.array([31.20, 31.19], dtype=np.float32),
            "lon": np.array([121.42, 121.43], dtype=np.float32),
        },
        attrs={
            "provider": "CHAP",
            "dataset": "ChinaHighPM2.5",
            "source_version": "V4",
            "spatial_basis": "grid_1km",
            "temporal_resolution": "daily",
        },
    )
    dataset.to_netcdf(path, engine="h5netcdf")


def _write_history(
    path: Path,
    *,
    business_time: str = "2026-08-25T17:00:00+08:00",
    source_id: str = REFERENCE_SOURCE_ID,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE air_quality_observations (
            record_id INTEGER PRIMARY KEY,
            location_key TEXT NOT NULL,
            business_time TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            source_key TEXT NOT NULL,
            dataset_role TEXT NOT NULL,
            granularity TEXT NOT NULL,
            valid_until TEXT,
            status TEXT NOT NULL,
            completeness REAL NOT NULL,
            record_json TEXT NOT NULL,
            UNIQUE (location_key, business_time, source_key)
        )
        """
    )
    record = {
        "location_key": source_id,
        "business_time": business_time,
        "fetched_at": "2026-08-25T17:02:00+08:00",
        "status": "ok",
        "values": {"pm2_5_ug_m3": 10.0, "aqi": 24},
        "source": {"provider": "qweather", "source_id": source_id},
    }
    connection.execute(
        """
        INSERT INTO air_quality_observations (
            location_key, business_time, fetched_at, source_key,
            dataset_role, granularity, valid_until, status, completeness, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            business_time,
            record["fetched_at"],
            "qweather-source",
            "operational",
            "current",
            None,
            "ok",
            1.0,
            json.dumps(record),
        ),
    )
    connection.commit()
    connection.close()


def _write_latest(
    path: Path,
    *,
    observed_at: str = "2026-08-25T17:00:00+08:00",
    station_80_observed_at: str | None = None,
    station_207_observed_at: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "point_air_quality": [
                    {
                        "provider": "shanghai_sthj",
                        "spatial_basis": "station",
                        "spatial_id": "80",
                        "observed_at": station_80_observed_at or observed_at,
                        "status": "ok",
                        "values": {"pm2_5_ug_m3": 12.0},
                    },
                    {
                        "provider": "shanghai_sthj",
                        "spatial_basis": "station",
                        "spatial_id": "207",
                        "observed_at": station_207_observed_at or observed_at,
                        "status": "ok",
                        "values": {"pm2_5_ug_m3": 7.0},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_regions(path: Path, *, source_id: str = REFERENCE_SOURCE_ID) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"reference_source_id": source_id}),
        encoding="utf-8",
    )


def _write_zones(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "zones": [
                    {
                        "zone_id": "xujiahui_sports_station",
                        "anchor": {"longitude": 121.42, "latitude": 31.20, "crs": "WGS84"},
                        "source_strategy": "shanghai_station",
                        "station_id": 80,
                    },
                    {
                        "zone_id": "tianlin_guilin_kangjian_station",
                        "anchor": {"longitude": 121.42, "latitude": 31.19, "crs": "WGS84"},
                        "source_strategy": "shanghai_station",
                        "station_id": 207,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_hourly_forecast(
    path: Path,
    *,
    count: int = 24,
    duplicate_time: bool = False,
    missing_pm2_5: bool = False,
    mismatched_source: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat("2026-08-25T18:00:00+08:00")
    records: list[dict[str, object]] = []
    for offset in range(count):
        forecast_at = (
            start
            if duplicate_time and offset == 1
            else start.replace(
                hour=(start.hour + offset) % 24,
                day=start.day + (start.hour + offset) // 24,
            )
        )
        values = {} if missing_pm2_5 and offset == 0 else {"pm2_5_ug_m3": 10.0 + offset}
        records.append(
            {
                "location_key": (
                    "qweather:other"
                    if mismatched_source and offset == count - 1
                    else REFERENCE_SOURCE_ID
                ),
                "business_time": forecast_at.isoformat(),
                "fetched_at": "2026-08-25T17:05:00+08:00",
                "status": "ok",
                "values": values,
                "units": {"pm2_5_ug_m3": "ug/m3"},
                "source": {"provider": "qweather", "source_id": REFERENCE_SOURCE_ID},
            }
        )
    path.write_text(
        json.dumps({"xuhui_pm2_5_forecast_24h": records}),
        encoding="utf-8",
    )


def _sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    chap_path = tmp_path / "chap.nc"
    history_path = tmp_path / "weather.sqlite"
    latest_path = tmp_path / "environment_latest.json"
    zones_path = tmp_path / "xuhui_air_quality_zones.json"
    _write_chap(chap_path)
    _write_history(history_path)
    _write_latest(latest_path)
    _write_zones(zones_path)
    return chap_path, history_path, latest_path, zones_path


def test_forecast_fusion_builds_24_hour_grids_and_zone_anchor_estimates(
    tmp_path: Path,
) -> None:
    chap_path = tmp_path / "chap.nc"
    hourly_path = tmp_path / "environment_hourly.json"
    zones_path = tmp_path / "xuhui_air_quality_zones.json"
    _write_chap(chap_path)
    _write_hourly_forecast(hourly_path)
    _write_zones(zones_path)

    result = pm25_fusion.build_pm25_grid_forecast(
        chap_path=chap_path,
        hourly_path=hourly_path,
        zones_path=zones_path,
        reference_source_id=REFERENCE_SOURCE_ID,
        generated_at=datetime.fromisoformat("2026-08-25T17:30:00+08:00"),
    )

    forecasts = cast(list[dict[str, object]], result["forecasts"])
    first = forecasts[0]
    grids = cast(list[dict[str, object]], first["grids"])
    zones = cast(list[dict[str, object]], first["zones"])
    assert result["forecast_count"] == 24
    assert result["grid_count"] == 3
    assert result["zone_count"] == 2
    assert result["provider"] == "qweather"
    assert result["source_id"] == REFERENCE_SOURCE_ID
    assert first["forecast_at"] == "2026-08-25T18:00:00+08:00"
    assert first["api_anchor_ug_m3"] == 10.0
    assert np.mean([cast(float, grid["pm2_5_ug_m3"]) for grid in grids]) == pytest.approx(10.0)
    assert [zone["grid_id"] for zone in zones] == ["XH_PM25_G001", "XH_PM25_G003"]
    assert all(cast(bool, grid["is_estimated"]) for grid in grids)
    assert all(cast(bool, zone["is_estimated"]) for zone in zones)


def test_forecast_fusion_writes_public_json_atomically(tmp_path: Path) -> None:
    root = tmp_path
    chap_path = root / (
        "pm2.5_data/xuhui_pm2.5_2025_1km/xuhui_data/CHAP_PM2.5_D1K_2025_xuhui_V4.nc"
    )
    hourly_path = root / "runtime/exports/environment_hourly.json"
    regions_path = root / "runtime/exports/environment_regions.json"
    zones_path = root / "config/xuhui_air_quality_zones.json"
    chap_path.parent.mkdir(parents=True)
    _write_chap(chap_path)
    _write_hourly_forecast(hourly_path)
    _write_regions(regions_path)
    _write_zones(zones_path)

    report = pm25_fusion.fuse_pm25_forecast_from_local_sources(root=root)

    output_path = root / "runtime/exports/pm25_grid_forecast_24h.json"
    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert report["forecast_count"] == 24
    assert report["grid_count"] == 3
    assert report["zone_count"] == 2
    assert Path(str(report["output_path"])) == output_path.resolve()
    assert document["forecast_count"] == 24


@pytest.mark.parametrize(
    ("forecast_options", "message"),
    [
        ({"count": 23}, "24"),
        ({"duplicate_time": True}, "重复"),
        ({"missing_pm2_5": True}, "PM2.5"),
        ({"mismatched_source": True}, "reference_source_id"),
    ],
)
def test_forecast_fusion_rejects_incomplete_hourly_inputs(
    tmp_path: Path,
    forecast_options: dict[str, object],
    message: str,
) -> None:
    chap_path = tmp_path / "chap.nc"
    hourly_path = tmp_path / "environment_hourly.json"
    zones_path = tmp_path / "xuhui_air_quality_zones.json"
    _write_chap(chap_path)
    _write_hourly_forecast(hourly_path, **forecast_options)  # type: ignore[arg-type]
    _write_zones(zones_path)

    with pytest.raises(pm25_fusion.Pm25FusionError, match=message):
        pm25_fusion.build_pm25_grid_forecast(
            chap_path=chap_path,
            hourly_path=hourly_path,
            zones_path=zones_path,
            reference_source_id=REFERENCE_SOURCE_ID,
        )


def test_fusion_builds_traceable_grid_estimates_with_anchor_mean(tmp_path: Path) -> None:
    from weather_api_data.pm25_fusion import build_pm25_grid_estimate

    chap_path, history_path, latest_path, zones_path = _sources(tmp_path)
    target_time = datetime.fromisoformat("2026-08-25T17:00:00+08:00")

    result = build_pm25_grid_estimate(
        chap_path=chap_path,
        history_path=history_path,
        latest_path=latest_path,
        zones_path=zones_path,
        reference_source_id=REFERENCE_SOURCE_ID,
        target_time=target_time,
        generated_at=datetime.fromisoformat("2026-08-25T17:30:00+08:00"),
    )

    anchor = cast(dict[str, object], result["anchor"])
    historical_prior = cast(dict[str, object], result["historical_prior"])
    stations = cast(list[dict[str, object]], result["stations"])
    grids = cast(list[dict[str, object]], result["grids"])
    assert result["target_time"] == "2026-08-25T17:00:00+08:00"
    assert result["provider"] == "qweather"
    assert result["source_id"] == REFERENCE_SOURCE_ID
    assert anchor["provider"] == "qweather"
    assert anchor["source_id"] == REFERENCE_SOURCE_ID
    assert anchor["pm2_5_ug_m3"] == 10.0
    assert historical_prior["month"] == 8
    assert historical_prior["days"] == 2
    assert len(stations) == 2
    assert len(grids) == 3
    assert np.mean([cast(float, grid["pm2_5_ug_m3"]) for grid in grids]) == pytest.approx(10.0)
    assert {grid["grid_id"] for grid in grids} == {
        "XH_PM25_G001",
        "XH_PM25_G002",
        "XH_PM25_G003",
    }
    assert all(grid["is_estimated"] is True for grid in grids)


def test_fusion_rejects_missing_exact_qweather_anchor(tmp_path: Path) -> None:
    from weather_api_data.pm25_fusion import Pm25FusionError, build_pm25_grid_estimate

    chap_path, history_path, latest_path, zones_path = _sources(tmp_path)

    with pytest.raises(Pm25FusionError, match="18:00:00"):
        build_pm25_grid_estimate(
            chap_path=chap_path,
            history_path=history_path,
            latest_path=latest_path,
            zones_path=zones_path,
            reference_source_id=REFERENCE_SOURCE_ID,
            target_time=datetime.fromisoformat("2026-08-25T18:00:00+08:00"),
        )


def test_fusion_reduces_station_weight_after_three_hours(tmp_path: Path) -> None:
    from weather_api_data.pm25_fusion import build_pm25_grid_estimate

    chap_path, history_path, latest_path, zones_path = _sources(tmp_path)
    _write_latest(
        latest_path,
        station_80_observed_at="2026-08-25T13:00:00+08:00",
        station_207_observed_at="2026-08-25T17:00:00+08:00",
    )

    result = build_pm25_grid_estimate(
        chap_path=chap_path,
        history_path=history_path,
        latest_path=latest_path,
        zones_path=zones_path,
        reference_source_id=REFERENCE_SOURCE_ID,
        target_time=datetime.fromisoformat("2026-08-25T17:00:00+08:00"),
    )

    stations = {
        str(station["station_id"]): station
        for station in cast(list[dict[str, object]], result["stations"])
    }
    assert result["status"] == "partial"
    assert stations["80"]["age_minutes"] == 240.0
    assert cast(float, stations["80"]["temporal_weight_factor"]) < 1.0
    assert stations["80"]["included"] is True
    assert stations["207"]["temporal_weight_factor"] == 1.0


def test_fusion_excludes_station_at_twenty_four_hours_and_keeps_grid_current(
    tmp_path: Path,
) -> None:
    from weather_api_data.pm25_fusion import build_pm25_grid_estimate

    chap_path, history_path, latest_path, zones_path = _sources(tmp_path)
    _write_latest(
        latest_path,
        station_80_observed_at="2026-08-24T17:00:00+08:00",
        station_207_observed_at="2026-08-25T17:00:00+08:00",
    )

    result = build_pm25_grid_estimate(
        chap_path=chap_path,
        history_path=history_path,
        latest_path=latest_path,
        zones_path=zones_path,
        reference_source_id=REFERENCE_SOURCE_ID,
        target_time=datetime.fromisoformat("2026-08-25T17:00:00+08:00"),
    )

    stations = {
        str(station["station_id"]): station
        for station in cast(list[dict[str, object]], result["stations"])
    }
    grids = cast(list[dict[str, object]], result["grids"])
    assert result["status"] == "partial"
    assert stations["80"]["included"] is False
    assert stations["80"]["exclusion_reason"] == "age_at_least_24_hours"
    assert stations["207"]["included"] is True
    assert all(grid["station_correction_ug_m3"] == 0.0 for grid in grids)
    assert np.mean([cast(float, grid["pm2_5_ug_m3"]) for grid in grids]) == pytest.approx(10.0)


def test_fusion_writes_public_json_atomically(tmp_path: Path) -> None:
    from weather_api_data.pm25_fusion import fuse_pm25_from_local_sources

    root = tmp_path
    chap_path = root / (
        "pm2.5_data/xuhui_pm2.5_2025_1km/xuhui_data/CHAP_PM2.5_D1K_2025_xuhui_V4.nc"
    )
    chap_path.parent.mkdir(parents=True)
    _write_chap(chap_path)
    _write_history(root / "runtime/history/weather.sqlite")
    _write_latest(root / "runtime/exports/environment_latest.json")
    _write_regions(root / "runtime/exports/environment_regions.json")
    _write_zones(root / "config/xuhui_air_quality_zones.json")

    report = fuse_pm25_from_local_sources(
        root=root,
        target_time=datetime.fromisoformat("2026-08-25T17:00:00+08:00"),
    )

    output_path = root / "runtime/exports/pm25_grid_latest.json"
    assert report["status"] == "ok"
    assert report["source_id"] == REFERENCE_SOURCE_ID
    assert report["grid_count"] == 3
    assert Path(str(report["output_path"])) == output_path.resolve()
    assert json.loads(output_path.read_text(encoding="utf-8"))["grid_count"] == 3


def test_latest_fusion_selects_newest_reference_source_observation(tmp_path: Path) -> None:
    from weather_api_data.pm25_fusion import fuse_latest_pm25_from_local_sources

    root = tmp_path
    chap_path = root / (
        "pm2.5_data/xuhui_pm2.5_2025_1km/xuhui_data/CHAP_PM2.5_D1K_2025_xuhui_V4.nc"
    )
    chap_path.parent.mkdir(parents=True)
    _write_chap(chap_path)
    history_path = root / "runtime/history/weather.sqlite"
    _write_history(history_path)
    business_time = "2026-08-25T18:00:00+08:00"
    with sqlite3.connect(history_path) as connection:
        record = {
            "location_key": REFERENCE_SOURCE_ID,
            "business_time": business_time,
            "fetched_at": "2026-08-25T18:02:00+08:00",
            "status": "ok",
            "values": {"pm2_5_ug_m3": 11.0, "aqi": 27},
            "source": {"provider": "qweather", "source_id": REFERENCE_SOURCE_ID},
        }
        connection.execute(
            """
            INSERT INTO air_quality_observations (
                location_key, business_time, fetched_at, source_key,
                dataset_role, granularity, valid_until, status, completeness, record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                REFERENCE_SOURCE_ID,
                record["business_time"],
                record["fetched_at"],
                "qweather-source",
                "operational",
                "current",
                None,
                "ok",
                1.0,
                json.dumps(record),
            ),
        )
    _write_latest(root / "runtime/exports/environment_latest.json", observed_at=business_time)
    _write_regions(root / "runtime/exports/environment_regions.json")
    _write_zones(root / "config/xuhui_air_quality_zones.json")

    report = fuse_latest_pm25_from_local_sources(root=root)

    assert report["status"] == "ok"
    assert report["source_id"] == REFERENCE_SOURCE_ID
    assert report["target_time"] == "2026-08-25T18:00:00+08:00"
    assert report["grid_mean_pm2_5_ug_m3"] == pytest.approx(11.0)
