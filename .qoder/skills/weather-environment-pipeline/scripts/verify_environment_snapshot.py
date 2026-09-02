#!/usr/bin/env python3
"""Deterministic environment dashboard snapshot check (stdlib only, no network).

Checks per docs/qwen-harness-build/02 §7.6:
  - dashboard top-level structure (current/forecast/grids/metadata/routes);
  - 90 route environment entries whose route_id set matches route_catalog.json;
  - time fields parse (generated_at, business_time, fetched_at);
  - status values stay within the allowed enum;
  - units and estimated markers present on environment blocks;
  - field missing rates reported;
  - no absolute paths or sensitive fields anywhere in the payload.

Usage: python verify_environment_snapshot.py [dashboard.json] [--route-catalog PATH]
Defaults resolve against the repository root.
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

TOP_KEYS = {"current", "forecast", "grids", "metadata", "routes"}
STATUS_ENUM = {
    "ok", "partial", "stale", "error", "missing",
    "not_computed", "not_aggregated", "skipped",
}
REPORT_FIELDS = ("business_time", "status", "spatial_scale", "estimated", "confidence", "unit")
ITEM_KEYS = ("route_id", "status", "pm2_5", "noise", "pollen_daily", "segment_count", "total_length_m")
MISSING_RATE_LIMIT = 0.10
EXPECTED_ROUTES = 90

ABSOLUTE_PATH_RE = re.compile(r"([A-Za-z]:[\\/][A-Za-z0-9_ .-])|(^/(home|Users|root)/)")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|LTAI[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})")


def parse_iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def scan_sensitive(node, path, problems: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            scan_sensitive(value, f"{path}.{key}", problems)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            scan_sensitive(value, f"{path}[{idx}]", problems)
    elif isinstance(node, str):
        if ABSOLUTE_PATH_RE.search(node):
            problems.append(f"absolute path at {path}: {node[:80]!r}")
        if SECRET_RE.search(node):
            problems.append(f"sensitive value at {path}")


def check_block(block, kind: str, route_id: str, problems: list[str], missing: dict) -> None:
    where = f"route {route_id} {kind}"
    if isinstance(block, list):  # pollen_daily
        if not block:
            problems.append(f"{where}: empty list")
            return
        for entry in block:
            for field in REPORT_FIELDS:
                if field not in entry:
                    missing[field] = missing.get(field, 0) + 1
        return
    if not isinstance(block, dict):
        problems.append(f"{where}: expected object, got {type(block).__name__}")
        return
    for field in REPORT_FIELDS + ("value",):
        if field not in block:
            missing[field] = missing.get(field, 0) + 1
    if "estimated" in block and not isinstance(block["estimated"], bool):
        problems.append(f"{where}: estimated must be boolean")
    if "unit" in block and not (isinstance(block["unit"], str) and block["unit"].strip()):
        problems.append(f"{where}: unit must be a non-empty string")
    if "status" in block and block["status"] not in STATUS_ENUM:
        problems.append(f"{where}: invalid status {block['status']!r}")
    for time_field in ("business_time",):
        value = block.get(time_field)
        if value is not None and not (isinstance(value, str) and value.strip()):
            problems.append(f"{where}: {time_field} must be a non-empty string")
    fetched = block.get("fetched_at")
    if fetched not in (None, "") and not parse_iso(fetched):
        problems.append(f"{where}: fetched_at not ISO-8601: {fetched!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description="Verify environment dashboard snapshot")
    parser.add_argument(
        "dashboard",
        nargs="?",
        type=Path,
        default=repo_root / "xuhui_route_builder" / "data" / "web" / "environment_dashboard.json",
    )
    parser.add_argument(
        "--route-catalog",
        type=Path,
        default=repo_root / "xuhui_route_builder" / "data" / "web" / "route_catalog.json",
    )
    args = parser.parse_args()

    problems: list[str] = []
    try:
        dashboard = json.loads(args.dashboard.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"FAIL: dashboard not found: {args.dashboard}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAIL: dashboard invalid JSON ({exc})")
        return 1

    # 1. Top-level structure.
    if not isinstance(dashboard, dict):
        print("FAIL: dashboard must be a JSON object")
        return 1
    for key in TOP_KEYS:
        if key not in dashboard:
            problems.append(f"missing top-level key '{key}'")

    metadata = dashboard.get("metadata", {}) if isinstance(dashboard.get("metadata"), dict) else {}
    generated_at = metadata.get("generated_at")
    if not (isinstance(generated_at, str) and parse_iso(generated_at)):
        problems.append(f"metadata.generated_at missing or not ISO-8601: {generated_at!r}")
    if metadata.get("status") not in STATUS_ENUM:
        problems.append(f"metadata.status invalid: {metadata.get('status')!r}")
    if not metadata.get("schema_version"):
        problems.append("metadata.schema_version missing")

    # 2. Route environment entries.
    routes = dashboard.get("routes", {}) if isinstance(dashboard.get("routes"), dict) else {}
    items = routes.get("items", []) if isinstance(routes.get("items"), list) else []
    if routes.get("status") not in STATUS_ENUM:
        problems.append(f"routes.status invalid: {routes.get('status')!r}")
    if len(items) != EXPECTED_ROUTES:
        problems.append(f"routes.items has {len(items)} entries, expected {EXPECTED_ROUTES}")
    if routes.get("count") != len(items):
        problems.append(f"routes.count={routes.get('count')} but items has {len(items)} entries")

    missing: dict = {}
    item_ids = []
    for item in items:
        if not isinstance(item, dict):
            problems.append("route item is not an object")
            continue
        for key in ITEM_KEYS:
            if key not in item:
                problems.append(f"route item missing key '{key}'")
        route_id = item.get("route_id", "?")
        item_ids.append(route_id)
        if item.get("status") not in STATUS_ENUM:
            problems.append(f"route {route_id}: invalid status {item.get('status')!r}")
        for block in ("pm2_5", "noise", "pollen_daily"):
            if block in item:
                check_block(item[block], block, route_id, problems, missing)

    # 3. Route ID consistency with the route catalog.
    try:
        catalog = json.loads(args.route_catalog.read_text(encoding="utf-8"))
        catalog_ids = {r.get("route_id") for r in catalog if isinstance(r, dict)}
        item_set = set(item_ids)
        if catalog_ids - item_set:
            problems.append(f"catalog routes missing environment: {sorted(catalog_ids - item_set)[:10]}")
        if item_set - catalog_ids:
            problems.append(f"environment ids not in catalog: {sorted(item_set - catalog_ids)[:10]}")
    except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
        problems.append(f"route catalog cross-check failed: {exc}")

    # 4. Missing rates.
    denominator = max(1, len(items))
    for field, count in sorted(missing.items()):
        rate = count / denominator
        print(f"INFO: reporting field '{field}' missing in {count}/{denominator} route entries ({rate:.1%})")
        if rate > MISSING_RATE_LIMIT:
            problems.append(f"reporting field '{field}' missing rate {rate:.1%} exceeds {MISSING_RATE_LIMIT:.0%}")

    # 5. Absolute paths and sensitive fields.
    scan_sensitive(dashboard, "$", problems)

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1
    print(
        f"PASS: environment dashboard valid ({len(items)} routes, status/time/unit/estimated checks "
        "passed, no absolute paths or secrets)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
