"""用可追踪空间特征计算 0 至 100 的路线段噪声风险代理。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from weather_api_data.osm_features import (
    SegmentSpatialFeatures,
    extract_segment_features,
    load_spatial_feature_catalog,
)
from weather_api_data.route_segments import assign_pm25_grids, load_route_segments

NoiseStatus = Literal["ok", "partial"]
Confidence = Literal["low", "medium", "high"]
_FEATURE_NAMES = (
    "road_class",
    "distance_pressure",
    "poi_transport",
    "intersection",
    "acoustic_zone",
    "green_water",
)


class NoiseModelError(RuntimeError):
    """表示噪声模型配置或输入特征无效。"""


@dataclass(frozen=True, slots=True)
class NoiseModelConfig:
    model_version: str
    feature_weights: Mapping[str, float]
    scenario_multipliers: Mapping[str, float]
    low_max: float
    medium_max: float
    missing_data_baseline_score: float
    observation_calibration_weight: float
    laeq_risk_min_db: float
    laeq_risk_max_db: float
    minimum_calibration_samples: int


@dataclass(frozen=True, slots=True)
class NoiseCalibration:
    anchor_score: float
    observation_count: int
    station_count: int
    source_id: str
    source_path: Path


@dataclass(frozen=True, slots=True)
class NoiseAssessment:
    segment_id: str
    route_id: str
    static_risk_score: float
    risk_level: str
    scenario_risk_scores: Mapping[str, float]
    status: NoiseStatus
    confidence: Confidence
    estimated: bool
    feature_completeness: float
    source_ids: tuple[str, ...]
    spatial_features: Mapping[str, object]
    model_version: str
    calibration_applied: bool
    calibration_weight: float
    calibration_anchor_score: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "route_id": self.route_id,
            "static_risk_score": self.static_risk_score,
            "noise_risk_score": self.static_risk_score,
            "risk_level": self.risk_level,
            "scenario_risk_scores": dict(self.scenario_risk_scores),
            "status": self.status,
            "confidence": self.confidence,
            "estimated": self.estimated,
            "feature_completeness": self.feature_completeness,
            "source_ids": list(self.source_ids),
            "spatial_features": dict(self.spatial_features),
            "model_version": self.model_version,
            "calibration_applied": self.calibration_applied,
            "calibration_weight": self.calibration_weight,
            "calibration_anchor_score": self.calibration_anchor_score,
        }


def load_noise_model_config(path: Path) -> NoiseModelConfig:
    """读取并严格校验首期静态噪声风险权重。"""

    if not path.is_file():
        raise NoiseModelError(f"噪声模型配置不存在: {path}")
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NoiseModelError(f"噪声模型配置读取失败: {path}") from error
    document = _mapping(decoded, "噪声模型配置")
    model_version = str(document.get("model_version", "")).strip()
    if not model_version:
        raise NoiseModelError("噪声模型配置缺少 model_version")
    weights = _float_mapping(document.get("feature_weights"), "feature_weights")
    if set(weights) != set(_FEATURE_NAMES):
        raise NoiseModelError(f"feature_weights 需包含: {list(_FEATURE_NAMES)}")
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise NoiseModelError("feature_weights 权重之和需为 1")
    scenarios = _float_mapping(document.get("scenario_multipliers"), "scenario_multipliers")
    if not scenarios or any(value <= 0 for value in scenarios.values()):
        raise NoiseModelError("scenario_multipliers 需为非空正数映射")
    thresholds = _mapping(document.get("risk_thresholds"), "risk_thresholds")
    low_max = _number(thresholds.get("low_max"), "risk_thresholds.low_max")
    medium_max = _number(thresholds.get("medium_max"), "risk_thresholds.medium_max")
    if not 0 <= low_max < medium_max <= 100:
        raise NoiseModelError("噪声风险阈值需满足 0 <= low_max < medium_max <= 100")
    baseline = _number(document.get("missing_data_baseline_score"), "missing_data_baseline_score")
    if not 0 <= baseline <= 100:
        raise NoiseModelError("missing_data_baseline_score 需位于 0 至 100")
    calibration = _mapping(document.get("observation_calibration"), "observation_calibration")
    calibration_weight = _number(calibration.get("weight"), "observation_calibration.weight")
    if not 0 <= calibration_weight <= 1:
        raise NoiseModelError("observation_calibration.weight 需位于 0 至 1")
    laeq_risk_min_db = _number(
        calibration.get("laeq_risk_min_db"),
        "observation_calibration.laeq_risk_min_db",
    )
    laeq_risk_max_db = _number(
        calibration.get("laeq_risk_max_db"),
        "observation_calibration.laeq_risk_max_db",
    )
    if laeq_risk_min_db >= laeq_risk_max_db:
        raise NoiseModelError("LAeq 风险映射上下界顺序无效")
    minimum_calibration_samples = _integer(
        calibration.get("minimum_samples"),
        "observation_calibration.minimum_samples",
    )
    if minimum_calibration_samples <= 0:
        raise NoiseModelError("observation_calibration.minimum_samples 需大于 0")
    return NoiseModelConfig(
        model_version,
        weights,
        scenarios,
        low_max,
        medium_max,
        baseline,
        calibration_weight,
        laeq_risk_min_db,
        laeq_risk_max_db,
        minimum_calibration_samples,
    )


def load_noise_calibration(path: Path, config: NoiseModelConfig) -> NoiseCalibration:
    """读取通过样本量与四站完整性门槛的历史观测校准。"""

    if not path.is_file():
        raise NoiseModelError(f"噪声观测校准不存在: {path}")
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NoiseModelError(f"噪声观测校准读取失败: {path}") from error
    document = _mapping(decoded, "噪声观测校准")
    if document.get("status") != "ok":
        raise NoiseModelError("噪声观测校准状态需为 ok")
    observation_count = _integer(document.get("observation_count"), "observation_count")
    station_count = _integer(document.get("station_count"), "station_count")
    if observation_count < config.minimum_calibration_samples or station_count < 4:
        raise NoiseModelError("噪声观测校准样本量或站点数不足")
    calibration = _mapping(document.get("calibration"), "calibration")
    anchor_db = _number(calibration.get("district_anchor"), "calibration.district_anchor")
    anchor_score = _clamp_score(
        100
        * (anchor_db - config.laeq_risk_min_db)
        / (config.laeq_risk_max_db - config.laeq_risk_min_db)
    )
    return NoiseCalibration(
        anchor_score=round(anchor_score, 3),
        observation_count=observation_count,
        station_count=station_count,
        source_id="shanghai_open_data:O5485687412025006",
        source_path=path.resolve(),
    )


def score_noise_segment(
    features: SegmentSpatialFeatures,
    config: NoiseModelConfig,
    calibration: NoiseCalibration | None = None,
) -> NoiseAssessment:
    """按现有特征权重重归一计算静态和分时噪声风险代理。"""

    components = {
        "road_class": features.road_class_score,
        "distance_pressure": features.distance_pressure_score,
        "poi_transport": features.poi_pressure_score,
        "intersection": features.intersection_pressure_score,
        "acoustic_zone": features.acoustic_zone_score,
        "green_water": (
            None
            if features.green_water_mitigation is None
            else 1.0 - features.green_water_mitigation
        ),
    }
    for name, value in components.items():
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
            raise NoiseModelError(f"特征 {name} 需位于 0 至 1")
    available_weight = sum(
        config.feature_weights[name] for name, value in components.items() if value is not None
    )
    if available_weight == 0:
        score = config.missing_data_baseline_score
    else:
        score = (
            100.0
            * sum(
                config.feature_weights[name] * value
                for name, value in components.items()
                if value is not None
            )
            / available_weight
        )
    calibration_weight = config.observation_calibration_weight if calibration is not None else 0.0
    if calibration is not None:
        score = (1.0 - calibration_weight) * score + calibration_weight * calibration.anchor_score
    static_score = round(_clamp_score(score), 3)
    scenarios = {
        name: round(_clamp_score(static_score * multiplier), 3)
        for name, multiplier in config.scenario_multipliers.items()
    }
    confidence: Confidence
    if features.completeness >= 0.85:
        confidence = "high"
    elif features.completeness >= 0.6:
        confidence = "medium"
    else:
        confidence = "low"
    return NoiseAssessment(
        segment_id=features.segment_id,
        route_id=features.route_id,
        static_risk_score=static_score,
        risk_level=_risk_level(static_score, config),
        scenario_risk_scores=scenarios,
        status="ok" if features.status == "ok" and features.completeness == 1.0 else "partial",
        confidence=confidence,
        estimated=True,
        feature_completeness=features.completeness,
        source_ids=(
            (*features.source_ids, calibration.source_id)
            if calibration is not None
            else features.source_ids
        ),
        spatial_features={
            **features.feature_values,
            "normalized_inputs": components,
        },
        model_version=config.model_version,
        calibration_applied=calibration is not None,
        calibration_weight=calibration_weight,
        calibration_anchor_score=calibration.anchor_score if calibration is not None else None,
    )


def build_noise_segments_document(
    *,
    routes_path: Path,
    config_path: Path,
    spatial_features_path: Path | None = None,
    calibration_path: Path | None = None,
    pm25_grid_path: Path | None = None,
    target_length_m: float = 100.0,
) -> dict[str, object]:
    """读取现有路线并生成可 JSON 序列化的路线段噪声风险文档。"""

    config = load_noise_model_config(config_path)
    calibration = (
        load_noise_calibration(calibration_path, config) if calibration_path is not None else None
    )
    segments = load_route_segments(routes_path, target_length_m=target_length_m)
    if pm25_grid_path is not None:
        segments = assign_pm25_grids(segments, pm25_grid_path)
    catalog = (
        load_spatial_feature_catalog(spatial_features_path)
        if spatial_features_path is not None
        else None
    )
    records: list[dict[str, object]] = []
    for segment in segments:
        features = extract_segment_features(segment, catalog)
        assessment = score_noise_segment(features, config, calibration)
        record = assessment.to_dict()
        record.update(
            {
                "segment_index": segment.segment_index,
                "length_m": segment.length_m,
                "midpoint_wgs84": {
                    "longitude": segment.midpoint_wgs84[0],
                    "latitude": segment.midpoint_wgs84[1],
                },
                "pm25_grid_id": segment.pm25_grid_id,
                "pm25_grid_distance_m": segment.pm25_grid_distance_m,
                "pm25_grid_source": segment.pm25_grid_source,
            }
        )
        records.append(record)
    route_count = len({segment.route_id for segment in segments})
    partial_count = sum(record["status"] == "partial" for record in records)
    return {
        "schema_version": "1.0",
        "dataset_type": "noise_segment_risk",
        "model_version": config.model_version,
        "status": "partial" if partial_count else "ok",
        "estimated": True,
        "spatial_scale": f"route_segments_approximately_{target_length_m:g}m",
        "analysis_crs": "EPSG:32651",
        "routes_source": str(routes_path.resolve()),
        "spatial_features_source": (
            str(spatial_features_path.resolve()) if spatial_features_path is not None else None
        ),
        "config_source": str(config_path.resolve()),
        "calibration_status": "applied" if calibration is not None else "not_applied",
        "calibration_source": (str(calibration.source_path) if calibration is not None else None),
        "calibration_observation_count": (
            calibration.observation_count if calibration is not None else 0
        ),
        "route_count": route_count,
        "segment_count": len(records),
        "partial_segment_count": partial_count,
        "limitations": [
            "risk proxy derived from static spatial features and route metadata",
            "missing local spatial layers lower status and confidence",
            "field measurements are required before adding sound-level estimates",
            "district observations calibrate the overall score scale; local ordering remains proxy-based",
        ],
        "segments": records,
    }


def _risk_level(score: float, config: NoiseModelConfig) -> str:
    if score <= config.low_max:
        return "low"
    if score <= config.medium_max:
        return "medium"
    return "high"


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise NoiseModelError(f"{label}需为对象")
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _float_mapping(value: object, label: str) -> dict[str, float]:
    mapping = _mapping(value, label)
    return {name: _number(item, f"{label}.{name}") for name, item in mapping.items()}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NoiseModelError(f"{label}需为数值")
    result = float(value)
    if not math.isfinite(result):
        raise NoiseModelError(f"{label}需为有限数值")
    return result


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NoiseModelError(f"{label}需为整数")
    return value


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


__all__ = [
    "NoiseAssessment",
    "NoiseCalibration",
    "NoiseModelConfig",
    "NoiseModelError",
    "build_noise_segments_document",
    "load_noise_calibration",
    "load_noise_model_config",
    "score_noise_segment",
]
