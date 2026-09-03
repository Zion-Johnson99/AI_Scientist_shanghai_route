"""Unit tests for the geometry primitives and the authoritative route gate.

Everything here runs on synthetic coordinates, so the suite stays meaningful
before any route portfolio has been generated.
"""

from __future__ import annotations

import pytest

from routes.gates import RouteInput, evaluate_route
from routes.geometry import (
    circuity,
    endpoint_offset_m,
    haversine_m,
    in_district_ratio,
    overlap_ratio,
    point_in_ring,
    polyline_length_m,
    resample,
)

#: A square of about 825 m perimeter, which lands inside walk band 0.
SQUARE = [
    (121.4300, 31.1700),
    (121.4320, 31.1700),
    (121.4320, 31.1720),
    (121.4300, 31.1720),
    (121.4300, 31.1700),
]

#: A boundary comfortably larger than the square, so interior tests are unambiguous.
BOUNDARY = [
    (121.4000, 31.1400),
    (121.4700, 31.1400),
    (121.4700, 31.2100),
    (121.4000, 31.2100),
    (121.4000, 31.1400),
]


def route_input(coords: list[tuple[float, float]], kind: str, target_m: float) -> RouteInput:
    return RouteInput(
        route_id="XH_WALK_0001",
        mode="walk",
        kind=kind,
        target_m=target_m,
        coords=coords,
        band=0,
        area="",
        navigation_nodes=2,
        start_marker=coords[0],
        end_marker=coords[-1],
        waypoints=(),
        long_distance=False,
    )


def test_haversine_is_symmetric_and_zero_on_itself() -> None:
    forward = haversine_m(SQUARE[0], SQUARE[1])
    assert forward == pytest.approx(haversine_m(SQUARE[1], SQUARE[0]))
    assert forward > 0.0
    assert haversine_m(SQUARE[0], SQUARE[0]) == 0.0


def test_polyline_length_is_the_sum_of_its_edges() -> None:
    total = polyline_length_m(SQUARE)
    edges = sum(haversine_m(SQUARE[i], SQUARE[i + 1]) for i in range(len(SQUARE) - 1))
    assert total == pytest.approx(edges, rel=1e-9)


def test_closed_square_has_no_endpoint_offset() -> None:
    assert endpoint_offset_m(SQUARE) == pytest.approx(0.0, abs=1e-6)


def test_open_path_reports_its_endpoint_gap() -> None:
    assert endpoint_offset_m(SQUARE[:-1]) > 200.0


def test_straight_line_circuity_is_one() -> None:
    straight = [(121.4300, 31.1700), (121.4320, 31.1700)]
    assert circuity(straight) == pytest.approx(1.0, abs=1e-6)


def test_point_in_ring_separates_inside_from_outside() -> None:
    assert point_in_ring((121.4350, 31.1750), BOUNDARY)
    assert not point_in_ring((121.5000, 31.1750), BOUNDARY)


def test_in_district_ratio_is_one_for_an_interior_route() -> None:
    assert in_district_ratio(SQUARE, BOUNDARY) == pytest.approx(1.0)


def test_identical_polylines_fully_overlap() -> None:
    assert overlap_ratio(SQUARE, SQUARE) == pytest.approx(1.0)


def test_distant_polylines_do_not_overlap() -> None:
    far = [(lon + 0.05, lat) for lon, lat in SQUARE]
    assert overlap_ratio(SQUARE, far) == pytest.approx(0.0)


def test_resample_keeps_endpoints_and_adds_points() -> None:
    dense = resample(SQUARE, 50.0)
    assert len(dense) > len(SQUARE)
    assert dense[0] == pytest.approx(SQUARE[0])
    assert dense[-1] == pytest.approx(SQUARE[-1])


def test_interior_loop_at_its_own_target_is_accepted() -> None:
    length = polyline_length_m(SQUARE)
    result = evaluate_route(route_input(SQUARE, "strict_loop", length), BOUNDARY)
    assert result.status == "accepted", result.failures
    assert result.passed


def test_route_outside_the_district_is_rejected() -> None:
    outside = [(lon + 0.20, lat) for lon, lat in SQUARE]
    length = polyline_length_m(outside)
    result = evaluate_route(route_input(outside, "strict_loop", length), BOUNDARY)
    assert not result.passed
    assert any("district" in failure for failure in result.failures)


def test_open_ring_is_rejected_as_a_strict_loop() -> None:
    length = polyline_length_m(SQUARE[:-1])
    result = evaluate_route(route_input(SQUARE[:-1], "strict_loop", length), BOUNDARY)
    assert not result.passed
