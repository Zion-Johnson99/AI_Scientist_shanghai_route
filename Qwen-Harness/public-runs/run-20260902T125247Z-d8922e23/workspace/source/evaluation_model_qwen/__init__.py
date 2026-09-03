"""Deterministic five-dimension recommendation and evaluation project root."""

from __future__ import annotations

from pathlib import Path

MODULE_ROOT: Path = Path(__file__).resolve().parent
WEIGHTS_RELATIVE: str = "config/default_weights.json"
DIMENSIONS: tuple[str, ...] = (
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "user_preference",
)

__all__ = ["DIMENSIONS", "MODULE_ROOT", "WEIGHTS_RELATIVE"]
