from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .geo import gcj02_to_wgs84, wgs84_to_gcj02
from .models import CandidateRoute

CLOSED_MARKERS = ("暂停", "关闭", "歇业", "停业", "closed", "suspended")
PREFERENCE_BY_TYPE = {
    "coffee": "coffee",
    "toilet": "toilet",
    "convenience": "store",
    "park_gate": "park",
}


def merge_verified_service_pois(
    routes: Iterable[CandidateRoute], documents: Iterable[dict[str, Any]]
) -> tuple[list[CandidateRoute], dict[str, Any], dict[str, Any]]:
    route_list = list(routes)
    accepted_ids = {
        route.route_id for route in route_list if route.validation_status == "accepted"
    }
    associations: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    pois: dict[str, dict[str, Any]] = {}
    counts = {
        "input": 0,
        "unverified": 0,
        "closed": 0,
        "unpublished_route": 0,
        "invalid": 0,
    }

    for document in documents:
        for record in document.get("records", []):
            counts["input"] += 1
            if record.get("verification_status") != "verified":
                counts["unverified"] += 1
                continue
            if _is_closed(record):
                counts["closed"] += 1
                continue
            route_id = str(record.get("route_id") or "")
            if route_id not in accepted_ids:
                counts["unpublished_route"] += 1
                continue
            normalized = _normalize_record(record)
            if normalized is None:
                counts["invalid"] += 1
                continue
            poi_id = normalized["poi_id"]
            association = {
                "poi_id": poi_id,
                "poi_type": normalized["poi_type"],
                "poi_name": normalized["poi_name"],
                "distance_m": normalized["distance_to_route_m"],
            }
            current = associations[route_id].get(poi_id)
            if current is None or association["distance_m"] < current["distance_m"]:
                associations[route_id][poi_id] = association
            if poi_id not in pois:
                pois[poi_id] = {**normalized, "route_ids": {route_id}}
            else:
                pois[poi_id]["route_ids"].add(route_id)
                pois[poi_id]["distance_to_route_m"] = min(
                    pois[poi_id]["distance_to_route_m"],
                    normalized["distance_to_route_m"],
                )

    updated_routes: list[CandidateRoute] = []
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
        updated_routes.append(
            route.model_copy(
                update={
                    "nearby_pois": nearby,
                    "amenity_ids": [item["poi_id"] for item in nearby],
                    "preference_hits": preference_hits,
                }
            )
        )

    features = []
    for poi_id in sorted(pois):
        poi = pois[poi_id]
        properties = {
            key: value
            for key, value in poi.items()
            if key not in {"lng_gcj02", "lat_gcj02", "lng_wgs84", "lat_wgs84"}
        }
        properties["route_ids"] = sorted(properties["route_ids"])
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
            len(items) for items in associations.values()
        ),
        "published_unique_poi_count": len(features),
        "routes_with_verified_pois": sorted(
            route_id for route_id, items in associations.items() if items
        ),
        "excluded": {
            key: counts[key]
            for key in ("unverified", "closed", "unpublished_route", "invalid")
        },
    }
    return updated_routes, {"type": "FeatureCollection", "features": features}, report


def _is_closed(record: dict[str, Any]) -> bool:
    status = f"{record.get('open_status', '')} {record.get('poi_name', '')}".lower()
    return any(marker in status for marker in CLOSED_MARKERS)


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
