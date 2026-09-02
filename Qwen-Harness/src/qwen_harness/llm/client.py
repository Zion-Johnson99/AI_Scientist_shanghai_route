"""Qwen 模型客户端：百炼 OpenAI 兼容 Chat API（设计文档 01 §9）。

约束摘要：

- 模型名来自配置（默认 ``qwen3.8-max``），``temperature=0.2``、``seed=1234``。
- ``extra_body`` 只设置 ``enable_thinking``、``reasoning_effort`` 与
  ``preserve_thinking=false``；``reasoning_effort`` 与 ``thinking_budget``
  互斥，本客户端绝不设置后者。
- 结构化输出由 Pydantic 解析；内部推理内容（thinking）不写入运行目录。
- 重试规则：连接超时 / 5xx / 限流最多 2 次指数退避；Schema 校验失败携带
  简短校验错误重试 1 次；引用不存在、越权输出等语义问题交由质量门禁，
  不做自由文本回退。
- 离线或缺少 API Key 时抛出 :class:`ModelCallError`；离线路径由工作流引擎
  用固定夹具替代，客户端不伪造任何模型输出。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..errors import ModelUnavailableError
from ..logging_utils import get_logger
from ..models import ModelCallAudit
from .audit import make_audit

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from ..config import HarnessConfig, HarnessSettings

LOGGER = get_logger("llm.client")

ModelT = TypeVar("ModelT", bound=BaseModel)

DEFAULT_MODEL = "qwen3.8-max"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_SEED = 1234
MAX_TRANSPORT_RETRIES = 2
SCHEMA_RETRY = 1
RETRY_BACKOFF_SECONDS = (1.0, 2.0)
_VALIDATION_ERROR_HINT_LIMIT = 400


class ModelCallError(ModelUnavailableError):
    """模型调用失败（未配置、传输失败重试耗尽或结构化解析失败）。"""

    error_type = "model_call_error"


def _is_retryable_api_error(exc: Exception) -> bool:
    """连接超时 / 5xx / 限流 属于可重试传输错误。"""
    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            RateLimitError,
        )
    except ImportError:  # pragma: no cover - openai 必装依赖
        return False
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500 or exc.status_code == 429
    return False


def _short_validation_error(exc: ValidationError) -> str:
    """把 Pydantic 校验错误压缩成给模型的简短重试提示。"""
    parts: list[str] = []
    for error in exc.errors()[:3]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    text = "; ".join(parts)
    return text[:_VALIDATION_ERROR_HINT_LIMIT]


class QwenModelClient:
    """按阶段发起一次结构化 Chat 调用，返回解析后的模型与审计。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        seed: int = DEFAULT_SEED,
        timeout_seconds: int = 180,
        default_reasoning_effort: str = "medium",
        stage_reasoning_effort: dict[str, str] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ModelCallError(
                "缺少 DASHSCOPE_API_KEY，无法发起在线模型调用",
                suggested_action="在 Qwen-Harness/.env 配置 DASHSCOPE_API_KEY，或使用 --offline 复现",
            )
        if not base_url.strip() or "<WorkspaceId>" in base_url:
            raise ModelCallError(
                "DASHSCOPE_BASE_URL 为空或仍含 <WorkspaceId> 占位符",
                suggested_action="把 Base URL 替换为真实百炼工作区地址后重试",
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - openai 必装依赖
            raise ModelCallError(
                "缺少 openai 依赖，无法调用百炼 OpenAI 兼容接口",
                suggested_action="执行 `uv sync` 安装 pyproject.toml 声明的依赖",
            ) from exc
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.seed = seed
        self.default_reasoning_effort = default_reasoning_effort
        self.stage_reasoning_effort = dict(stage_reasoning_effort or {})
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=float(timeout_seconds),
        )

    # -- 工厂 -----------------------------------------------------------------
    @classmethod
    def from_env(cls, settings: "HarnessSettings", harness_config: "HarnessConfig | None" = None) -> "QwenModelClient":
        """引擎用 ``from_env(settings, harness_config)`` 构造；离线时不调用。"""
        if harness_config is not None:
            model_cfg = harness_config.model
            return cls(
                api_key=settings.api_key,
                base_url=settings.base_url,
                model=model_cfg.name,
                temperature=model_cfg.temperature,
                seed=model_cfg.seed,
                timeout_seconds=settings.timeout_seconds,
                default_reasoning_effort=model_cfg.default_reasoning_effort,
                stage_reasoning_effort=dict(model_cfg.stage_reasoning_effort),
            )
        return cls(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            default_reasoning_effort=settings.default_reasoning_effort,
        )

    # -- 参数 -----------------------------------------------------------------
    def reasoning_effort_for(self, stage_name: str) -> str:
        return self.stage_reasoning_effort.get(stage_name, self.default_reasoning_effort)

    def _extra_body(self, stage_name: str) -> dict[str, Any]:
        """保持百炼的 thinking 开关与 reasoning_effort 参数一致。"""
        effort = self.reasoning_effort_for(stage_name)
        return {
            "enable_thinking": effort != "none",
            "reasoning_effort": effort,
            "preserve_thinking": False,
        }

    # -- 结构化调用 ------------------------------------------------------------
    def generate_structured(
        self,
        *,
        stage_name: str,
        system_prompt: str,
        user_payload: dict[str, object],
        output_model: type[ModelT],
        prompt_version: str,
        skill_hashes: dict[str, str] | None = None,
    ) -> tuple[ModelT, ModelCallAudit]:
        """发起一次（含受控重试的）结构化调用并返回解析结果与审计。"""
        effort = self.reasoning_effort_for(stage_name)
        schema_hint: str | None = None
        last_transport_error: Exception | None = None

        for round_index in range(SCHEMA_RETRY + 1):  # Schema 失败最多重试 1 次
            payload = dict(user_payload)
            if schema_hint is not None:
                payload["_retry_validation_error"] = schema_hint
            try:
                raw_text, audit = self._chat_with_transport_retry(
                    stage_name=stage_name,
                    system_prompt=system_prompt,
                    payload=payload,
                    prompt_version=prompt_version,
                    effort=effort,
                    skill_hashes=skill_hashes,
                )
            except ModelCallError:
                raise
            except Exception as exc:
                if _is_retryable_api_error(exc):
                    # 理论上已被内部退避重试耗尽，这里兜底
                    last_transport_error = exc
                    raise ModelCallError(
                        f"模型调用失败（重试耗尽）: {type(exc).__name__}: {exc}",
                        stage=stage_name,
                        suggested_action="稍后重试；持续失败请检查百炼服务状态与网络",
                    ) from exc
                raise ModelCallError(
                    f"模型调用失败: {type(exc).__name__}: {exc}",
                    stage=stage_name,
                    suggested_action="检查百炼账号配额与请求参数",
                ) from exc
            try:
                parsed = self._parse_structured(raw_text, output_model)
            except (ValidationError, json.JSONDecodeError) as exc:
                if round_index < SCHEMA_RETRY:
                    schema_hint = (
                        _short_validation_error(exc) if isinstance(exc, ValidationError) else f"JSON 解析失败: {exc}"
                    )
                    LOGGER.warning("阶段 %s 结构化输出校验失败，携带错误重试: %s", stage_name, schema_hint)
                    continue
                audit_failure = make_audit(
                    stage=stage_name,
                    model=self.model,
                    prompt_version=prompt_version,
                    reasoning_effort=effort,
                    skill_hashes=skill_hashes,
                    error_type="schema_validation_failed",
                )
                error = ModelCallError(
                    "模型输出两次均不符合输出模型契约（不回退自由文本）",
                    stage=stage_name,
                    suggested_action="检查 prompts 中的输出模型说明与输入数据质量",
                )
                error.retryable = False
                error.details = {"audit": audit_failure.model_dump(mode="json")}
                raise error from exc
            return parsed, audit
        # 循环必然 return 或 raise；此处仅为类型收敛
        raise ModelCallError(
            "结构化调用异常退出重试循环",
            stage=stage_name,
            details={"last_transport_error": str(last_transport_error)} if last_transport_error else {},
        )

    # -- 底层调用 ------------------------------------------------------------
    def _chat_with_transport_retry(
        self,
        *,
        stage_name: str,
        system_prompt: str,
        payload: dict[str, object],
        prompt_version: str,
        effort: str,
        skill_hashes: dict[str, str] | None,
    ) -> tuple[str, ModelCallAudit]:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            },
        ]
        extra_body = self._extra_body(stage_name)
        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    seed=self.seed,
                    response_format={"type": "json_object"},
                    extra_body=extra_body,
                )
            except Exception as exc:
                if _is_retryable_api_error(exc) and attempt <= MAX_TRANSPORT_RETRIES:
                    delay = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                    LOGGER.warning(
                        "阶段 %s 模型调用可重试错误（第 %d/%d 次），%.1fs 后重试: %s",
                        stage_name,
                        attempt,
                        MAX_TRANSPORT_RETRIES,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    continue
                if _is_retryable_api_error(exc):
                    raise
                raise
            latency_ms = (time.perf_counter() - started) * 1000.0
            choice = response.choices[0] if response.choices else None
            if choice is None or not choice.message or choice.message.content is None:
                raise ModelCallError(
                    "模型返回空内容",
                    stage=stage_name,
                    suggested_action="降低单次输入规模或稍后重试",
                )
            usage = getattr(response, "usage", None)
            audit = make_audit(
                stage=stage_name,
                model=self.model,
                prompt_version=prompt_version,
                reasoning_effort=effort,
                skill_hashes=skill_hashes,
                request_id=getattr(response, "id", None),
                latency_ms=latency_ms,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            )
            return str(choice.message.content), audit

    @staticmethod
    def _parse_structured(raw_text: str, output_model: type[ModelT]) -> ModelT:
        """Pydantic 解析模型输出；JSON 语法错误以 JSONDecodeError 上抛。"""
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        data = json.loads(text)
        return output_model.model_validate(data)
