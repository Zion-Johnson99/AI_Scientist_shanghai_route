"""Data pipeline core: tiered refresh logic, last-known-good fallback, snapshot management."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Required API key names checked by check_api_keys
REQUIRED_API_KEYS: list[str] = ["weather_api", "aqi_api"]


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""

    exports_dir: Path
    api_keys: dict[str, str] = field(default_factory=dict)
    allow_network: bool = False
    tier: str = "weather"


@dataclass
class PipelineResult:
    """Result of a pipeline run."""

    status: str  # "ok" | "partial" | "stale" | "error" | "no_data"
    tier: str
    data: dict[str, Any] | None = None
    stale_reason: str | None = None
    missing_items: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to a JSON-compatible dictionary."""
        return {
            "status": self.status,
            "tier": self.tier,
            "data": self.data,
            "stale_reason": self.stale_reason,
            "missing_items": self.missing_items,
        }


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def check_api_keys(config: PipelineConfig) -> list[str]:
    """Return list of required API key names that are missing from config."""
    missing: list[str] = []
    for key_name in REQUIRED_API_KEYS:
        if key_name not in config.api_keys or not config.api_keys[key_name]:
            missing.append(key_name)
    return missing


def load_last_known_good(exports_dir: Path, tier: str) -> dict[str, Any] | None:
    """Load the last-known-good snapshot for a given tier.

    Looks for <tier>_latest.json in exports_dir.
    Returns the parsed dict if valid JSON with a 'data' field, else None.
    """
    path = Path(exports_dir) / f"{tier}_latest.json"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if "data" not in data:
        return None
    return data


def save_snapshot(
    exports_dir: Path,
    tier: str,
    data: dict[str, Any],
    status: str,
    api_keys: dict[str, str] | None = None,
) -> Path:
    """Atomically save a snapshot file for the given tier.

    The snapshot filename includes the tier name.
    API keys are never written into the snapshot content.
    Returns the Path of the written file.
    """
    exports_dir = Path(exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)

    snapshot: dict[str, Any] = {
        "generated_at": _now_iso(),
        "status": status,
        "tier": tier,
        "data": data,
    }

    filename = f"{tier}_latest.json"
    path = exports_dir / filename

    # Atomic write: write to temp then rename
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return path


def run_pipeline(config: PipelineConfig) -> PipelineResult:
    """Execute the data pipeline for the configured tier.

    Logic:
    1. Check API keys and network availability.
    2. If keys are missing or network is unavailable, attempt last-known-good fallback.
    3. If fallback succeeds, return status='stale' with the snapshot data.
    4. If no fallback available, return status='partial' with missing_items.
    5. Never fabricate fill values.
    """
    missing_keys = check_api_keys(config)
    network_available = config.allow_network

    # Determine if we can fetch fresh data
    can_fetch = (len(missing_keys) == 0) and network_available

    if can_fetch:
        # In a real implementation we would call upstream APIs here.
        # For offline-first design without real endpoints, we still
        # fall through to snapshot logic. If network were truly available
        # and APIs responded, we'd return status="ok" with fresh data.
        # Since we have no real endpoints, treat as unable to fetch.
        can_fetch = False

    if not can_fetch:
        # Build a descriptive stale reason
        reasons: list[str] = []
        if missing_keys:
            reasons.append(f"Missing API key(s): {', '.join(missing_keys)}")
        if not network_available:
            reasons.append("Network access is disabled")
        stale_reason = "; ".join(reasons) if reasons else "Unable to fetch fresh data"

        # Attempt last-known-good fallback
        snapshot = load_last_known_good(config.exports_dir, config.tier)
        if snapshot is not None and "data" in snapshot:
            return PipelineResult(
                status="stale",
                tier=config.tier,
                data=snapshot["data"],
                stale_reason=stale_reason,
                missing_items=None,
            )

        # No fallback available: return partial with missing items
        missing_items: list[str] = []
        if missing_keys:
            missing_items.extend(missing_keys)
        if not network_available:
            missing_items.append("network_access")
        if not missing_items:
            missing_items.append("upstream_data")

        return PipelineResult(
            status="partial",
            tier=config.tier,
            data=None,
            stale_reason=None,
            missing_items=missing_items,
        )

    # Unreachable in current offline-first design, but kept for completeness
    return PipelineResult(
        status="ok",
        tier=config.tier,
        data=None,
        stale_reason=None,
        missing_items=None,
    )
