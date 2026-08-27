import json
from pathlib import Path
from typing import cast

from weather_api_data.noise_model import (
    build_noise_segments_document,
    load_noise_calibration,
    load_noise_model_config,
    score_noise_segment,
)
from weather_api_data.osm_features import SegmentSpatialFeatures


def _complete_features() -> SegmentSpatialFeatures:
    return SegmentSpatialFeatures(
        segment_id="R1_S0001",
        route_id="R1",
        road_class_score=0.8,
        distance_pressure_score=0.7,
        poi_pressure_score=0.4,
        intersection_pressure_score=0.3,
        acoustic_zone_score=0.4,
        green_water_mitigation=0.2,
        feature_values={"road_class": "primary"},
        source_ids=("osm:way/1", "shanghai-acoustic:zone-2"),
        completeness=1.0,
        status="ok",
    )


def test_noise_model_outputs_risk_scenarios_without_decibels() -> None:
    root = Path(__file__).parents[1]
    config = load_noise_model_config(root / "config" / "noise_model.json")

    assessment = score_noise_segment(_complete_features(), config)
    payload = assessment.to_dict()

    assert assessment.status == "ok"
    assert assessment.confidence == "high"
    assert 0.0 <= assessment.static_risk_score <= 100.0
    assert assessment.scenario_risk_scores["weekday_peak"] > assessment.static_risk_score
    assert assessment.estimated is True
    assert assessment.calibration_applied is False
    assert not any("db" in key.lower() for key in payload)


def test_missing_features_lower_status_and_confidence() -> None:
    root = Path(__file__).parents[1]
    config = load_noise_model_config(root / "config" / "noise_model.json")
    features = SegmentSpatialFeatures(
        segment_id="R1_S0001",
        route_id="R1",
        road_class_score=0.5,
        distance_pressure_score=None,
        poi_pressure_score=None,
        intersection_pressure_score=None,
        acoustic_zone_score=None,
        green_water_mitigation=None,
        feature_values={},
        source_ids=("route_metadata:R1",),
        completeness=1 / 6,
        status="partial",
    )

    assessment = score_noise_segment(features, config)

    assert assessment.status == "partial"
    assert assessment.confidence == "low"
    assert assessment.source_ids == ("route_metadata:R1",)


def test_existing_90_routes_build_a_jsonable_partial_noise_document() -> None:
    root = Path(__file__).parents[1]
    routes_path = root.parent / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"

    document = build_noise_segments_document(
        routes_path=routes_path,
        config_path=root / "config" / "noise_model.json",
    )

    assert document["route_count"] == 90
    assert isinstance(document["segment_count"], int)
    assert document["segment_count"] > 90
    assert document["status"] == "partial"
    assert isinstance(document["segments"], list)
    records = cast(list[dict[str, object]], document["segments"])
    assert all(record["estimated"] is True for record in records)
    assert all("noise_estimated_db_a" not in record for record in records)
    json.dumps(document, ensure_ascii=False)


def test_historical_observations_conservatively_anchor_risk_score(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = load_noise_model_config(root / "config" / "noise_model.json")
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "observation_count": 1000,
                "station_count": 4,
                "calibration": {"district_anchor": 60.0},
            }
        ),
        encoding="utf-8",
    )
    calibration = load_noise_calibration(calibration_path, config)

    raw = score_noise_segment(_complete_features(), config)
    anchored = score_noise_segment(_complete_features(), config, calibration)

    assert calibration.anchor_score == 50.0
    assert anchored.calibration_applied is True
    assert anchored.calibration_weight == 0.2
    assert anchored.static_risk_score != raw.static_risk_score
    assert "shanghai_open_data:O5485687412025006" in anchored.source_ids
    assert not any("db" in key.lower() for key in anchored.to_dict())
