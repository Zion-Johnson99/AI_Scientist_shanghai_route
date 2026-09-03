"""Pure-Python geodesy and polyline geometry.

Every coordinate in this package is a ``(lon, lat)`` pair in CRS84 / WGS84.
The run uses one coordinate reference system end to end, so no conversion is
performed here; ``assert_crs`` exists so that any artifact entering the
pipeline declares its CRS and a mismatch fails loudly instead of silently
shifting the district by a few hundred metres.

No third-party dependency is used: the module is importable by pytest, Ruff,
Pyright and the offline reproduction entry point alike.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Coord = tuple[float, float]
Ring = Sequence[Coord]

EARTH_RADIUS_M = 6371008.8
CRS_WGS84 = "CRS84/WGS84"
CRS_ALIASES = frozenset(
    {
        "CRS84/WGS84",
        "CRS84",
        "WGS84",
        "EPSG:4326",
        "URN:OGC:DEF:CRS:OGC:1.3:CRS84",
    }
)


class CRSMismatchError(ValueError):
    """Raised when an artifact declares a CRS other than the run-wide one."""


def normalise_crs(declared: str) -> str:
    """Fold a declared CRS string onto the run-wide canonical form.

    Source payloads annotate the axis order (``CRS84/WGS84 (lon,lat)``). The
    annotation carries no reprojection information, so it is dropped before the
    alias lookup.
    """
    return declared.split("(", 1)[0].upper().replace(" ", "")


def assert_crs(declared: str | None, context: str) -> str:
    """Validate ``declared`` and return the unified CRS name to store."""
    if declared is None:
        raise CRSMismatchError(f"{context}: missing CRS declaration")
    if normalise_crs(declared) not in CRS_ALIASES:
        raise CRSMismatchError(f"{context}: unsupported CRS {declared!r}; run uses {CRS_WGS84}")
    return CRS_WGS84


def haversine_m(a: Coord, b: Coord) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def polyline_length_m(coords: Sequence[Coord]) -> float:
    return sum(haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def bbox(coords: Sequence[Coord]) -> tuple[float, float, float, float]:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def bbox_diagonal_m(box: tuple[float, float, float, float]) -> float:
    west, south, east, north = box
    return haversine_m((west, south), (east, north))


def point_in_ring(point: Coord, ring: Ring) -> bool:
    """Ray casting. ``ring`` may or may not repeat its first vertex."""
    x, y = point
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def point_to_segment_distance_m(p: Coord, a: Coord, b: Coord) -> float:
    """Distance from ``p`` to segment ``ab`` using a local equirectangular frame."""
    lat0 = math.radians(a[1])
    ax = a[0] * math.cos(lat0)
    ay = a[1]
    bx = b[0] * math.cos(lat0)
    by = b[1]
    px = p[0] * math.cos(lat0)
    py = p[1]
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        t = 0.0
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
    cx = ax + t * dx
    cy = ay + t * dy
    return math.hypot((px - cx) * math.cos(lat0), py - cy) * 111320.0


def polyline_distance_m(point: Coord, coords: Sequence[Coord]) -> float:
    return min(point_to_segment_distance_m(point, coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def resample(coords: Sequence[Coord], step_m: float) -> list[Coord]:
    """Densify a polyline so that no gap exceeds ``step_m``."""
    if len(coords) < 2:
        return list(coords)
    out: list[Coord] = [coords[0]]
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        segment = haversine_m(a, b)
        steps = max(1, math.ceil(segment / step_m))
        for k in range(1, steps + 1):
            t = k / steps
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def in_district_ratio(coords: Sequence[Coord], boundary: Ring, step_m: float = 20.0) -> float:
    """Share of the trajectory length that falls inside ``boundary``."""
    dense = resample(coords, step_m)
    if len(dense) < 2:
        return 0.0
    inside = 0.0
    total = 0.0
    for i in range(len(dense) - 1):
        segment = haversine_m(dense[i], dense[i + 1])
        total += segment
        if point_in_ring(dense[i], boundary):
            inside += segment
    return inside / total if total > 0 else 0.0


def _orientation(p: Coord, q: Coord, r: Coord) -> int:
    value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if abs(value) < 1e-14:
        return 0
    return 1 if value > 0 else 2


def _on_segment(p: Coord, q: Coord, r: Coord) -> bool:
    return (
        min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12
        and min(p[1], r[1]) - 1e-12 <= q[1] <= max(p[1], r[1]) + 1e-12
    )


def segments_intersect(p1: Coord, p2: Coord, p3: Coord, p4: Coord) -> bool:
    """Proper intersection test; shared endpoints are not an intersection."""
    o1 = _orientation(p1, p2, p3)
    o2 = _orientation(p1, p2, p4)
    o3 = _orientation(p3, p4, p1)
    o4 = _orientation(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p3, p2):
        return True
    if o2 == 0 and _on_segment(p1, p4, p2):
        return True
    if o3 == 0 and _on_segment(p3, p1, p4):
        return True
    return o4 == 0 and _on_segment(p3, p2, p4)


def self_intersection_count(coords: Sequence[Coord]) -> int:
    """Count proper crossings between non-adjacent segments.

    Segments are bucketed onto a uniform grid first, so only pairs whose bounding
    boxes can possibly overlap are handed to ``segments_intersect``. The result is
    identical to an all-pairs scan.
    """
    simplified = [coords[0]]
    for point in coords[1:]:
        if point != simplified[-1]:
            simplified.append(point)
    count = len(simplified) - 1
    if count < 3:
        return 0

    cell = 0.0005
    grid: dict[tuple[int, int], list[int]] = {}
    boxes: list[tuple[float, float, float, float]] = []
    for i in range(count):
        x0, y0 = simplified[i]
        x1, y1 = simplified[i + 1]
        west, east = (x0, x1) if x0 <= x1 else (x1, x0)
        south, north = (y0, y1) if y0 <= y1 else (y1, y0)
        boxes.append((west, south, east, north))
        for gx in range(math.floor(west / cell), math.floor(east / cell) + 1):
            for gy in range(math.floor(south / cell), math.floor(north / cell) + 1):
                grid.setdefault((gx, gy), []).append(i)

    tested: set[tuple[int, int]] = set()
    hits = 0
    for bucket in grid.values():
        if len(bucket) < 2:
            continue
        for a_index in range(len(bucket)):
            i = bucket[a_index]
            for b_index in range(a_index + 1, len(bucket)):
                j = bucket[b_index]
                low, high = (i, j) if i < j else (j, i)
                if high - low < 2 or (low, high) in tested:
                    continue
                if low == 0 and high == count - 1:
                    continue
                tested.add((low, high))
                west_a, south_a, east_a, north_a = boxes[low]
                west_b, south_b, east_b, north_b = boxes[high]
                if east_a < west_b or east_b < west_a:
                    continue
                if north_a < south_b or north_b < south_a:
                    continue
                if segments_intersect(
                    simplified[low],
                    simplified[low + 1],
                    simplified[high],
                    simplified[high + 1],
                ):
                    hits += 1
    return hits


def turn_angles_deg(coords: Sequence[Coord]) -> list[float]:
    angles: list[float] = []
    for i in range(1, len(coords) - 1):
        ax, ay = coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1]
        bx, by = coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1]
        na = math.hypot(ax, ay)
        nb = math.hypot(bx, by)
        if na == 0 or nb == 0:
            continue
        cos_theta = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
        angles.append(math.degrees(math.acos(cos_theta)))
    return angles


def retrace_segments(coords: Sequence[Coord], min_leg_m: float = 15.0, close_m: float = 10.0) -> int:
    """Count U-turn style local retraces: a leg that returns to where it started."""
    hits = 0
    for i in range(len(coords) - 2):
        leg = haversine_m(coords[i], coords[i + 1])
        if leg < min_leg_m:
            continue
        if haversine_m(coords[i], coords[i + 2]) < close_m:
            hits += 1
    return hits


def local_return_loops(
    coords: Sequence[Coord],
    min_path_m: float = 200.0,
    close_m: float = 20.0,
    closure_margin_m: float = 75.0,
) -> int:
    """Count sub-paths that leave and come back to nearly the same point."""
    dense_index = list(range(len(coords)))
    hits = 0
    for i in dense_index:
        travelled = 0.0
        for j in range(i + 1, len(coords)):
            travelled += haversine_m(coords[j - 1], coords[j])
            if travelled < min_path_m:
                continue
            if travelled > min_path_m * 4:
                break
            if haversine_m(coords[i], coords[j]) < close_m:
                closure = travelled - haversine_m(coords[i], coords[j])
                if closure > closure_margin_m:
                    hits += 1
                break
    return hits


def repeated_undirected_edges(coords: Sequence[Coord], tolerance_deg: float = 1e-7) -> tuple[int, float, float]:
    """Return (repeat count, cumulative repeated length m, longest single repeat m)."""
    seen: dict[tuple[tuple[int, int], tuple[int, int]], float] = {}
    repeats = 0
    repeated_length = 0.0
    longest = 0.0
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        length = haversine_m(a, b)
        if length < 0.5:
            continue
        ka = (round(a[0] / tolerance_deg), round(a[1] / tolerance_deg))
        kb = (round(b[0] / tolerance_deg), round(b[1] / tolerance_deg))
        edge = (ka, kb) if ka <= kb else (kb, ka)
        if edge in seen:
            repeats += 1
            repeated_length += length
            longest = max(longest, length)
        else:
            seen[edge] = length
    return repeats, repeated_length, longest


def circuity(coords: Sequence[Coord]) -> float:
    straight = haversine_m(coords[0], coords[-1])
    if straight < 1e-6:
        return 1.0
    return polyline_length_m(coords) / straight


def endpoint_offset_m(coords: Sequence[Coord]) -> float:
    return haversine_m(coords[0], coords[-1])


def bearings_deg(coords: Sequence[Coord], count: int = 8) -> list[tuple[Coord, float]]:
    """Direction arrows sampled along the route, for run and bike display."""
    if len(coords) < 2:
        return []
    total = polyline_length_m(coords)
    if total <= 0:
        return []
    targets = [total * (i + 1) / (count + 1) for i in range(count)]
    out: list[tuple[Coord, float]] = []
    travelled = 0.0
    index = 0
    for target in targets:
        while index < len(coords) - 1:
            a, b = coords[index], coords[index + 1]
            segment = haversine_m(a, b)
            if travelled + segment >= target and segment > 0:
                t = (target - travelled) / segment
                point = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                bearing = math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360.0
                out.append((point, bearing))
                break
            travelled += segment
            index += 1
    return out


def ring_area_deg2(ring: Ring) -> float:
    total = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def isoperimetric_ratio(coords: Sequence[Coord]) -> float:
    """perimeter^2 / area in a local metric frame. Circle ~= 4*pi; dumbbells are much larger."""
    if len(coords) < 4:
        return float("inf")
    lat0 = math.radians(coords[0][1])
    metric = [(c[0] * math.cos(lat0) * 111320.0, c[1] * 110540.0) for c in coords]
    area = ring_area_deg2(metric)
    perimeter = 0.0
    for i in range(len(metric) - 1):
        perimeter += math.hypot(metric[i + 1][0] - metric[i][0], metric[i + 1][1] - metric[i][1])
    if area <= 0:
        return float("inf")
    return perimeter * perimeter / area


def _segment_grid(
    dense: Sequence[Coord], cell_lon: float, cell_lat: float
) -> dict[tuple[int, int], list[int]]:
    """Bucket each segment index of ``dense`` into every cell its bbox touches."""
    grid: dict[tuple[int, int], list[int]] = {}
    for i in range(len(dense) - 1):
        lon0, lat0 = dense[i]
        lon1, lat1 = dense[i + 1]
        x0 = math.floor(min(lon0, lon1) / cell_lon)
        x1 = math.floor(max(lon0, lon1) / cell_lon)
        y0 = math.floor(min(lat0, lat1) / cell_lat)
        y1 = math.floor(max(lat0, lat1) / cell_lat)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                grid.setdefault((gx, gy), []).append(i)
    return grid


def overlap_ratio(a: Sequence[Coord], b: Sequence[Coord], tolerance_m: float = 25.0) -> float:
    """Share of route ``a`` that runs within ``tolerance_m`` of route ``b``."""
    dense = resample(a, 30.0)
    dense_b = resample(b, 30.0)
    if len(dense) < 2:
        return 0.0
    #: Cells one tolerance wide keep the 3x3 lookup exact rather than approximate:
    #: a segment within tolerance of a query point has its nearest point inside the
    #: tolerance box around it, and that box cannot reach past the eight neighbours.
    #: The full scan is ``len(dense) * len(dense_b)``, which on a 25 km bike arc is
    #: ~833 * ~833 per direction and made the sibling screen unusable in the sweep.
    lat_ref = max((abs(c[1]) for c in dense_b), default=0.0)
    metres_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_ref))
    cell_lon = tolerance_m / max(metres_per_deg_lon, 1.0)
    cell_lat = tolerance_m / 110_540.0
    grid = _segment_grid(dense_b, cell_lon, cell_lat)
    near = 0
    for point in dense:
        gx = math.floor(point[0] / cell_lon)
        gy = math.floor(point[1] / cell_lat)
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(grid.get((gx + dx, gy + dy), ()))
        if any(
            point_to_segment_distance_m(point, dense_b[i], dense_b[i + 1]) <= tolerance_m
            for i in candidates
        ):
            near += 1
    return near / len(dense)


def centroid(coords: Sequence[Coord]) -> Coord:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (sum(lons) / len(lons), sum(lats) / len(lats))


def round_coord(value: float, digits: int = 6) -> float:
    return round(value, digits)


def to_geojson_coords(coords: Sequence[Coord], digits: int = 6) -> list[list[float]]:
    return [[round_coord(lon, digits), round_coord(lat, digits)] for lon, lat in coords]
