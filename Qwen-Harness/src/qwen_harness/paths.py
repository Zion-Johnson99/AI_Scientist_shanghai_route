"""Path resolution and repository boundary checks.

All relative paths in ``config/harness.json`` resolve against the
``Qwen-Harness/`` directory and must stay inside the repository root
(design doc section 4.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import PathBoundaryError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import HarnessConfig


def resolve_within(
    base: Path, candidate: Path | str, label: str, boundary: Path | None = None
) -> Path:
    """Resolve ``candidate`` against ``base`` and require it stays in ``boundary``.

    Design doc §4.2: config paths resolve against ``Qwen-Harness/`` and the
    resolved result must stay inside the repository root. ``boundary``
    defaults to ``base`` for callers that resolve and check against the same
    directory.
    """
    base_resolved = base.resolve()
    boundary_resolved = (boundary if boundary is not None else base).resolve()
    resolved = (
        (base_resolved / candidate).resolve()
        if not Path(candidate).is_absolute()
        else Path(candidate).resolve()
    )
    try:
        resolved.relative_to(boundary_resolved)
    except ValueError as exc:
        raise PathBoundaryError(
            f"{label} 解析后越界: {resolved} 不在 {boundary_resolved} 内",
            details={"label": label, "resolved": str(resolved), "base": str(boundary_resolved)},
        ) from exc
    return resolved


@dataclass(frozen=True)
class HarnessPaths:
    """All canonical directories used by the harness."""

    repo_root: Path
    harness_root: Path
    skills_root: Path
    config_dir: Path
    workflows_dir: Path
    runtime_root: Path
    runs_dir: Path
    logs_dir: Path
    route_module: Path
    environment_module: Path
    evaluation_module: Path
    web_root: Path
    web_data_root: Path

    @classmethod
    def resolve(
        cls, harness_root: Path, config: "HarnessConfig", runtime_root: str = "runtime"
    ) -> "HarnessPaths":
        harness_root = harness_root.resolve()
        repo_root = harness_root.parent
        cfg_paths = config.paths

        skills_root = resolve_within(
            harness_root, cfg_paths.skills_root, "paths.skills_root", boundary=repo_root
        )
        route_module = resolve_within(
            harness_root, cfg_paths.route_module, "paths.route_module", boundary=repo_root
        )
        environment_module = resolve_within(
            harness_root,
            cfg_paths.environment_module,
            "paths.environment_module",
            boundary=repo_root,
        )
        evaluation_module = resolve_within(
            harness_root, cfg_paths.evaluation_module, "paths.evaluation_module", boundary=repo_root
        )
        web_root = resolve_within(
            harness_root, cfg_paths.web_root, "paths.web_root", boundary=repo_root
        )
        web_data_root = resolve_within(
            harness_root, cfg_paths.web_data_root, "paths.web_data_root", boundary=repo_root
        )

        runtime = Path(runtime_root)
        runtime_abs = runtime if runtime.is_absolute() else (harness_root / runtime)
        runtime_root_path = resolve_within(
            harness_root, runtime_abs, "runtime_root", boundary=repo_root
        )

        return cls(
            repo_root=repo_root,
            harness_root=harness_root,
            skills_root=skills_root,
            config_dir=harness_root / "config",
            workflows_dir=harness_root / "config" / "workflows",
            runtime_root=runtime_root_path,
            runs_dir=runtime_root_path / "runs",
            logs_dir=runtime_root_path / "logs",
            route_module=route_module,
            environment_module=environment_module,
            evaluation_module=evaluation_module,
            web_root=web_root,
            web_data_root=web_data_root,
        )

    # Convenience derived paths -------------------------------------------------
    @property
    def route_catalog_path(self) -> Path:
        return self.web_data_root / "route_catalog.json"

    @property
    def web_payload_target(self) -> Path:
        return self.web_data_root / "research_harness_latest.json"

    @property
    def environment_dashboard_path(self) -> Path:
        return self.web_data_root / "environment_dashboard.json"

    def boundary_check(self, candidate: Path | str, label: str = "path") -> Path:
        """Ensure an arbitrary path stays inside the repo or runtime tree."""
        return resolve_within(self.repo_root, candidate, label)
