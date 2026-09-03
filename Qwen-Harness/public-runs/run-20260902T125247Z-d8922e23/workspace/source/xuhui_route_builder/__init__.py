"""Route module root: 90 accepted Xuhui walk / run / bike routes."""

from __future__ import annotations

from pathlib import Path

MODULE_ROOT: Path = Path(__file__).resolve().parent
DATA_WEB: Path = MODULE_ROOT / "data" / "web"
ROUTE_CATALOG_RELATIVE: str = "data/web/route_catalog.json"
ROUTES_GEOJSON_RELATIVE: str = "data/web/xuhui_routes.geojson"
BOUNDARY_GEOJSON_RELATIVE: str = "data/web/xuhui_boundary.geojson"
ENTRIES_GEOJSON_RELATIVE: str = "data/web/xuhui_entries.geojson"
POI_CATALOG_RELATIVE: str = "data/web/poi_catalog.json"
ACCESS_CASES_RELATIVE: str = "data/web/access_cases.json"
ENVIRONMENT_DASHBOARD_RELATIVE: str = "data/web/environment_dashboard.json"

__all__ = [
    "ACCESS_CASES_RELATIVE",
    "BOUNDARY_GEOJSON_RELATIVE",
    "DATA_WEB",
    "ENTRIES_GEOJSON_RELATIVE",
    "ENVIRONMENT_DASHBOARD_RELATIVE",
    "MODULE_ROOT",
    "POI_CATALOG_RELATIVE",
    "ROUTES_GEOJSON_RELATIVE",
    "ROUTE_CATALOG_RELATIVE",
]
