FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir uv==0.11.26 \
    && useradd --create-home --uid 10001 appuser

COPY evaluation_model_qwen /app/evaluation_model_qwen
COPY xuhui_route_builder/data/web/route_catalog.json \
    /app/xuhui_route_builder/data/web/route_catalog.json
COPY xuhui_route_builder/data/web/xuhui_routes.geojson \
    /app/xuhui_route_builder/data/web/xuhui_routes.geojson

RUN uv sync --directory /app/evaluation_model_qwen --frozen --no-dev \
    && mkdir -p /app/evaluation_model_qwen/runtime/cache \
        /app/evaluation_model_qwen/runtime/recommendations \
    && chown -R appuser:appuser /app/evaluation_model_qwen/runtime

USER appuser
WORKDIR /app/evaluation_model_qwen

CMD ["sh", "-c", "exec /app/evaluation_model_qwen/.venv/bin/evaluation-model-qwen-api --host 0.0.0.0 --port ${PORT:-10000}"]
