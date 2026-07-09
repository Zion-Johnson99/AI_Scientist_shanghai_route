from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


RouteMode = Literal["walk", "run", "bike", "bike_assist", "access"]
AccessMode = Literal["walk", "bike", "transit", "drive"]


class CoordinatePair(BaseModel):
    lng_gcj02: float
    lat_gcj02: float
    lng_wgs84: float
    lat_wgs84: float

    def gcj02_list(self) -> list[float]:
        return [self.lng_gcj02, self.lat_gcj02]


class EntryPoint(BaseModel):
    entry_id: str
    entry_name: str
    entry_type: str
    region_zone: str
    lng_gcj02: float
    lat_gcj02: float
    lng_wgs84: float
    lat_wgs84: float
    source_url: str
    confidence: int = Field(ge=1, le=5)
    poi_id: str | None = None
    address: str | None = None
    parent_poi: str | None = None
    navi_poiid: str | None = None
    entr_location: str | None = None
    nearest_metro: str | None = None
    source_api: str | None = None
    default_visible: bool = False


class RouteSeed(BaseModel):
    seed_id: str
    route_name: str
    route_mode: RouteMode
    distance_level: str
    target_distance_m: int
    region_zone: str
    start_hint: str
    end_hint: str
    waypoint_hints: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reason: str
    source_name: str
    source_url: str
    confidence: str

    @field_validator("source_url")
    @classmethod
    def require_https_source(cls, value: str) -> str:
        HttpUrl(value)
        return value


class DirectionPath(BaseModel):
    distance_m: int
    duration_s: int
    polyline_gcj02: list[str]
    road_names: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class CandidateRoute(BaseModel):
    route_id: str
    route_name: str
    route_mode: RouteMode
    target_distance_m: int
    actual_distance_m: int
    duration_s: int
    start_entry_id: str
    end_entry_id: str
    region_zone: str
    polyline_gcj02: list[CoordinatePair]
    tags: list[str] = Field(default_factory=list)
    source_method: str
    road_names: list[str] = Field(default_factory=list)
    turn_count: int = 0
    route_inside_ratio: float | None = None
    future_score: float | None = None
    score_note: str = "后续评分入口：当前阶段只展示路线标签，暂不计算 PM2.5、噪声、花粉或综合暴露评分。"
    raw_response_path: str | None = None
    source_name: str = ""
    source_url: str = ""
    confidence: str = "中"
    distance_error_m: int = 0
    loop_flag: bool = False
    feature_tags: list[str] = Field(default_factory=list)
    candidate_rank: str = "candidate"
    geometry_source: str = "amap_direction"
    source_level: Literal["official", "media", "curated"] = "curated"
    waypoint_names: list[str] = Field(default_factory=list)
    nearby_pois: list[dict[str, Any]] = Field(default_factory=list)
    preference_hits: list[str] = Field(default_factory=list)


class PoiPoint(BaseModel):
    poi_id: str
    poi_name: str
    poi_type: Literal["coffee", "toilet", "convenience", "metro", "park_gate"]
    region_zone: str
    lng_gcj02: float
    lat_gcj02: float
    lng_wgs84: float
    lat_wgs84: float
    source_api: str = "curated_sample"
    default_visible: bool = False


class AccessCase(BaseModel):
    case_id: str
    origin_type: str
    origin_name: str
    origin_lng_gcj02: float
    origin_lat_gcj02: float
    origin_lng_wgs84: float
    origin_lat_wgs84: float
    target_entry_id: str
    access_mode: AccessMode
    distance_m: int
    duration_s: int
    navigation_api: str
    risk_note: str = "接驳段仅记录距离和时间，环境风险评分后续接入。"


class AmapRawRecord(BaseModel):
    endpoint: str
    params_hash: str
    status: str | None
    info: str | None
    infocode: str | None
    raw_path: str
    payload: dict[str, Any]
