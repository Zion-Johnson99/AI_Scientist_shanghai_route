from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import RouteSeed


RESEARCH_FILES = tuple(f"{mode}_route_candidates_0813.json" for mode in ("walk", "run", "bike"))
OPTIMIZATION_FILES = tuple(f"{mode}_route_optimization_0815.json" for mode in ("walk", "run", "bike"))
PROTECTED_GEOMETRY_IDS = {
    "XH_RUN_0033",
    "XH_RUN_0036",
    "XH_RUN_0053",
    "XH_BIKE_0066",
    "XH_BIKE_0083",
    "XH_BIKE_0088",
}


def merge_research_drafts(
    research_dir: Path,
    target: Path,
    validate: Callable[[list[dict[str, Any]]], None],
) -> list[dict[str, Any]]:
    missing = [name for name in RESEARCH_FILES if not (research_dir / name).is_file()]
    if missing:
        raise ValueError(f"missing research files: {missing}")
    merged: list[dict[str, Any]] = []
    for name in RESEARCH_FILES:
        payload = json.loads((research_dir / name).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"research file must contain a list: {name}")
        merged.extend(payload)
    validate(merged)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(merged, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return merged


def merge_route_optimizations(research_dir: Path, base_path: Path, target: Path) -> list[dict[str, Any]]:
    missing = [name for name in OPTIMIZATION_FILES if not (research_dir / name).is_file()]
    if missing:
        raise ValueError(f"missing optimization files: {missing}")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(base, list) or len(base) != 90:
        raise ValueError("base route seeds must contain exactly 90 items")

    work_items: list[dict[str, Any]] = []
    for name in OPTIMIZATION_FILES:
        payload = json.loads((research_dir / name).read_text(encoding="utf-8"))
        if not isinstance(payload, list) or len(payload) != 30:
            raise ValueError(f"optimization file must contain exactly 30 items: {name}")
        work_items.extend(payload)
    by_id = {item.get("route_id"): item for item in work_items if isinstance(item, dict)}
    expected_ids = [_route_id(item["route_mode"], index) for index, item in enumerate(base, start=1)]
    if set(by_id) != set(expected_ids) or len(by_id) != 90:
        raise ValueError("optimization route_id values must match the 90-route baseline")

    merged: list[dict[str, Any]] = []
    for index, old in enumerate(base, start=1):
        route_id = _route_id(old["route_mode"], index)
        item = by_id[route_id]
        if item.get("seed_id") != old.get("seed_id") or item.get("route_mode") != old.get("route_mode"):
            raise ValueError(f"optimization identity mismatch: {route_id}")
        expected_action = "preserve" if route_id in PROTECTED_GEOMETRY_IDS else "regenerate"
        if item.get("geometry_action") != expected_action:
            raise ValueError(f"geometry_action mismatch: {route_id}")
        source_record = next(
            (record for record in item.get("source_records", []) if record.get("source_url") or record.get("url")),
            {},
        )
        source_url = source_record.get("source_url") or source_record.get("url") or old["source_url"]
        start = _normalize_location(item["start_location"], source_url)
        end = _normalize_location(item["end_location"], source_url)
        nodes = [_normalize_node(node, source_url) for node in item["ordered_nodes"]]
        nodes[0] = _node_from_location(start, nodes[0])
        if item["route_shape"] == "strict_loop":
            if not _node_matches_location(nodes[-1], end):
                nodes.append(_node_from_location(end, nodes[0]))
            else:
                nodes[-1] = _node_from_location(end, nodes[-1])
        else:
            nodes[-1] = _node_from_location(end, nodes[-1])
        target_distance_m = int(item["target_distance_m"])
        candidate = {
            **old,
            "route_name": item["route_name"],
            "route_shape": item["route_shape"],
            "distance_level": f"{target_distance_m / 1000:g}km",
            "target_distance_m": target_distance_m,
            "start_hint": start["name"],
            "end_hint": end["name"],
            "start_location": start,
            "end_location": end,
            "waypoint_hints": list(item.get("waypoint_names", [])),
            "reason": item.get("design_rationale") or old["reason"],
            "source_name": source_record.get("source_name") or source_record.get("title") or source_record.get("publisher") or old["source_name"],
            "source_url": source_url,
            "source_accessed_at": source_record.get("accessed_at") or old["source_accessed_at"],
            "ordered_nodes": nodes,
            "evidence_note": item["evidence_note"],
            "access_restrictions": item["access_restrictions"],
            "amenity_ids": list(item.get("amenity_ids", [])),
            "geometry_action": item["geometry_action"],
        }
        merged.append(RouteSeed.model_validate(candidate).model_dump(mode="json"))
    _atomic_write(target, merged)
    return merged


def _route_id(mode: str, index: int) -> str:
    prefix = {"walk": "WALK", "run": "RUN", "bike": "BIKE"}[mode]
    return f"XH_{prefix}_{index:04d}"


def _normalize_location(raw: dict[str, Any], source_url: str) -> dict[str, Any]:
    return {
        "name": raw["name"],
        "location_type": raw.get("location_type") or "route_node",
        "lng_gcj02": float(raw["lng_gcj02"]),
        "lat_gcj02": float(raw["lat_gcj02"]),
        "source_url": raw.get("source_url") or source_url,
        "poi_id": raw.get("poi_id"),
    }


def _normalize_node(raw: dict[str, Any], source_url: str) -> dict[str, Any]:
    return {
        "node_name": raw.get("node_name") or raw.get("name"),
        "node_type": raw.get("node_type"),
        "source_url": raw.get("source_url") or source_url,
        "poi_id": raw.get("poi_id"),
        "lng_gcj02": float(raw["lng_gcj02"]),
        "lat_gcj02": float(raw["lat_gcj02"]),
    }


def _node_from_location(location: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    return {
        **template,
        "node_name": location["name"],
        "source_url": location["source_url"],
        "poi_id": location.get("poi_id"),
        "lng_gcj02": location["lng_gcj02"],
        "lat_gcj02": location["lat_gcj02"],
    }


def _node_matches_location(node: dict[str, Any], location: dict[str, Any]) -> bool:
    return (
        node["node_name"] == location["name"]
        and abs(node["lng_gcj02"] - location["lng_gcj02"]) <= 1e-6
        and abs(node["lat_gcj02"] - location["lat_gcj02"]) <= 1e-6
    )


def _atomic_write(target: Path, payload: list[dict[str, Any]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
