"""Safe subprocess execution with fixed command templates.

Security model:
- Only pre-registered operation IDs are allowed.
- Each operation maps to a fixed command template with typed placeholders.
- No shell string concatenation; all commands run via subprocess with list argv.
- Every execution is recorded as a CommandAudit entry.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ExecutionError(Exception):
    """Raised when a command execution fails or is rejected."""

    def __init__(
        self,
        message: str,
        *,
        operation_id: str | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation_id = operation_id
        self.returncode = returncode
        self.stderr = stderr


class OperationStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass
class CommandAudit:
    """Audit record for a single subprocess execution."""

    operation_id: str
    command: list[str]
    status: OperationStatus
    started_at: float
    finished_at: float
    returncode: int | None = None
    stdout_sha256: str | None = None
    stderr_truncated: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "command": self.command,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "returncode": self.returncode,
            "stdout_sha256": self.stdout_sha256,
            "stderr_truncated": self.stderr_truncated,
            "error_message": self.error_message,
        }


@dataclass
class CommandTemplate:
    """A fixed command template with typed parameter placeholders.

    Parameters are substituted positionally; no free-form shell injection.
    """

    operation_id: str
    executable: str
    args_template: list[str]
    description: str
    allowed_params: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 120.0

    def build_argv(self, params: dict[str, str]) -> list[str]:
        """Build the final argv list from validated parameters.

        Raises ExecutionError if required parameters are missing or
        unexpected parameters are provided.
        """
        # Validate parameter names
        unknown = set(params.keys()) - set(self.allowed_params.keys())
        if unknown:
            raise ExecutionError(
                f"Unknown parameters for operation '{self.operation_id}': "
                f"{sorted(unknown)}. Allowed: {sorted(self.allowed_params.keys())}",
                operation_id=self.operation_id,
            )

        missing = set(self.allowed_params.keys()) - set(params.keys())
        if missing:
            raise ExecutionError(
                f"Missing parameters for operation '{self.operation_id}': "
                f"{sorted(missing)}. Required: {sorted(self.allowed_params.keys())}",
                operation_id=self.operation_id,
            )

        argv = [self.executable]
        for arg in self.args_template:
            if arg.startswith("{") and arg.endswith("}"):
                param_name = arg[1:-1]
                if param_name not in params:
                    raise ExecutionError(
                        f"Template parameter '{param_name}' not provided "
                        f"for operation '{self.operation_id}'",
                        operation_id=self.operation_id,
                    )
                argv.append(params[param_name])
            else:
                argv.append(arg)
        return argv


def _build_registry() -> dict[str, CommandTemplate]:
    """Build the pre-registered command template registry.

    Only these operations are allowed. Adding new operations requires
    explicit code changes here.
    """
    templates: list[CommandTemplate] = [
        # --- uv operations ---
        CommandTemplate(
            operation_id="uv_sync",
            executable="uv",
            args_template=["sync", "--directory", "{directory}"],
            description="Sync dependencies for a project directory",
            allowed_params={"directory": "path"},
            timeout_seconds=300.0,
        ),
        CommandTemplate(
            operation_id="uv_run_pytest",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--extra", "dev", "pytest", "-q",
            ],
            description="Run pytest in a project directory",
            allowed_params={"directory": "path"},
            timeout_seconds=300.0,
        ),
        CommandTemplate(
            operation_id="uv_run_ruff_check",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--extra", "dev", "ruff", "check", ".",
            ],
            description="Run ruff lint check in a project directory",
            allowed_params={"directory": "path"},
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="uv_run_ruff_format_check",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--extra", "dev", "ruff", "format", "--check", ".",
            ],
            description="Run ruff format check in a project directory",
            allowed_params={"directory": "path"},
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="uv_run_cli",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "{command_name}",
            ],
            description="Run a registered CLI command in a project directory",
            allowed_params={"directory": "path", "command_name": "string"},
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="uv_run_cli_with_args",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "{command_name}",
            ],
            description="Run a registered CLI command with additional arguments",
            allowed_params={"directory": "path", "command_name": "string"},
            timeout_seconds=120.0,
        ),
        # --- python operations ---
        CommandTemplate(
            operation_id="python_script",
            executable="python",
            args_template=["{script_path}"],
            description="Run a Python script by path",
            allowed_params={"script_path": "path"},
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="python_module",
            executable="python",
            args_template=["-m", "{module_name}"],
            description="Run a Python module",
            allowed_params={"module_name": "string"},
            timeout_seconds=120.0,
        ),
        # --- node operations ---
        CommandTemplate(
            operation_id="node_test",
            executable="node",
            args_template=["--test", "{test_path}"],
            description="Run Node.js built-in test runner on a test file",
            allowed_params={"test_path": "path"},
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="node_test_glob",
            executable="node",
            args_template=["--test", "{test_dir}"],
            description="Run Node.js test runner on a directory",
            allowed_params={"test_dir": "path"},
            timeout_seconds=120.0,
        ),
        # --- git operations ---
        CommandTemplate(
            operation_id="git_status",
            executable="git",
            args_template=["status", "--porcelain"],
            description="Check git working tree status",
            allowed_params={},
            timeout_seconds=30.0,
        ),
        CommandTemplate(
            operation_id="git_rev_parse_head",
            executable="git",
            args_template=["rev-parse", "HEAD"],
            description="Get current HEAD commit hash",
            allowed_params={},
            timeout_seconds=30.0,
        ),
        CommandTemplate(
            operation_id="git_branch_show_current",
            executable="git",
            args_template=["branch", "--show-current"],
            description="Get current branch name",
            allowed_params={},
            timeout_seconds=30.0,
        ),
        CommandTemplate(
            operation_id="git_diff_stat",
            executable="git",
            args_template=["diff", "--stat"],
            description="Show diff statistics",
            allowed_params={},
            timeout_seconds=30.0,
        ),
        # --- evaluation module specific ---
        CommandTemplate(
            operation_id="evaluation_score_candidates",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "evaluation-model-qwen",
                "score-candidates",
                "--profile", "{profile_path}",
                "--weights", "{weights_path}",
                "--route-catalog", "{route_catalog_path}",
                "--environment-dashboard", "{environment_dashboard_path}",
                "--json",
            ],
            description="Run evaluation score-candidates command",
            allowed_params={
                "directory": "path",
                "profile_path": "path",
                "weights_path": "path",
                "route_catalog_path": "path",
                "environment_dashboard_path": "path",
            },
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="evaluation_recommend_offline",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "evaluation-model-qwen",
                "recommend",
                "--profile", "{profile_path}",
                "--offline", "--json",
            ],
            description="Run evaluation recommend command in offline mode",
            allowed_params={"directory": "path", "profile_path": "path"},
            timeout_seconds=120.0,
        ),
        CommandTemplate(
            operation_id="evaluation_api_check",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "evaluation-model-qwen",
                "api-check",
            ],
            description="Check evaluation API availability",
            allowed_params={"directory": "path"},
            timeout_seconds=30.0,
        ),
        # --- weather module specific ---
        CommandTemplate(
            operation_id="weather_config_check",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "weather-api-data",
                "config-check",
            ],
            description="Check weather API configuration",
            allowed_params={"directory": "path"},
            timeout_seconds=30.0,
        ),
        CommandTemplate(
            operation_id="weather_dry_run",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "weather-api-data",
                "dry-run",
            ],
            description="Dry-run weather pipeline without API calls",
            allowed_params={"directory": "path"},
            timeout_seconds=60.0,
        ),
        CommandTemplate(
            operation_id="weather_publish_web",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "weather-api-data",
                "publish-web",
            ],
            description="Publish environment dashboard to web data directory",
            allowed_params={"directory": "path"},
            timeout_seconds=60.0,
        ),
        # --- route module specific ---
        CommandTemplate(
            operation_id="route_validate_seeds",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "xuhui-route-builder",
                "validate-seeds",
            ],
            description="Validate route seed data",
            allowed_params={"directory": "path"},
            timeout_seconds=60.0,
        ),
        CommandTemplate(
            operation_id="route_validate_routes",
            executable="uv",
            args_template=[
                "run", "--directory", "{directory}",
                "--frozen", "xuhui-route-builder",
                "validate-routes",
            ],
            description="Validate routes (may require network)",
            allowed_params={"directory": "path"},
            timeout_seconds=120.0,
        ),
    ]
    return {t.operation_id: t for t in templates}


# Module-level registry (built once at import time)
_COMMAND_REGISTRY: dict[str, CommandTemplate] = _build_registry()


def get_registry() -> dict[str, CommandTemplate]:
    """Return a copy of the command registry for inspection."""
    return dict(_COMMAND_REGISTRY)


def list_operations() -> list[str]:
    """Return sorted list of all registered operation IDs."""
    return sorted(_COMMAND_REGISTRY.keys())


class SafeSubprocessRunner:
    """Executes commands only through pre-registered operation templates.

    Security guarantees:
    - Only operation IDs in the registry are accepted.
    - Commands are built as argv lists, never shell strings.
    - Parameters are validated against the template's allowed_params.
    - Every execution (success or failure) produces a CommandAudit.
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self._repo_root = repo_root or Path.cwd()
        self._dry_run = dry_run
        self._audit_log: list[CommandAudit] = []

    @property
    def audit_log(self) -> list[CommandAudit]:
        """Return all audit records from this runner instance."""
        return list(self._audit_log)

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def _validate_path_within_repo(self, path_str: str) -> None:
        """Ensure a path parameter resolves within the repository root."""
        try:
            resolved = Path(path_str).resolve()
        except (OSError, ValueError) as exc:
            raise ExecutionError(
                f"Invalid path: {path_str!r} ({exc})"
            ) from exc

        try:
            resolved.relative_to(self._repo_root.resolve())
        except ValueError:
            raise ExecutionError(
                f"Path escapes repository boundary: {path_str!r} "
                f"resolves to {resolved} which is outside {self._repo_root.resolve()}"
            )

    def _validate_params(self, template: CommandTemplate, params: dict[str, str]) -> None:
        """Validate parameters against the template's type declarations."""
        for param_name, param_type in template.allowed_params.items():
            if param_name not in params:
                continue
            value = params[param_name]
            if param_type == "path":
                self._validate_path_within_repo(value)
            elif param_type == "string":
                # Reject shell metacharacters in string params
                shell_chars = set(";&|`$(){}[]!<>\\\n\r")
                found = shell_chars.intersection(set(value))
                if found:
                    raise ExecutionError(
                        f"Parameter '{param_name}' contains forbidden characters: "
                        f"{sorted(found)}",
                        operation_id=template.operation_id,
                    )

    def execute(
        self,
        operation_id: str,
        params: dict[str, str] | None = None,
        *,
        timeout_override: float | None = None,
    ) -> CommandAudit:
        """Execute a pre-registered operation.

        Args:
            operation_id: Must be a key in the command registry.
            params: Parameters matching the template's allowed_params.
            timeout_override: Override the template's default timeout.

        Returns:
            CommandAudit record for this execution.

        Raises:
            ExecutionError: If the operation is not registered, parameters
                are invalid, or the command fails.
        """
        params = params or {}

        # Check operation is registered
        if operation_id not in _COMMAND_REGISTRY:
            audit = CommandAudit(
                operation_id=operation_id,
                command=[],
                status=OperationStatus.REJECTED,
                started_at=time.time(),
                finished_at=time.time(),
                error_message=(
                    f"Operation '{operation_id}' is not registered. "
                    f"Available operations: {list_operations()}"
                ),
            )
            self._audit_log.append(audit)
            raise ExecutionError(
                audit.error_message or "Unknown operation",
                operation_id=operation_id,
            )

        template = _COMMAND_REGISTRY[operation_id]

        # Validate parameters
        try:
            self._validate_params(template, params)
            argv = template.build_argv(params)
        except ExecutionError as exc:
            audit = CommandAudit(
                operation_id=operation_id,
                command=[],
                status=OperationStatus.REJECTED,
                started_at=time.time(),
                finished_at=time.time(),
                error_message=str(exc),
            )
            self._audit_log.append(audit)
            raise

        timeout = timeout_override or template.timeout_seconds

        # Dry run mode: record but don't execute
        if self._dry_run:
            audit = CommandAudit(
                operation_id=operation_id,
                command=argv,
                status=OperationStatus.SUCCESS,
                started_at=time.time(),
                finished_at=time.time(),
                returncode=0,
                error_message="dry_run: command not executed",
            )
            self._audit_log.append(audit)
            return audit

        # Execute
        started_at = time.time()
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._repo_root),
                shell=False,  # Explicit: never use shell
            )
        except subprocess.TimeoutExpired:
            finished_at = time.time()
            audit = CommandAudit(
                operation_id=operation_id,
                command=argv,
                status=OperationStatus.TIMEOUT,
                started_at=started_at,
                finished_at=finished_at,
                returncode=None,
                error_message=f"Command timed out after {timeout}s",
            )
            self._audit_log.append(audit)
            raise ExecutionError(
                f"Operation '{operation_id}' timed out after {timeout}s",
                operation_id=operation_id,
            )
        except OSError as exc:
            finished_at = time.time()
            audit = CommandAudit(
                operation_id=operation_id,
                command=argv,
                status=OperationStatus.FAILURE,
                started_at=started_at,
                finished_at=finished_at,
                returncode=None,
                error_message=f"OS error: {exc}",
            )
            self._audit_log.append(audit)
            raise ExecutionError(
                f"Operation '{operation_id}' failed with OS error: {exc}",
                operation_id=operation_id,
            )

        finished_at = time.time()
        stdout_hash = (
            hashlib.sha256(result.stdout.encode()).hexdigest()
            if result.stdout
            else None
        )
        stderr_truncated = (
            result.stderr[:500] if result.stderr else None
        )

        if result.returncode == 0:
            status = OperationStatus.SUCCESS
        else:
            status = OperationStatus.FAILURE

        audit = CommandAudit(
            operation_id=operation_id,
            command=argv,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            returncode=result.returncode,
            stdout_sha256=stdout_hash,
            stderr_truncated=stderr_truncated,
        )
        self._audit_log.append(audit)

        if result.returncode != 0:
            raise ExecutionError(
                f"Operation '{operation_id}' exited with code {result.returncode}",
                operation_id=operation_id,
                returncode=result.returncode,
                stderr=stderr_truncated,
            )

        return audit

    def execute_json(
        self,
        operation_id: str,
        params: dict[str, str] | None = None,
        *,
        timeout_override: float | None = None,
    ) -> Any:
        """Execute an operation and parse stdout as JSON.

        Raises ExecutionError if the command fails or stdout is not valid JSON.
        """
        params = params or {}

        if operation_id not in _COMMAND_REGISTRY:
            raise ExecutionError(
                f"Operation '{operation_id}' is not registered.",
                operation_id=operation_id,
            )

        template = _COMMAND_REGISTRY[operation_id]
        self._validate_params(template, params)
        argv = template.build_argv(params)
        timeout = timeout_override or template.timeout_seconds

        if self._dry_run:
            return {}

        started_at = time.time()
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._repo_root),
                shell=False,
            )
        except subprocess.TimeoutExpired:
            audit = CommandAudit(
                operation_id=operation_id,
                command=argv,
                status=OperationStatus.TIMEOUT,
                started_at=started_at,
                finished_at=time.time(),
                error_message=f"Command timed out after {timeout}s",
            )
            self._audit_log.append(audit)
            raise ExecutionError(
                f"Operation '{operation_id}' timed out after {timeout}s",
                operation_id=operation_id,
            )

        finished_at = time.time()
        stdout_hash = (
            hashlib.sha256(result.stdout.encode()).hexdigest()
            if result.stdout
            else None
        )

        if result.returncode != 0:
            audit = CommandAudit(
                operation_id=operation_id,
                command=argv,
                status=OperationStatus.FAILURE,
                started_at=started_at,
                finished_at=finished_at,
                returncode=result.returncode,
                stdout_sha256=stdout_hash,
                stderr_truncated=result.stderr[:500] if result.stderr else None,
            )
            self._audit_log.append(audit)
            raise ExecutionError(
                f"Operation '{operation_id}' exited with code {result.returncode}",
                operation_id=operation_id,
                returncode=result.returncode,
                stderr=result.stderr[:500] if result.stderr else None,
            )

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            audit = CommandAudit(
                operation_id=operation_id,
                command=argv,
                status=OperationStatus.FAILURE,
                started_at=started_at,
                finished_at=finished_at,
                returncode=result.returncode,
                stdout_sha256=stdout_hash,
                error_message=f"stdout is not valid JSON: {exc}",
            )
            self._audit_log.append(audit)
            raise ExecutionError(
                f"Operation '{operation_id}' produced invalid JSON output: {exc}",
                operation_id=operation_id,
                returncode=result.returncode,
            )

        audit = CommandAudit(
            operation_id=operation_id,
            command=argv,
            status=OperationStatus.SUCCESS,
            started_at=started_at,
            finished_at=finished_at,
            returncode=result.returncode,
            stdout_sha256=stdout_hash,
        )
        self._audit_log.append(audit)
        return parsed

    def clear_audit_log(self) -> list[CommandAudit]:
        """Clear and return the audit log (for periodic flushing)."""
        log = self._audit_log
        self._audit_log = []
        return log
