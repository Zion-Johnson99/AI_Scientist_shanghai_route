"""Provenance utilities: SHA256 hashing, Git metadata and run hash manifests.

Used by RunStore to fill ``run_manifest.json`` (design doc sections 7.2, 21).
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_CHUNK_SIZE = 65536


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class GitSnapshot:
    available: bool = False
    branch: str | None = None
    head: str | None = None
    clean: bool | None = None
    error: str | None = None


def _git(repo_root: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        shell=False,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_snapshot(repo_root: Path) -> GitSnapshot:
    """Collect branch / HEAD / clean-state without failing the run."""
    snapshot = GitSnapshot()
    try:
        code, out, err = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            snapshot.error = err or "git rev-parse failed"
            return snapshot
        snapshot.available = True
        snapshot.branch = out
        code, out, err = _git(repo_root, "rev-parse", "HEAD")
        snapshot.head = out if code == 0 else None
        code, out, _err = _git(repo_root, "status", "--porcelain")
        snapshot.clean = (out == "") if code == 0 else None
    except (OSError, subprocess.SubprocessError) as exc:
        snapshot.error = str(exc)
    return snapshot


def hash_paths(paths: Iterable[Path], relative_to: Path) -> dict[str, str]:
    """SHA256 manifest keyed by POSIX path relative to ``relative_to``."""
    base = Path(relative_to).resolve()
    manifest: dict[str, str] = {}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(base).as_posix()
        except ValueError:
            rel = path.resolve().name
        manifest[rel] = sha256_file(path)
    return dict(sorted(manifest.items()))


def config_hashes(config_dir: Path) -> dict[str, str]:
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        return {}
    files = [p for p in sorted(config_dir.rglob("*.json")) if p.is_file()]
    return hash_paths(files, config_dir.parent)


#: Key stable artifacts per module, probed for hashing at run creation.
MODULE_DATA_FILES: dict[str, tuple[str, ...]] = {
    "route": (
        "data/web/route_catalog.json",
        "data/web/xuhui_routes.geojson",
        "data/web/xuhui_entries.geojson",
        "data/web/poi_catalog.json",
        "data/web/access_cases.json",
        "data/web/environment_dashboard.json",
    ),
    "environment": (
        "runtime/exports/environment_latest.json",
        "runtime/exports/route_environment.json",
    ),
}


def module_data_hashes(module_roots: dict[str, Path]) -> tuple[dict[str, str], list[str]]:
    """Hash key module data files; return (hashes, missing_labels)."""
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for module, rel_paths in MODULE_DATA_FILES.items():
        root = module_roots.get(module)
        if root is None:
            missing.extend(f"{module}:{rel}" for rel in rel_paths)
            continue
        for rel in rel_paths:
            path = Path(root) / rel
            if path.is_file():
                hashes[f"{module}/{rel}"] = sha256_file(path)
            else:
                missing.append(f"{module}/{rel}")
    return dict(sorted(hashes.items())), sorted(missing)


@dataclass
class RunDirectoryManifest:
    """Hash manifest over a finished run directory (reproducibility checks)."""

    run_id: str
    files: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, run_id: str, run_dir: Path) -> "RunDirectoryManifest":
        run_dir = Path(run_dir)
        files: dict[str, str] = {}
        if run_dir.is_dir():
            for path in sorted(run_dir.rglob("*")):
                if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
                    rel = path.relative_to(run_dir).as_posix()
                    files[rel] = sha256_file(path)
        return cls(run_id=run_id, files=files)
