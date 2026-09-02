"""当前 run 内的源码工作区与原子写入。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from threading import RLock

from ..errors import PathBoundaryError
from .models import REQUIRED_PROJECT_ROOTS, normalize_source_path


class GenerationWorkspace:
    """把全部模型写入限制在 ``<run-dir>/workspace/source``。"""

    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir).resolve()
        self.workspace_root = self.run_dir / "workspace"
        self.source_root = self.workspace_root / "source"
        self._write_lock = RLock()

    def initialize(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._require_within_run(self.workspace_root, "workspace")
        self.source_root.mkdir(parents=True, exist_ok=True)
        self._require_within_run(self.source_root, "workspace/source")
        for project in REQUIRED_PROJECT_ROOTS:
            target = self.source_root / project
            if target.exists() and target.is_symlink():
                raise PathBoundaryError(f"生成项目目录不允许使用符号链接: {target}")
            target.mkdir(exist_ok=True)
        return self.source_root

    def resolve_file(self, relative_path: str) -> Path:
        try:
            normalized = normalize_source_path(relative_path)
        except ValueError as exc:
            raise PathBoundaryError(
                f"生成文件路径无效: {relative_path!r}",
                details={"relative_path": relative_path, "source_root": str(self.source_root)},
            ) from exc
        source_root = self.source_root.resolve()
        destination = (source_root / normalized).resolve()
        try:
            destination.relative_to(source_root)
        except ValueError as exc:
            raise PathBoundaryError(
                f"生成文件路径越界: {destination}",
                details={"relative_path": normalized, "source_root": str(source_root)},
            ) from exc
        return destination

    def write_text(self, relative_path: str, content: str) -> Path:
        """以 UTF-8 原子写入单个模型生成文件。"""
        with self._write_lock:
            self.initialize()
            destination = self.resolve_file(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(content, encoding="utf-8", newline="\n")
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
            return destination

    def read_text(self, relative_path: str) -> str:
        return self.resolve_file(relative_path).read_text(encoding="utf-8")

    def _require_within_run(self, candidate: Path, label: str) -> None:
        try:
            candidate.resolve().relative_to(self.run_dir)
        except ValueError as exc:
            raise PathBoundaryError(
                f"{label} 解析后越出当前 run: {candidate.resolve()}",
                details={"label": label, "run_dir": str(self.run_dir)},
            ) from exc
