#!/usr/bin/env python3
"""Validate score-candidates --json output structure (stdlib only, no network).

Checks per docs/qwen-harness-build/01 §15.4:
  - top-level keys profile/risk/data_generated_at/candidate_count/candidates/weights_sha256;
  - candidate_count equals len(candidates);
  - weights_sha256 is 64 hex chars;
  - candidate route_id values are unique and (optionally) exist in route_catalog.json.

Usage: python verify_score_candidates_output.py <output.json> [--route-catalog PATH]
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
DIMENSIONS = {
    "environment_health",
    "sport_match",
    "access_convenience",
    "route_quality",
    "interest_service",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify score-candidates output")
    parser.add_argument("output", type=Path)
    parser.add_argument("--route-catalog", type=Path, default=None)
    args = parser.parse_args()

    problems: list[str] = []
    try:
        data = json.loads(args.output.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"FAIL: output file not found: {args.output}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAIL: invalid JSON ({exc})")
        return 1
    if not isinstance(data, dict):
        print("FAIL: output must be a JSON object")
        return 1

    for key in ("profile", "risk", "data_generated_at", "candidate_count", "candidates", "weights_sha256"):
        if key not in data:
            problems.append(f"missing top-level key '{key}'")

    profile = data.get("profile")
    if profile is not None and not isinstance(profile, dict):
        problems.append("'profile' must be an object")
    risk = data.get("risk")
    if risk is not None and not isinstance(risk, dict):
        problems.append("'risk' must be an object")

    generated_at = data.get("data_generated_at")
    if generated_at is not None and not (isinstance(generated_at, str) and generated_at.strip()):
        problems.append("'data_generated_at' must be a non-empty string")

    weights_sha = data.get("weights_sha256")
    if weights_sha is not None and not (isinstance(weights_sha, str) and SHA256_RE.match(weights_sha)):
        problems.append("'weights_sha256' must be 64 hex chars")

    candidates = data.get("candidates")
    count = data.get("candidate_count")
    if isinstance(candidates, list):
        if count != len(candidates):
            problems.append(f"candidate_count={count} but candidates has {len(candidates)} entries")
        route_ids = []
        for idx, cand in enumerate(candidates):
            if not isinstance(cand, dict):
                problems.append(f"candidate #{idx} is not an object")
                continue
            rid = cand.get("route_id")
            if not rid:
                problems.append(f"candidate #{idx} missing route_id")
            route_ids.append(rid)
            # Dimension scores, when provided as a dict, use the five known dimensions.
            dims = cand.get("dimension_scores") or cand.get("dimensions")
            if isinstance(dims, dict):
                unknown = set(dims) - DIMENSIONS - {"total", "total_score", "base_score"}
                if unknown:
                    problems.append(f"candidate {rid}: unknown dimension keys {sorted(unknown)}")
        seen = set()
        for rid in route_ids:
            if rid in seen:
                problems.append(f"duplicate candidate route_id: {rid}")
            seen.add(rid)
    else:
        problems.append("'candidates' must be a list")

    # Optional cross-check against the route catalog.
    catalog_path = args.route_catalog
    if catalog_path is None:
        default = Path(__file__).resolve().parents[4] / "xuhui_route_builder" / "data" / "web" / "route_catalog.json"
        catalog_path = default if default.is_file() else None
    if catalog_path is not None and isinstance(candidates, list):
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog_ids = {r.get("route_id") for r in catalog if isinstance(r, dict)}
            for cand in candidates:
                if isinstance(cand, dict) and cand.get("route_id") not in catalog_ids:
                    problems.append(f"candidate route_id not in catalog: {cand.get('route_id')}")
        except (json.JSONDecodeError, TypeError) as exc:
            problems.append(f"route catalog cross-check failed: {exc}")

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1
    n = len(candidates) if isinstance(candidates, list) else 0
    print(f"PASS: score-candidates output valid ({n} candidate(s), weights hash and counts consistent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
