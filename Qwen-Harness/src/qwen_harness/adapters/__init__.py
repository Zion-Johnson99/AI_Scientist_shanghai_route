"""四模块 Adapter 注册表（设计文档 01 §15）。

本包实现 RouteBuilderAdapter / EnvironmentDataAdapter /
EvaluationModelAdapter / WebProductAdapter，并在导入时通过
:func:`register_adapter` 注册到 :data:`ADAPTERS`。``workflow.stages`` 在
执行 ``module_preflight`` / ``module_execution`` 阶段时惰性导入本模块。
"""

from __future__ import annotations

from typing import Any

#: 模块键 -> Adapter 实例。键集合冻结为四个项目模块。
ADAPTERS: dict[str, Any] = {}

#: 每个 Adapter 必须实现的方法（设计文档 §15.1 基类）。
REQUIRED_ADAPTER_METHODS: tuple[str, ...] = ("preflight", "snapshot", "execute", "validate")

_VALID_MODULE_KEYS = ("route", "environment", "evaluation", "web")


def register_adapter(module_key: str, adapter: Any) -> Any:
    """把 Adapter 注册进 :data:`ADAPTERS`，注册前校验模块键与必需方法。"""
    if module_key not in _VALID_MODULE_KEYS:
        raise ValueError(f"未知模块键: {module_key!r}（允许: {', '.join(_VALID_MODULE_KEYS)}）")
    missing = [
        name for name in REQUIRED_ADAPTER_METHODS if not callable(getattr(adapter, name, None))
    ]
    if missing:
        raise ValueError(f"模块 {module_key} 的 Adapter 缺少方法: {', '.join(missing)}")
    ADAPTERS[module_key] = adapter
    return adapter


def _register_builtin_adapters() -> None:
    """导入并注册四个内置 Adapter（惰性导入避免包级循环依赖）。"""
    from .environment_data import EnvironmentDataAdapter
    from .evaluation_model import EvaluationModelAdapter
    from .route_builder import RouteBuilderAdapter
    from .web_product import WebProductAdapter

    register_adapter("route", RouteBuilderAdapter())
    register_adapter("environment", EnvironmentDataAdapter())
    register_adapter("evaluation", EvaluationModelAdapter())
    register_adapter("web", WebProductAdapter())


_register_builtin_adapters()

__all__ = ["ADAPTERS", "REQUIRED_ADAPTER_METHODS", "register_adapter"]
