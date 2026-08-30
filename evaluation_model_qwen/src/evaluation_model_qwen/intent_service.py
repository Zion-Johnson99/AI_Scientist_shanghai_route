from __future__ import annotations

import logging
from pathlib import Path

from .models import IntentMissingField, IntentPreferencePatch, IntentRequest, IntentResponse
from .qwen_client import QwenClient, QwenClientError

LOGGER = logging.getLogger(__name__)


def interpret_intent(
    request: IntentRequest,
    *,
    qwen_client: QwenClient | None = None,
) -> IntentResponse:
    client = qwen_client or QwenClient.from_env(_environment_file())
    try:
        result, audit = client.interpret_intent(request)
    except QwenClientError as exc:
        audit = exc.audit
        LOGGER.warning(
            "intent_completed request_id=%s latency_ms=%s model=%s status=degraded error_type=%s",
            audit.request_id,
            audit.latency_ms,
            audit.model,
            audit.error_type,
        )
        return _fallback_response(request)

    LOGGER.info(
        "intent_completed request_id=%s latency_ms=%s model=%s status=ok error_type=none",
        audit.request_id,
        audit.latency_ms,
        audit.model,
    )
    return result


def _fallback_response(request: IntentRequest) -> IntentResponse:
    return IntentResponse(
        reply="千问暂时无法继续整理需求，已保留当前偏好。请切换到快捷选择继续。",
        ready=False,
        missing_fields=[_next_missing_field(request)],
        preference_patch=_existing_patch(request),
    )


def _next_missing_field(request: IntentRequest) -> IntentMissingField:
    if request.context.location is None:
        return "location"
    preferences = request.context.preferences
    if preferences.target_distance_m is None:
        return "distance"
    if preferences.target_time is None:
        return "target_time"
    if preferences.goal is None:
        return "goal"
    return "goal"


def _environment_file() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _existing_patch(request: IntentRequest) -> IntentPreferencePatch:
    fields = set(IntentPreferencePatch.model_fields)
    document = request.context.preferences.model_dump(include=fields, exclude_none=True)
    return IntentPreferencePatch.model_validate(document)
