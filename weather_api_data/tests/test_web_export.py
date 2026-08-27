from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather_api_data.web_export import WebExportError, publish_web_dashboard


def _record(dataset_type: str, *, values: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "dataset_type": dataset_type,
        "business_time": "2026-08-27T14:00:00+08:00",
        "fetched_at": "2026-08-27T14:01:00+08:00",
        "valid_until": "2026-08-27T15:01:00+08:00",
        "status": "ok",
        "location_key": "qweather:31.18,121.45",
        "values": values or {},
        "source": {
            "provider": "qweather",
            "source_id": "qweather:31.18,121.45",
            "api_key": "do-not-export",
        },
        "raw_data": {"secret": "do-not-export"},
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _source_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "weather_api_data"
    exports = root / "runtime" / "exports"
    web_output = tmp_path / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json"
    route_geojson = tmp_path / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"

    life_indices: list[dict[str, object]] = []
    for day in range(27, 30):
        for index_id in range(1, 17):
            life_indices.append(
                _record(
                    "life_index",
                    values={
                        "index_id": str(index_id),
                        "local_date_time": f"2026-08-{day:02d}",
                        "name": f"指数{index_id}",
                    },
                )
            )
    _write_json(
        exports / "environment_latest.json",
        {
            "generated_at": "2026-08-27T14:01:00+08:00",
            "reference_source_id": "qweather:31.18,121.45",
            "current_weather": [_record("weather_observation", values={"temperature_c": 30})],
            "active_alerts": [],
            "xuhui_aqi": [_record("air_quality_observation", values={"aqi": 25})],
            "daily_indices_3day": life_indices,
        },
    )
    _write_json(
        exports / "environment_hourly.json",
        {
            "reference_source_id": "qweather:31.18,121.45",
            "weather_forecast_24h": [
                _record("weather_forecast", values={"temperature_c": hour}) for hour in range(24)
            ],
            "xuhui_aqi_forecast_24h": [
                _record("air_quality_forecast", values={"aqi": hour}) for hour in range(24)
            ],
            "xuhui_pm2_5_forecast_24h": [
                {
                    **_record("air_quality_forecast"),
                    "status": "partial",
                    "missing_fields": ["pm2_5_ug_m3"],
                }
                for _ in range(24)
            ],
        },
    )
    grids: list[dict[str, object]] = []
    for number in range(1, 55):
        grids.append(
            {
                "grid_id": f"GRID_{number:03d}",
                "longitude": 121.44 + number / 10000,
                "latitude": 31.16 + number / 10000,
                "pm2_5_ug_m3": float(number),
                "is_estimated": True,
                "status": "partial",
                "pollen": {
                    "forecast_date": "2026-08-27",
                    "pollen_risk_score": 20.0,
                    "status": "partial",
                    "estimated": True,
                },
                "noise": {
                    "noise_risk_score": 40.0,
                    "confidence": "medium",
                    "scenario_risk_scores": {"daytime": 40.0, "night": 30.0},
                    "status": "partial",
                    "estimated": True,
                },
            }
        )
    _write_json(
        exports / "grid_environment_latest.json",
        {"generated_at": "2026-08-27T14:03:00+08:00", "grids": grids},
    )
    _write_json(
        exports / "pm25_grid_latest.json",
        {
            "generated_at": "2026-08-27T14:02:00+08:00",
            "target_time": "2026-08-27T14:00:00+08:00",
            "spatial_basis": "grid_1km",
            "provider": "multi_source",
            "grids": grids,
        },
    )
    pollen_scores: list[dict[str, object]] = []
    for day in range(27, 32):
        # Deliberately omit most grids: partial pollen is a valid published state.
        pollen_scores.append(
            {
                "grid_id": "GRID_001",
                "forecast_date": f"2026-08-{day:02d}",
                "pollen_risk_score": 20.0,
                "status": "partial",
                "confidence": "low",
                "estimated": True,
                "source": "fixture",
            }
        )
    _write_json(
        exports / "pollen_grid_scores.json",
        {
            "generated_at": "2026-08-27T14:03:00+08:00",
            "source": "fixture",
            "spatial_resolution_m": 1000,
            "grid_scores": pollen_scores,
        },
    )

    routes: list[dict[str, object]] = []
    noise_segments: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    for number in range(1, 91):
        route_id = f"ROUTE_{number:03d}"
        routes.append(
            {
                "route_id": route_id,
                "status": "partial",
                "segment_count": 2,
                "total_length_m": 1000.0,
                "pm2_5": {
                    "value": number + 0.25,
                    "unit": "ug/m3",
                    "coverage_ratio": 1.0,
                    "status": "ok",
                    "estimated": True,
                    "spatial_scale": "grid_1km",
                },
                "pollen_daily": [],
                "noise": {
                    "value": 40.0,
                    "unit": "0-100 risk index",
                    "confidence": "medium",
                    "scenarios": {"daytime": 40.0},
                    "status": "partial",
                },
            }
        )
        noise_segments.extend(
            [
                {
                    "segment_id": f"{route_id}_S0001",
                    "route_id": route_id,
                    "segment_index": 1,
                    "length_m": 250.0,
                    "pm25_grid_id": "GRID_001",
                    "static_risk_score": 30.0,
                    "scenario_risk_scores": {"daytime": 30.0},
                    "status": "partial",
                    "confidence": "medium",
                    "estimated": True,
                    "source_ids": ["fixture"],
                },
                {
                    "segment_id": f"{route_id}_S0002",
                    "route_id": route_id,
                    "segment_index": 2,
                    "length_m": 750.0,
                    "pm25_grid_id": "GRID_002",
                    "static_risk_score": 50.0,
                    "scenario_risk_scores": {"daytime": 50.0},
                    "status": "partial",
                    "confidence": "medium",
                    "estimated": True,
                    "source_ids": ["fixture"],
                },
            ]
        )
        features.append({"type": "Feature", "properties": {"route_id": route_id}})
    _write_json(exports / "route_environment.json", {"routes": routes})
    _write_json(exports / "noise_segments.json", {"segments": noise_segments})
    _write_json(route_geojson, {"type": "FeatureCollection", "features": features})
    return root, route_geojson, web_output


def test_publish_web_dashboard_builds_valid_sanitized_contract(tmp_path: Path) -> None:
    root, route_geojson, output = _source_tree(tmp_path)

    dashboard = publish_web_dashboard(
        root=root,
        route_geojson_path=route_geojson,
        output_path=output,
        generated_at=datetime(2026, 8, 27, 6, 10, tzinfo=timezone.utc),
    )

    assert set(dashboard) == {"current", "forecast", "grids", "routes", "metadata"}
    assert len(dashboard["current"]["life_indices"]) == 16
    assert len(dashboard["forecast"]["weather_hourly"]) == 24
    assert len(dashboard["forecast"]["aqi_hourly"]) == 24
    assert len(dashboard["forecast"]["pm2_5_hourly"]) == 24
    assert len(dashboard["forecast"]["life_indices_daily"]) == 48
    assert len(dashboard["forecast"]["pollen_grid_daily"]) == 5
    assert len(dashboard["grids"]["items"]) == 54
    assert len(dashboard["routes"]["items"]) == 90
    first_grid = dashboard["grids"]["items"][0]
    assert first_grid["pm2_5"]["name"] == "PM2.5"
    assert first_grid["pm2_5"]["value"] == 1.0
    assert first_grid["pm2_5"]["unit"] == "µg/m³"
    assert first_grid["pm2_5"]["spatial_resolution_m"] == 1000
    assert first_grid["pm2_5"]["spatial_scale"] == "1km_grid_estimate"
    assert first_grid["pm2_5"]["estimated"] is True
    assert first_grid["pm2_5"]["status"] == "ok"
    assert first_grid["pm2_5"]["business_time"] == "2026-08-27T14:00:00+08:00"
    assert first_grid["pm2_5"]["fetched_at"] == "2026-08-27T14:02:00+08:00"
    assert first_grid["noise"]["unit"] == "0-100 risk index"
    assert first_grid["noise"]["confidence"] == "medium"
    assert first_grid["noise"]["scenario_risk_scores"]["daytime"] == 40.0
    assert first_grid["coordinates"]["wgs84"] == {
        "longitude": pytest.approx(121.4401),
        "latitude": pytest.approx(31.1601),
    }
    assert first_grid["coordinates"]["gcj02"]["longitude"] != pytest.approx(121.4401)
    first_route = dashboard["routes"]["items"][0]
    assert first_route["pm2_5"]["value"] == pytest.approx(1.75)
    assert first_route["pm2_5"]["unit"] == "µg/m³"
    assert first_route["pm2_5"]["business_time"] == "2026-08-27T14:00:00+08:00"
    assert first_route["access_route_environment"] == {
        "status": "not_aggregated",
        "aggregation": "not_computed",
    }
    assert dashboard["metadata"]["pm2_5_route_method"]["grid_count"] == 54
    assert dashboard["metadata"]["pm2_5_route_method"]["weight"] == "segment_length_m"
    assert dashboard["metadata"]["pm2_5_route_method"]["recomputed_by_web_export"] is True
    assert dashboard["metadata"]["status"] == "partial"
    assert dashboard["metadata"]["future_pm2_5"]["concentration_inferred_from_aqi"] is False
    assert all(not item["values"] for item in dashboard["forecast"]["pm2_5_hourly"])
    serialized = output.read_text(encoding="utf-8")
    assert "raw_data" not in serialized
    assert "api_key" not in serialized
    assert "do-not-export" not in serialized
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))
    assert json.loads(serialized) == dashboard


def test_publish_web_dashboard_limits_long_provider_forecast_to_24_hours(
    tmp_path: Path,
) -> None:
    root, route_geojson, output = _source_tree(tmp_path)
    hourly_path = root / "runtime" / "exports" / "environment_hourly.json"
    hourly = json.loads(hourly_path.read_text(encoding="utf-8"))
    hourly["weather_forecast_24h"] = [
        _record("weather_forecast", values={"temperature_c": hour}) for hour in range(96)
    ]
    _write_json(hourly_path, hourly)

    dashboard = publish_web_dashboard(
        root=root,
        route_geojson_path=route_geojson,
        output_path=output,
    )

    weather_hourly = dashboard["forecast"]["weather_hourly"]
    assert len(weather_hourly) == 24
    assert weather_hourly[0]["values"]["temperature_c"] == 0
    assert weather_hourly[-1]["values"]["temperature_c"] == 23


def test_publish_web_dashboard_selects_latest_valid_qweather_reference_weather(
    tmp_path: Path,
) -> None:
    root, route_geojson, output = _source_tree(tmp_path)
    exports = root / "runtime" / "exports"
    reference_source_id = "qweather:31.18,121.45"

    latest_path = exports / "environment_latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    stale_huafeng = {
        **_record("weather_observation", values={"temperature_c": 34}),
        "business_time": "2026-08-26T15:00:00+08:00",
        "fetched_at": "2026-08-26T15:01:00+08:00",
        "status": "stale",
        "location_key": "974168",
        "source": {"provider": "huafeng", "source_id": "974168"},
    }
    older_qweather = {
        **_record("weather_observation", values={"temperature_c": 29}),
        "business_time": "2026-08-27T13:00:00+08:00",
        "fetched_at": "2026-08-27T13:01:00+08:00",
    }
    latest_qweather = {
        **_record("weather_observation", values={"temperature_c": 30}),
        "business_time": "2026-08-27T14:00:00+08:00",
        "fetched_at": "2026-08-27T14:01:00+08:00",
    }
    latest["reference_source_id"] = reference_source_id
    latest["current_weather"] = [stale_huafeng, older_qweather, latest_qweather]
    latest["active_alerts"] = [
        {
            **_record("weather_alert", values={"title": f"Huafeng alert {number}"}),
            "status": "no_data",
            "location_key": "974168",
            "source": {"provider": "huafeng", "source_id": "974168"},
        }
        for number in range(3)
    ] + [
        {
            **_record("weather_alert"),
            "status": "no_data",
        }
    ]
    _write_json(latest_path, latest)

    hourly_path = exports / "environment_hourly.json"
    hourly = json.loads(hourly_path.read_text(encoding="utf-8"))
    stale_huafeng_hourly: list[dict[str, object]] = []
    older_qweather_hourly: list[dict[str, object]] = []
    latest_qweather_hourly: list[dict[str, object]] = []
    for hour in range(24):
        stale_huafeng_hourly.append(
            {
                **_record("weather_forecast", values={"temperature_c": 40 + hour}),
                "business_time": f"2026-08-26T{hour:02d}:00:00+08:00",
                "fetched_at": "2026-08-26T00:01:00+08:00",
                "status": "stale",
                "location_key": "974168",
                "source": {"provider": "huafeng", "source_id": "974168"},
            }
        )
        older_qweather_hourly.append(
            {
                **_record("weather_forecast", values={"temperature_c": 10 + hour}),
                "business_time": f"2026-08-27T{hour:02d}:00:00+08:00",
                "fetched_at": "2026-08-27T12:01:00+08:00",
            }
        )
        latest_qweather_hourly.append(
            {
                **_record("weather_forecast", values={"temperature_c": 20 + hour}),
                "business_time": f"2026-08-28T{hour:02d}:00:00+08:00",
                "fetched_at": "2026-08-27T14:01:00+08:00",
            }
        )
    hourly["reference_source_id"] = reference_source_id
    hourly["weather_forecast_24h"] = [
        *stale_huafeng_hourly,
        *older_qweather_hourly,
        *latest_qweather_hourly,
    ]
    _write_json(hourly_path, hourly)

    dashboard = publish_web_dashboard(
        root=root,
        route_geojson_path=route_geojson,
        output_path=output,
    )

    current_weather = dashboard["current"]["weather"]
    assert current_weather["values"]["temperature_c"] == 30
    assert current_weather["location_key"] == reference_source_id
    assert current_weather["source"]["provider"] == "qweather"
    assert dashboard["current"]["alerts"] == []
    weather_hourly = dashboard["forecast"]["weather_hourly"]
    assert [record["values"]["temperature_c"] for record in weather_hourly] == list(range(20, 44))
    assert {record["location_key"] for record in weather_hourly} == {reference_source_id}
    assert {record["source"]["provider"] for record in weather_hourly} == {"qweather"}
    assert "huafeng" not in json.dumps(dashboard, ensure_ascii=False).lower()


def test_publish_web_dashboard_rejects_weather_without_valid_qweather_reference(
    tmp_path: Path,
) -> None:
    root, route_geojson, output = _source_tree(tmp_path)
    latest_path = root / "runtime" / "exports" / "environment_latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["current_weather"] = [
        {
            **_record("weather_observation", values={"temperature_c": 34}),
            "status": "stale",
            "location_key": "974168",
            "source": {"provider": "huafeng", "source_id": "974168"},
        }
    ]
    _write_json(latest_path, latest)

    with pytest.raises(
        WebExportError,
        match="current_weather 缺少有效的 qweather 参考源记录",
    ):
        publish_web_dashboard(
            root=root,
            route_geojson_path=route_geojson,
            output_path=output,
        )


def test_publish_web_dashboard_rejects_route_id_mismatch_without_snapshot(
    tmp_path: Path,
) -> None:
    root, route_geojson, output = _source_tree(tmp_path)
    document = json.loads(route_geojson.read_text(encoding="utf-8"))
    document["features"][0]["properties"]["route_id"] = "UNMATCHED"
    _write_json(route_geojson, document)

    with pytest.raises(WebExportError, match="route_id 集合"):
        publish_web_dashboard(
            root=root,
            route_geojson_path=route_geojson,
            output_path=output,
        )

    assert not output.exists()


def test_publish_web_dashboard_preserves_snapshot_and_marks_stale_on_source_failure(
    tmp_path: Path,
) -> None:
    root, route_geojson, output = _source_tree(tmp_path)
    previous = publish_web_dashboard(
        root=root,
        route_geojson_path=route_geojson,
        output_path=output,
    )
    (root / "runtime" / "exports" / "route_environment.json").unlink()

    stale = publish_web_dashboard(
        root=root,
        route_geojson_path=route_geojson,
        output_path=output,
    )

    assert stale["metadata"]["status"] == "stale"
    assert stale["metadata"]["stale_reason"] == "missing_source:route_environment.json"
    assert stale["current"]["status"] == "stale"
    assert stale["forecast"]["status"] == "stale"
    assert stale["grids"]["status"] == "stale"
    assert stale["routes"]["status"] == "stale"
    assert stale["routes"]["items"] == previous["routes"]["items"]
    assert json.loads(output.read_text(encoding="utf-8")) == stale


def test_publish_web_dashboard_removes_absolute_local_paths(tmp_path: Path) -> None:
    root, route_geojson, output = _source_tree(tmp_path)
    route_path = root / "runtime" / "exports" / "route_environment.json"
    document = json.loads(route_path.read_text(encoding="utf-8"))
    document["routes"][0]["debug_path"] = r"D:\private\route.json"
    document["routes"][0]["debug_paths"] = ["/tmp/private.json", "public-label"]
    _write_json(route_path, document)

    dashboard = publish_web_dashboard(
        root=root,
        route_geojson_path=route_geojson,
        output_path=output,
    )

    serialized = json.dumps(dashboard, ensure_ascii=False)
    assert "D:\\\\private" not in serialized
    assert "/tmp/private.json" not in serialized
    assert "public-label" in serialized
