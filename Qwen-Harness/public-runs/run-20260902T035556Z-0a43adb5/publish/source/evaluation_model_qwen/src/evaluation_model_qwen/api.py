"""FastAPI application for evaluation model service.

Provides /api/v1/health and /api/v1/recommendations endpoints.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from evaluation_model_qwen.models import UserProfile
from evaluation_model_qwen.service import recommend

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Evaluation Model Qwen",
    version="0.1.0",
    description="Multi-source route evaluation and recommendation service",
)
allowed_origins = os.getenv(
    "EVALUATION_MODEL_QWEN_ALLOWED_ORIGINS",
    "http://127.0.0.1:8130,http://localhost:8130",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str


class RecommendationRequest(BaseModel):
    """Request body for /api/v1/recommendations."""

    route_mode: str = Field(..., description="walk, run, or bike")
    goal: str = Field(default="balanced", description="User goal")
    target_distance_m: float = Field(..., gt=0, description="Target distance in meters")
    sensitivities: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    origin_lat: float | None = Field(default=None, description="Origin latitude")
    origin_lng: float | None = Field(default=None, description="Origin longitude")


class RecommendationResponse(BaseModel):
    """Response body for /api/v1/recommendations."""

    status: str
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    risk_assessment: dict[str, Any] | None = None
    paused: bool = False
    pause_reason: str | None = None


@app.get("/api/v1/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/api/v1/recommendations", response_model=RecommendationResponse)
def get_recommendations(request: RecommendationRequest) -> RecommendationResponse:
    """Accept a user profile and return route recommendations."""
    try:
        profile = UserProfile(
            case_id=None,
            route_mode=request.route_mode,
            goal=request.goal,
            target_distance_m=request.target_distance_m,
            sensitivities=request.sensitivities,
            interests=request.interests,
            origin=(
                {"lat": request.origin_lat, "lng": request.origin_lng}
                if request.origin_lat is not None and request.origin_lng is not None
                else None
            ),
        )
    except (ValueError, TypeError) as exc:
        logger.warning("Invalid profile construction: %s", exc)
        raise HTTPException(status_code=422, detail=f"Invalid profile: {exc}") from exc

    try:
        result = recommend(profile=profile)
    except FileNotFoundError as exc:
        logger.error("Data file not found: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Required data file not found: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during recommendation")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {type(exc).__name__}",
        ) from exc

    if result is None:
        logger.error("Recommendation returned no result for profile: %s", request.route_mode)
        raise HTTPException(
            status_code=500,
            detail="Recommendation engine returned no result",
        )

    paused = result.get("paused", False)
    pause_reason = result.get("pause_reason")
    recommendations = result.get("recommendations", [])
    risk_assessment = result.get("risk_assessment")

    return RecommendationResponse(
        status="paused" if paused else "ok",
        recommendations=recommendations,
        risk_assessment=risk_assessment,
        paused=paused,
        pause_reason=pause_reason,
    )
