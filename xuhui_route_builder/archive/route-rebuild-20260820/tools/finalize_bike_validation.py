from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xuhui_route_builder.cli import _load_boundary_polygons, _route_distribution
from xuhui_route_builder.models import CandidateRoute
from xuhui_route_builder.validation import (
    find_duplicate_routes,
    validate_amap_raw_evidence,
    validate_candidate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = PROJECT_ROOT / "data/interim/pilot_candidates.json"
PROCESSED_PATH = PROJECT_ROOT / "data/processed/pilot_validated.json"
BOUNDARY_PATH = PROJECT_ROOT / "data/web/xuhui_boundary.geojson"
GATE_REPORT_PATH = PROJECT_ROOT / "data/processed/bike_quality_gate_20260820.json"
VISUAL_MANIFEST_PATH = PROJECT_ROOT / "data/processed/bike_visual_audit_20260820.json"
VALIDATION_REPORT_PATH = PROJECT_ROOT / "data/processed/route_validation_report.json"
NETWORK_VERSION = "amap_riding_20260820+local_topology+visual_audit_20260820"


def assert_bike_gate(report: dict[str, Any], expected_ids: set[str]) -> None:
    results = [
        item
        for item in report.get("results", [])
        if item.get("route_id") in expected_ids
    ]
    passed_ids = {item["route_id"] for item in results if item.get("status") == "pass"}
    if len(results) != 30 or passed_ids != expected_ids:
        missing = sorted(expected_ids - passed_ids)
        raise RuntimeError(
            f"bike gate incomplete: count={len(results)} missing_or_failed={missing}"
        )


def assert_visual_manifest(manifest: dict[str, Any], expected_ids: set[str]) -> None:
    records = [
        item
        for item in manifest.get("routes", [])
        if item.get("route_id") in expected_ids
    ]
    passed_ids = {
        item["route_id"]
        for item in records
        if item.get("status") == "pass" and item.get("image_path")
    }
    if len(records) != 30 or passed_ids != expected_ids:
        missing = sorted(expected_ids - passed_ids)
        raise RuntimeError(
            f"visual audit incomplete: count={len(records)} missing_or_failed={missing}"
        )


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _write_validation_report(routes: list[CandidateRoute]) -> None:
    mode_counts, distance_band_counts = _route_distribution(routes)
    accepted = [route for route in routes if route.validation_status == "accepted"]
    review_count = sum(route.validation_status == "needs_review" for route in routes)
    rejected_count = sum(route.validation_status == "rejected" for route in routes)
    network_versions = list(
        dict.fromkeys(route.network_source for route in routes if route.network_source)
    )
    report = {
        "batch_status": (
            "accepted"
            if len(accepted) == len(routes) and review_count == 0 and rejected_count == 0
            else "partial"
        ),
        "accepted_count": len(accepted),
        "review_count": review_count,
        "rejected_count": rejected_count,
        "published_count": sum(route.is_publishable() for route in routes),
        "displayed_count": len(routes),
        "mode_counts": mode_counts,
        "distance_band_counts": distance_band_counts,
        "network_version": network_versions,
        "duplicate_groups": find_duplicate_routes(accepted),
        "routes": [
            {
                "route_id": route.route_id,
                "mode": route.route_mode,
                "validation_status": route.validation_status,
                "snap_ratio": route.snap_ratio,
                "route_inside_ratio": route.route_inside_ratio,
                "source_accessed_at": route.source_accessed_at.isoformat()
                if route.source_accessed_at
                else None,
                "network_source": route.network_source,
                "review_note": route.review_note,
            }
            for route in routes
        ],
        "failures": [],
    }
    _write_json(VALIDATION_REPORT_PATH, report)


def _assert_visual_files(manifest: dict[str, Any]) -> None:
    missing = [
        item["route_id"]
        for item in manifest["routes"]
        if not (PROJECT_ROOT / item["image_path"]).is_file()
    ]
    if missing:
        raise RuntimeError(f"visual audit images missing: {missing}")


def main() -> None:
    payload = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    bike_ids = {item["route_id"] for item in payload if item.get("route_mode") == "bike"}
    if len(bike_ids) != 30:
        raise RuntimeError(f"expected 30 bike routes, got {len(bike_ids)}")

    gate_report = json.loads(GATE_REPORT_PATH.read_text(encoding="utf-8"))
    visual_manifest = json.loads(VISUAL_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert_bike_gate(gate_report, bike_ids)
    assert_visual_manifest(visual_manifest, bike_ids)
    _assert_visual_files(visual_manifest)

    boundary_polygons = _load_boundary_polygons(BOUNDARY_PATH)
    verified_at = datetime(2026, 8, 20, tzinfo=timezone.utc)
    finalized: list[dict[str, Any]] = []
    accepted_bike_ids: list[str] = []
    for item in payload:
        route = CandidateRoute.model_validate(item)
        if route.route_mode != "bike":
            finalized.append(route.model_dump(mode="json"))
            continue
        evidence_failures = (
            validate_amap_raw_evidence(route, PROJECT_ROOT)
            if route.geometry_source == "amap_direction"
            else []
        )
        checked = validate_candidate(
            route,
            None,
            verified_at,
            NETWORK_VERSION,
            evidence_failures,
            boundary_polygons,
        )
        if checked.validation_status != "accepted":
            raise RuntimeError(
                f"bike validation failed: {checked.route_id}: {checked.review_note}"
            )
        accepted_bike_ids.append(checked.route_id)
        finalized.append(checked.model_dump(mode="json"))
    if len(accepted_bike_ids) != 30:
        raise RuntimeError(f"expected 30 accepted bikes, got {len(accepted_bike_ids)}")

    _write_json(CANDIDATE_PATH, finalized)
    accepted_bikes = {
        item["route_id"]: item for item in finalized if item["route_mode"] == "bike"
    }
    published = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
    published = [accepted_bikes.get(item["route_id"], item) for item in published]
    if (
        len(published) != 90
        or sum(
            item["route_mode"] == "bike" and item["validation_status"] == "accepted"
            for item in published
        )
        != 30
    ):
        raise RuntimeError("processed catalog does not contain 30 accepted bikes")
    _write_json(PROCESSED_PATH, published)
    _write_validation_report([CandidateRoute.model_validate(item) for item in published])
    print("bike validation finalized: 30 accepted")


if __name__ == "__main__":
    main()
