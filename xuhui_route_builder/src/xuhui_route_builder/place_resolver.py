from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .geo import gcj02_to_wgs84, wgs84_to_gcj02
from .models import RouteNode


@dataclass(frozen=True)
class PlaceCandidate:
    name: str
    source_id: str | None
    lng_gcj02: float
    lat_gcj02: float
    lng_wgs84: float
    lat_wgs84: float
    source_path: str
    address: str = ""

    def to_route_node(self, expected_name: str) -> RouteNode:
        return RouteNode(
            node_name=expected_name,
            poi_id=self.source_id,
            lng_gcj02=self.lng_gcj02,
            lat_gcj02=self.lat_gcj02,
            lng_wgs84=self.lng_wgs84,
            lat_wgs84=self.lat_wgs84,
        )


class HybridPlaceResolver:
    def __init__(
        self,
        baidu_client: Any,
        *,
        local_seed_path: Path,
        osm_index_path: Path,
        boundary_path: Path,
        max_online_calls: int = 50,
    ) -> None:
        if max_online_calls < 0:
            raise ValueError("max_online_calls must be non-negative")
        self.baidu_client = baidu_client
        self.max_online_calls = max_online_calls
        self.online_calls = 0
        self.local_candidates = _load_local_candidates(local_seed_path)
        self.osm_candidates = _load_osm_candidates(osm_index_path)
        self.boundary_rings = _load_boundary_rings(boundary_path)

    def resolve(
        self,
        expected_name: str,
        query: str,
        expected_poi_id: str | None,
        seed_id: str,
        node_index: int,
    ) -> tuple[RouteNode, str]:
        context = f"seed_id={seed_id} node_index={node_index} node_name={expected_name} query={query}"
        local = _select_candidate(
            self.local_candidates, expected_name, query, expected_poi_id
        )
        if local is not None:
            return local.to_route_node(expected_name), local.source_path
        osm = _select_candidate(self.osm_candidates, expected_name, query, None)
        if osm is not None:
            return osm.to_route_node(expected_name), osm.source_path
        try:
            record = self.baidu_client.place_region(
                query,
                region="上海市徐汇区",
                allow_network=self.online_calls < self.max_online_calls,
            )
            self.online_calls += int(not record.cache_hit)
            candidate = _select_candidate(
                _baidu_place_candidates(record), expected_name, query, None
            )
            if candidate is not None:
                return candidate.to_route_node(expected_name), candidate.source_path

            geocode = self.baidu_client.geocode(
                f"上海市徐汇区{query}",
                city="上海市",
                allow_network=self.online_calls < self.max_online_calls,
            )
            self.online_calls += int(not geocode.cache_hit)
            candidate = _baidu_geocode_candidate(geocode, self.boundary_rings)
            if candidate is not None:
                return candidate.to_route_node(expected_name), candidate.source_path
        except Exception as exc:
            raise ValueError(f"Place resolution failed: {context}: {exc}") from exc
        raise ValueError(f"Place resolution failed: {context}: no unique Xuhui result")


def _load_local_candidates(path: Path) -> list[PlaceCandidate]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates: list[PlaceCandidate] = []
    for seed in payload:
        for node in seed.get("ordered_nodes") or []:
            if node.get("lng_gcj02") is None or node.get("lat_gcj02") is None:
                continue
            gcj_lng, gcj_lat = float(node["lng_gcj02"]), float(node["lat_gcj02"])
            wgs_lng = node.get("lng_wgs84")
            wgs_lat = node.get("lat_wgs84")
            if wgs_lng is None or wgs_lat is None:
                wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
            candidates.append(
                PlaceCandidate(
                    name=str(node.get("node_name") or ""),
                    source_id=str(node.get("poi_id")) if node.get("poi_id") else None,
                    lng_gcj02=gcj_lng,
                    lat_gcj02=gcj_lat,
                    lng_wgs84=float(wgs_lng),
                    lat_wgs84=float(wgs_lat),
                    source_path=path.as_posix(),
                )
            )
    return _deduplicate(candidates)


def _load_osm_candidates(path: Path) -> list[PlaceCandidate]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("pois") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise TypeError(f"OSM POI index invalid: path={path}")
    candidates: list[PlaceCandidate] = []
    for row in rows:
        try:
            wgs_lng, wgs_lat = float(row["lng_wgs84"]), float(row["lat_wgs84"])
            gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
            candidates.append(
                PlaceCandidate(
                    name=str(row["name"]),
                    source_id=f"osm:{row['osm_type']}/{row['osm_id']}",
                    lng_gcj02=gcj_lng,
                    lat_gcj02=gcj_lat,
                    lng_wgs84=wgs_lng,
                    lat_wgs84=wgs_lat,
                    source_path=path.as_posix(),
                    address=str(row.get("address") or ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"OSM POI index row invalid: path={path}") from exc
    return _deduplicate(candidates)


def _baidu_place_candidates(record: Any) -> list[PlaceCandidate]:
    if record.status != 0:
        raise ValueError(
            f"Baidu place search failed: status={record.status}, message={record.message}"
        )
    candidates: list[PlaceCandidate] = []
    for result in record.payload.get("results") or []:
        location = result.get("location") or {}
        if (
            str(result.get("adcode", "")) != "310104"
            or location.get("lng") is None
            or location.get("lat") is None
        ):
            continue
        gcj_lng, gcj_lat = float(location["lng"]), float(location["lat"])
        wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
        candidates.append(
            PlaceCandidate(
                name=str(result.get("name") or ""),
                source_id=f"baidu:{result['uid']}" if result.get("uid") else None,
                lng_gcj02=gcj_lng,
                lat_gcj02=gcj_lat,
                lng_wgs84=wgs_lng,
                lat_wgs84=wgs_lat,
                source_path=str(record.raw_path),
                address=str(result.get("address") or ""),
            )
        )
    return _deduplicate(candidates)


def _baidu_geocode_candidate(
    record: Any, boundary_rings: list[list[list[float]]]
) -> PlaceCandidate | None:
    if record.status != 0:
        raise ValueError(
            f"Baidu geocode failed: status={record.status}, message={record.message}"
        )
    result = record.payload.get("result") or {}
    location = result.get("location") or {}
    if location.get("lng") is None or location.get("lat") is None:
        return None
    gcj_lng, gcj_lat = float(location["lng"]), float(location["lat"])
    if boundary_rings and not any(
        _point_in_ring(gcj_lng, gcj_lat, ring) for ring in boundary_rings
    ):
        return None
    wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
    return PlaceCandidate(
        name="",
        source_id=None,
        lng_gcj02=gcj_lng,
        lat_gcj02=gcj_lat,
        lng_wgs84=wgs_lng,
        lat_wgs84=wgs_lat,
        source_path=str(record.raw_path),
    )


def _select_candidate(
    candidates: list[PlaceCandidate],
    expected_name: str,
    query: str,
    expected_poi_id: str | None,
) -> PlaceCandidate | None:
    if expected_poi_id:
        matches = [
            candidate
            for candidate in candidates
            if candidate.source_id == expected_poi_id
        ]
        return matches[0] if len(matches) == 1 else None
    expected = _normalize(expected_name)
    query_text = _normalize(query)
    exact = [
        candidate
        for candidate in candidates
        if _normalize(candidate.name) in {expected, query_text}
    ]
    if len(exact) == 1:
        return exact[0]
    contained = [
        candidate
        for candidate in candidates
        if expected
        and (
            expected in _normalize(candidate.name)
            or expected in _normalize(candidate.address)
        )
    ]
    if contained:
        shortest = min(len(_normalize(candidate.name)) for candidate in contained)
        shortest_matches = [
            candidate
            for candidate in contained
            if len(_normalize(candidate.name)) == shortest
        ]
        if len(shortest_matches) == 1:
            return shortest_matches[0]
    return None


def _deduplicate(candidates: list[PlaceCandidate]) -> list[PlaceCandidate]:
    unique: dict[tuple[str, str | None, float, float], PlaceCandidate] = {}
    for candidate in candidates:
        key = (
            _normalize(candidate.name),
            candidate.source_id,
            candidate.lng_gcj02,
            candidate.lat_gcj02,
        )
        unique[key] = candidate
    return list(unique.values())


def _load_boundary_rings(path: Path) -> list[list[list[float]]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = (
        payload.get("features")
        if payload.get("type") == "FeatureCollection"
        else [payload]
    )
    rings: list[list[list[float]]] = []
    for feature in features or []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") == "Polygon" and coordinates:
            rings.append(coordinates[0])
        elif geometry.get("type") == "MultiPolygon":
            rings.extend(polygon[0] for polygon in coordinates if polygon)
        else:
            raise ValueError(f"Boundary geometry invalid: path={path}")
    if rings:
        return rings
    raise ValueError(f"Boundary geometry invalid: path={path}")


def _point_in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lng < crossing:
                inside = not inside
        previous = current
    return inside


def _normalize(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(normalized.split()).replace("-", "")
