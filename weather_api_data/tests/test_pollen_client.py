from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest
import requests

from weather_api_data.config import Settings
from weather_api_data.pollen_client import (
    PollenApiError,
    PollenClient,
    PollenRunStopped,
    parse_pollen_forecast,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pollen_forecast.json"
FIXED_NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        outcome = self.responses.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _payload() -> object:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "pollen_enabled": True,
        "pollen_api_key": "secret-placeholder",
        "pollen_max_calls_per_run": 60,
        "pollen_min_interval_seconds": 0.0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_fixture_parser_preserves_missing_pollen_types_as_no_data() -> None:
    days = parse_pollen_forecast(_payload())

    assert [day.forecast_date for day in days] == ["2026-08-26", "2026-08-27"]
    first = days[0]
    assert first.pollen_types["GRASS"].index_value == 3
    assert first.pollen_types["GRASS"].index_code == "MODERATE"
    assert first.pollen_types["GRASS"].status == "ok"
    assert first.pollen_types["TREE"].index_value is None
    assert first.pollen_types["TREE"].status == "no_data"
    assert first.pollen_types["WEED"].status == "no_data"


def test_client_uses_google_lookup_contract_without_putting_key_in_url() -> None:
    session = FakeSession([FakeResponse(200, _payload(), headers={"Expires": "soon"})])
    client = PollenClient(
        cast(requests.Session, session),
        _settings(),
        utcnow_fn=lambda: FIXED_NOW,
    )

    result = client.lookup(latitude=31.2, longitude=121.44, days=5)

    assert result.status == "ok"
    assert result.fetched_at == FIXED_NOW
    assert result.expires == "soon"
    assert len(result.days) == 2
    assert client.call_count == 1
    url, kwargs = session.calls[0]
    assert url == "https://pollen.googleapis.com/v1/forecast:lookup"
    assert "secret-placeholder" not in url
    assert kwargs["params"] == {
        "key": "secret-placeholder",
        "location.latitude": 31.2,
        "location.longitude": 121.44,
        "days": 5,
        "languageCode": "zh-CN",
    }
    assert kwargs["timeout"] == (5.0, 20.0)


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_terminal_http_status_stops_later_requests(status_code: int) -> None:
    session = FakeSession(
        [FakeResponse(status_code, {"error": {"message": "contains sensitive detail"}})]
    )
    client = PollenClient(cast(requests.Session, session), _settings())

    with pytest.raises(PollenApiError) as first_error:
        client.lookup(latitude=31.2, longitude=121.44)

    assert first_error.value.status_code == status_code
    assert "sensitive" not in str(first_error.value)
    with pytest.raises(PollenRunStopped) as stopped_error:
        client.lookup(latitude=31.21, longitude=121.45)
    assert stopped_error.value.status_code == status_code
    assert len(session.calls) == 1


def test_429_preserves_retry_after_without_response_body() -> None:
    session = FakeSession([FakeResponse(429, {"error": "private"}, headers={"Retry-After": "120"})])
    client = PollenClient(cast(requests.Session, session), _settings())

    with pytest.raises(PollenApiError) as error:
        client.lookup(latitude=31.2, longitude=121.44)

    assert error.value.retry_after == "120"
    assert "private" not in str(error.value)


def test_budget_is_independent_and_checked_before_network() -> None:
    session = FakeSession([FakeResponse(200, _payload())])
    client = PollenClient(
        cast(requests.Session, session),
        _settings(pollen_max_calls_per_run=1),
    )

    client.lookup(latitude=31.2, longitude=121.44)
    with pytest.raises(PollenRunStopped, match="调用预算"):
        client.lookup(latitude=31.21, longitude=121.45)

    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dailyInfo": []},
        {"dailyInfo": [{"date": {"year": 2026, "month": 8}}]},
    ],
)
def test_missing_daily_fields_return_no_data_without_crashing(payload: object) -> None:
    session = FakeSession([FakeResponse(200, payload)])
    client = PollenClient(cast(requests.Session, session), _settings())

    result = client.lookup(latitude=31.2, longitude=121.44)

    assert result.status == "no_data"
    assert result.days == ()


def test_valid_date_without_any_index_keeps_day_but_marks_result_no_data() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "dailyInfo": [
                        {
                            "date": {"year": 2026, "month": 8, "day": 26},
                            "pollenTypeInfo": [{"code": "GRASS", "inSeason": False}],
                        }
                    ]
                },
            )
        ]
    )
    client = PollenClient(cast(requests.Session, session), _settings())

    result = client.lookup(latitude=31.2, longitude=121.44)

    assert len(result.days) == 1
    assert result.days[0].pollen_types["GRASS"].status == "no_data"
    assert result.status == "no_data"


def test_network_error_is_sanitized_but_does_not_halt_run() -> None:
    session = FakeSession(
        [requests.Timeout("secret connection detail"), FakeResponse(200, _payload())]
    )
    client = PollenClient(cast(requests.Session, session), _settings())

    with pytest.raises(PollenApiError, match="网络错误") as error:
        client.lookup(latitude=31.2, longitude=121.44)

    assert error.value.status_code is None
    assert "secret" not in str(error.value)
    assert client.lookup(latitude=31.21, longitude=121.45).status == "ok"
