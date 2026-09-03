"""Environment module adapter for Qwen-Harness.

Pre-checks environment_dashboard.json structure, 90-route coverage,
and field completeness. Snapshots the file with SHA256 hash.
Marks partial when required top-level keys or route items are missing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL_KEYS = ("metadata", "current", "forecast", "routes")
REQUIRED_ROUTE_FIELDS = ("route_id", "pm2_5", "noise", "pollen_daily")
EXPECTED_ROUTE_COUNT = 90


@dataclass
class EnvironmentAdapterResult:
    """Result of environment adapter pre-check and snapshot."""

    status: str  # "ok" | "partial" | "error"
    dashboard_path: str = ""
    missing_top_level_keys: list[str] = field(default_factory=list)
    missing_route_ids: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    route_count: int = 0
    sha256: str = ""
    snapshot_path: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def precheck_dashboard(dashboard_path: Path) -> EnvironmentAdapterResult:
    """Pre-check environment_dashboard.json structure and coverage.

    Returns a result with status:
    - "ok": all checks pass
    - "partial": some keys or routes missing but file is parseable
    - "error": file missing or unparseable
    """
    result = EnvironmentAdapterResult(status="error", dashboard_path=str(dashboard_path))

    if not dashboard_path.exists():
        result.errors.append(f"Dashboard file not found: {dashboard_path}")
        return result

    try:
        with open(dashboard_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        result.errors.append(f"Failed to parse dashboard JSON: {exc}")
        return result

    if not isinstance(data, dict):
        result.errors.append("Dashboard root is not a JSON object")
        return result

    # Check top-level keys
    missing_keys = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing_keys:
        result.missing_top_level_keys = missing_keys
        result.warnings.append(
            f"Missing top-level keys: {', '.join(missing_keys)}"
        )

    # Check routes section
    routes_section = data.get("routes")
    if routes_section is None:
        result.status = "partial"
        result.warnings.append("No 'routes' section; cannot verify route coverage")
        return result

    if not isinstance(routes_section, dict):
        result.status = "partial"
        result.warnings.append("'routes' section is not an object")
        return result

    items = routes_section.get("items")
    if items is None:
        result.status = "partial"
        result.warnings.append("'routes.items' is missing")
        return result

    if not isinstance(items, list):
        result.status = "partial"
        result.warnings.append("'routes.items' is not a list")
        return result

    result.route_count = len(items)

    # Check each route item for required fields
    seen_route_ids: set[str] = set()
    missing_route_ids: list[str] = []
    missing_fields_set: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        route_id = item.get("route_id")
        if route_id is not None:
            seen_route_ids.add(str(route_id))
        for fld in REQUIRED_ROUTE_FIELDS:
            if fld not in item:
                missing_fields_set.add(fld)

    if missing_fields_set:
        result.missing_fields = sorted(missing_fields_set)
        result.warnings.append(
            f"Missing fields in route items: {', '.join(sorted(missing_fields_set))}"
        )

    # Check coverage against expected 90 route IDs
    # We expect route IDs in format: W01-W30, R01-R30, B01-B30
    expected_ids = set()
    for i in range(1, 31):
        expected_ids.add(f"W{i:02d}")
        expected_ids.add(f"R{i:02d}")
        expected_ids.add(f"B{i:02d}")

    missing_ids = sorted(expected_ids - seen_route_ids)
    if missing_ids:
        result.missing_route_ids = missing_ids
        result.warnings.append(
            f"Missing {len(missing_ids)} route_id(s) in dashboard: "
            f"{', '.join(missing_ids[:10])}{'...' if len(missing_ids) > 10 else ''}"
        )

    # Determine final status
    if result.missing_top_level_keys or result.missing_route_ids or result.missing_fields:
        result.status = "partial"
    elif result.route_count < EXPECTED_ROUTE_COUNT:
        result.status = "partial"
        result.warnings.append(
            f"Route count {result.route_count} < expected {EXPECTED_ROUTE_COUNT}"
        )
    else:
        result.status = "ok"

    return result


def snapshot_dashboard(
    dashboard_path: Path,
    run_output_dir: Path,
) -> EnvironmentAdapterResult:
    """Snapshot environment_dashboard.json into the run output directory.

    Records SHA256 hash. Returns result with snapshot_path and sha256 set.
    If pre-check fails with error status, snapshot is skipped.
    """
    result = precheck_dashboard(dashboard_path)

    if result.status == "error":
        return result

    # Compute hash
    result.sha256 = compute_sha256(dashboard_path)

    # Create snapshot directory
    snapshot_dir = run_output_dir / "modules" / "environment"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    snapshot_file = snapshot_dir / "environment_dashboard.json"
    shutil.copy2(dashboard_path, snapshot_file)
    result.snapshot_path = str(snapshot_file)

    # Write hash record
    hash_record = {
        "file": "environment_dashboard.json",
        "sha256": result.sha256,
        "source_path": str(dashboard_path),
        "route_count": result.route_count,
        "status": result.status,
    }
    hash_file = snapshot_dir / "snapshot_hash.json"
    with open(hash_file, "w", encoding="utf-8") as f:
        json.dump(hash_record, f, indent=2, ensure_ascii=False)

    return result


def run_environment_adapter(
    dashboard_path: Path,
    run_output_dir: Path,
) -> dict[str, Any]:
    """Main entry point for the environment adapter.

    Performs pre-check and snapshot, returns a serializable result dict
    suitable for writing to modules/environment/result.json.
    """
    result = snapshot_dashboard(dashboard_path, run_output_dir)

    output: dict[str, Any] = {
        "status": result.status,
        "dashboard_path": result.dashboard_path,
        "route_count": result.route_count,
        "sha256": result.sha256,
        "snapshot_path": result.snapshot_path,
        "missing_top_level_keys": result.missing_top_level_keys,
        "missing_route_ids": result.missing_route_ids,
        "missing_fields": result.missing_fields,
        "warnings": result.warnings,
        "errors": result.errors,
    }

    # Write result.json
    result_dir = run_output_dir / "modules" / "environment"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "result.json"

    # Atomic write: temp file -> flush -> fsync -> os.replace
    tmp_file = result_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.flush()
        import os
        os.fsync(f.fileno())
    import os
    os.replace(str(tmp_file), str(result_file))

    return output
