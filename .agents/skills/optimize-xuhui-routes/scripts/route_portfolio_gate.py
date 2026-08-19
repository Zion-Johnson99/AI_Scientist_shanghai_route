#!/usr/bin/env python3
"""Audit the fixed 90-route Xuhui portfolio and its web-catalog contract."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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
    "walk": (
        ("0.5-2km", 500.0, 2_000.0),
        ("2-3.5km", 2_000.0, 3_500.0),
        ("3.5-5km", 3_500.0, 5_000.0),
    ),
    "run": (
        ("1-5km", 1_000.0, 5_000.0),
        ("5-10km", 5_000.0, 10_000.0),
        ("10-15km", 10_000.0, 15_000.0),
    ),
    "bike": (
        ("5-10km", 5_000.0, 10_000.0),
        ("10-20km", 10_000.0, 20_000.0),
        ("20-30km", 20_000.0, 30_000.0),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the Xuhui 90-route portfolio contract."
    )
    parser.add_argument(
        "routes", type=Path, help="Route JSON list or GeoJSON FeatureCollection"
    )
    parser.add_argument(
        "--web-catalog", type=Path, help="Optional web route catalog to compare"
    )
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Return success while retaining failures",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        help="Audit one 30-route mode handoff instead of the full 90-route portfolio",
    )
    parser.add_argument(
        "--require-all-accepted",
        action="store_true",
        help="Final-release gate: fail when any route remains needs_review",
    )
    parser.add_argument(
        "--require-poi-audit-clean",
        action="store_true",
        help="Fail the command when POI relationships or audit records are inconsistent",
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
        raise ValueError(
            f"{path}: expected a route list, routes object, or FeatureCollection"
        )
    if not all(isinstance(route, dict) for route in routes):
        raise ValueError(f"{path}: every route must be an object")
    return routes


def audit_portfolio(
    routes: list[dict[str, Any]],
    web_routes: list[dict[str, Any]] | None = None,
    require_all_accepted: bool = False,
    mode: str | None = None,
) -> dict[str, Any]:
    if mode is not None and mode not in MODES:
        raise ValueError(f"unsupported route mode: {mode}")

    scoped_routes = (
        [route for route in routes if _route_mode(route) == mode] if mode else routes
    )
    scoped_modes = (mode,) if mode else MODES
    expected_route_count = 30 if mode else 90
    failures: list[dict[str, Any]] = []
    route_ids = [_route_id(route, index) for index, route in enumerate(scoped_routes)]
    duplicate_ids = sorted(
        identifier for identifier, count in Counter(route_ids).items() if count > 1
    )
    if duplicate_ids:
        failures.append(_failure("duplicate_route_ids", duplicate_ids))
    if len(scoped_routes) != expected_route_count:
        failures.append(
            _failure(
                "route_count_mismatch",
                {
                    "scope": mode or "all",
                    "expected": expected_route_count,
                    "actual": len(scoped_routes),
                },
            )
        )
    invalid_statuses = [
        {
            "route_id": identifier,
            "validation_status": str(route.get("validation_status") or ""),
        }
        for identifier, route in zip(route_ids, scoped_routes)
        if str(route.get("validation_status") or "") not in {"accepted", "needs_review"}
    ]
    if invalid_statuses:
        failures.append(_failure("invalid_validation_status", invalid_statuses))
    validation_status_counts = Counter(
        str(route.get("validation_status") or "") for route in scoped_routes
    )
    if (
        require_all_accepted
        and validation_status_counts["accepted"] != expected_route_count
    ):
        failures.append(
            _failure(
                "not_all_routes_accepted",
                {
                    "accepted": validation_status_counts["accepted"],
                    "needs_review": validation_status_counts["needs_review"],
                },
            )
        )

    mode_counts = Counter(_route_mode(route) for route in scoped_routes)
    if any(mode_counts[route_mode] != 30 for route_mode in scoped_modes) or any(
        route_mode not in scoped_modes for route_mode in mode_counts
    ):
        failures.append(_failure("mode_count_mismatch", dict(mode_counts)))

    distance_bucket_counts: dict[str, dict[str, int]] = {}
    distance_outliers: list[dict[str, Any]] = []
    for route_mode in scoped_modes:
        bucket_counts = Counter()
        for route in scoped_routes:
            if _route_mode(route) != route_mode:
                continue
            distance = _route_distance_m(route)
            bucket = _distance_bucket(route_mode, distance)
            if bucket is None:
                distance_outliers.append(
                    {
                        "route_id": _route_id(route, 0),
                        "mode": route_mode,
                        "distance_m": distance,
                    }
                )
            else:
                bucket_counts[bucket] += 1
        distance_bucket_counts[route_mode] = {
            label: bucket_counts[label] for label, _, _ in DISTANCE_BUCKETS[route_mode]
        }
        if any(
            bucket_counts[label] != 10 for label, _, _ in DISTANCE_BUCKETS[route_mode]
        ):
            failures.append(
                _failure(
                    "distance_bucket_count_mismatch",
                    {"mode": route_mode, "counts": distance_bucket_counts[route_mode]},
                )
            )
    if distance_outliers:
        failures.append(_failure("distance_out_of_range", distance_outliers))

    shape_counts: dict[str, dict[str, int]] = {}
    invalid_shapes: list[str] = []
    false_loops: list[dict[str, Any]] = []
    missing_loop_geometry: list[str] = []
    strict_loop_geometry_checked = 0
    for route_mode in scoped_modes:
        counts = Counter(
            str(route.get("route_shape") or "")
            for route in scoped_routes
            if _route_mode(route) == route_mode
        )
        shape_counts[route_mode] = {shape: counts[shape] for shape in SHAPES}
        if (
            not 14 <= counts["strict_loop"] <= 16
            or counts["one_way"] + counts["strict_loop"] != 30
        ):
            failures.append(
                _failure(
                    "shape_balance_mismatch",
                    {"mode": route_mode, "counts": shape_counts[route_mode]},
                )
            )
    for index, route in enumerate(scoped_routes):
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
                in {
                    "open_loop",
                    "false_loop_topology",
                    "retraced_edges",
                    "branch_or_self_intersection",
                }
            }
            if topology_codes:
                false_loops.append(
                    {
                        "route_id": result["route_id"],
                        "failure_codes": sorted(topology_codes),
                    }
                )
    if invalid_shapes:
        failures.append(_failure("invalid_route_shapes", invalid_shapes))
    if missing_loop_geometry:
        failures.append(_failure("strict_loop_geometry_missing", missing_loop_geometry))
    if false_loops:
        failures.append(_failure("false_loop_detected", false_loops))

    popular_area_counts: dict[str, int] = Counter()
    popular_area_mode_counts: dict[str, dict[str, int]] = defaultdict(lambda: Counter())
    for route in scoped_routes:
        route_mode = _route_mode(route)
        for area_id in _popular_area_ids(route):
            popular_area_counts[area_id] += 1
            popular_area_mode_counts[area_id][route_mode] += 1
    missing_popular_areas = [
        area_id for area_id in POPULAR_AREAS if popular_area_counts[area_id] == 0
    ]
    if missing_popular_areas:
        failures.append(_failure("popular_area_coverage_gap", missing_popular_areas))

    web_metrics: dict[str, Any] | None = None
    poi_routes = scoped_routes
    if web_routes is not None:
        scoped_web_routes = (
            [route for route in web_routes if _route_mode(route) == mode]
            if mode
            else web_routes
        )
        web_metrics, web_failures = _audit_web_catalog(scoped_routes, scoped_web_routes)
        failures.extend(web_failures)
        poi_routes = scoped_web_routes

    poi_audit, preference_coverage_counts = _audit_pois(poi_routes)

    metrics = {
        "scope": mode or "all",
        "route_count": len(scoped_routes),
        "validation_status_counts": dict(validation_status_counts),
        "mode_counts": {
            route_mode: mode_counts[route_mode] for route_mode in scoped_modes
        },
        "distance_bucket_counts": distance_bucket_counts,
        "shape_counts": shape_counts,
        "shape_target_per_mode": {
            "strict_loop": 15,
            "one_way": 15,
            "strict_loop_allowed": [14, 16],
        },
        "strict_loop_geometry_checked_count": strict_loop_geometry_checked,
        "preference_coverage_counts": {
            label: preference_coverage_counts[label]
            for label in ("zero", "one", "two", "three", "four")
        },
        "popular_area_counts": {
            area_id: popular_area_counts[area_id] for area_id in POPULAR_AREAS
        },
        "popular_area_mode_counts": {
            area_id: {mode: popular_area_mode_counts[area_id][mode] for mode in MODES}
            for area_id in POPULAR_AREAS
        },
        "web_catalog": web_metrics,
    }
    return {
        "status": "pass" if not failures else "fail",
        "metrics": metrics,
        "failures": failures,
        "poi_audit": poi_audit,
    }


def _audit_web_catalog(
    routes: list[dict[str, Any]], web_routes: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    route_statuses = {
        _route_id(route, index): str(route.get("validation_status") or "")
        for index, route in enumerate(routes)
    }
    web_ids = [_route_id(route, index) for index, route in enumerate(web_routes)]
    web_index = {
        _route_id(route, index): route for index, route in enumerate(web_routes)
    }
    if (
        len(web_routes) != len(routes)
        or set(web_ids) != set(route_statuses)
        or len(web_ids) != len(set(web_ids))
    ):
        failures.append(
            _failure(
                "web_catalog_route_set_mismatch",
                {
                    "expected_count": len(routes),
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
        recommendation_eligible = route.get(
            "recommendation_eligible", expected_eligible
        )
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
        failures.append(
            _failure(
                "web_recommendation_eligibility_mismatch", recommendation_mismatches
            )
        )
    if navigation_mismatches:
        failures.append(
            _failure("web_navigation_eligibility_mismatch", navigation_mismatches)
        )
    return (
        {
            "displayed_count": len(web_routes),
            "needs_review_count": sum(
                route.get("validation_status") == "needs_review" for route in web_routes
            ),
            "recommendation_eligible_count": len(recommendation_ids),
            "navigation_eligible_count": len(navigation_ids),
        },
        failures,
    )


def _audit_pois(
    routes: list[dict[str, Any]],
) -> tuple[dict[str, Any], Counter[str]]:
    coverage_labels = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four"}
    coverage_counts: Counter[str] = Counter()
    incomplete_searches: list[dict[str, Any]] = []
    relation_mismatches: list[dict[str, Any]] = []
    invalid_associations: list[dict[str, Any]] = []
    preference_gaps: list[dict[str, Any]] = []
    long_route_supply_gaps: list[str] = []

    for index, route in enumerate(routes):
        identifier = _route_id(route, index)
        route_mode = _route_mode(route)
        nearby_pois = route.get("nearby_pois")
        if not isinstance(nearby_pois, list):
            nearby_pois = []
            invalid_associations.append(
                {"route_id": identifier, "reason": "nearby_pois_not_list"}
            )

        verified_types: set[str] = set()
        association_issues: list[dict[str, Any]] = []
        for poi_index, poi in enumerate(nearby_pois):
            if not isinstance(poi, dict):
                association_issues.append(
                    {"index": poi_index, "reason": "poi_not_object"}
                )
                continue
            poi_type = str(poi.get("poi_type") or "")
            if poi.get("verification_status") != "verified":
                association_issues.append(
                    {
                        "index": poi_index,
                        "poi_type": poi_type,
                        "reason": "poi_not_verified",
                    }
                )
                continue
            missing_fields = [
                field
                for field in (
                    "poi_id",
                    "poi_name",
                    "source",
                    "source_accessed_at",
                    "open_status",
                )
                if not poi.get(field)
            ]
            if missing_fields:
                association_issues.append(
                    {
                        "index": poi_index,
                        "poi_type": poi_type,
                        "reason": "missing_verified_fields",
                        "fields": missing_fields,
                    }
                )
                continue
            relation_issue = _poi_relation_issue(route_mode, poi)
            if relation_issue:
                association_issues.append(
                    {"index": poi_index, "poi_type": poi_type, "reason": relation_issue}
                )
                continue
            if poi_type in PREFERENCES:
                verified_types.add(poi_type)
        if association_issues:
            invalid_associations.append(
                {"route_id": identifier, "issues": association_issues}
            )

        hits = set(route.get("preference_hits") or ()) & set(PREFERENCES)
        if hits != verified_types:
            relation_mismatches.append(
                {
                    "route_id": identifier,
                    "preference_hits": sorted(hits),
                    "derived_from_nearby_pois": sorted(verified_types),
                }
            )
        coverage_counts[coverage_labels[len(verified_types)]] += 1
        if len(verified_types) < 2:
            preference_gaps.append(
                {"route_id": identifier, "verified_types": sorted(verified_types)}
            )

        search_status = route.get("preference_search_status")
        if not isinstance(search_status, dict):
            incomplete_searches.append(
                {"route_id": identifier, "missing_types": list(PREFERENCES)}
            )
        else:
            missing = [
                preference
                for preference in PREFERENCES
                if search_status.get(preference) not in SEARCH_STATUSES
            ]
            if missing:
                incomplete_searches.append(
                    {"route_id": identifier, "missing_types": missing}
                )
            inconsistent = [
                preference
                for preference in PREFERENCES
                if (preference in verified_types)
                != (search_status.get(preference) == "verified")
            ]
            if inconsistent:
                relation_mismatches.append(
                    {
                        "route_id": identifier,
                        "search_status_mismatch_types": inconsistent,
                    }
                )

        distance = _route_distance_m(route)
        is_long_route = distance is not None and (
            (route_mode == "run" and distance > 5_000)
            or (route_mode == "bike" and distance > 10_000)
        )
        if is_long_route and not verified_types & {"toilet", "convenience"}:
            long_route_supply_gaps.append(identifier)

    findings: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if incomplete_searches:
        findings.append(_failure("incomplete_preference_search", incomplete_searches))
    if relation_mismatches:
        findings.append(_failure("preference_relation_mismatch", relation_mismatches))
    if invalid_associations:
        findings.append(_failure("invalid_poi_route_relation", invalid_associations))
    if preference_gaps:
        warnings.append(_failure("insufficient_preference_coverage", preference_gaps))
    if long_route_supply_gaps:
        warnings.append(_failure("long_route_supply_gap", long_route_supply_gaps))
    return (
        {
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "warnings": warnings,
        },
        coverage_counts,
    )


def _poi_relation_issue(route_mode: str, poi: dict[str, Any]) -> str | None:
    poi_type = str(poi.get("poi_type") or "")
    try:
        distance_m = float(poi.get("distance_m"))
    except (TypeError, ValueError):
        return "invalid_distance"
    if distance_m < 0:
        return "invalid_distance"

    relation = str(poi.get("route_relation") or "")
    if poi_type == "park_gate":
        expected_relation = "along_route" if distance_m <= 100.0 else "nearby"
        if distance_m > 200.0 or relation != expected_relation:
            return "park_distance_or_relation_out_of_range"
        return None

    corridor_m = 200.0 if route_mode == "bike" else 100.0
    if poi_type in {"coffee", "toilet", "convenience"} and (
        distance_m > corridor_m or relation != "along_route"
    ):
        return "service_distance_or_relation_out_of_range"
    return None


def _route_id(route: dict[str, Any], index: int) -> str:
    return str(route.get("route_id") or route.get("seed_id") or f"route-{index + 1}")


def _route_mode(route: dict[str, Any]) -> str:
    return str(route.get("route_mode") or route.get("mode") or "")


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
        if lower <= distance < upper or (
            index == len(buckets) - 1 and distance == upper
        ):
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
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def result_exit_code(result: dict[str, Any], require_poi_audit_clean: bool) -> int:
    if result.get("status") != "pass":
        return 1
    if (
        require_poi_audit_clean
        and (result.get("poi_audit") or {}).get("status") != "pass"
    ):
        return 1
    return 0


def main() -> int:
    args = parse_args()
    routes = load_routes(args.routes)
    web_routes = load_routes(args.web_catalog) if args.web_catalog else None
    result = audit_portfolio(
        routes,
        web_routes,
        require_all_accepted=args.require_all_accepted,
        mode=args.mode,
    )
    if args.report:
        write_report(args.report, result)
    print(
        f"status={result['status']} poi_audit={result['poi_audit']['status']} "
        f"routes={result['metrics']['route_count']} failures={len(result['failures'])}"
    )
    for failure in result["failures"]:
        print(f"FAIL {failure['code']}")
    if args.report_only:
        return 0
    return result_exit_code(result, args.require_poi_audit_clean)


if __name__ == "__main__":
    raise SystemExit(main())
