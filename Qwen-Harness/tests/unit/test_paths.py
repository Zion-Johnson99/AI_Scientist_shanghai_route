from __future__ import annotations

from pathlib import Path

import pytest

from qwen_harness.errors import PathBoundaryError
from qwen_harness.paths import resolve_within


def test_resolve_within_accepts_nested_path(tmp_path: Path) -> None:
    resolved = resolve_within(tmp_path, "runtime/runs", "runtime")

    assert resolved == (tmp_path / "runtime" / "runs").resolve()


def test_resolve_within_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(PathBoundaryError, match="越界"):
        resolve_within(tmp_path, "../outside", "runtime")


def test_resolve_within_rejects_absolute_path_outside_boundary(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"

    with pytest.raises(PathBoundaryError):
        resolve_within(tmp_path, outside, "publish")
