from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


RESEARCH_FILES = tuple(f"{mode}_route_candidates_0813.json" for mode in ("walk", "run", "bike"))


def merge_research_drafts(
    research_dir: Path,
    target: Path,
    validate: Callable[[list[dict[str, Any]]], None],
) -> list[dict[str, Any]]:
    missing = [name for name in RESEARCH_FILES if not (research_dir / name).is_file()]
    if missing:
        raise ValueError(f"missing research files: {missing}")
    merged: list[dict[str, Any]] = []
    for name in RESEARCH_FILES:
        payload = json.loads((research_dir / name).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"research file must contain a list: {name}")
        merged.extend(payload)
    validate(merged)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(merged, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return merged
