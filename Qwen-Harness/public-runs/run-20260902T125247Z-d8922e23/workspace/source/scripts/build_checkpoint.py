"""Build ``blind_checkpoint/`` or ``final_checkpoint/`` from the artifacts on disk.

The manifest records run identity, the git head and a SHA-256 for every file under
``workspace/source``, so a later reader can tell whether the frozen tree still
matches what was accepted. ``test_summary.json`` aggregates the check artifacts
instead of restating them, which keeps one source of truth per gate.

The twelve-item product matrix is a judgement about what a browser showed, so it
is authored separately and passed in with ``--product-matrix`` rather than
inferred here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
CHECKS_DIR: Path = RUN_ROOT / "checks"
COMMANDS_DIR: Path = RUN_ROOT / "commands"

#: Caches and dependency trees are not deliverables, so they are neither hashed
#: nor reported.
SKIPPED_DIR_NAMES = frozenset({"__pycache__", ".ruff_cache", "node_modules", ".venv", ".git"})
CHUNK_BYTES = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    """Run-relative posix path, so the manifest stays portable across machines."""
    if not path.is_relative_to(RUN_ROOT):
        return path.name
    return path.relative_to(RUN_ROOT).as_posix()


def source_hashes() -> dict[str, Any]:
    """Hash every source file, and report the total so a diff is checkable."""
    files: dict[str, str] = {}
    for path in sorted(SOURCE_ROOT.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(SOURCE_ROOT).parts[:-1]
        if any(part in SKIPPED_DIR_NAMES for part in parts):
            continue
        files[relative(path)] = sha256_of(path)
    return {"file_count": len(files), "files": files}


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=RUN_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return done.stdout.strip()


def collect_checks() -> list[dict[str, Any]]:
    """One row per check artifact, reading its own verdict rather than guessing."""
    rows: list[dict[str, Any]] = []
    if not CHECKS_DIR.is_dir():
        return rows
    for path in sorted(CHECKS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            rows.append({"check": path.stem, "passed": None, "error": "unreadable"})
            continue
        if not isinstance(payload, dict):
            rows.append({"check": path.stem, "passed": None, "error": "not_an_object"})
            continue
        rows.append(
            {
                "check": path.stem,
                "passed": payload.get("passed"),
                "failure_count": len(payload.get("failures") or [])
                if isinstance(payload.get("failures"), list)
                else None,
                "path": relative(path),
            }
        )
    return rows


def quality_summary() -> dict[str, Any]:
    """Pull the 14-check contract result apart so the summary names each gate."""
    path = CHECKS_DIR / "generated_quality.json"
    if not path.is_file():
        return {"available": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {"available": False, "error": "unreadable"}
    if not isinstance(payload, dict):
        return {"available": False, "error": "not_an_object"}
    checks = payload.get("checks")
    rows: list[dict[str, Any]] = []
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, dict):
                rows.append(
                    {
                        "id": item.get("id"),
                        "passed": item.get("passed"),
                        "required": item.get("required"),
                        "exit_code": item.get("exit_code"),
                    }
                )
    required_failed = [
        str(row["id"]) for row in rows if row.get("required") and not row.get("passed")
    ]
    return {
        "available": True,
        "passed": payload.get("passed"),
        "check_count": len(rows),
        "checks": rows,
        "required_failed": required_failed,
        "path": relative(path),
    }


def load_product_matrix(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {
            "available": False,
            "note": "authored separately from browser evidence; pass --product-matrix",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {"available": False, "error": "unreadable"}
    if not isinstance(payload, dict):
        return {"available": False, "error": "not_an_object"}
    items = payload.get("items")
    passed = 0
    total = 0
    if isinstance(items, list):
        total = len(items)
        passed = sum(1 for item in items if isinstance(item, dict) and item.get("passed"))
    payload.setdefault("available", True)
    payload["passed_count"] = passed
    payload["item_count"] = total
    payload["meets_eight_of_twelve"] = passed >= 8
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("blind", "final"))
    parser.add_argument("--product-matrix", type=Path, default=None)
    parser.add_argument(
        "--generated-at",
        default=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    args = parser.parse_args(argv)

    out_dir = RUN_ROOT / f"{args.stage}_checkpoint"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / "manifest.json"
    run_id = RUN_ROOT.name
    if (RUN_ROOT / "run_manifest.json").is_file():
        try:
            recorded = json.loads((RUN_ROOT / "run_manifest.json").read_text(encoding="utf-8"))
            if isinstance(recorded, dict) and isinstance(recorded.get("run_id"), str):
                run_id = recorded["run_id"]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass

    hashes = source_hashes()
    checks = collect_checks()
    checks_passed = sum(1 for row in checks if row.get("passed") is True)
    checks_failed = sum(1 for row in checks if row.get("passed") is False)

    manifest: dict[str, Any] = {
        "stage": f"{args.stage}_checkpoint",
        "run_id": run_id,
        "run_directory": str(RUN_ROOT),
        "frozen_at": args.generated_at,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_head": git("rev-parse", "HEAD"),
        "provider": "qoder_session",
        "model_name": "qwen3.8-max",
        "billing_channel": "qoder_credits",
        "dashscope_api_used": False,
        "source_file_count": hashes["file_count"],
        "source_sha256": hashes["files"],
        "check_count": len(checks),
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    screenshots = sorted(
        relative(path)
        for path in (out_dir / "screenshots").rglob("*")
        if path.is_file()
    ) if (out_dir / "screenshots").is_dir() else []

    summary: dict[str, Any] = {
        "stage": f"{args.stage}_checkpoint",
        "generated_at": args.generated_at,
        "checks": checks,
        "generated_quality": quality_summary(),
        "product_matrix": load_product_matrix(args.product_matrix),
        "screenshots": screenshots,
        "screenshot_count": len(screenshots),
        "source_file_count": hashes["file_count"],
    }
    (out_dir / "test_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    matrix = summary["product_matrix"]
    print(
        f"stage={args.stage} files={hashes['file_count']} "
        f"checks={len(checks)} passed={checks_passed} failed={checks_failed} "
        f"screenshots={len(screenshots)} "
        f"matrix={matrix.get('passed_count')}/{matrix.get('item_count')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
