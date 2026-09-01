"""徐汇约 1 km 网格的日级花粉派生评分。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast
from zoneinfo import ZoneInfo

from weather_api_data.pollen_client import PollenClient, PollenForecastDay

RiskLevel = Literal["low", "medium", "high", "no_data"]
ScoreStatus = Literal["ok", "partial", "no_data"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True, slots=True)
class PollenGridPoint:
    """与 PM2.5 输出一一对应的 WGS84 网格中心。"""

    grid_id: str
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if not self.grid_id.strip():
            raise ValueError("花粉网格 grid_id 不能为空")
        if not -180 <= self.longitude <= 180 or not -90 <= self.latitude <= 90:
            raise ValueError(f"花粉网格 {self.grid_id} 经纬度越界")


@dataclass(frozen=True, slots=True)
class WeatherFactors:
    """计算天气修正所需的和风日级或日内汇总字段。"""

    wind_speed_kph: float | None
    precipitation_mm: float | None
    humidity_percent: float | None

    def __post_init__(self) -> None:
        if self.wind_speed_kph is not None and self.wind_speed_kph < 0:
            raise ValueError("wind_speed_kph 需大于或等于 0")
        if self.precipitation_mm is not None and self.precipitation_mm < 0:
            raise ValueError("precipitation_mm 需大于或等于 0")
        if self.humidity_percent is not None and not 0 <= self.humidity_percent <= 100:
            raise ValueError("humidity_percent 需位于 0 至 100 之间")


@dataclass(frozen=True, slots=True)
class PollenModelConfig:
    """经校验的首版花粉评分参数。"""

    weights: Mapping[str, float]
    weather_weights: Mapping[str, float]
    google_index_max: int
    rain_full_suppression_mm: float
    humidity_high_risk_percent: float
    humidity_low_risk_percent: float
    wind_full_score_kph: float
    medium_threshold: float
    high_threshold: float
    spatial_resolution_m: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(
            self,
            "weather_weights",
            MappingProxyType(dict(self.weather_weights)),
        )


@dataclass(frozen=True, slots=True)
class PollenGridScore:
    """单个网格和业务日期的可序列化派生花粉评分。"""

    grid_id: str
    longitude: float
    latitude: float
    forecast_date: str
    pollen_risk_score: float | None
    risk_level: RiskLevel
    status: ScoreStatus
    source: str
    spatial_resolution_m: int
    confidence: Confidence
    estimated: bool
    components: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))

    def to_dict(self) -> dict[str, object]:
        return {
            "grid_id": self.grid_id,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "forecast_date": self.forecast_date,
            "pollen_risk_score": self.pollen_risk_score,
            "risk_level": self.risk_level,
            "status": self.status,
            "source": self.source,
            "spatial_resolution_m": self.spatial_resolution_m,
            "confidence": self.confidence,
            "estimated": self.estimated,
            "components": dict(self.components),
        }


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} 需为 JSON 对象")
    return cast(Mapping[str, object], value)


def _float(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{context} 需为数值")
    return float(value)


def _int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} 需为整数")
    return value


def _weights(value: object, names: set[str], context: str) -> dict[str, float]:
    raw = _mapping(value, context)
    if set(raw) != names:
        raise ValueError(f"{context} 字段需为 {sorted(names)}")
    result = {name: _float(raw[name], f"{context}.{name}") for name in names}
    if any(weight < 0 for weight in result.values()) or abs(sum(result.values()) - 1.0) > 1e-9:
        raise ValueError(f"{context} 权重需非负且总和为 1")
    return result


def load_pollen_model_config(path: Path) -> PollenModelConfig:
    """读取并严格校验花粉模型 JSON。"""

    try:
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"花粉模型配置无法读取: {path}") from error
    root = _mapping(payload, "花粉模型配置")
    weather = _mapping(root.get("weather"), "weather")
    thresholds = _mapping(root.get("risk_thresholds"), "risk_thresholds")
    model = PollenModelConfig(
        weights=_weights(
            root.get("weights"),
            {"google_background", "weather", "vegetation"},
            "weights",
        ),
        weather_weights=_weights(
            weather.get("weights"),
            {"dryness", "humidity", "wind"},
            "weather.weights",
        ),
        google_index_max=_int(root.get("google_index_max"), "google_index_max"),
        rain_full_suppression_mm=_float(
            weather.get("rain_full_suppression_mm"),
            "weather.rain_full_suppression_mm",
        ),
        humidity_high_risk_percent=_float(
            weather.get("humidity_high_risk_percent"),
            "weather.humidity_high_risk_percent",
        ),
        humidity_low_risk_percent=_float(
            weather.get("humidity_low_risk_percent"),
            "weather.humidity_low_risk_percent",
        ),
        wind_full_score_kph=_float(
            weather.get("wind_full_score_kph"),
            "weather.wind_full_score_kph",
        ),
        medium_threshold=_float(thresholds.get("medium"), "risk_thresholds.medium"),
        high_threshold=_float(thresholds.get("high"), "risk_thresholds.high"),
        spatial_resolution_m=_int(
            root.get("spatial_resolution_m"),
            "spatial_resolution_m",
        ),
    )
    if model.google_index_max <= 0:
        raise ValueError("google_index_max 需大于 0")
    if model.rain_full_suppression_mm <= 0 or model.wind_full_score_kph <= 0:
        raise ValueError("weather 雨量和风速标尺需大于 0")
    if not (0 <= model.humidity_high_risk_percent < model.humidity_low_risk_percent <= 100):
        raise ValueError("weather 湿度阈值顺序无效")
    if not 0 < model.medium_threshold < model.high_threshold <= 100:
        raise ValueError("risk_thresholds 顺序无效")
    if model.spatial_resolution_m <= 0:
        raise ValueError("spatial_resolution_m 需大于 0")
    return model


def load_pollen_grid_points(path: Path, *, expected_count: int = 54) -> tuple[PollenGridPoint, ...]:
    """从 pm25_grid_latest.json 读取稳定网格编号与 WGS84 中心。"""

    try:
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"PM2.5 网格文件无法读取: {path}") from error
    root = _mapping(payload, "PM2.5 网格文件")
    raw_grids = root.get("grids")
    if not isinstance(raw_grids, list):
        raise TypeError("PM2.5 网格文件缺少 grids 数组")
    points: list[PollenGridPoint] = []
    for index, raw_grid in enumerate(cast(list[object], raw_grids), start=1):
        grid = _mapping(raw_grid, f"grids[{index - 1}]")
        grid_id = grid.get("grid_id")
        if not isinstance(grid_id, str):
            raise TypeError(f"grids[{index - 1}].grid_id 需为字符串")
        points.append(
            PollenGridPoint(
                grid_id=grid_id,
                longitude=_float(grid.get("longitude"), f"网格 {grid_id} longitude"),
                latitude=_float(grid.get("latitude"), f"网格 {grid_id} latitude"),
            )
        )
    if len(points) != expected_count:
        raise ValueError(f"PM2.5 网格数量需为 {expected_count}，当前为 {len(points)}")
    _validate_unique_points(points)
    return tuple(points)


def fetch_pollen_grid_forecasts(
    client: PollenClient,
    points: Sequence[PollenGridPoint],
    *,
    days: int = 5,
) -> dict[str, tuple[PollenForecastDay, ...]]:
    """按稳定网格顺序查询 Google。终止错误直接停止后续点位。"""

    _validate_unique_points(points)
    return {
        point.grid_id: client.lookup(
            latitude=point.latitude,
            longitude=point.longitude,
            days=days,
        ).days
        for point in points
    }


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _weather_score(weather: WeatherFactors | None, model: PollenModelConfig) -> float | None:
    if weather is None or any(
        value is None
        for value in (
            weather.wind_speed_kph,
            weather.precipitation_mm,
            weather.humidity_percent,
        )
    ):
        return None
    wind_speed = cast(float, weather.wind_speed_kph)
    precipitation = cast(float, weather.precipitation_mm)
    humidity = cast(float, weather.humidity_percent)
    dryness = _clamp(100.0 * (1.0 - precipitation / model.rain_full_suppression_mm))
    humidity_score = _clamp(
        100.0
        * (model.humidity_low_risk_percent - humidity)
        / (model.humidity_low_risk_percent - model.humidity_high_risk_percent)
    )
    wind_score = _clamp(100.0 * wind_speed / model.wind_full_score_kph)
    return sum(
        (
            dryness * model.weather_weights["dryness"],
            humidity_score * model.weather_weights["humidity"],
            wind_score * model.weather_weights["wind"],
        )
    )


def _risk_level(score: float | None, model: PollenModelConfig) -> RiskLevel:
    if score is None:
        return "no_data"
    if score >= model.high_threshold:
        return "high"
    if score >= model.medium_threshold:
        return "medium"
    return "low"


def _validate_unique_points(points: Sequence[PollenGridPoint]) -> None:
    seen: set[str] = set()
    for point in points:
        if point.grid_id in seen:
            raise ValueError(f"花粉网格编号重复: {point.grid_id}")
        seen.add(point.grid_id)


def derive_pollen_grid_scores(
    points: Sequence[PollenGridPoint],
    *,
    forecasts_by_grid: Mapping[str, Sequence[PollenForecastDay]],
    weather_by_date: Mapping[str, WeatherFactors],
    vegetation_by_grid: Mapping[str, float],
    model: PollenModelConfig,
) -> tuple[PollenGridScore, ...]:
    """融合 Google 背景、和风天气和植被代理。缺项时按可用权重归一。"""

    _validate_unique_points(points)
    for grid_id, ratio in vegetation_by_grid.items():
        if not 0 <= ratio <= 1:
            raise ValueError(f"vegetation_by_grid 中 {grid_id} 需位于 0 至 1 之间")

    dates = set(weather_by_date)
    for forecast_days in forecasts_by_grid.values():
        dates.update(day.forecast_date for day in forecast_days)

    records: list[PollenGridScore] = []
    for point in points:
        point_forecasts = {
            day.forecast_date: day for day in forecasts_by_grid.get(point.grid_id, ())
        }
        for forecast_date in sorted(dates):
            day = point_forecasts.get(forecast_date)
            grass = day.pollen_types.get("GRASS") if day is not None else None
            tree = day.pollen_types.get("TREE") if day is not None else None
            weed = day.pollen_types.get("WEED") if day is not None else None
            google_score = (
                _clamp(100.0 * grass.index_value / model.google_index_max)
                if grass is not None and grass.index_value is not None
                else None
            )
            weather_score = _weather_score(weather_by_date.get(forecast_date), model)
            vegetation_ratio = vegetation_by_grid.get(point.grid_id)
            vegetation_score = 100.0 * vegetation_ratio if vegetation_ratio is not None else None
            components = {
                "google_background_score": google_score,
                "weather_score": round(weather_score, 2) if weather_score is not None else None,
                "vegetation_score": (
                    round(vegetation_score, 2) if vegetation_score is not None else None
                ),
                "grass_index_value": grass.index_value if grass is not None else None,
                "grass_index_code": grass.index_code if grass is not None else None,
                "grass_status": grass.status if grass is not None else "no_data",
                "tree_index_value": tree.index_value if tree is not None else None,
                "tree_status": tree.status if tree is not None else "no_data",
                "weed_index_value": weed.index_value if weed is not None else None,
                "weed_status": weed.status if weed is not None else "no_data",
            }
            weighted_values = (
                ("google_background", google_score),
                ("weather", weather_score),
                ("vegetation", vegetation_score),
            )
            available = [(name, value) for name, value in weighted_values if value is not None]
            if available:
                available_weight = sum(model.weights[name] for name, _ in available)
                score = round(
                    sum(model.weights[name] * value for name, value in available)
                    / available_weight,
                    2,
                )
                status: ScoreStatus = "ok" if len(available) == 3 else "partial"
            else:
                score = None
                status = "no_data"
            if len(available) == 3:
                confidence: Confidence = "high"
            elif google_score is not None:
                confidence = "medium"
            else:
                confidence = "low"
            source_parts: list[str] = []
            if google_score is not None:
                source_parts.append("google_pollen")
            if weather_score is not None:
                source_parts.append("qweather")
            if vegetation_score is not None:
                source_parts.append("vegetation_proxy")
            records.append(
                PollenGridScore(
                    grid_id=point.grid_id,
                    longitude=point.longitude,
                    latitude=point.latitude,
                    forecast_date=forecast_date,
                    pollen_risk_score=score,
                    risk_level=_risk_level(score, model),
                    status=status,
                    source="+".join(source_parts) if source_parts else "no_data",
                    spatial_resolution_m=model.spatial_resolution_m,
                    confidence=confidence,
                    estimated=True,
                    components=components,
                )
            )
    return tuple(records)


def build_pollen_grid_document(
    scores: Sequence[PollenGridScore],
    *,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """生成供导出器或路线聚合器直接消费的完整 JSON 文档。"""

    generated = generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at 需包含时区")
    local_date = generated.astimezone(ZoneInfo("Asia/Shanghai")).date()
    window_end = local_date + timedelta(days=4)
    filtered_scores = tuple(
        score for score in scores if local_date <= _iso_date(score.forecast_date) <= window_end
    )
    statuses = {score.status for score in filtered_scores}
    if not filtered_scores or statuses == {"no_data"}:
        status: ScoreStatus = "no_data"
    elif statuses == {"ok"}:
        status = "ok"
    else:
        status = "partial"
    resolutions = {score.spatial_resolution_m for score in filtered_scores}
    resolution = next(iter(resolutions)) if len(resolutions) == 1 else None
    preferred_sources = ("google_pollen", "qweather", "vegetation_proxy")
    source_tokens = {
        token
        for score in filtered_scores
        for token in score.source.split("+")
        if token != "no_data"
    }
    source = "+".join(token for token in preferred_sources if token in source_tokens)
    return {
        "schema_version": "1.0",
        "dataset_type": "pollen_grid_scores",
        "generated_at": generated.isoformat(),
        "grid_count": len({score.grid_id for score in filtered_scores}),
        "forecast_date_count": len({score.forecast_date for score in filtered_scores}),
        "status": status,
        "spatial_resolution_m": resolution,
        "estimated": True,
        "source": source or "no_data",
        "attribution": "Includes data from Google Maps"
        if "google_pollen" in source_tokens
        else None,
        "grid_scores": [score.to_dict() for score in filtered_scores],
    }


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"forecast_date 需为 ISO 日期: {value}") from error


def collect_pollen_grid_document(
    *,
    client: PollenClient,
    pm25_grid_path: Path,
    model_path: Path,
    weather_by_date: Mapping[str, WeatherFactors],
    vegetation_by_grid: Mapping[str, float],
    days: int = 5,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """读取 54 格、逐格查询并返回完整派生文档。文件写出交给导出层。"""

    points = load_pollen_grid_points(pm25_grid_path)
    forecasts = fetch_pollen_grid_forecasts(client, points, days=days)
    scores = derive_pollen_grid_scores(
        points,
        forecasts_by_grid=forecasts,
        weather_by_date=weather_by_date,
        vegetation_by_grid=vegetation_by_grid,
        model=load_pollen_model_config(model_path),
    )
    return build_pollen_grid_document(scores, generated_at=generated_at)


__all__ = [
    "PollenGridPoint",
    "PollenGridScore",
    "PollenModelConfig",
    "WeatherFactors",
    "build_pollen_grid_document",
    "collect_pollen_grid_document",
    "derive_pollen_grid_scores",
    "fetch_pollen_grid_forecasts",
    "load_pollen_grid_points",
    "load_pollen_model_config",
]
