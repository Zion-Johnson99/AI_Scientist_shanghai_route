"""Acquire the Xuhui road network and POIs from the official OSM API 0.6 /map endpoint.

The Overpass mirrors returned HTTP 500/502/504 for every attempt in this run, so
this script uses a completely different public server
(https://api.openstreetmap.org/api/0.6/map) which serves raw OSM XML for a bbox.
The district bbox is about 0.010 square degrees, far below the endpoint's 0.25
square degree limit; it is nevertheless cut into a grid so that no single cell can
hit the 50,000 node ceiling. Cells that still overflow are split recursively.

Output is written in the same element shape that ``routes.road_graph.build_graph``
consumes, so no downstream code needs to know which endpoint produced it.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
SOURCES = RUN_ROOT / "sources"
COMMANDS = RUN_ROOT / "commands"

BOUNDARY_PATH = SOURCES / "xuhui_boundary.geojson"
HIGHWAYS_PATH = SOURCES / "osm_xuhui_highways.json"
POIS_PATH = SOURCES / "osm_xuhui_pois.json"
STATUS_PATH = COMMANDS / "fetch_osm4_status.json"

API = "https://api.openstreetmap.org/api/0.6/map"
USER_AGENT = "ai-scientist-round2-research/1.0 (offline scientific run)"
GRID = 6
PAD = 0.001
SLEEP_S = 1.5
MAX_DEPTH = 3

HIGHWAY_TYPES = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "pedestrian",
        "footway",
        "path",
        "cycleway",
        "steps",
        "track",
        "bridleway",
        "road",
        "construction",
    }
)

POI_KEYS = frozenset(
    {
        "railway",
        "leisure",
        "natural",
        "waterway",
        "amenity",
        "shop",
        "tourism",
        "historic",
        "sport",
        "public_transport",
        "entrance",
    }
)
POI_AMENITY_KEEP = frozenset(
    {
        "school",
        "university",
        "college",
        "hospital",
        "clinic",
        "kindergarten",
        "toilets",
        "cafe",
        "restaurant",
        "drinking_water",
        "bench",
        "shelter",
        "bus_station",
        "ferry_terminal",
        "place_of_worship",
    }
)

status: dict[str, object] = {
    "script": "fetch_osm4_api.py",
    "endpoint": API,
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "grid": GRID,
    "requests": [],
    "highways_ok": False,
    "pois_ok": False,
}


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with (COMMANDS / "fetch_osm4.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def fetch_cell(cell: tuple[float, float, float, float], depth: int = 0) -> ET.Element | None:
    west, south, east, north = cell
    url = f"{API}?{urllib.parse.urlencode({'bbox': f'{west},{south},{east},{north}'})}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read()
        root = ET.fromstring(body)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except OSError:
            pass
        too_big = exc.code in (400, 413) and ("too many nodes" in detail or "too large" in detail)
        status["requests"].append(  # type: ignore[union-attr]
            {"bbox": list(cell), "outcome": f"HTTP {exc.code}", "detail": detail, "seconds": round(time.time() - started, 1)}
        )
        log(f"  HTTP {exc.code} depth={depth} bbox={cell}: {detail[:120]}")
        if too_big and depth < MAX_DEPTH:
            return None
        if exc.code >= 500 and depth <= MAX_DEPTH:
            time.sleep(10 * (depth + 1))
            return fetch_cell(cell, depth + 1)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError) as exc:
        status["requests"].append(  # type: ignore[union-attr]
            {"bbox": list(cell), "outcome": f"{type(exc).__name__}", "seconds": round(time.time() - started, 1)}
        )
        log(f"  {type(exc).__name__} depth={depth} bbox={cell}")
        time.sleep(8 * (depth + 1))
        if depth < MAX_DEPTH:
            return fetch_cell(cell, depth + 1)
        return None
    status["requests"].append(  # type: ignore[union-attr]
        {
            "bbox": list(cell),
            "outcome": "ok",
            "bytes": len(body),
            "seconds": round(time.time() - started, 1),
        }
    )
    return root


def split(cell: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    west, south, east, north = cell
    mid_x = (west + east) / 2
    mid_y = (south + north) / 2
    return [
        (west, south, mid_x, mid_y),
        (mid_x, south, east, mid_y),
        (west, mid_y, mid_x, north),
        (mid_x, mid_y, east, north),
    ]


def harvest(
    cell: tuple[float, float, float, float],
    ways: dict[int, dict],
    pois: dict[tuple[str, int], dict],
    depth: int = 0,
) -> bool:
    root = fetch_cell(cell, depth)
    if root is None:
        if depth >= MAX_DEPTH:
            log(f"  GIVE UP on bbox={cell}")
            return False
        ok = True
        for sub in split(cell):
            ok = harvest(sub, ways, pois, depth + 1) and ok
            time.sleep(SLEEP_S)
        return ok

    node_xy: dict[int, tuple[float, float]] = {}
    node_tags: dict[int, dict[str, str]] = {}
    for node in root.iter("node"):
        node_id = int(node.get("id", "0"))
        try:
            node_xy[node_id] = (float(node.get("lon", "0")), float(node.get("lat", "0")))
        except ValueError:
            continue
        tags = {tag.get("k", ""): tag.get("v", "") for tag in node.findall("tag")}
        if tags:
            node_tags[node_id] = tags

    for node_id, tags in node_tags.items():
        if keep_poi(tags):
            lon, lat = node_xy[node_id]
            pois[("node", node_id)] = {
                "type": "node",
                "id": node_id,
                "tags": tags,
                "lat": lat,
                "lon": lon,
                "center": {"lat": lat, "lon": lon},
            }

    for way in root.iter("way"):
        way_id = int(way.get("id", "0"))
        tags = {tag.get("k", ""): tag.get("v", "") for tag in way.findall("tag")}
        refs = [int(nd.get("ref", "0")) for nd in way.findall("nd")]
        geometry = [{"lon": node_xy[r][0], "lat": node_xy[r][1]} for r in refs if r in node_xy]
        if len(geometry) < 2:
            continue
        highway = tags.get("highway", "")
        if highway in HIGHWAY_TYPES:
            ways[way_id] = {"type": "way", "id": way_id, "tags": tags, "geometry": geometry}
        if keep_poi(tags):
            lon = sum(p["lon"] for p in geometry) / len(geometry)
            lat = sum(p["lat"] for p in geometry) / len(geometry)
            pois[("way", way_id)] = {
                "type": "way",
                "id": way_id,
                "tags": tags,
                "center": {"lat": lat, "lon": lon},
                "geometry": geometry,
            }
    log(f"  cell depth={depth} ways={len(ways)} pois={len(pois)}")
    return True


def keep_poi(tags: dict[str, str]) -> bool:
    if "railway" in tags and tags["railway"] in {"station", "subway_entrance", "halt", "tram_stop"}:
        return True
    if "leisure" in tags and tags["leisure"] in {"park", "garden", "playground", "sports_centre", "stadium", "fitness_centre", "nature_reserve"}:
        return True
    if tags.get("natural") == "water":
        return True
    if "waterway" in tags and tags["waterway"] in {"river", "canal", "stream"}:
        return True
    if "amenity" in tags and tags["amenity"] in POI_AMENITY_KEEP:
        return True
    if "tourism" in tags and tags["tourism"] in {"attraction", "museum", "artwork", "viewpoint"}:
        return True
    if "historic" in tags:
        return True
    if tags.get("shop") in {"convenience", "supermarket", "sports", "bicycle"}:
        return True
    if tags.get("sport") in {"running", "athletics", "soccer", "basketball", "tennis", "swimming"}:
        return True
    return False


def boundary_bbox() -> tuple[float, float, float, float]:
    payload = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    ring = payload["features"][0]["geometry"]["coordinates"][0]
    lons = [float(point[0]) for point in ring]
    lats = [float(point[1]) for point in ring]
    return min(lons), min(lats), max(lons), max(lats)


def grid_cells(bbox: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    west, south, east, north = bbox
    dx = (east - west) / GRID
    dy = (north - south) / GRID
    out: list[tuple[float, float, float, float]] = []
    for row in range(GRID):
        for col in range(GRID):
            out.append(
                (
                    west + col * dx - PAD,
                    south + row * dy - PAD,
                    west + (col + 1) * dx + PAD,
                    south + (row + 1) * dy + PAD,
                )
            )
    return out


def write_record(path: Path, elements: list[dict], bbox: tuple[float, float, float, float], cells: int) -> None:
    record = {
        "version": 1,
        "generator": "fetch_osm4_api.py",
        "source": "OpenStreetMap via api.openstreetmap.org /api/0.6/map",
        "licence": "ODbL 1.0",
        "crs": "CRS84/WGS84 (lon,lat)",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bbox": list(bbox),
        "grid": GRID,
        "cell_count": cells,
        "element_count": len(elements),
        "elements": elements,
    }
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {path.name}: {len(elements)} elements")


def main() -> int:
    SOURCES.mkdir(parents=True, exist_ok=True)
    bbox = boundary_bbox()
    cells = grid_cells(bbox)
    status["bbox"] = list(bbox)
    log(f"bbox={bbox} cells={len(cells)}")

    ways: dict[int, dict] = {}
    pois: dict[tuple[str, int], dict] = {}
    failed_cells = 0
    for index, cell in enumerate(cells, start=1):
        log(f"cell {index}/{len(cells)} {cell}")
        if not harvest(cell, ways, pois):
            failed_cells += 1
        time.sleep(SLEEP_S)

    status["failed_cells"] = failed_cells
    write_record(HIGHWAYS_PATH, list(ways.values()), bbox, len(cells))
    write_record(POIS_PATH, list(pois.values()), bbox, len(cells))
    status["highway_way_count"] = len(ways)
    status["poi_count"] = len(pois)
    status["highways_ok"] = len(ways) > 500
    status["pois_ok"] = len(pois) > 20
    status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"RESULT highways_ok={status['highways_ok']} pois_ok={status['pois_ok']} failed_cells={failed_cells}")
    if status["highways_ok"]:
        log("OSM_ACQUISITION_OK")
        return 0
    log("OSM_ACQUISITION_FAILED")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - top-level guard for a batch script
        log(f"FATAL {type(exc).__name__}: {exc}")
        status["fatal"] = f"{type(exc).__name__}: {exc}"
        status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        sys.exit(2)
