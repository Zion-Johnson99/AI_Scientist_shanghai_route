"""华风爱科标准化数据契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, cast

Status = Literal["ok", "partial", "stale", "no_data", "error"]
Confidence = Literal["high", "medium", "low"]


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return MappingProxyType({str(key): _freeze(item) for key, item in mapping.items()})
    if isinstance(value, list):
        items = cast(list[object], value)
        return tuple(_freeze(item) for item in items)
    if isinstance(value, tuple):
        tuple_items = cast(tuple[object, ...], value)
        return tuple(_freeze(item) for item in tuple_items)
    return value


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_jsonable(item) for item in items]
    if isinstance(value, tuple):
        tuple_items = cast(tuple[object, ...], value)
        return [_jsonable(item) for item in tuple_items]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"不支持 JSON 序列化的类型: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class SamplingPoint:
    """用于发现 LocationKey 与数据来源的采样点。"""

    point_id: str
    name: str
    longitude: float
    latitude: float


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    """单条可追踪、可序列化的标准化业务记录。"""

    dataset_type: str
    dataset_role: str
    granularity: str
    location_key: str
    probe_point_ids: tuple[str, ...]
    business_time: str | None
    fetched_at: str
    valid_until: str | None
    status: Status
    source: Mapping[str, object]
    values: Mapping[str, object]
    units: Mapping[str, object]
    completeness: float
    missing_fields: tuple[str, ...]
    raw_data: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe_point_ids", tuple(self.probe_point_ids))
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        object.__setattr__(self, "source", _freeze(self.source))
        object.__setattr__(self, "values", _freeze(self.values))
        object.__setattr__(self, "units", _freeze(self.units))
        object.__setattr__(self, "raw_data", _freeze(self.raw_data))

    def to_dict(self) -> dict[str, object]:
        """返回可直接交给 json.dumps 的普通字典。"""

        return {
            "dataset_type": self.dataset_type,
            "dataset_role": self.dataset_role,
            "granularity": self.granularity,
            "location_key": self.location_key,
            "probe_point_ids": list(self.probe_point_ids),
            "business_time": self.business_time,
            "fetched_at": self.fetched_at,
            "valid_until": self.valid_until,
            "status": self.status,
            "source": _jsonable(self.source),
            "values": _jsonable(self.values),
            "units": _jsonable(self.units),
            "completeness": self.completeness,
            "missing_fields": list(self.missing_fields),
            "raw_data": _jsonable(self.raw_data),
        }


@dataclass(frozen=True, slots=True)
class RouteExposureMetric:
    """单项路线暴露结果及其时空来源。"""

    value: float | None
    unit: str
    source: tuple[str, ...]
    business_time: str | None
    fetched_at: str | None
    expires_at: str | None
    spatial_scale: str
    status: Status
    confidence: Confidence
    estimated: bool
    coverage_ratio: float
    risk_level: str | None = None
    scenarios: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", tuple(self.source))
        if self.scenarios is not None:
            object.__setattr__(self, "scenarios", _freeze(self.scenarios))

    def to_dict(self) -> dict[str, object]:
        """返回可直接交给 json.dumps 的普通字典。"""

        result: dict[str, object] = {
            "value": self.value,
            "unit": self.unit,
            "source": list(self.source),
            "business_time": self.business_time,
            "fetched_at": self.fetched_at,
            "expires_at": self.expires_at,
            "spatial_scale": self.spatial_scale,
            "status": self.status,
            "confidence": self.confidence,
            "estimated": self.estimated,
            "coverage_ratio": self.coverage_ratio,
        }
        if self.risk_level is not None:
            result["risk_level"] = self.risk_level
        if self.scenarios is not None:
            result["scenarios"] = _jsonable(self.scenarios)
        return result


@dataclass(frozen=True, slots=True)
class RouteEnvironmentRecord:
    """按路线汇总的 PM2.5、花粉与噪声暴露契约。"""

    route_id: str
    segment_count: int
    total_length_m: float
    status: Status
    pm2_5: RouteExposureMetric
    pollen_daily: tuple[RouteExposureMetric, ...]
    noise: RouteExposureMetric

    def __post_init__(self) -> None:
        object.__setattr__(self, "pollen_daily", tuple(self.pollen_daily))

    def to_dict(self) -> dict[str, object]:
        """返回可直接交给 json.dumps 的普通字典。"""

        return {
            "route_id": self.route_id,
            "segment_count": self.segment_count,
            "total_length_m": self.total_length_m,
            "status": self.status,
            "pm2_5": self.pm2_5.to_dict(),
            "pollen_daily": [metric.to_dict() for metric in self.pollen_daily],
            "noise": self.noise.to_dict(),
        }


__all__ = [
    "Confidence",
    "NormalizedRecord",
    "RouteEnvironmentRecord",
    "RouteExposureMetric",
    "SamplingPoint",
    "Status",
]
