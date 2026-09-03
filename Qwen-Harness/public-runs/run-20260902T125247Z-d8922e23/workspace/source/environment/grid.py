"""Deterministic 6x9 environment grid over the Xuhui bbox.

All metrics are computed purely from the local OSM payloads: no network, no
randomness. Geometry uses a local equirectangular projection in metres with
the same constants as ``routes.geometry`` (111320 m per degree of longitude at
the equator scaled by cos(lat0), 110540 m per degree of latitude).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from routes.geometry import haversine_m, normalise_crs, point_in_ring

from .contract import CANONICAL_CRS, GRID_CELL_COUNT, GRID_COLS, GRID_ROWS

Coord = tuple[float, float]

M_PER_DEG_LON_EQUATOR = 111320.0
M_PER_DEG_LAT = 110540.0

MAJOR_HIGHWAY_VALUES = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
    }
)

GREEN_TAG_MATCHES: tuple[tuple[str, frozenset[str]], ...] = (
    ("leisure", frozenset({"park", "garden", "nature_reserve"})),
    ("landuse", frozenset({"grass", "meadow", "forest", "recreation_ground"})),
    ("natural", frozenset({"wood", "scrub", "grassland"})),
)

WATER_TAG_MATCHES: tuple[tuple[str, frozenset[str] | None], ...] = (
    ("natural", frozenset({"water", "coastline"})),
    ("water", None),
    ("landuse", frozenset({"reservoir", "basin"})),
)

TRAFFIC_SATURATION_KM_PER_KM2 = 20.0
NOISE_BASE_DB = 38.0
NOISE_MAJOR_COEFF = 12.0
NOISE_TOTAL_COEFF = 4.0
NOISE_CLIP_MIN_DB = 35.0
NOISE_CLIP_MAX_DB = 85.0


@dataclass
class Cell:
    """One grid cell: identity, extent and boundary membership."""

    cell_id: str
    row: int
    col: int
    bbox: tuple[float, float, float, float]
    center: Coord
    inside_district: bool


@dataclass
class CellMetrics:
    """Deterministic OSM-derived metrics for one cell."""

    green_ratio_0_1: float
    water_ratio_0_1: float
    road_density_km_per_km2: float
    major_road_density_km_per_km2: float
    traffic_exposure_0_1: float
    noise_proxy_db: float


@dataclass
class Grid:
    """Row-major grid; row 0 is the northernmost row."""

    west: float
    south: float
    east: float
    north: float
    rows: int
    cols: int
    dlon: float
    dlat: float
    lat0: float
    cell_area_km2: float
    cells: list[Cell] = field(default_factory=list)

    def locate(self, lon: float, lat: float) -> int | None:
        """Flat index of the cell containing (lon, lat), or None outside."""
        if lon < self.west or lon > self.east or lat < self.south or lat > self.north:
            return None
        col = int((lon - self.west) / self.dlon)
        row = int((self.north - lat) / self.dlat)
        col = min(max(col, 0), self.cols - 1)
        row = min(max(row, 0), self.rows - 1)
        return row * self.cols + col


def _project(lon: float, lat: float, lat0_rad: float) -> Coord:
    return (lon * math.cos(lat0_rad) * M_PER_DEG_LON_EQUATOR, lat * M_PER_DEG_LAT)


def shoelace_area_m2(points_m: list[Coord]) -> float:
    """Absolute polygon area in m2 via the shoelace formula."""
    total = 0.0
    count = len(points_m)
    for i in range(count):
        x0, y0 = points_m[i]
        x1, y1 = points_m[(i + 1) % count]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def load_boundary(path: Path) -> tuple[list[Coord], tuple[float, float, float, float]]:
    """Return the district ring and bbox from the boundary GeoJSON."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    feature = payload["features"][0]
    declared = str(feature.get("properties", {}).get("crs", CANONICAL_CRS))
    if normalise_crs(declared) != normalise_crs(CANONICAL_CRS):
        msg = f"boundary CRS {declared!r} differs from run CRS {CANONICAL_CRS!r}"
        raise ValueError(msg)
    ring_raw = feature["geometry"]["coordinates"][0]
    ring: list[Coord] = [(float(pair[0]), float(pair[1])) for pair in ring_raw]
    bbox_raw = feature["properties"]["bbox"]
    bbox: tuple[float, float, float, float] = (
        float(bbox_raw[0]),
        float(bbox_raw[1]),
        float(bbox_raw[2]),
        float(bbox_raw[3]),
    )
    return ring, bbox


def build_grid(ring: list[Coord], bbox: tuple[float, float, float, float]) -> Grid:
    """Build the 54-cell grid and mark cells whose centre is in the district."""
    west, south, east, north = bbox
    dlon = (east - west) / GRID_COLS
    dlat = (north - south) / GRID_ROWS
    lat0 = (south + north) / 2.0
    width_m = dlon * math.cos(math.radians(lat0)) * M_PER_DEG_LON_EQUATOR
    height_m = dlat * M_PER_DEG_LAT
    grid = Grid(
        west=west,
        south=south,
        east=east,
        north=north,
        rows=GRID_ROWS,
        cols=GRID_COLS,
        dlon=dlon,
        dlat=dlat,
        lat0=lat0,
        cell_area_km2=width_m * height_m / 1_000_000.0,
    )
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            cell_west = west + col * dlon
            cell_east = cell_west + dlon
            cell_north = north - row * dlat
            cell_south = cell_north - dlat
            center = ((cell_west + cell_east) / 2.0, (cell_south + cell_north) / 2.0)
            grid.cells.append(
                Cell(
                    cell_id=f"ENV_{row * GRID_COLS + col + 1:03d}",
                    row=row,
                    col=col,
                    bbox=(cell_west, cell_south, cell_east, cell_north),
                    center=center,
                    inside_district=point_in_ring(center, ring),
                )
            )
    if len(grid.cells) != GRID_CELL_COUNT:
        msg = f"grid built {len(grid.cells)} cells, expected {GRID_CELL_COUNT}"
        raise ValueError(msg)
    return grid


def _bbox_overlaps_grid(
    grid: Grid, box: tuple[float, float, float, float]
) -> bool:
    return not (box[2] < grid.west or box[0] > grid.east or box[3] < grid.south or box[1] > grid.north)


def _way_coords(element: dict[str, Any]) -> list[Coord] | None:
    geometry = element.get("geometry")
    if not isinstance(geometry, list) or len(geometry) < 2:
        return None
    coords: list[Coord] = []
    for point in geometry:
        if not isinstance(point, dict):
            return None
        coords.append((float(point["lon"]), float(point["lat"])))
    return coords


def _matches_tags(tags: dict[str, Any], matches: tuple[tuple[str, frozenset[str] | None], ...]) -> bool:
    for key, allowed in matches:
        value = tags.get(key)
        if value is None:
            continue
        if allowed is None or str(value) in allowed:
            return True
    return False


def _accumulate_road_lengths(
    grid: Grid, highway_payload: dict[str, Any]
) -> tuple[list[float], list[float]]:
    road_km = [0.0] * GRID_CELL_COUNT
    major_km = [0.0] * GRID_CELL_COUNT
    for element in highway_payload.get("elements", []):
        if element.get("type") != "way":
            continue
        coords = _way_coords(element)
        if coords is None:
            continue
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        if not _bbox_overlaps_grid(grid, (min(lons), min(lats), max(lons), max(lats))):
            continue
        tags = element.get("tags", {})
        is_major = str(tags.get("highway", "")) in MAJOR_HIGHWAY_VALUES
        for i in range(len(coords) - 1):
            a, b = coords[i], coords[i + 1]
            index = grid.locate((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            if index is None:
                continue
            length_km = haversine_m(a, b) / 1000.0
            road_km[index] += length_km
            if is_major:
                major_km[index] += length_km
    return road_km, major_km


def _accumulate_polygon_areas(
    grid: Grid, poi_payload: dict[str, Any]
) -> tuple[list[float], list[float], dict[str, int]]:
    """Distribute polygon areas over cells by vertex+midpoint hit fractions."""
    green_m2 = [0.0] * GRID_CELL_COUNT
    water_m2 = [0.0] * GRID_CELL_COUNT
    counts = {"green_ways": 0, "water_ways": 0, "green_nodes_ignored": 0, "water_nodes_ignored": 0}
    lat0_rad = math.radians(grid.lat0)
    for element in poi_payload.get("elements", []):
        tags = element.get("tags", {})
        is_green = _matches_tags(tags, GREEN_TAG_MATCHES)
        is_water = not is_green and _matches_tags(tags, WATER_TAG_MATCHES)
        if not is_green and not is_water:
            continue
        if element.get("type") != "way":
            if is_green:
                counts["green_nodes_ignored"] += 1
            else:
                counts["water_nodes_ignored"] += 1
            continue
        coords = _way_coords(element)
        if coords is None or len(coords) < 4 or coords[0] != coords[-1]:
            continue
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        if not _bbox_overlaps_grid(grid, (min(lons), min(lats), max(lons), max(lats))):
            continue
        ring = coords[:-1]
        projected = [_project(lon, lat, lat0_rad) for lon, lat in ring]
        area_m2 = shoelace_area_m2(projected)
        if area_m2 <= 0.0:
            continue
        hits = [0] * GRID_CELL_COUNT
        total_points = 0
        count = len(ring)
        for i in range(count):
            test_points = [ring[i], ((ring[i][0] + ring[(i + 1) % count][0]) / 2.0, (ring[i][1] + ring[(i + 1) % count][1]) / 2.0)]
            for test_point in test_points:
                total_points += 1
                index = grid.locate(test_point[0], test_point[1])
                if index is not None:
                    hits[index] += 1
        if total_points == 0:
            continue
        target = green_m2 if is_green else water_m2
        for index, hit in enumerate(hits):
            if hit:
                target[index] += area_m2 * hit / total_points
        if is_green:
            counts["green_ways"] += 1
        else:
            counts["water_ways"] += 1
    return green_m2, water_m2, counts


def traffic_exposure_from_density(major_density_km_per_km2: float) -> float:
    """Fixed documented scale: saturates at 20 km of major road per km2."""
    return min(1.0, max(0.0, major_density_km_per_km2 / TRAFFIC_SATURATION_KM_PER_KM2))


def noise_proxy_from_densities(
    major_density_km_per_km2: float, road_density_km_per_km2: float
) -> float:
    """Deterministic log proxy in dB, clipped to 35..85; NOT a measured level."""
    raw = (
        NOISE_BASE_DB
        + NOISE_MAJOR_COEFF * math.log10(1.0 + max(0.0, major_density_km_per_km2))
        + NOISE_TOTAL_COEFF * math.log10(1.0 + max(0.0, road_density_km_per_km2))
    )
    return min(NOISE_CLIP_MAX_DB, max(NOISE_CLIP_MIN_DB, raw))


def compute_cell_metrics(
    grid: Grid, highways_path: Path, pois_path: Path
) -> tuple[list[CellMetrics], dict[str, int]]:
    """Compute all six OSM-derived metrics per cell from the local payloads."""
    highway_payload: dict[str, Any] = json.loads(highways_path.read_text(encoding="utf-8"))
    declared = str(highway_payload.get("crs", CANONICAL_CRS))
    if normalise_crs(declared) != normalise_crs(CANONICAL_CRS):
        msg = f"highways CRS {declared!r} differs from run CRS {CANONICAL_CRS!r}"
        raise ValueError(msg)
    poi_payload: dict[str, Any] = json.loads(pois_path.read_text(encoding="utf-8"))

    road_km, major_km = _accumulate_road_lengths(grid, highway_payload)
    green_m2, water_m2, counts = _accumulate_polygon_areas(grid, poi_payload)

    cell_area_m2 = grid.cell_area_km2 * 1_000_000.0
    metrics: list[CellMetrics] = []
    for index in range(GRID_CELL_COUNT):
        road_density = road_km[index] / grid.cell_area_km2
        major_density = major_km[index] / grid.cell_area_km2
        metrics.append(
            CellMetrics(
                green_ratio_0_1=green_m2[index] / cell_area_m2,
                water_ratio_0_1=water_m2[index] / cell_area_m2,
                road_density_km_per_km2=road_density,
                major_road_density_km_per_km2=major_density,
                traffic_exposure_0_1=traffic_exposure_from_density(major_density),
                noise_proxy_db=noise_proxy_from_densities(major_density, road_density),
            )
        )
    return metrics, counts
