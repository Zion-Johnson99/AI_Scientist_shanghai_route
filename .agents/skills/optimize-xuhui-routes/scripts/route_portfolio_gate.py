#!/usr/bin/env python3
"""Audit the fixed 90-route Xuhui portfolio and its web-catalog contract."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from route_quality_gate import audit_route, route_points


MODES = ("walk", "run", "bike")
SHAPES = ("one_way", "strict_loop")
PREFERENCES = ("coffee", "park_gate", "toilet", "convenience")
SEARCH_STATUSES = {"verified", "no_verified_match", "needs_review", "source_failed"}
POPULAR_AREAS = {
    "west_bund": ("徐汇滨江", "西岸", "龙腾大道"),
    "longhua": ("龙华",),
    "xujiahui": ("徐家汇",),
    "hengfu": ("衡复", "衡山路", "复兴路"),
    "shanghai_botanical_garden": ("上海植物园", "植物园"),
    "kangjian": ("康健园", "康健"),
    "caohejing": ("漕河泾",),
    "huajing": ("华泾",),
}
DISTANCE_BUCKETS = {
    "walk": (("0.5-2km", 500.0, 2_000.0), ("2-3.5km", 2_000.0, 3_500.0), ("3.5-5km", 3_500.0, 5_000.0)),
    "run": (("1-5km", 1_000.0, 5_000.0), ("5-10km", 5_000.0, 10_000.0), ("10-15km", 10_000.0, 15_000.0)),
    "bike": (("5-10km", 5_000.0, 10_000.0), ("10-20km", 10_000.0, 20_000.0), ("20-30km", 20_000.0, 30_000.0)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the Xuhui 90-route portfolio contract.")
    parser.add_argument("routes", type=Path, help="Route JSON list or GeoJSON FeatureCollection")
    parser.add_argument("--web-catalog", type=Path, help="Optional web route catalog to compare")
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    parser.add_argument("--report-only", action="store_true", help="Return success while retaining failures")
    parser.add_argument(
        "--require-all-accepted",
        action="store_true",
        help="Final-release gate: fail when any route remains needs_review",
    )
    return parser.parse_args()


def load_routes(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        routes = payload
    elif isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        routes = []
        for feature in payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            properties["_geometry"] = feature.get("geometry") or {}
            routes.append(properties)
    elif isinstance(payload, dict) and isinstance(payload.get("routes"), list):
        routes = payload["routes"]
    else:
        raise ValueError(f"{path}: expected a route list, routes object, or FeatureCollection")
    if not all(isinstance(route, dict) for route in routes):
        raise ValueError(f"{path}: every route must be an object")
    return routes


def audit_portfolio(
    routes: list[dict[str, Any]],
    web_routes: list[dict[str, Any]] | None = None,
    require_all_accepted: bool = False,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    route_ids = [_route_id(route, index) for index, route in enumerate(routes)]
    duplicate_ids = sorted(identifier for identifier, count in Counter(route_ids).items() if count > 1)
    if duplicate_ids:
        failures.append(_failure("duplicate_route_ids", duplicate_ids))
    if len(routes) != 90:
        failures.append(_failure("route_count_mismatch", {"expected": 90, "actual": len(routes)}))
    invalid_statuses = [
        {"route_id": identifier, "validation_status": str(route.get("validation_status") or "")}
        for identifier, route in zip(route_ids, routes)
        if str(route.get("validation_status") or "") not in {"accepted", "needs_review"}
    ]
    if invalid_statuses:
        failures.append(_failure("invalid_validation_status", invalid_statuses))
    validation_status_counts = Counter(str(route.get("validation_status") or "") for route in routes)
    if require_all_accepted and validation_status_counts["accepted"] != 90:
        failures.append(
            _failure(
                "not_all_routes_accepted",
                {
                    "accepted": validation_status_counts["accepted"],
                    "needs_review": validation_status_counts["needs_review"],
                },
            )
        )

    mode_counts = Counter(str(route.get("route_mode") or route.get("mode") or "") for route in routes)
    if any(mode_counts[mode] != 30 for mode in MODES) or any(mode not in MODES for mode in mode_counts):
        failures.append(_failure("mode_count_mismatch", dict(mode_counts)))

    distance_bucket_counts: dict[str, dict[str, int]] = {}
    distance_outliers: list[dict[str, Any]] = []
    for mode in MODES:
        bucket_counts = Counter()
        for route in routes:
            if str(route.get("route_mode") or route.get("mode") or "") != mode:
                continue
            distance = _route_distance_m(route)
            bucket = _distance_bucket(mode, distance)
            if bucket is None:
                distance_outliers.append({"route_id": _route_id(route, 0), "mode": mode, "distance_m": distance})
            else:
                bucket_counts[bucket] += 1
        distance_bucket_counts[mode] = {label: bucket_counts[label] for label, _, _ in DISTANCE_BUCKETS[mode]}
        if any(bucket_counts[label] != 10 for label, _, _ in DISTANCE_BUCKETS[mode]):
            failures.append(
                _failure("distance_bucket_count_mismatch", {"mode": mode, "counts": distance_bucket_counts[mode]})
            )
    if distance_outliers:
        failures.append(_failure("distance_out_of_range", distance_outliers))

    shape_counts: dict[str, dict[str, int]] = {}
    invalid_shapes: list[str] = []
    false_loops: list[dict[str, Any]] = []
    missing_loop_geometry: list[str] = []
    strict_loop_geometry_checked = 0
    for mode in MODES:
        counts = Counter(
            str(route.get("route_shape") or "")
            for route in routes
            if str(route.get("route_mode") or route.get("mode") or "") == mode
        )
        shape_counts[mode] = {shape: counts[shape] for shape in SHAPES}
        if not 14 <= counts["strict_loop"] <= 16 or counts["one_way"] + counts["strict_loop"] != 30:
            failures.append(_failure("shape_balance_mismatch", {"mode": mode, "counts": shape_counts[mode]}))
    for index, route in enumerate(routes):
        shape = str(route.get("route_shape") or "")
        if shape not in SHAPES:
            invalid_shapes.append(_route_id(route, index))
        points = route_points(route)
        if shape == "strict_loop" and not points:
            missing_loop_geometry.append(_route_id(route, index))
        elif shape == "strict_loop":
            strict_loop_geometry_checked += 1
            result = audit_route(route, index)
            topology_codes = {
                failure["code"]
                for failure in result["failures"]
                if failure["code"]
                in {"open_loop", "false_loop_topology", "retraced_edges", "branch_or_self_intersection"}
            }
            if topology_codes:
                false_loops.append({"route_id": result["route_id"], "failure_codes": sorted(topology_codes)})
    if invalid_shapes:
        failures.append(_failure("invalid_route_shapes", invalid_shapes))
    if missing_loop_geometry:
        failures.append(_failure("strict_loop_geometry_missing", missing_loop_geometry))
    if false_loops:
        failures.append(_failure("false_loop_detected", false_loops))

    preference_coverage_counts = Counter()
    preference_gaps: list[dict[str, Any]] = []
    incomplete_searches: list[dict[str, Any]] = []
    verification_mismatches: list[dict[str, Any]] = []
    long_route_supply_gaps: list[str] = []
    for index, route in enumerate(routes):
        identifier = _route_id(route, index)
        hits = set(route.get("preference_hits") or ()) & set(PREFERENCES)
        hit_count = len(hits)
        if hit_count in (2, 3, 4):
            preference_coverage_counts[{2: "two", 3: "three", 4: "four"}[hit_count]] += 1
        if hit_count < 2:
            preference_gaps.append({"route_id": identifier, "verified_types": sorted(hits)})

        search_status = route.get("preference_search_status")
        if not isinstance(search_status, dict):
            incomplete_searches.append({"route_id": identifier, "missing_types": list(PREFERENCES)})
        else:
            missing = [
                preference
                for preference in PREFERENCES
                if search_status.get(preference) not in SEARCH_STATUSES
            ]
            if missing:
                incomplete_searches.append({"route_id": identifier, "missing_types": missing})
            inconsistent = [
                preference
                for preference in PREFERENCES
                if (preference in hits) != (search_status.get(preference) == "verified")
            ]
            if inconsistent:
                verification_mismatches.append({"route_id": identifier, "types": inconsistent})

        mode = str(route.get("route_mode") or route.get("mode") or "")
        distance = _route_distance_m(route)
        is_long_route = distance is not None and (
            (mode == "run" and distance > 5_000) or (mode == "bike" and distance > 10_000)
        )
        if is_long_route and not hits & {"toilet", "convenience"}:
            long_route_supply_gaps.append(identifier)
    if preference_gaps:
        failures.append(_failure("insufficient_preference_coverage", preference_gaps))
    if incomplete_searches:
        failures.append(_failure("incomplete_preference_search", incomplete_searches))
    if verification_mismatches:
        failures.append(_failure("preference_verification_mismatch", verification_mismatches))
    if long_route_supply_gaps:
        failures.append(_failure("long_route_supply_gap", long_route_supply_gaps))

    popular_area_counts: dict[str, int] = Counter()
    popular_area_mode_counts: dict[str, dict[str, int]] = defaultdict(lambda: Counter())
    for route in routes:
        mode = str(route.get("route_mode") or route.get("mode") or "")
        for area_id in _popular_area_ids(route):
            popular_area_counts[area_id] += 1
            popular_area_mode_counts[area_id][mode] += 1
    missing_popular_areas = [area_id for area_id in POPULAR_AREAS if popular_area_counts[area_id] == 0]
    if missing_popular_areas:
        failures.append(_failure("popular_area_coverage_gap", missing_popular_areas))

    web_metrics: dict[str, Any] | None = None
    if web_routes is not None:
        web_metrics, web_failures = _audit_web_catalog(routes, web_routes)
        failures.extend(web_failures)

    metrics = {
        "route_count": len(routes),
        "validation_status_counts": dict(validation_status_counts),
        "mode_counts": {mode: mode_counts[mode] for mode in MODES},
        "distance_bucket_counts": distance_bucket_counts,
        "shape_counts": shape_counts,
        "shape_target_per_mode": {"strict_loop": 15, "one_way": 15, "strict_loop_allowed": [14, 16]},
        "strict_loop_geometry_checked_count": strict_loop_geometry_checked,
        "preference_coverage_counts": {
            label: preference_coverage_counts[label] for label in ("two", "three", "four")
        },
        "popular_area_counts": {area_id: popular_area_counts[area_id] for area_id in POPULAR_AREAS},
        "popular_area_mode_counts": {
            area_id: {mode: popular_area_mode_counts[area_id][mode] for mode in MODES}
            for area_id in POPULAR_AREAS
        },
        "web_catalog": web_metrics,
    }
    return {"status": "pass" if not failures else "fail", "metrics": metrics, "failures": failures}


def _audit_web_catalog(
    routes: list[dict[str, Any]], web_routes: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    route_statuses = {
        _route_id(route, index): str(route.get("validation_status") or "")
        for index, route in enumerate(routes)
    }
    web_ids = [_route_id(route, index) for index, route in enumerate(web_routes)]
    web_index = {_route_id(route, index): route for index, route in enumerate(web_routes)}
    if len(web_routes) != 90 or set(web_ids) != set(route_statuses) or len(web_ids) != len(set(web_ids)):
        failures.append(
            _failure(
                "web_catalog_route_set_mismatch",
                {
                    "expected_count": 90,
                    "actual_count": len(web_routes),
                    "missing_ids": sorted(set(route_statuses) - set(web_ids)),
                    "extra_ids": sorted(set(web_ids) - set(route_statuses)),
                },
            )
        )

    status_mismatches: list[str] = []
    viewability_mismatches: list[str] = []
    recommendation_mismatches: list[str] = []
    navigation_mismatches: list[str] = []
    recommendation_ids: list[str] = []
    navigation_ids: list[str] = []
    for identifier, route in web_index.items():
        status = str(route.get("validation_status") or "")
        if identifier in route_statuses and status != route_statuses[identifier]:
            status_mismatches.append(identifier)
        if route.get("display_eligible", True) is not True:
            viewability_mismatches.append(identifier)
        expected_eligible = status == "accepted"
        recommendation_eligible = route.get("recommendation_eligible", expected_eligible)
        navigation_eligible = route.get("navigation_eligible", expected_eligible)
        if recommendation_eligible is not expected_eligible:
            recommendation_mismatches.append(identifier)
        if navigation_eligible is not expected_eligible:
            navigation_mismatches.append(identifier)
        if recommendation_eligible:
            recommendation_ids.append(identifier)
        if navigation_eligible:
            navigation_ids.append(identifier)
    if status_mismatches:
        failures.append(_failure("web_validation_status_mismatch", status_mismatches))
    if viewability_mismatches:
        failures.append(_failure("web_viewability_mismatch", viewability_mismatches))
    if recommendation_mismatches:
        failures.append(_failure("web_recommendation_eligibility_mismatch", recommendation_mismatches))
    if navigation_mismatches:
        failures.append(_failure("web_navigation_eligibility_mismatch", navigation_mismatches))
    return (
        {
            "displayed_count": len(web_routes),
            "needs_review_count": sum(route.get("validation_status") == "needs_review" for route in web_routes),
            "recommendation_eligible_count": len(recommendation_ids),
            "navigation_eligible_count": len(navigation_ids),
        },
        failures,
    )


def _route_id(route: dict[str, Any], index: int) -> str:
    return str(route.get("route_id") or route.get("seed_id") or f"route-{index + 1}")


def _route_distance_m(route: dict[str, Any]) -> float | None:
    for field in ("actual_distance_m", "distance_m", "target_distance_m"):
        value = route.get(field)
        try:
            distance = float(value)
        except (TypeError, ValueError):
            continue
        if distance > 0:
            return distance
    return None


def _distance_bucket(mode: str, distance: float | None) -> str | None:
    if distance is None:
        return None
    buckets = DISTANCE_BUCKETS[mode]
    for index, (label, lower, upper) in enumerate(buckets):
        if lower <= distance < upper or (index == len(buckets) - 1 and distance == upper):
            return label
    return None


def _popular_area_ids(route: dict[str, Any]) -> set[str]:
    explicit = route.get("popular_area_ids")
    if isinstance(explicit, list):
        return {str(area_id) for area_id in explicit if str(area_id) in POPULAR_AREAS}
    text_values: Iterable[Any] = (
        route.get("route_name"),
        route.get("region_zone"),
        *(route.get("tags") or ()),
    )
    text = " ".join(str(value or "") for value in text_values)
    return {
        area_id
        for area_id, aliases in POPULAR_AREAS.items()
        if any(alias in text for alias in aliases)
    }


def _failure(code: str, details: Any) -> dict[str, Any]:
    return {"code": code, "details": details}


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    routes = load_routes(args.routes)
    web_routes = load_routes(args.web_catalog) if args.web_catalog else None
    result = audit_portfolio(routes, web_routes, require_all_accepted=args.require_all_accepted)
    if args.report:
        write_report(args.report, result)
    print(
        f"status={result['status']} routes={result['metrics']['route_count']} "
        f"failures={len(result['failures'])}"
    )
    for failure in result["failures"]:
        print(f"FAIL {failure['code']}")
    return 0 if args.report_only or result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
