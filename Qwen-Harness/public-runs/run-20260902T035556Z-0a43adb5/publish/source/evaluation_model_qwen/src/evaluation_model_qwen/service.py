"""Service layer for evaluation_model_qwen.

Provides:
- evaluation_root(): returns the data root path for the evaluation module.
- load_weights(): loads weight configuration from JSON file.
- recommend(): full recommendation pipeline using the module's own scoring.
- score_candidates(): narrow interface returning all feasible candidates.

All scoring logic is delegated exclusively to the generated module's own
loaders, constraints, and scoring sub-modules. No local scoring fallback,
no external project imports, no duplicated algorithms.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .loaders import load_data
from .models import (
    CandidateScoreResult,
    UserProfile,
)
from .scoring import evaluate_risk, score_routes

logger = logging.getLogger(__name__)

_MODULE_ROOT = Path(__file__).resolve().parent.parent.parent

# Default data directory: xuhui_route_builder/data/web relative to workspace root
_WORKSPACE_ROOT = _MODULE_ROOT.parent
_DEFAULT_DATA_DIR = _WORKSPACE_ROOT / "xuhui_route_builder" / "data" / "web"


def evaluation_root() -> Path:
    """Return the root directory of the evaluation module."""
    return _MODULE_ROOT


def _default_data_path(filename: str) -> Path:
    """Resolve a default data file path under xuhui_route_builder/data/web."""
    return _DEFAULT_DATA_DIR / filename


def load_weights(weights_path: Path | str | None = None) -> dict[str, float]:
    """Load dimension weights from a JSON file.

    Args:
        weights_path: Path to weights JSON. Defaults to config/default_weights.json.

    Returns:
        Dictionary mapping dimension names to weight values.

    Raises:
        FileNotFoundError: If the weights file does not exist.
        ValueError: If the file is not valid JSON or missing required keys.
    """
    if weights_path is None:
        weights_path = _MODULE_ROOT / "config" / "default_weights.json"
    else:
        weights_path = Path(weights_path)

    if not weights_path.exists():
        raise FileNotFoundError(f"Weights file not found: {weights_path}")

    with open(weights_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    dimensions = data.get("dimensions") if isinstance(data, dict) else None
    weights = dimensions if isinstance(dimensions, dict) else data

    required_keys = [
        "environment_health",
        "sport_match",
        "access_convenience",
        "route_quality",
        "interest_service",
    ]
    missing = [k for k in required_keys if k not in weights]
    if missing:
        raise ValueError(f"Weights file missing required keys: {missing}")

    return {k: float(weights[k]) for k in required_keys}


def _compute_weights_sha256(weights_path: Path | str | None = None) -> str:
    """Compute SHA256 hash of the weights file content.

    Returns a 64-character lowercase hexadecimal string.
    """
    if weights_path is None:
        weights_path = _MODULE_ROOT / "config" / "default_weights.json"
    else:
        weights_path = Path(weights_path)

    if not weights_path.exists():
        raise FileNotFoundError(f"Weights file not found: {weights_path}")

    content = weights_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def score_candidates(
    profile_path: Path | str,
    weights_path: Path | str | None = None,
    route_catalog_path: Path | str | None = None,
    environment_dashboard_path: Path | str | None = None,
) -> CandidateScoreResult:
    """Score all feasible candidates for the given profile.

    This is the narrow score-candidates interface. It uses exclusively the
    module's own loaders, constraints, and scoring implementations.

    Args:
        profile_path: Path to a JSON file containing the user profile.
        weights_path: Path to weights JSON. Defaults to config/default_weights.json.
        route_catalog_path: Path to route_catalog.json. Defaults to
            xuhui_route_builder/data/web/route_catalog.json.
        environment_dashboard_path: Path to environment_dashboard.json. Defaults to
            xuhui_route_builder/data/web/environment_dashboard.json.

    Returns:
        CandidateScoreResult with profile, risk, data_generated_at,
        candidate_count, candidates (each with route_id, route_mode,
        base_score, scores dict with five dimensions), and weights_sha256
        (64-char lowercase hex).

    Raises:
        FileNotFoundError: If any required input file does not exist.
    """
    from .constraints import apply_hard_constraints

    # Resolve and validate profile path
    profile_path = Path(profile_path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile file not found: {profile_path}")

    # Resolve weights path
    if weights_path is None:
        weights_path = _MODULE_ROOT / "config" / "default_weights.json"
    else:
        weights_path = Path(weights_path)
    if not weights_path.exists():
        raise FileNotFoundError(f"Weights file not found: {weights_path}")

    # Resolve data paths with defaults
    if route_catalog_path is None:
        route_catalog_path = _default_data_path("route_catalog.json")
    else:
        route_catalog_path = Path(route_catalog_path)
    if not route_catalog_path.exists():
        raise FileNotFoundError(f"Route catalog not found: {route_catalog_path}")

    if environment_dashboard_path is None:
        environment_dashboard_path = _default_data_path("environment_dashboard.json")
    else:
        environment_dashboard_path = Path(environment_dashboard_path)
    if not environment_dashboard_path.exists():
        raise FileNotFoundError(f"Environment dashboard not found: {environment_dashboard_path}")

    # Load profile
    with open(profile_path, "r", encoding="utf-8") as f:
        profile_data = json.load(f)
    profile = UserProfile(**profile_data)

    # Load data via module's own loader
    routes, environment = load_data(
        route_catalog_path=route_catalog_path,
        environment_dashboard_path=environment_dashboard_path,
    )

    # Evaluate risk
    risk = evaluate_risk(environment, profile)

    # Load weights
    weights = load_weights(weights_path)

    # Score routes using module's own scoring
    scored_routes = score_routes(routes, environment, profile, weights)

    # Apply hard constraints using module's own constraints
    feasible = apply_hard_constraints(scored_routes, profile)

    # Sort by composite score descending
    feasible.sort(key=lambda r: r.base_score, reverse=True)

    # Build candidates list
    candidates = []
    for route in feasible:
        candidates.append(
            {
                "route_id": route.route_id,
                "route_mode": route.route_mode,
                "base_score": route.base_score,
                "scores": route.scores,
            }
        )

    # Compute weights SHA256 (64-char lowercase hex)
    weights_sha256 = _compute_weights_sha256(weights_path)

    # Determine data_generated_at from environment metadata if available
    data_generated_at = None
    if isinstance(environment, dict):
        metadata = environment.get("metadata", {})
        data_generated_at = metadata.get("generated_at", None)

    result = CandidateScoreResult(
        profile=profile_data,
        risk=risk.model_dump() if hasattr(risk, "model_dump") else risk,
        data_generated_at=data_generated_at,
        candidate_count=len(candidates),
        candidates=candidates,
        weights_sha256=weights_sha256,
    )

    return result


def recommend(
    profile: UserProfile,
    weights_path: Path | str | None = None,
    route_catalog_path: Path | str | None = None,
    environment_dashboard_path: Path | str | None = None,
) -> dict[str, Any]:
    """Full recommendation pipeline.

    Uses the same score_candidates / scoring pipeline internally.
    Returns API-usable dict with non-empty recommendations, risk_assessment,
    and paused fields.

    Args:
        profile: User profile for personalization.
        weights_path: Optional path to weights file.
        route_catalog_path: Optional path to route catalog JSON.
        environment_dashboard_path: Optional path to environment dashboard JSON.

    Returns:
        Recommendation result dictionary with keys:
        - recommendations: non-empty list of scored route dicts
        - risk_assessment: risk evaluation dict
        - paused: boolean indicating if activity should be paused
        - candidate_count: number of feasible candidates
        - status: pipeline status string

    Raises:
        FileNotFoundError: If any required input file does not exist.
    """
    from .constraints import apply_hard_constraints

    # Resolve data paths with defaults
    if route_catalog_path is None:
        route_catalog_path = _default_data_path("route_catalog.json")
    else:
        route_catalog_path = Path(route_catalog_path)
    if not route_catalog_path.exists():
        raise FileNotFoundError(f"Route catalog not found: {route_catalog_path}")

    if environment_dashboard_path is None:
        environment_dashboard_path = _default_data_path("environment_dashboard.json")
    else:
        environment_dashboard_path = Path(environment_dashboard_path)
    if not environment_dashboard_path.exists():
        raise FileNotFoundError(f"Environment dashboard not found: {environment_dashboard_path}")

    # Load data via module's own loader
    routes, environment = load_data(
        route_catalog_path=route_catalog_path,
        environment_dashboard_path=environment_dashboard_path,
    )

    # Evaluate risk
    risk = evaluate_risk(environment, profile)
    risk_dict = risk.model_dump() if hasattr(risk, "model_dump") else dict(risk)

    # Check for pause conditions
    paused = getattr(risk, "paused", False)
    if paused:
        return {
            "status": "paused",
            "paused": True,
            "reason": getattr(risk, "pause_reason", "Environmental conditions unsafe"),
            "risk_assessment": risk_dict,
            "recommendations": [],
            "candidate_count": 0,
        }

    # Load weights
    weights = load_weights(weights_path)

    # Score routes using module's own scoring
    scored_routes = score_routes(routes, environment, profile, weights)

    # Apply hard constraints using module's own constraints
    feasible = apply_hard_constraints(scored_routes, profile)

    # Sort by composite score descending
    feasible.sort(key=lambda r: r.base_score, reverse=True)

    # Build recommendations list
    recommendations = []
    for route in feasible:
        recommendations.append(route.model_dump() if hasattr(route, "model_dump") else dict(route))

    return {
        "status": "ok",
        "paused": False,
        "risk_assessment": risk_dict,
        "recommendations": recommendations,
        "candidate_count": len(recommendations),
    }
