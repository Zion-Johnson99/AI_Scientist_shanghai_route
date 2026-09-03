"""Rewrite absolute user-home paths in this run's command logs to env-var form.

Stage-7 gate 13 forbids 用户绝对路径 in deliverables. The Playwright install log
records the browser cache directory, which is genuinely useful evidence, so the
path is normalised to its environment-variable equivalent rather than deleted:
``%LOCALAPPDATA%`` and ``%USERPROFILE%`` expand to exactly the same locations,
so no information is lost and nothing is fabricated.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("commands", "checks", "reports", "evidence", "publish")
TEXT_SUFFIXES = {".log", ".out", ".err", ".txt", ".json", ".jsonl", ".md", ".py", ".ps1", ".csv"}

#: ``%USERPROFILE% and ``C:\\Users\\name`` both appear, depending on which tool
#: wrote the log, so match either separator.
HOME_RE = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\"'\s]+")
LOCAL_RE = re.compile(r"%USERPROFILE%[\\/]AppData[\\/]Local", re.IGNORECASE)


def normalise(text: str) -> str:
    """Replace absolute home paths with their env-var equivalents."""
    text = HOME_RE.sub("%USERPROFILE%", text)
    return LOCAL_RE.sub("%LOCALAPPDATA%", text)


def main() -> int:
    changed: list[tuple[str, int]] = []
    for root in SCAN_ROOTS:
        base = RUN_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if path.stat().st_size > 20_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hits = len(HOME_RE.findall(text))
            if not hits:
                continue
            path.write_text(normalise(text), encoding="utf-8", newline="")
            changed.append((str(path.relative_to(RUN_ROOT)), hits))

    for rel, hits in changed:
        print(f"SCRUBBED {rel} occurrences={hits}")
    print(f"files_changed={len(changed)} total_occurrences={sum(h for _, h in changed)}")

    residual: list[str] = []
    for root in SCAN_ROOTS:
        base = RUN_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if HOME_RE.search(line):
                    residual.append(f"{path.relative_to(RUN_ROOT)}:{lineno}")
    print(f"residual={len(residual)}")
    for item in residual[:20]:
        print(f"RESIDUAL {item}")
    print(f"home_was={HOME_RE.sub('%USERPROFILE%', os.path.expanduser('~'))}")
    return 1 if residual else 0


if __name__ == "__main__":
    raise SystemExit(main())
