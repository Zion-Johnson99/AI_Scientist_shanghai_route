#!/usr/bin/env python3
"""Deterministic route catalog contract check (stdlib only, no network).

Checks per docs/qwen-harness-build/02 §6.7:
  - route_catalog.json holds 90 routes, 30 per route_mode (walk/run/bike);
  - route_id values are unique;
  - catalog route_id set equals xuhui_routes.geojson feature route_id set;
  - validation_status values are from the accepted set;
  - route_shape values are one_way/strict_loop.

Usage: python verify_route_catalog.py [--data-dir PATH]
Default data dir: <repo>/xuhui_route_builder/data/web
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

MODES = {"walk": 30, "run": 30, "bike": 30}
SHAPES = {"one_way", "strict_loop"}
EXPECTED_TOTAL = 90


def load_json(path: Path, problems: list):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        problems.append(f"invalid JSON in {path}: {exc}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify route catalog contract")
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()

    data_dir = args.data_dir or (
        Path(__file__).resolve().parents[4] / "xuhui_route_builder" / "data" / "web"
    )
    problems: list[str] = []

    catalog = load_json(data_dir / "route_catalog.json", problems)
    geojson = load_json(data_dir / "xuhui_routes.geojson", problems)
    if catalog is None or geojson is None:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1

    if not isinstance(catalog, list):
        problems.append("route_catalog.json must be a JSON array")
        catalog = []
    features = geojson.get("features", []) if isinstance(geojson, dict) else []

    # Count and mode distribution.
    if len(catalog) != EXPECTED_TOTAL:
        problems.append(f"route count is {len(catalog)}, expected {EXPECTED_TOTAL}")
    mode_counts = Counter(r.get("route_mode") for r in catalog if isinstance(r, dict))
    for mode, expected in MODES.items():
        actual = mode_counts.get(mode, 0)
        if actual != expected:
            problems.append(f"mode '{mode}' has {actual} routes, expected {expected}")

    # ID uniqueness and required fields.
    catalog_ids = []
    for idx, route in enumerate(catalog):
        if not isinstance(route, dict):
            problems.append(f"catalog entry #{idx} is not an object")
            continue
        rid = route.get("route_id")
        if not rid:
            problems.append(f"catalog entry #{idx} missing route_id")
        catalog_ids.append(rid)
        if route.get("route_shape") not in SHAPES:
            problems.append(f"route {rid}: invalid route_shape {route.get('route_shape')!r}")
        if route.get("validation_status") != "accepted":
            problems.append(
                f"route {rid}: validation_status is {route.get('validation_status')!r}, expected 'accepted'"
            )
    duplicates = [rid for rid, count in Counter(catalog_ids).items() if count > 1]
    if duplicates:
        problems.append(f"duplicate route_id values: {sorted(duplicates)}")

    # GeoJSON consistency.
    geo_ids = []
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature, dict) else {}
        rid = props.get("route_id")
        if not rid:
            problems.append("geojson feature missing properties.route_id")
        geo_ids.append(rid)
    catalog_set, geo_set = set(catalog_ids), set(geo_ids)
    if catalog_set - geo_set:
        problems.append(f"catalog ids missing from geojson: {sorted(catalog_set - geo_set)}")
    if geo_set - catalog_set:
        problems.append(f"geojson ids missing from catalog: {sorted(geo_set - catalog_set)}")

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1
    print(
        "PASS: route catalog has 90 routes (walk/run/bike = 30/30/30), "
        "unique ids, catalog/geojson consistency and accepted status"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
