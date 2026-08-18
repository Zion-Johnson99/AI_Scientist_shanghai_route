#!/usr/bin/env python3
"""Regression tests for the project route-optimization skill scripts."""

from __future__ import annotations

import unittest

from route_portfolio_gate import POPULAR_AREAS, audit_portfolio
from route_quality_gate import audit_route
from select_changed_routes import build_work_batches, classify


def failure_codes(route: dict[str, object]) -> set[str]:
    result = audit_route(route, 0)
    return {failure["code"] for failure in result["failures"]}


class RouteQualityGateTests(unittest.TestCase):
    def test_accepts_smooth_one_way(self) -> None:
        route = {
            "route_id": "clean-one-way",
            "route_mode": "bike",
            "route_shape": "one_way",
            "polyline_gcj02": [[121.440, 31.180], [121.445, 31.180], [121.450, 31.180]],
        }
        self.assertEqual(failure_codes(route), set())

    def test_accepts_clean_strict_loop(self) -> None:
        route = {
            "route_id": "clean-loop",
            "route_mode": "run",
            "route_shape": "strict_loop",
            "polyline_gcj02": [
                [121.440, 31.180],
                [121.445, 31.180],
                [121.445, 31.185],
                [121.440, 31.185],
                [121.440, 31.180],
            ],
        }
        self.assertEqual(failure_codes(route), set())

    def test_rejects_formally_closed_dumbbell_route(self) -> None:
        route = {
            "route_id": "false-dumbbell-loop",
            "route_mode": "walk",
            "route_shape": "strict_loop",
            "polyline_gcj02": [
                [121.445, 31.180],
                [121.445, 31.184],
                [121.449, 31.184],
                [121.449, 31.180],
                [121.445, 31.180],
                [121.445, 31.176],
                [121.449, 31.176],
                [121.449, 31.172],
                [121.445, 31.172],
                [121.445, 31.176],
                [121.445, 31.180],
            ],
        }
        self.assertIn("false_loop_topology", failure_codes(route))

    def test_rejects_branching_local_detour(self) -> None:
        route = {
            "route_id": "branching-detour",
            "route_mode": "walk",
            "route_shape": "one_way",
            "polyline_gcj02": [
                [121.440, 31.180],
                [121.445, 31.180],
                [121.445, 31.183],
                [121.448, 31.183],
                [121.445, 31.180],
                [121.452, 31.180],
            ],
        }
        codes = failure_codes(route)
        self.assertIn("branch_or_self_intersection", codes)
        self.assertIn("local_return_loop", codes)

    def test_rejects_geometry_before_start_marker(self) -> None:
        route = {
            "route_id": "line-before-start",
            "route_mode": "bike",
            "route_shape": "one_way",
            "start_location": {"lng_gcj02": 121.445, "lat_gcj02": 31.180},
            "end_location": {"lng_gcj02": 121.455, "lat_gcj02": 31.180},
            "polyline_gcj02": [[121.440, 31.180], [121.445, 31.180], [121.455, 31.180]],
        }
        self.assertIn("start_marker_offset", failure_codes(route))

    def test_rejects_proper_self_intersection(self) -> None:
        route = {
            "route_id": "bow-crossing",
            "route_mode": "run",
            "route_shape": "one_way",
            "polyline_gcj02": [
                [121.440, 31.180],
                [121.445, 31.185],
                [121.440, 31.185],
                [121.445, 31.180],
            ],
        }
        self.assertIn("branch_or_self_intersection", failure_codes(route))


class ChangedRouteSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "seed_id": "XH_WALK_0001",
            "route_mode": "walk",
            "route_shape": "one_way",
            "start_location": {"name": "入口", "lng_gcj02": 121.44, "lat_gcj02": 31.18, "source": "A"},
            "end_location": {"name": "出口", "lng_gcj02": 121.45, "lat_gcj02": 31.18},
            "ordered_nodes": [],
            "amenity_ids": ["POI-1"],
        }

    def test_evidence_change_skips_geometry_regeneration(self) -> None:
        current = {**self.base, "start_location": {**self.base["start_location"], "source": "B"}}
        result = classify("XH_WALK_0001", self.base, current)
        self.assertEqual(result["change_types"], ["metadata_changed"])

    def test_coordinate_change_regenerates_geometry(self) -> None:
        current = {
            **self.base,
            "start_location": {**self.base["start_location"], "lng_gcj02": 121.441},
        }
        result = classify("XH_WALK_0001", self.base, current)
        self.assertEqual(result["change_types"], ["geometry_changed"])

    def test_amenity_change_only_rematches_pois(self) -> None:
        current = {**self.base, "amenity_ids": ["POI-1", "POI-2"]}
        result = classify("XH_WALK_0001", self.base, current)
        self.assertEqual(result["change_types"], ["amenity_changed"])

    def test_display_change_only_rebuilds_web_catalog(self) -> None:
        current = {**self.base, "route_name": "更新后的页面标题"}
        result = classify("XH_WALK_0001", self.base, current)
        self.assertEqual(result["change_types"], ["display_changed"])

    def test_work_batches_never_exceed_five_routes(self) -> None:
        routes = [
            {"route_id": f"XH_WALK_{index:04d}", "change_types": ["geometry_changed"]}
            for index in range(1, 13)
        ]
        batches = build_work_batches(routes, max_batch_size=5)
        self.assertEqual([len(batch["route_ids"]) for batch in batches["geometry_changed"]], [5, 5, 2])

    def test_work_batches_propagate_downstream_tasks(self) -> None:
        routes = [
            {"route_id": "geometry", "change_types": ["geometry_changed"]},
            {"route_id": "amenity", "change_types": ["amenity_changed"]},
            {"route_id": "display", "change_types": ["display_changed"]},
        ]
        batches = build_work_batches(routes)
        self.assertEqual(batches["geometry_changed"][0]["route_ids"], ["geometry"])
        self.assertEqual(batches["amenity_changed"][0]["route_ids"], ["amenity", "geometry"])
        self.assertEqual(batches["display_changed"][0]["route_ids"], ["amenity", "display", "geometry"])


class RoutePortfolioGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = self._balanced_routes()
        self.web_routes = [
            {
                "route_id": route["route_id"],
                "validation_status": route["validation_status"],
                "recommendation_eligible": route["validation_status"] == "accepted",
                "navigation_eligible": route["validation_status"] == "accepted",
            }
            for route in self.routes
        ]

    def test_accepts_complete_balanced_portfolio(self) -> None:
        result = audit_portfolio(self.routes, self.web_routes)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["metrics"]["route_count"], 90)
        self.assertEqual(result["metrics"]["preference_coverage_counts"], {"two": 90, "three": 0, "four": 0})

    def test_rejects_wrong_distance_shape_and_preference_coverage(self) -> None:
        self.routes[0]["target_distance_m"] = 8_000
        self.routes[1]["route_shape"] = "one_way"
        self.routes[3]["route_shape"] = "one_way"
        self.routes[2]["preference_hits"] = ["coffee"]
        result = audit_portfolio(self.routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("distance_bucket_count_mismatch", codes)
        self.assertIn("shape_balance_mismatch", codes)
        self.assertIn("insufficient_preference_coverage", codes)

    def test_reports_missing_distance_without_crashing(self) -> None:
        del self.routes[30]["target_distance_m"]
        result = audit_portfolio(self.routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("distance_out_of_range", codes)

    def test_rejects_incomplete_four_type_search_audit(self) -> None:
        del self.routes[0]["preference_search_status"]["park_gate"]
        result = audit_portfolio(self.routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("incomplete_preference_search", codes)

    def test_rejects_false_loop_when_geometry_is_available(self) -> None:
        self.routes[0]["polyline_gcj02"] = [
            [121.445, 31.180],
            [121.445, 31.184],
            [121.449, 31.184],
            [121.449, 31.180],
            [121.445, 31.180],
            [121.445, 31.176],
            [121.449, 31.176],
            [121.449, 31.172],
            [121.445, 31.172],
            [121.445, 31.176],
            [121.445, 31.180],
        ]
        result = audit_portfolio(self.routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("false_loop_detected", codes)

    def test_rejects_strict_loop_without_geometry(self) -> None:
        del self.routes[0]["polyline_gcj02"]
        result = audit_portfolio(self.routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("strict_loop_geometry_missing", codes)

    def test_rejects_missing_popular_area(self) -> None:
        for route in self.routes:
            if "huajing" in route["popular_area_ids"]:
                route["popular_area_ids"] = ["west_bund"]
        result = audit_portfolio(self.routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("popular_area_coverage_gap", codes)

    def test_needs_review_is_viewable_but_not_recommendable_or_navigable(self) -> None:
        self.routes[0]["validation_status"] = "needs_review"
        self.web_routes[0].update(
            validation_status="needs_review",
            recommendation_eligible=False,
            navigation_eligible=False,
        )
        self.assertEqual(audit_portfolio(self.routes, self.web_routes)["status"], "pass")

        self.web_routes[0]["recommendation_eligible"] = True
        result = audit_portfolio(self.routes, self.web_routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("web_recommendation_eligibility_mismatch", codes)

    def test_final_release_requires_all_routes_accepted(self) -> None:
        self.routes[0]["validation_status"] = "needs_review"
        self.web_routes[0].update(
            validation_status="needs_review",
            recommendation_eligible=False,
            navigation_eligible=False,
        )
        result = audit_portfolio(self.routes, self.web_routes, require_all_accepted=True)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("not_all_routes_accepted", codes)

    def test_rejects_web_catalog_missing_a_route(self) -> None:
        result = audit_portfolio(self.routes, self.web_routes[:-1])
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("web_catalog_route_set_mismatch", codes)

    def test_rejects_nonpublishable_validation_status(self) -> None:
        self.routes[0]["validation_status"] = "pending"
        self.web_routes[0]["validation_status"] = "pending"
        result = audit_portfolio(self.routes, self.web_routes)
        codes = {failure["code"] for failure in result["failures"]}
        self.assertIn("invalid_validation_status", codes)

    @staticmethod
    def _balanced_routes() -> list[dict[str, object]]:
        mode_distances = {
            "walk": (1_000, 2_500, 4_000),
            "run": (3_000, 7_000, 12_000),
            "bike": (7_000, 15_000, 25_000),
        }
        prefixes = {"walk": "WALK", "run": "RUN", "bike": "BIKE"}
        routes: list[dict[str, object]] = []
        route_number = 1
        area_ids = list(POPULAR_AREAS)
        for mode, distances in mode_distances.items():
            for mode_index in range(30):
                hits = ["coffee", "toilet"]
                routes.append(
                    {
                        "route_id": f"XH_{prefixes[mode]}_{route_number:04d}",
                        "route_mode": mode,
                        "route_shape": "strict_loop" if mode_index < 15 else "one_way",
                        "target_distance_m": distances[mode_index // 10],
                        "validation_status": "accepted",
                        "popular_area_ids": [area_ids[mode_index % len(area_ids)]],
                        "preference_hits": hits,
                        "preference_search_status": {
                            preference: "verified" if preference in hits else "no_verified_match"
                            for preference in ("coffee", "park_gate", "toilet", "convenience")
                        },
                        **(
                            {
                                "polyline_gcj02": [
                                    [121.440, 31.180],
                                    [121.445, 31.180],
                                    [121.445, 31.185],
                                    [121.440, 31.185],
                                    [121.440, 31.180],
                                ]
                            }
                            if mode_index < 15
                            else {}
                        ),
                    }
                )
                route_number += 1
        return routes


if __name__ == "__main__":
    unittest.main()
