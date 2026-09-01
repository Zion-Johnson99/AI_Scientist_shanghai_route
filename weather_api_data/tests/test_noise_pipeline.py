from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import requests

from weather_api_data.config import Settings
from weather_api_data.noise_pipeline import (
    build_noise_from_project,
    prepare_noise_history_from_project,
    refresh_noise_observations_from_project,
)


class FakeResponse:
    status_code = 200

    def json(self) -> object:
        return {
            "code": "000000",
            "message": "成功",
            "data": '{"state":true,"message":"","total":0,"data":null}',
        }


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(self, _url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse()


def _write_history(root: Path) -> None:
    target = (
        root
        / "noise_data"
        / "xuhui_noise_monitoring"
        / "origin_data"
        / "shanghai_noise_monitoring.csv"
    )
    target.parent.mkdir(parents=True)
    target.write_text(
        "ID,STIME,L90,POINTID,JHPT_DELETE,FS,YWSJ_DATE,LAEQ,SHIDU,QW,SD,"
        "JHPT_UPDATE_TIME,LMIN,L50,YL,QY,L10,LMAX\n"
        "1,2025-01-01 00:00:00,45,310104320001,0,1,2025-01-01 01:00:00,50,"
        "60,20,1,2025-01-01 01:00:00,40,48,0,1010,55,70\n",
        encoding="utf-8-sig",
    )


def _write_complete_history(root: Path) -> None:
    target = (
        root
        / "noise_data"
        / "xuhui_noise_monitoring"
        / "origin_data"
        / "shanghai_noise_monitoring.csv"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "ID,STIME,L90,POINTID,JHPT_DELETE,FS,YWSJ_DATE,LAEQ,SHIDU,QW,SD,"
        "JHPT_UPDATE_TIME,LMIN,L50,YL,QY,L10,LMAX"
    )
    rows: list[str] = []
    pointids = ("310104320001", "310104330002", "310104340004", "310104340006")
    for day in range(100):
        observed = datetime(2025, 1, 1) + timedelta(days=day)
        timestamp = observed.strftime("%Y-%m-%d 00:00:00")
        for station_index, pointid in enumerate(pointids):
            rows.append(
                f"{day}-{pointid},{timestamp},45,{pointid},0,1,{timestamp},"
                f"{50 + station_index},60,20,1,{timestamp},40,48,0,1010,55,70"
            )
    target.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8-sig")


def test_disabled_api_still_prepares_historical_calibration(tmp_path: Path) -> None:
    _write_history(tmp_path)

    result = refresh_noise_observations_from_project(
        settings=Settings(),
        session=cast(requests.Session, FakeSession()),
        root=tmp_path,
    )

    assert result["status"] == "disabled"
    assert Path(cast(str, result["historical_calibration_path"])).is_file()


def test_prepare_noise_history_reports_generated_products(tmp_path: Path) -> None:
    _write_history(tmp_path)

    result = prepare_noise_history_from_project(tmp_path)

    assert result["status"] == "partial"
    assert result["observation_count"] == 1
    assert Path(cast(str, result["observations_path"])).is_file()


def test_successful_empty_api_is_partial_no_data_and_archived(tmp_path: Path) -> None:
    _write_history(tmp_path)
    session = FakeSession()
    settings = Settings(
        shanghai_noise_enabled=True,
        shanghai_noise_token="fixture-token",
        shanghai_noise_min_interval_seconds=0.0,
    )

    result = refresh_noise_observations_from_project(
        settings=settings,
        session=cast(requests.Session, session),
        root=tmp_path,
        generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        sleep_fn=lambda _seconds: None,
    )

    assert result["status"] == "partial"
    assert result["api_status"] == "no_data"
    assert result["call_count"] == 4
    assert len(session.calls) == 4
    assert all(call["headers"] == {"token": "fixture-token"} for call in session.calls)
    context = json.loads(Path(cast(str, result["observation_context_path"])).read_text("utf-8"))
    assert context["status"] == "no_data"
    assert context["calibration_applied_to_segments"] is False
    archives = list((tmp_path / "runtime" / "archive" / "noise").rglob("*.json.gz"))
    assert len(archives) == 4
    archived_text = "".join(gzip.open(path, "rt", encoding="utf-8").read() for path in archives)
    assert "fixture-token" not in archived_text


def test_build_noise_does_not_require_pm25_output(tmp_path: Path) -> None:
    root = tmp_path / "weather_api_data"
    _write_complete_history(root)
    config_dir = root / "config"
    config_dir.mkdir()
    project_root = Path(__file__).parents[1]
    (config_dir / "noise_model.json").write_text(
        (project_root / "config" / "noise_model.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    routes = tmp_path / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"
    routes.parent.mkdir(parents=True)
    routes.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "route_id": "XH_TEST_0001",
                            "road_names": ["滨江绿道"],
                            "tags": ["滨江"],
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

    result = build_noise_from_project(root=root)

    assert result["route_count"] == 1
    assert result["calibration_status"] == "applied"
    assert Path(cast(str, result["output_path"])).is_file()
    assert not (root / "runtime" / "exports" / "pm25_grid_latest.json").exists()
