"""Adapter 使用的当前 run 生成工程路径视图。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import InputContractError, PathBoundaryError

_REQUIRED_MODULE_KEYS = ("route", "environment", "evaluation", "web")


@dataclass(frozen=True)
class GeneratedProjectPaths:
    """四个 Adapter 共享的单一路径来源。

    context 需暴露 ``generated.module_paths``，所有路径限定在当前 run 的
    ``workspace/source`` 中。
    """

    source_root: Path
    harness_root: Path
    route_module: Path
    environment_module: Path
    evaluation_module: Path
    web_root: Path
    web_data_root: Path
    route_catalog_path: Path
    environment_dashboard_path: Path
    generated: bool

    @property
    def module_roots(self) -> tuple[Path, Path, Path, Path]:
        return (
            self.harness_root,
            self.route_module,
            self.environment_module,
            self.evaluation_module,
        )

    def resolve_path(self, candidate: Path, label: str) -> Path:
        """解析生成工程子路径，包括符号链接解析后的边界校验。"""
        resolved = candidate.resolve()
        _require_generated_boundary(self.source_root, resolved, label)
        return resolved

    @classmethod
    def from_context(cls, context: Any) -> "GeneratedProjectPaths":
        module_paths = _extract_module_paths(context)
        if not hasattr(context, "run_dir"):
            raise InputContractError("Adapter context 缺少 run_dir，无法建立生成源码边界")

        run_dir = Path(context.run_dir).resolve()
        source_root = (run_dir / "workspace" / "source").resolve()
        try:
            source_root.relative_to(run_dir)
        except ValueError as exc:
            raise PathBoundaryError(
                f"workspace/source 解析后越出当前 run: {source_root}",
                details={"run_dir": str(run_dir), "source_root": str(source_root)},
            ) from exc
        roots = {
            name: _resolve_generated_root(source_root, module_paths[name])
            for name in ("route", "environment", "evaluation", "web")
        }
        harness_root = _resolve_generated_root(source_root, "Qwen-Harness")
        web_data_root = _resolve_generated_root(source_root, roots["route"] / "data" / "web")
        route_catalog_path = _resolve_generated_root(
            source_root, web_data_root / "route_catalog.json"
        )
        environment_dashboard_path = _resolve_generated_root(
            source_root, web_data_root / "environment_dashboard.json"
        )
        return cls(
            source_root=source_root,
            harness_root=harness_root,
            route_module=roots["route"],
            environment_module=roots["environment"],
            evaluation_module=roots["evaluation"],
            web_root=roots["web"],
            web_data_root=web_data_root,
            route_catalog_path=route_catalog_path,
            environment_dashboard_path=environment_dashboard_path,
            generated=True,
        )


def _extract_module_paths(context: Any) -> Mapping[str, Any]:
    generated = getattr(context, "generated", None)
    module_paths = getattr(generated, "module_paths", None)
    if not isinstance(module_paths, Mapping):
        raise InputContractError(
            "Adapter context 缺少当前 run 的 generated.module_paths",
            suggested_action="先完成 workspace/source 生成并向 Adapter 传入模块路径",
        )
    missing = [key for key in _REQUIRED_MODULE_KEYS if key not in module_paths]
    invalid = [
        key
        for key in _REQUIRED_MODULE_KEYS
        if key in module_paths
        and (not isinstance(module_paths[key], (str, Path)) or not str(module_paths[key]).strip())
    ]
    if missing or invalid:
        raise InputContractError(
            "generated.module_paths 需提供有效的 route/environment/evaluation/web 路径",
            details={"missing": missing, "invalid": invalid},
        )
    return module_paths


def _resolve_generated_root(source_root: Path, value: Any) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else source_root / candidate).resolve()
    _require_generated_boundary(source_root, resolved, str(value))
    return resolved


def _require_generated_boundary(source_root: Path, candidate: Path, label: str) -> None:
    try:
        candidate.resolve().relative_to(source_root.resolve())
    except ValueError as exc:
        raise PathBoundaryError(
            f"生成模块 {label!r} 越出当前 run 生成源码边界: {candidate.resolve()}",
            details={"label": label, "source_root": str(source_root), "resolved": str(candidate)},
        ) from exc


__all__ = ["GeneratedProjectPaths"]
