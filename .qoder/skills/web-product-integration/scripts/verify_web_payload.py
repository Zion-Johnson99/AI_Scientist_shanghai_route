#!/usr/bin/env python3
"""Validate research_harness_latest.json web payload (stdlib only, no network).

Checks per docs/qwen-harness-build/01 §19.3 and §18.5 (PublishGate):
  - required keys and non-empty strings;
  - status within supported/partially_supported/unsupported/inconclusive;
  - selected_route.route_id exists in route_catalog.json;
  - references are https URLs or explicit local sources;
  - artifacts are repo-relative paths or https URLs;
  - no absolute paths, keys, or other sensitive values.

Usage: python verify_web_payload.py [payload.json] [--route-catalog PATH]
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

STATUS_ENUM = {"supported", "partially_supported", "unsupported", "inconclusive"}
STRING_FIELDS = ("schema_version", "run_id", "research_question", "hypothesis")
LIST_FIELDS = ("key_metrics", "baseline_comparison", "iterations", "references", "limitations", "artifacts")
ABSOLUTE_PATH_RE = re.compile(r"([A-Za-z]:[\\/][A-Za-z0-9_ .-])|(^/(home|Users|root)/)")
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|LTAI[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})"
)


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


def check_ref(ref, idx: int, problems: list[str]) -> None:
    if isinstance(ref, dict):
        url = ref.get("url") or ref.get("href") or ""
        title = ref.get("title") or ref.get("source_id") or ""
        if not (url or title):
            problems.append(f"reference #{idx}: needs url or title/source_id")
            ref = url
        else:
            ref = url or title
    if isinstance(ref, str) and ref:
        is_https = ref.startswith("https://")
        is_local = not re.match(r"^[a-z][a-z0-9+.-]*://", ref, re.IGNORECASE)
        if not (is_https or is_local):
            problems.append(f"reference #{idx}: must be https or explicit local source: {ref[:80]}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description="Verify research harness web payload")
    parser.add_argument(
        "payload",
        nargs="?",
        type=Path,
        default=repo_root / "xuhui_route_builder" / "data" / "web" / "research_harness_latest.json",
    )
    parser.add_argument(
        "--route-catalog",
        type=Path,
        default=repo_root / "xuhui_route_builder" / "data" / "web" / "route_catalog.json",
    )
    args = parser.parse_args()

    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"FAIL: payload not found: {args.payload}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAIL: payload invalid JSON ({exc})")
        return 1
    if not isinstance(payload, dict):
        print("FAIL: payload must be a JSON object")
        return 1

    problems: list[str] = []
    for field in STRING_FIELDS:
        value = payload.get(field)
        if not (isinstance(value, str) and value.strip()):
            problems.append(f"field '{field}' missing or empty")

    generated_at = payload.get("generated_at")
    if not (isinstance(generated_at, str) and parse_iso(generated_at)):
        problems.append(f"'generated_at' missing or not ISO-8601: {generated_at!r}")

    if payload.get("status") not in STATUS_ENUM:
        problems.append(f"'status' invalid: {payload.get('status')!r} (allowed: {sorted(STATUS_ENUM)})")

    for field in LIST_FIELDS:
        value = payload.get(field)
        if not isinstance(value, list):
            problems.append(f"field '{field}' must be a list")

    selected = payload.get("selected_route")
    if not isinstance(selected, dict):
        problems.append("'selected_route' must be an object")
    else:
        for key in ("route_id", "route_name", "reason"):
            if not (isinstance(selected.get(key), str) and selected[key].strip()):
                problems.append(f"selected_route.{key} missing or empty")
        route_id = selected.get("route_id")
        try:
            catalog = json.loads(args.route_catalog.read_text(encoding="utf-8"))
            catalog_ids = {r.get("route_id") for r in catalog if isinstance(r, dict)}
            if route_id not in catalog_ids:
                problems.append(f"selected_route.route_id '{route_id}' not in route_catalog.json")
        except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
            problems.append(f"route catalog cross-check failed: {exc}")

    for idx, ref in enumerate(payload.get("references", []) or [], start=1):
        check_ref(ref, idx, problems)

    for idx, artifact in enumerate(payload.get("artifacts", []) or [], start=1):
        if not isinstance(artifact, str):
            artifact = artifact.get("path") if isinstance(artifact, dict) else ""
        if not artifact:
            problems.append(f"artifact #{idx}: empty")
        elif artifact.startswith(("http://",)):
            problems.append(f"artifact #{idx}: must be https or repo-relative: {artifact[:80]}")
        elif not artifact.startswith("https://") and (artifact.startswith("/") or ABSOLUTE_PATH_RE.match(artifact)):
            problems.append(f"artifact #{idx}: must be repo-relative, got {artifact[:80]}")

    scan_sensitive(payload, "$", problems)

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1
    print("PASS: web payload structure, status enum, route linkage, references and artifacts all valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
