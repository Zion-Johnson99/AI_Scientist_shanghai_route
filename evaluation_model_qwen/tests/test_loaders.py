from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from evaluation_model_qwen import loaders
from evaluation_model_qwen.loaders import LoaderError, load_data


def _route(route_id: str) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "route_name": f"路线 {route_id}",
        "route_mode": "walk",
        "route_shape": "one_way",
        "distance_m": 1000,
        "duration_min": 15.0,
        "start_location": {
            "name": "起点",
            "lng_gcj02": 121.45,
            "lat_gcj02": 31.18,
            "ignored": "source detail",
        },
        "end_location": {
            "name": "终点",
            "lng_gcj02": 121.46,
            "lat_gcj02": 31.19,
        },
        "region_zone": "徐汇区",
        "tags": ["步行"],
        "feature_tags": ["公园"],
        "popular_area_ids": ["park"],
        "preference_hits": ["quiet"],
        "nearby_pois": [
            {
                "poi_type": "toilet",
                "poi_name": "公共厕所",
                "distance_m": 20.0,
                "verification_status": "verified",
                "ignored": "evidence detail",
            },
            {
                "poi_type": "coffee",
                "poi_name": "未核实咖啡店",
                "distance_m": 30.0,
                "verification_status": "pending",
            },
        ],
        "confidence": "high",
        "validation_status": "accepted",
        "geometry_status": "complete",
        "route_inside_ratio": 1.0,
        "snap_ratio": None,
        "ignored": "catalog detail",
    }


def _timed(status: str, business_time: str) -> dict[str, Any]:
    return {
        "status": status,
        "business_time": business_time,
        "valid_until": "2026-08-28T19:00:00+08:00",
        "values": {"temperature_c": 28.0},
        "ignored": "source detail",
    }


def _route_environment(route_id: str) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "status": "partial",
        "pm2_5": {
            "status": "ok",
            "value": 12.5,
            "business_time": "2026-08-28T17:00:00+08:00",
            "fetched_at": "2026-08-28T17:02:00+08:00",
            "expires_at": "2026-08-28T18:02:00+08:00",
            "confidence": "medium",
            "estimated": True,
            "spatial_scale": "1km_grid_estimate",
            "unit": "ug/m3",
            "ignored": "source detail",
        },
        "noise": {
            "status": "partial",
            "value": 17.0,
            "business_time": "static_scenario",
            "fetched_at": "2026-08-27T14:42:00+08:00",
            "expires_at": None,
            "confidence": "low",
            "estimated": True,
            "spatial_scale": "about_100m_road_segment_proxy",
            "unit": "0-100 risk index",
            "scenarios": {"daytime": 17.0},
        },
        "pollen_daily": [
            {
                "status": "partial",
                "value": 20.0,
                "business_time": "2026-08-28",
                "fetched_at": "2026-08-27T14:42:00+08:00",
                "expires_at": "2026-08-28T23:59:59+08:00",
                "confidence": "low",
                "estimated": True,
                "spatial_scale": "about_1000m_grid_sample",
                "unit": "0-100 risk index",
                "risk_level": "low",
            }
        ],
        "ignored": "aggregation detail",
    }


def _dashboard(route_ids: list[str]) -> dict[str, Any]:
    return {
        "metadata": {
            "generated_at": "2026-08-28T17:30:00+08:00",
            "status": "partial",
        },
        "current": {
            "status": "ok",
            "weather": _timed("ok", "2026-08-28T17:30:00+08:00"),
            "aqi": _timed("ok", "2026-08-28T17:00:00+08:00"),
            "alerts": [_timed("stale", "2026-08-28T16:00:00+08:00")],
        },
        "forecast": {
            "status": "partial",
            "weather_hourly": [_timed("ok", "2026-08-28T18:00:00+08:00")],
            "aqi_hourly": [_timed("partial", "2026-08-28T18:00:00+08:00")],
        },
        "routes": {
            "status": "partial",
            "count": len(route_ids),
            "items": [_route_environment(route_id) for route_id in route_ids],
        },
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_contract(tmp_path: Path) -> tuple[Path, Path]:
    route_ids = [f"XH_WALK_{index:04d}" for index in range(1, 91)]
    route_path = tmp_path / "route_catalog.json"
    environment_path = tmp_path / "environment_dashboard.json"
    _write_json(route_path, [_route(route_id) for route_id in route_ids])
    _write_json(environment_path, _dashboard(route_ids))
    return route_path, environment_path


def test_load_data_parses_and_selects_contract_fields(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)

    bundle = load_data(route_catalog_path=route_path, environment_path=environment_path)

    assert len(bundle.routes) == 90
    route = bundle.routes[0]
    assert route.model_dump() == {
        "route_id": "XH_WALK_0001",
        "route_name": "路线 XH_WALK_0001",
        "route_mode": "walk",
        "route_shape": "one_way",
        "distance_m": 1000,
        "duration_min": 15.0,
        "start_location": {"name": "起点", "lng_gcj02": 121.45, "lat_gcj02": 31.18},
        "end_location": {"name": "终点", "lng_gcj02": 121.46, "lat_gcj02": 31.19},
        "region_zone": "徐汇区",
        "tags": ["步行"],
        "feature_tags": ["公园"],
        "popular_area_ids": ["park"],
        "preference_hits": ["quiet"],
        "nearby_pois": [{"poi_type": "toilet", "poi_name": "公共厕所", "distance_m": 20.0}],
        "confidence": "high",
        "validation_status": "accepted",
        "geometry_status": "complete",
        "route_inside_ratio": 1.0,
        "snap_ratio": None,
    }
    snapshot = bundle.environment
    assert snapshot.status == "partial"
    assert snapshot.generated_at.isoformat() == "2026-08-28T17:30:00+08:00"
    assert snapshot.current_weather is not None
    assert snapshot.current_weather.business_time == "2026-08-28T17:30:00+08:00"
    assert len(snapshot.current_alerts) == 1
    assert snapshot.current_alerts[0].status == "stale"
    assert snapshot.weather_hourly[0].status == "ok"
    assert snapshot.aqi_hourly[0].status == "partial"
    route_environment = snapshot.route_environment["XH_WALK_0001"]
    assert route_environment.status == "partial"
    assert route_environment.pm2_5.valid_until == "2026-08-28T18:02:00+08:00"
    assert route_environment.noise.scenarios == {"daytime": 17.0}
    assert route_environment.pollen_daily[0].risk_level == "low"


def test_load_data_preserves_all_current_alerts(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    dashboard = json.loads(environment_path.read_text(encoding="utf-8"))
    dashboard["current"]["alerts"] = [
        _timed("ok", "2026-08-28T17:00:00+08:00"),
        _timed("ok", "2026-08-28T17:10:00+08:00"),
    ]
    _write_json(environment_path, dashboard)

    bundle = load_data(route_catalog_path=route_path, environment_path=environment_path)

    assert [item.business_time for item in bundle.environment.current_alerts] == [
        "2026-08-28T17:00:00+08:00",
        "2026-08-28T17:10:00+08:00",
    ]


def test_load_data_fetches_remote_environment_to_runtime_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    payload = environment_path.read_bytes()
    project_root = tmp_path / "evaluation_model_qwen"
    project_root.mkdir()
    calls: list[tuple[str, float]] = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, amount: int = -1) -> bytes:
            return payload[:amount] if amount >= 0 else payload

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        calls.append((cast(str, request.full_url), timeout))
        return FakeResponse()

    remote_url = "https://zion-johnson99.github.io/AI_Scientist_shanghai_route/data/web/environment_dashboard.json"
    monkeypatch.setenv("EVALUATION_MODEL_QWEN_ENVIRONMENT_URL", remote_url)
    monkeypatch.setenv("EVALUATION_MODEL_QWEN_ENVIRONMENT_CACHE_SECONDS", "300")
    monkeypatch.setattr(loaders, "urlopen", fake_urlopen)

    bundle = load_data(project_root=project_root, route_catalog_path=route_path)

    assert len(bundle.environment.route_environment) == 90
    assert calls == [(remote_url, 10.0)]
    assert (project_root / "runtime" / "cache" / "environment_dashboard.json").is_file()


def test_load_data_defaults_to_real_sibling_data() -> None:
    bundle = load_data()

    assert len(bundle.routes) == 90
    assert len(bundle.environment.route_environment) == 90
    assert {route.route_id for route in bundle.routes} == set(bundle.environment.route_environment)


def test_load_data_rejects_duplicate_route_id_with_context(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    routes = json.loads(route_path.read_text(encoding="utf-8"))
    routes[1]["route_id"] = routes[0]["route_id"]
    _write_json(route_path, routes)

    with pytest.raises(LoaderError) as error:
        load_data(route_catalog_path=route_path, environment_path=environment_path)

    message = str(error.value)
    assert str(route_path) in message
    assert "route_catalog[1].route_id" in message


def test_load_data_requires_exactly_90_routes(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    routes = json.loads(route_path.read_text(encoding="utf-8"))
    _write_json(route_path, routes[:-1])

    with pytest.raises(LoaderError) as error:
        load_data(route_catalog_path=route_path, environment_path=environment_path)

    message = str(error.value)
    assert str(route_path) in message
    assert "route_catalog" in message
    assert "expected 90 routes, got 89" in message


def test_load_data_rejects_route_environment_id_mismatch(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    dashboard = json.loads(environment_path.read_text(encoding="utf-8"))
    dashboard["routes"]["items"][-1]["route_id"] = "XH_WALK_9999"
    _write_json(environment_path, dashboard)

    with pytest.raises(LoaderError) as error:
        load_data(route_catalog_path=route_path, environment_path=environment_path)

    message = str(error.value)
    assert str(route_path) in message
    assert str(environment_path) in message
    assert "routes.items.route_id" in message
    assert "XH_WALK_0090" in message
    assert "XH_WALK_9999" in message


def test_load_data_reports_invalid_field_path(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    dashboard = json.loads(environment_path.read_text(encoding="utf-8"))
    dashboard["current"]["weather"]["status"] = "unknown"
    _write_json(environment_path, dashboard)

    with pytest.raises(LoaderError) as error:
        load_data(route_catalog_path=route_path, environment_path=environment_path)

    message = str(error.value)
    assert str(environment_path) in message
    assert "current.weather.status" in message


def test_load_data_requires_environment_provenance_fields(tmp_path: Path) -> None:
    route_path, environment_path = _write_contract(tmp_path)
    dashboard = json.loads(environment_path.read_text(encoding="utf-8"))
    del dashboard["routes"]["items"][0]["pm2_5"]["spatial_scale"]
    _write_json(environment_path, dashboard)

    with pytest.raises(LoaderError) as error:
        load_data(route_catalog_path=route_path, environment_path=environment_path)

    assert "routes.items[0].pm2_5.spatial_scale" in str(error.value)
