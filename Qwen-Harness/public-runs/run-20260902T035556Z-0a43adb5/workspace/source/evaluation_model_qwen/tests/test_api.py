from fastapi.testclient import TestClient

from evaluation_model_qwen.api import app


def test_local_web_origin_is_allowed_for_recommendations() -> None:
    response = TestClient(app).options(
        "/api/v1/recommendations",
        headers={
            "Origin": "http://127.0.0.1:8130",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8130"
