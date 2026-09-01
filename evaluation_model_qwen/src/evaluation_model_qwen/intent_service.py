from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import IntentMissingField, IntentPreferencePatch, IntentRequest, IntentResponse
from .qwen_client import QwenClient, QwenClientError

LOGGER = logging.getLogger(__name__)
MAX_TARGET_HORIZON = timedelta(hours=24)
SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

_LOOP_PATTERN = re.compile(r"回到(?:出发点|起点)|返回(?:出发点|起点)|回原点|闭环|环线|绕一圈")
_LOOP_NEGATION_PATTERN = re.compile(
    r"不(?:用|要|想|需要)?(?:回到|返回)(?:出发点|起点)|(?:不要|不想要)(?:闭环|环线)"
)
_WATERFRONT_PATTERN = re.compile(r"滨江|沿江|江景|滨水|沿河|河景|水岸|江边|河边")
_SCENERY_PATTERN = re.compile(r"风景|景色|观景|看江|看景")


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

    result = _sanitize_preference_patch(result, request)
    LOGGER.info(
        "intent_completed request_id=%s latency_ms=%s model=%s status=ok error_type=none",
        audit.request_id,
        audit.latency_ms,
        audit.model,
    )
    return result


def _sanitize_preference_patch(result: IntentResponse, request: IntentRequest) -> IntentResponse:
    patch = result.preference_patch
    updates: dict[str, object] = {}
    context_target_time = request.context.preferences.target_time
    target_time = patch.target_time or (
        context_target_time if isinstance(context_target_time, datetime) else None
    )
    if target_time is not None:
        comparable = (
            target_time.replace(tzinfo=SHANGHAI_TZ).astimezone(timezone.utc)
            if target_time.tzinfo is None
            else target_time.astimezone(timezone.utc)
        )
        now = datetime.now(timezone.utc)
        if comparable < now:
            updates["target_time"] = None
        elif comparable > now + MAX_TARGET_HORIZON:
            patch = patch.model_copy(update={"target_time": None})
            patch = _apply_explicit_semantics(patch, request.message)
            return IntentResponse(
                reply="当前环境预测只覆盖未来 24 小时，请选择这段时间内的出发时间。",
                ready=False,
                missing_fields=["target_time"],
                preference_patch=patch,
            )
    if patch.search_radius_m is not None and patch.area_ids:
        updates["area_ids"] = None
    patch = patch.model_copy(update=updates) if updates else patch
    patch = _apply_explicit_semantics(patch, request.message)
    reply = _aligned_ready_reply(result, request.message)
    return result.model_copy(update={"reply": reply, "preference_patch": patch})


def _apply_explicit_semantics(
    patch: IntentPreferencePatch,
    message: str,
) -> IntentPreferencePatch:
    updates: dict[str, object] = {"free_text": message.strip()}
    if _LOOP_PATTERN.search(message) and not _LOOP_NEGATION_PATTERN.search(message):
        updates["route_shape"] = "strict_loop"
    waterfront = bool(_WATERFRONT_PATTERN.search(message))
    if waterfront:
        interests = ["waterfront"]
        interests.extend(
            interest for interest in (patch.interests or []) if interest != "waterfront"
        )
        updates["interests"] = interests[:6]
    if _SCENERY_PATTERN.search(message):
        updates["goal"] = "scenery"
    return IntentPreferencePatch.model_validate({**patch.model_dump(), **updates})


def _aligned_ready_reply(result: IntentResponse, message: str) -> str:
    if not result.ready:
        return result.reply
    loop = bool(_LOOP_PATTERN.search(message) and not _LOOP_NEGATION_PATTERN.search(message))
    waterfront = bool(_WATERFRONT_PATTERN.search(message))
    scenery = bool(_SCENERY_PATTERN.search(message))
    if loop and waterfront:
        view = "滨江观景" if scenery else "滨江"
        return f"会按{view}的闭环路线整理，并确保回到出发点。"
    if loop:
        return "会按闭环路线整理，并确保回到出发点。"
    if waterfront:
        return "会优先按滨江观景需求整理路线。" if scenery else "会优先按滨江需求整理路线。"
    return result.reply


def _fallback_response(request: IntentRequest) -> IntentResponse:
    patch = _apply_explicit_semantics(_existing_patch(request), request.message)
    return IntentResponse(
        reply="千问暂时无法继续整理需求，已保留当前偏好。请切换到快捷选择继续。",
        ready=False,
        missing_fields=[_next_missing_field(request)],
        preference_patch=patch,
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
