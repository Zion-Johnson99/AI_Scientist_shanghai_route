from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from traceback import extract_tb
from typing import Any, Sequence

import uvicorn
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .intent_service import interpret_intent
from .loaders import LoaderError, load_data
from .models import (
    IntentRequest,
    IntentResponse,
    QuestionnaireConfig,
    RecommendationResult,
    UserProfile,
)
from .qwen_client import QwenClientError, QwenConfigurationError
from .service import evaluation_root, recommend, write_audit_result

LOGGER = logging.getLogger(__name__)
ALLOWED_ORIGINS = ("http://127.0.0.1:8123", "http://localhost:8123")
OFFLINE_ENV = "EVALUATION_MODEL_QWEN_OFFLINE"
AUDIT_ROOT_ENV = "EVALUATION_MODEL_QWEN_AUDIT_ROOT"

_QWEN_ERROR_CODES = {
    "authentication": "qwen_authentication_failed",
    "connection": "qwen_network_unavailable",
    "rate_limit": "qwen_quota_exceeded",
    "timeout": "qwen_timeout",
}
_QWEN_CONFIGURATION_ERRORS = {
    "invalid_base_url",
    "invalid_timeout",
    "missing_api_key",
    "missing_base_url",
}
_ERROR_MESSAGES = {
    "invalid_recommendation_request": "推荐条件无效，请检查后重试。",
    "qwen_authentication_failed": "千问服务鉴权失败，请联系管理员。",
    "qwen_configuration_unavailable": "千问服务配置暂不可用，请联系管理员。",
    "qwen_network_unavailable": "千问服务连接失败，请稍后重试。",
    "qwen_quota_exceeded": "千问服务额度暂不可用，请稍后重试。",
    "qwen_timeout": "千问服务响应超时，请稍后重试。",
    "recommendation_data_unavailable": "路线与环境数据暂不可用，请稍后重试。",
    "service_unavailable": "推荐服务暂不可用，请稍后重试。",
}

_INTEREST_LABELS = {
    "waterfront": "滨水",
    "park": "公园",
    "quiet": "安静",
    "coffee": "咖啡",
    "toilet": "厕所",
    "convenience": "补给",
}
_SENSITIVITY_LABELS = {
    "air": "空气",
    "pollen": "花粉",
    "heat": "高温",
    "noise": "噪声",
}


def create_app() -> FastAPI:
    application = FastAPI(title="徐汇健康路线推荐 API", version="1.0.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.add_exception_handler(RequestValidationError, _validation_error)

    application.add_api_route(
        "/api/v1/health",
        health,
        methods=["GET"],
        response_model=None,
    )
    application.add_api_route(
        "/api/v1/questionnaire",
        questionnaire,
        methods=["GET"],
        response_model=None,
    )
    application.add_api_route(
        "/api/v1/recommendation-intent",
        recommendation_intent,
        methods=["POST"],
        response_model=IntentResponse,
        responses={503: {"description": "意图解析服务暂不可用"}},
    )
    application.add_api_route(
        "/api/v1/recommendations",
        recommendations,
        methods=["POST"],
        response_model=RecommendationResult,
        responses={
            422: {"description": "推荐条件无效"},
            503: {"description": "推荐服务或数据包暂不可用"},
        },
    )
    return application


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    operation = request.url.path.rsplit("/", maxsplit=1)[-1].replace("-", "_")
    _log_exception(operation or "request_validation", exc, level=logging.WARNING)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "请求参数未通过校验。",
            }
        },
    )


def health() -> dict[str, Any] | JSONResponse:
    try:
        bundle = load_data()
    except Exception as exc:  # noqa: BLE001
        return _error_response("health", exc)
    return {
        "status": "ok",
        "data": {
            "status": bundle.environment.status,
            "generated_at": bundle.environment.generated_at,
            "route_count": len(bundle.routes),
        },
        "qwen": {
            "configured": _qwen_configured(),
            "offline": _offline_enabled(),
        },
    }


def questionnaire() -> dict[str, Any] | JSONResponse:
    try:
        config = _load_questionnaire()
    except Exception as exc:  # noqa: BLE001
        return _error_response("questionnaire", exc)
    return _questionnaire_document(config)


def recommendation_intent(request: IntentRequest) -> IntentResponse | JSONResponse:
    try:
        return interpret_intent(request)
    except Exception as exc:  # noqa: BLE001
        return _error_response("recommendation_intent", exc)


def recommendations(profile: UserProfile) -> RecommendationResult | JSONResponse:
    try:
        result = recommend(profile, offline=_offline_enabled())
        audit_path = write_audit_result(result, _audit_root())
    except Exception as exc:  # noqa: BLE001
        return _error_response("recommendations", exc)
    LOGGER.info(
        "recommendation_completed run_id=%s status=%s decision_source=%s audit_file=%s",
        result.run_id,
        result.status,
        result.decision_source,
        audit_path.name,
    )
    return result


def _load_questionnaire() -> QuestionnaireConfig:
    path = evaluation_root() / "config" / "questionnaire.json"
    return QuestionnaireConfig.model_validate_json(path.read_text(encoding="utf-8"))


def _questionnaire_document(config: QuestionnaireConfig) -> dict[str, Any]:
    distance_ranges = {
        mode: [
            {
                "value": f"{low}_{high}_{target}",
                "label": f"{low / 1000:g}–{high / 1000:g} 公里",
                "distance_min_m": low,
                "target_distance_m": target,
                "distance_max_m": high,
            }
            for low, high, target in ranges
        ]
        for mode, ranges in config.distance_ranges.items()
    }
    return {
        "route_modes": _options(config.route_modes),
        "distance_ranges": distance_ranges,
        "goals": _options(config.goals),
        "experience_levels": _options(config.experience_levels),
        "age_groups": _options(config.age_groups),
        "areas": _options(config.areas),
        "interests": [
            {"value": value, "label": _INTEREST_LABELS[value]} for value in config.interests
        ],
        "sensitivities": [
            {"value": value, "label": _SENSITIVITY_LABELS[value]} for value in config.sensitivities
        ],
        "target_times": [
            {"value": "now", "label": "现在"},
            {"value": "plus_2h", "label": "两小时后"},
            {"value": "custom", "label": "自定义时间"},
        ],
        "search_scopes": [
            {"value": "nearby_3000", "label": "附近 3 公里"},
            {"value": "nearby_5000", "label": "附近 5 公里"},
            {"value": "nearby_8000", "label": "附近 8 公里"},
            {"value": "area", "label": "指定片区"},
            {"value": "all_xuhui", "label": "全徐汇区"},
        ],
        "route_shapes": [
            {"value": "any", "label": "不限"},
            {"value": "strict_loop", "label": "环线"},
            {"value": "one_way", "label": "单程"},
        ],
    }


def _options(values: list[Any]) -> list[dict[str, str]]:
    return [{"value": item.value, "label": item.label} for item in values]


def _offline_enabled() -> bool:
    return os.getenv(OFFLINE_ENV, "0") == "1"


def _audit_root() -> Path:
    configured = os.getenv(AUDIT_ROOT_ENV)
    return Path(configured) if configured else evaluation_root() / "runtime" / "recommendations"


def _qwen_configured() -> bool:
    file_values = dotenv_values(evaluation_root() / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY") or file_values.get("DASHSCOPE_API_KEY")
    base_url = os.getenv("DASHSCOPE_BASE_URL") or file_values.get("DASHSCOPE_BASE_URL")
    return bool(api_key and base_url and "<" not in base_url and ">" not in base_url)


def _error_response(operation: str, exc: Exception) -> JSONResponse:
    status_code, code = _classify_error(operation, exc)
    _log_exception(operation, exc)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": _ERROR_MESSAGES[code]}},
    )


def _classify_error(operation: str, exc: Exception) -> tuple[int, str]:
    if isinstance(exc, LoaderError) or operation in {"health", "questionnaire"}:
        return 503, "recommendation_data_unavailable"
    if isinstance(exc, QwenConfigurationError):
        return 503, "qwen_configuration_unavailable"
    if isinstance(exc, QwenClientError):
        error_type = exc.audit.error_type
        if error_type in _QWEN_CONFIGURATION_ERRORS:
            return 503, "qwen_configuration_unavailable"
        if error_type is not None and error_type in _QWEN_ERROR_CODES:
            return 503, _QWEN_ERROR_CODES[error_type]
        return 503, "service_unavailable"
    if isinstance(exc, ValueError):
        return 422, "invalid_recommendation_request"
    return 503, "service_unavailable"


def _log_exception(operation: str, exc: Exception, *, level: int = logging.ERROR) -> None:
    redacted = RuntimeError(f"{type(exc).__name__}: exception details redacted")
    traceback_lines = ["Traceback (most recent call last):"]
    traceback_lines.extend(
        f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
        for frame in extract_tb(exc.__traceback__)
    )
    LOGGER.log(
        level,
        "request_failed operation=%s error_type=%s\n%s",
        operation,
        type(exc).__name__,
        "\n".join(traceback_lines),
        exc_info=(type(redacted), redacted, None),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="徐汇健康路线推荐 API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8124)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    uvicorn.run(app, host=args.host, port=args.port)


app = create_app()


if __name__ == "__main__":
    main()
