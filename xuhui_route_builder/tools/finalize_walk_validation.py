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
GATE_REPORT_PATH = PROJECT_ROOT / "data/processed/walk_quality_gate_20260819.json"
VALIDATION_REPORT_PATH = PROJECT_ROOT / "data/processed/route_validation_report.json"
NETWORK_VERSION = "amap_walking_20260819+local_topology+visual_audit_20260819"


def _assert_walk_gate_passed() -> None:
    report = json.loads(GATE_REPORT_PATH.read_text(encoding="utf-8"))
    results = [
        item for item in report["results"] if item["route_id"].startswith("XH_WALK_")
    ]
    failed = [item["route_id"] for item in results if item["status"] != "pass"]
    if len(results) != 30 or failed:
        raise RuntimeError(
            f"walk gate is incomplete or failed: count={len(results)} failed={failed}"
        )


def _write_json(path: Path, payload: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_validation_report(routes: list[CandidateRoute]) -> None:
    mode_counts, distance_band_counts = _route_distribution(routes)
    accepted = [route for route in routes if route.validation_status == "accepted"]
    network_versions = list(
        dict.fromkeys(route.network_source for route in routes if route.network_source)
    )
    report = {
        "batch_status": "partial",
        "accepted_count": len(accepted),
        "review_count": sum(
            route.validation_status == "needs_review" for route in routes
        ),
        "rejected_count": sum(
            route.validation_status == "rejected" for route in routes
        ),
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
    temporary = VALIDATION_REPORT_PATH.with_name(f".{VALIDATION_REPORT_PATH.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, VALIDATION_REPORT_PATH)


def main() -> None:
    _assert_walk_gate_passed()
    boundary_polygons = _load_boundary_polygons(BOUNDARY_PATH)
    payload = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    verified_at = datetime(2026, 8, 19, tzinfo=timezone.utc)
    finalized: list[dict[str, Any]] = []
    accepted_walk_ids: list[str] = []
    for item in payload:
        route = CandidateRoute.model_validate(item)
        if route.route_mode != "walk":
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
                f"walk validation failed: {checked.route_id}: {checked.review_note}"
            )
        accepted_walk_ids.append(checked.route_id)
        finalized.append(checked.model_dump(mode="json"))
    if len(accepted_walk_ids) != 30:
        raise RuntimeError(f"expected 30 accepted walks, got {len(accepted_walk_ids)}")
    _write_json(CANDIDATE_PATH, finalized)
    accepted_walks = {
        item["route_id"]: item for item in finalized if item["route_mode"] == "walk"
    }
    published = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
    published = [accepted_walks.get(item["route_id"], item) for item in published]
    if (
        len(published) != 90
        or sum(
            item["route_mode"] == "walk" and item["validation_status"] == "accepted"
            for item in published
        )
        != 30
    ):
        raise RuntimeError("processed catalog does not contain 30 accepted walks")
    _write_json(PROCESSED_PATH, published)
    _write_validation_report(
        [CandidateRoute.model_validate(item) for item in published]
    )
    print("walk validation finalized: 30 accepted")


if __name__ == "__main__":
    main()
