"""Fixed-command subprocess runner (design doc section 14).

Only allowlisted executables (uv / python / node / git) may run, always as
argv lists with ``shell=False``. Working directories and declared write paths
must stay inside the repository or the runtime root. stdout/stderr are
captured to disk under the run directory and secrets are redacted from logs.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from .errors import InputContractError, ModuleCommandError
from .logging_utils import get_logger, log_event
from .models import CommandAudit, StrictModel

LOGGER = get_logger("subprocess")

#: Frozen executable allowlist (matched by basename without extension).
ALLOWED_EXECUTABLES = ("uv", "python", "node", "git")

#: Environment variable name fragments whose values must never reach logs.
_SENSITIVE_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")

_STRIP_EXTENSIONS = (".exe", ".cmd", ".bat", ".com")
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_POST_KILL_WAIT_SECONDS = 15


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CommandSpec(StrictModel):
    """A single fixed command the platform may execute."""

    command_id: str
    argv: list[str] = Field(min_length=1)
    cwd: Path
    timeout_seconds: int = Field(default=900, ge=1, le=7200)
    allowed_exit_codes: set[int] = Field(default_factory=lambda: {0})
    env_overrides: dict[str, str] = Field(default_factory=dict)
    writes: list[Path] = Field(default_factory=list)


class SafeSubprocessRunner:
    """Executes CommandSpecs under the section-14 safety contract."""

    def __init__(self, repo_root: Path, runtime_root: Path, default_timeout: int = 900) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.runtime_root = Path(runtime_root).resolve()
        self.default_timeout = default_timeout

    # -- boundary enforcement ---------------------------------------------
    def _within_boundary(self, path: Path | str, label: str) -> Path:
        resolved = Path(path).resolve()
        for base in (self.repo_root, self.runtime_root):
            try:
                resolved.relative_to(base)
            except ValueError:
                continue
            else:
                return resolved
        raise InputContractError(
            f"{label} 越界: {resolved} 必须位于仓库根目录或 runtime 目录内",
            details={"label": label, "resolved": str(resolved)},
            suggested_action="收缩命令的工作目录/写入路径到仓库范围内",
        )

    def _resolve_executable(self, argv0: str) -> str:
        base = Path(argv0).name.lower()
        for ext in _STRIP_EXTENSIONS:
            if base.endswith(ext):
                base = base[: -len(ext)]
                break
        if base not in ALLOWED_EXECUTABLES:
            raise InputContractError(
                f"可执行文件 {argv0!r} 不在白名单内: {', '.join(ALLOWED_EXECUTABLES)}",
                suggested_action="仅允许固定命令（uv/python/node/git），修正模块命令配置",
            )
        resolved = shutil.which(argv0)
        if resolved is None:
            raise ModuleCommandError(
                f"可执行文件 {argv0!r} 未安装或不在 PATH 中",
                suggested_action="安装对应工具链（如 uv）后重试",
            )
        return resolved

    def _redacted_env_log(self, env: dict[str, str]) -> dict[str, str]:
        redacted: dict[str, str] = {}
        for key, value in env.items():
            upper = key.upper()
            if any(marker in upper for marker in _SENSITIVE_MARKERS) and value:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = value
        return redacted

    # -- execution ----------------------------------------------------------
    def run(self, spec: CommandSpec, run_store: object | None = None) -> CommandAudit:
        """Run the command; raise ModuleCommandError on timeout/bad exit."""
        cwd = self._within_boundary(spec.cwd, "cwd")
        for write_path in spec.writes:
            self._within_boundary(write_path, f"writes[{write_path}]")
        executable = self._resolve_executable(spec.argv[0])

        if run_store is not None:
            log_root = Path(getattr(run_store, "run_dir")) / "commands"  # type: ignore[arg-type]
        else:
            log_root = self.runtime_root / "commands"
        log_root.mkdir(parents=True, exist_ok=True)
        safe_id = _SANITIZE_RE.sub("_", spec.command_id)[:64] or "command"
        suffix = uuid.uuid4().hex[:8]
        stdout_path = log_root / f"{safe_id}.{suffix}.stdout.log"
        stderr_path = log_root / f"{safe_id}.{suffix}.stderr.log"

        env = os.environ.copy()
        env.update(spec.env_overrides)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        timeout = spec.timeout_seconds or self.default_timeout
        started_at = _utc_now()
        started_perf = time.perf_counter()

        popen_kwargs: dict[str, object] = {
            "shell": False,
            "cwd": str(cwd),
            "env": env,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        log_event(
            LOGGER,
            logging.INFO,
            f"执行固定命令 {spec.command_id}: {' '.join(spec.argv)}",
            operation="subprocess_run",
            status="started",
        )

        timed_out = False
        with (
            stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file,
            stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_file,
        ):
            process = subprocess.Popen(
                [executable, *spec.argv[1:]],
                stdout=stdout_file,
                stderr=stderr_file,
                **popen_kwargs,  # type: ignore[arg-type]
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                try:
                    process.wait(timeout=_POST_KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:  # pragma: no cover - extreme case
                    LOGGER.warning("命令 %s 超时后仍无法终止", spec.command_id)
        elapsed_ms = (time.perf_counter() - started_perf) * 1000.0
        finished_at = _utc_now()
        exit_code = process.returncode if process.returncode is not None else -1

        audit = CommandAudit(
            command_id=spec.command_id,
            argv=list(spec.argv),
            cwd=str(cwd),
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            timeout=timed_out,
        )

        env_summary = self._redacted_env_log(spec.env_overrides)
        if timed_out or exit_code not in spec.allowed_exit_codes:
            reason = f"超时（>{timeout}s）" if timed_out else f"退出码 {exit_code}"
            log_event(
                LOGGER,
                logging.ERROR,
                f"命令 {spec.command_id} 失败: {reason}",
                operation="subprocess_run",
                status="failed",
                elapsed_ms=elapsed_ms,
            )
            raise ModuleCommandError(
                f"固定命令 {spec.command_id} 失败: {reason}",
                details={
                    "command_id": spec.command_id,
                    "argv": list(spec.argv),
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "env_overrides": env_summary,
                },
                suggested_action="查看 commands/ 下的 stdout/stderr 日志，修复模块环境后重跑",
            )
        log_event(
            LOGGER,
            logging.INFO,
            f"命令 {spec.command_id} 完成（退出码 {exit_code}）",
            operation="subprocess_run",
            status="ok",
            elapsed_ms=elapsed_ms,
        )
        return audit
