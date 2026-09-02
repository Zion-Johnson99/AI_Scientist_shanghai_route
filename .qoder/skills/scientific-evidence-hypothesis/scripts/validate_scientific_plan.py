#!/usr/bin/env python3
"""Validate reports/scientific_plan.json contest fields and citation integrity (stdlib only).

Checks per docs/qwen-harness-build/01 §19.1 and 02 §5:
  - required contest fields exist and are non-empty;
  - datasets.source / datasets.target present;
  - references resolve to registered source_ids (verification rate 100%);
  - provenance fields run_id / git_head / data_snapshot_hashes present.

Usage: python validate_scientific_plan.py <run-dir>
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOP_FIELDS = [
    "problem_statement",
    "rationale",
    "technical_details",
    "paper_title",
    "paper_abstract",
    "methods",
    "results",
    "references",
    "limitations",
    "reproducibility",
]
PROVENANCE_FIELDS = ["run_id", "git_head", "data_snapshot_hashes"]


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def read_jsonl_ids(path: Path) -> set:
    ids = set()
    if not path.is_file():
        return ids
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("source_id"):
            ids.add(obj["source_id"])
    return ids


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python validate_scientific_plan.py <run-dir>")
        return 2
    run_dir = Path(sys.argv[1])
    plan_path = run_dir / "reports" / "scientific_plan.json"
    if not plan_path.is_file():
        print(f"FAIL: missing {plan_path}")
        return 1

    problems: list[str] = []
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: scientific_plan.json invalid JSON ({exc})")
        return 1
    if not isinstance(plan, dict):
        print("FAIL: scientific_plan.json must be a JSON object")
        return 1

    for field in TOP_FIELDS:
        if field not in plan:
            problems.append(f"missing field '{field}'")
        elif is_blank(plan[field]):
            problems.append(f"field '{field}' is empty")

    datasets = plan.get("datasets")
    if not isinstance(datasets, dict):
        problems.append("missing 'datasets' object")
    else:
        for key in ("source", "target"):
            if is_blank(datasets.get(key)):
                problems.append(f"datasets.{key} missing or empty")

    experiments = plan.get("experiments")
    if not isinstance(experiments, dict):
        problems.append("missing 'experiments' object")
    else:
        for key in ("baselines", "metrics"):
            if is_blank(experiments.get(key)):
                problems.append(f"experiments.{key} missing or empty")

    for field in PROVENANCE_FIELDS:
        if is_blank(plan.get(field)):
            problems.append(f"provenance field '{field}' missing or empty")

    # References must resolve to the source registry (100% verification).
    registry_ids = read_jsonl_ids(run_dir / "sources" / "source_registry.jsonl")
    references = plan.get("references")
    if isinstance(references, list) and references:
        seen = set()
        for idx, ref in enumerate(references, start=1):
            sid = ref.get("source_id") if isinstance(ref, dict) else ref
            if not isinstance(sid, str) or not sid:
                problems.append(f"reference #{idx}: missing source_id")
                continue
            if sid not in registry_ids:
                problems.append(f"reference #{idx}: source_id '{sid}' not in source registry")
            if sid in seen:
                problems.append(f"reference #{idx}: duplicate source_id '{sid}'")
            seen.add(sid)
    elif not problems:
        problems.append("references must contain at least one entry")

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1
    print("PASS: scientific plan fields complete and all references resolve to the registry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
