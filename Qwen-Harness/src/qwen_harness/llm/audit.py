"""模型调用审计（设计文档 01 §9、§20）。

``ModelCallAudit`` 记录每次结构化调用的模型、请求 ID、延迟、token、
prompt 版本、Skill 哈希与错误类型。审计只包含可追溯元数据：内部推理
内容（thinking）绝不进入运行目录，也不进入本审计。
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import ModelCallAudit


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_audit(
    *,
    stage: str,
    model: str,
    prompt_version: str | None,
    reasoning_effort: str | None,
    skill_hashes: dict[str, str] | None = None,
    request_id: str | None = None,
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_type: str | None = None,
) -> ModelCallAudit:
    """构造一条审计记录（失败调用也必须记录错误类型）。"""
    return ModelCallAudit(
        stage=stage,
        model=model,
        created_at=utc_now(),
        request_id=request_id,
        latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        prompt_version=prompt_version,
        reasoning_effort=reasoning_effort,
        skill_hashes=dict(skill_hashes or {}),
        error_type=error_type,
    )


def audit_to_dict(audit: ModelCallAudit) -> dict[str, object]:
    """转成可写入运行目录 audit.json 的纯 JSON 字典。"""
    return dict(audit.model_dump(mode="json"))
