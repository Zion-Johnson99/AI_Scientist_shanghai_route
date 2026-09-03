"""Generate 90 route data files for xuhui_route_builder.

Produces:
- route_catalog.json (90 items, walk/run/bike 30 each)
- xuhui_routes.geojson (FeatureCollection, 90 features)
- xuhui_entries.geojson (entry points)
- poi_catalog.json
- access_cases.json
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

# Deterministic seed for reproducibility
_RNG = random.Random(2024)

# Xuhui district approximate bounding box (GCJ-02)
_LAT_MIN, _LAT_MAX = 31.14, 31.22
_LNG_MIN, _LNG_MAX = 121.38, 121.50

# Distance bands per mode (meters)
_DISTANCE_BANDS: dict[str, list[tuple[float, float]]] = {
    "walk": [(2000, 3000), (3000, 4000), (4000, 5000)],
    "run": [(3000, 5000), (5000, 7000), (7000, 9000)],
    "bike": [(5000, 8000), (8000, 11000), (11000, 15000)],
}

# Route name templates per mode
_NAME_TEMPLATES: dict[str, list[str]] = {
    "walk": [
        "滨江步道{idx}", "公园环道{idx}", "社区漫步{idx}", "河滨绿道{idx}",
        "历史街区{idx}", "校园周边{idx}", "商业休闲{idx}", "林荫小道{idx}",
        "湖畔环线{idx}", "文化走廊{idx}",
    ],
    "run": [
        "滨江跑道{idx}", "公园环线{idx}", "绿道竞速{idx}", "河堤长跑{idx}",
        "城市穿越{idx}", "体育场周边{idx}", "林荫跑道{idx}", "湖畔竞速{idx}",
        "社区环跑{idx}", "夜间安全跑{idx}",
    ],
    "bike": [
        "滨江骑行{idx}", "绿道长线{idx}", "城市环线{idx}", "河滨骑行{idx}",
        "公园穿越{idx}", "通勤骑行{idx}", "郊野骑行{idx}", "文化骑行{idx}",
        "夜间骑行{idx}", "休闲骑行{idx}",
    ],
}


def _generate_linestring(
    rng: random.Random,
    target_distance_m: float,
) -> list[list[float]]:
    """Generate a plausible LineString with approximate target distance.

    Uses a random walk approach within the bounding box.
    Coordinates are [lng, lat] per GeoJSON spec.
    """
    # Approximate meters per degree at Shanghai latitude
    m_per_deg_lat = 111_000.0
    m_per_deg_lng = 111_000.0 * math.cos(math.radians(31.18))

    # Number of segments: more for longer routes
    n_segments = max(4, int(target_distance_m / 400))
    segment_length_m = target_distance_m / n_segments

    # Start point
    lat = rng.uniform(_LAT_MIN + 0.01, _LAT_MAX - 0.01)
    lng = rng.uniform(_LNG_MIN + 0.01, _LNG_MAX - 0.01)

    coords: list[list[float]] = [[round(lng, 6), round(lat, 6)]]

    # Random direction with persistence (smooth turns)
    heading = rng.uniform(0, 2 * math.pi)

    for _ in range(n_segments):
        # Turn: small random deviation
        heading += rng.gauss(0, 0.4)

        d_lat = (segment_length_m / m_per_deg_lat) * math.cos(heading)
        d_lng = (segment_length_m / m_per_deg_lng) * math.sin(heading)

        lat += d_lat
        lng += d_lng

        # Clamp to bounding box with reflection
        if lat < _LAT_MIN:
            lat = 2 * _LAT_MIN - lat
            heading = -heading
        elif lat > _LAT_MAX:
            lat = 2 * _LAT_MAX - lat
            heading = -heading

        if lng < _LNG_MIN:
            lng = 2 * _LNG_MIN - lng
            heading = math.pi - heading
        elif lng > _LNG_MAX:
            lng = 2 * _LNG_MAX - lng
            heading = math.pi - heading

        coords.append([round(lng, 6), round(lat, 6)])

    return coords


def _compute_distance_m(coords: list[list[float]]) -> float:
    """Compute approximate polyline distance in meters."""
    m_per_deg_lat = 111_000.0
    m_per_deg_lng = 111_000.0 * math.cos(math.radians(31.18))

    total = 0.0
    for i in range(1, len(coords)):
        d_lng = (coords[i][0] - coords[i - 1][0]) * m_per_deg_lng
        d_lat = (coords[i][1] - coords[i - 1][1]) * m_per_deg_lat
        total += math.sqrt(d_lng**2 + d_lat**2)
    return total


def generate_routes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate 90 route catalog entries and GeoJSON features.

    Returns:
        Tuple of (catalog_entries, geojson_features).
    """
    catalog: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []

    modes = ["walk", "run", "bike"]
    routes_per_mode = 30

    for mode in modes:
        templates = _NAME_TEMPLATES[mode]
        bands = _DISTANCE_BANDS[mode]

        for i in range(routes_per_mode):
            route_idx = i + 1
            route_id = f"{mode}-{route_idx:03d}"

            # Assign distance band round-robin
            band = bands[i % len(bands)]
            target_distance = _RNG.uniform(band[0], band[1])

            # Name
            template = templates[i % len(templates)]
            route_name = template.format(idx=route_idx)

            # Generate geometry
            coords = _generate_linestring(_RNG, target_distance)
            actual_distance = _compute_distance_m(coords)

            # Catalog entry
            entry: dict[str, Any] = {
                "route_id": route_id,
                "route_name": route_name,
                "route_mode": mode,
                "distance_m": round(actual_distance, 1),
                "target_distance_m": round(target_distance, 1),
                "validation_status": "accepted",
                "geometry_status": "valid",
                "coordinate_system": "GCJ-02",
                "distance_band": f"{band[0]}-{band[1]}",
                "description": f"{route_name}，全长约{actual_distance/1000:.1f}公里，适合{mode}运动。",
            }
            catalog.append(entry)

            # GeoJSON feature
            feature: dict[str, Any] = {
                "type": "Feature",
                "properties": {
                    "route_id": route_id,
                    "route_name": route_name,
                    "route_mode": mode,
                    "distance_m": round(actual_distance, 1),
                    "validation_status": "accepted",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            }
            features.append(feature)

    return catalog, features


def generate_entries(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate entry point features for routes."""
    entries: list[dict[str, Any]] = []
    for entry in catalog:
        # Each route gets one entry point (start)
        entry_feature: dict[str, Any] = {
            "type": "Feature",
            "properties": {
                "entry_id": f"entry-{entry['route_id']}",
                "route_id": entry["route_id"],
                "entry_type": "start",
                "accessibility": "public",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [
                    _RNG.uniform(_LNG_MIN + 0.01, _LNG_MAX - 0.01),
                    _RNG.uniform(_LAT_MIN + 0.01, _LAT_MAX - 0.01),
                ],
            },
        }
        entries.append(entry_feature)
    return entries


def generate_poi_catalog() -> list[dict[str, Any]]:
    """Generate a POI catalog with common facility types."""
    poi_types = [
        ("toilet", "公共厕所", 15),
        ("water_station", "饮水点", 12),
        ("bench", "休息座椅", 20),
        ("park_entrance", "公园入口", 10),
        ("convenience_store", "便利店", 18),
        ("first_aid", "急救点", 5),
        ("parking", "停车场", 8),
        ("bike_station", "自行车租赁点", 10),
    ]

    pois: list[dict[str, Any]] = []
    poi_id = 1
    for poi_type, name_prefix, count in poi_types:
        for i in range(count):
            pois.append({
                "poi_id": f"poi-{poi_id:04d}",
                "poi_type": poi_type,
                "name": f"{name_prefix}{i + 1}号",
                "lng": round(_RNG.uniform(_LNG_MIN, _LNG_MAX), 6),
                "lat": round(_RNG.uniform(_LAT_MIN, _LAT_MAX), 6),
                "coordinate_system": "GCJ-02",
            })
            poi_id += 1

    return pois


def generate_access_cases(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate sample access cases for route connectivity."""
    cases: list[dict[str, Any]] = []
    # Pick a subset of routes for access cases
    sample_routes = catalog[::3]  # Every 3rd route
    for i, route in enumerate(sample_routes):
        cases.append({
            "case_id": f"access-{i + 1:03d}",
            "route_id": route["route_id"],
            "origin_type": _RNG.choice(["metro_station", "bus_stop", "residential", "commercial"]),
            "origin_name": f"示例起点{i + 1}",
            "distance_to_route_m": round(_RNG.uniform(50, 500), 1),
            "walk_time_min": round(_RNG.uniform(1, 7), 1),
            "has_bike_parking": _RNG.random() > 0.5,
            "has_toilet_nearby": _RNG.random() > 0.4,
        })
    return cases


def write_output(
    output_dir: Path,
    catalog: list[dict[str, Any]],
    features: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    pois: list[dict[str, Any]],
    access_cases: list[dict[str, Any]],
) -> None:
    """Write all generated data files to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # route_catalog.json
    catalog_path = output_dir / "route_catalog.json"
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # xuhui_routes.geojson
    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }
    geojson_path = output_dir / "xuhui_routes.geojson"
    geojson_path.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # xuhui_entries.geojson
    entries_geojson = {
        "type": "FeatureCollection",
        "features": entries,
    }
    entries_path = output_dir / "xuhui_entries.geojson"
    entries_path.write_text(
        json.dumps(entries_geojson, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # poi_catalog.json
    poi_path = output_dir / "poi_catalog.json"
    poi_path.write_text(
        json.dumps(pois, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # access_cases.json
    access_path = output_dir / "access_cases.json"
    access_path.write_text(
        json.dumps(access_cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(output_dir: str | Path | None = None) -> None:
    """Main entry point for data generation."""
    if output_dir is None:
        # Default: relative to package root
        output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "web"
    else:
        output_dir = Path(output_dir)

    catalog, features = generate_routes()
    entries = generate_entries(catalog)
    pois = generate_poi_catalog()
    access_cases = generate_access_cases(catalog)

    write_output(output_dir, catalog, features, entries, pois, access_cases)

    print(f"Generated {len(catalog)} routes to {output_dir}")
    print(f"  walk: {sum(1 for r in catalog if r['route_mode'] == 'walk')}")
    print(f"  run:  {sum(1 for r in catalog if r['route_mode'] == 'run')}")
    print(f"  bike: {sum(1 for r in catalog if r['route_mode'] == 'bike')}")
    print(f"  POIs: {len(pois)}")
    print(f"  Access cases: {len(access_cases)}")


if __name__ == "__main__":
    main()
