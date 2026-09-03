"""Douglas-Peucker simplification in a local metric frame.

Raw OpenStreetMap ways carry a shape point every few metres. Left untouched, a
25 km cycling route would hold tens of thousands of vertices, which makes the
quadratic geometry audits unusable and the browser map heavy. Simplification here
is a pure geometry operation: it never invents a coordinate that was not already
on the road, so road snapping survives it.
"""

from __future__ import annotations

from collections.abc import Sequence

from .geometry import Coord, point_to_segment_distance_m


def douglas_peucker(coords: Sequence[Coord], tolerance_m: float) -> list[Coord]:
    """Return the vertices of ``coords`` that survive a ``tolerance_m`` filter.

    The first and last vertices are always kept, so a closed ring stays closed and
    an open route keeps both of its real endpoints.
    """
    if len(coords) < 3:
        return list(coords)
    keep = [False] * len(coords)
    keep[0] = True
    keep[-1] = True
    stack: list[tuple[int, int]] = [(0, len(coords) - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        anchor_a = coords[start]
        anchor_b = coords[end]
        worst_index = -1
        worst_distance = -1.0
        for index in range(start + 1, end):
            distance = point_to_segment_distance_m(coords[index], anchor_a, anchor_b)
            if distance > worst_distance:
                worst_distance = distance
                worst_index = index
        if worst_index > 0 and worst_distance > tolerance_m:
            keep[worst_index] = True
            stack.append((start, worst_index))
            stack.append((worst_index, end))
    out: list[Coord] = []
    for point, flag in zip(coords, keep, strict=True):
        if not flag:
            continue
        if out and point == out[-1]:
            continue
        out.append(point)
    return out
