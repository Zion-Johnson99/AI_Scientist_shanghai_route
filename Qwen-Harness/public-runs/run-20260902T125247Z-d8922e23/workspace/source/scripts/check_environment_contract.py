"""Gate 9: the 54-cell environment grid must agree with the route catalog.

The contract asks for identity, unit, time, status and missing-value consistency
between the environment grid and the route set. ``validate_dashboard`` already
enforces the per-cell rules and the per-field missing rate, so this script adds
only the cross-artifact checks it cannot see: the route id sets must match in
both directions, every declared field must carry a unit, and both artifacts must
report the same generation stamp.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
CHECKS_DIR: Path = RUN_ROOT / "checks"

#: Run as ``python scripts/check_environment_contract.py``, so sys.path[0] is
#: scripts/ and the first-party packages one level up are invisible without this.
sys.path.insert(0, str(SOURCE_ROOT))

from environment.contract import (  # noqa: E402
    CANONICAL_CRS,
    DEFAULT_DASHBOARD_PATH,
    FIELD_SPECS,
    GRID_CELL_COUNT,
    MISSING_RATE_LIMIT,
    STATUS_DOMAIN,
    validate_dashboard,
)

CATALOG_PATH: Path = SOURCE_ROOT / "xuhui_route_builder" / "data" / "web" / "route_catalog.json"


def load_json(path: Path) -> dict[str, Any]:
    """Read one JSON artifact, tolerating a non-object root."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def route_ids(payload: dict[str, Any]) -> set[str]:
    """Collect the route ids an artifact claims, ignoring malformed entries."""
    entries = payload.get("routes")
    if not isinstance(entries, list):
        return set()
    ids: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("route_id"), str):
            ids.add(entry["route_id"])
    return ids


def unit_problems() -> list[str]:
    """Every field spec must declare a unit, and no key may declare two."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for spec in FIELD_SPECS:
        key = str(spec.get("key", ""))
        unit = str(spec.get("unit", ""))
        if not key:
            problems.append("field_spec_missing_key")
            continue
        if not unit:
            problems.append(f"unit_missing:{key}")
        if key in seen and seen[key] != unit:
            problems.append(f"unit_conflict:{key}")
        seen[key] = unit
    return problems


def relative(path: Path) -> str:
    """Run-relative posix path, so the report stays portable across machines."""
    if not path.is_relative_to(RUN_ROOT):
        return path.name
    return path.relative_to(RUN_ROOT).as_posix()


def main() -> int:
    """Compare the dashboard against the catalog and write the gate result."""
    failures: list[str] = []
    if not DEFAULT_DASHBOARD_PATH.exists():
        failures.append(f"dashboard_missing:{DEFAULT_DASHBOARD_PATH.name}")
    if not CATALOG_PATH.exists():
        failures.append(f"route_catalog_missing:{CATALOG_PATH.name}")

    payload: dict[str, Any] = {}
    catalog: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    dash_ids: set[str] = set()
    cat_ids: set[str] = set()

    if not failures:
        payload = load_json(DEFAULT_DASHBOARD_PATH)
        catalog = load_json(CATALOG_PATH)
        dash_ids = route_ids(payload)
        cat_ids = route_ids(catalog)
        validation = validate_dashboard(payload, cat_ids)
        failures.extend(str(item) for item in validation.get("errors", []))
        failures.extend(unit_problems())

        only_dashboard = len(dash_ids - cat_ids)
        only_catalog = len(cat_ids - dash_ids)
        if only_dashboard:
            failures.append(f"route_id_only_in_dashboard:{only_dashboard}")
        if only_catalog:
            failures.append(f"route_id_only_in_catalog:{only_catalog}")

        dash_stamp = str(payload.get("generated_at", ""))
        catalog_stamp = str(catalog.get("generated_at", ""))
        if not dash_stamp:
            failures.append("dashboard_generated_at_missing")
        elif catalog_stamp and dash_stamp != catalog_stamp:
            failures.append("generated_at_mismatch")

    missing_rate = validation.get("missing_rate") if validation else {}
    rates = missing_rate if isinstance(missing_rate, dict) else {}
    report: dict[str, Any] = {
        "check": "environment_contract",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rule": "54 个环境网格与路线目录在 ID、单位、时间、状态和缺失值上契约一致",
        "scope": f"{relative(DEFAULT_DASHBOARD_PATH)} 对 {relative(CATALOG_PATH)}",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures[:200],
        "warnings": [str(item) for item in validation.get("warnings", [])],
        "cell_count": validation.get("cell_count", 0),
        "expected_cell_count": GRID_CELL_COUNT,
        "dashboard_route_count": len(dash_ids),
        "catalog_route_count": len(cat_ids),
        "route_id_sets_equal": bool(cat_ids) and dash_ids == cat_ids,
        "crs": str(payload.get("crs", "")),
        "expected_crs": CANONICAL_CRS,
        "generated_at": str(payload.get("generated_at", "")),
        "catalog_generated_at": str(catalog.get("generated_at", "")),
        "status_domain": list(STATUS_DOMAIN),
        "missing_rate_limit": MISSING_RATE_LIMIT,
        "missing_rate": rates,
        "worst_missing_rate": max(rates.values(), default=0.0),
        "field_count": len(FIELD_SPECS),
        "dashboard_path": relative(DEFAULT_DASHBOARD_PATH),
        "catalog_path": relative(CATALOG_PATH),
    }
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    (CHECKS_DIR / "environment_contract.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item in failures[:40]:
        print(f"FAIL {item}")
    print(
        f"cells={report['cell_count']}/{GRID_CELL_COUNT} "
        f"dashboard_routes={len(dash_ids)} catalog_routes={len(cat_ids)} "
        f"sets_equal={report['route_id_sets_equal']} "
        f"worst_missing_rate={report['worst_missing_rate']}"
    )
    passed = not failures
    print(f"ENVIRONMENT_CONTRACT_PASSED={str(passed).lower()}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
