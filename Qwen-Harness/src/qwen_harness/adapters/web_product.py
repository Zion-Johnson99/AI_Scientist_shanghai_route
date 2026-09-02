"""WebProductAdapter：网页产品接入（设计文档 01 §15.5）。

职责：

- 校验 ``WebPayload``（``schema_version == "1.0"``、状态枚举、
  必备字段），保证离开 runtime 的内容满足发布契约。
- 脱敏审计：不含本地绝对路径、API Key / Token、模型原始内部推理内容。
- ``web.export_payload`` 操作只校验运行目录中的
  ``publish/research_harness_latest.json``。本地产品由 Qwen-Harness 在
  当前运行目录内构建，现有 ``xuhui_route_builder`` 产品目录保持只读。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ..models import HARNESS_SCHEMA_VERSION, WebPayload
from .base import ModuleAdapter

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..models import ModuleOperation
    from ..workflow.engine import WorkflowContext

PAYLOAD_RELATIVE = "publish/research_harness_latest.json"
INDEX_RELATIVE = "index.html"

#: 状态枚举（与 models.SupportStatus 保持一致）。
_STATUS_ENUM = frozenset(
    {"supported", "partially_supported", "unsupported", "inconclusive", "error"}
)

#: 密钥/凭据标记（对 JSON 文本做小写扫描）。
_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "api-key",
    "dashscope_api_key",
    "access_token",
    "secret",
    "bearer ",
    "sk-",
    "private_key",
)

#: 疑似模型内部推理的键名片段（递归扫描 payload 键）。
_REASONING_KEY_MARKERS = ("reasoning", "thinking", "chain_of_thought", "raw_completion", "raw_response")

_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"',\[])(?:/(?:home|Users|mnt|opt|var|tmp)/|~/)")


class WebProductAdapter(ModuleAdapter):
    """网页模块 Adapter：导出前完成契约校验与脱敏审计。"""

    module = "web"
    supported_operations = ("web.export_payload",)

    # -- 预检与快照 -------------------------------------------------------------
    def preflight(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        paths = self.project_paths(context)
        for label, path in (
            ("路线目录", paths.route_catalog_path),
            ("环境仪表盘", paths.environment_dashboard_path),
        ):
            if not path.is_file():
                warnings.append(f"网页数据文件缺失: {label}")
        index_candidate = paths.resolve_path(paths.web_root / INDEX_RELATIVE, "网页入口")
        index_path = self.optional_project_file(index_candidate)
        if index_path is None:
            warnings.append(f"网页入口缺失: {INDEX_RELATIVE}")
        if len(warnings) >= 3:
            return self.result("error", errors=["网页产品数据目录不可用"], warnings=warnings)
        return self.result("partial" if warnings else "ok", warnings=warnings)

    def snapshot(self, context: "WorkflowContext") -> Any:
        warnings: list[str] = []
        paths = []
        project_paths = self.project_paths(context)
        for path in (
            project_paths.route_catalog_path,
            project_paths.environment_dashboard_path,
        ):
            if path.is_file():
                paths.append(path)
            else:
                warnings.append(f"快照缺少网页数据文件: {self.repo_relative(context, path)}")
        if not paths:
            return self.result("error", errors=["网页数据目录为空"], warnings=warnings)
        return self.result(
            "partial" if warnings else "ok",
            input_artifacts=[self.repo_relative(context, path) for path in paths],
            data_hashes=self.hash_files(paths),
            warnings=warnings,
        )

    def validate(self, context: "WorkflowContext") -> Any:
        """校验已产出/已发布的 payload 是否满足契约与脱敏要求。"""
        run_payload = context.store.read_json(PAYLOAD_RELATIVE)
        if run_payload is None:
            return self.skipped("运行目录没有 research_harness_latest.json，跳过 payload 校验")
        payload_text = json.dumps(run_payload, ensure_ascii=False)
        errors = self.audit_payload_text(payload_text)
        if errors:
            return self.result("error", errors=errors)
        return self.result("ok")

    # -- 操作执行 ---------------------------------------------------------------
    def execute(self, operation: "ModuleOperation", context: "WorkflowContext") -> Any:
        op = operation.operation_id
        if op != "web.export_payload":
            return self.unknown_operation(operation)

        payload_json: dict[str, Any] | None = None
        inline = operation.parameters.get("payload")
        if isinstance(inline, dict):
            payload_json = inline
            context.store.write_json_atomic(PAYLOAD_RELATIVE, inline)
        else:
            data = context.store.read_json(PAYLOAD_RELATIVE)
            if data is None:
                return self.skipped(
                    "publish/research_harness_latest.json 尚未生成（web_payload 阶段未运行）"
                )
            if not isinstance(data, dict):
                return self.result("error", errors=["payload 顶层必须是对象"])
            payload_json = data

        errors = self.audit_payload(payload_json)
        if errors:
            return self.result("error", errors=errors)

        warnings = ["payload 已通过 WebPayload 契约与脱敏校验，并仅保留在当前运行目录"]
        output_artifacts: list[str] = [PAYLOAD_RELATIVE]
        return self.result("ok", output_artifacts=output_artifacts, warnings=warnings)

    # -- 校验与脱敏 -------------------------------------------------------------
    def audit_payload(self, payload: dict[str, Any]) -> list[str]:
        """WebPayload 契约 + 脱敏审计，返回全部违规项。"""
        errors: list[str] = []
        schema_version = payload.get("schema_version")
        if schema_version != HARNESS_SCHEMA_VERSION:
            errors.append(
                f"schema_version 必须为 {HARNESS_SCHEMA_VERSION!r}，实际 {schema_version!r}"
            )
        status = payload.get("status")
        if status not in _STATUS_ENUM:
            errors.append(f"status 非法: {status!r}（允许: {', '.join(sorted(_STATUS_ENUM))}）")
        try:
            WebPayload.model_validate(payload)
        except ValidationError as exc:
            errors.append(f"payload 不符合 WebPayload 契约: {exc}")
        errors.extend(self.audit_payload_text(json.dumps(payload, ensure_ascii=False)))
        return errors

    def audit_payload_text(self, text: str) -> list[str]:
        """对 payload 序列化文本做脱敏扫描（路径、密钥、内部推理）。"""
        errors: list[str] = []
        lowered = text.lower()
        for marker in _SECRET_MARKERS:
            if marker in lowered:
                errors.append(f"payload 疑似包含密钥/凭据标记: {marker!r}")
        if _WINDOWS_PATH_RE.search(text):
            errors.append("payload 包含本地绝对路径（Windows 盘符）")
        if _POSIX_HOME_RE.search(text):
            errors.append("payload 包含本地绝对路径（POSIX 主目录/系统目录）")
        for marker in _REASONING_KEY_MARKERS:
            if f'"{marker}' in lowered:
                errors.append(f"payload 疑似包含模型内部推理字段: {marker!r}")
        return errors
