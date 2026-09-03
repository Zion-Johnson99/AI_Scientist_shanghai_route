"""Chunked public OSM acquisition for Xuhui district.

Strategy
--------
The single district-wide ``way["highway"...](area.a)`` query repeatedly returned
HTTP 502 from every public Overpass mirror (area lookups are expensive for the
server). This script therefore:

1. rebuilds the administrative boundary by chaining *all* outer member ways of
   OSM relation 1278188 instead of keeping only the longest single way;
2. fetches the passable road network cell by cell over a bbox grid, which keeps
   every individual request small;
3. fetches POIs the same way.

All data is OSM (ODbL 1.0) and every artifact declares CRS84 / WGS84.
Nothing here reads any repository business module.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parents[1]
SOURCES = RUN_DIR / "sources"
SOURCES.mkdir(parents=True, exist_ok=True)

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

RELATION_ID = 1278188  # OSM relation for 徐汇区 (Xuhui), Shanghai
GRID = 3  # GRID x GRID bbox cells
HIGHWAY_TYPES = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "living_street|pedestrian|footway|path|cycleway|steps|track|bridleway|road"
)
SNAP_TOL_DEG = 1e-6


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post_overpass(query: str, timeout: int = 240) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(5):
        mirror = MIRRORS[attempt % len(MIRRORS)]
        try:
            data = urllib.parse.urlencode({"data": query}).encode("utf-8")
            request = urllib.request.Request(
                mirror,
                data=data,
                headers={"User-Agent": "ai-scientist-round2-research/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            print(f"  attempt {attempt + 1} via {mirror} failed: {exc}", flush=True)
            time.sleep(6 * (attempt + 1))
    raise RuntimeError(f"all overpass endpoints failed: {last_error}")


def cached(name: str, query: str, timeout: int = 240) -> dict[str, Any]:
    path = SOURCES / name
    if path.exists() and path.stat().st_size > 200:
        print(f"[cache] {name}", flush=True)
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"[fetch] {name}", flush=True)
    payload = post_overpass(query, timeout=timeout)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def ring_from_points(points: list[tuple[float, float]]) -> list[list[float]]:
    return [[lon, lat] for lat, lon in points]


def signed_area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def key(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] / SNAP_TOL_DEG), round(point[1] / SNAP_TOL_DEG))


def chain_outer_rings(ways: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Join admin outer ways into closed rings by snapped endpoint matching."""
    segments = [list(w) for w in ways if len(w) >= 2]
    used = [False] * len(segments)
    rings: list[list[tuple[float, float]]] = []

    for start_index in range(len(segments)):
        if used[start_index]:
            continue
        used[start_index] = True
        chain: list[tuple[float, float]] = list(segments[start_index])
        guard = 0

        while key(chain[0]) != key(chain[-1]) and guard < len(segments) * 2:
            guard += 1
            tail_key = key(chain[-1])
            head_key = key(chain[0])
            advanced = False

            for index, segment in enumerate(segments):
                if used[index]:
                    continue
                a, b = key(segment[0]), key(segment[-1])
                if a == tail_key:
                    chain.extend(segment[1:])
                elif b == tail_key:
                    chain.extend(list(reversed(segment))[1:])
                else:
                    continue
                used[index] = True
                advanced = True
                break

            if advanced:
                continue

            for index, segment in enumerate(segments):
                if used[index]:
                    continue
                a, b = key(segment[0]), key(segment[-1])
                if b == head_key:
                    chain = segment + chain[1:]
                elif a == head_key:
                    chain = list(reversed(segment)) + chain[1:]
                else:
                    continue
                used[index] = True
                advanced = True
                break

            if not advanced:
                break

        if key(chain[0]) == key(chain[-1]) and len(chain) >= 4:
            rings.append(chain)

    return rings


def build_boundary(relation_payload: dict[str, Any]) -> dict[str, Any]:
    ways: list[list[tuple[float, float]]] = []
    for element in relation_payload.get("elements", []):
        if element.get("type") != "relation":
            continue
        for member in element.get("members", []):
            if member.get("type") != "way":
                continue
            if member.get("role") not in ("outer", ""):
                continue
            geometry = member.get("geometry") or []
            points = [(float(p["lat"]), float(p["lon"])) for p in geometry]
            if len(points) >= 2:
                ways.append(points)

    rings = chain_outer_rings(ways)
    if not rings:
        raise RuntimeError("no closed outer ring could be assembled")
    best = max(rings, key=lambda r: abs(signed_area(r)))
    coords = ring_from_points(best)
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "徐汇区",
                    "name_en": "Xuhui District",
                    "admin_level": "6",
                    "osm_relation_id": RELATION_ID,
                    "crs": "CRS84/WGS84 (lon,lat)",
                    "source": "OpenStreetMap via Overpass API",
                    "licence": "ODbL 1.0",
                    "retrieved_at": utc_now(),
                    "ring_vertex_count": len(coords),
                    "outer_way_count": len(ways),
                    "assembled_ring_count": len(rings),
                    "bbox": [min(lons), min(lats), max(lons), max(lats)],
                },
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            }
        ],
    }


def merge_elements(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Dedupe Overpass elements across bbox cells by (type, id)."""
    merged: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
    for chunk in chunks.get("payloads", []):
        for element in chunk.get("elements", []):
            merged[(element.get("type", ""), int(element.get("id", 0)))] = element
    return {"version": 0.6, "generator": "chunked-merge", "elements": list(merged.values())}


def chunked_fetch(name: str, template: str, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    path = SOURCES / name
    if path.exists() and path.stat().st_size > 2000:
        print(f"[cache] {name}", flush=True)
        return json.loads(path.read_text(encoding="utf-8"))

    west, south, east, north = bbox
    dlat = (north - south) / GRID
    dlon = (east - west) / GRID
    payloads: list[dict[str, Any]] = []
    for row in range(GRID):
        for col in range(GRID):
            cell = (
                south + row * dlat - 0.002,
                west + col * dlon - 0.002,
                south + (row + 1) * dlat + 0.002,
                west + (col + 1) * dlon + 0.002,
            )
            query = template.format(bbox=f"{cell[0]:.6f},{cell[1]:.6f},{cell[2]:.6f},{cell[3]:.6f}")
            print(f"  cell {row},{col} bbox={cell}", flush=True)
            payloads.append(post_overpass(query))
            time.sleep(2)

    merged: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
    for payload in payloads:
        for element in payload.get("elements", []):
            merged[(element.get("type", ""), int(element.get("id", 0)))] = element

    result = {
        "version": 0.6,
        "generator": "ai-scientist-round2 chunked overpass fetch",
        "source": "OpenStreetMap via Overpass API",
        "licence": "ODbL 1.0",
        "retrieved_at": utc_now(),
        "bbox": list(bbox),
        "grid": GRID,
        "cell_count": len(payloads),
        "elements": list(merged.values()),
    }
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> int:
    admin = cached(
        "osm_xuhui_admin_relation.json",
        f'relation({RELATION_ID});out geom;',
    )
    boundary = build_boundary(admin)
    (SOURCES / "xuhui_boundary.geojson").write_text(
        json.dumps(boundary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    props = boundary["features"][0]["properties"]
    print(
        f"boundary rings={props['assembled_ring_count']} outer_ways={props['outer_way_count']} "
        f"vertices={props['ring_vertex_count']} bbox={props['bbox']}",
        flush=True,
    )

    west, south, east, north = props["bbox"]
    bbox = (west - 0.01, south - 0.01, east + 0.01, north + 0.01)

    roads = chunked_fetch(
        "osm_xuhui_highways.json",
        'way["highway"~"^(' + HIGHWAY_TYPES + r')$"]({bbox});out geom;',
        bbox,
    )
    print(f"highway ways={len(roads['elements'])}", flush=True)

    pois = chunked_fetch(
        "osm_xuhui_pois.json",
        'nwr["railway"="station"]({bbox});nwr["leisure"~"^(park|garden|playground|sports_centre|stadium)$"]({bbox});'
        'nwr["natural"="water"]({bbox});nwr["waterway"="river"]({bbox});'
        'nwr["amenity"~"^(school|university|college|hospital|clinic)$"]({bbox});'
        'nwr["shop"="convenience"]({bbox});nwr["amenity"="toilets"]({bbox});'
        'nwr["amenity"="cafe"]({bbox});out center tags;',
        bbox,
    )
    print(f"poi elements={len(pois['elements'])}", flush=True)

    total_coords = sum(len(e.get("geometry", []) or []) for e in roads["elements"])
    print(f"road geometry nodes={total_coords}", flush=True)
    print("OSM_ACQUISITION_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
