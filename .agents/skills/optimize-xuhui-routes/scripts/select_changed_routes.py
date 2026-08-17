#!/usr/bin/env python3
"""Classify route-seed changes so only affected work is repeated."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


GEOMETRY_FIELDS = {
    "route_mode",
    "route_shape",
    "start_location",
    "end_location",
    "ordered_nodes",
    "geometry_action",
}
AMENITY_FIELDS = {"amenity_ids"}
VALIDATION_FIELDS = {
    "target_distance_m",
    "region_zone",
    "allowed_modes",
    "access_restrictions",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two route-seed snapshots and classify changes.")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def load_index(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON list")
    index: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: item {position} is not an object")
        identifier = str(item.get("route_id") or item.get("seed_id") or "").strip()
        if not identifier:
            raise ValueError(f"{path}: item {position} has no route_id or seed_id")
        if identifier in index:
            raise ValueError(f"{path}: duplicate identifier {identifier}")
        index[identifier] = item
    return index


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if normalized(before.get(key), key) != normalized(after.get(key), key)]


def normalized(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: normalized(value[key], key) for key in sorted(value)}
    if isinstance(value, list):
        items = [normalized(item) for item in value]
        if field in {"amenity_ids", "allowed_modes", "access_restrictions", "tags"}:
            return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
        return items
    if isinstance(value, float):
        return round(value, 8)
    return value


def geometry_signature(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_mode": route.get("route_mode"),
        "route_shape": route.get("route_shape"),
        "geometry_action": route.get("geometry_action"),
        "start": _navigation_point(route.get("start_location")),
        "end": _navigation_point(route.get("end_location")),
        "ordered_nodes": [_navigation_point(node) for node in route.get("ordered_nodes") or []],
    }


def _navigation_point(value: Any) -> Any:
    if not isinstance(value, dict):
        return normalized(value)
    lng, lat = value.get("lng_gcj02"), value.get("lat_gcj02")
    if lng is not None and lat is not None:
        return {"lng_gcj02": normalized(lng), "lat_gcj02": normalized(lat)}
    return {
        "node_name": value.get("node_name") or value.get("name"),
        "poi_id": value.get("poi_id"),
    }


def classify(identifier: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    if before is None:
        return {"route_id": identifier, "change_types": ["added", "geometry_changed"], "changed_fields": sorted(after or {})}
    if after is None:
        return {"route_id": identifier, "change_types": ["removed"], "changed_fields": sorted(before)}

    fields = changed_fields(before, after)
    change_types: list[str] = []
    covered_fields: set[str] = set()
    if geometry_signature(before) != geometry_signature(after):
        change_types.append("geometry_changed")
        covered_fields.update(field for field in fields if field in GEOMETRY_FIELDS)
    if any(field in AMENITY_FIELDS for field in fields):
        change_types.append("amenity_changed")
        covered_fields.update(field for field in fields if field in AMENITY_FIELDS)
    if any(field in VALIDATION_FIELDS for field in fields):
        change_types.append("validation_changed")
        covered_fields.update(field for field in fields if field in VALIDATION_FIELDS)
    if any(field not in covered_fields for field in fields):
        change_types.append("metadata_changed")
    if not change_types:
        change_types.append("unchanged")
    return {"route_id": identifier, "change_types": change_types, "changed_fields": fields}


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    baseline = load_index(args.baseline)
    current = load_index(args.current)
    identifiers = sorted(set(baseline) | set(current))
    routes = [classify(identifier, baseline.get(identifier), current.get(identifier)) for identifier in identifiers]
    summary = {
        change_type: sum(change_type in route["change_types"] for route in routes)
        for change_type in (
            "added",
            "removed",
            "geometry_changed",
            "amenity_changed",
            "validation_changed",
            "metadata_changed",
            "unchanged",
        )
    }
    payload = {"routes_compared": len(routes), "summary": summary, "routes": routes}
    if args.report:
        write_report(args.report, payload)
    print(f"routes_compared={len(routes)} " + " ".join(f"{key}={value}" for key, value in summary.items()))
    for route in routes:
        if route["change_types"] != ["unchanged"]:
            print(f"{route['route_id']}: {','.join(route['change_types'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
