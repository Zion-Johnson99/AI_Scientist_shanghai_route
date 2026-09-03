"""ModuleAdapter 基类与共享工具（设计文档 01 §15.1）。

四个模块 Adapter 共享这里的工具：当前 run 生成源码边界、数据文件哈希、
固定命令执行（经 ``SafeSubprocessRunner`` 审计）与
``CommandAudit -> ModuleResult`` 汇总。子类必须实现
``preflight / snapshot / execute / validate`` 四个契约方法。

纪律（设计文档 §15、轮 2 施工要求）：

- 预检与快照只读仓库现有数据文件，绝不执行模块命令。
- 需要执行命令但未获授权或处于离线模式时，返回 ``status="skipped"``
  的 :class:`ModuleResult` 并写明原因，绝不伪造数据。
- Adapter 不复制任何模块业务算法，只通过固定命令或文件读取调用模块。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from ..errors import InputContractError
from ..logging_utils import get_logger
from ..models import CommandAudit, ModuleResult
from ..provenance import sha256_file
from ..subprocess_runner import CommandSpec, SafeSubprocessRunner
from .project_paths import GeneratedProjectPaths

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..models import ModuleOperation
    from ..workflow.engine import WorkflowContext

LOGGER = get_logger("adapters")

#: 输出产物相对路径中允许的字符（避免把操作参数直接拼进文件名）。
_SAFE_LABEL_RE = re.compile(r"[^a-z0-9_-]+")


class ModuleAdapter:
    """四模块 Adapter 的公共基类。

    子类需要覆盖类属性 :attr:`module`（route/environment/evaluation/web）
    并实现四个契约方法；直接调用基类方法会抛出
    :class:`NotImplementedError`，注册表在导入时校验方法存在。
    """

    #: 模块键，子类必须覆盖为 ``route``/``environment``/``evaluation``/``web``。
    module: str = ""

    #: 该 Adapter 能处理的操作 ID -> 说明，子类覆盖。
    supported_operations: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.__class__.__name__

    # -- 契约方法（子类必须覆盖） -------------------------------------------
    def preflight(self, context: "WorkflowContext") -> ModuleResult:
        raise NotImplementedError(f"{self.name} 未实现 preflight")

    def snapshot(self, context: "WorkflowContext") -> ModuleResult:
        raise NotImplementedError(f"{self.name} 未实现 snapshot")

    def execute(self, operation: "ModuleOperation", context: "WorkflowContext") -> ModuleResult:
        raise NotImplementedError(f"{self.name} 未实现 execute")

    def validate(self, context: "WorkflowContext") -> ModuleResult:
        raise NotImplementedError(f"{self.name} 未实现 validate")

    # -- 路径与文件工具 -------------------------------------------------------
    def project_file(self, path: Path, label: str) -> Path:
        """要求生成工程视图中的固定文件存在。"""
        if not path.is_file():
            raise InputContractError(
                f"{label} 缺失: {path}",
                suggested_action=f"修复当前 run 生成源码中的 {label}",
            )
        return path

    @staticmethod
    def optional_project_file(path: Path) -> Path | None:
        """生成工程文件存在时返回路径。"""
        return path if path.is_file() else None

    def read_json(self, path: Path, label: str) -> Any:
        """读取并解析 JSON 文件，失败时抛出契约错误。"""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InputContractError(
                f"{label} 无法读取或解析: {path.name}: {exc}",
                suggested_action=f"修复 {label} 的 JSON 内容或恢复该文件",
            ) from exc

    def repo_relative(self, context: "WorkflowContext", path: Path) -> str:
        """把绝对路径转换为本 run 生成源码根相对路径。"""
        try:
            return (
                path.resolve()
                .relative_to(self.project_paths(context).source_root.resolve())
                .as_posix()
            )
        except ValueError:
            return path.name

    def hash_files(self, paths: Iterable[Path]) -> dict[str, str]:
        """对存在的文件计算 SHA256，键为仓库相对路径。"""
        hashes: dict[str, str] = {}
        for path in paths:
            if path.is_file():
                hashes[self._hash_key(path)] = sha256_file(path)
        return hashes

    def _hash_key(self, path: Path) -> str:
        return path.name

    # -- ModuleResult 组装 ----------------------------------------------------
    def result(
        self,
        status: str,
        *,
        input_artifacts: Iterable[str] = (),
        output_artifacts: Iterable[str] = (),
        data_hashes: dict[str, str] | None = None,
        commands: Iterable[CommandAudit] = (),
        warnings: Iterable[str] = (),
        errors: Iterable[str] = (),
    ) -> ModuleResult:
        """把路径、哈希与命令审计汇总为 :class:`ModuleResult`。"""
        return ModuleResult(
            module=self.module,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            input_artifacts=list(input_artifacts),
            output_artifacts=list(output_artifacts),
            data_hashes=dict(data_hashes or {}),
            commands=list(commands),
            warnings=list(warnings),
            errors=list(errors),
        )

    def skipped(self, reason: str, **kwargs: Any) -> ModuleResult:
        """未获授权或离线无法执行时的诚实降级：记录原因、不伪造数据。"""
        warnings = [reason, *kwargs.pop("warnings", [])]
        return self.result("skipped", warnings=warnings, **kwargs)

    def unknown_operation(self, operation: "ModuleOperation") -> ModuleResult:
        """未知操作 ID 一律显式失败，避免静默忽略。"""
        supported = ", ".join(self.supported_operations) or "（无）"
        return self.result(
            "error",
            errors=[
                f"操作 {operation.operation_id} 不在 {self.name} 支持范围内（支持: {supported}）"
            ],
        )

    # -- 固定命令执行 ----------------------------------------------------------
    def commands_allowed(self, context: "WorkflowContext") -> bool:
        """离线模式禁止执行任何模块命令（只读文件操作不受影响）。"""
        return not context.options.offline

    def subprocess_runner(self, context: "WorkflowContext") -> SafeSubprocessRunner:
        return SafeSubprocessRunner(context.paths.repo_root, context.paths.runtime_root)

    def run_fixed_command(
        self,
        context: "WorkflowContext",
        command_id: str,
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: int = 900,
    ) -> CommandAudit:
        """经 SafeSubprocessRunner 执行固定命令（白名单可执行文件、shell=False）。"""
        spec = CommandSpec(
            command_id=command_id,
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
        audit = self.subprocess_runner(context).run(spec, run_store=context.store)
        LOGGER.info(
            "模块 %s 固定命令 %s 完成（退出码 %s）", self.module, command_id, audit.exit_code
        )
        return audit

    def project_paths(self, context: "WorkflowContext") -> GeneratedProjectPaths:
        """返回当前 run 的生成源码路径视图。"""
        return GeneratedProjectPaths.from_context(context)

    @staticmethod
    def safe_label(raw: object, fallback: str) -> str:
        """把操作参数里的标签规范化为文件名片段。"""
        if not isinstance(raw, str):
            return fallback
        cleaned = _SAFE_LABEL_RE.sub("_", raw.strip().lower()).strip("_")
        return cleaned[:32] or fallback
