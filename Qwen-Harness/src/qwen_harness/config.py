"""Configuration loading: .env settings, harness.json, source policy, gates.

Uses python-dotenv for ``.env`` and validates placeholders such as
``<WorkspaceId>`` so ``doctor`` can report actionable problems
(design doc sections 4.1-4.3).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field, ValidationError

from .errors import ConfigError
from .models import (
    ApprovalMode,
    HarnessSettings,
    ReasoningEffort,
    StrictModel,
    WorkflowConfig,
)

PLACEHOLDER_TOKENS = ("<WorkspaceId>", "<workspace-id>", "<WORKSPACE_ID>")
TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}
VALID_REASONING_EFFORTS = {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# harness.json models
# ---------------------------------------------------------------------------
class ModelConfig(StrictModel):
    name: str = "qwen3.8-max"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    seed: int = 1234
    default_reasoning_effort: ReasoningEffort = "medium"
    stage_reasoning_effort: dict[str, ReasoningEffort] = Field(default_factory=dict)


class RuntimeConfig(StrictModel):
    max_iterations: int = Field(default=2, ge=1, le=16)
    atomic_writes: bool = True
    approval_mode: ApprovalMode = "critical"
    command_timeout_seconds: int = Field(default=900, ge=1)


class PathsConfig(StrictModel):
    skills_root: str = "../.qoder/skills"
    route_module: str = "../xuhui_route_builder"
    environment_module: str = "../weather_api_data"
    evaluation_module: str = "../evaluation_model_qwen"
    web_root: str = "../xuhui_route_builder/web"
    web_data_root: str = "../xuhui_route_builder/data/web"


class HarnessConfig(StrictModel):
    schema_version: str
    model: ModelConfig = Field(default_factory=ModelConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


class SourcePolicy(StrictModel):
    schema_version: str = "1.0"
    allowed_source_types: list[str] = Field(
        default_factory=lambda: ["local_file", "pubmed", "crossref", "https_url", "repository_file"]
    )
    allowed_domains: list[str] = Field(default_factory=list)
    max_download_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    pdf_max_pages: int = Field(default=40, ge=1)
    excerpt_max_chars: int = Field(default=400, ge=40)
    request_interval_seconds: float = Field(default=1.0, ge=0.0)
    max_retries: int = Field(default=2, ge=0, le=10)
    user_agent: str = "qwen-harness/0.1.0"
    require_license_note: bool = True
    require_accessed_at: bool = True
    https_only: bool = True
    reject_url_credentials: bool = True


# ---------------------------------------------------------------------------
# Environment settings
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in TRUTHY:
        return True
    if raw in FALSY:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(
            f"环境变量 {name} 不是整数: {raw!r}",
            suggested_action=f"修正 .env 中的 {name}",
        ) from exc


def load_settings(harness_root: Path) -> HarnessSettings:
    """Load ``.env`` (if present) and build HarnessSettings."""
    harness_root = Path(harness_root)
    env_file = harness_root / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    try:
        return HarnessSettings(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "").strip(),
            base_url=os.environ.get("DASHSCOPE_BASE_URL", "").strip(),
            model=os.environ.get("QWEN_HARNESS_MODEL", "qwen3.8-max").strip() or "qwen3.8-max",
            timeout_seconds=_env_int("QWEN_HARNESS_TIMEOUT_SECONDS", 180),
            network_enabled=_env_bool("QWEN_HARNESS_NETWORK_ENABLED", False),
            max_iterations=_env_int("QWEN_HARNESS_MAX_ITERATIONS", 2),
            default_reasoning_effort=os.environ.get(
                "QWEN_HARNESS_DEFAULT_REASONING_EFFORT", "medium"
            ).strip()
            or "medium",
            runtime_root=os.environ.get("QWEN_HARNESS_RUNTIME_ROOT", "runtime").strip()
            or "runtime",
            env_file_exists=env_file.is_file(),
        )
    except ValidationError as exc:
        raise ConfigError(
            f".env 配置无效: {exc}",
            suggested_action="对照 .env.example 修正 .env 中的取值",
        ) from exc


def env_diagnostics(settings: HarnessSettings) -> list[dict[str, object]]:
    """Problems that ``doctor`` should surface (never prints the key itself)."""
    problems: list[dict[str, object]] = []
    if not settings.env_file_exists:
        problems.append(
            {
                "level": "warn",
                "item": ".env",
                "message": "缺少 .env；仅离线模式可用（复制 .env.example 并填写）",
            }
        )
    if not settings.api_key_configured:
        problems.append(
            {
                "level": "warn",
                "item": "DASHSCOPE_API_KEY",
                "message": "未配置 API Key；在线模型调用不可用",
            }
        )
    if settings.base_url_has_placeholder:
        problems.append(
            {
                "level": "error",
                "item": "DASHSCOPE_BASE_URL",
                "message": "Base URL 仍含 <WorkspaceId> 占位符或为空，请替换为真实百炼工作区地址",
            }
        )
    if settings.default_reasoning_effort not in VALID_REASONING_EFFORTS:
        problems.append(
            {
                "level": "error",
                "item": "QWEN_HARNESS_DEFAULT_REASONING_EFFORT",
                "message": f"非法推理强度 {settings.default_reasoning_effort!r}，应为 low|medium|high",
            }
        )
    return problems


# ---------------------------------------------------------------------------
# JSON config files
# ---------------------------------------------------------------------------
def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"缺少配置文件: {path}", suggested_action=f"恢复 {label} 文件")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"配置文件 {path} 无法解析: {exc}", suggested_action="修复 JSON 语法"
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件 {path} 顶层必须是 JSON 对象")
    return data


def load_harness_config(harness_root: Path) -> HarnessConfig:
    data = _read_json(Path(harness_root) / "config" / "harness.json", "harness.json")
    try:
        config = HarnessConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"config/harness.json 字段无效: {exc}",
            suggested_action="对照设计文档 4.2 节修正字段",
        ) from exc
    for stage, effort in config.model.stage_reasoning_effort.items():
        if effort not in VALID_REASONING_EFFORTS:
            raise ConfigError(f"stage_reasoning_effort[{stage}] 非法: {effort!r}")
    return config


def load_source_policy(harness_root: Path) -> SourcePolicy:
    data = _read_json(Path(harness_root) / "config" / "source_policy.json", "source_policy.json")
    try:
        return SourcePolicy.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"config/source_policy.json 字段无效: {exc}") from exc


def load_quality_gates(harness_root: Path) -> dict[str, Any]:
    data = _read_json(Path(harness_root) / "config" / "quality_gates.json", "quality_gates.json")
    for section in ("evidence", "hypothesis", "experiment", "result", "supported", "publish"):
        if section not in data or not isinstance(data[section], dict):
            raise ConfigError(
                f"config/quality_gates.json 缺少 {section} 配置段",
                suggested_action="补齐质量门禁配置段",
            )
    supported = data["supported"]
    for key in (
        "detour_pass_rate_min",
        "environment_win_rate_min",
        "preference_win_rate_min",
        "reference_verification_rate_min",
        "fatal_data_errors_max",
    ):
        if key not in supported:
            raise ConfigError(f"config/quality_gates.json supported 段缺少 {key}")
    return data


def load_workflow_file(workflows_dir: Path, name: str) -> WorkflowConfig:
    path = Path(workflows_dir) / f"{name}.json"
    data = _read_json(path, f"workflows/{name}.json")
    try:
        workflow = WorkflowConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"工作流配置 {path} 无效: {exc}") from exc
    if workflow.name != name:
        raise ConfigError(f"工作流配置 name={workflow.name!r} 与文件名 {name!r} 不一致")
    return workflow


def validate_all_configs(harness_root: Path) -> list[dict[str, object]]:
    """Collect validation problems for `validate --scope config`."""
    harness_root = Path(harness_root)
    problems: list[dict[str, object]] = []

    def _try(label: str, loader: Any) -> None:
        try:
            loader()
        except ConfigError as exc:
            problems.append({"item": label, "message": exc.message})

    _try("harness.json", lambda: load_harness_config(harness_root))
    _try("source_policy.json", lambda: load_source_policy(harness_root))
    _try("quality_gates.json", lambda: load_quality_gates(harness_root))
    workflows_dir = harness_root / "config" / "workflows"
    for name in ("full-research", "research-only", "reproduce-existing"):
        _try(f"workflows/{name}.json", lambda name=name: load_workflow_file(workflows_dir, name))
    return problems
