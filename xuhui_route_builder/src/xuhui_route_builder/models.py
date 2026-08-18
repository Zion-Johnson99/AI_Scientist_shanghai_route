from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


RouteMode = Literal["walk", "run", "bike", "bike_assist", "access"]
AccessMode = Literal["walk", "bike", "transit", "drive"]
RouteShape = Literal["one_way", "strict_loop"]
GeometryAction = Literal["regenerate", "preserve"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoordinatePair(StrictModel):
    lng_gcj02: float
    lat_gcj02: float
    lng_wgs84: float
    lat_wgs84: float

    def gcj02_list(self) -> list[float]:
        return [self.lng_gcj02, self.lat_gcj02]


class EntryPoint(StrictModel):
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


class RouteNode(StrictModel):
    node_name: str
    node_type: str | None = None
    source_url: str | None = None
    poi_id: str | None = None
    lng_gcj02: float | None = Field(default=None, ge=-180, le=180)
    lat_gcj02: float | None = Field(default=None, ge=-90, le=90)
    lng_wgs84: float | None = Field(default=None, ge=-180, le=180)
    lat_wgs84: float | None = Field(default=None, ge=-90, le=90)

    @model_validator(mode="after")
    def require_complete_location(self) -> RouteNode:
        has_gcj_lng = self.lng_gcj02 is not None
        has_gcj_lat = self.lat_gcj02 is not None
        if has_gcj_lng != has_gcj_lat:
            raise ValueError("GCJ02 coordinates must be a complete pair")
        has_wgs_lng = self.lng_wgs84 is not None
        has_wgs_lat = self.lat_wgs84 is not None
        if has_wgs_lng != has_wgs_lat:
            raise ValueError("WGS84 coordinates must be a complete pair")
        if not self.poi_id and not (has_gcj_lng and has_gcj_lat):
            raise ValueError("RouteNode requires poi_id or complete GCJ02 coordinates")
        return self


class RouteLocation(StrictModel):
    name: str
    location_type: str
    lng_gcj02: float = Field(ge=-180, le=180)
    lat_gcj02: float = Field(ge=-90, le=90)
    source_url: str
    poi_id: str | None = None

    @field_validator("source_url")
    @classmethod
    def require_https_source(cls, value: str) -> str:
        HttpUrl(value)
        return value


class RouteSeed(StrictModel):
    seed_id: str
    route_name: str
    route_mode: RouteMode
    route_shape: RouteShape
    distance_level: str
    target_distance_m: int
    region_zone: str
    start_hint: str
    end_hint: str
    start_location: RouteLocation
    end_location: RouteLocation
    waypoint_hints: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reason: str
    source_name: str
    source_url: str
    source_accessed_at: date
    confidence: str
    ordered_nodes: list[RouteNode] = Field(default_factory=list)
    allowed_modes: list[RouteMode] = Field(default_factory=list)
    source_level: Literal["A", "B", "C"] = "C"
    evidence_note: str = ""
    access_restrictions: list[str] = Field(default_factory=list)
    amenity_ids: list[str]
    geometry_action: GeometryAction

    @field_validator("source_url")
    @classmethod
    def require_https_source(cls, value: str) -> str:
        HttpUrl(value)
        return value

    @model_validator(mode="after")
    def require_complete_structured_route(self) -> RouteSeed:
        if not self.ordered_nodes:
            if self.allowed_modes:
                raise ValueError("partial RouteSeed cannot have allowed_modes without ordered_nodes")
            return self
        if len(self.ordered_nodes) < 2:
            raise ValueError("ordered_nodes must contain at least two nodes")
        if not self.allowed_modes or self.route_mode not in self.allowed_modes:
            raise ValueError("allowed_modes must contain route_mode")
        if not _locations_match_node(self.start_location, self.ordered_nodes[0]):
            raise ValueError("start_location must match the first ordered node")
        if not _locations_match_node(self.end_location, self.ordered_nodes[-1]):
            raise ValueError("end_location must match the last ordered node")
        same_endpoints = _same_location(self.start_location, self.end_location)
        if self.route_shape == "strict_loop" and not same_endpoints:
            raise ValueError("strict_loop requires one shared start and end location")
        if self.route_shape == "one_way" and same_endpoints:
            raise ValueError("one_way requires distinct start and end locations")
        return self


class DirectionPath(StrictModel):
    distance_m: int
    duration_s: int
    polyline_gcj02: list[str]
    road_names: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class CandidateRoute(StrictModel):
    route_id: str
    route_name: str
    route_mode: RouteMode
    route_shape: RouteShape
    target_distance_m: int
    actual_distance_m: int
    duration_s: int
    start_entry_id: str
    end_entry_id: str
    start_location: RouteLocation
    end_location: RouteLocation
    ordered_nodes: list[RouteNode]
    amenity_ids: list[str]
    region_zone: str
    polyline_gcj02: list[CoordinatePair]
    tags: list[str] = Field(default_factory=list)
    source_method: str
    road_names: list[str] = Field(default_factory=list)
    turn_count: int = 0
    route_inside_ratio: float | None = None
    future_score: float | None = None
    score_note: str = "后续评分入口：当前阶段只展示路线标签，暂不计算 PM2.5、噪声、花粉或综合暴露评分。"
    source_name: str = ""
    source_url: str = ""
    source_accessed_at: date | None = None
    confidence: str = "中"
    distance_error_m: int = 0
    loop_flag: bool = False
    feature_tags: list[str] = Field(default_factory=list)
    candidate_rank: str = "candidate"
    geometry_source: Literal["not_generated", "amap_direction", "audited_import"] = "not_generated"
    geometry_status: Literal["not_generated", "complete", "partial", "failed"] = "not_generated"
    validation_status: Literal["pending", "accepted", "needs_review", "rejected"] = "pending"
    snap_ratio: float | None = Field(default=None, ge=0, le=1)
    network_source: str | None = None
    verified_at: datetime | None = None
    review_note: str = ""
    raw_response_paths: list[str] = Field(default_factory=list)
    source_level: Literal["A", "B", "C"] = "C"
    waypoint_names: list[str] = Field(default_factory=list)
    nearby_pois: list[dict[str, Any]] = Field(default_factory=list)
    preference_hits: list[str] = Field(default_factory=list)

    def is_publishable(self) -> bool:
        distinct_points = {(point.lng_gcj02, point.lat_gcj02) for point in self.polyline_gcj02}
        verified_with_timezone = self.verified_at is not None and self.verified_at.utcoffset() is not None
        has_common_evidence = (
            self.validation_status == "accepted"
            and self.geometry_source in {"amap_direction", "audited_import"}
            and self.geometry_status == "complete"
            and len(distinct_points) >= 2
            and bool(self.waypoint_names and self.waypoint_names[0].strip())
            and self.source_accessed_at is not None
            and self.snap_ratio is not None
            and self.snap_ratio >= 0.98
            and bool(self.network_source and self.network_source.strip())
            and verified_with_timezone
            and bool(self.review_note.strip())
        )
        if not has_common_evidence:
            return False
        return self.geometry_source != "amap_direction" or bool(self.raw_response_paths)

    @model_validator(mode="after")
    def validate_accepted_route(self) -> CandidateRoute:
        if self.validation_status != "accepted":
            return self
        if self.geometry_source not in {"amap_direction", "audited_import"}:
            raise ValueError("accepted route requires approved geometry_source")
        if self.geometry_status != "complete":
            raise ValueError("accepted route requires geometry_status=complete")
        if len({(point.lng_gcj02, point.lat_gcj02) for point in self.polyline_gcj02}) < 2:
            raise ValueError("accepted route polyline_gcj02 requires two distinct coordinates")
        if self.snap_ratio is None or self.snap_ratio < 0.98:
            raise ValueError("accepted route requires snap_ratio >= 0.98")
        if not self.network_source or not self.network_source.strip():
            raise ValueError("accepted route requires network_source")
        if self.verified_at is None or self.verified_at.utcoffset() is None:
            raise ValueError("accepted route requires timezone-aware verified_at")
        if not self.review_note.strip():
            raise ValueError("accepted route requires review_note")
        if self.geometry_source == "amap_direction" and not self.raw_response_paths:
            raise ValueError("amap_direction route requires raw_response_paths")
        return self


def _same_location(first: RouteLocation, second: RouteLocation) -> bool:
    return (
        first.name == second.name
        and abs(first.lng_gcj02 - second.lng_gcj02) <= 1e-6
        and abs(first.lat_gcj02 - second.lat_gcj02) <= 1e-6
    )


def _locations_match_node(location: RouteLocation, node: RouteNode) -> bool:
    if node.lng_gcj02 is None or node.lat_gcj02 is None:
        return location.name == node.node_name
    return (
        location.name == node.node_name
        and abs(location.lng_gcj02 - node.lng_gcj02) <= 1e-6
        and abs(location.lat_gcj02 - node.lat_gcj02) <= 1e-6
    )


class PoiPoint(StrictModel):
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


class AccessCase(StrictModel):
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


class AmapRawRecord(StrictModel):
    endpoint: str
    params_hash: str
    status: str | None
    info: str | None
    infocode: str | None
    raw_path: str
    payload: dict[str, Any]
