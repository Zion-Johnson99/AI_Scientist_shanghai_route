from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .models import AccessCase, CandidateRoute, EntryPoint, PoiPoint


def build_feature_collection(items: Iterable[EntryPoint]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": item.model_dump(),
                "geometry": {
                    "type": "Point",
                    "coordinates": [item.lng_gcj02, item.lat_gcj02],
                },
            }
            for item in items
        ],
    }


def build_route_feature_collection(routes: Iterable[CandidateRoute]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": route.model_dump(mode="json", exclude={"polyline_gcj02"}),
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        point.gcj02_list() for point in route.polyline_gcj02
                    ],
                },
            }
            for route in routes
            if route.is_publishable()
        ],
    }


def build_candidate_route_feature_collection(
    routes: Iterable[CandidateRoute],
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    **route.model_dump(mode="json", exclude={"polyline_gcj02"}),
                    "display_status": _display_status(route),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        point.gcj02_list() for point in route.polyline_gcj02
                    ],
                },
            }
            for route in routes
            if _is_candidate_displayable(route)
        ],
    }


def build_route_catalog(routes: Iterable[CandidateRoute]) -> list[dict[str, Any]]:
    catalog = []
    for route in routes:
        if not route.is_publishable():
            continue
        catalog.append(
            {
                "route_id": route.route_id,
                "route_name": route.route_name,
                "route_mode": route.route_mode,
                "route_shape": route.route_shape,
                "distance_level": _distance_level(route.target_distance_m),
                "target_distance_m": route.target_distance_m,
                "distance_m": route.actual_distance_m,
                "duration_min": round(route.duration_s / 60, 1),
                "start_entry_id": route.start_entry_id,
                "start_location": {
                    "name": route.start_location.name,
                    "location_type": route.start_location.location_type,
                    "lng_gcj02": route.start_location.lng_gcj02,
                    "lat_gcj02": route.start_location.lat_gcj02,
                    "source_url": route.start_location.source_url,
                },
                "end_entry_id": route.end_entry_id,
                "end_location": {
                    "name": route.end_location.name,
                    "location_type": route.end_location.location_type,
                    "lng_gcj02": route.end_location.lng_gcj02,
                    "lat_gcj02": route.end_location.lat_gcj02,
                    "source_url": route.end_location.source_url,
                },
                "region_zone": route.region_zone,
                "tags": route.tags,
                "future_score": route.future_score,
                "score_note": route.score_note,
                "source_name": route.source_name,
                "source_url": route.source_url,
                "source_accessed_at": route.source_accessed_at.isoformat()
                if route.source_accessed_at
                else None,
                "confidence": route.confidence,
                "distance_error_m": route.distance_error_m,
                "loop_flag": route.loop_flag,
                "feature_tags": route.feature_tags,
                "candidate_rank": route.candidate_rank,
                "geometry_source": route.geometry_source,
                "geometry_status": route.geometry_status,
                "validation_status": route.validation_status,
                "snap_ratio": route.snap_ratio,
                "network_source": route.network_source,
                "verified_at": route.verified_at.isoformat()
                if route.verified_at
                else None,
                "review_note": route.review_note,
                "raw_response_paths": route.raw_response_paths,
                "source_level": route.source_level,
                "waypoint_names": route.waypoint_names,
                "ordered_nodes": [_export_node(node) for node in route.ordered_nodes],
                "amenity_ids": route.amenity_ids,
                "nearby_pois": route.nearby_pois,
                "popular_area_ids": route.popular_area_ids,
                "preference_search_status": route.preference_search_status,
                "preference_hits": route.preference_hits,
            }
        )
    return catalog


def build_candidate_route_catalog(
    routes: Iterable[CandidateRoute],
) -> list[dict[str, Any]]:
    return [
        _catalog_item(route) for route in routes if _is_candidate_displayable(route)
    ]


def _catalog_item(route: CandidateRoute) -> dict[str, Any]:
    return {
        "route_id": route.route_id,
        "route_name": route.route_name,
        "route_mode": route.route_mode,
        "route_shape": route.route_shape,
        "distance_level": _distance_level(route.target_distance_m),
        "target_distance_m": route.target_distance_m,
        "distance_m": route.actual_distance_m,
        "duration_min": round(route.duration_s / 60, 1),
        "start_entry_id": route.start_entry_id,
        "start_location": {
            "name": route.start_location.name,
            "location_type": route.start_location.location_type,
            "lng_gcj02": route.start_location.lng_gcj02,
            "lat_gcj02": route.start_location.lat_gcj02,
            "source_url": route.start_location.source_url,
        },
        "end_entry_id": route.end_entry_id,
        "end_location": {
            "name": route.end_location.name,
            "location_type": route.end_location.location_type,
            "lng_gcj02": route.end_location.lng_gcj02,
            "lat_gcj02": route.end_location.lat_gcj02,
            "source_url": route.end_location.source_url,
        },
        "region_zone": route.region_zone,
        "tags": route.tags,
        "future_score": route.future_score,
        "score_note": route.score_note,
        "source_name": route.source_name,
        "source_url": route.source_url,
        "source_accessed_at": route.source_accessed_at.isoformat()
        if route.source_accessed_at
        else None,
        "confidence": route.confidence,
        "distance_error_m": route.distance_error_m,
        "loop_flag": route.loop_flag,
        "feature_tags": route.feature_tags,
        "candidate_rank": route.candidate_rank,
        "geometry_source": route.geometry_source,
        "geometry_status": route.geometry_status,
        "validation_status": route.validation_status,
        "display_status": _display_status(route),
        "snap_ratio": route.snap_ratio,
        "route_inside_ratio": route.route_inside_ratio,
        "network_source": route.network_source,
        "verified_at": route.verified_at.isoformat() if route.verified_at else None,
        "review_note": route.review_note,
        "raw_response_paths": route.raw_response_paths,
        "source_level": route.source_level,
        "waypoint_names": route.waypoint_names,
        "ordered_nodes": [_export_node(node) for node in route.ordered_nodes],
        "amenity_ids": route.amenity_ids,
        "nearby_pois": route.nearby_pois,
        "popular_area_ids": route.popular_area_ids,
        "preference_search_status": route.preference_search_status,
        "preference_hits": route.preference_hits,
    }


def _export_node(node) -> dict[str, Any]:
    return {
        "name": node.node_name,
        "node_type": node.node_type,
        "lng_gcj02": node.lng_gcj02,
        "lat_gcj02": node.lat_gcj02,
        "source_url": node.source_url,
        "poi_id": node.poi_id,
    }


def _is_candidate_displayable(route: CandidateRoute) -> bool:
    return (
        route.validation_status in {"accepted", "needs_review"}
        and route.geometry_source in {"amap_direction", "audited_import"}
        and route.geometry_status == "complete"
        and len({(point.lng_gcj02, point.lat_gcj02) for point in route.polyline_gcj02})
        >= 2
        and bool(route.waypoint_names and route.waypoint_names[0].strip())
        and bool(route.raw_response_paths)
    )


def _display_status(route: CandidateRoute) -> str:
    return "严格验收" if route.validation_status == "accepted" else "待考证"


def build_poi_feature_collection(items: Iterable[PoiPoint]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": item.model_dump(),
                "geometry": {
                    "type": "Point",
                    "coordinates": [item.lng_gcj02, item.lat_gcj02],
                },
            }
            for item in items
        ],
    }


def build_access_catalog(cases: Iterable[AccessCase]) -> list[dict[str, Any]]:
    return [case.model_dump() for case in cases]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_entries_csv(path: Path, entries: Iterable[EntryPoint]) -> None:
    rows = [entry.model_dump() for entry in entries]
    _write_csv(path, rows)


def write_access_cases_csv(path: Path, cases: Iterable[AccessCase]) -> None:
    rows = [case.model_dump() for case in cases]
    _write_csv(path, rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _distance_level(distance_m: int) -> str:
    km = distance_m / 1000
    return f"{km:g}km"
