"""Gate 敏感信息 / Key / 用户绝对路径 / 虚假 request ID 检查.

The run directory is the only thing this scan reads, and it reports four separate
risks the task forbids: a committed API key, a credential assignment, a path that
only makes sense on this one machine, and an invented Bailian request or task
identifier.

Two properties matter more than coverage.

First, the scanner has to satisfy its own patterns. Every rule is assembled from
fragments at import time, so no matched literal ever appears contiguously in this
file and the scan cannot report itself. That includes this docstring, which
describes the rules without spelling out a single example of what they match. A
scanner that flags its own source is worse than no scanner, because the obvious
"fix" is to allow-list the scanner and then allow-list whatever else is convenient.

Second, severity has to depend on what the file is. Command logs legitimately
contain tracebacks, and a Python traceback on Windows contains the interpreter's
own absolute path. Treating that as a deliverable defect would make the gate
impossible to pass without deleting the evidence the task explicitly asks for. So
files under ``commands/`` are evidence: their findings are warnings. Everything
else ships, and its findings are violations.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
CHECKS_DIR: Path = RUN_ROOT / "checks"

#: Anything larger is almost certainly a generated payload rather than source, and
#: reading it line by line costs more than the whole rest of the scan.
MAX_FILE_BYTES = 16 * 1024 * 1024

TEXT_SUFFIXES = frozenset(
    {
        ".py", ".js", ".mjs", ".json", ".jsonl", ".md", ".txt", ".html", ".css",
        ".ps1", ".sh", ".yml", ".yaml", ".toml", ".csv", ".log", ".out", ".err",
        ".geojson", ".cfg", ".ini", ".xml", ".svg",
    }
)

#: Dependency and cache trees are not deliverables and are not ours to audit.
SKIPPED_DIR_NAMES = frozenset({"node_modules", "__pycache__", ".ruff_cache", ".venv", ".git"})

#: Built from pieces so this module never contains a contiguous match for its own
#: credential rule. ``KEY_NAMES`` is the vendor prefix only.
KEY_NAMES = ("DASHSCOPE", "OPENAI")
KEY_SUFFIX = "_API" + "_KEY"
CREDENTIAL_PATTERN = re.compile(
    "(?:" + "|".join(KEY_NAMES) + ")" + KEY_SUFFIX + r"""["']?\s*[=:]\s*["']?([A-Za-z0-9_\-]{8,})"""
)

#: Key-shaped strings. ``sk-`` followed by a long alphanumeric run; the character
#: class in the source keeps this from matching itself.
KEY_SHAPE_PATTERN = re.compile(r"sk-[A-Za-z0-9]{16,}")

#: Per-user home directories. Fragmented for the same self-match reason: the
#: Windows separator is built with ``chr`` so no literal backslash run appears.
_HOME_PATTERNS = (
    re.compile(re.escape("C:" + chr(92) + "Users" + chr(92)) + r"[^\\/\s]+"),
    re.compile(re.escape("/" + "Users" + "/") + r"[^/\s]+"),
    re.compile(re.escape("/" + "home" + "/") + r"[^/\s]+"),
)

#: Invented provider identifiers. Only placeholders the task names are acceptable;
#: a real-looking value here would be a fabrication, since no paid API was called.
ALLOWED_ID_VALUES = frozenset(
    {"", "unknown", "evidence_pending_user_capture", "not_applicable", "not_applicable_no_credentials"}
)
PROVIDER_ID_PATTERN = re.compile(r'"(?:request_id|task_id|billing_id)"\s*:\s*"([^"]*)"')

#: The report carries ``shape`` rather than the regex source. Emitting
#: ``pattern.pattern`` writes the escaped literals back out contiguously, so the
#: JSON this scan produces matches the very rule it documents and the gate can
#: never pass a second time. The source stays readable in this module, where the
#: fragments keep it from matching itself.
RULES: list[dict[str, Any]] = [
    {
        "id": "key_shape",
        "shape": "密钥常见前缀，后接 16 位以上字母数字串",
        "severity": "violation",
        "why": "任务禁止读取或写入任何 Key；出现该形状的字符串即视为泄露",
    },
    {
        "id": "credential_assignment",
        "shape": "供应商前缀加密钥变量名，随后是等号或冒号赋值和一个取值",
        "severity": "violation",
        "why": "只有 name=value 形式的凭据赋值才算泄露；单独出现变量名（如清理列表）不报",
    },
    {
        "id": "user_home_path",
        "shape": "Windows 用户目录前缀、macOS 用户目录前缀或 Linux 家目录前缀，后接一段用户名",
        "severity": "deliverable=violation, commands/=warning",
        "why": "交付物必须可在他人机器上复现；命令日志中的解释器路径属于取证痕迹，只告警",
    },
    {
        "id": "provider_identifier",
        "shape": "request_id、task_id 或 billing_id 三个 JSON 键之一的字符串取值",
        "severity": "violation",
        "why": "未调用付费 API，任何真实形状的 request/task ID 都是编造；只允许占位值",
    },
]


def mask(value: str) -> str:
    """Return an excerpt that proves a finding without reproducing the secret."""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 5) + value[-2:]


def classify(relative: str) -> str:
    """Command output is evidence, everything else is a deliverable."""
    return "log" if relative.startswith("commands/") else "deliverable"


def scan_text(relative: str, text: str) -> list[dict[str, Any]]:
    """Apply every rule to one decoded file and return its findings."""
    findings: list[dict[str, Any]] = []
    category = classify(relative)
    for number, line in enumerate(text.splitlines(), start=1):
        for match in KEY_SHAPE_PATTERN.finditer(line):
            findings.append(_finding(relative, "key_shape", number, match.group(0), category))
        for match in CREDENTIAL_PATTERN.finditer(line):
            findings.append(
                _finding(relative, "credential_assignment", number, match.group(0), category)
            )
        for pattern in _HOME_PATTERNS:
            for match in pattern.finditer(line):
                findings.append(
                    _finding(relative, "user_home_path", number, match.group(0), category)
                )
        for match in PROVIDER_ID_PATTERN.finditer(line):
            if match.group(1).strip() not in ALLOWED_ID_VALUES:
                findings.append(
                    _finding(relative, "provider_identifier", number, match.group(0), category)
                )
    return findings


def _finding(
    relative: str, rule_id: str, line: int, matched: str, category: str
) -> dict[str, Any]:
    """Build one finding record with a masked excerpt and a resolved severity."""
    if rule_id == "user_home_path" and category == "log":
        severity = "warning"
    else:
        severity = "violation"
    return {
        "path": relative,
        "category": category,
        "rule": rule_id,
        "line": line,
        "excerpt": mask(matched),
        "severity": severity,
    }


def walk() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Scan the run directory and return findings plus coverage statistics."""
    findings: list[dict[str, Any]] = []
    scanned = 0
    skipped_dirs: list[str] = []
    skipped_binary: list[str] = []
    skipped_large: list[str] = []
    env_files: list[str] = []
    for path in sorted(RUN_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(RUN_ROOT).as_posix()
        if any(part in SKIPPED_DIR_NAMES for part in path.relative_to(RUN_ROOT).parts[:-1]):
            skipped_dirs.append(relative)
            continue
        if path.name == ".env" or path.name.startswith(".env."):
            #: Presence only. The task forbids reading any .env, so this scan
            #: reports that one exists in the run directory and never opens it.
            env_files.append(relative)
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            skipped_binary.append(relative)
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped_large.append(relative)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped_binary.append(relative)
            continue
        scanned += 1
        findings.extend(scan_text(relative, text))
    stats = {
        "files_scanned": scanned,
        "files_skipped_dependency_or_cache": len(skipped_dirs),
        "files_skipped_binary": len(skipped_binary),
        "files_skipped_oversize": len(skipped_large),
        "skipped_oversize_paths": skipped_large[:20],
        "env_files_present": env_files,
    }
    return findings, stats


def main() -> int:
    """Scan, write checks/secret_scan.json, and report the gate result."""
    findings, stats = walk()
    violations = [item for item in findings if item["severity"] == "violation"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    payload: dict[str, Any] = {
        "check": "secret_scan",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rule": "run 目录内不得出现 Key、凭据赋值、用户主目录绝对路径或编造的百炼 request/task ID",
        "scope": "Qwen-Harness/runtime/runs/<run-id>/ 全量文本文件",
        "severity_policy": "commands/ 下的日志为 warning，其余交付物为 violation",
        "passed": not violations,
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "violations": violations[:200],
        "warnings": warnings[:200],
        "rules": RULES,
        "allowed_provider_id_values": sorted(ALLOWED_ID_VALUES),
        **stats,
    }
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    (CHECKS_DIR / "secret_scan.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item in violations[:40]:
        print(f"FAIL {item['rule']} {item['path']}:{item['line']} {item['excerpt']}")
    print(
        f"scanned={stats['files_scanned']} violations={len(violations)} "
        f"warnings={len(warnings)} env_files={len(stats['env_files_present'])}"
    )
    passed = not violations
    print(f"SECRET_SCAN_PASSED={str(passed).lower()}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
