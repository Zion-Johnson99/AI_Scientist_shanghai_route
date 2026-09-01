from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.models import PreparedRequest, Response

from weather_api_data.config import Settings
from weather_api_data.http_client import (
    ApiRequestError,
    CallLimitExceeded,
    HttpClient,
    HttpResult,
    RequestBudget,
)

UTC_NOW = datetime(2026, 8, 24, 7, 30, tzinfo=timezone.utc)


class QueueAdapter(BaseAdapter):
    """在 requests 完成请求准备后返回排队结果并避免真实联网。"""

    def __init__(self, outcomes: list[Response | requests.RequestException]) -> None:
        self.outcomes = iter(outcomes)
        self.requests: list[PreparedRequest] = []
        self.timeouts: list[object] = []

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: object = None,
        verify: bool | str = True,
        cert: object = None,
        proxies: dict[str, str] | None = None,
    ) -> Response:
        del stream, verify, cert, proxies
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = next(self.outcomes)
        if isinstance(outcome, requests.RequestException):
            raise outcome
        outcome.request = request
        outcome.url = request.url or ""
        return outcome

    def close(self) -> None:
        return None


class StubResponse(Response):
    """允许测试在类内部设置 requests 响应正文。"""

    def set_body(self, body: bytes) -> None:
        self._content = body


def response(
    status_code: int,
    payload: object = None,
    *,
    headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
) -> Response:
    result = StubResponse()
    result.status_code = status_code
    result.headers.update(headers or {})
    result.encoding = "utf-8"
    result.set_body(raw_body if raw_body is not None else json.dumps(payload).encode())
    return result


@pytest.fixture
def settings() -> Settings:
    return Settings(
        max_calls_per_run=10,
        connect_timeout_seconds=2.5,
        read_timeout_seconds=7.5,
        max_retries=2,
        min_interval_seconds=1.0,
        jitter_max_seconds=0.25,
    )


def make_client(
    outcomes: list[Response | requests.RequestException],
    settings: Settings,
    *,
    sleep_fn: Callable[[float], None] = lambda _seconds: None,
    uniform_fn: Callable[[float, float], float] = lambda _start, _end: 0.0,
) -> tuple[HttpClient, QueueAdapter]:
    adapter = QueueAdapter(outcomes)
    session = requests.Session()
    session.mount("https://", adapter)
    client = HttpClient(
        session=session,
        settings=settings,
        sleep_fn=sleep_fn,
        uniform_fn=uniform_fn,
        utcnow_fn=lambda: UTC_NOW,
    )
    return client, adapter


def test_http_result_is_immutable() -> None:
    result = HttpResult(payload={"ok": True}, status_code=200, expires=None, fetched_at=UTC_NOW)

    with pytest.raises(FrozenInstanceError):
        result.status_code = 201  # type: ignore[misc]


def test_success_uses_requests_encoding_gzip_timeout_and_response_metadata(
    settings: Settings,
) -> None:
    client, adapter = make_client(
        [response(200, {"temperature": 29}, headers={"Expires": "Sun, 24 Aug 2026 08:00:00 GMT"})],
        settings,
    )

    result = client.get_json(
        endpoint="current_weather",
        base_url="https://api.weathercn.example",
        path="v1/current",
        params={"location": "徐汇 / A+B", "accessKey": "a+b/="},
    )

    assert result == HttpResult(
        payload={"temperature": 29},
        status_code=200,
        expires="Sun, 24 Aug 2026 08:00:00 GMT",
        fetched_at=UTC_NOW,
    )
    prepared = adapter.requests[0]
    assert prepared.method == "GET"
    assert urlsplit(prepared.url or "").path == "/v1/current"
    assert parse_qs(urlsplit(prepared.url or "").query) == {
        "location": ["徐汇 / A+B"],
        "accessKey": ["a+b/="],
    }
    assert prepared.headers["Accept-Encoding"] == "gzip, deflate"
    assert adapter.timeouts == [(2.5, 7.5)]


@pytest.mark.parametrize(
    ("base_url", "path"),
    [
        ("http://api.weathercn.example", "v1/current"),
        ("https://api.weathercn.example", "/v1/current"),
        ("https://api.weathercn.example", "https://attacker.example/data"),
    ],
)
def test_rejects_non_https_or_non_relative_paths(
    settings: Settings, base_url: str, path: str
) -> None:
    client, adapter = make_client([], settings)

    with pytest.raises(ValueError):
        client.get_json(endpoint="current_weather", base_url=base_url, path=path)

    assert adapter.requests == []


def test_request_budget_rejects_the_attempt_after_the_limit() -> None:
    budget = RequestBudget(max_calls=2)

    budget.consume("weather")
    budget.consume("air_quality")

    assert budget.calls == 2
    with pytest.raises(CallLimitExceeded) as error:
        budget.consume("forecast")
    assert error.value.endpoint == "forecast"
    assert error.value.max_calls == 2


def test_call_count_starts_at_zero_tracks_success_and_is_read_only(settings: Settings) -> None:
    client, adapter = make_client([response(200, {"ok": True})], settings)

    assert client.call_count == 0

    client.get_json("weather", "https://api.weathercn.example", "v1/current")

    assert client.call_count == 1
    assert len(adapter.requests) == 1
    with pytest.raises(AttributeError):
        client.call_count = 99  # type: ignore[misc]


def test_retry_attempt_also_consumes_request_budget() -> None:
    limited_settings = Settings(max_calls_per_run=1, max_retries=2, min_interval_seconds=0)
    client, adapter = make_client([response(503)], limited_settings)

    assert client.call_count == 0

    with pytest.raises(CallLimitExceeded):
        client.get_json(
            endpoint="current_weather",
            base_url="https://api.weathercn.example",
            path="v1/current",
        )

    assert len(adapter.requests) == 1
    assert client.call_count == 1


def test_first_attempt_is_immediate_and_later_attempts_are_throttled(
    settings: Settings,
) -> None:
    sleeps: list[float] = []
    uniform_calls: list[tuple[float, float]] = []

    def uniform(start: float, end: float) -> float:
        uniform_calls.append((start, end))
        return 0.2

    client, _adapter = make_client(
        [response(200, {"id": 1}), response(200, {"id": 2})],
        settings,
        sleep_fn=sleeps.append,
        uniform_fn=uniform,
    )

    client.get_json("first", "https://api.weathercn.example", "v1/first")
    client.get_json("second", "https://api.weathercn.example", "v1/second")

    assert sleeps == [1.2]
    assert uniform_calls == [(0.0, 0.25)]


@pytest.mark.parametrize(
    "first_outcome",
    [
        response(500),
        requests.Timeout("timeout at https://api.weathercn.example?apikey=secret"),
        requests.ConnectionError("failed with Secret=secret"),
    ],
)
def test_retries_temporary_failures_then_returns_success(
    settings: Settings, first_outcome: Response | requests.RequestException
) -> None:
    sleeps: list[float] = []
    client, adapter = make_client(
        [first_outcome, response(200, {"ok": True})], settings, sleep_fn=sleeps.append
    )

    result = client.get_json("weather", "https://api.weathercn.example", "v1/current")

    assert result.payload == {"ok": True}
    assert len(adapter.requests) == 2
    assert client.call_count == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_client_errors_fail_immediately_without_retry(settings: Settings, status_code: int) -> None:
    client, adapter = make_client([response(status_code), response(200, {})], settings)

    with pytest.raises(ApiRequestError) as error:
        client.get_json("weather", "https://api.weathercn.example", "v1/current")

    assert error.value.endpoint == "weather"
    assert error.value.status_code == status_code
    assert error.value.retry_after is None
    assert len(adapter.requests) == 1


def test_429_exposes_retry_after_and_does_not_retry(settings: Settings) -> None:
    client, adapter = make_client(
        [response(429, headers={"Retry-After": "120"}), response(200, {})], settings
    )

    with pytest.raises(ApiRequestError) as error:
        client.get_json("weather", "https://api.weathercn.example", "v1/current")

    assert error.value.status_code == 429
    assert error.value.retry_after == "120"
    assert len(adapter.requests) == 1


def test_malformed_json_has_explicit_sanitized_error(settings: Settings) -> None:
    client, _adapter = make_client([response(200, raw_body=b"not-json")], settings)

    with pytest.raises(ApiRequestError, match="JSON") as error:
        client.get_json(
            "weather",
            "https://api.weathercn.example",
            "v1/current",
            params={"apikey": "top-secret"},
            headers={"X-Gw-API-Key": "header-secret"},
        )

    message = str(error.value)
    for secret in (
        "top-secret",
        "header-secret",
        "apikey",
        "accessKey",
        "Secret",
        "X-Gw-API-Key",
        "https://",
    ):
        assert secret not in message


def test_exhausted_network_error_does_not_expose_exception_details(settings: Settings) -> None:
    errors: Iterator[requests.RequestException] = iter(
        requests.Timeout("https://api.weathercn.example?accessKey=leaked")
        for _ in range(settings.max_retries + 1)
    )
    client, adapter = make_client(list(errors), settings)

    with pytest.raises(ApiRequestError) as error:
        client.get_json(
            "weather",
            "https://api.weathercn.example",
            "v1/current",
            headers={"Secret": "header-secret"},
        )

    assert error.value.status_code is None
    assert len(adapter.requests) == settings.max_retries + 1
    message = str(error.value)
    assert "https://" not in message
    assert "leaked" not in message
    assert "header-secret" not in message


def test_error_message_does_not_trust_endpoint_as_safe(settings: Settings) -> None:
    client, _adapter = make_client([response(401)], settings)
    unsafe_endpoint = "https://api.weathercn.example/current?apikey=top-secret"

    with pytest.raises(ApiRequestError) as error:
        client.get_json(
            unsafe_endpoint,
            "https://api.weathercn.example",
            "v1/current",
        )

    assert error.value.endpoint == unsafe_endpoint
    assert "https://" not in str(error.value)
    assert "apikey" not in str(error.value)
    assert "top-secret" not in str(error.value)

    budget = RequestBudget(max_calls=1)
    budget.consume("weather")
    with pytest.raises(CallLimitExceeded) as budget_error:
        budget.consume(unsafe_endpoint)
    assert budget_error.value.endpoint == unsafe_endpoint
    assert "https://" not in str(budget_error.value)
    assert "apikey" not in str(budget_error.value)
    assert "top-secret" not in str(budget_error.value)
