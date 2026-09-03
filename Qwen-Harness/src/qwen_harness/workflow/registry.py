"""Handler registry: lazy resolution of ``"module:function"`` references.

Workflow JSON files reference each stage handler as a ``"module:function"``
string (e.g. ``"qwen_harness.workflow.stages:initialize_stage"``). Resolution
happens only when the stage executes, via :mod:`importlib`, so the engine
never imports second-round packages (agents/sources/adapters) at startup.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Callable

from ..config import load_workflow_file
from ..errors import ConfigError, InputContractError
from ..logging_utils import get_logger
from ..models import WorkflowConfig

logger = get_logger("workflow.registry")

HandlerRef = str
StageHandler = Callable[..., Any]

_HANDLER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


class HandlerRegistry:
    """Resolves and caches ``"module:function"`` handler references."""

    def __init__(self) -> None:
        self._cache: dict[str, StageHandler] = {}

    @staticmethod
    def validate_reference(reference: str) -> None:
        if not isinstance(reference, str) or not _HANDLER_RE.match(reference):
            raise ConfigError(
                f"handler 必须形如 '模块:函数': {reference!r}",
                suggested_action="示例: 'qwen_harness.workflow.stages:initialize_stage'",
            )

    def resolve(self, reference: str) -> StageHandler:
        """Import the target module lazily and return the handler callable."""
        if reference in self._cache:
            return self._cache[reference]
        self.validate_reference(reference)
        module_name, func_name = reference.split(":", 1)
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise InputContractError(
                f"阶段处理模块不可用: {module_name}",
                details={"missing_module": module_name},
                suggested_action="确认该模块已实现；离线复现同样需要全部阶段处理模块存在",
            ) from exc
        except ImportError as exc:
            raise InputContractError(
                f"阶段处理模块导入失败: {module_name}: {exc}",
                suggested_action="运行 'qwen-harness doctor' 检查依赖",
            ) from exc
        handler = getattr(module, func_name, None)
        if handler is None or not callable(handler):
            raise InputContractError(
                f"模块 {module_name} 中不存在可调用函数 {func_name}",
                suggested_action="检查阶段冻结映射中的函数名",
            )
        self._cache[reference] = handler
        return handler

    def clear(self) -> None:
        self._cache.clear()


def load_workflow(workflows_dir: Path, name: str) -> WorkflowConfig:
    """Load and validate ``config/workflows/<name>.json``."""
    workflow = load_workflow_file(Path(workflows_dir), name)
    _validate_stage_graph(workflow)
    return workflow


def _validate_stage_graph(workflow: WorkflowConfig) -> None:
    names = [stage.name for stage in workflow.stages]
    seen: set[str] = set()
    for stage in workflow.stages:
        if stage.name in seen:
            raise ConfigError(f"工作流 {workflow.name} 阶段名重复: {stage.name}")
        seen.add(stage.name)
        HandlerRegistry.validate_reference(stage.handler)
    for stage in workflow.stages:
        for dep in stage.dependencies:
            if dep not in seen:
                raise ConfigError(
                    f"工作流 {workflow.name} 阶段 {stage.name} 依赖不存在的阶段 {dep!r}"
                )
            if names.index(dep) >= names.index(stage.name):
                raise ConfigError(
                    f"工作流 {workflow.name} 阶段 {stage.name} 依赖其后定义的阶段 {dep!r}"
                )
