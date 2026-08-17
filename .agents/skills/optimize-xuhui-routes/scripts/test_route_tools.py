#!/usr/bin/env python3
"""Regression tests for the project route-optimization skill scripts."""

from __future__ import annotations

import unittest

from route_quality_gate import audit_route
from select_changed_routes import classify


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


if __name__ == "__main__":
    unittest.main()
