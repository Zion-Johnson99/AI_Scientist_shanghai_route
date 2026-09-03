"""Deterministic 81-case evaluation matrix comparing the model against two baselines."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import scorer
from .baselines import distance_only, shortest_access
from .recommend import (
    InvalidRequestError,
    _band_tables,
    band_matches,
    load_default_inputs,
    resolve_band,
    resolve_sha,
)
from .recommend import (
    recommend as model_recommend,
)
from .scorer import as_float

RUN_DIR = Path(__file__).resolve().parents[3]
SCORE_CANDIDATES_DIR = RUN_DIR / "experiments" / "score_candidates"

SPORT_LETTERS: dict[str, str] = {"walk": "W", "run": "R", "bike": "B"}
SPORT_ORDER: tuple[str, ...] = ("walk", "run", "bike")

CASE_PREFERENCE_SETS: tuple[tuple[str, ...], ...] = (
    ("riverside", "quiet"),
    ("park", "scenic"),
    ("urban", "shade"),
)

#: Fallback origins used only when the POI catalog cannot supply three transit
#: entries; coordinates are approximate representative points inside Xuhui.
FALLBACK_ORIGINS: tuple[dict[str, Any], ...] = (
    {"name_zh": "徐家汇（代表起点）", "coord": [121.4365, 31.1949]},
    {"name_zh": "徐汇滨江（代表起点）", "coord": [121.4520, 31.1830]},
    {"name_zh": "上海植物园（代表起点）", "coord": [121.4500, 31.1600]},
)
FALLBACK_ORIGIN_PROVENANCE = "manual_setting: approximate representative Xuhui origins for offline evaluation"

VARIANTS: tuple[str, ...] = ("model", "shortest_access", "distance_only")

THRESHOLDS: dict[str, tuple[str, float]] = {
    "detour_pass_rate": (">=", 0.90),
    "environment_win_rate": (">=", 0.60),
    "preference_win_rate": (">=", 0.60),
    "constraint_pass_rate": (">=", 0.90),
    "mean_detour_ratio": ("<=", 0.20),
}


def write_json_file(path: Path, payload: Any) -> None:
    """Write one JSON artifact with the project's canonical formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8")


def origin_pool(pois: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], str]:
    """Three deterministic origins: POI transit entries when available, else fallbacks."""
    entries = pois.get("entries") if isinstance(pois, Mapping) else None
    pool: list[dict[str, Any]] = []
    if isinstance(entries, list):
        usable = [
            item
            for item in entries
            if isinstance(item, dict)
            and isinstance(item.get("name_zh"), str)
            and isinstance(item.get("coord"), (list, tuple))
            and len(item["coord"]) >= 2
            and as_float(item["coord"][0]) is not None
        ]
        usable.sort(key=lambda item: (str(item.get("kind") != "station"), str(item.get("poi_id"))))
        pool = [
            {"name_zh": str(item["name_zh"]), "coord": [float(item["coord"][0]), float(item["coord"][1])]}
            for item in usable[:3]
        ]
    if len(pool) == 3:
        return pool, "poi_catalog:entries"
    return [dict(item) for item in FALLBACK_ORIGINS], FALLBACK_ORIGIN_PROVENANCE


def build_case_requests(
    catalog: Mapping[str, Any] | None, pois: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Cross product 3 sports x 3 bands x 3 preference sets x 3 origins = 81 cases."""
    origins, origin_provenance = origin_pool(pois)
    cases: list[dict[str, Any]] = []
    for sport in SPORT_ORDER:
        letter = SPORT_LETTERS[sport]
        labels, _ = _band_tables(catalog, sport)
        for band_index in range(3):
            label = labels[band_index] if band_index < len(labels) else None
            for pref_index, preferences in enumerate(CASE_PREFERENCE_SETS, start=1):
                for origin_index, origin in enumerate(origins, start=1):
                    case_id = f"CASE_{letter}_{band_index + 1}_P{pref_index}_O{origin_index}"
                    request: dict[str, Any] = {
                        "sport": sport,
                        "preferences": list(preferences),
                        "origin": list(origin["coord"]),
                        "origin_name": origin["name_zh"],
                        "limit": 10,
                    }
                    if label is not None:
                        request["distance_band"] = label
                    cases.append(
                        {
                            "case_id": case_id,
                            "sport": sport,
                            "band_index": band_index,
                            "band_label_zh": label,
                            "origin_provenance": origin_provenance,
                            "request": request,
                        }
                    )
    return cases


def feasible_floor(
    catalog: Mapping[str, Any] | None, sport: str, band_spec: Mapping[str, Any] | None
) -> float | None:
    """Minimum actual distance among accepted routes of the same sport and band."""
    routes = catalog.get("routes") if isinstance(catalog, Mapping) else None
    if not isinstance(routes, list):
        return None
    best: float | None = None
    for route in routes:
        if not isinstance(route, dict):
            continue
        if route.get("mode") != sport or route.get("status") != "accepted":
            continue
        if not band_matches(route, band_spec):
            continue
        distance = as_float(route.get("actual_distance_m"))
        if distance is None or distance <= 0.0:
            continue
        if best is None or distance < best:
            best = distance
    return best


def _primary_dimension(response: Mapping[str, Any], dimension: str) -> float | None:
    primary = response.get("primary")
    if not isinstance(primary, dict):
        return None
    breakdown = primary.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return None
    entry = breakdown.get(dimension)
    if not isinstance(entry, dict):
        return None
    return as_float(entry.get("score"))


def _score_ge(model_score: float | None, baseline_score: float | None) -> bool:
    if baseline_score is None:
        return True
    if model_score is None:
        return False
    return model_score >= baseline_score


def score_case(
    case: Mapping[str, Any],
    catalog: Mapping[str, Any] | None,
    dashboard: Mapping[str, Any] | None,
    access: Sequence[Any],
    pois: Mapping[str, Any] | None,
    weights: Mapping[str, float],
    *,
    write_dir: Path | None = None,
) -> dict[str, Any]:
    """Run model plus both baselines for one case and reduce to comparable metrics."""
    case_id = str(case.get("case_id", "CASE_UNKNOWN"))
    request = case["request"]
    result: dict[str, Any] = {
        "case_id": case_id,
        "sport": case.get("sport"),
        "band_label_zh": case.get("band_label_zh"),
        "request": request,
        "ready": False,
        "no_candidate": True,
        "model_route_id": None,
        "model_total_score": None,
        "model_distance_m": None,
        "feasible_floor_m": None,
        "detour_ratio": None,
        "detour_pass": False,
        "environment_win": False,
        "preference_win": False,
        "constraint_pass": False,
        "fatal_error": None,
    }
    responses: dict[str, Mapping[str, Any]] = {}
    try:
        strategies: dict[str, Callable[..., dict[str, Any]]] = {
            "model": model_recommend,
            "shortest_access": shortest_access,
            "distance_only": distance_only,
        }
        for variant in VARIANTS:
            response = strategies[variant](
                request, catalog, dashboard, access, pois, weights, offline=True
            )
            responses[variant] = response
            if write_dir is not None:
                payload = dict(response)
                payload["case_id"] = case_id
                payload["variant_id"] = variant
                write_json_file(write_dir / f"{case_id}__{variant}.json", payload)
    except (InvalidRequestError, OSError) as exc:
        result["fatal_error"] = f"{case_id}: {type(exc).__name__}: {exc}"
        return result

    model = responses["model"]
    result["no_candidate"] = not bool(model.get("candidate_count"))
    result["ready"] = bool(model.get("candidate_count"))
    primary = model.get("primary")
    if isinstance(primary, dict):
        result["model_route_id"] = primary.get("route_id")
        result["model_total_score"] = as_float(primary.get("total_score"))
        model_distance = as_float(primary.get("actual_distance_m"))
        result["model_distance_m"] = model_distance
        band_spec = resolve_band(str(case.get("sport")), request.get("distance_band"), catalog)
        floor = feasible_floor(catalog, str(case.get("sport")), band_spec)
        result["feasible_floor_m"] = floor
        if floor is not None and floor > 0.0 and model_distance is not None:
            ratio = (model_distance - floor) / floor
            result["detour_ratio"] = round(ratio, 6)
            result["detour_pass"] = ratio <= 0.20
        constraint = (
            primary.get("mode") == case.get("sport")
            and primary.get("status") == "accepted"
            and band_matches(primary, band_spec)
        )
        avoid_pause = bool(request.get("avoid_risk_pause", True))
        if avoid_pause and primary.get("overall_risk") == "stop":
            constraint = False
        result["constraint_pass"] = bool(constraint)
    result["environment_win"] = result["ready"] and _score_ge(
        _primary_dimension(model, "environment_health"),
        _primary_dimension(responses["distance_only"], "environment_health"),
    )
    result["preference_win"] = result["ready"] and _score_ge(
        _primary_dimension(model, "user_preference"),
        _primary_dimension(responses["shortest_access"], "user_preference"),
    )
    return result


def evaluate_matrix(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case metric dicts into the matrix verdict."""
    case_count = len(cases)
    fatal_errors = [str(case["fatal_error"]) for case in cases if case.get("fatal_error")]
    scored_cases = [case for case in cases if not case.get("fatal_error")]
    ready_cases = [case for case in scored_cases if case.get("ready")]
    ready_count = len(ready_cases)
    no_candidate_count = sum(1 for case in scored_cases if not case.get("ready"))
    ratios = [
        float(case["detour_ratio"])
        for case in cases
        if isinstance(case.get("detour_ratio"), (int, float))
    ]
    detour_pass_count = sum(1 for case in cases if case.get("detour_pass"))
    detour_pass_rate = detour_pass_count / len(ratios) if ratios else 0.0
    environment_win_rate = (
        sum(1 for case in ready_cases if case.get("environment_win")) / ready_count
        if ready_count
        else 0.0
    )
    preference_win_rate = (
        sum(1 for case in ready_cases if case.get("preference_win")) / ready_count
        if ready_count
        else 0.0
    )
    constraint_pass_rate = (
        sum(1 for case in ready_cases if case.get("constraint_pass")) / ready_count
        if ready_count
        else 0.0
    )
    mean_detour_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    values = {
        "detour_pass_rate": detour_pass_rate,
        "environment_win_rate": environment_win_rate,
        "preference_win_rate": preference_win_rate,
        "constraint_pass_rate": constraint_pass_rate,
        "mean_detour_ratio": mean_detour_ratio,
    }
    passed: dict[str, bool] = {}
    for key, (comparator, threshold) in THRESHOLDS.items():
        passed[key] = values[key] >= threshold if comparator == ">=" else values[key] <= threshold
    ready_share = ready_count / case_count if case_count else 0.0
    if fatal_errors or ready_share < 0.60:
        support_status = "inconclusive"
    elif all(passed.values()):
        support_status = "supported"
    else:
        #: Zero or partial threshold passes with enough ready cases is still a
        #: conclusive measurement, so it reports partially_supported.
        support_status = "partially_supported"
    return {
        "case_count": case_count,
        "ready_count": ready_count,
        "no_candidate_count": no_candidate_count,
        "ready_share": round(ready_share, 6),
        "detour_pass_rate": round(detour_pass_rate, 6),
        "environment_win_rate": round(environment_win_rate, 6),
        "preference_win_rate": round(preference_win_rate, 6),
        "constraint_pass_rate": round(constraint_pass_rate, 6),
        "mean_detour_ratio": round(mean_detour_ratio, 6),
        "detour_ratio_case_count": len(ratios),
        "fatal_data_errors": fatal_errors,
        "fatal_data_error_count": len(fatal_errors),
        "thresholds": {
            key: {"comparator": comparator, "threshold": threshold, "value": round(values[key], 6), "passed": passed[key]}
            for key, (comparator, threshold) in THRESHOLDS.items()
        },
        "passed": passed,
        "support_status": support_status,
        "provenance": scorer.PROVENANCE,
    }


def run_matrix(
    catalog: Mapping[str, Any] | None = None,
    dashboard: Mapping[str, Any] | None = None,
    access: Sequence[Any] | None = None,
    pois: Mapping[str, Any] | None = None,
    weights: Mapping[str, float] | None = None,
    *,
    write_dir: Path | None = SCORE_CANDIDATES_DIR,
    cases: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the deterministic case list, score every case and aggregate the matrix."""
    if catalog is None or dashboard is None or access is None or pois is None:
        defaults = load_default_inputs()
        catalog = defaults["catalog"] if catalog is None else catalog
        dashboard = defaults["dashboard"] if dashboard is None else dashboard
        access = defaults["access"] if access is None else access
        pois = defaults["pois"] if pois is None else pois
    access_list: Sequence[Any] = access if access is not None else []
    resolved_weights, _ = resolve_sha(weights)
    case_list = [dict(case) for case in cases] if cases is not None else build_case_requests(catalog, pois)
    results = [
        score_case(case, catalog, dashboard, access_list, pois, resolved_weights, write_dir=write_dir)
        for case in case_list
    ]
    matrix = evaluate_matrix(results)
    if write_dir is None:
        matrix["write_dir"] = None
    else:
        try:
            matrix["write_dir"] = write_dir.relative_to(RUN_DIR).as_posix()
        except ValueError:
            matrix["write_dir"] = write_dir.name
    matrix["per_case"] = [
        {
            "case_id": item["case_id"],
            "ready": item["ready"],
            "model_route_id": item["model_route_id"],
            "detour_ratio": item["detour_ratio"],
            "detour_pass": item["detour_pass"],
            "environment_win": item["environment_win"],
            "preference_win": item["preference_win"],
            "constraint_pass": item["constraint_pass"],
            "fatal_error": item["fatal_error"],
        }
        for item in results
    ]
    return matrix
