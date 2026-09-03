"""Serialise the generated portfolio into the route-adapter artifacts.

The harness route adapter reads ``data/web/route_catalog.json`` and
``data/web/xuhui_routes.geojson`` from the ``xuhui_route_builder`` module root,
and gate G-10 requires the two ``route_id`` sets to be identical. Every field
written here is either measured from OSM geometry by this run, or labelled with
an explicit provenance string saying it is a manual setting or a deterministic
estimate. No value is presented as an online routing-API result, because no
routing API was called.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .areas import ResolvedArea
from .gates import ROUTES_PER_MODE
from .generator import BANDS_KM, MODES, Portfolio
from .geometry import (
    Coord,
    Ring,
    bbox,
    haversine_m,
    point_in_ring,
    polyline_distance_m,
)

CRS_DECLARATION = "CRS84/WGS84 (lon,lat)"

#: Cruising speeds used only to turn a measured distance into a displayed
#: duration. These are planning conventions, not measurements.
SPEED_KMH = {"walk": 4.8, "run": 9.0, "bike": 18.0}
SPEED_PROVENANCE = "manual_setting"

MODE_LABELS = {"walk": "步行", "run": "跑步", "bike": "骑行"}
KIND_LABELS = {"strict_loop": "闭环路线", "one_way": "单程路线"}
BAND_LABELS = {
    "walk": ("轻松短程", "中等距离", "长距健行"),
    "run": ("短程快跑", "中距离跑", "长距离跑"),
    "bike": ("通勤骑行", "中距骑行", "长距骑行"),
}

#: Straight-line to walking-distance factor for access legs, and the walking
#: speed used for them. Both are declared as deterministic estimates.
ACCESS_DETOUR_FACTOR = 1.35
ACCESS_SPEED_KMH = SPEED_KMH["walk"]
ACCESS_PROVENANCE = "deterministic_estimate"

ENTRY_RAILWAY_KINDS = ("station", "subway_entrance", "halt")
ENTRY_LIMIT = 40
ACCESS_CASE_LIMIT = 12

PARK_NEAR_M = 100.0
PARK_RELATED_M = 200.0
SERVICE_NEAR_M = 150.0
SERVICE_KEYS = (
    ("amenity", "drinking_water", "直饮水点"),
    ("amenity", "toilets", "公共卫生间"),
    ("amenity", "cafe", "咖啡补给"),
    ("shop", "convenience", "便利店"),
    ("shop", "supermarket", "超市补给"),
    ("shop", "bicycle", "自行车服务"),
    ("leisure", "sports_centre", "运动场馆"),
)
PARK_KEYS = (("leisure", "park"), ("leisure", "garden"), ("leisure", "nature_reserve"))


def bucket_label(mode: str, band: int) -> str:
    """Band label in the exact form the contract's bucket table uses."""
    low, high = BANDS_KM[mode][band]
    return f"{low:g}\u2013{high:g} km"


def band_from_distance(mode: str, distance_m: float) -> int:
    """Band index for an actual distance; boundaries fall into the next band."""
    for index, (low, high) in enumerate(BANDS_KM[mode]):
        if low * 1000.0 <= distance_m < high * 1000.0:
            return index
    return len(BANDS_KM[mode]) - 1


def duration_min(mode: str, distance_m: float) -> float:
    return round(distance_m / 1000.0 / SPEED_KMH[mode] * 60.0, 1)


def _area_names(areas: Sequence[ResolvedArea]) -> dict[str, dict[str, str]]:
    return {
        area.area_id: {"name_zh": area.name_zh, "name_en": area.name_en}
        for area in areas
    }


def _round_coord(value: float, digits: int = 6) -> float:
    return round(value, digits)


def _geojson_coords(coords: Sequence[Coord]) -> list[list[float]]:
    return [[_round_coord(lon), _round_coord(lat)] for lon, lat in coords]


def route_name(route: Any, names: dict[str, dict[str, str]], position: int) -> str:  # type: ignore[no-untyped-def]
    area = names.get(route.area, {}).get("name_zh", "徐汇")
    band_label = BAND_LABELS[route.mode][route.band]
    kind_label = KIND_LABELS[route.kind]
    return f"{area}·{band_label}{kind_label}{position:02d}"


def _poi_name(tags: dict[str, Any]) -> str:
    for key in ("name:zh", "name", "brand", "operator"):
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _poi_point(element: dict[str, Any]) -> Coord | None:
    lon = element.get("lon")
    lat = element.get("lat")
    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
        return (float(lon), float(lat))
    geometry = element.get("geometry") or []
    if not geometry:
        return None
    lons = [float(point["lon"]) for point in geometry]
    lats = [float(point["lat"]) for point in geometry]
    return (sum(lons) / len(lons), sum(lats) / len(lats))


def _matches(tags: dict[str, Any], keys: Sequence[tuple[str, str]]) -> str | None:
    for key, value in keys:
        if tags.get(key) == value:
            return value
    return None


def _matches_labelled(
    tags: dict[str, Any], keys: Sequence[tuple[str, str, str]]
) -> tuple[str, str] | None:
    for key, value, label in keys:
        if tags.get(key) == value:
            return value, label
    return None


def collect_pois(
    payload: dict[str, Any], boundary: Ring
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the fetched POI payload into entries, parks and service points."""
    entries: list[dict[str, Any]] = []
    parks: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        point = _poi_point(element)
        if point is None or not point_in_ring(point, boundary):
            continue
        poi_id = int(element.get("id", 0))
        record = {
            "poi_id": poi_id,
            "osm_type": element.get("type"),
            "name_zh": _poi_name(tags),
            "coord": [_round_coord(point[0]), _round_coord(point[1])],
            "crs": CRS_DECLARATION,
        }
        railway = tags.get("railway")
        if railway in ENTRY_RAILWAY_KINDS:
            entries.append({**record, "kind": railway, "category": "transit_entry"})
            continue
        if _matches(tags, PARK_KEYS):
            parks.append({**record, "kind": _matches(tags, PARK_KEYS), "category": "park"})
            continue
        service = _matches_labelled(tags, SERVICE_KEYS)
        if service is not None:
            services.append({**record, "kind": service[0], "label": service[1], "category": "service"})
    entries.sort(key=lambda item: (item["kind"] != "station", item["poi_id"]))
    parks.sort(key=lambda item: item["poi_id"])
    services.sort(key=lambda item: item["poi_id"])
    return entries[:ENTRY_LIMIT], parks, services


def _distance_m(a: Coord, b: Coord) -> float:
    return haversine_m(a, b)


def park_relation(route: Any, parks: Sequence[dict[str, Any]]) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    """Nearest park to the route, labelled per gate G-65.

    ``<=100 m`` reads as an on-route park entrance, ``100-200 m`` as a nearby
    park with the distance spelled out, and anything farther is dropped.
    """
    coords = route.coords
    box = bbox(coords)
    best: dict[str, Any] | None = None
    best_distance = float("inf")
    for park in parks:
        lon, lat = park["coord"]
        if not box[0] - 0.003 <= lon <= box[2] + 0.003:
            continue
        if not box[1] - 0.003 <= lat <= box[3] + 0.003:
            continue
        distance = polyline_distance_m((lon, lat), coords)
        if distance < best_distance:
            best_distance = distance
            best = park
    if best is None or best_distance > PARK_RELATED_M:
        return None
    if best_distance <= PARK_NEAR_M:
        label = "公园入口"
    else:
        label = f"邻近公园·约 {int(round(best_distance / 10.0) * 10)} 米"
    return {
        "poi_id": best["poi_id"],
        "name_zh": best["name_zh"],
        "coord": best["coord"],
        "distance_m": round(best_distance, 1),
        "relation": "along_route" if best_distance <= PARK_NEAR_M else "nearby",
        "label": label,
        "provenance": "deterministic_computation",
    }


def nearest_service(
    point: Coord, services: Sequence[dict[str, Any]], radius_m: float = SERVICE_NEAR_M
) -> list[dict[str, Any]]:
    found = [
        {**service, "distance_m": round(_distance_m(point, tuple(service["coord"])), 1)}
        for service in services
        if _distance_m(point, tuple(service["coord"])) <= radius_m
    ]
    found.sort(key=lambda item: (item["distance_m"], item["poi_id"]))
    return found[:4]


def build_catalog_entry(
    route: Any,  # type: ignore[no-untyped-def]
    result: Any,  # type: ignore[no-untyped-def]
    names: dict[str, dict[str, str]],
    position: int,
    parks: Sequence[dict[str, Any]],
    services: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    distance_m = float(route.actual_distance_m)
    band = band_from_distance(route.mode, distance_m)
    metrics = result.metrics
    entry: dict[str, Any] = {
        "route_id": route.route_id,
        "name_zh": route_name(route, names, position),
        "mode": route.mode,
        "mode_label": MODE_LABELS[route.mode],
        "kind": route.kind,
        "kind_label": KIND_LABELS[route.kind],
        "band": band,
        "band_label": bucket_label(route.mode, band),
        "band_label_zh": BAND_LABELS[route.mode][band],
        "actual_distance_m": round(distance_m, 1),
        "distance_m": round(distance_m, 1),
        "target_distance_m": round(float(route.target_m), 1),
        "distance_error": metrics.get("target_error"),
        "duration_min": duration_min(route.mode, distance_m),
        "speed_kmh": SPEED_KMH[route.mode],
        "speed_provenance": SPEED_PROVENANCE,
        "area": route.area,
        "area_name_zh": names.get(route.area, {}).get("name_zh", route.area),
        "area_name_en": names.get(route.area, {}).get("name_en", route.area),
        "popular_area_ids": [route.area],
        "anchor_area_id": route.anchor_area_id,
        "status": result.status,
        "failures": list(result.failures),
        "crs": CRS_DECLARATION,
        "coordinate_count": len(route.coords),
        "start": [_round_coord(route.coords[0][0]), _round_coord(route.coords[0][1])],
        "end": [_round_coord(route.coords[-1][0]), _round_coord(route.coords[-1][1])],
        "start_marker": [_round_coord(route.coords[0][0]), _round_coord(route.coords[0][1])],
        "end_marker": [_round_coord(route.coords[-1][0]), _round_coord(route.coords[-1][1])],
        "navigation_nodes": 2,
        "long_distance": bool(route.mode == "bike" and band == len(BANDS_KM[route.mode]) - 1),
        "bbox": [round(value, 6) for value in bbox(route.coords)],
        "geometry_provenance": "osm_highway_snapped",
        "road_snapping_ratio": metrics.get("road_snapping_ratio"),
        "road_snapping_provenance": metrics.get("road_snapping_provenance"),
        "in_district_ratio": metrics.get("in_district_ratio"),
        "endpoint_offset_m": metrics.get("endpoint_offset_m"),
        "circuity": metrics.get("circuity"),
        "repeated_edge_count": metrics.get("repeated_edge_count"),
        "proper_self_intersection_count": metrics.get("proper_self_intersection_count"),
        "local_uturn_count": metrics.get("local_uturn_count"),
        "local_return_loop_count": metrics.get("local_return_loop_count"),
        "park_relation": park_relation(route, parks),
        "nearby_services": nearest_service(route.coords[0], services),
        "edge_count": len(route.edge_path),
        "anchor_origin": route.anchor_origin,
        "planned_kind": route.plan_kind,
        "api_distance_error": metrics.get("api_distance_error"),
        "api_distance_provenance": metrics.get("api_distance_provenance"),
    }
    return entry


def build_access_cases(
    entries: Sequence[dict[str, Any]], catalog: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Twelve origin-to-route-start access samples, estimated from straight lines."""
    cases: list[dict[str, Any]] = []
    starts = [(item["route_id"], item["name_zh"], tuple(item["start"]), item["mode"]) for item in catalog]
    for index, entry in enumerate(entries[:ACCESS_CASE_LIMIT], start=1):
        origin = tuple(entry["coord"])
        best_id = ""
        best_name = ""
        best_mode = ""
        best_point: Coord = origin
        best_distance = float("inf")
        for route_id, name, start, mode in starts:
            distance = _distance_m(origin, start)
            if distance < best_distance:
                best_distance = distance
                best_id = route_id
                best_name = name
                best_point = start
                best_mode = mode
        estimated_m = best_distance * ACCESS_DETOUR_FACTOR
        cases.append(
            {
                "case_id": f"ACC_{index:03d}",
                "origin": {
                    "poi_id": entry["poi_id"],
                    "name_zh": entry["name_zh"] or f"{entry['kind']} {entry['poi_id']}",
                    "kind": entry["kind"],
                    "coord": entry["coord"],
                },
                "destination": {
                    "route_id": best_id,
                    "route_name": best_name,
                    "mode": best_mode,
                    "coord": [_round_coord(best_point[0]), _round_coord(best_point[1])],
                },
                "straight_line_m": round(best_distance, 1),
                "estimated_access_m": round(estimated_m, 1),
                "estimated_access_min": round(estimated_m / 1000.0 / ACCESS_SPEED_KMH * 60.0, 1),
                "detour_factor": ACCESS_DETOUR_FACTOR,
                "access_speed_kmh": ACCESS_SPEED_KMH,
                "access_mode": "walk",
                "provenance": ACCESS_PROVENANCE,
                "note": "直线距离乘 1.35 绕行系数估算，未调用任何在线路径规划接口",
                "crs": CRS_DECLARATION,
            }
        )
    return cases


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_artifacts(
    portfolio: Portfolio,
    pois_payload: dict[str, Any],
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Return every route-adapter artifact keyed by its file name."""
    names = _area_names(portfolio.areas)
    entries, parks, services = collect_pois(pois_payload, portfolio.boundary)

    catalog: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for route, result in zip(portfolio.routes, portfolio.results, strict=True):
        positions[route.mode] = positions.get(route.mode, 0) + 1
        catalog.append(
            build_catalog_entry(route, result, names, positions[route.mode], parks, services)
        )

    mode_counts = {mode: 0 for mode in MODES}
    kind_counts: dict[str, dict[str, int]] = {mode: {"strict_loop": 0, "one_way": 0} for mode in MODES}
    bucket_counts: dict[str, int] = {}
    area_counts: dict[str, int] = {}
    for item in catalog:
        mode_counts[item["mode"]] += 1
        kind_counts[item["mode"]][item["kind"]] += 1
        key = f"{item['mode']}:{item['band_label']}"
        bucket_counts[key] = bucket_counts.get(key, 0) + 1
        area_counts[item["area"]] = area_counts.get(item["area"], 0) + 1

    features = [
        {
            "type": "Feature",
            "id": item["route_id"],
            "geometry": {"type": "LineString", "coordinates": _geojson_coords(route.coords)},
            "properties": {key: value for key, value in item.items() if key != "nearby_services"},
        }
        for item, route in zip(catalog, portfolio.routes, strict=True)
    ]
    geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "name": "xuhui_routes",
        "generated_at": generated_at,
        "run_id": run_id,
        "coordinate_reference_system": CRS_DECLARATION,
        "feature_count": len(features),
        "features": features,
    }

    boundary_feature = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "name": "xuhui_boundary",
        "coordinate_reference_system": CRS_DECLARATION,
        "features": [
            {
                "type": "Feature",
                "id": "xuhui_district",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_geojson_coords(list(portfolio.boundary))],
                },
                "properties": {
                    "name_zh": "徐汇区",
                    "name_en": "Xuhui District",
                    "osm_relation_id": 1278188,
                    "admin_level": "6",
                    "source": "OpenStreetMap contributors",
                    "licence": "ODbL 1.0",
                    "ring_vertex_count": len(portfolio.boundary),
                },
            }
        ],
    }

    entry_features = [
        {
            "type": "Feature",
            "id": f"entry-{item['poi_id']}",
            "geometry": {"type": "Point", "coordinates": item["coord"]},
            "properties": {
                "poi_id": item["poi_id"],
                "name_zh": item["name_zh"],
                "kind": item["kind"],
                "category": item["category"],
                "crs": CRS_DECLARATION,
            },
        }
        for item in entries
    ]
    entries_geojson = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "name": "xuhui_entries",
        "coordinate_reference_system": CRS_DECLARATION,
        "feature_count": len(entry_features),
        "features": entry_features,
    }

    access_cases = build_access_cases(entries, catalog)

    used_park_ids = {
        item["park_relation"]["poi_id"] for item in catalog if item.get("park_relation")
    }
    used_service_ids = {
        service["poi_id"] for item in catalog for service in item.get("nearby_services", [])
    }
    poi_catalog = {
        "version": 1,
        "generated_at": generated_at,
        "run_id": run_id,
        "crs": CRS_DECLARATION,
        "source": "OpenStreetMap contributors",
        "licence": "ODbL 1.0",
        "provenance": "public_osm_data_fetched_in_this_run",
        "entries": entries,
        "parks": [park for park in parks if park["poi_id"] in used_park_ids],
        "services": [service for service in services if service["poi_id"] in used_service_ids],
    }
    poi_catalog["count"] = (
        len(poi_catalog["entries"]) + len(poi_catalog["parks"]) + len(poi_catalog["services"])
    )

    catalog_payload = {
        "version": 2,
        "generated_at": generated_at,
        "run_id": run_id,
        "crs": CRS_DECLARATION,
        "coordinate_reference_system": CRS_DECLARATION,
        "district": {
            "name_zh": "徐汇区",
            "name_en": "Xuhui District",
            "osm_relation_id": 1278188,
            "admin_level": "6",
            "source": "OpenStreetMap contributors",
            "licence": "ODbL 1.0",
        },
        "route_count": len(catalog),
        "routes_per_mode_target": ROUTES_PER_MODE,
        "mode_counts": mode_counts,
        "kind_counts": kind_counts,
        "bucket_counts": bucket_counts,
        "band_counts": {mode: {str(k): v for k, v in portfolio.band_counts[mode].items()} for mode in MODES},
        "area_counts": area_counts,
        "status_counts": {
            "accepted": sum(1 for item in catalog if item["status"] == "accepted"),
            "needs_review": sum(1 for item in catalog if item["status"] == "needs_review"),
            "rejected": sum(1 for item in catalog if item["status"] == "rejected"),
        },
        "distance_bands_km": {mode: [list(band) for band in BANDS_KM[mode]] for mode in MODES},
        "speed_kmh": SPEED_KMH,
        "speed_provenance": SPEED_PROVENANCE,
        "portfolio_gate": portfolio.portfolio,
        "generation_diagnostics": {
            "attempts": portfolio.attempts,
            "kind_swaps": portfolio.kind_swaps,
            "unfilled_slots": portfolio.unfilled_slots,
            "graph_stats": portfolio.graph_stats,
            "log": portfolio.log,
        },
        "routes": catalog,
    }

    return {
        "route_catalog.json": catalog_payload,
        "xuhui_routes.geojson": geojson,
        "xuhui_boundary.geojson": boundary_feature,
        "xuhui_entries.geojson": entries_geojson,
        "access_cases.json": {
            "version": 1,
            "generated_at": generated_at,
            "run_id": run_id,
            "crs": CRS_DECLARATION,
            "provenance": ACCESS_PROVENANCE,
            "detour_factor": ACCESS_DETOUR_FACTOR,
            "access_speed_kmh": ACCESS_SPEED_KMH,
            "case_count": len(access_cases),
            "cases": access_cases,
        },
        "poi_catalog.json": poi_catalog,
    }


def write_artifacts(
    portfolio: Portfolio,
    pois_payload: dict[str, Any],
    out_dir: Path,
    run_id: str,
    generated_at: str,
) -> dict[str, Path]:
    artifacts = build_artifacts(portfolio, pois_payload, run_id, generated_at)
    written: dict[str, Path] = {}
    for name, payload in artifacts.items():
        path = out_dir / name
        write_json(path, payload)
        written[name] = path
    return written


def artifact_route_id_sets(out_dir: Path) -> dict[str, Any]:
    """Gate G-10 evidence: the catalog and GeoJSON id sets must be equal."""
    catalog = json.loads((out_dir / "route_catalog.json").read_text(encoding="utf-8"))
    geojson = json.loads((out_dir / "xuhui_routes.geojson").read_text(encoding="utf-8"))
    catalog_ids = {item["route_id"] for item in catalog["routes"]}
    geojson_ids = {feature["properties"]["route_id"] for feature in geojson["features"]}
    return {
        "catalog_route_count": len(catalog_ids),
        "geojson_route_count": len(geojson_ids),
        "sets_equal": catalog_ids == geojson_ids,
        "only_in_catalog": sorted(catalog_ids - geojson_ids),
        "only_in_geojson": sorted(geojson_ids - catalog_ids),
        "unique_ids": len(catalog_ids) == len(catalog["routes"]),
    }


__all__ = [
    "ACCESS_CASE_LIMIT",
    "ACCESS_DETOUR_FACTOR",
    "ACCESS_PROVENANCE",
    "ACCESS_SPEED_KMH",
    "BAND_LABELS",
    "CRS_DECLARATION",
    "ENTRY_LIMIT",
    "KIND_LABELS",
    "MODE_LABELS",
    "PARK_NEAR_M",
    "PARK_RELATED_M",
    "SPEED_KMH",
    "SPEED_PROVENANCE",
    "artifact_route_id_sets",
    "band_from_distance",
    "bucket_label",
    "build_access_cases",
    "build_artifacts",
    "build_catalog_entry",
    "collect_pois",
    "duration_min",
    "park_relation",
    "route_name",
    "write_artifacts",
    "write_json",
]
