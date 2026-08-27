from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import MappingProxyType
from typing import cast

import pytest
import requests

from weather_api_data.shanghai_noise_client import (
    SHANGHAI_NOISE_API_URL,
    ShanghaiNoiseClient,
    ShanghaiNoiseRequestError,
    ShanghaiNoiseResponseError,
)

FIXED_NOW = datetime(2026, 8, 27, 1, 2, 3, tzinfo=timezone.utc)
TOKEN = "secret-token-placeholder"


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, outcomes: list[FakeResponse | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _success(data: str | dict[str, object]) -> dict[str, object]:
    return {"code": "000000", "message": "成功", "data": data}


def test_fetch_posts_exact_contract_and_parses_string_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = _success(
        '{"state":true,"message":"","total":2,"data":'
        '[{"siteName":"龙华","leq":55.2},{"siteName":"徐家汇","leq":61.4}]}'
    )
    session = FakeSession([FakeResponse(200, payload)])
    client = ShanghaiNoiseClient(
        cast(requests.Session, session),
        token=TOKEN,
        timeout=(4.0, 12.0),
        utcnow_fn=lambda: FIXED_NOW,
    )

    with caplog.at_level(logging.INFO):
        result = client.fetch(
            limit=100,
            offset=20,
            query_fields={"district": "徐汇区", "year": 2025},
        )

    assert session.calls == [
        (
            SHANGHAI_NOISE_API_URL,
            {
                "json": {
                    "limit": 100,
                    "offset": 20,
                    "district": "徐汇区",
                    "year": 2025,
                },
                "headers": {"token": TOKEN},
                "timeout": (4.0, 12.0),
            },
        )
    ]
    assert result.status == "ok"
    assert result.total == 2
    assert result.fetched_at == FIXED_NOW
    assert result.source_url == SHANGHAI_NOISE_API_URL
    assert result.api_code == "000000"
    assert result.api_message == "成功"
    assert result.provider_message is None
    assert [item.raw_data["siteName"] for item in result.observations] == ["龙华", "徐家汇"]
    assert isinstance(result.observations[0].raw_data, MappingProxyType)
    assert TOKEN not in caplog.text
    assert TOKEN not in repr(client)


def test_total_zero_and_null_data_is_explicit_no_data() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                _success(
                    {
                        "state": True,
                        "message": "",
                        "total": 0,
                        "data": None,
                    }
                ),
            )
        ]
    )

    result = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN).fetch()

    assert result.status == "no_data"
    assert result.total == 0
    assert result.observations == ()
    assert session.calls[0][1]["json"] == {"limit": 10, "offset": 0}


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (101, 0), (True, 0), (10, -1), (10, False)],
)
def test_invalid_pagination_is_rejected_before_network(limit: object, offset: object) -> None:
    session = FakeSession([])
    client = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN)

    with pytest.raises(ValueError):
        client.fetch(limit=limit, offset=offset)  # type: ignore[arg-type]

    assert session.calls == []


def test_query_fields_cannot_override_pagination() -> None:
    session = FakeSession([])
    client = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN)

    with pytest.raises(ValueError, match="limit 或 offset"):
        client.fetch(query_fields={"limit": 50})

    assert session.calls == []


def test_error_code_is_exposed_without_response_message_or_token() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"code": "100003", "message": f"认证失败 {TOKEN}", "data": None},
            )
        ]
    )
    client = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN)

    with pytest.raises(ShanghaiNoiseResponseError) as captured:
        client.fetch()

    assert captured.value.api_code == "100003"
    assert captured.value.status_code == 200
    assert TOKEN not in str(captured.value)


def test_network_error_is_sanitized() -> None:
    session = FakeSession([requests.Timeout(f"connection contains {TOKEN}")])
    client = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN)

    with pytest.raises(ShanghaiNoiseRequestError) as captured:
        client.fetch()

    assert TOKEN not in str(captured.value)
    assert captured.value.source_url == SHANGHAI_NOISE_API_URL


@pytest.mark.parametrize(
    "payload",
    [
        ValueError("invalid outer json"),
        _success("not json"),
        _success({"state": False, "message": "provider rejected", "total": 0, "data": None}),
        _success({"state": True, "message": "", "total": -1, "data": []}),
        _success({"state": True, "message": "", "total": 1, "data": ["not an object"]}),
    ],
)
def test_invalid_success_payload_is_rejected(payload: object) -> None:
    session = FakeSession([FakeResponse(200, payload)])
    client = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN)

    with pytest.raises(ShanghaiNoiseResponseError):
        client.fetch()


def test_http_error_is_rejected_without_parsing_body() -> None:
    session = FakeSession([FakeResponse(503, ValueError("must not parse"))])
    client = ShanghaiNoiseClient(cast(requests.Session, session), token=TOKEN)

    with pytest.raises(ShanghaiNoiseResponseError) as captured:
        client.fetch()

    assert captured.value.status_code == 503
