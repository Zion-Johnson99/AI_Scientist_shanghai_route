"""Fetch public OSM data for Xuhui district (Shanghai) via Overpass API.

Writes raw responses and derived GeoJSON into the run's sources/ directory.
Deterministic, offline-cacheable: skips a download when the cache file exists.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any
from urllib import request

SOURCES = Path(__file__).resolve().parents[1] / "sources"
SOURCES.mkdir(parents=True, exist_ok=True)

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

HIGHWAY_TYPES = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "living_street|pedestrian|footway|path|cycleway|steps|track|bridleway|"
    "road|construction"
)


def post_overpass(query: str, timeout: int = 900) -> dict[str, Any]:
    last_error: Exception | None = None
    for endpoint in ENDPOINTS:
        for attempt in range(2):
            try:
                data = ("data=" + query).encode("utf-8")
                req = request.Request(
                    endpoint,
                    data=data,
                    headers={"User-Agent": "qh-round2-research/1.0", "Accept": "application/json"},
                )
                with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https hosts
                    payload = json.loads(resp.read().decode("utf-8"))
                if isinstance(payload, dict) and "elements" in payload:
                    return payload
                last_error = RuntimeError(f"unexpected payload from {endpoint}")
            except Exception as exc:  # noqa: BLE001 - retry across mirrors
                last_error = exc
                time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"all overpass endpoints failed: {last_error}")


def cached(name: str, query: str) -> dict[str, Any]:
    path = SOURCES / name
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    payload = post_overpass(query)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def ring_length_deg(ring: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(ring) - 1):
        lon0, lat0 = ring[i]
        lon1, lat1 = ring[i + 1]
        mid = math.radians((lat0 + lat1) / 2.0)
        dx = (lon1 - lon0) * math.cos(mid)
        total += math.hypot(dx, lat1 - lat0)
    return total


def main() -> int:
    boundary_query = """
[out:json][timeout:600];
relation["boundary"="administrative"]["name:zh"="徐汇区"];
out geom;
"""
    boundary = cached("osm_xuhui_admin_relation.json", boundary_query)
    relations = [e for e in boundary.get("elements", []) if e.get("type") == "relation"]
    if not relations:
        print("NO_XUHUI_RELATION", file=sys.stderr)
        return 2
    rel = max(relations, key=lambda r: len(r.get("members", [])))
    print(
        "relation_id=%s admin_level=%s members=%d"
        % (rel.get("id"), rel.get("tags", {}).get("admin_level"), len(rel.get("members", [])))
    )

    outer_rings: list[list[list[float]]] = []
    for member in rel.get("members", []):
        if member.get("role") != "outer":
            continue
        geom = member.get("geometry")
        if not geom:
            continue
        outer_rings.append([[float(p["lon"]), float(p["lat"])] for p in geom])

    if not outer_rings:
        print("NO_OUTER_GEOMETRY", file=sys.stderr)
        return 3

    outer_rings.sort(key=ring_length_deg, reverse=True)
    main_ring = outer_rings[0]
    if main_ring[0] != main_ring[-1]:
        main_ring = [*main_ring, main_ring[0]]

    polygon = {
        "type": "FeatureCollection",
        "name": "xuhui_district_boundary",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            {
                "type": "Feature",
                "id": "xuhui-district",
                "properties": {
                    "name_zh": "徐汇区",
                    "admin_level": rel.get("tags", {}).get("admin_level"),
                    "osm_relation_id": rel.get("id"),
                    "osm_rings_total": len(outer_rings),
                    "source": "OpenStreetMap via Overpass API",
                    "licence": "ODbL 1.0",
                },
                "geometry": {"type": "Polygon", "coordinates": [main_ring]},
            }
        ],
    }
    (SOURCES / "xuhui_boundary.geojson").write_text(
        json.dumps(polygon, ensure_ascii=False), encoding="utf-8"
    )
    print("boundary_vertices=%d" % (len(main_ring) - 1))

    roads_query = f"""
[out:json][timeout:900][bbox:];
area["boundary"="administrative"]["name:zh"="徐汇区"]->.a;
way["highway"~"^({HIGHWAY_TYPES})$"](area.a);
out geom tags;
"""
    roads = cached("osm_xuhui_highways.json", roads_query)
    road_ways = [e for e in roads.get("elements", []) if e.get("type") == "way"]
    print("road_ways=%d" % len(road_ways))

    poi_query = """
[out:json][timeout:900][bbox:];
area["boundary"="administrative"]["name:zh"="徐汇区"]->.a;
(
  node["railway"="station"](area.a);
  way["railway"="station"](area.a);
  node["leisure"~"park|garden|playground|sports_centre|stadium"](area.a);
  way["leisure"~"park|garden|playground|sports_centre|stadium"](area.a);
  node["natural"="water"](area.a);
  way["natural"="water"](area.a);
  way["waterway"="river"](area.a);
  node["amenity"~"school|university|college|hospital|clinic"](area.a);
  way["amenity"~"school|university|college|hospital|clinic"](area.a);
);
out center tags;
"""
    pois = cached("osm_xuhui_pois.json", poi_query)
    poi_elements = [e for e in pois.get("elements", []) if e.get("type") in {"node", "way"}]
    print("poi_elements=%d" % len(poi_elements))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
