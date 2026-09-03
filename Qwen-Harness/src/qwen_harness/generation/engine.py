"""架构规划、逐文件生成与验证修复循环。"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..errors import InputContractError
from ..models import ModelCallAudit
from .models import (
    REQUIRED_PROJECT_ROOTS,
    ArchitecturePlan,
    GeneratedFile,
    GenerationResult,
    ValidationIssue,
)
from .workspace import GenerationWorkspace

Validator = Callable[[Path], list[ValidationIssue]]
_MAX_REPAIR_CONTEXT_FILES = 8
_MAX_REPAIR_FILE_CHARS = 6_000
_REPAIR_SOURCE_SUFFIXES = {".css", ".html", ".js", ".mjs", ".ps1", ".py", ".sh"}


class GenerationEngine:
    """使用现有结构化模型客户端驱动隔离源码生成。"""

    def __init__(
        self,
        *,
        workspace: GenerationWorkspace,
        model_client: Any,
        prompts: Any,
        max_parallel_files: int = 1,
    ) -> None:
        if not 1 <= max_parallel_files <= 8:
            raise InputContractError("max_parallel_files 需位于 1 到 8")
        self.workspace = workspace
        self.model_client = model_client
        self.prompts = prompts
        self.max_parallel_files = max_parallel_files

    def generate(
        self,
        requirements: str,
        *,
        skills: Sequence[Any] = (),
        validator: Validator | None = None,
        max_repair_rounds: int = 2,
        reuse_existing: bool = False,
        deferred_file_paths: set[str] | None = None,
    ) -> GenerationResult:
        if not requirements.strip():
            raise InputContractError("工程生成需求为空")
        if not 0 <= max_repair_rounds <= 16:
            raise InputContractError("max_repair_rounds 需位于 0 到 16")

        self.workspace.initialize()
        audits: list[ModelCallAudit] = []
        architecture = self._load_cached_architecture() if reuse_existing else None
        if architecture is None:
            architecture, audit = self._call(
                stage_name="generation_architecture",
                template_name="generation-architecture",
                output_model=ArchitecturePlan,
                user_payload={
                    "requirements": requirements,
                    "required_project_roots": list(REQUIRED_PROJECT_ROOTS),
                    "source_root": "workspace/source",
                },
                skills=skills,
            )
            audits.append(audit)
            self._persist_architecture(architecture)

        planned_paths = [target.path for target in architecture.files]
        deferred = set(deferred_file_paths or ())

        def generate_file(target: Any) -> tuple[str, ModelCallAudit]:
            generated, audit = self._call(
                stage_name="generation_file",
                template_name="generation-file",
                output_model=GeneratedFile,
                user_payload={
                    "requirements": requirements,
                    "architecture": architecture.model_dump(mode="json"),
                    "target_file": target.model_dump(mode="json"),
                    "files_in_plan": planned_paths,
                },
                skills=skills,
            )
            if generated.path != target.path:
                raise InputContractError(
                    f"模型返回路径 {generated.path!r} 与计划目标不一致: {target.path!r}",
                    stage="generation_file",
                    details={"planned": target.path, "returned": generated.path},
                )
            self.workspace.write_text(generated.path, generated.content)
            return generated.path, audit

        pending = [
            target
            for target in architecture.files
            if target.path not in deferred
            and not (
                reuse_existing
                and self.workspace.resolve_file(target.path).is_file()
                and self.workspace.resolve_file(target.path).stat().st_size > 0
            )
        ]
        if pending:
            with ThreadPoolExecutor(
                max_workers=min(self.max_parallel_files, len(pending)),
                thread_name_prefix="qwen-file",
            ) as executor:
                generated_results = list(executor.map(generate_file, pending))
        else:
            generated_results = []
        audits.extend(audit for _path, audit in generated_results)
        written = [path for path in planned_paths if self.workspace.resolve_file(path).is_file()]

        issues = self._validate(validator)
        repair_rounds = 0
        while issues and repair_rounds < max_repair_rounds:
            repair_rounds += 1
            architecture_context = {
                "summary": architecture.summary,
                "technology_choices": architecture.technology_choices,
                "integration_contracts": architecture.integration_contracts,
                "planned_files": planned_paths,
            }

            def repair_issue(issue: ValidationIssue) -> tuple[GeneratedFile, ModelCallAudit]:
                target_path = self._repair_target(issue, planned_paths)
                focused_issue = issue.model_copy(update={"files": [target_path]})
                generated, audit = self._call(
                    stage_name="generation_repair",
                    template_name="generation-repair-file",
                    output_model=GeneratedFile,
                    user_payload={
                        "requirements": requirements,
                        "architecture": architecture_context,
                        "repair_round": repair_rounds,
                        "validation_issue": issue.model_dump(mode="json"),
                        "target_file": {"path": target_path},
                        "current_content": self._affected_contents([focused_issue], written).get(
                            target_path, ""
                        ),
                    },
                    skills=skills,
                )
                if generated.path != target_path:
                    raise InputContractError(
                        f"修复返回路径 {generated.path!r} 与目标不一致: {target_path!r}",
                        stage="generation_repair",
                    )
                return generated, audit

            with ThreadPoolExecutor(
                max_workers=min(self.max_parallel_files, len(issues)),
                thread_name_prefix="qwen-repair",
            ) as executor:
                repair_results = list(executor.map(repair_issue, issues))
            for generated, audit in repair_results:
                audits.append(audit)
                self.workspace.write_text(generated.path, generated.content)
                if generated.path not in written:
                    written.append(generated.path)
            issues = self._validate(validator)

        written = [path for path in planned_paths if self.workspace.resolve_file(path).is_file()]
        return GenerationResult(
            source_root=str(self.workspace.source_root),
            architecture=architecture,
            written_files=written,
            repair_rounds=repair_rounds,
            remaining_issues=issues,
            model_audits=audits,
        )

    def repair_issue(
        self,
        requirements: str,
        issue: ValidationIssue,
        *,
        skills: Sequence[Any] = (),
        repair_round: int = 1,
    ) -> tuple[GeneratedFile, ModelCallAudit]:
        """让模型定向修复缓存架构中的一个既有文件。"""
        if not requirements.strip():
            raise InputContractError("工程修复需求为空")
        self.workspace.initialize()
        architecture = self._load_cached_architecture()
        if architecture is None:
            raise InputContractError(
                "运行时修复缺少已缓存架构计划",
                stage="generation_repair",
            )
        planned_paths = [target.path for target in architecture.files]
        target_path = self._repair_target(issue, planned_paths)
        if target_path not in planned_paths:
            raise InputContractError(
                f"运行时修复目标未出现在架构计划中: {target_path}",
                stage="generation_repair",
            )
        focused_issue = issue.model_copy(update={"files": [target_path]})
        current_content = self._affected_contents([focused_issue], planned_paths).get(
            target_path, ""
        )
        generated, audit = self._call(
            stage_name="generation_runtime_repair",
            template_name="generation-repair-file",
            output_model=GeneratedFile,
            user_payload={
                "requirements": requirements,
                "architecture": {
                    "summary": architecture.summary,
                    "technology_choices": architecture.technology_choices,
                    "integration_contracts": architecture.integration_contracts,
                    "planned_files": planned_paths,
                },
                "repair_round": repair_round,
                "validation_issue": issue.model_dump(mode="json"),
                "target_file": {"path": target_path},
                "current_content": current_content,
            },
            skills=skills,
        )
        if generated.path != target_path:
            raise InputContractError(
                f"运行时修复返回路径 {generated.path!r} 与目标不一致: {target_path!r}",
                stage="generation_repair",
            )
        self.workspace.write_text(generated.path, generated.content)
        return generated, audit

    @property
    def _architecture_path(self) -> Path:
        return self.workspace.workspace_root / "architecture.json"

    def _load_cached_architecture(self) -> ArchitecturePlan | None:
        if not self._architecture_path.is_file():
            return None
        try:
            return ArchitecturePlan.model_validate_json(
                self._architecture_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise InputContractError(
                f"已缓存架构计划无效: {self._architecture_path}",
                stage="generation_architecture",
            ) from exc

    def _persist_architecture(self, architecture: ArchitecturePlan) -> None:
        self._architecture_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._architecture_path.with_name(
            f"architecture.json.tmp-{uuid.uuid4().hex[:8]}"
        )
        try:
            temporary.write_text(architecture.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, self._architecture_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _call(
        self,
        *,
        stage_name: str,
        template_name: str,
        output_model: type[BaseModel],
        user_payload: dict[str, object],
        skills: Sequence[Any],
    ) -> tuple[Any, ModelCallAudit]:
        system_prompt = self.prompts.build_system_prompt(
            template_name,
            list(skills),
            json.dumps(output_model.model_json_schema(), ensure_ascii=False, indent=2),
        )
        skill_hashes = {
            str(skill.name): str(skill.sha256)
            for skill in skills
            if getattr(skill, "name", None) and getattr(skill, "sha256", None)
        }
        response, audit = self.model_client.generate_structured(
            stage_name=stage_name,
            system_prompt=system_prompt,
            user_payload=user_payload,
            output_model=output_model,
            prompt_version=self.prompts.template_version(template_name),
            skill_hashes=skill_hashes,
        )
        if not isinstance(response, output_model):
            raise InputContractError(
                f"阶段 {stage_name} 返回了错误的结构化类型: {type(response).__name__}",
                stage=stage_name,
            )
        return response, audit

    def _validate(self, validator: Validator | None) -> list[ValidationIssue]:
        if validator is None:
            return []
        issues = validator(self.workspace.source_root)
        if not isinstance(issues, list) or any(
            not isinstance(issue, ValidationIssue) for issue in issues
        ):
            raise InputContractError("生成验证器需返回 list[ValidationIssue]")
        return issues

    def _affected_contents(
        self, issues: list[ValidationIssue], written: list[str]
    ) -> dict[str, str]:
        affected = list(dict.fromkeys(path for issue in issues for path in issue.files))
        candidates = affected or written
        preferred = [
            path
            for path in candidates
            if Path(path).suffix.lower() in _REPAIR_SOURCE_SUFFIXES
            and "/tests/" not in f"/{path}"
            and not Path(path).name.startswith("test_")
        ]
        selected = (preferred or candidates)[:_MAX_REPAIR_CONTEXT_FILES]
        contents: dict[str, str] = {}
        for path in selected:
            destination = self.workspace.resolve_file(path)
            if destination.is_file():
                content = self.workspace.read_text(path)
                if len(content) > _MAX_REPAIR_FILE_CHARS:
                    half = _MAX_REPAIR_FILE_CHARS // 2
                    content = (
                        content[:half]
                        + "\n...中间内容已截断...\n"
                        + content[-half:]
                        + "\n...内容已截断"
                    )
                contents[path] = content
        return contents

    @staticmethod
    def _repair_target(issue: ValidationIssue, planned_paths: list[str]) -> str:
        explicit = next((path for path in issue.files if path in planned_paths), None)
        if explicit is not None:
            return explicit
        candidates = list(dict.fromkeys([*issue.files, *planned_paths]))
        preferences: tuple[str, ...]
        if "environment" in issue.check:
            preferences = ("web_export.py", "route_environment.py", "pipeline.py")
        elif "launcher" in issue.check:
            preferences = ("launch-local.ps1", "start-local.ps1", "start-local.sh")
        elif "traversal" in issue.check:
            preferences = ("cli.py",)
        elif "browser" in issue.check or "map_web" in issue.check:
            preferences = ("web/index.html", "web/src/main.js")
        else:
            preferences = ()
        for preference in preferences:
            match = next((path for path in candidates if path.endswith(preference)), None)
            if match:
                return match
        if issue.files:
            return issue.files[0]
        if planned_paths:
            return planned_paths[0]
        raise InputContractError("修复问题没有可用目标文件", stage="generation_repair")
