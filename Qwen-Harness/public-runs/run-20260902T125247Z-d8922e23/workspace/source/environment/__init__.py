"""Environment module: 54-cell grid, public weather/AQI data, route exposure.

The dashboard binds one canonical unit/status contract (``contract``) to a
deterministic OSM-derived grid (``grid``), keyless Open-Meteo measurements
(``fetch_public``) and length-weighted route exposure (``exposure``).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from routes.geometry import haversine_m

from .contract import (
    CANONICAL_CRS,
    CANONICAL_UNITS,
    DEFAULT_DASHBOARD_PATH,
    DEFAULT_ROUTE_CATALOG_PATH,
    FIELD_KEYS,
    FIELD_PROVENANCE,
    FIELD_SPECS,
    GRID_CELL_COUNT,
    GRID_COLS,
    GRID_ROWS,
    MEASURED_FIELD_KEYS,
    RISK_THRESHOLDS,
)
from .exposure import build_route_exposure, collect_route_coords
from .fetch_public import (
    AIR_QUALITY_ARTIFACT,
    AIR_QUALITY_FIELD_TO_KEY,
    FORECAST_ARTIFACT,
    FORECAST_FIELD_TO_KEY,
    field_availability,
)
from .grid import Cell, Grid, build_grid, compute_cell_metrics, load_boundary

RUN_ROOT = Path(__file__).resolve().parents[3]
SOURCES_DIR = RUN_ROOT / "sources"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HIGHWAYS_PATH = SOURCES_DIR / "osm_xuhui_highways.json"
DEFAULT_POIS_PATH = SOURCES_DIR / "osm_xuhui_pois.json"
DEFAULT_BOUNDARY_PATH = SOURCES_DIR / "xuhui_boundary.geojson"
DEFAULT_ROUTES_GEOJSON_PATH = (
    SOURCE_ROOT / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"
)

RUN_ID = "run-20260902T125247Z-d8922e23"
MISSING_REASON_UNREACHABLE = "public_api_unreachable"
MISSING_REASON_ALL_NULL = "all_null_in_open_meteo_response"
MISSING_REASON_NULL = "null_in_source_response"

NOISE_NOTE = (
    "noise_proxy_db is a deterministic proxy derived from OSM road densities; "
    "it is NOT a measured sound level."
)


class RouteCatalogMissingError(RuntimeError):
    """Raised when the route catalog artifact has not been generated yet."""


def _parse_iso(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


class PointSeries:
    """Hourly series of one fetched sample point, times as aware UTC."""

    def __init__(
        self,
        name: str,
        lon: float,
        lat: float,
        times: list[datetime],
        values: dict[str, list[float | None]],
    ) -> None:
        self.name = name
        self.lon = lon
        self.lat = lat
        self.times = times
        self.values = values


def _load_service(
    path: Path | None, field_map: dict[str, str]
) -> tuple[list[PointSeries], dict[str, bool], str | None]:
    """Load one saved Open-Meteo wrapper; report per-key availability."""
    unavailable = {key: False for key in field_map.values()}
    if path is None or not path.exists():
        return [], unavailable, MISSING_REASON_UNREACHABLE
    wrapper = _load_json(path)
    response_map = wrapper.get("response")
    if not isinstance(response_map, dict) or not response_map:
        return [], unavailable, MISSING_REASON_UNREACHABLE
    series_list: list[PointSeries] = []
    for name, payload in response_map.items():
        if not isinstance(payload, dict):
            continue
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            continue
        offset_seconds = int(payload.get("utc_offset_seconds", 28800))
        raw_times = hourly.get("time")
        if not isinstance(raw_times, list):
            continue
        times = [
            _parse_iso(str(stamp)) + timedelta(seconds=offset_seconds) for stamp in raw_times
        ]
        values: dict[str, list[float | None]] = {}
        for api_field, key in field_map.items():
            raw_series = hourly.get(api_field)
            if not isinstance(raw_series, list) or len(raw_series) != len(times):
                values[key] = [None] * len(times)
                continue
            values[key] = [
                None if item is None else float(item) for item in raw_series
            ]
        series_list.append(
            PointSeries(
                name=str(name),
                lon=float(payload.get("longitude", 0.0)),
                lat=float(payload.get("latitude", 0.0)),
                times=times,
                values=values,
            )
        )
    available = field_availability(wrapper, field_map)
    reason: str | None = None
    if not series_list:
        reason = MISSING_REASON_UNREACHABLE
    elif not all(available.values()):
        reason = MISSING_REASON_ALL_NULL
    return series_list, available, reason


def _nearest_point(series_list: list[PointSeries], center: tuple[float, float]) -> PointSeries | None:
    if not series_list:
        return None
    return min(series_list, key=lambda s: haversine_m(center, (s.lon, s.lat)))


def _nearest_hour_index(series: PointSeries, target: datetime) -> int:
    return min(
        range(len(series.times)),
        key=lambda i: abs((series.times[i] - target).total_seconds()),
    )


def _measured_value_object(
    key: str,
    series: PointSeries | None,
    target: datetime,
    all_null: bool,
) -> dict[str, Any]:
    unit = CANONICAL_UNITS[key]
    provenance = FIELD_PROVENANCE[key]
    if series is None:
        return {
            "value": None,
            "unit": unit,
            "status": "unavailable",
            "provenance": provenance,
            "as_of": None,
            "missing_reason": MISSING_REASON_UNREACHABLE,
        }
    index = _nearest_hour_index(series, target)
    raw = series.values[key][index] if key in series.values else None
    if raw is None:
        return {
            "value": None,
            "unit": unit,
            "status": "unavailable",
            "provenance": provenance,
            "as_of": series.times[index].isoformat(),
            "missing_reason": MISSING_REASON_ALL_NULL if all_null else MISSING_REASON_NULL,
        }
    return {
        "value": round(raw, 4),
        "unit": unit,
        "status": "measured",
        "provenance": provenance,
        "as_of": series.times[index].isoformat(),
        "source_point": series.name,
    }


def _derived_value_object(key: str, value: float, as_of: str, note: str | None = None) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "value": round(value, 6),
        "unit": CANONICAL_UNITS[key],
        "status": "derived",
        "provenance": FIELD_PROVENANCE[key],
        "as_of": as_of,
    }
    if note is not None:
        obj["note"] = note
    return obj


def _missing_rate(cells: list[dict[str, Any]]) -> dict[str, float]:
    counts = {key: 0 for key in FIELD_KEYS}
    for cell in cells:
        values: dict[str, Any] = cell["values"]
        for key in FIELD_KEYS:
            if values[key]["value"] is None:
                counts[key] += 1
    denominator = len(cells) if cells else 1
    return {key: round(counts[key] / denominator, 4) for key in FIELD_KEYS}


def build_dashboard_from_objects(
    catalog_payload: dict[str, Any],
    routes_geojson_payload: dict[str, Any],
    highways_path: Path,
    boundary_path: Path,
    weather_path: Path | None,
    air_quality_path: Path | None,
    generated_at: str,
    pois_path: Path | None = None,
) -> dict[str, Any]:
    """Assemble the full environment dashboard payload (deterministic)."""
    generated_at_dt = _parse_iso(generated_at)
    ring, district_bbox = load_boundary(boundary_path)
    grid: Grid = build_grid(ring, district_bbox)
    metrics, osm_counts = compute_cell_metrics(
        grid, highways_path, pois_path if pois_path is not None else DEFAULT_POIS_PATH
    )

    forecast_series, forecast_available, forecast_reason = _load_service(
        weather_path, FORECAST_FIELD_TO_KEY
    )
    air_series, air_available, air_reason = _load_service(air_quality_path, AIR_QUALITY_FIELD_TO_KEY)

    excluded_fields: list[dict[str, str]] = []
    for key in FORECAST_FIELD_TO_KEY.values():
        if not forecast_available.get(key, False):
            excluded_fields.append(
                {"key": key, "reason": forecast_reason or MISSING_REASON_UNREACHABLE}
            )
    for key in AIR_QUALITY_FIELD_TO_KEY.values():
        if not air_available.get(key, False):
            excluded_fields.append({"key": key, "reason": air_reason or MISSING_REASON_UNREACHABLE})

    all_null_keys = {entry["key"] for entry in excluded_fields}

    reference_series = forecast_series or air_series
    if reference_series:
        reference_point = _nearest_point(reference_series, (121.4370, 31.1885))
        data_generated_at = reference_point.times[
            _nearest_hour_index(reference_point, generated_at_dt)
        ].isoformat() if reference_point is not None else generated_at
    else:
        data_generated_at = generated_at

    cells: list[dict[str, Any]] = []
    cell_values: dict[str, dict[str, dict[str, Any]]] = {}
    for index in range(GRID_CELL_COUNT):
        cell: Cell = grid.cells[index]
        metric = metrics[index]
        forecast_point = _nearest_point(forecast_series, cell.center)
        air_point = _nearest_point(air_series, cell.center)
        values: dict[str, dict[str, Any]] = {}
        for key in MEASURED_FIELD_KEYS:
            if key in FORECAST_FIELD_TO_KEY.values():
                values[key] = _measured_value_object(
                    key, forecast_point, generated_at_dt, key in all_null_keys
                )
            else:
                values[key] = _measured_value_object(
                    key, air_point, generated_at_dt, key in all_null_keys
                )
        values["green_ratio_0_1"] = _derived_value_object(
            "green_ratio_0_1", metric.green_ratio_0_1, data_generated_at
        )
        values["water_ratio_0_1"] = _derived_value_object(
            "water_ratio_0_1", metric.water_ratio_0_1, data_generated_at
        )
        values["road_density_km_per_km2"] = _derived_value_object(
            "road_density_km_per_km2", metric.road_density_km_per_km2, data_generated_at
        )
        values["major_road_density_km_per_km2"] = _derived_value_object(
            "major_road_density_km_per_km2", metric.major_road_density_km_per_km2, data_generated_at
        )
        values["traffic_exposure_0_1"] = _derived_value_object(
            "traffic_exposure_0_1", metric.traffic_exposure_0_1, data_generated_at
        )
        values["noise_proxy_db"] = _derived_value_object(
            "noise_proxy_db", metric.noise_proxy_db, data_generated_at, note=NOISE_NOTE
        )
        missing_fields = [key for key in FIELD_KEYS if values[key]["value"] is None]
        cells.append(
            {
                "cell_id": cell.cell_id,
                "row": cell.row,
                "col": cell.col,
                "bbox": [round(v, 7) for v in cell.bbox],
                "center": [round(v, 7) for v in cell.center],
                "inside_district": cell.inside_district,
                "values": values,
                "missing_fields": missing_fields,
            }
        )
        cell_values[cell.cell_id] = values

    coords_by_id = collect_route_coords(routes_geojson_payload)
    catalog_routes = catalog_payload.get("routes")
    if not isinstance(catalog_routes, list):
        msg = "route catalog payload has no routes array"
        raise TypeError(msg)
    routes: list[dict[str, Any]] = []
    for entry in catalog_routes:
        if not isinstance(entry, dict):
            continue
        route_id = str(entry.get("route_id"))
        coords = coords_by_id.get(route_id)
        if coords is None:
            msg = f"route {route_id} exists in the catalog but not in the routes GeoJSON"
            raise ValueError(msg)
        routes.append(
            build_route_exposure(
                route_id=route_id,
                mode=str(entry.get("mode", "")),
                coords=coords,
                grid=grid,
                cell_values=cell_values,
                data_generated_at=data_generated_at,
            )
        )

    provenance_notes = [
        "OSM data: sources/osm_xuhui_highways.json, sources/osm_xuhui_pois.json, sources/xuhui_boundary.geojson; (c) OpenStreetMap contributors, ODbL 1.0.",
        "Weather/AQI: Open-Meteo forecast and air-quality APIs, licence CC BY 4.0 (Open-Meteo), fetched keyless from 4 sample points (centroid plus northwest/east/south spread).",
        "Cell weather assignment uses the nearest sample point (not inverse-distance weighting); the hour nearest to generated_at in Asia/Shanghai local time is used.",
        "Polygon areas use the shoelace formula on a local equirectangular projection (111320 m/deg lon scaled by cos(lat0), 110540 m/deg lat); cell area uses the same projection.",
        "Road lengths are attributed to the cell containing each segment midpoint; ways are bucketed by bbox before testing.",
        "Polygon area is distributed over cells by the fraction of ring vertices plus edge midpoints falling in each cell; the share outside the grid is dropped.",
        f"Point-node POIs carry no area and are excluded from green/water ratios (green nodes ignored: {osm_counts['green_nodes_ignored']}, water nodes ignored: {osm_counts['water_nodes_ignored']}).",
        "traffic_exposure_0_1 = min(1, major_road_density_km_per_km2 / 20); deterministic proxy, status derived.",
        "noise_proxy_db = clip(38 + 12*log10(1+major_density) + 4*log10(1+road_density), 35, 85); deterministic proxy, NOT a measured sound level.",
        "Fields that came back all-null from Open-Meteo are listed in excluded_fields and never backfilled with invented numbers.",
        "Route exposure resamples each LineString to ~50 m steps and takes a length-weighted mean per field with worst-case status among contributing cells.",
    ]

    return {
        "version": 1,
        "generated_at": generated_at,
        "data_generated_at": data_generated_at,
        "run_id": RUN_ID,
        "crs": CANONICAL_CRS,
        "district": {
            "name_zh": "徐汇区",
            "name_en": "Xuhui District",
            "osm_relation_id": 1278188,
            "admin_level": "6",
            "bbox": list(district_bbox),
            "source": "OpenStreetMap contributors",
            "licence": "ODbL 1.0",
        },
        "grid": {
            "rows": GRID_ROWS,
            "cols": GRID_COLS,
            "cell_count": GRID_CELL_COUNT,
            "cell_size_deg": [grid.dlon, grid.dlat],
            "projection": "local_equirectangular_metres",
        },
        "field_specs": FIELD_SPECS,
        "risk_thresholds": RISK_THRESHOLDS,
        "cells": cells,
        "routes": routes,
        "missing_rate": _missing_rate(cells),
        "provenance_notes": provenance_notes,
        "excluded_fields": excluded_fields,
    }


def build_dashboard(
    route_catalog_path: Path = DEFAULT_ROUTE_CATALOG_PATH,
    routes_geojson_path: Path = DEFAULT_ROUTES_GEOJSON_PATH,
    highways_path: Path = DEFAULT_HIGHWAYS_PATH,
    boundary_path: Path = DEFAULT_BOUNDARY_PATH,
    weather_path: Path | None = FORECAST_ARTIFACT,
    air_quality_path: Path | None = AIR_QUALITY_ARTIFACT,
    generated_at: str = "",
    pois_path: Path | None = None,
) -> dict[str, Any]:
    """Load artifacts from disk and build the dashboard payload."""
    if not route_catalog_path.exists():
        msg = (
            f"route catalog not found at {route_catalog_path}; the route builder "
            "background job must produce data/web/route_catalog.json first "
            "(or run python -m environment --fixture for an in-memory smoke test)"
        )
        raise RouteCatalogMissingError(msg)
    if not routes_geojson_path.exists():
        msg = f"routes GeoJSON not found at {routes_geojson_path}"
        raise RouteCatalogMissingError(msg)
    if not generated_at:
        msg = "generated_at must be passed in; only __main__ may read the clock"
        raise ValueError(msg)
    catalog_payload = _load_json(route_catalog_path)
    routes_geojson_payload = _load_json(routes_geojson_path)
    return build_dashboard_from_objects(
        catalog_payload=catalog_payload,
        routes_geojson_payload=routes_geojson_payload,
        highways_path=highways_path,
        boundary_path=boundary_path,
        weather_path=weather_path,
        air_quality_path=air_quality_path,
        generated_at=generated_at,
        pois_path=pois_path,
    )


def write_dashboard(payload: dict[str, Any], path: Path = DEFAULT_DASHBOARD_PATH) -> Path:
    """Save the dashboard as UTF-8 JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "AIR_QUALITY_ARTIFACT",
    "DEFAULT_BOUNDARY_PATH",
    "DEFAULT_DASHBOARD_PATH",
    "DEFAULT_HIGHWAYS_PATH",
    "DEFAULT_POIS_PATH",
    "DEFAULT_ROUTES_GEOJSON_PATH",
    "DEFAULT_ROUTE_CATALOG_PATH",
    "FORECAST_ARTIFACT",
    "RUN_ID",
    "RouteCatalogMissingError",
    "build_dashboard",
    "build_dashboard_from_objects",
    "write_dashboard",
]
