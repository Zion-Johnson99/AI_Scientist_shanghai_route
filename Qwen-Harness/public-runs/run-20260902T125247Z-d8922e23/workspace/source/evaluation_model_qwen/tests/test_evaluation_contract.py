"""Contract tests for weights, recommendation and the experiment matrix."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation_model_qwen import DIMENSIONS, MODULE_ROOT, WEIGHTS_RELATIVE


def load_weights_file() -> dict:
    target: Path = MODULE_ROOT / WEIGHTS_RELATIVE
    assert target.is_file(), WEIGHTS_RELATIVE
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_weights_file_shape() -> None:
    payload = load_weights_file()
    nested = payload.get("weights")
    weights = nested if isinstance(nested, dict) else payload
    assert set(weights) == set(DIMENSIONS)
    values = [float(value) for value in weights.values()]
    assert all(value > 0.0 for value in values)
    assert abs(sum(values) - 1.0) < 1e-6


def test_scorer_renormalises_missing_dimensions() -> None:
    from evaluation import scorer

    present = {
        "environment_health": {"score": None, "status": "unavailable"},
        "sport_match": {"score": 80.0, "status": "measured"},
        "access_convenience": {"score": 60.0, "status": "measured"},
        "route_quality": {"score": 70.0, "status": "measured"},
        "user_preference": {"score": 50.0, "status": "measured"},
    }
    weights = {
        "environment_health": 0.30,
        "sport_match": 0.20,
        "access_convenience": 0.15,
        "route_quality": 0.20,
        "user_preference": 0.15,
    }
    total, breakdown = scorer.combine_dimensions(present, weights)
    assert breakdown["environment_health"]["weight_effective"] == 0.0
    effective = [item["weight_effective"] for item in breakdown.values()]
    assert abs(sum(effective) - 1.0) < 1e-6
    assert total is not None
    assert 0.0 <= total <= 100.0


def test_recommend_accepts_offline_kwarg() -> None:
    #: ``evaluation/__init__`` re-exports the callable as ``recommend``, shadowing
    #: the submodule of the same name, so bind it from the module itself.
    from evaluation.recommend import recommend

    assert "offline" in recommend.__code__.co_varnames


def test_recommend_returns_empty_reason_not_raise() -> None:
    from evaluation.recommend import recommend

    catalog = {"routes": []}
    dashboard = {"cells": [], "routes": [], "field_specs": [], "risk_thresholds": {}}
    response = recommend(
        {"sport": "walk"},
        catalog,
        dashboard,
        [],
        {"entries": [], "parks": [], "services": []},
        {
            "environment_health": 0.30,
            "sport_match": 0.20,
            "access_convenience": 0.15,
            "route_quality": 0.20,
            "user_preference": 0.15,
        },
        offline=True,
    )
    assert response["candidate_count"] == 0
    assert response["empty_reason"]
    assert response["offline"] is True
    assert response["weights_sha256"]
