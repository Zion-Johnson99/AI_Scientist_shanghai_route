"""Route environment association module.

Maps grid/station environmental data to 90 routes, computing per-route
exposure values for pm2_5, noise, and pollen_daily.

Data semantics:
- PM2.5: grid/station fusion estimate, not per-address observation.
- Noise: 0-100 risk proxy, not measured decibels.
- Pollen: daily background/proxy indicator, not real-time concentration.

Missing values are marked as estimated=True rather than filled with
synthetic data.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentValue:
    """A single environment measurement with metadata."""

    value: float | None
    unit: str
    estimated: bool
    confidence: str = "medium"
    spatial_scale: str = "grid"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "unit": self.unit,
            "estimated": self.estimated,
            "confidence": self.confidence,
            "spatial_scale": self.spatial_scale,
        }
        if self.value is not None:
            result["value"] = self.value
        else:
            result["value"] = None
        return result


@dataclass
class RouteEnvironmentRecord:
    """Environment exposure record for a single route."""

    route_id: str
    pm2_5: EnvironmentValue
    noise: EnvironmentValue
    pollen_daily: EnvironmentValue

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "pm2_5": self.pm2_5.to_dict(),
            "noise": self.noise.to_dict(),
            "pollen_daily": self.pollen_daily.to_dict(),
        }


@dataclass
class GridCell:
    """A grid cell with environmental measurements."""

    cell_id: str
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float
    pm2_5: float | None = None
    noise: float | None = None
    pollen_daily: float | None = None
    pm2_5_estimated: bool = False
    noise_estimated: bool = False
    pollen_estimated: bool = False


@dataclass
class StationReading:
    """A monitoring station reading."""

    station_id: str
    lat: float
    lng: float
    pm2_5: float | None = None
    confidence: str = "medium"


@dataclass
class RouteEnvironmentResult:
    """Result of mapping environment data to routes."""

    records: list[RouteEnvironmentRecord] = field(default_factory=list)
    missing_count: int = 0
    estimated_count: int = 0
    total_routes: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "missing_count": self.missing_count,
            "estimated_count": self.estimated_count,
            "total_routes": self.total_routes,
            "warnings": self.warnings,
        }


def _point_in_cell(lat: float, lng: float, cell: GridCell) -> bool:
    """Check if a point falls within a grid cell."""
    return (
        cell.lat_min <= lat <= cell.lat_max
        and cell.lng_min <= lng <= cell.lng_max
    )


def _nearest_station(
    lat: float, lng: float, stations: list[StationReading]
) -> StationReading | None:
    """Find the nearest station to a point using simple Euclidean distance."""
    if not stations:
        return None
    best: StationReading | None = None
    best_dist = float("inf")
    for station in stations:
        dist = (station.lat - lat) ** 2 + (station.lng - lng) ** 2
        if dist < best_dist:
            best_dist = dist
            best = station
    return best


def _route_centroid(coordinates: list[list[float]]) -> tuple[float, float]:
    """Compute the centroid of a route's coordinates.

    Coordinates are in [lng, lat] order (GeoJSON convention).
    Returns (lat, lng).
    """
    if not coordinates:
        return (0.0, 0.0)
    lng_sum = sum(c[0] for c in coordinates)
    lat_sum = sum(c[1] for c in coordinates)
    n = len(coordinates)
    return (lat_sum / n, lng_sum / n)


def _sample_route_points(
    coordinates: list[list[float]], max_samples: int = 5
) -> list[tuple[float, float]]:
    """Sample up to max_samples points along a route.

    Returns list of (lat, lng) tuples.
    """
    if not coordinates:
        return []
    if len(coordinates) <= max_samples:
        return [(c[1], c[0]) for c in coordinates]
    step = len(coordinates) / max_samples
    points: list[tuple[float, float]] = []
    for i in range(max_samples):
        idx = int(i * step)
        points.append((coordinates[idx][1], coordinates[idx][0]))
    return points


def compute_route_environment(
    route_catalog: list[dict[str, Any]],
    geojson_features: list[dict[str, Any]],
    grid_cells: list[GridCell] | None = None,
    stations: list[StationReading] | None = None,
    default_pm25: float | None = None,
    default_noise: float | None = None,
    default_pollen: float | None = None,
) -> RouteEnvironmentResult:
    """Map environmental data to routes.

    For each route, samples points along the geometry and aggregates
    environmental values from grid cells or nearest stations.

    Args:
        route_catalog: List of route entries from route_catalog.json.
        geojson_features: List of GeoJSON features from xuhui_routes.geojson.
        grid_cells: Optional grid cells with environmental data.
        stations: Optional monitoring stations.
        default_pm25: Fallback PM2.5 value when no grid/station data available.
        default_noise: Fallback noise value when no grid/station data available.
        default_pollen: Fallback pollen value when no grid/station data available.

    Returns:
        RouteEnvironmentResult with per-route environment records.
    """
    if grid_cells is None:
        grid_cells = []
    if stations is None:
        stations = []

    # Build route_id -> coordinates mapping from GeoJSON
    route_coords: dict[str, list[list[float]]] = {}
    for feature in geojson_features:
        props = feature.get("properties", {})
        route_id = props.get("route_id", "")
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])
        if route_id and coords:
            route_coords[route_id] = coords

    result = RouteEnvironmentResult(total_routes=len(route_catalog))

    for route_entry in route_catalog:
        route_id = route_entry.get("route_id", "")
        if not route_id:
            result.warnings.append("Route entry missing route_id, skipped")
            continue

        coordinates = route_coords.get(route_id, [])
        if not coordinates:
            result.warnings.append(
                f"Route {route_id} has no geometry coordinates"
            )
            # Still produce a record with all-estimated values
            pm25_val = EnvironmentValue(
                value=default_pm25,
                unit="\u00b5g/m\u00b3",
                estimated=True,
                confidence="low",
                spatial_scale="grid",
            )
            noise_val = EnvironmentValue(
                value=default_noise,
                unit="0-100 proxy",
                estimated=True,
                confidence="low",
                spatial_scale="grid",
            )
            pollen_val = EnvironmentValue(
                value=default_pollen,
                unit="index",
                estimated=True,
                confidence="low",
                spatial_scale="daily_background",
            )
            record = RouteEnvironmentRecord(
                route_id=route_id,
                pm2_5=pm25_val,
                noise=noise_val,
                pollen_daily=pollen_val,
            )
            result.records.append(record)
            result.estimated_count += 1
            if default_pm25 is None or default_noise is None or default_pollen is None:
                result.missing_count += 1
            continue

        # Sample points along the route
        sample_points = _sample_route_points(coordinates)

        # Aggregate PM2.5 from grid cells or stations
        pm25_values: list[float] = []
        noise_values: list[float] = []
        pollen_values: list[float] = []
        pm25_estimated = False
        noise_estimated = False
        pollen_estimated = False

        for lat, lng in sample_points:
            # Try grid cells first
            matched_cell: GridCell | None = None
            for cell in grid_cells:
                if _point_in_cell(lat, lng, cell):
                    matched_cell = cell
                    break

            if matched_cell is not None:
                if matched_cell.pm2_5 is not None:
                    pm25_values.append(matched_cell.pm2_5)
                    if matched_cell.pm2_5_estimated:
                        pm25_estimated = True
                if matched_cell.noise is not None:
                    noise_values.append(matched_cell.noise)
                    if matched_cell.noise_estimated:
                        noise_estimated = True
                if matched_cell.pollen_daily is not None:
                    pollen_values.append(matched_cell.pollen_daily)
                    if matched_cell.pollen_estimated:
                        pollen_estimated = True
            else:
                # Fall back to nearest station for PM2.5
                nearest = _nearest_station(lat, lng, stations)
                if nearest is not None and nearest.pm2_5 is not None:
                    pm25_values.append(nearest.pm2_5)
                    pm25_estimated = True  # station interpolation is estimated
                else:
                    pm25_estimated = True

                # No grid match: mark as estimated
                noise_estimated = True
                pollen_estimated = True

        # Compute final values
        if pm25_values:
            pm25_final = sum(pm25_values) / len(pm25_values)
        elif default_pm25 is not None:
            pm25_final = default_pm25
            pm25_estimated = True
        else:
            pm25_final = None
            pm25_estimated = True

        if noise_values:
            noise_final = sum(noise_values) / len(noise_values)
        elif default_noise is not None:
            noise_final = default_noise
            noise_estimated = True
        else:
            noise_final = None
            noise_estimated = True

        if pollen_values:
            pollen_final = sum(pollen_values) / len(pollen_values)
        elif default_pollen is not None:
            pollen_final = default_pollen
            pollen_estimated = True
        else:
            pollen_final = None
            pollen_estimated = True

        # Determine confidence
        pm25_confidence = "high" if (pm25_values and not pm25_estimated) else (
            "medium" if pm25_values else "low"
        )
        noise_confidence = "high" if (noise_values and not noise_estimated) else (
            "medium" if noise_values else "low"
        )
        pollen_confidence = "high" if (pollen_values and not pollen_estimated) else (
            "medium" if pollen_values else "low"
        )

        pm25_env = EnvironmentValue(
            value=round(pm25_final, 1) if pm25_final is not None else None,
            unit="\u00b5g/m\u00b3",
            estimated=pm25_estimated,
            confidence=pm25_confidence,
            spatial_scale="grid",
        )
        noise_env = EnvironmentValue(
            value=round(noise_final, 1) if noise_final is not None else None,
            unit="0-100 proxy",
            estimated=noise_estimated,
            confidence=noise_confidence,
            spatial_scale="grid",
        )
        pollen_env = EnvironmentValue(
            value=round(pollen_final, 1) if pollen_final is not None else None,
            unit="index",
            estimated=pollen_estimated,
            confidence=pollen_confidence,
            spatial_scale="daily_background",
        )

        record = RouteEnvironmentRecord(
            route_id=route_id,
            pm2_5=pm25_env,
            noise=noise_env,
            pollen_daily=pollen_env,
        )
        result.records.append(record)

        if pm25_estimated or noise_estimated or pollen_estimated:
            result.estimated_count += 1
        if pm25_final is None or noise_final is None or pollen_final is None:
            result.missing_count += 1

    return result


def build_default_grid_cells() -> list[GridCell]:
    """Build default grid cells covering Xuhui district.

    These are synthetic grid cells for offline/demo use.
    PM2.5 values are grid/station fusion estimates, not per-address observations.
    Noise values are 0-100 risk proxies, not measured decibels.
    Pollen values are daily background/proxy indicators.
    """
    # Xuhui district approximate bounds: lat 31.12-31.22, lng 121.38-121.50
    cells: list[GridCell] = []
    lat_steps = 5
    lng_steps = 6
    lat_min_base = 31.12
    lat_max_base = 31.22
    lng_min_base = 121.38
    lng_max_base = 121.50

    lat_step = (lat_max_base - lat_min_base) / lat_steps
    lng_step = (lng_max_base - lng_min_base) / lng_steps

    # Deterministic pseudo-values based on cell position
    import random
    rng = random.Random(1234)

    for i in range(lat_steps):
        for j in range(lng_steps):
            cell_id = f"xuhui_grid_{i}_{j}"
            lat_lo = lat_min_base + i * lat_step
            lat_hi = lat_lo + lat_step
            lng_lo = lng_min_base + j * lng_step
            lng_hi = lng_lo + lng_step

            # PM2.5: typical urban range 15-65 \u00b5g/m\u00b3
            pm25 = round(rng.uniform(15.0, 65.0), 1)
            # Noise: 0-100 proxy, typical urban range 30-80
            noise = round(rng.uniform(30.0, 80.0), 1)
            # Pollen: daily index 0-10
            pollen = round(rng.uniform(0.5, 8.0), 1)

            cells.append(GridCell(
                cell_id=cell_id,
                lat_min=lat_lo,
                lat_max=lat_hi,
                lng_min=lng_lo,
                lng_max=lng_hi,
                pm2_5=pm25,
                noise=noise,
                pollen_daily=pollen,
                pm2_5_estimated=True,
                noise_estimated=True,
                pollen_estimated=True,
            ))

    return cells


def generate_route_environment(
    route_catalog_path: Path,
    geojson_path: Path,
    grid_cells: list[GridCell] | None = None,
    stations: list[StationReading] | None = None,
) -> RouteEnvironmentResult:
    """Load route data and compute environment for all routes.

    Args:
        route_catalog_path: Path to route_catalog.json.
        geojson_path: Path to xuhui_routes.geojson.
        grid_cells: Optional grid cells. If None, uses default Xuhui grid.
        stations: Optional monitoring stations.

    Returns:
        RouteEnvironmentResult with 90 route environment records.

    Raises:
        FileNotFoundError: If route_catalog_path or geojson_path does not exist.
        json.JSONDecodeError: If files are not valid JSON.
    """
    if not route_catalog_path.exists():
        raise FileNotFoundError(
            f"Route catalog not found: {route_catalog_path}"
        )
    if not geojson_path.exists():
        raise FileNotFoundError(
            f"GeoJSON not found: {geojson_path}"
        )

    with open(route_catalog_path, "r", encoding="utf-8") as f:
        route_catalog = json.load(f)

    with open(geojson_path, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    features = geojson_data.get("features", [])

    if grid_cells is None:
        grid_cells = build_default_grid_cells()

    result = compute_route_environment(
        route_catalog=route_catalog,
        geojson_features=features,
        grid_cells=grid_cells,
        stations=stations,
    )

    return result


def records_to_dashboard_items(
    records: list[RouteEnvironmentRecord],
) -> list[dict[str, Any]]:
    """Convert route environment records to dashboard items format.

    Each item contains route_id, pm2_5, noise, pollen_daily with
    value/unit/estimated fields as required by the dashboard contract.
    """
    items: list[dict[str, Any]] = []
    for record in records:
        item: dict[str, Any] = {
            "route_id": record.route_id,
            "pm2_5": record.pm2_5.to_dict(),
            "noise": record.noise.to_dict(),
            "pollen_daily": record.pollen_daily.to_dict(),
        }
        items.append(item)
    return items
