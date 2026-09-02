"""LLM 客户端、提示词构建与调用审计（设计文档 01 §9、§10）。

对外导出：

- :class:`QwenModelClient` —— 百炼 OpenAI 兼容 Chat API 的结构化客户端。
- :class:`PromptBuilder` —— 提示词模板装载与系统提示词组装。
- :class:`ModelCallError` —— 模型不可用 / 调用失败错误（退出码 3）。
- ``make_audit`` / ``audit_to_dict`` —— ModelCallAudit 构造辅助。
"""

from .audit import audit_to_dict, make_audit, utc_now
from .client import ModelCallError, QwenModelClient
from .prompts import UNIFIED_SYSTEM_FRAGMENT, PromptBuilder

__all__ = [
    "UNIFIED_SYSTEM_FRAGMENT",
    "ModelCallError",
    "PromptBuilder",
    "QwenModelClient",
    "audit_to_dict",
    "make_audit",
    "utc_now",
]
