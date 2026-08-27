from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import requests

from weather_api_data.config import Settings
from weather_api_data.exposure_pipeline import (
    build_static_exposure_documents,
    refresh_exposure_from_local_sources,
    weather_factors_from_documents,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pollen_forecast.json"
PROJECT_ROOT = Path(__file__).parents[1]


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.status_code = 200
        self.headers = {"Expires": "Wed, 26 Aug 2026 12:00:00 GMT"}
        self._payload = payload

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def get(self, _url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse(self.payload)


def _write_pm25(path: Path, *, count: int = 54) -> None:
    grids = [
        {
            "grid_id": f"XH_PM25_G{index:03d}",
            "longitude": 121.465 + index * 0.00001,
            "latitude": 31.165 + index * 0.00001,
            "pm2_5_ug_m3": 10.0 + index / 10,
            "is_estimated": True,
        }
        for index in range(1, count + 1)
    ]
    path.write_text(
        json.dumps(
            {
                "dataset_type": "pm25_grid_estimate",
                "target_time": "2026-08-26T09:00:00+08:00",
                "generated_at": "2026-08-26T09:02:00+08:00",
                "spatial_basis": "grid_1km",
                "quality": {"status": "estimated", "confidence": "medium"},
                "grids": grids,
            }
        ),
        encoding="utf-8",
    )


def _write_routes(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "route_id": "XH_TEST_0001",
                            "road_names": ["滨江绿道"],
                            "tags": ["滨江", "绿道"],
                            "network_source": "fixture-route-network",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.4695, 31.1631], [121.4705, 31.1631]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _weather_documents() -> tuple[dict[str, object], dict[str, object]]:
    latest: dict[str, object] = {
        "reference_source_id": "qweather:31.18,121.45",
        "current_weather": [
            {
                "location_key": "qweather:31.18,121.45",
                "business_time": "2026-08-26T08:00:00+08:00",
                "values": {
                    "wind_speed_kmh": 10.0,
                    "precipitation_mm": 0.5,
                    "relative_humidity_pct": 60.0,
                },
            }
        ],
    }
    hourly: dict[str, object] = {
        "reference_source_id": "qweather:31.18,121.45",
        "weather_forecast_24h": [
            {
                "location_key": "qweather:31.18,121.45",
                "business_time": "2026-08-27T08:00:00+08:00",
                "values": {
                    "wind_speed_kmh": 8.0,
                    "precipitation_mm": 1.0,
                    "relative_humidity_pct": 70.0,
                },
            },
            {
                "location_key": "qweather:31.18,121.45",
                "business_time": "2026-08-27T09:00:00+08:00",
                "values": {
                    "wind_speed_kmh": 12.0,
                    "precipitation_mm": 2.0,
                    "relative_humidity_pct": 50.0,
                },
            },
        ],
    }
    return latest, hourly


def test_weather_factors_use_current_day_and_aggregate_hourly_forecast() -> None:
    latest, hourly = _weather_documents()

    factors = weather_factors_from_documents(latest, hourly)

    assert factors["2026-08-26"].wind_speed_kph == 10.0
    assert factors["2026-08-27"].wind_speed_kph == 10.0
    assert factors["2026-08-27"].precipitation_mm == 3.0
    assert factors["2026-08-27"].humidity_percent == 60.0


def test_static_exposure_writes_noise_and_partial_route_contract(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.geojson"
    pm25_path = tmp_path / "pm25.json"
    _write_routes(routes_path)
    _write_pm25(pm25_path)

    result = build_static_exposure_documents(
        output_dir=tmp_path / "exports",
        routes_path=routes_path,
        pm25_grid_path=pm25_path,
        noise_config_path=PROJECT_ROOT / "config" / "noise_model.json",
        generated_at=datetime(2026, 8, 26, 9, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "partial"
    assert result["route_count"] == 1
    files = cast(dict[str, str], result["files"])
    assert set(files) == {
        "grid_environment_latest.json",
        "noise_segments.json",
        "route_environment.json",
    }
    route_document = json.loads(Path(files["route_environment.json"]).read_text("utf-8"))
    route = route_document["routes"][0]
    assert route["pm2_5"]["status"] == "ok"
    assert route["pollen_daily"] == []
    assert route["noise"]["status"] == "partial"


def test_static_exposure_applies_historical_noise_calibration(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.geojson"
    pm25_path = tmp_path / "pm25.json"
    calibration_path = tmp_path / "noise_calibration.json"
    _write_routes(routes_path)
    _write_pm25(pm25_path)
    calibration_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "observation_count": 2525,
                "station_count": 4,
                "calibration": {"district_anchor": 52.965},
            }
        ),
        encoding="utf-8",
    )

    result = build_static_exposure_documents(
        output_dir=tmp_path / "exports",
        routes_path=routes_path,
        pm25_grid_path=pm25_path,
        noise_config_path=PROJECT_ROOT / "config" / "noise_model.json",
        noise_calibration_path=calibration_path,
    )

    assert result["noise_calibration_status"] == "applied"
    noise = json.loads((tmp_path / "exports" / "noise_segments.json").read_text("utf-8"))
    assert noise["calibration_observation_count"] == 2525
    assert noise["segments"][0]["calibration_applied"] is True
    assert "db" not in " ".join(noise["segments"][0]).lower()


def test_fixture_full_refresh_calls_54_grids_and_exports_four_documents(
    tmp_path: Path,
) -> None:
    routes_path = tmp_path / "routes.geojson"
    pm25_path = tmp_path / "pm25.json"
    latest_path = tmp_path / "environment_latest.json"
    hourly_path = tmp_path / "environment_hourly.json"
    _write_routes(routes_path)
    _write_pm25(pm25_path)
    latest, hourly = _weather_documents()
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    hourly_path.write_text(json.dumps(hourly), encoding="utf-8")
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    session = FakeSession(payload)
    settings = Settings(
        pollen_enabled=True,
        pollen_api_key="fixture-key",
        pollen_min_interval_seconds=0.0,
    )

    result = refresh_exposure_from_local_sources(
        settings=settings,
        session=cast(requests.Session, session),
        output_dir=tmp_path / "exports",
        routes_path=routes_path,
        pm25_grid_path=pm25_path,
        pollen_model_path=PROJECT_ROOT / "config" / "pollen_model.json",
        noise_config_path=PROJECT_ROOT / "config" / "noise_model.json",
        environment_latest_path=latest_path,
        environment_hourly_path=hourly_path,
        generated_at=datetime(2026, 8, 26, 9, 5, tzinfo=timezone.utc),
    )

    assert result["pollen_call_count"] == 54
    assert len(session.calls) == 54
    assert result["route_count"] == 1
    files = cast(dict[str, str], result["files"])
    assert set(files) == {
        "pollen_grid_scores.json",
        "grid_environment_latest.json",
        "noise_segments.json",
        "route_environment.json",
    }
    pollen = json.loads(Path(files["pollen_grid_scores.json"]).read_text("utf-8"))
    assert pollen["grid_count"] == 54
    assert pollen["forecast_date_count"] == 2
    grids = json.loads(Path(files["grid_environment_latest.json"]).read_text("utf-8"))
    assert grids["grid_count"] == 54
    assert grids["grids"][0]["pollen"]["forecast_date"] == "2026-08-26"
    assert grids["grids"][0]["noise"]["estimated"] is True
