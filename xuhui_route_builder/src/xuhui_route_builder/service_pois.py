from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .geo import gcj02_to_wgs84, wgs84_to_gcj02
from .models import CandidateRoute, PreferenceSearchState, PreferenceType
from .validation import point_to_polyline_distance_m

CLOSED_MARKERS = ("暂停", "关闭", "歇业", "停业", "closed", "suspended")
PREFERENCE_BY_TYPE: dict[str, PreferenceType] = {
    "coffee": "coffee",
    "toilet": "toilet",
    "convenience": "convenience",
    "park_gate": "park_gate",
}


def merge_verified_service_pois(
    routes: Iterable[CandidateRoute], documents: Iterable[dict[str, Any]]
) -> tuple[list[CandidateRoute], dict[str, Any], dict[str, Any]]:
    route_list = list(routes)
    routes_by_id = {route.route_id: route for route in route_list}
    associations: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    pois: dict[str, dict[str, Any]] = {}
    poi_ids_by_location: dict[tuple[str, float, float], str] = {}
    counts = {
        "input": 0,
        "unverified": 0,
        "closed": 0,
        "unpublished_route": 0,
        "invalid": 0,
        "outside_corridor": 0,
        "blocked_access": 0,
    }

    for document in documents:
        document_mode = _document_route_mode(document)
        mode_route_ids = [
            route.route_id for route in route_list if route.route_mode == document_mode
        ]
        for record in document.get("records", []):
            counts["input"] += 1
            if record.get("verification_status") != "verified":
                counts["unverified"] += 1
                continue
            if _is_closed(record):
                counts["closed"] += 1
                continue
            declared_route_ids = [
                str(record.get("route_id") or ""),
                *(str(route_id) for route_id in record.get("related_route_ids", [])),
            ]
            declared_route_ids = list(
                dict.fromkeys(route_id for route_id in declared_route_ids if route_id)
            )
            route_ids = (
                list(routes_by_id)
                if record.get("poi_type") == "park_gate"
                else mode_route_ids or declared_route_ids
            )
            known_record_ids = [
                route_id for route_id in route_ids if route_id in routes_by_id
            ]
            counts["unpublished_route"] += len(declared_route_ids) - sum(
                route_id in routes_by_id for route_id in declared_route_ids
            )
            if not known_record_ids:
                continue
            normalized = _normalize_record(record)
            if normalized is None:
                counts["invalid"] += 1
                continue
            location_key = (
                normalized["poi_type"],
                round(normalized["lng_gcj02"], 6),
                round(normalized["lat_gcj02"], 6),
            )
            canonical_poi_id = poi_ids_by_location.setdefault(
                location_key, normalized["poi_id"]
            )
            normalized = {**normalized, "poi_id": canonical_poi_id}
            if record.get("access_status") == "blocked":
                counts["blocked_access"] += 1
                continue
            for route_id in known_record_ids:
                route = routes_by_id[route_id]
                distance_to_route_m = point_to_polyline_distance_m(
                    (normalized["lng_gcj02"], normalized["lat_gcj02"]),
                    route.polyline_gcj02,
                )
                route_relation = _route_relation(
                    normalized["poi_type"], distance_to_route_m, record
                )
                if route_relation is None:
                    counts["outside_corridor"] += 1
                    continue
                route_poi = {
                    **normalized,
                    "distance_to_route_m": round(distance_to_route_m, 1),
                    "route_relation": route_relation,
                }
                poi_id = route_poi["poi_id"]
                association = {
                    "poi_id": poi_id,
                    "poi_type": route_poi["poi_type"],
                    "poi_name": route_poi["poi_name"],
                    "distance_m": route_poi["distance_to_route_m"],
                    "route_relation": route_relation,
                    "source": route_poi["source"],
                    "source_id": route_poi["source_id"],
                    "source_accessed_at": route_poi["source_accessed_at"],
                    "open_status": route_poi["open_status"],
                    "verification_status": route_poi["verification_status"],
                    "evidence_path": route_poi["evidence_path"],
                }
                current = associations[route_id].get(poi_id)
                if current is None or association["distance_m"] < current["distance_m"]:
                    associations[route_id][poi_id] = association
                if poi_id not in pois:
                    pois[poi_id] = {**route_poi, "route_ids": {route_id}}
                else:
                    pois[poi_id]["route_ids"].add(route_id)
                    if (
                        route_poi["distance_to_route_m"]
                        < pois[poi_id]["distance_to_route_m"]
                    ):
                        pois[poi_id]["distance_to_route_m"] = route_poi[
                            "distance_to_route_m"
                        ]
                        pois[poi_id]["route_relation"] = route_relation

    updated_routes: list[CandidateRoute] = []
    preference_coverage: dict[str, int] = {}
    for route in route_list:
        nearby = sorted(
            associations.get(route.route_id, {}).values(),
            key=lambda item: (item["distance_m"], item["poi_id"]),
        )
        preference_hits = sorted(
            {
                PREFERENCE_BY_TYPE[item["poi_type"]]
                for item in nearby
                if item["poi_type"] in PREFERENCE_BY_TYPE
            }
        )
        search_status: dict[PreferenceType, PreferenceSearchState] = dict(
            route.preference_search_status
        )
        for preference in PREFERENCE_BY_TYPE.values():
            if preference in preference_hits:
                search_status[preference] = "verified"
            elif (
                search_status.get(preference) == "verified"
                or preference not in search_status
            ):
                search_status[preference] = "no_verified_match"
        preference_coverage[route.route_id] = len(preference_hits)
        updated_routes.append(
            route.model_copy(
                update={
                    "nearby_pois": nearby,
                    "amenity_ids": [item["poi_id"] for item in nearby],
                    "preference_hits": preference_hits,
                    "preference_search_status": search_status,
                }
            )
        )

    features = []
    final_route_ids = {route.route_id for route in updated_routes}
    for poi_id in sorted(pois):
        poi = pois[poi_id]
        route_ids = sorted(poi["route_ids"] & final_route_ids)
        if not route_ids:
            continue
        properties = {
            key: value
            for key, value in poi.items()
            if key not in {"lng_gcj02", "lat_gcj02", "lng_wgs84", "lat_wgs84"}
        }
        properties["route_ids"] = route_ids
        properties["distance_to_route_m"] = min(
            associations[route_id][poi_id]["distance_m"]
            for route_id in route_ids
            if poi_id in associations[route_id]
        )
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "Point",
                    "coordinates": [poi["lng_gcj02"], poi["lat_gcj02"]],
                },
            }
        )
    report = {
        "input_record_count": counts["input"],
        "published_association_count": sum(
            len(associations.get(route_id, {})) for route_id in final_route_ids
        ),
        "published_unique_poi_count": len(features),
        "routes_with_verified_pois": sorted(
            route_id for route_id in final_route_ids if associations.get(route_id)
        ),
        "verified_preference_type_count": preference_coverage,
        "excluded": {
            key: counts[key]
            for key in (
                "unverified",
                "closed",
                "unpublished_route",
                "invalid",
                "outside_corridor",
            )
        },
    }
    if counts["blocked_access"]:
        report["excluded"]["blocked_access"] = counts["blocked_access"]
    return updated_routes, {"type": "FeatureCollection", "features": features}, report


def _document_route_mode(document: dict[str, Any]) -> str:
    route_filter = document.get("route_filter") or {}
    metadata = document.get("metadata") or {}
    mode = str(route_filter.get("route_mode") or metadata.get("route_mode") or "")
    return mode if mode in {"walk", "run", "bike"} else ""


def _is_closed(record: dict[str, Any]) -> bool:
    status = f"{record.get('open_status', '')} {record.get('poi_name', '')}".lower()
    return any(marker in status for marker in CLOSED_MARKERS)


def _route_relation(
    poi_type: str, distance_to_route_m: float, record: dict[str, Any]
) -> str | None:
    if distance_to_route_m <= 100:
        return "along_route"
    if (
        poi_type == "park_gate"
        and distance_to_route_m <= 200
        and record.get("access_status") == "verified_walkable"
    ):
        return "nearby"
    return None


def _normalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    poi_id = _stable_poi_id(record)
    poi_name = str(record.get("poi_name") or "").strip()
    poi_type = str(record.get("poi_type") or "").strip()
    coordinates = record.get("coordinates") or {}
    lng = coordinates.get("lng", record.get("lng"))
    lat = coordinates.get("lat", record.get("lat"))
    coordinate_system = (
        str(record.get("coordinate_system") or "").upper().replace("-", "")
    )
    if (
        not poi_id
        or not poi_name
        or not poi_type
        or not isinstance(lng, (int, float))
        or not isinstance(lat, (int, float))
    ):
        return None
    if coordinate_system == "GCJ02":
        lng_gcj02, lat_gcj02 = float(lng), float(lat)
        lng_wgs84, lat_wgs84 = gcj02_to_wgs84(lng_gcj02, lat_gcj02)
    elif coordinate_system == "WGS84":
        lng_wgs84, lat_wgs84 = float(lng), float(lat)
        lng_gcj02, lat_gcj02 = wgs84_to_gcj02(lng_wgs84, lat_wgs84)
    else:
        return None
    return {
        "poi_id": poi_id,
        "poi_name": poi_name,
        "poi_type": poi_type,
        "source": record.get("source"),
        "source_id": record.get("source_id"),
        "source_accessed_at": record.get("source_accessed_at")
        or record.get("query_time"),
        "open_status": record.get("open_status"),
        "verification_status": "verified",
        "evidence_path": record.get("evidence_path"),
        "distance_to_route_m": round(float(record.get("distance_to_route_m", 0)), 1),
        "lng_gcj02": lng_gcj02,
        "lat_gcj02": lat_gcj02,
        "lng_wgs84": lng_wgs84,
        "lat_wgs84": lat_wgs84,
    }


def _stable_poi_id(record: dict[str, Any]) -> str:
    for key in ("poi_id", "source_id"):
        value = str(record.get(key) or "").strip()
        if ":" in value:
            return value.replace("osm:node/", "osm:node:")
    source_id = str(record.get("source_id") or record.get("poi_id") or "").strip()
    source = str(record.get("source") or "source").lower()
    prefix = (
        "amap" if "amap" in source else "osm" if "openstreetmap" in source else "source"
    )
    return f"{prefix}:{source_id}" if source_id else ""
