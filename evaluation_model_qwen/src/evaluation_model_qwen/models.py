from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RouteMode = Literal["walk", "run", "bike"]
RouteShapePreference = Literal["any", "one_way", "strict_loop"]
Goal = Literal[
    "balanced",
    "health_environment",
    "distance_training",
    "relax",
    "scenery",
    "family",
    "nearby",
]
Experience = Literal["beginner", "regular", "frequent"]
AgeGroup = Literal["under_18", "18_39", "40_59", "60_plus", "undisclosed"]
Sensitivity = Literal["air", "pollen", "heat", "noise"]
Interest = Literal["waterfront", "park", "quiet", "coffee", "toilet", "convenience"]
DataStatus = Literal["ok", "partial", "stale", "no_data", "error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Coordinate(StrictModel):
    lng_gcj02: float = Field(ge=-180, le=180)
    lat_gcj02: float = Field(ge=-90, le=90)


class UserProfile(StrictModel):
    route_mode: RouteMode
    target_time: datetime
    distance_min_m: int = Field(gt=0)
    target_distance_m: int = Field(gt=0)
    distance_max_m: int = Field(gt=0)
    origin: Coordinate | None = None
    search_radius_m: int | None = Field(default=None, gt=0)
    area_ids: list[str] = Field(default_factory=list)
    goal: Goal = "balanced"
    experience: Experience = "regular"
    age_group: AgeGroup = "undisclosed"
    sensitivities: list[Sensitivity] = Field(default_factory=lambda: list[Sensitivity]())
    route_shape: RouteShapePreference = "any"
    interests: list[Interest] = Field(default_factory=lambda: list[Interest]())
    free_text: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_distance_and_location(self) -> UserProfile:
        if not self.distance_min_m <= self.target_distance_m <= self.distance_max_m:
            raise ValueError("目标距离需位于距离上下限之间")
        if self.origin is None and self.search_radius_m is not None:
            raise ValueError("设置搜索半径时需提供 GCJ-02 出发坐标")
        return self


class QuestionnaireOption(StrictModel):
    value: str
    label: str


class QuestionnaireConfig(StrictModel):
    route_modes: list[QuestionnaireOption]
    distance_ranges: dict[str, list[tuple[int, int, int]]]
    goals: list[QuestionnaireOption]
    experience_levels: list[QuestionnaireOption]
    age_groups: list[QuestionnaireOption]
    areas: list[QuestionnaireOption]
    interests: list[Interest]
    sensitivities: list[Sensitivity]


class RouteLocation(StrictModel):
    name: str
    lng_gcj02: float
    lat_gcj02: float


class VerifiedPoi(StrictModel):
    poi_type: str
    poi_name: str
    distance_m: float


class RouteRecord(StrictModel):
    route_id: str
    route_name: str
    route_mode: RouteMode
    route_shape: Literal["one_way", "strict_loop"]
    distance_m: int
    duration_min: float
    start_location: RouteLocation
    end_location: RouteLocation
    region_zone: str
    tags: list[str]
    feature_tags: list[str]
    popular_area_ids: list[str]
    preference_hits: list[str]
    nearby_pois: list[VerifiedPoi]
    confidence: str
    validation_status: str
    geometry_status: str
    route_inside_ratio: float | None = None
    snap_ratio: float | None = None


class EnvironmentMetric(StrictModel):
    status: DataStatus
    value: float | None = None
    business_time: str | None = None
    fetched_at: str | None = None
    valid_until: str | None = None
    confidence: str
    estimated: bool
    spatial_scale: str
    unit: str
    scenarios: dict[str, float] = Field(default_factory=dict)


class PollenMetric(EnvironmentMetric):
    risk_level: str | None = None


class RouteEnvironment(StrictModel):
    route_id: str
    status: DataStatus
    pm2_5: EnvironmentMetric
    noise: EnvironmentMetric
    pollen_daily: list[PollenMetric]


class TimedRecord(StrictModel):
    status: DataStatus
    business_time: str | None = None
    valid_until: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class EnvironmentSnapshot(StrictModel):
    generated_at: datetime
    status: DataStatus
    current_weather: TimedRecord | None
    current_aqi: TimedRecord | None
    current_alerts: list[TimedRecord]
    weather_hourly: list[TimedRecord]
    aqi_hourly: list[TimedRecord]
    route_environment: dict[str, RouteEnvironment]


class DataBundle(StrictModel):
    routes: list[RouteRecord]
    environment: EnvironmentSnapshot


class RiskAssessment(StrictModel):
    status: Literal["ok", "warning", "paused"]
    score_penalty: float = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    weather: TimedRecord | None = None
    aqi: TimedRecord | None = None
    alerts: list[TimedRecord] = Field(default_factory=lambda: list[TimedRecord]())


class ScoredRoute(StrictModel):
    route: RouteRecord
    base_rank: int = 0
    base_score: float = Field(ge=0, le=100)
    dimension_scores: dict[str, float]
    data_confidence: float = Field(ge=0, le=1)
    access_distance_m: float | None = None
    matched_preferences: list[str] = Field(default_factory=list)
    environment_summary: dict[str, Any] = Field(default_factory=dict)
    risk_notes: list[str] = Field(default_factory=list)


class QwenRouteReview(StrictModel):
    route_id: str = Field(description="候选路线的 route_id")
    personalized_fit_reason: str = Field(
        min_length=8,
        max_length=160,
        description="用中文完整句说明路线与用户目标、距离和兴趣偏好的匹配依据",
    )
    cautions: list[str] = Field(
        default_factory=list,
        description="只列出输入数据能支持的环境或安全提醒",
    )


class QwenDecision(StrictModel):
    profile_summary: str
    ranked_route_ids: list[str]
    route_reviews: list[QwenRouteReview]
    decision_summary: str
    profile_conflicts: list[str] = Field(default_factory=list)
    review_status: Literal["approved", "adjusted"]


class ApiAudit(StrictModel):
    status: Literal["not_used", "ok", "degraded"]
    model: str | None = None
    prompt_version: str | None = None
    request_id: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str | None = None
    error_message: str | None = None


class FinalRoute(StrictModel):
    route: ScoredRoute
    final_rank: int
    personalized_fit: str
    cautions: list[str] = Field(default_factory=list)


class RecommendationResult(StrictModel):
    run_id: str
    generated_at: datetime
    status: Literal["ok", "degraded", "paused", "no_candidates"]
    decision_source: Literal["qwen", "python_fallback", "offline", "none"]
    profile: UserProfile
    risk: RiskAssessment
    base_candidates: list[ScoredRoute]
    final_routes: list[FinalRoute]
    decision_summary: str
    profile_conflicts: list[str] = Field(default_factory=list)
    data_generated_at: datetime
    api_audit: ApiAudit
