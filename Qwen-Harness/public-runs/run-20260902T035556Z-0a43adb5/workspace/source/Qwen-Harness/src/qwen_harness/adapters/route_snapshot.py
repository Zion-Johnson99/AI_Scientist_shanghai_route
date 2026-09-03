"""Route module adapter: snapshot, validate, and hash route data files."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


EXPECTED_TOTAL = 90
EXPECTED_MODES = {"walk": 30, "run": 30, "bike": 30}
REQUIRED_CATALOG_FIELDS = [
    "route_id",
    "route_name",
    "route_mode",
    "validation_status",
    "geometry_status",
]


@dataclass
class CommandAudit:
    """Audit record for a single adapter operation."""

    operation_id: str
    status: str
    detail: str = ""


@dataclass
class RouteModuleResult:
    """Structured result from route snapshot and validation."""

    status: str  # "ok" | "error" | "partial"
    total: int = 0
    mode_distribution: dict[str, int] = field(default_factory=dict)
    validation_status_distribution: dict[str, int] = field(default_factory=dict)
    catalog_route_ids: list[str] = field(default_factory=list)
    geojson_route_ids: list[str] = field(default_factory=list)
    id_consistency: bool = False
    file_hashes: dict[str, str] = field(default_factory=dict)
    snapshot_paths: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    command_audits: list[CommandAudit] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Any:
    """Load and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_route_catalog(catalog: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Validate route catalog structure.

    Returns (warnings, blockers).
    """
    warnings: list[str] = []
    blockers: list[str] = []

    if not isinstance(catalog, list):
        blockers.append("route_catalog.json top-level is not an array")
        return warnings, blockers

    if len(catalog) != EXPECTED_TOTAL:
        blockers.append(
            f"Expected {EXPECTED_TOTAL} routes, found {len(catalog)}"
        )

    mode_counts: dict[str, int] = {}
    route_ids: set[str] = set()
    duplicate_ids: list[str] = []

    for i, item in enumerate(catalog):
        if not isinstance(item, dict):
            blockers.append(f"Item at index {i} is not an object")
            continue

        for fld in REQUIRED_CATALOG_FIELDS:
            if fld not in item:
                blockers.append(f"Item at index {i} missing field '{fld}'")

        rid = item.get("route_id", "")
        if rid in route_ids:
            duplicate_ids.append(rid)
        route_ids.add(rid)

        mode = item.get("route_mode", "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

        vs = item.get("validation_status", "")
        if vs != "accepted":
            warnings.append(
                f"Route {rid} has validation_status='{vs}' (expected 'accepted')"
            )

    if duplicate_ids:
        blockers.append(f"Duplicate route_ids: {duplicate_ids}")

    for mode, expected in EXPECTED_MODES.items():
        actual = mode_counts.get(mode, 0)
        if actual != expected:
            blockers.append(
                f"Mode '{mode}': expected {expected}, found {actual}"
            )

    return warnings, blockers


def validate_geojson(geojson: dict[str, Any], catalog_ids: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Validate GeoJSON structure.

    Returns (warnings, blockers, geojson_route_ids).
    """
    warnings: list[str] = []
    blockers: list[str] = []
    geojson_ids: list[str] = []

    if geojson.get("type") != "FeatureCollection":
        blockers.append("GeoJSON top-level type is not 'FeatureCollection'")
        return warnings, blockers, geojson_ids

    features = geojson.get("features", [])
    if len(features) != EXPECTED_TOTAL:
        blockers.append(
            f"Expected {EXPECTED_TOTAL} features, found {len(features)}"
        )

    for i, feat in enumerate(features):
        if not isinstance(feat, dict):
            blockers.append(f"Feature at index {i} is not an object")
            continue

        props = feat.get("properties", {})
        rid = props.get("route_id", "")
        geojson_ids.append(rid)

        if rid not in catalog_ids:
            blockers.append(
                f"Feature at index {i} has route_id '{rid}' not in catalog"
            )

        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            warnings.append(
                f"Feature at index {i} (route_id={rid}) geometry type is "
                f"'{geom.get('type')}' (expected 'LineString')"
            )

    return warnings, blockers, geojson_ids


def snapshot_route_data(
    data_dir: Path,
    run_output_dir: Path | None = None,
) -> RouteModuleResult:
    """Read, validate, hash, and optionally snapshot route data files.

    Args:
        data_dir: Directory containing route_catalog.json and xuhui_routes.geojson.
        run_output_dir: If provided, copy data files here and record paths.

    Returns:
        RouteModuleResult with validation results, hashes, and audits.
    """
    result = RouteModuleResult(status="ok")
    catalog_path = data_dir / "route_catalog.json"
    geojson_path = data_dir / "xuhui_routes.geojson"

    # --- Check file existence ---
    missing: list[str] = []
    if not catalog_path.exists():
        missing.append(str(catalog_path))
    if not geojson_path.exists():
        missing.append(str(geojson_path))

    if missing:
        result.status = "error"
        result.blockers.append(f"Missing data files: {missing}")
        result.command_audits.append(
            CommandAudit(
                operation_id="route_snapshot",
                status="error",
                detail=f"Missing files: {missing}",
            )
        )
        return result

    # --- Load and parse ---
    try:
        catalog = _load_json(catalog_path)
    except (json.JSONDecodeError, OSError) as exc:
        result.status = "error"
        result.blockers.append(f"Failed to parse route_catalog.json: {exc}")
        result.command_audits.append(
            CommandAudit(
                operation_id="route_snapshot",
                status="error",
                detail=f"Parse error: {exc}",
            )
        )
        return result

    try:
        geojson = _load_json(geojson_path)
    except (json.JSONDecodeError, OSError) as exc:
        result.status = "error"
        result.blockers.append(f"Failed to parse xuhui_routes.geojson: {exc}")
        result.command_audits.append(
            CommandAudit(
                operation_id="route_snapshot",
                status="error",
                detail=f"Parse error: {exc}",
            )
        )
        return result

    # --- Validate catalog ---
    cat_warnings, cat_blockers = validate_route_catalog(catalog)
    result.warnings.extend(cat_warnings)
    result.blockers.extend(cat_blockers)

    # --- Extract catalog info ---
    if isinstance(catalog, list):
        result.total = len(catalog)
        result.catalog_route_ids = [
            item.get("route_id", "") for item in catalog if isinstance(item, dict)
        ]
        for item in catalog:
            if isinstance(item, dict):
                mode = item.get("route_mode", "unknown")
                result.mode_distribution[mode] = (
                    result.mode_distribution.get(mode, 0) + 1
                )
                vs = item.get("validation_status", "unknown")
                result.validation_status_distribution[vs] = (
                    result.validation_status_distribution.get(vs, 0) + 1
                )

    # --- Validate GeoJSON ---
    catalog_id_set = set(result.catalog_route_ids)
    geo_warnings, geo_blockers, geojson_ids = validate_geojson(geojson, catalog_id_set)
    result.warnings.extend(geo_warnings)
    result.blockers.extend(geo_blockers)
    result.geojson_route_ids = geojson_ids

    # --- ID consistency ---
    result.id_consistency = set(geojson_ids) == catalog_id_set

    # --- Compute hashes ---
    result.file_hashes["route_catalog.json"] = _sha256_file(catalog_path)
    result.file_hashes["xuhui_routes.geojson"] = _sha256_file(geojson_path)

    # --- Snapshot to run directory ---
    if run_output_dir is not None:
        run_output_dir.mkdir(parents=True, exist_ok=True)
        for src_path in [catalog_path, geojson_path]:
            dest = run_output_dir / src_path.name
            shutil.copy2(src_path, dest)
            result.snapshot_paths[src_path.name] = str(dest)

    # --- Determine final status ---
    if result.blockers:
        result.status = "error"
    elif result.warnings:
        result.status = "partial"

    result.command_audits.append(
        CommandAudit(
            operation_id="route_snapshot",
            status=result.status,
            detail=(
                f"total={result.total}, "
                f"modes={result.mode_distribution}, "
                f"id_consistent={result.id_consistency}"
            ),
        )
    )

    return result
