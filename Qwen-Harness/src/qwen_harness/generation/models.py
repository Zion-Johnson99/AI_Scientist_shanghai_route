"""生成阶段使用的严格结构化契约。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models import ModelCallAudit, StrictModel

REQUIRED_PROJECT_ROOTS: tuple[str, ...] = (
    "Qwen-Harness",
    "evaluation_model_qwen",
    "weather_api_data",
    "xuhui_route_builder",
)


def normalize_source_path(value: str) -> str:
    """校验模型输出路径并统一为 POSIX 相对路径。"""
    candidate = value.strip()
    if not candidate or "\\" in candidate:
        raise ValueError("文件路径需使用非空 POSIX 相对路径")
    path = PurePosixPath(candidate)
    if path.is_absolute() or len(path.parts) < 2 or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("文件路径需位于规定项目目录内")
    if path.parts[0] not in REQUIRED_PROJECT_ROOTS:
        raise ValueError(f"文件路径顶层目录需属于 {', '.join(REQUIRED_PROJECT_ROOTS)}")
    return path.as_posix()


class FilePlan(StrictModel):
    path: str
    purpose: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return normalize_source_path(value)


class ArchitecturePlan(StrictModel):
    summary: str = Field(min_length=1)
    technology_choices: list[str] = Field(min_length=1)
    integration_contracts: list[str] = Field(min_length=1)
    files: list[FilePlan] = Field(min_length=4, max_length=64)

    @model_validator(mode="after")
    def _validate_file_coverage(self) -> "ArchitecturePlan":
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("架构计划包含重复文件路径")
        covered = {PurePosixPath(path).parts[0] for path in paths}
        missing = sorted(set(REQUIRED_PROJECT_ROOTS) - covered)
        if missing:
            raise ValueError(f"架构计划缺少项目目录文件: {', '.join(missing)}")
        return self


class GeneratedFile(StrictModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return normalize_source_path(value)


class ValidationIssue(StrictModel):
    check: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    details: str = ""
    severity: Literal["error", "warning"] = "error"
    files: list[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def _validate_files(cls, values: list[str]) -> list[str]:
        return [normalize_source_path(value) for value in values]


class RepairBatch(StrictModel):
    summary: str = Field(min_length=1)
    files: list[GeneratedFile] = Field(min_length=1)


class GenerationResult(StrictModel):
    source_root: str
    architecture: ArchitecturePlan
    written_files: list[str]
    repair_rounds: int = Field(ge=0)
    remaining_issues: list[ValidationIssue] = Field(default_factory=list)
    model_audits: list[ModelCallAudit] = Field(default_factory=list)
