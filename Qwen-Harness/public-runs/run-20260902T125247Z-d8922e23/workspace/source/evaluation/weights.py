"""Weight loading and validation for the five-dimension evaluation model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SOURCE_DIR = Path(__file__).resolve().parents[1]
WEIGHTS_PATH = SOURCE_DIR / "evaluation_model_qwen" / "config" / "default_weights.json"

DIMENSIONS: tuple[str, ...] = (
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "user_preference",
)

DIMENSION_LABELS_ZH: dict[str, str] = {
    "environment_health": "环境健康",
    "sport_match": "运动匹配",
    "access_convenience": "接驳便利",
    "route_quality": "路线质量",
    "user_preference": "用户偏好",
}

SUM_TOLERANCE = 1e-6


class WeightsError(ValueError):
    """Raised when the weights configuration is missing, malformed or inconsistent."""


def canonical_json_bytes(payload: Any) -> bytes:
    """Canonical (sorted, compact, utf-8) JSON bytes used for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def weights_sha256(weights: dict[str, float]) -> str:
    """Hash of the canonical weights mapping alone."""
    return hashlib.sha256(canonical_json_bytes({"weights": weights})).hexdigest()


def validate_weights(weights: dict[str, float]) -> None:
    """Raise WeightsError unless the five weights are positive and sum to 1.0."""
    missing = [key for key in DIMENSIONS if key not in weights]
    if missing:
        raise WeightsError(f"weights file is missing keys: {missing}")
    unexpected = [key for key in weights if key not in DIMENSIONS]
    if unexpected:
        raise WeightsError(f"weights file has unexpected keys: {unexpected}")
    for key in DIMENSIONS:
        value = weights[key]
        if value != value or value <= 0.0 or value == float("inf"):
            raise WeightsError(f"weight {key} must be a finite positive number, got {value!r}")
    total = sum(weights[key] for key in DIMENSIONS)
    if abs(total - 1.0) > SUM_TOLERANCE:
        raise WeightsError(f"weights sum to {total!r}, expected 1.0 within {SUM_TOLERANCE}")


def load_weights(path: Path | None = None) -> tuple[dict[str, float], str]:
    """Load and validate the default weights file, returning (weights, sha256)."""
    target = path if path is not None else WEIGHTS_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise WeightsError(f"cannot read weights file {target.name}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WeightsError("weights file is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise WeightsError("weights file must contain a JSON object")
    block = payload.get("weights", payload)
    if not isinstance(block, dict):
        raise WeightsError("weights block must be a JSON object")
    try:
        weights = {str(key): float(value) for key, value in block.items()}
    except (TypeError, ValueError) as exc:
        raise WeightsError(f"weight values must be numeric: {exc}") from exc
    validate_weights(weights)
    return weights, weights_sha256(weights)
