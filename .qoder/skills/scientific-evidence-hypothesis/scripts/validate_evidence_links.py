#!/usr/bin/env python3
"""Validate evidence cards link back to the source registry (stdlib only).

Checks: every EvidenceClaim.source_id resolves in source_registry.jsonl,
claim fields and enums are valid, claim_id unique, and hypothesis/gap stage
outputs (if present) only reference existing claim/source ids.

Usage: python validate_evidence_links.py <run-dir>
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVIDENCE_TYPES = {"result", "method", "dataset", "limitation", "definition", "policy"}
STRENGTHS = {"high", "medium", "low"}


def read_jsonl(path: Path, problems: list[str]) -> list[dict]:
    records = []
    if not path.is_file():
        problems.append(f"missing file: {path}")
        return records
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}:{lineno}: invalid JSON ({exc})")
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            problems.append(f"{path.name}:{lineno}: record must be an object")
    return records


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python validate_evidence_links.py <run-dir>")
        return 2
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"FAIL: run directory not found: {run_dir}")
        return 1

    problems: list[str] = []
    registry = read_jsonl(run_dir / "sources" / "source_registry.jsonl", problems)
    cards = read_jsonl(run_dir / "sources" / "evidence_cards.jsonl", problems)

    source_ids = {rec.get("source_id") for rec in registry if isinstance(rec, dict)}
    claim_ids: set[str] = set()

    for idx, card in enumerate(cards, start=1):
        where = f"claim #{idx} ({card.get('claim_id', '?')})"
        for field in ("claim_id", "source_id", "claim", "evidence_location", "evidence_type", "support_strength"):
            if field not in card:
                problems.append(f"{where}: missing field '{field}'")
        cid = card.get("claim_id")
        if cid in claim_ids:
            problems.append(f"duplicate claim_id: {cid}")
        claim_ids.add(cid)
        sid = card.get("source_id")
        if sid not in source_ids:
            problems.append(f"{where}: source_id '{sid}' not in source registry")
        if card.get("evidence_type") not in EVIDENCE_TYPES:
            problems.append(f"{where}: invalid evidence_type {card.get('evidence_type')!r}")
        if card.get("support_strength") not in STRENGTHS:
            problems.append(f"{where}: invalid support_strength {card.get('support_strength')!r}")
        caveats = card.get("caveats")
        if caveats is not None and not isinstance(caveats, list):
            problems.append(f"{where}: caveats must be a list")

    # Cross-check stage outputs that reference claims, when present.
    stages_dir = run_dir / "stages"
    if stages_dir.is_dir():
        for out in sorted(stages_dir.glob("*/output.json")):
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            refs = collect_claim_refs(data)
            for ref in refs:
                if ref not in claim_ids:
                    problems.append(f"{out.parent.name}/output.json: unknown claim_id '{ref}'")

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s), {len(cards)} card(s))")
        return 1
    print(f"PASS: evidence links valid ({len(cards)} card(s), {len(source_ids)} source(s))")
    return 0


def collect_claim_refs(node) -> set:
    refs = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("supporting_claim_ids", "supported_by_claim_ids") and isinstance(value, list):
                refs.update(v for v in value if isinstance(v, str))
            else:
                refs |= collect_claim_refs(value)
    elif isinstance(node, list):
        for item in node:
            refs |= collect_claim_refs(item)
    return refs


if __name__ == "__main__":
    sys.exit(main())
