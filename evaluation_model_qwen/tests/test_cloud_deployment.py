from pathlib import Path

ROOT = Path(__file__).parents[2]
DOCKERFILE = ROOT / "evaluation_model_qwen" / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
RENDER_BLUEPRINT = ROOT / "render.yaml"


def test_qwen_container_uses_frozen_runtime_and_public_bind() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "python:3.12-slim" in dockerfile
    assert "uv==0.11.26" in dockerfile
    assert "uv sync --directory /app/evaluation_model_qwen --frozen --no-dev" in dockerfile
    assert "xuhui_route_builder/data/web/route_catalog.json" in dockerfile
    assert (
        "exec /app/evaluation_model_qwen/.venv/bin/evaluation-model-qwen-api --host 0.0.0.0"
    ) in dockerfile
    assert "uv run" not in dockerfile
    assert "${PORT:-10000}" in dockerfile
    assert "USER appuser" in dockerfile
    assert "COPY ." not in dockerfile
    assert ".env" not in dockerfile


def test_docker_context_excludes_credentials_and_local_runtime() -> None:
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")

    for pattern in (
        "**/.env",
        "**/.venv",
        "**/runtime",
        "**/__pycache__",
        ".git",
    ):
        assert pattern in dockerignore
    assert "!evaluation_model_qwen/**" in dockerignore
    assert "!xuhui_route_builder/data/web/route_catalog.json" in dockerignore


def test_render_blueprint_keeps_qwen_secrets_out_of_git() -> None:
    blueprint = RENDER_BLUEPRINT.read_text(encoding="utf-8")

    assert "runtime: docker" in blueprint
    assert "dockerfilePath: ./evaluation_model_qwen/Dockerfile" in blueprint
    assert "dockerContext: ." in blueprint
    assert "region: singapore" in blueprint
    assert "healthCheckPath: /api/v1/health" in blueprint
    assert "key: DASHSCOPE_API_KEY\n        sync: false" in blueprint
    assert "key: DASHSCOPE_BASE_URL\n        sync: false" in blueprint
    assert 'key: FORWARDED_ALLOW_IPS\n        value: "*"' in blueprint
    assert "key: EVALUATION_MODEL_QWEN_ENVIRONMENT_URL\n        sync: false" in blueprint
    assert 'key: EVALUATION_MODEL_QWEN_ENVIRONMENT_CACHE_SECONDS\n        value: "60"' in blueprint
    assert (
        "github.io/AI_Scientist_shanghai_route/data/web/environment_dashboard.json" not in blueprint
    )
    assert "DASHSCOPE_API_KEY=" not in blueprint
