from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
CANDIDATE_PATH = PROJECT_ROOT / "data/interim/pilot_candidates.json"
VALIDATION_REPORT_PATH = PROJECT_ROOT / "data/processed/route_validation_report.json"
OUTPUT_PATH = PROJECT_ROOT / "data/processed/bike_rebuild_baseline_20260820.json"
QUALITY_GATE_PATH = (
    REPO_ROOT / ".agents/skills/optimize-xuhui-routes/scripts/route_quality_gate.py"
)

CONDITIONAL_PRESERVE = {"XH_BIKE_0068"}
PLACEHOLDER_PATTERN = re.compile(r"实测|(?:节点|node)[-_ ]*\d+$|^\d+$", re.IGNORECASE)


def distance_band(distance_m: float) -> str:
    if 5_000 <= distance_m < 10_000:
        return "short"
    if 10_000 <= distance_m < 20_000:
        return "medium"
    if 20_000 <= distance_m <= 30_000:
        return "long"
    return "out_of_range"


def _geometry_hash(route: dict[str, Any]) -> str:
    points = [
        [round(float(point["lng_gcj02"]), 7), round(float(point["lat_gcj02"]), 7)]
        for point in route.get("polyline_gcj02", [])
    ]
    canonical = json.dumps(points, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _poi_summary(route: dict[str, Any]) -> dict[str, Any]:
    verified = [
        poi
        for poi in route.get("nearby_pois", [])
        if poi.get("verification_status", "verified") == "verified"
    ]
    type_counts = Counter(poi.get("poi_type", "unknown") for poi in verified)
    preference_hits = sorted(
        {
            poi["poi_type"]
            for poi in verified
            if poi.get("poi_type")
            in {"coffee", "park_gate", "toilet", "convenience"}
        }
    )
    supply_warning = float(route.get("actual_distance_m", 0)) > 10_000 and not (
        {"toilet", "convenience"} & set(preference_hits)
    )
    coordinate_systems = sorted(
        {str(poi.get("coordinate_system", "unknown")) for poi in verified}
    )
    return {
        "verified_count": len(verified),
        "verified_type_counts": dict(sorted(type_counts.items())),
        "preference_hits_from_verified_pois": preference_hits,
        "stored_preference_hits": sorted(route.get("preference_hits", [])),
        "supply_warning": supply_warning,
        "coordinate_systems": coordinate_systems,
    }


def _classification(route_id: str) -> str:
    if route_id in CONDITIONAL_PRESERVE:
        return "unchanged_pending_visual_audit"
    return "geometry_changed"


def build_record(
    route: dict[str, Any], gate: dict[str, Any], validation_status: str
) -> dict[str, Any]:
    node_names = [
        str(node.get("node_name", "")).strip()
        for node in route.get("ordered_nodes", [])
    ]
    placeholder_names = [
        name for name in node_names if PLACEHOLDER_PATTERN.search(name)
    ]
    return {
        "route_id": route["route_id"],
        "route_name": route.get("route_name"),
        "region_zone": route.get("region_zone"),
        "popular_area_ids": route.get("popular_area_ids", []),
        "actual_distance_m": route.get("actual_distance_m"),
        "target_distance_m": route.get("target_distance_m"),
        "distance_band": distance_band(float(route.get("actual_distance_m", 0))),
        "route_shape": route.get("route_shape"),
        "validation_status": validation_status,
        "work_classification": _classification(route["route_id"]),
        "route_inside_ratio": route.get("route_inside_ratio"),
        "ordered_node_count": len(node_names),
        "ordered_node_names": node_names,
        "placeholder_node_names": placeholder_names,
        "geometry_sha256": _geometry_hash(route),
        "geometry_coordinate_system": "GCJ-02",
        "gate_status": gate.get("status"),
        "gate_failure_codes": [item.get("code") for item in gate.get("failures", [])],
        "gate_metrics": gate.get("metrics", {}),
        "visual_audit_status": "pending",
        "visual_issue_codes": [],
        "raw_response_paths": route.get("raw_response_paths", []),
        "geometry_source": route.get("geometry_source"),
        "network_source": route.get("network_source"),
        "poi_audit": _poi_summary(route),
    }


def _load_quality_gate():
    spec = importlib.util.spec_from_file_location(
        "bike_baseline_quality_gate", QUALITY_GATE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"quality gate unavailable: {QUALITY_GATE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_baseline() -> dict[str, Any]:
    candidates = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    bikes = [route for route in candidates if route.get("route_mode") == "bike"]
    if len(bikes) != 30:
        raise RuntimeError(f"expected 30 bike routes, got {len(bikes)}")

    validation_report = json.loads(VALIDATION_REPORT_PATH.read_text(encoding="utf-8"))
    validation_by_id = {
        item["route_id"]: item["validation_status"]
        for item in validation_report.get("routes", [])
    }
    gate = _load_quality_gate()
    records = [
        build_record(
            route,
            gate.audit_route(route, index),
            validation_by_id.get(
                route["route_id"], route.get("validation_status", "pending")
            ),
        )
        for index, route in enumerate(bikes)
    ]
    return {
        "metadata": {
            "route_mode": "bike",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_source": CANDIDATE_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "validation_source": VALIDATION_REPORT_PATH.relative_to(
                PROJECT_ROOT
            ).as_posix(),
            "geometry_coordinate_system": "GCJ-02",
            "visual_audit_contract": "one full-route view per route; street-scale view for flagged segments",
        },
        "summary": {
            "route_count": len(records),
            "distance_band_counts": dict(
                Counter(item["distance_band"] for item in records)
            ),
            "shape_counts": dict(Counter(item["route_shape"] for item in records)),
            "validation_status_counts": dict(
                Counter(item["validation_status"] for item in records)
            ),
            "gate_status_counts": dict(
                Counter(item["gate_status"] for item in records)
            ),
            "work_classification_counts": dict(
                Counter(item["work_classification"] for item in records)
            ),
            "route_inside_ratio_missing_count": sum(
                item["route_inside_ratio"] is None for item in records
            ),
            "placeholder_node_count": sum(
                len(item["placeholder_node_names"]) for item in records
            ),
        },
        "routes": records,
    }


def main() -> None:
    payload = build_baseline()
    temporary = OUTPUT_PATH.with_name(f".{OUTPUT_PATH.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, OUTPUT_PATH)
    summary = payload["summary"]
    print(
        "bike baseline written: "
        f"routes={summary['route_count']} gate={summary['gate_status_counts']} "
        f"bands={summary['distance_band_counts']}"
    )


if __name__ == "__main__":
    main()
