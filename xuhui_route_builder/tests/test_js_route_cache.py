import pytest

from xuhui_route_builder import js_route_cache
from xuhui_route_builder.js_route_cache import (
    build_browser_expression,
    cache_route_batch,
)


def test_browser_expression_uses_mode_service_and_serializes_route_payload() -> None:
    expression = build_browser_expression(
        "Walking", "121.44574,31.15186", "121.451,31.15186"
    )

    assert "new A.Walking" in expression
    assert "status:'1'" in expression
    assert "polyline:" in expression
    assert "121.44574" in expression


def test_route_cache_batch_rejects_more_than_five_routes(tmp_path) -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        cache_route_batch(
            tmp_path,
            "target",
            [f"XH_WALK_{index:04d}" for index in range(1, 7)],
        )


def test_browser_route_payload_retries_one_transient_invalid_response(monkeypatch) -> None:
    valid = {
        "status": "1",
        "route": {
            "paths": [
                {
                    "distance": "100",
                    "duration": "60",
                    "steps": [{"polyline": "121.44,31.18;121.45,31.19"}],
                }
            ]
        },
    }
    payloads = iter([{"error": "transient"}, valid])
    monkeypatch.setattr(
        js_route_cache,
        "_fetch_browser_payload",
        lambda *args: next(payloads),
    )
    monkeypatch.setattr(js_route_cache.time, "sleep", lambda _seconds: None)

    result = js_route_cache._fetch_validated_payload(
        "http://localhost:3456", "target", "expression", "XH_WALK_0001", 1
    )

    assert result == valid
