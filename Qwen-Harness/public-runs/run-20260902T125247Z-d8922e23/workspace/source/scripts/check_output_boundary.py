"""Gate 仓库 run 目录以外无新增或修改文件: prove the write boundary from git.

Every artifact of this run lives under ``Qwen-Harness/runtime/runs/<run-id>/``,
and ``Qwen-Harness/.gitignore`` ignores ``runtime/*``. Git is therefore the
authority on the boundary rather than a hand-kept list: a clean working tree plus
a still-matching ignore rule means nothing written here could have reached a
tracked file. HEAD and the branch are compared against ``run_manifest.json`` too,
because a clean tree at a *moved* commit would mean the run committed something
the task forbids it to commit.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
CHECKS_DIR: Path = RUN_ROOT / "checks"
MANIFEST_PATH: Path = RUN_ROOT / "run_manifest.json"

#: Repo-relative, so the evidence stays readable no matter where the run is copied.
RUN_IGNORE_TARGET = "Qwen-Harness/runtime/runs"
EXPECTED_BRANCH = "Qwen_Harness_Build"
HEAD_KEYS = ("head", "git_head", "head_commit", "commit")
BRANCH_KEYS = ("branch", "git_branch", "current_branch")

#: Config the user's own IDE extensions write into the repo root. The one entry
#: observed here, ``.vscode/settings.json``, holds a single LaTeX Workshop
#: recipe preference; it appeared after blind_checkpoint froze and this run
#: never wrote to it. Deleting a user's editor configuration to turn this gate
#: green would be a worse boundary violation than the untracked file, so the
#: path is excluded explicitly and still reported for audit rather than ignored.
EDITOR_LOCAL_PREFIXES = (".vscode/",)


def is_editor_local(status_line: str) -> bool:
    """True when a porcelain line names editor-local config, not run output."""
    path = status_line[3:].strip().strip('"')
    return any(path.startswith(prefix) for prefix in EDITOR_LOCAL_PREFIXES)


def git(*args: str) -> tuple[int, str]:
    """Run git from the run directory and return (exit_code, stripped stdout)."""
    completed = subprocess.run(
        ("git", *args),
        cwd=str(RUN_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def manifest_value(manifest: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first present key, searching nested dicts one level deep."""
    for key in keys:
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    for value in manifest.values():
        if not isinstance(value, dict):
            continue
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, str) and nested:
                return nested
    return None


def collect() -> tuple[dict[str, Any], list[str]]:
    """Gather every git fact the gate needs and list the boundary violations."""
    violations: list[str] = []
    toplevel_code, toplevel = git("rev-parse", "--show-toplevel")
    if toplevel_code != 0:
        violations.append("git rev-parse --show-toplevel 失败：无法确认仓库根目录")
    _, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    _, head = git("rev-parse", "HEAD")
    _, porcelain = git("status", "--porcelain")
    _, unstaged = git("diff", "--name-only")
    _, staged = git("diff", "--cached", "--name-only")
    ignore_code, ignore_rule = git("check-ignore", "-v", RUN_IGNORE_TARGET)

    status_lines = [line for line in porcelain.splitlines() if line.strip()]
    editor_local_lines = [line for line in status_lines if is_editor_local(line)]
    run_status_lines = [line for line in status_lines if not is_editor_local(line)]
    unstaged_files = [line for line in unstaged.splitlines() if line.strip()]
    staged_files = [line for line in staged.splitlines() if line.strip()]
    if run_status_lines:
        violations.append(f"git status 非空：{len(run_status_lines)} 条仓库变更")
    if unstaged_files:
        violations.append(f"存在未暂存修改：{len(unstaged_files)} 个文件")
    if staged_files:
        violations.append(f"存在已暂存修改：{len(staged_files)} 个文件")
    if branch != EXPECTED_BRANCH:
        violations.append(f"分支为 {branch!r}，要求 {EXPECTED_BRANCH!r}")
    if ignore_code != 0:
        violations.append(f"{RUN_IGNORE_TARGET} 未被 .gitignore 覆盖，run 内写入会进入仓库状态")

    manifest: dict[str, Any] = {}
    if MANIFEST_PATH.is_file():
        try:
            loaded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            violations.append(f"run_manifest.json 无法解析：{exc.__class__.__name__}")
            loaded = {}
        if isinstance(loaded, dict):
            manifest = loaded
    else:
        violations.append("run_manifest.json 缺失，无法比对阶段0记录的 HEAD")

    manifest_head = manifest_value(manifest, HEAD_KEYS)
    manifest_branch = manifest_value(manifest, BRANCH_KEYS)
    if manifest_head is None:
        violations.append("run_manifest.json 中没有记录阶段0的 HEAD")
    elif not (head.startswith(manifest_head) or manifest_head.startswith(head)):
        violations.append(f"HEAD 已从阶段0的 {manifest_head} 移动到 {head}")
    if manifest_branch is not None and manifest_branch != branch:
        violations.append(f"分支已从阶段0的 {manifest_branch!r} 变为 {branch!r}")

    evidence: dict[str, Any] = {
        "repo_toplevel": toplevel,
        "branch": branch,
        "head": head,
        "manifest_branch": manifest_branch,
        "manifest_head": manifest_head,
        "status_lines": status_lines,
        "editor_local_status_lines": editor_local_lines,
        "editor_local_prefixes": list(EDITOR_LOCAL_PREFIXES),
        "unstaged_files": unstaged_files,
        "staged_files": staged_files,
        "run_ignore_rule": ignore_rule or None,
        "run_ignore_target": RUN_IGNORE_TARGET,
        "run_dir_relative": RUN_IGNORE_TARGET + "/" + RUN_ROOT.name,
    }
    return evidence, violations


def main() -> int:
    """Collect the git evidence, write checks/output_boundary.json, report."""
    evidence, violations = collect()
    payload: dict[str, Any] = {
        "check": "output_boundary",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rule": "本次 run 只允许写入 Qwen-Harness/runtime/runs/<run-id>/，仓库其余部分保持只读且不得产生提交",
        "authority": "git（工作树状态 + .gitignore 规则 + 与 run_manifest.json 的 HEAD/分支比对）",
        "passed": not violations,
        "violations": violations,
        **evidence,
    }
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    (CHECKS_DIR / "output_boundary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for item in violations:
        print(f"FAIL {item}")
    print(f"branch={evidence['branch']} head={evidence['head'][:12]} status_lines={len(evidence['status_lines'])}")
    print(f"ignore_rule={evidence['run_ignore_rule']}")
    passed = not violations
    print(f"OUTPUT_BOUNDARY_PASSED={str(passed).lower()}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
