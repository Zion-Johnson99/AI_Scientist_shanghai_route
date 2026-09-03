"""Acquire Xuhui road network and POIs from public Overpass mirrors.

Robustness notes learned from the failed fetch_osm2.py attempt:
  * a non-JSON body (HTML 5xx page) must be treated as a retryable mirror failure;
  * every query carries an explicit [out:json][timeout:N][maxsize:M] header;
  * per-cell failures are tolerated and recorded instead of aborting the run.

Only public OSM data is read. No credentials, no paid API.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
SOURCES = RUN_ROOT / "sources"
COMMANDS = RUN_ROOT / "commands"

BOUNDARY_PATH = SOURCES / "xuhui_boundary.geojson"
HIGHWAYS_PATH = SOURCES / "osm_xuhui_highways.json"
POIS_PATH = SOURCES / "osm_xuhui_pois.json"
STATUS_PATH = COMMANDS / "fetch_osm3_status.json"

GRID = 4
PAD = 0.0025
USER_AGENT = "ai-scientist-round2-research/1.0 (offline scientific run; contact: none)"
OVERPASS_TIMEOUT = 180
MAXSIZE = 536_870_936

MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)

HIGHWAY_TYPES = "|".join(
    (
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
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
    )
)

POI_SELECTOR = (
    'nwr["railway"="station"]({bbox});'
    'nwr["railway"="subway_entrance"]({bbox});'
    'nwr["leisure"~"^(park|garden|playground|sports_centre|stadium|fitness_centre)$"]({bbox});'
    'nwr["natural"="water"]({bbox});'
    'nwr["waterway"~"^(river|canal|stream)$"]({bbox});'
    'nwr["amenity"~"^(school|university|college|hospital|clinic|kindergarten)$"]({bbox});'
    'nwr["shop"="convenience"]({bbox});'
    'nwr["amenity"="toilets"]({bbox});'
    'nwr["amenity"~"^(cafe|restaurant)$"]({bbox});'
    'nwr["tourism"~"^(attraction|museum|artwork)$"]({bbox});'
)

status: dict[str, object] = {
    "script": "fetch_osm3.py",
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "mirrors": list(MIRRORS),
    "grid": GRID,
    "requests": [],
    "highways_ok": False,
    "pois_ok": False,
}


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with (COMMANDS / "fetch_osm3.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def header(timeout: int = OVERPASS_TIMEOUT) -> str:
    return f"[out:json][timeout:{timeout}][maxsize:{MAXSIZE}];"


def post_overpass(query: str, label: str, timeout: int = 300) -> dict:
    """Return parsed Overpass JSON, rotating mirrors on any failure.

    Retries on transport errors, HTTP errors and malformed bodies. A body that is
    not valid JSON is almost always an HTML gateway error page, so it is treated
    as retryable rather than fatal.
    """
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    attempts = len(MIRRORS) * 2
    last = "no attempt made"
    for attempt in range(attempts):
        mirror = MIRRORS[attempt % len(MIRRORS)]
        request = urllib.request.Request(
            mirror,
            data=payload,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )
        started = time.time()
        outcome: str
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                outcome = f"non_json_body({type(exc).__name__}, {len(body)} bytes)"
                last = outcome
            else:
                elapsed = round(time.time() - started, 1)
                count = len(parsed.get("elements", []))
                status["requests"].append(  # type: ignore[union-attr]
                    {
                        "label": label,
                        "mirror": mirror,
                        "attempt": attempt + 1,
                        "outcome": "ok",
                        "elements": count,
                        "seconds": elapsed,
                    }
                )
                log(f"  ok {label} via {mirror} attempt={attempt + 1} elements={count} {elapsed}s")
                return parsed
        except urllib.error.HTTPError as exc:
            outcome = f"HTTP {exc.code}"
            last = outcome
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            outcome = f"{type(exc).__name__}: {exc}"
            last = outcome
        status["requests"].append(  # type: ignore[union-attr]
            {
                "label": label,
                "mirror": mirror,
                "attempt": attempt + 1,
                "outcome": outcome,
                "seconds": round(time.time() - started, 1),
            }
        )
        log(f"  fail {label} via {mirror} attempt={attempt + 1}: {outcome}")
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"all overpass mirrors failed for {label}; last error: {last}")


def boundary_bbox() -> tuple[float, float, float, float]:
    payload = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    ring = payload["features"][0]["geometry"]["coordinates"][0]
    lons = [float(point[0]) for point in ring]
    lats = [float(point[1]) for point in ring]
    return min(lons), min(lats), max(lons), max(lats)


def cells(bbox: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    west, south, east, north = bbox
    dx = (east - west) / GRID
    dy = (north - south) / GRID
    out: list[tuple[float, float, float, float]] = []
    for row in range(GRID):
        for col in range(GRID):
            cell_west = west + col * dx - PAD
            cell_south = south + row * dy - PAD
            cell_east = west + (col + 1) * dx + PAD
            cell_north = south + (row + 1) * dy + PAD
            out.append((cell_south, cell_west, cell_north, cell_east))
    return out


def already_cached(path: Path, minimum_bytes: int) -> bool:
    return path.exists() and path.stat().st_size > minimum_bytes


def chunked_fetch(path: Path, name: str, template: str, bbox: tuple[float, float, float, float]) -> bool:
    """Fetch per cell; tolerate individual cell failure and record it."""
    if already_cached(path, 5000):
        log(f"{name}: using cache ({path.stat().st_size} bytes)")
        return True

    merged: dict[tuple[str, int], dict] = {}
    failures: list[dict] = []
    grid_cells = cells(bbox)
    for index, cell in enumerate(grid_cells, start=1):
        label = f"{name} cell {index}/{len(grid_cells)}"
        query = header() + template.format(bbox=f"{cell[0]},{cell[1]},{cell[2]},{cell[3]}") + "out geom;"
        try:
            payload = post_overpass(query, label)
        except RuntimeError as exc:
            log(f"  SKIP {label}: {exc}")
            failures.append({"cell": index, "bbox": list(cell), "error": str(exc)})
            continue
        for element in payload.get("elements", []):
            element_type = element.get("type", "?")
            element_id = element.get("id")
            if element_id is None:
                continue
            merged[(element_type, int(element_id))] = element
        log(f"  merged total = {len(merged)}")
        time.sleep(3)

    record = {
        "version": 1,
        "generator": "fetch_osm3.py",
        "source": "OpenStreetMap via Overpass API",
        "licence": "ODbL 1.0",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bbox": list(bbox),
        "grid": GRID,
        "cell_count": len(grid_cells),
        "cell_failures": failures,
        "element_count": len(merged),
        "elements": list(merged.values()),
    }
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    ok = len(merged) > 0
    log(f"{name}: wrote {len(merged)} elements, {len(failures)} cell failures, ok={ok}")
    return ok


def main() -> int:
    SOURCES.mkdir(parents=True, exist_ok=True)
    bbox = boundary_bbox()
    log(f"bbox = {bbox}")

    status["bbox"] = list(bbox)
    status["highways_ok"] = chunked_fetch(
        HIGHWAYS_PATH,
        "osm_xuhui_highways",
        f'way["highway"~"^({HIGHWAY_TYPES})$"]({{bbox}});',
        bbox,
    )
    status["pois_ok"] = chunked_fetch(
        POIS_PATH,
        "osm_xuhui_pois",
        POI_SELECTOR.replace("out geom;", ""),
        bbox,
    )
    status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")

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
