"""CLI entry: python -m environment [--fixture] [--generated-at ISO]."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import (
    DEFAULT_BOUNDARY_PATH,
    DEFAULT_HIGHWAYS_PATH,
    DEFAULT_ROUTE_CATALOG_PATH,
    DEFAULT_ROUTES_GEOJSON_PATH,
    RouteCatalogMissingError,
    build_dashboard,
    build_dashboard_from_objects,
    write_dashboard,
)
from .contract import GRID_CELL_COUNT, validate_dashboard
from .fetch_public import AIR_QUALITY_ARTIFACT, FORECAST_ARTIFACT

_FIXTURE_ROUTE_DEFS: list[tuple[str, str, list[list[float]]]] = [
    (
        "FIX_WALK_0001",
        "walk",
        [
            [121.4300, 31.1850],
            [121.4360, 31.1850],
            [121.4360, 31.1900],
            [121.4300, 31.1900],
            [121.4300, 31.1850],
        ],
    ),
    (
        "FIX_RUN_0002",
        "run",
        [
            [121.4400, 31.1950],
            [121.4520, 31.1950],
            [121.4520, 31.2050],
            [121.4400, 31.2050],
            [121.4400, 31.1950],
        ],
    ),
    (
        "FIX_RUN_0003",
        "run",
        [
            [121.4100, 31.1500],
            [121.4250, 31.1500],
            [121.4250, 31.1600],
            [121.4100, 31.1600],
            [121.4100, 31.1500],
        ],
    ),
    (
        "FIX_BIKE_0004",
        "bike",
        [
            [121.4200, 31.1700],
            [121.4450, 31.1750],
            [121.4600, 31.1900],
            [121.4450, 31.2000],
            [121.4200, 31.1700],
        ],
    ),
]


def _fixture_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    """Synthesise 4 fake routes in memory; nothing is written to disk."""
    catalog = {
        "routes": [{"route_id": route_id, "mode": mode} for route_id, mode, _ in _FIXTURE_ROUTE_DEFS]
    }
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"route_id": route_id},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
            for route_id, _, coords in _FIXTURE_ROUTE_DEFS
        ],
    }
    return catalog, geojson


def _print_summary(payload: dict[str, Any], report: dict[str, Any], fixture: bool) -> None:
    inside = sum(1 for cell in payload["cells"] if cell["inside_district"])
    risk_counts: dict[str, int] = {}
    for route in payload["routes"]:
        level = str(route["overall_risk"])
        risk_counts[level] = risk_counts.get(level, 0) + 1
    summary = {
        "mode": "fixture" if fixture else "real",
        "cell_count": len(payload["cells"]),
        "cells_inside_district": inside,
        "route_count": len(payload["routes"]),
        "data_generated_at": payload["data_generated_at"],
        "excluded_fields": [entry["key"] for entry in payload["excluded_fields"]],
        "missing_rate": payload["missing_rate"],
        "overall_risk_counts": risk_counts,
        "validation_passed": report["passed"],
        "validation_errors": report["errors"][:20],
        "validation_warnings": report["warnings"][:10],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="environment", description=__doc__)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="run end-to-end on 4 in-memory fake routes without touching deliverables",
    )
    parser.add_argument("--generated-at", default=None, help="ISO-8601 override for the clock")
    args = parser.parse_args(argv)

    generated_at: str = args.generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.fixture:
        catalog, geojson = _fixture_payloads()
        payload = build_dashboard_from_objects(
            catalog_payload=catalog,
            routes_geojson_payload=geojson,
            highways_path=DEFAULT_HIGHWAYS_PATH,
            boundary_path=DEFAULT_BOUNDARY_PATH,
            weather_path=FORECAST_ARTIFACT if FORECAST_ARTIFACT.exists() else None,
            air_quality_path=AIR_QUALITY_ARTIFACT if AIR_QUALITY_ARTIFACT.exists() else None,
            generated_at=generated_at,
        )
        catalog_ids = {route["route_id"] for route in catalog["routes"]}
        report = validate_dashboard(payload, catalog_route_ids=catalog_ids)
        _print_summary(payload, report, fixture=True)
        return 0 if report["passed"] else 1

    try:
        payload = build_dashboard(
            route_catalog_path=Path(DEFAULT_ROUTE_CATALOG_PATH),
            routes_geojson_path=Path(DEFAULT_ROUTES_GEOJSON_PATH),
            highways_path=DEFAULT_HIGHWAYS_PATH,
            boundary_path=DEFAULT_BOUNDARY_PATH,
            weather_path=FORECAST_ARTIFACT,
            air_quality_path=AIR_QUALITY_ARTIFACT,
            generated_at=generated_at,
        )
    except RouteCatalogMissingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    out_path = write_dashboard(payload)
    print(f"dashboard written: {out_path}")
    report = validate_dashboard(payload)
    _print_summary(payload, report, fixture=False)
    if len(payload["cells"]) != GRID_CELL_COUNT:
        print("ERROR: unexpected cell count", file=sys.stderr)
        return 1
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
