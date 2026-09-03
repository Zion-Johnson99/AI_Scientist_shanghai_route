"""Environment module adapter: read, validate, hash and snapshot environment_dashboard.json."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL_KEYS = frozenset({"metadata", "current", "forecast", "routes"})
REQUIRED_ROUTE_FIELDS = frozenset({"route_id", "pm2_5", "noise", "pollen_daily"})
SEMANTIC_FIELDS = frozenset({"unit", "estimated", "status"})
EXPECTED_ROUTE_COUNT = 90


@dataclass
class EnvironmentSnapshotResult:
    """Result of environment snapshot operation."""

    status: str  # "ok" | "partial" | "error"
    route_count: int = 0
    missing_fields: list[str] = field(default_factory=list)
    missing_routes: list[str] = field(default_factory=list)
    sha256: str = ""
    source_path: str = ""
    snapshot_path: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def validate_dashboard(data: dict[str, Any]) -> EnvironmentSnapshotResult:
    """Validate environment_dashboard.json structure and content.

    Returns an EnvironmentSnapshotResult with status:
    - "ok": all checks pass
    - "partial": some semantic fields missing but core data present
    - "error": critical structure missing
    """
    result = EnvironmentSnapshotResult(status="ok")

    # Check top-level keys
    missing_top = REQUIRED_TOP_LEVEL_KEYS - set(data.keys())
    if missing_top:
        result.status = "error"
        result.errors.append(f"Missing top-level keys: {sorted(missing_top)}")
        return result

    # Check routes section
    routes_section = data.get("routes", {})
    if not isinstance(routes_section, dict):
        result.status = "error"
        result.errors.append("routes must be an object")
        return result

    items = routes_section.get("items", [])
    if not isinstance(items, list):
        result.status = "error"
        result.errors.append("routes.items must be a list")
        return result

    result.route_count = len(items)

    if result.route_count != EXPECTED_ROUTE_COUNT:
        result.status = "error"
        result.errors.append(
            f"Expected {EXPECTED_ROUTE_COUNT} route items, got {result.route_count}"
        )
        return result

    # Check each route item
    seen_route_ids: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            result.status = "error"
            result.errors.append(f"routes.items[{idx}] is not an object")
            return result

        route_id = item.get("route_id")
        if route_id is None:
            result.status = "error"
            result.errors.append(f"routes.items[{idx}] missing route_id")
            return result

        if route_id in seen_route_ids:
            result.warnings.append(f"Duplicate route_id: {route_id}")
        seen_route_ids.add(route_id)

        # Check required fields
        missing = REQUIRED_ROUTE_FIELDS - set(item.keys())
        if missing:
            result.status = "error"
            result.errors.append(
                f"routes.items[{idx}] (route_id={route_id}) missing required fields: {sorted(missing)}"
            )
            return result

        # Check semantic fields (non-blocking, mark partial)
        missing_semantic = SEMANTIC_FIELDS - set(item.keys())
        if missing_semantic:
            if result.status == "ok":
                result.status = "partial"
            for f in sorted(missing_semantic):
                field_key = f"routes.items[{idx}].{f}"
                if field_key not in result.missing_fields:
                    result.missing_fields.append(field_key)

    return result


def read_environment_snapshot(
    dashboard_path: Path,
    run_dir: Path | None = None,
) -> EnvironmentSnapshotResult:
    """Read and validate environment_dashboard.json, optionally snapshot to run directory.

    Args:
        dashboard_path: Path to environment_dashboard.json.
        run_dir: If provided, copy the file to run_dir/modules/environment/.

    Returns:
        EnvironmentSnapshotResult with validation outcome and hash.
    """
    if not dashboard_path.exists():
        return EnvironmentSnapshotResult(
            status="error",
            source_path=str(dashboard_path),
            errors=[f"File not found: {dashboard_path}"],
        )

    try:
        raw = dashboard_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return EnvironmentSnapshotResult(
            status="error",
            source_path=str(dashboard_path),
            errors=[f"Failed to parse JSON: {exc}"],
        )

    result = validate_dashboard(data)
    result.source_path = str(dashboard_path)
    result.sha256 = compute_sha256(dashboard_path)

    # Snapshot to run directory if requested
    if run_dir is not None and result.status != "error":
        dest_dir = run_dir / "modules" / "environment"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / "environment_dashboard.json"
        shutil.copy2(dashboard_path, dest_path)
        result.snapshot_path = str(dest_path)

    return result
