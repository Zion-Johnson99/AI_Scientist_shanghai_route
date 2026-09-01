from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from weather_api_data.pollen_client import (
    PollenClient,
    PollenForecastDay,
    PollenLookupResult,
    PollenTypeIndex,
)
from weather_api_data.pollen_model import (
    PollenGridPoint,
    WeatherFactors,
    build_pollen_grid_document,
    collect_pollen_grid_document,
    derive_pollen_grid_scores,
    load_pollen_model_config,
)

MODEL_PATH = Path(__file__).parents[1] / "config" / "pollen_model.json"
GENERATED_AT = datetime(2026, 8, 26, 1, 2, 3, tzinfo=timezone.utc)


def _day(value: int | None = 3) -> PollenForecastDay:
    return PollenForecastDay(
        forecast_date="2026-08-26",
        pollen_types={
            "GRASS": PollenTypeIndex(
                code="GRASS",
                index_value=value,
                index_code="MODERATE" if value is not None else None,
                category="Moderate" if value is not None else None,
                in_season=True,
                status="ok" if value is not None else "no_data",
            ),
            "TREE": PollenTypeIndex.no_data("TREE"),
            "WEED": PollenTypeIndex.no_data("WEED"),
        },
    )


def _points(count: int = 54) -> tuple[PollenGridPoint, ...]:
    return tuple(
        PollenGridPoint(
            grid_id=f"XH_PM25_G{index:03d}",
            longitude=121.39 + index * 0.001,
            latitude=31.13 + index * 0.001,
        )
        for index in range(1, count + 1)
    )


def test_model_config_uses_approved_component_weights() -> None:
    model = load_pollen_model_config(MODEL_PATH)

    assert model.weights == {
        "google_background": 0.70,
        "weather": 0.15,
        "vegetation": 0.15,
    }
    assert sum(model.weights.values()) == pytest.approx(1.0)


def test_derive_scores_emits_one_daily_record_for_all_54_grids() -> None:
    points = _points()
    forecasts = {point.grid_id: (_day(),) for point in points}
    weather = {
        "2026-08-26": WeatherFactors(
            wind_speed_kph=10.0,
            precipitation_mm=0.0,
            humidity_percent=50.0,
        )
    }
    vegetation = {point.grid_id: 0.40 for point in points}

    scores = derive_pollen_grid_scores(
        points,
        forecasts_by_grid=forecasts,
        weather_by_date=weather,
        vegetation_by_grid=vegetation,
        model=load_pollen_model_config(MODEL_PATH),
    )

    assert len(scores) == 54
    assert {score.grid_id for score in scores} == {point.grid_id for point in points}
    assert all(score.forecast_date == "2026-08-26" for score in scores)
    assert all(score.pollen_risk_score is not None for score in scores)
    assert all(
        0.0 <= score.pollen_risk_score <= 100.0
        for score in scores
        if score.pollen_risk_score is not None
    )
    assert all(score.status == "ok" for score in scores)
    assert all(score.estimated is True for score in scores)
    assert scores[0].components["tree_status"] == "no_data"
    assert scores[0].components["weed_status"] == "no_data"


def test_missing_google_index_renormalizes_proxy_components_and_marks_partial() -> None:
    point = _points(1)[0]
    weather = WeatherFactors(
        wind_speed_kph=10.0,
        precipitation_mm=0.0,
        humidity_percent=50.0,
    )
    model = load_pollen_model_config(MODEL_PATH)

    score = derive_pollen_grid_scores(
        (point,),
        forecasts_by_grid={point.grid_id: (_day(None),)},
        weather_by_date={"2026-08-26": weather},
        vegetation_by_grid={point.grid_id: 0.40},
        model=model,
    )[0]

    assert score.status == "partial"
    assert score.confidence == "low"
    assert score.components["grass_status"] == "no_data"
    assert score.components["google_background_score"] is None
    assert score.pollen_risk_score is not None
    assert score.pollen_risk_score > 0
    assert score.source == "qweather+vegetation_proxy"


def test_no_available_component_emits_no_data_without_inventing_score() -> None:
    point = _points(1)[0]

    score = derive_pollen_grid_scores(
        (point,),
        forecasts_by_grid={point.grid_id: (_day(None),)},
        weather_by_date={},
        vegetation_by_grid={},
        model=load_pollen_model_config(MODEL_PATH),
    )[0]

    assert score.status == "no_data"
    assert score.pollen_risk_score is None
    assert score.risk_level == "no_data"
    assert score.confidence == "low"


def test_invalid_grid_and_feature_values_fail_with_context() -> None:
    duplicate_points = (
        PollenGridPoint("XH_PM25_G001", 121.4, 31.2),
        PollenGridPoint("XH_PM25_G001", 121.5, 31.2),
    )
    model = load_pollen_model_config(MODEL_PATH)

    with pytest.raises(ValueError, match="XH_PM25_G001"):
        derive_pollen_grid_scores(
            duplicate_points,
            forecasts_by_grid={},
            weather_by_date={},
            vegetation_by_grid={},
            model=model,
        )

    point = _points(1)[0]
    with pytest.raises(ValueError, match="vegetation"):
        derive_pollen_grid_scores(
            (point,),
            forecasts_by_grid={point.grid_id: (_day(),)},
            weather_by_date={},
            vegetation_by_grid={point.grid_id: 1.1},
            model=model,
        )


def test_document_contract_is_json_ready_and_counts_unique_dates() -> None:
    point = _points(1)[0]
    scores = derive_pollen_grid_scores(
        (point,),
        forecasts_by_grid={point.grid_id: (_day(),)},
        weather_by_date={
            "2026-08-26": WeatherFactors(10.0, 0.0, 50.0),
        },
        vegetation_by_grid={point.grid_id: 0.4},
        model=load_pollen_model_config(MODEL_PATH),
    )

    document = build_pollen_grid_document(scores, generated_at=GENERATED_AT)

    assert document["dataset_type"] == "pollen_grid_scores"
    assert document["grid_count"] == 1
    assert document["forecast_date_count"] == 1
    assert document["status"] == "ok"
    assert document["generated_at"] == "2026-08-26T01:02:03+00:00"
    assert document["spatial_resolution_m"] == 1000
    assert document["estimated"] is True
    assert document["source"] == "google_pollen+qweather+vegetation_proxy"
    record = document["grid_scores"][0]  # type: ignore[index]
    assert record["grid_id"] == point.grid_id  # type: ignore[index]


def test_document_excludes_expired_dates_and_caps_window_from_generated_day() -> None:
    point = _points(1)[0]
    model = load_pollen_model_config(MODEL_PATH)
    forecasts = {
        point.grid_id: tuple(
            PollenForecastDay(
                forecast_date=f"2026-08-{day:02d}",
                pollen_types=_day().pollen_types,
            )
            for day in range(25, 32)
        )
    }
    scores = derive_pollen_grid_scores(
        (point,),
        forecasts_by_grid=forecasts,
        weather_by_date={
            "2026-08-20": WeatherFactors(10.0, 0.0, 50.0),
        },
        vegetation_by_grid={},
        model=model,
    )

    document = build_pollen_grid_document(
        scores,
        generated_at=datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc),
    )

    records = cast(list[dict[str, object]], document["grid_scores"])
    assert {record["forecast_date"] for record in records} == {
        "2026-08-26",
        "2026-08-27",
        "2026-08-28",
        "2026-08-29",
        "2026-08-30",
    }
    assert document["forecast_date_count"] == 5


def test_collect_document_reads_54_pm25_centers_and_queries_each_once(tmp_path: Path) -> None:
    points = _points()
    pm25_path = tmp_path / "pm25_grid_latest.json"
    pm25_path.write_text(
        json.dumps(
            {
                "grid_count": 54,
                "grids": [
                    {
                        "grid_id": point.grid_id,
                        "longitude": point.longitude,
                        "latitude": point.latitude,
                    }
                    for point in points
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakePollenClient:
        def __init__(self) -> None:
            self.calls: list[tuple[float, float, int]] = []

        def lookup(
            self,
            *,
            latitude: float,
            longitude: float,
            days: int = 5,
            language_code: str = "zh-CN",
        ) -> PollenLookupResult:
            del language_code
            self.calls.append((latitude, longitude, days))
            return PollenLookupResult(
                latitude=latitude,
                longitude=longitude,
                days=(_day(),),
                status="ok",
                fetched_at=GENERATED_AT,
                expires=None,
            )

    client = FakePollenClient()
    document = collect_pollen_grid_document(
        client=cast(PollenClient, client),
        pm25_grid_path=pm25_path,
        model_path=MODEL_PATH,
        weather_by_date={
            "2026-08-26": WeatherFactors(10.0, 0.0, 50.0),
        },
        vegetation_by_grid={point.grid_id: 0.4 for point in points},
        generated_at=GENERATED_AT,
    )

    assert len(client.calls) == 54
    assert document["grid_count"] == 54
    assert len(document["grid_scores"]) == 54  # type: ignore[arg-type]
