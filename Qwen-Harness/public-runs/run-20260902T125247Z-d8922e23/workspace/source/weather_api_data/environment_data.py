"""Adapter surface over the generated environment dashboard.

The dashboard lives beside the route artifacts because the harness environment
adapter resolves it relative to the route module root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DASHBOARD_RELATIVE: str = "data/web/environment_dashboard.json"
STATUS_DOMAIN: frozenset[str] = frozenset({"measured", "derived", "estimated", "unavailable"})
GRID_CELL_COUNT: int = 54
MISSING_RATE_MAX: float = 0.10
CANONICAL_CRS: str = "CRS84/WGS84 (lon,lat)"


class EnvironmentArtifactError(RuntimeError):
    """Raised when the dashboard is missing or structurally invalid."""


@dataclass(frozen=True)
class EnvironmentModuleResult:
    """Immutable summary of the environment dashboard contract."""

    cell_count: int
    route_count: int
    field_keys: tuple[str, ...]
    missing_rate: dict[str, float]
    worst_missing_rate: float
    unit_mismatches: int
    status_violations: int
    crs: str
    data_generated_at: str
    excluded_fields: tuple[str, ...]
    passed: bool
    errors: tuple[str, ...]


def route_module_root() -> Path:
    """Return the route module root, which owns the dashboard file."""
    return Path(__file__).resolve().parent.parent / "xuhui_route_builder"


def load_dashboard(root: Path | None = None) -> dict[str, Any]:
    """Return the dashboard payload, raising if it is absent."""
    base = root or route_module_root()
    target = base / DASHBOARD_RELATIVE
    if not target.is_file():
        raise EnvironmentArtifactError(f"环境产物缺失: {DASHBOARD_RELATIVE}")
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise EnvironmentArtifactError("environment_dashboard.json 无法解析") from exc
    if not isinstance(payload, dict):
        raise EnvironmentArtifactError("environment_dashboard.json 顶层不是对象")
    return payload


def audit(payload: dict[str, Any]) -> EnvironmentModuleResult:
    """Check cell count, units, status domain, CRS and per-field missing rate."""
    errors: list[str] = []
    cells: list[dict[str, Any]] = list(payload.get("cells") or [])
    routes: list[dict[str, Any]] = list(payload.get("routes") or [])
    specs: list[dict[str, Any]] = list(payload.get("field_specs") or [])
    canonical: dict[str, str] = {str(s.get("key")): str(s.get("unit")) for s in specs}
    if len(cells) != GRID_CELL_COUNT:
        errors.append("cell_count_mismatch")
    crs = str(payload.get("crs") or "")
    if crs != CANONICAL_CRS:
        errors.append("crs_mismatch")
    unit_mismatches = 0
    status_violations = 0
    for cell in cells:
        values = cell.get("values")
        if not isinstance(values, dict):
            errors.append("cell_values_missing")
            continue
        for key, block in values.items():
            if not isinstance(block, dict):
                errors.append("value_block_not_object")
                continue
            expected = canonical.get(str(key))
            if expected is not None and str(block.get("unit")) != expected:
                unit_mismatches += 1
            if str(block.get("status")) not in STATUS_DOMAIN:
                status_violations += 1
    if unit_mismatches:
        errors.append("unit_mismatch")
    if status_violations:
        errors.append("status_out_of_domain")
    rates_raw = payload.get("missing_rate")
    missing_rate: dict[str, float] = (
        {str(k): float(v) for k, v in rates_raw.items()} if isinstance(rates_raw, dict) else {}
    )
    worst = max(missing_rate.values()) if missing_rate else 0.0
    if worst > MISSING_RATE_MAX:
        errors.append("missing_rate_exceeded")
    excluded = tuple(
        str(item.get("key"))
        for item in (payload.get("excluded_fields") or [])
        if isinstance(item, dict)
    )
    return EnvironmentModuleResult(
        cell_count=len(cells),
        route_count=len(routes),
        field_keys=tuple(canonical),
        missing_rate=missing_rate,
        worst_missing_rate=worst,
        unit_mismatches=unit_mismatches,
        status_violations=status_violations,
        crs=crs,
        data_generated_at=str(payload.get("data_generated_at") or "unknown"),
        excluded_fields=excluded,
        passed=not errors,
        errors=tuple(errors),
    )


def as_dict(result: EnvironmentModuleResult) -> dict[str, Any]:
    """Serialise an EnvironmentModuleResult for JSON output."""
    return {
        "cell_count": result.cell_count,
        "route_count": result.route_count,
        "field_count": len(result.field_keys),
        "field_keys": list(result.field_keys),
        "missing_rate": result.missing_rate,
        "worst_missing_rate": result.worst_missing_rate,
        "unit_mismatches": result.unit_mismatches,
        "status_violations": result.status_violations,
        "crs": result.crs,
        "data_generated_at": result.data_generated_at,
        "excluded_fields": list(result.excluded_fields),
        "passed": result.passed,
        "errors": list(result.errors),
    }
