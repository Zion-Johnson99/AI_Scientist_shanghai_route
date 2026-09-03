"""Offline five-dimension evaluation package for the Xuhui healthy-route AI Scientist."""

from __future__ import annotations

from .baselines import distance_only, shortest_access
from .metrics import build_case_requests, evaluate_matrix, run_matrix, score_case
from .recommend import InvalidRequestError, recommend, score_candidates
from .scorer import PROVENANCE, score_route, scored_catalog_summary
from .weights import WeightsError, load_weights, weights_sha256

__all__ = [
    "PROVENANCE",
    "InvalidRequestError",
    "WeightsError",
    "build_case_requests",
    "distance_only",
    "evaluate_matrix",
    "load_weights",
    "recommend",
    "run_matrix",
    "score_candidates",
    "score_case",
    "score_route",
    "scored_catalog_summary",
    "shortest_access",
    "weights_sha256",
]
