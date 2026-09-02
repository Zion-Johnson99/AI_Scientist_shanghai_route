"""Typed error hierarchy for Qwen-Harness.

Every error carries a stable ``error_type``, a CLI ``exit_code`` (see design
doc section 5.3) and a human readable ``suggested_action`` so the CLI can emit
machine parseable diagnostics without ever leaking secrets.

Exit code mapping:
    0 success / 1 gate failed or unsupported-but-complete / 2 config or input
    contract error / 3 model or external source failure without fallback /
    4 module command failure / 5 run state corruption or recovery failure.
"""

from __future__ import annotations

from typing import Any


class HarnessError(Exception):
    """Base class for all harness errors."""

    error_type: str = "harness_error"
    exit_code: int = 5
    default_suggestion: str = "查看运行目录中的 events.jsonl 与日志，修复后重试"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        run_id: str | None = None,
        suggested_action: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.run_id = run_id
        self.suggested_action = suggested_action or self.default_suggestion
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "run_id": self.run_id,
            "stage": self.stage,
            "suggested_action": self.suggested_action,
            "exit_code": self.exit_code,
            "details": self.details,
        }


class ConfigError(HarnessError):
    """Configuration files, environment variables or CLI input are invalid."""

    error_type = "config_error"
    exit_code = 2
    default_suggestion = "检查 config/*.json、.env 与命令行参数后重试"


class InputContractError(HarnessError):
    """Input data violates a frozen JSON/model contract."""

    error_type = "input_contract_error"
    exit_code = 2
    default_suggestion = "核对输入文件字段与 schemas/ 中的契约定义"


class PathBoundaryError(ConfigError):
    """A resolved path escapes the repository or runtime boundary."""

    error_type = "path_boundary_error"
    default_suggestion = "路径必须位于仓库根目录或 runtime 目录内"


class SkillError(ConfigError):
    """Skill discovery, parsing or snapshot failed."""

    error_type = "skill_error"
    default_suggestion = "运行 `qwen-harness validate --scope skills` 定位问题技能"


class ModelUnavailableError(HarnessError):
    """Model API unavailable and no offline fallback applies."""

    error_type = "model_unavailable"
    exit_code = 3
    retryable = True
    default_suggestion = "检查 .env 中的 DASHSCOPE_API_KEY / DASHSCOPE_BASE_URL，或使用 --offline 复现"


class SourceUnavailableError(HarnessError):
    """External source failed and no cached fallback exists."""

    error_type = "source_unavailable"
    exit_code = 3
    retryable = True
    default_suggestion = "稍后重试，或改用本地来源 / --offline 固定夹具"


class ModuleCommandError(HarnessError):
    """A fixed module command failed."""

    error_type = "module_command_failed"
    exit_code = 4
    retryable = True
    default_suggestion = "查看运行目录 commands/ 下的 stdout/stderr，修复模块环境后重跑该阶段"


class GateFailure(HarnessError):
    """A quality gate rejected the artifacts (run completed)."""

    error_type = "gate_failed"
    exit_code = 1
    default_suggestion = "查看 gate 检查明细，修正证据、指标或发布内容"


class ApprovalPendingError(HarnessError):
    """A stage requires approval that was not granted in this mode."""

    error_type = "approval_pending"
    exit_code = 1
    default_suggestion = "使用 --approval-mode auto，或提供对应显式授权参数（如 --publish-web）"


class RunStateError(HarnessError):
    """Run state is corrupted, locked or cannot be resumed."""

    error_type = "run_state_error"
    default_suggestion = "检查 runtime/runs/<run-id>/state.json 与 lock.json；必要时新建 run"
