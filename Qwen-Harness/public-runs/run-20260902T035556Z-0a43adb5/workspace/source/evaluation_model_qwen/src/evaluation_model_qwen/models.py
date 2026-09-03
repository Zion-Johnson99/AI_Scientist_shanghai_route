"""Data models for the evaluation module.

Single data-contract module providing environment blocks, route records,
dashboard structures, user profiles, risk assessment, five-dimension scoring,
and experiment audit types. All models use Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RouteMode(str, Enum):
    """Supported route modes."""

    WALK = "walk"
    RUN = "run"
    BIKE = "bike"


class GoalType(str, Enum):
    """User goal types for route selection."""

    BALANCED = "balanced"
    HEALTH_ENVIRONMENT = "health_environment"
    NEARBY = "nearby"
    SCENERY = "scenery"


class SensitivityType(str, Enum):
    """Environmental sensitivity types."""

    PM25 = "pm25"
    POLLEN = "pollen"
    NOISE = "noise"


class InterestType(str, Enum):
    """User interest types."""

    WATERSIDE = "waterside"
    PARK = "park"
    QUIET = "quiet"
    CONVENIENCE = "convenience"
    TOILET = "toilet"


class RiskLevel(str, Enum):
    """Risk assessment levels."""

    SAFE = "safe"
    CAUTION = "caution"
    PAUSE = "pause"


# ---------------------------------------------------------------------------
# Environment data models
# ---------------------------------------------------------------------------


class EnvironmentBlock(BaseModel):
    """A single environment measurement with semantic metadata."""

    value: Optional[float] = Field(None, description="Numeric measurement value")
    unit: str = Field(..., description="Unit of measurement, e.g. ug/m3, dB, grains/m3")
    estimated: bool = Field(False, description="Whether the value is estimated")
    status: Optional[str] = Field(None, description="Semantic status, e.g. good, moderate, poor")


class EnvironmentRouteRecord(BaseModel):
    """Per-route environment record with semantic blocks."""

    route_id: str = Field(..., description="Route identifier")
    pm2_5: EnvironmentBlock = Field(..., description="PM2.5 measurement block")
    noise: EnvironmentBlock = Field(..., description="Noise measurement block")
    pollen_daily: EnvironmentBlock = Field(..., description="Daily pollen measurement block")


class EnvironmentRecord(EnvironmentRouteRecord):
    """Compatibility alias for EnvironmentRouteRecord."""


class EnvironmentRoutes(BaseModel):
    """Container for per-route environment items."""

    items: list[EnvironmentRouteRecord] = Field(
        default_factory=list, description="List of per-route environment records"
    )


class EnvironmentDashboard(BaseModel):
    """Top-level environment dashboard structure."""

    metadata: dict[str, Any] = Field(default_factory=dict, description="Dashboard metadata")
    current: dict[str, Any] = Field(default_factory=dict, description="Current conditions")
    forecast: Union[dict[str, Any], list[Any]] = Field(
        default_factory=dict, description="Forecast data"
    )
    routes: EnvironmentRoutes = Field(
        default_factory=EnvironmentRoutes, description="Per-route environment data"
    )
    route_records: list[EnvironmentRouteRecord] = Field(
        default_factory=list, description="Flat list of route environment records"
    )


class EnvironmentData(BaseModel):
    """Point-in-time environment observation for scoring."""

    temperature_c: float = Field(..., description="Temperature in Celsius")
    feels_like_c: float = Field(..., description="Feels-like temperature in Celsius")
    precipitation_mm: float = Field(0.0, ge=0, description="Precipitation in mm/h")
    wind_gust_ms: float = Field(0.0, ge=0, description="Wind gust speed in m/s")
    aqi: float = Field(0.0, ge=0, description="Air Quality Index")
    pm25: Optional[float] = Field(None, ge=0, description="PM2.5 concentration in ug/m3")


# ---------------------------------------------------------------------------
# Route models
# ---------------------------------------------------------------------------


class RouteEntry(BaseModel):
    """A route entry from the catalog, allowing extension fields."""

    model_config = {"extra": "allow"}

    route_id: str = Field(..., description="Unique route identifier")
    route_name: str = Field("", description="Display name of the route")
    route_mode: str = Field(..., description="Route mode: walk, run, or bike")
    distance_m: float = Field(0.0, ge=0, description="Route distance in meters")
    validation_status: str = Field("valid", description="Validation status")
    geometry_status: str = Field("ok", description="Geometry status")


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


class RiskFactor(BaseModel):
    """A single risk factor contributing to the overall assessment."""

    factor: str = Field(..., description="Risk factor identifier")
    level: RiskLevel = Field(..., description="Risk level for this factor")
    value: Optional[float] = Field(None, description="Observed or estimated value")
    threshold: Optional[float] = Field(None, description="Threshold that was exceeded")
    unit: Optional[str] = Field(None, description="Unit of the value")
    message: str = Field("", description="Human-readable explanation")


class RiskAssessment(BaseModel):
    """Overall risk assessment for outdoor activity."""

    paused: bool = Field(False, description="Whether activity should be paused")
    reasons: list[str] = Field(default_factory=list, description="Reasons for pause")
    thresholds_applied: dict[str, float] = Field(
        default_factory=dict, description="Mapping of threshold name to applied value"
    )
    level: RiskLevel = Field(default=RiskLevel.SAFE, description="Overall risk level")

    @property
    def risk_level(self) -> RiskLevel:
        """Alias property returning the risk level."""
        return self.level


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


class UserProfile(BaseModel):
    """User profile for route evaluation."""

    model_config = {"extra": "allow"}

    case_id: Optional[str] = Field(None, description="Optional experiment case identifier")
    route_mode: str = Field(..., description="Preferred route mode: walk, run, or bike")
    goal: str = Field("balanced", description="User goal for route selection")
    target_distance_m: float = Field(..., gt=0, description="Target distance in meters")
    sensitivities: list[str] = Field(default_factory=list, description="Environmental sensitivities")
    interests: list[str] = Field(default_factory=list, description="User interests")
    origin: Optional[dict[str, Any]] = Field(None, description="Optional origin coordinates")


# ---------------------------------------------------------------------------
# Five-dimension scoring (0..100 scale)
# ---------------------------------------------------------------------------

_FIVE_DIMENSIONS = (
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "interest_service",
)


class ScoredRoute(BaseModel):
    """A route with five-dimension scores on a 0..100 scale."""

    route_id: str = Field(..., description="Route identifier")
    route_name: str = Field("", description="Display name of the route")
    route_mode: str = Field("", description="Route mode")
    distance_m: float = Field(0.0, ge=0, description="Route distance in meters")
    base_score: float = Field(0.0, ge=0, le=100, description="Composite base score 0..100")
    environment_health: float = Field(0.0, ge=0, le=100, description="Environment health score")
    sport_match: float = Field(0.0, ge=0, le=100, description="Sport match score")
    access_convenience: float = Field(0.0, ge=0, le=100, description="Access convenience score")
    route_quality: float = Field(0.0, ge=0, le=100, description="Route quality score")
    interest_service: float = Field(0.0, ge=0, le=100, description="Interest service score")

    @property
    def scores(self) -> dict[str, float]:
        """Return the five dimension scores as a dictionary."""
        return {
            "environment_health": self.environment_health,
            "sport_match": self.sport_match,
            "access_convenience": self.access_convenience,
            "route_quality": self.route_quality,
            "interest_service": self.interest_service,
        }


class CandidateScoreResult(BaseModel):
    """Result of the score-candidates operation."""

    profile: dict[str, Any] = Field(default_factory=dict, description="Echoed user profile")
    risk: dict[str, Any] = Field(default_factory=dict, description="Risk assessment summary")
    data_generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of data generation",
    )
    candidate_count: int = Field(0, ge=0, description="Number of candidates returned")
    candidates: list[ScoredRoute] = Field(
        default_factory=list, description="Scored candidate routes"
    )
    weights_sha256: str = Field("", description="SHA256 of the weights file used")

    @model_validator(mode="after")
    def _check_candidate_count(self) -> "CandidateScoreResult":
        if self.candidate_count != len(self.candidates):
            raise ValueError(
                f"candidate_count ({self.candidate_count}) != len(candidates) ({len(self.candidates)})"
            )
        return self


# ---------------------------------------------------------------------------
# Experiment audit types
# ---------------------------------------------------------------------------


class CommandAudit(BaseModel):
    """Audit record for a single command invocation."""

    command: str = Field(..., description="Full command string")
    returncode: int = Field(0, description="Process return code")
    stdout_sha256: Optional[str] = Field(None, description="SHA256 of stdout")
    stderr_sha256: Optional[str] = Field(None, description="SHA256 of stderr")
    duration_ms: float = Field(0.0, ge=0, description="Execution duration in milliseconds")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of execution",
    )


class ModuleResult(BaseModel):
    """Result envelope for a module execution step."""

    module: str = Field(..., description="Module identifier")
    status: str = Field("ok", description="Execution status: ok, error, skipped")
    message: str = Field("", description="Human-readable status message")
    data: dict[str, Any] = Field(default_factory=dict, description="Module output payload")
    audit: Optional[CommandAudit] = Field(None, description="Optional command audit record")
