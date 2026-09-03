"""Data pipeline core: tiered refresh logic, last-known-good fallback, snapshot management."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SnapshotMeta(BaseModel):
    """Metadata for a single snapshot file."""

    filename: str
    path: str
    sha256: str
    generated_at: str
    status: str  # "fresh" | "stale" | "partial" | "error"
    stale_reason: str | None = None


class PipelineResult(BaseModel):
    """Result of a pipeline run."""

    tier: str
    status: str  # "ok" | "partial" | "stale" | "error"
    generated_at: str
    snapshots: list[SnapshotMeta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    stale_reason: str | None = None


class RefreshConfig(BaseModel):
    """Configuration for a refresh operation."""

    tier: str  # "weather" | "hourly" | "daily"
    allow_network: bool = False
    api_keys: dict[str, str] = Field(default_factory=dict)
    exports_dir: str = "runtime/exports"
    max_retries: int = 2
    retry_backoff_base: float = 2.0


# Tier definitions: which data sources each tier refreshes
TIER_SOURCES: dict[str, list[str]] = {
    "weather": ["current_weather", "forecast_24h"],
    "hourly": ["current_weather", "forecast_24h", "aqi_hourly", "pm25_hourly"],
    "daily": ["current_weather", "forecast_24h", "aqi_hourly", "pm25_hourly", "pollen_daily", "noise_daily"],
}

# Snapshot file naming convention
SNAPSHOT_FILES: dict[str, str] = {
    "current_weather": "current_weather.json",
    "forecast_24h": "forecast_24h.json",
    "aqi_hourly": "aqi_hourly.json",
    "pm25_hourly": "pm25_hourly.json",
    "pollen_daily": "pollen_daily.json",
    "noise_daily": "noise_daily.json",
}


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _compute_sha256(filepath: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(filepath: Path, data: Any) -> None:
    """Atomically write JSON data to a file using temp file + fsync + rename."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = filepath.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, filepath)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _find_last_known_good(exports_dir: Path, source_name: str) -> Path | None:
    """Find the most recent valid snapshot file for a given source.

    Looks for the canonical filename first, then any numbered backup.
    Returns None if no valid snapshot exists.
    """
    canonical = exports_dir / SNAPSHOT_FILES.get(source_name, f"{source_name}.json")
    if canonical.exists():
        try:
            with open(canonical, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Validate minimal structure
            if isinstance(data, dict) and "generated_at" in data:
                return canonical
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _load_snapshot(filepath: Path) -> dict[str, Any] | None:
    """Load and validate a snapshot file. Returns None if invalid."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _fetch_source_data(
    source_name: str,
    config: RefreshConfig,
) -> dict[str, Any] | None:
    """Fetch data for a single source from its upstream API.

    Returns None if network is not allowed or fetch fails.
    In production this would call real APIs; here we simulate
    the interface for offline-first design.
    """
    if not config.allow_network:
        return None

    # Check if required API key is available
    required_keys = _get_required_keys(source_name)
    for key_name in required_keys:
        if key_name not in config.api_keys or not config.api_keys[key_name]:
            return None

    # Simulate API call - in production this would use httpx
    # For now, return None to trigger fallback behavior
    # Real implementation would be:
    #   response = httpx.get(url, headers={...}, timeout=30)
    #   return response.json()
    return None


def _get_required_keys(source_name: str) -> list[str]:
    """Return the API key names required for a given source."""
    key_map: dict[str, list[str]] = {
        "current_weather": ["WEATHER_API_KEY"],
        "forecast_24h": ["WEATHER_API_KEY"],
        "aqi_hourly": ["AQI_API_KEY"],
        "pm25_hourly": ["AQI_API_KEY"],
        "pollen_daily": ["POLLEN_API_KEY"],
        "noise_daily": [],  # noise is modeled locally, no API key needed
    }
    return key_map.get(source_name, [])


def _generate_placeholder_snapshot(source_name: str, generated_at: str) -> dict[str, Any]:
    """Generate a minimal placeholder snapshot structure.

    This is used only when no last-known-good exists and we need
    to record that data is unavailable. The status is 'no_data'.
    """
    return {
        "source": source_name,
        "generated_at": generated_at,
        "status": "no_data",
        "data": None,
        "note": "No upstream data available and no last-known-good snapshot exists.",
    }


def refresh_tier(config: RefreshConfig) -> PipelineResult:
    """Execute a tiered refresh operation.

    For each source in the tier:
    1. Attempt to fetch fresh data from upstream.
    2. If fetch fails or network unavailable, fall back to last-known-good.
    3. If no last-known-good exists, mark as no_data.
    4. Write snapshot to exports directory.

    Returns a PipelineResult with status and snapshot metadata.
    """
    exports_dir = Path(config.exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)

    generated_at = _now_iso()
    sources = TIER_SOURCES.get(config.tier, [])

    if not sources:
        return PipelineResult(
            tier=config.tier,
            status="error",
            generated_at=generated_at,
            errors=[f"Unknown tier: {config.tier}"],
        )

    snapshots: list[SnapshotMeta] = []
    warnings: list[str] = []
    errors: list[str] = []
    has_fresh = False
    has_stale = False
    has_error = False

    for source_name in sources:
        snapshot_filename = SNAPSHOT_FILES.get(source_name, f"{source_name}.json")
        snapshot_path = exports_dir / snapshot_filename

        # Step 1: Try to fetch fresh data
        fresh_data = _fetch_source_data(source_name, config)

        if fresh_data is not None:
            # Fresh data available - write it
            fresh_data["generated_at"] = generated_at
            fresh_data["status"] = "fresh"
            fresh_data["source"] = source_name
            _atomic_write_json(snapshot_path, fresh_data)
            has_fresh = True
            snapshots.append(
                SnapshotMeta(
                    filename=snapshot_filename,
                    path=str(snapshot_path),
                    sha256=_compute_sha256(snapshot_path),
                    generated_at=generated_at,
                    status="fresh",
                )
            )
        else:
            # Step 2: Fall back to last-known-good
            lkg_path = _find_last_known_good(exports_dir, source_name)

            if lkg_path is not None:
                # Last-known-good exists - mark as stale
                lkg_data = _load_snapshot(lkg_path)
                if lkg_data is not None:
                    stale_reason = (
                        "Network unavailable" if not config.allow_network
                        else "API key missing or fetch failed"
                    )
                    # Update the snapshot metadata to reflect staleness
                    lkg_data["status"] = "stale"
                    lkg_data["stale_reason"] = stale_reason
                    lkg_data["last_refresh_attempt"] = generated_at
                    _atomic_write_json(snapshot_path, lkg_data)
                    has_stale = True
                    warnings.append(
                        f"Source '{source_name}' using last-known-good snapshot. "
                        f"Reason: {stale_reason}"
                    )
                    snapshots.append(
                        SnapshotMeta(
                            filename=snapshot_filename,
                            path=str(snapshot_path),
                            sha256=_compute_sha256(snapshot_path),
                            generated_at=lkg_data.get("generated_at", generated_at),
                            status="stale",
                            stale_reason=stale_reason,
                        )
                    )
                else:
                    # LKG file exists but is corrupted
                    has_error = True
                    errors.append(
                        f"Source '{source_name}': last-known-good file exists but is corrupted."
                    )
                    no_data = _generate_placeholder_snapshot(source_name, generated_at)
                    _atomic_write_json(snapshot_path, no_data)
                    snapshots.append(
                        SnapshotMeta(
                            filename=snapshot_filename,
                            path=str(snapshot_path),
                            sha256=_compute_sha256(snapshot_path),
                            generated_at=generated_at,
                            status="error",
                            stale_reason="Last-known-good file corrupted",
                        )
                    )
            else:
                # Step 3: No last-known-good available
                has_error = True
                no_data = _generate_placeholder_snapshot(source_name, generated_at)
                _atomic_write_json(snapshot_path, no_data)
                errors.append(
                    f"Source '{source_name}': no upstream data and no last-known-good snapshot."
                )
                snapshots.append(
                    SnapshotMeta(
                        filename=snapshot_filename,
                        path=str(snapshot_path),
                        sha256=_compute_sha256(snapshot_path),
                        generated_at=generated_at,
                        status="error",
                        stale_reason="No data available and no fallback snapshot",
                    )
                )

    # Determine overall status
    if has_error and not has_fresh and not has_stale:
        overall_status = "error"
    elif has_error:
        overall_status = "partial"
    elif has_stale and not has_fresh:
        overall_status = "stale"
    elif has_stale:
        overall_status = "partial"
    else:
        overall_status = "ok"

    stale_reason = None
    if overall_status in ("stale", "partial"):
        stale_reason = "; ".join(warnings) if warnings else "Some sources using fallback"

    return PipelineResult(
        tier=config.tier,
        status=overall_status,
        generated_at=generated_at,
        snapshots=snapshots,
        warnings=warnings,
        errors=errors,
        stale_reason=stale_reason,
    )


def get_snapshot_status(exports_dir: Path) -> dict[str, Any]:
    """Get the current status of all snapshot files in the exports directory.

    Returns a summary dict with per-source status and overall assessment.
    """
    result: dict[str, Any] = {
        "exports_dir": str(exports_dir),
        "checked_at": _now_iso(),
        "sources": {},
        "overall_status": "unknown",
    }

    if not exports_dir.exists():
        result["overall_status"] = "no_data"
        result["note"] = "Exports directory does not exist"
        return result

    statuses: list[str] = []
    for source_name, filename in SNAPSHOT_FILES.items():
        filepath = exports_dir / filename
        if filepath.exists():
            data = _load_snapshot(filepath)
            if data is not None:
                source_status = data.get("status", "unknown")
                result["sources"][source_name] = {
                    "file": filename,
                    "status": source_status,
                    "generated_at": data.get("generated_at"),
                    "stale_reason": data.get("stale_reason"),
                    "sha256": _compute_sha256(filepath),
                }
                statuses.append(source_status)
            else:
                result["sources"][source_name] = {
                    "file": filename,
                    "status": "corrupted",
                    "sha256": _compute_sha256(filepath),
                }
                statuses.append("error")
        else:
            result["sources"][source_name] = {
                "file": filename,
                "status": "missing",
            }
            statuses.append("missing")

    # Determine overall status
    if not statuses:
        result["overall_status"] = "no_data"
    elif all(s == "fresh" for s in statuses):
        result["overall_status"] = "fresh"
    elif any(s == "error" for s in statuses) or any(s == "missing" for s in statuses):
        result["overall_status"] = "partial"
    elif any(s == "stale" for s in statuses):
        result["overall_status"] = "stale"
    else:
        result["overall_status"] = "mixed"

    return result


def validate_snapshot_integrity(exports_dir: Path, expected_hashes: dict[str, str]) -> list[str]:
    """Validate that snapshot files match expected hashes.

    Args:
        exports_dir: Path to the exports directory.
        expected_hashes: Mapping of filename to expected SHA256 hash.

    Returns:
        List of mismatch descriptions. Empty list means all OK.
    """
    mismatches: list[str] = []

    for filename, expected_hash in expected_hashes.items():
        filepath = exports_dir / filename
        if not filepath.exists():
            mismatches.append(f"File missing: {filename}")
            continue

        actual_hash = _compute_sha256(filepath)
        if actual_hash != expected_hash:
            mismatches.append(
                f"Hash mismatch for {filename}: "
                f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
            )

    return mismatches


def copy_snapshots_to_run_dir(
    exports_dir: Path,
    run_dir: Path,
) -> list[SnapshotMeta]:
    """Copy all valid snapshot files to a run directory for provenance.

    Args:
        exports_dir: Source exports directory.
        run_dir: Target run directory (will create modules/environment/ inside).

    Returns:
        List of SnapshotMeta for copied files.
    """
    target_dir = run_dir / "modules" / "environment"
    target_dir.mkdir(parents=True, exist_ok=True)

    copied: list[SnapshotMeta] = []
    generated_at = _now_iso()

    for source_name, filename in SNAPSHOT_FILES.items():
        src_path = exports_dir / filename
        if not src_path.exists():
            continue

        dst_path = target_dir / filename
        shutil.copy2(src_path, dst_path)

        data = _load_snapshot(dst_path)
        status = data.get("status", "unknown") if data else "corrupted"
        stale_reason = data.get("stale_reason") if data else None

        copied.append(
            SnapshotMeta(
                filename=filename,
                path=str(dst_path),
                sha256=_compute_sha256(dst_path),
                generated_at=data.get("generated_at", generated_at) if data else generated_at,
                status=status,
                stale_reason=stale_reason,
            )
        )

    return copied
