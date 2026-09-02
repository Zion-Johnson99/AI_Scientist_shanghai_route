#!/usr/bin/env python3
"""Validate a run's source registry against the SourceRecord schema (stdlib only).

Usage: python validate_source_registry.py <run-dir>
Exit codes: 0 PASS, 1 FAIL, 2 usage error.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

SOURCE_TYPES = {"local_file", "pubmed", "crossref", "https_url", "repository_file"}
VERIFICATION = {"verified", "partial", "unverified", "rejected"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def read_jsonl(path: Path, problems: list[str]) -> list[dict]:
    records = []
    if not path.is_file():
        problems.append(f"missing file: {path}")
        return records
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}:{lineno}: invalid JSON ({exc})")
            continue
        if not isinstance(obj, dict):
            problems.append(f"{path.name}:{lineno}: record must be an object")
            continue
        records.append(obj)
    return records


def check_record(rec: dict, idx: int, problems: list[str]) -> None:
    where = f"source #{idx} ({rec.get('source_id', '?')})"
    for field in ("source_id", "source_type", "title", "authors", "accessed_at", "sha256", "license_note", "verification_status"):
        if field not in rec:
            problems.append(f"{where}: missing field '{field}'")
    if rec.get("source_type") not in SOURCE_TYPES:
        problems.append(f"{where}: invalid source_type {rec.get('source_type')!r}")
    if not isinstance(rec.get("authors"), list):
        problems.append(f"{where}: authors must be a list")
    year = rec.get("year")
    if year is not None and not isinstance(year, int):
        problems.append(f"{where}: year must be int or null")
    doi = rec.get("doi")
    if doi not in (None, "") and not DOI_RE.match(str(doi)):
        problems.append(f"{where}: malformed DOI {doi!r}")
    sha = rec.get("sha256")
    if not (isinstance(sha, str) and SHA256_RE.match(sha)):
        problems.append(f"{where}: sha256 must be 64 hex chars")
    if rec.get("verification_status") not in VERIFICATION:
        problems.append(f"{where}: invalid verification_status {rec.get('verification_status')!r}")
    accessed = rec.get("accessed_at")
    if isinstance(accessed, str):
        try:
            datetime.fromisoformat(accessed.replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"{where}: accessed_at is not ISO-8601: {accessed!r}")
    else:
        problems.append(f"{where}: accessed_at missing or not a string")
    if rec.get("source_type") == "repository_file" and not rec.get("local_path"):
        problems.append(f"{where}: repository_file source needs local_path")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python validate_source_registry.py <run-dir>")
        return 2
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"FAIL: run directory not found: {run_dir}")
        return 1

    problems: list[str] = []
    records = read_jsonl(run_dir / "sources" / "source_registry.jsonl", problems)

    seen_ids: set[str] = set()
    for idx, rec in enumerate(records, start=1):
        check_record(rec, idx, problems)
        sid = rec.get("source_id")
        if sid in seen_ids:
            problems.append(f"duplicate source_id: {sid}")
        seen_ids.add(sid)

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s), {len(records)} record(s))")
        return 1
    print(f"PASS: source registry valid ({len(records)} record(s), ids unique)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
