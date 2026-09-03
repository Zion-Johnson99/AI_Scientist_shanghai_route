"""Route module adapter for Qwen-Harness.

Performs pre-flight checks on route data files, validates the 90-route
contract (walk/run/bike × 30), verifies route_id consistency between
catalog and GeoJSON, and snapshots stable artifacts into the run directory
with SHA256 hashes and Git HEAD.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_TOTAL_ROUTES = 90
EXPECTED_MODE_COUNT = 30
EXPECTED_MODES = {"walk", "run", "bike"}
REQUIRED_CATALOG_FIELDS = {
    "route_id",
    "route_name",
    "route_mode",
    "validation_status",
    "geometry_status",
}

# Default data directory relative to repository root
DEFAULT_DATA_DIR = Path("xuhui_route_builder/data/web")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class RouteModuleResult:
    """Structured result from route adapter operations."""

    status: str  # "ok" | "error" | "partial"
    total_routes: int = 0
    mode_distribution: dict[str, int] = field(default_factory=dict)
    validation_status_distribution: dict[str, int] = field(default_factory=dict)
    catalog_geojson_id_consistent: bool = False
    data_hashes: dict[str, str] = field(default_factory=dict)
    git_head: str = ""
    snapshot_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_routes": self.total_routes,
            "mode_distribution": self.mode_distribution,
            "validation_status_distribution": self.validation_status_distribution,
            "catalog_geojson_id_consistent": self.catalog_geojson_id_consistent,
            "data_hashes": self.data_hashes,
            "git_head": self.git_head,
            "snapshot_paths": self.snapshot_paths,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "missing_items": self.missing_items,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _get_git_head(repo_root: Path) -> str:
    """Get current Git HEAD commit hash. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def _get_git_branch(repo_root: Path) -> str:
    """Get current Git branch name. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def preflight_check(
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> RouteModuleResult:
    """Run pre-flight checks on route data files.

    Checks:
    1. Required files exist and are parseable JSON.
    2. route_catalog.json has exactly 90 entries.
    3. Mode distribution is walk/run/bike × 30.
    4. route_id is unique within catalog.
    5. route_id set in catalog matches GeoJSON features.
    6. All entries have required fields.
    7. All validation_status == 'accepted'.

    Returns a RouteModuleResult with status='ok' if all checks pass,
    or status='error' with missing_items/blockers listing failures.
    """
    if repo_root is None:
        repo_root = Path.cwd()
    if data_dir is None:
        data_dir = repo_root / DEFAULT_DATA_DIR

    result = RouteModuleResult(status="ok")

    # --- File existence ---
    catalog_path = data_dir / "route_catalog.json"
    geojson_path = data_dir / "xuhui_routes.geojson"

    missing_files: list[str] = []
    if not catalog_path.exists():
        missing_files.append(str(catalog_path))
    if not geojson_path.exists():
        missing_files.append(str(geojson_path))

    if missing_files:
        result.status = "error"
        result.missing_items = missing_files
        result.blockers.append(
            f"Required data files missing: {', '.join(missing_files)}"
        )
        return result

    # --- Parse catalog ---
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog: list[dict[str, Any]] = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        result.status = "error"
        result.blockers.append(f"route_catalog.json not parseable: {exc}")
        return result

    if not isinstance(catalog, list):
        result.status = "error"
        result.blockers.append("route_catalog.json top-level is not an array")
        return result

    # --- Parse GeoJSON ---
    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            geojson: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        result.status = "error"
        result.blockers.append(f"xuhui_routes.geojson not parseable: {exc}")
        return result

    if geojson.get("type") != "FeatureCollection":
        result.status = "error"
        result.blockers.append("xuhui_routes.geojson type is not FeatureCollection")
        return result

    features: list[dict[str, Any]] = geojson.get("features", [])

    # --- Route count ---
    result.total_routes = len(catalog)
    if len(catalog) != EXPECTED_TOTAL_ROUTES:
        result.blockers.append(
            f"Expected {EXPECTED_TOTAL_ROUTES} routes in catalog, got {len(catalog)}"
        )

    if len(features) != EXPECTED_TOTAL_ROUTES:
        result.blockers.append(
            f"Expected {EXPECTED_TOTAL_ROUTES} features in GeoJSON, got {len(features)}"
        )

    # --- Mode distribution ---
    mode_counts: dict[str, int] = {}
    for entry in catalog:
        mode = entry.get("route_mode", "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    result.mode_distribution = mode_counts

    for mode in EXPECTED_MODES:
        count = mode_counts.get(mode, 0)
        if count != EXPECTED_MODE_COUNT:
            result.blockers.append(
                f"Mode '{mode}' has {count} routes, expected {EXPECTED_MODE_COUNT}"
            )

    unexpected_modes = set(mode_counts.keys()) - EXPECTED_MODES
    if unexpected_modes:
        result.blockers.append(
            f"Unexpected modes found: {', '.join(sorted(unexpected_modes))}"
        )

    # --- Required fields ---
    for i, entry in enumerate(catalog):
        missing_fields = REQUIRED_CATALOG_FIELDS - set(entry.keys())
        if missing_fields:
            result.blockers.append(
                f"Catalog entry {i} (route_id={entry.get('route_id', '?')}) "
                f"missing fields: {', '.join(sorted(missing_fields))}"
            )

    # --- route_id uniqueness ---
    catalog_ids = [entry.get("route_id") for entry in catalog]
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for rid in catalog_ids:
        if rid is None:
            result.blockers.append("Catalog entry with missing route_id found")
            continue
        if rid in seen_ids:
            duplicates.append(str(rid))
        seen_ids.add(str(rid))
    if duplicates:
        result.blockers.append(
            f"Duplicate route_ids in catalog: {', '.join(sorted(set(duplicates)))}"
        )

    # --- GeoJSON route_id consistency ---
    geojson_ids: set[str] = set()
    for feat in features:
        props = feat.get("properties", {})
        rid = props.get("route_id")
        if rid is not None:
            geojson_ids.add(str(rid))

    catalog_id_set = {str(rid) for rid in catalog_ids if rid is not None}
    result.catalog_geojson_id_consistent = catalog_id_set == geojson_ids

    if not result.catalog_geojson_id_consistent:
        only_catalog = catalog_id_set - geojson_ids
        only_geojson = geojson_ids - catalog_id_set
        if only_catalog:
            result.blockers.append(
                f"route_ids in catalog but not in GeoJSON: "
                f"{', '.join(sorted(only_catalog))}"
            )
        if only_geojson:
            result.blockers.append(
                f"route_ids in GeoJSON but not in catalog: "
                f"{', '.join(sorted(only_geojson))}"
            )

    # --- validation_status distribution ---
    vs_counts: dict[str, int] = {}
    for entry in catalog:
        vs = entry.get("validation_status", "unknown")
        vs_counts[vs] = vs_counts.get(vs, 0) + 1
    result.validation_status_distribution = vs_counts

    non_accepted = [
        entry.get("route_id", "?")
        for entry in catalog
        if entry.get("validation_status") != "accepted"
    ]
    if non_accepted:
        result.warnings.append(
            f"Routes with validation_status != 'accepted': "
            f"{', '.join(str(r) for r in non_accepted[:10])}"
            + ("..." if len(non_accepted) > 10 else "")
        )

    # --- Final status ---
    if result.blockers:
        result.status = "error"

    return result


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def snapshot_routes(
    run_dir: Path,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> RouteModuleResult:
    """Snapshot stable route artifacts into the run directory.

    Copies route_catalog.json and xuhui_routes.geojson into
    <run_dir>/modules/route/ and records SHA256 hashes and Git HEAD.

    Returns a RouteModuleResult with snapshot_paths and data_hashes populated.
    """
    if repo_root is None:
        repo_root = Path.cwd()
    if data_dir is None:
        data_dir = repo_root / DEFAULT_DATA_DIR

    result = RouteModuleResult(status="ok")

    # Pre-flight first
    pf = preflight_check(data_dir=data_dir, repo_root=repo_root)
    if pf.status == "error":
        return pf

    # Prepare snapshot directory
    snapshot_dir = run_dir / "modules" / "route"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Files to snapshot
    files_to_snapshot = [
        "route_catalog.json",
        "xuhui_routes.geojson",
    ]

    # Optional files (snapshot if present, warn if not)
    optional_files = [
        "xuhui_entries.geojson",
        "poi_catalog.json",
        "access_cases.json",
    ]

    data_hashes: dict[str, str] = {}
    snapshot_paths: list[str] = []

    for filename in files_to_snapshot:
        src = data_dir / filename
        if not src.exists():
            result.status = "error"
            result.missing_items.append(str(src))
            result.blockers.append(f"Required file missing for snapshot: {src}")
            return result

        dst = snapshot_dir / filename
        shutil.copy2(src, dst)
        sha = _sha256_file(dst)
        data_hashes[filename] = sha
        snapshot_paths.append(str(dst))

    for filename in optional_files:
        src = data_dir / filename
        if src.exists():
            dst = snapshot_dir / filename
            shutil.copy2(src, dst)
            sha = _sha256_file(dst)
            data_hashes[filename] = sha
            snapshot_paths.append(str(dst))
        else:
            result.warnings.append(f"Optional file not found, skipped: {src}")

    # Git info
    result.git_head = _get_git_head(repo_root)
    if not result.git_head:
        result.warnings.append("Could not determine Git HEAD; recorded as empty")

    result.data_hashes = data_hashes
    result.snapshot_paths = snapshot_paths
    result.total_routes = pf.total_routes
    result.mode_distribution = pf.mode_distribution
    result.validation_status_distribution = pf.validation_status_distribution
    result.catalog_geojson_id_consistent = pf.catalog_geojson_id_consistent
    result.warnings.extend(pf.warnings)
    result.blockers.extend(pf.blockers)

    if result.blockers:
        result.status = "error"

    return result


# ---------------------------------------------------------------------------
# Write result to run directory
# ---------------------------------------------------------------------------


def write_result(result: RouteModuleResult, run_dir: Path) -> Path:
    """Write RouteModuleResult to modules/route/result.json in the run dir."""
    output_dir = run_dir / "modules" / "route"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "result.json"

    payload = result.to_dict()

    # Atomic write: temp file -> flush -> fsync -> os.replace
    tmp_path = output_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(output_path))

    return output_path
