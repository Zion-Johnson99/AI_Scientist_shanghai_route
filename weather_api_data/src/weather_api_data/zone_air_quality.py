"""徐汇区空气质量分区与行政区浓度融合。"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Literal, TypedDict, cast

from weather_api_data.models import SamplingPoint

_EXPECTED_ZONE_COUNT = 11
_EXPECTED_STRATEGY_COUNTS = {
    "qweather_direct": 6,
    "district_blend": 3,
    "shanghai_station": 2,
}
_STATION_IDS = {80, 207}
_COMMON_ZONE_KEYS = {"zone_id", "name", "anchor", "source_strategy"}
_ANCHOR_KEYS = {"longitude", "latitude", "crs"}
_BLEND_COMPONENT_KEYS = {"district", "point_id", "weight"}
_TOP_LEVEL_KEYS = {"probe_points", "zones"}
_PROBE_POINT_KEYS = {"point_id", "name", "longitude", "latitude", "district"}
_POLLUTANTS = (
    "pm2_5_ug_m3",
    "pm10_ug_m3",
    "ozone_ug_m3",
    "nitrogen_dioxide_ug_m3",
    "sulfur_dioxide_ug_m3",
    "carbon_monoxide_mg_m3",
)

SourceStrategy = Literal["qweather_direct", "district_blend", "shanghai_station"]
AqiCalculator = Callable[[dict[str, float]], object]


class BlendResult(TypedDict):
    """空气质量浓度融合结果。"""

    status: Literal["ok", "partial", "no_data"]
    values: dict[str, object]
    components: list[dict[str, object]]
    missing_components: list[str]
    is_estimated: bool


class AirQualityZoneError(ValueError):
    """空气质量分区配置或输入违反契约。"""


def load_air_quality_zones(
    path: str | Path,
    *,
    valid_point_ids: Collection[str] | None = None,
) -> tuple[dict[str, object], ...]:
    """加载并严格校验 11 个空气质量分区。"""

    config_path = Path(path)
    try:
        payload: object = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AirQualityZoneError(f"分区配置读取失败: {config_path.name}") from error
    if not isinstance(payload, dict):
        raise AirQualityZoneError("分区配置顶层字段应为 probe_points 和 zones")
    config = cast(dict[str, object], payload)
    if set(config) != _TOP_LEVEL_KEYS:
        raise AirQualityZoneError("分区配置顶层字段应为 probe_points 和 zones")
    raw_zones = config["zones"]
    if not isinstance(raw_zones, list):
        raise AirQualityZoneError("分区配置 zones 应为数组")
    rows = cast(list[object], raw_zones)
    if len(rows) != _EXPECTED_ZONE_COUNT:
        raise AirQualityZoneError(f"分区数量应为 {_EXPECTED_ZONE_COUNT}")

    sampling_point_ids = (
        set(valid_point_ids)
        if valid_point_ids is not None
        else _load_point_ids(config_path.with_name("xuhui_sampling_points.json"))
    )
    external_point_ids = _validate_probe_points(config["probe_points"], sampling_point_ids)
    known_points = sampling_point_ids | external_point_ids
    zones: list[dict[str, object]] = []
    seen_zone_ids: set[str] = set()
    strategies: list[str] = []
    station_ids: set[int] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AirQualityZoneError(f"分区第 {index} 项应为对象")
        zone = cast(dict[str, object], row)
        zone_id = _nonempty_string(zone.get("zone_id"), f"分区第 {index} 项 zone_id")
        if zone_id in seen_zone_ids:
            raise AirQualityZoneError(f"分区 ID 重复: {zone_id}")
        seen_zone_ids.add(zone_id)
        _nonempty_string(zone.get("name"), f"分区第 {index} 项 name")
        _validate_anchor(zone.get("anchor"), index)

        strategy = _strategy(zone.get("source_strategy"), index)
        strategies.append(strategy)
        if strategy == "qweather_direct":
            _require_exact_keys(zone, _COMMON_ZONE_KEYS | {"probe_point_ids"}, index)
            _validate_point_references(zone.get("probe_point_ids"), known_points, index)
        elif strategy == "district_blend":
            _require_exact_keys(zone, _COMMON_ZONE_KEYS | {"blend_components"}, index)
            _validate_blend_components(zone.get("blend_components"), known_points, index)
        else:
            _require_exact_keys(zone, _COMMON_ZONE_KEYS | {"station_id"}, index)
            station_id = zone.get("station_id")
            if isinstance(station_id, bool) or not isinstance(station_id, int):
                raise AirQualityZoneError(f"分区第 {index} 项 station_id 应为整数")
            if station_id not in _STATION_IDS:
                raise AirQualityZoneError(f"分区第 {index} 项 station_id 非法: {station_id}")
            if station_id in station_ids:
                raise AirQualityZoneError(f"监测站 ID 重复: {station_id}")
            station_ids.add(station_id)
        zones.append(deepcopy(zone))

    if Counter(strategies) != Counter(_EXPECTED_STRATEGY_COUNTS):
        raise AirQualityZoneError("分区 source_strategy 数量不符合 6/3/2 契约")
    if station_ids != _STATION_IDS:
        raise AirQualityZoneError("监测站配置应精确包含 80 和 207")
    return tuple(zones)


def load_air_quality_probe_points(path: str | Path) -> tuple[SamplingPoint, ...]:
    """加载且校验跨行政区融合所需的坐标探针。"""

    config_path = Path(path)
    load_air_quality_zones(config_path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AirQualityZoneError(f"分区配置读取失败: {config_path.name}") from error
    config = cast(dict[str, object], payload)
    rows = cast(list[object], config["probe_points"])
    points: list[SamplingPoint] = []
    for row in rows:
        item = cast(dict[str, object], row)
        points.append(
            SamplingPoint(
                point_id=cast(str, item["point_id"]),
                name=cast(str, item["name"]),
                longitude=float(cast(float, item["longitude"])),
                latitude=float(cast(float, item["latitude"])),
            )
        )
    return tuple(points)


def resolve_air_quality_zone(
    longitude: float,
    latitude: float,
    zones: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """按 WGS84 锚点的大圆距离返回最近分区。"""

    valid_longitude = _coordinate(longitude, -180.0, 180.0, "longitude")
    valid_latitude = _coordinate(latitude, -90.0, 90.0, "latitude")
    if not zones:
        raise AirQualityZoneError("分区列表为空")

    nearest = min(
        zones,
        key=lambda zone: _haversine_distance(
            valid_longitude,
            valid_latitude,
            *_anchor_coordinates(zone),
        ),
    )
    return deepcopy(dict(nearest))


def blend_pollutants(
    component_records: Mapping[str, Mapping[str, object] | None],
    components: Sequence[Mapping[str, object]],
    *,
    aqi_calculator: AqiCalculator | None = None,
) -> BlendResult:
    """按配置权重融合六项浓度。AQI 由调用方注入的函数重算。"""

    parsed_components = _parse_runtime_components(components)
    available: list[tuple[str, str, float, Mapping[str, object]]] = []
    missing: list[str] = []
    for district, point_id, weight in parsed_components:
        record = component_records.get(point_id)
        if record is None:
            missing.append(point_id)
            continue
        available.append((district, point_id, weight, record))

    if not available:
        return {
            "status": "no_data",
            "values": {},
            "components": [],
            "missing_components": missing,
            "is_estimated": True,
        }

    values: dict[str, object] = {}
    for pollutant in _POLLUTANTS:
        weighted_values: list[tuple[float, float]] = []
        for _, point_id, weight, record in available:
            record_values = record.get("values")
            if not isinstance(record_values, Mapping):
                raise AirQualityZoneError(f"融合来源 {point_id} 的 values 应为对象")
            typed_values = cast(Mapping[str, object], record_values)
            raw_value = typed_values.get(pollutant)
            if raw_value is None:
                continue
            value = _finite_number(raw_value, f"融合来源 {point_id} 的 {pollutant}")
            weighted_values.append((weight, value))
        if weighted_values:
            weight_sum = sum(weight for weight, _ in weighted_values)
            values[pollutant] = (
                sum(weight * value for weight, value in weighted_values) / weight_sum
            )

    if aqi_calculator is not None and values:
        concentrations = {
            key: cast(float, value) for key, value in values.items() if key in _POLLUTANTS
        }
        values["aqi"] = aqi_calculator(concentrations)

    retained_components: list[dict[str, object]] = [
        {
            "district": district,
            "point_id": point_id,
            "weight": weight,
            "record": deepcopy(dict(record)),
        }
        for district, point_id, weight, record in available
    ]
    return {
        "status": "partial" if missing else "ok",
        "values": values,
        "components": retained_components,
        "missing_components": missing,
        "is_estimated": True,
    }


def _load_point_ids(path: Path) -> set[str]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AirQualityZoneError(f"采样点配置读取失败: {path.name}") from error
    if not isinstance(payload, list):
        raise AirQualityZoneError("采样点配置顶层应为数组")
    point_ids: set[str] = set()
    for index, row in enumerate(cast(list[object], payload)):
        if not isinstance(row, dict):
            raise AirQualityZoneError(f"采样点第 {index} 项应为对象")
        item = cast(dict[str, object], row)
        point_id = _nonempty_string(item.get("point_id"), f"采样点第 {index} 项 point_id")
        if point_id in point_ids:
            raise AirQualityZoneError(f"采样点 ID 重复: {point_id}")
        point_ids.add(point_id)
    return point_ids


def _validate_probe_points(value: object, sampling_point_ids: set[str]) -> set[str]:
    if not isinstance(value, list):
        raise AirQualityZoneError("分区配置 probe_points 应为数组")
    probe_ids: set[str] = set()
    for index, row in enumerate(cast(list[object], value)):
        if not isinstance(row, dict):
            raise AirQualityZoneError(f"外区探针第 {index} 项字段与契约不一致")
        item = cast(dict[str, object], row)
        if set(item) != _PROBE_POINT_KEYS:
            raise AirQualityZoneError(f"外区探针第 {index} 项字段与契约不一致")
        point_id = _nonempty_string(item.get("point_id"), f"外区探针第 {index} 项 point_id")
        _nonempty_string(item.get("name"), f"外区探针第 {index} 项 name")
        _nonempty_string(item.get("district"), f"外区探针第 {index} 项 district")
        _coordinate(item.get("longitude"), -180.0, 180.0, "probe.longitude")
        _coordinate(item.get("latitude"), -90.0, 90.0, "probe.latitude")
        if point_id in sampling_point_ids or point_id in probe_ids:
            raise AirQualityZoneError(f"探针 point_id 重复: {point_id}")
        probe_ids.add(point_id)
    return probe_ids


def _validate_anchor(value: object, index: int) -> None:
    if not isinstance(value, dict):
        raise AirQualityZoneError(f"分区第 {index} 项 anchor 应为对象")
    anchor = cast(dict[str, object], value)
    if set(anchor) != _ANCHOR_KEYS:
        raise AirQualityZoneError(f"分区第 {index} 项 anchor 字段与契约不一致")
    if anchor.get("crs") != "WGS84":
        raise AirQualityZoneError(f"分区第 {index} 项 anchor.crs 应为 WGS84")
    _coordinate(anchor.get("longitude"), -180.0, 180.0, "anchor.longitude")
    _coordinate(anchor.get("latitude"), -90.0, 90.0, "anchor.latitude")


def _strategy(value: object, index: int) -> SourceStrategy:
    if value not in _EXPECTED_STRATEGY_COUNTS:
        raise AirQualityZoneError(f"分区第 {index} 项 source_strategy 非法")
    return cast(SourceStrategy, value)


def _require_exact_keys(zone: Mapping[str, object], expected: set[str], index: int) -> None:
    if set(zone) != expected:
        raise AirQualityZoneError(f"分区第 {index} 项字段与策略契约不一致")


def _validate_point_references(
    value: object,
    known_points: set[str],
    index: int,
) -> None:
    if not isinstance(value, list) or not value:
        raise AirQualityZoneError(f"分区第 {index} 项 probe_point_ids 应为非空数组")
    items = cast(list[object], value)
    point_ids = [_nonempty_string(item, "probe_point_ids 项") for item in items]
    if len(point_ids) != len(set(point_ids)):
        raise AirQualityZoneError(f"分区第 {index} 项 probe_point_ids 重复")
    _require_known_points(point_ids, known_points)


def _validate_blend_components(
    value: object,
    known_points: set[str],
    index: int,
) -> None:
    if not isinstance(value, list):
        raise AirQualityZoneError(f"分区第 {index} 项 blend_components 应精确包含两项")
    components = cast(list[object], value)
    if len(components) != 2:
        raise AirQualityZoneError(f"分区第 {index} 项 blend_components 应精确包含两项")
    point_ids: list[str] = []
    districts: list[str] = []
    weights: list[float] = []
    for component_index, component in enumerate(components):
        if not isinstance(component, dict):
            raise AirQualityZoneError(
                f"分区第 {index} 项 blend_components[{component_index}] 字段非法"
            )
        item = cast(dict[str, object], component)
        if set(item) != _BLEND_COMPONENT_KEYS:
            raise AirQualityZoneError(
                f"分区第 {index} 项 blend_components[{component_index}] 字段非法"
            )
        districts.append(_nonempty_string(item.get("district"), "blend district"))
        point_ids.append(_nonempty_string(item.get("point_id"), "blend point_id"))
        weight = _finite_number(item.get("weight"), "blend weight")
        if weight <= 0.0:
            raise AirQualityZoneError("融合权重应大于 0")
        weights.append(weight)
    if len(districts) != len(set(districts)):
        raise AirQualityZoneError(f"分区第 {index} 项融合行政区重复")
    if len(point_ids) != len(set(point_ids)):
        raise AirQualityZoneError(f"分区第 {index} 项融合采样点重复")
    if not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise AirQualityZoneError("融合权重之和应为 1")
    _require_known_points(point_ids, known_points)


def _parse_runtime_components(
    components: Sequence[Mapping[str, object]],
) -> list[tuple[str, str, float]]:
    if not components:
        raise AirQualityZoneError("融合 components 为空")
    parsed: list[tuple[str, str, float]] = []
    for index, component in enumerate(components):
        if set(component) != _BLEND_COMPONENT_KEYS:
            raise AirQualityZoneError(f"融合 components[{index}] 字段非法")
        district = _nonempty_string(component.get("district"), "融合 district")
        point_id = _nonempty_string(component.get("point_id"), "融合 point_id")
        weight = _finite_number(component.get("weight"), "融合 weight")
        if weight <= 0.0:
            raise AirQualityZoneError("融合权重应大于 0")
        parsed.append((district, point_id, weight))
    if not math.isclose(sum(item[2] for item in parsed), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise AirQualityZoneError("融合权重之和应为 1")
    return parsed


def _require_known_points(point_ids: Sequence[str], known_points: set[str]) -> None:
    unknown = [point_id for point_id in point_ids if point_id not in known_points]
    if unknown:
        raise AirQualityZoneError(f"引用未知采样点: {', '.join(unknown)}")


def _anchor_coordinates(zone: Mapping[str, object]) -> tuple[float, float]:
    anchor = zone.get("anchor")
    if not isinstance(anchor, Mapping):
        raise AirQualityZoneError("分区 anchor 应为对象")
    typed_anchor = cast(Mapping[str, object], anchor)
    return (
        _coordinate(typed_anchor.get("longitude"), -180.0, 180.0, "anchor.longitude"),
        _coordinate(typed_anchor.get("latitude"), -90.0, 90.0, "anchor.latitude"),
    )


def _haversine_distance(
    longitude: float,
    latitude: float,
    anchor_longitude: float,
    anchor_latitude: float,
) -> float:
    longitude_delta = math.radians(anchor_longitude - longitude)
    latitude_delta = math.radians(anchor_latitude - latitude)
    latitude_radians = math.radians(latitude)
    anchor_latitude_radians = math.radians(anchor_latitude)
    haversine = (
        math.sin(latitude_delta / 2.0) ** 2
        + math.cos(latitude_radians)
        * math.cos(anchor_latitude_radians)
        * math.sin(longitude_delta / 2.0) ** 2
    )
    return 2.0 * math.asin(math.sqrt(haversine))


def _nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AirQualityZoneError(f"{field_name} 应为非空字符串")
    return value


def _coordinate(value: object, minimum: float, maximum: float, field_name: str) -> float:
    number = _finite_number(value, field_name)
    if not minimum <= number <= maximum:
        raise AirQualityZoneError(f"{field_name} 超出 WGS84 合法范围")
    return number


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AirQualityZoneError(f"{field_name} 应为数值")
    number = float(value)
    if not math.isfinite(number):
        raise AirQualityZoneError(f"{field_name} 应为有限数值")
    return number


__all__ = [
    "AirQualityZoneError",
    "BlendResult",
    "blend_pollutants",
    "load_air_quality_probe_points",
    "load_air_quality_zones",
    "resolve_air_quality_zone",
]
