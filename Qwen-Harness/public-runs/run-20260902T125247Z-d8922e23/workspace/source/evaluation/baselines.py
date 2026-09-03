"""Baseline comparison strategies over the same scored candidate set as the full model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .recommend import (
    access_sort_key,
    assemble_response,
    distance_sort_key,
    resolve_sha,
    score_candidates,
)
from .scorer import as_float


def shortest_access(
    request: dict[str, Any],
    catalog: Mapping[str, Any] | None = None,
    dashboard: Mapping[str, Any] | None = None,
    access: Sequence[Any] | None = None,
    pois: Mapping[str, Any] | None = None,
    weights: Mapping[str, float] | None = None,
    *,
    offline: bool = True,
    **_ignored: object,
) -> dict[str, Any]:
    """Baseline: rank purely by estimated access minutes, ignoring environment."""
    resolved_weights, sha = resolve_sha(weights)
    prepared = score_candidates(request, catalog, dashboard, access, pois, resolved_weights)
    return assemble_response(
        prepared,
        "shortest_access",
        access_sort_key,
        sha,
        offline,
        sorted(str(key) for key in _ignored),
    )


def distance_only(
    request: dict[str, Any],
    catalog: Mapping[str, Any] | None = None,
    dashboard: Mapping[str, Any] | None = None,
    access: Sequence[Any] | None = None,
    pois: Mapping[str, Any] | None = None,
    weights: Mapping[str, float] | None = None,
    *,
    offline: bool = True,
    **_ignored: object,
) -> dict[str, Any]:
    """Baseline: rank purely by |actual_distance_m - requested band target|."""
    resolved_weights, sha = resolve_sha(weights)
    prepared = score_candidates(request, catalog, dashboard, access, pois, resolved_weights)
    target = as_float(prepared["profile"].get("band_target_m"))
    return assemble_response(
        prepared,
        "distance_only",
        distance_sort_key(target),
        sha,
        offline,
        sorted(str(key) for key in _ignored),
    )
