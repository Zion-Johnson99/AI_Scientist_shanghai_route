"""Length-weighted route exposure over the environment grid.

Each route LineString is resampled to ~50 m steps; every resampled segment is
attributed to the cell containing its midpoint, which yields ordered unique
cell ids and per-cell metre weights for the exposure means.
"""

from __future__ import annotations

from typing import Any

from routes.geometry import haversine_m, resample

from .contract import (
    CANONICAL_UNITS,
    FIELD_KEYS,
    FIELD_PROVENANCE,
    RISK_THRESHOLDS,
    RiskLevel,
    risk_level,
    worst_risk,
)
from .grid import Coord, Grid

RESAMPLE_STEP_M = 50.0

STATUS_SEVERITY: dict[str, int] = {
    "measured": 0,
    "derived": 1,
    "estimated": 2,
    "unavailable": 3,
}


def route_cell_weights(
    coords: list[Coord], grid: Grid
) -> tuple[list[str], dict[str, float]]:
    """Ordered unique cell ids plus metres of route inside each cell."""
    dense = resample(coords, RESAMPLE_STEP_M)
    ordered: list[str] = []
    weights: dict[str, float] = {}
    for i in range(len(dense) - 1):
        a, b = dense[i], dense[i + 1]
        index = grid.locate((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if index is None:
            continue
        cell_id = grid.cells[index].cell_id
        if cell_id not in weights:
            ordered.append(cell_id)
            weights[cell_id] = 0.0
        weights[cell_id] += haversine_m(a, b)
    return ordered, weights


def _merge_field(
    field_key: str,
    weights: dict[str, float],
    cell_values: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    numerator = 0.0
    denominator = 0.0
    worst_status = "measured"
    provenance = FIELD_PROVENANCE[field_key]
    as_of: str | None = None
    for cell_id, weight in weights.items():
        entry = cell_values.get(cell_id, {}).get(field_key, {})
        value = entry.get("value")
        if value is None:
            continue
        numerator += float(value) * weight
        denominator += weight
        status = str(entry.get("status", "unavailable"))
        if STATUS_SEVERITY.get(status, 3) > STATUS_SEVERITY.get(worst_status, 0):
            worst_status = status
        if as_of is None and isinstance(entry.get("as_of"), str):
            as_of = entry["as_of"]
    result: dict[str, Any] = {
        "unit": CANONICAL_UNITS[field_key],
        "provenance": provenance,
        "aggregation": "length_weighted_mean",
        "as_of": as_of,
    }
    if denominator > 0.0:
        result["value"] = round(numerator / denominator, 4)
        result["status"] = worst_status
    else:
        result["value"] = None
        result["status"] = "unavailable"
        result["missing_reason"] = "public_api_unreachable"
    return result


def build_route_exposure(
    route_id: str,
    mode: str,
    coords: list[Coord],
    grid: Grid,
    cell_values: dict[str, dict[str, dict[str, Any]]],
    data_generated_at: str,
) -> dict[str, Any]:
    """Full exposure record for one route."""
    ordered, weights = route_cell_weights(coords, grid)
    exposure: dict[str, Any] = {}
    risk: dict[str, RiskLevel] = {}
    missing_fields: list[str] = []
    for field_key in FIELD_KEYS:
        merged = _merge_field(field_key, weights, cell_values)
        exposure[field_key] = merged
        if merged["value"] is None:
            missing_fields.append(field_key)
        if field_key in RISK_THRESHOLDS:
            value = merged["value"]
            risk[field_key] = risk_level(field_key, None if value is None else float(value))
    overall = worst_risk(list(risk.values()))
    return {
        "route_id": route_id,
        "mode": mode,
        "cell_ids": ordered,
        "cell_count": len(ordered),
        "exposure": exposure,
        "risk": risk,
        "overall_risk": overall,
        "missing_fields": missing_fields,
        "data_generated_at": data_generated_at,
    }


def collect_route_coords(geojson_payload: dict[str, Any]) -> dict[str, list[Coord]]:
    """Map route_id to LineString coordinates from the routes FeatureCollection."""
    coords_by_id: dict[str, list[Coord]] = {}
    features = geojson_payload.get("features")
    if not isinstance(features, list):
        return coords_by_id
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        route_id = properties.get("route_id")
        raw_coords = geometry.get("coordinates")
        if not isinstance(route_id, str) or not isinstance(raw_coords, list):
            continue
        coords_by_id[route_id] = [(float(pair[0]), float(pair[1])) for pair in raw_coords]
    return coords_by_id
