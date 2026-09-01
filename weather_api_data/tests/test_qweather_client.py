from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from weather_api_data.config import Settings
from weather_api_data.http_client import ApiRequestError, HttpResult
from weather_api_data.qweather_client import QWeatherClient

FETCHED_AT = datetime(2026, 8, 26, 11, 35, tzinfo=timezone.utc)
SOURCE_ID = "qweather:31.16,121.46"
API_KEY = "fixture-qweather-key"
API_HOST = "https://fixture.qweatherapi.com"


class CapturingHttpClient:
    def __init__(self, *, failure: ApiRequestError | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure = failure

    def get_json(self, **kwargs: Any) -> HttpResult:
        self.calls.append(dict(kwargs))
        if self.failure is not None:
            raise self.failure
        return HttpResult(
            payload={"code": "200", "ok": True},
            status_code=200,
            expires=None,
            fetched_at=FETCHED_AT,
        )


def _client(http: CapturingHttpClient) -> QWeatherClient:
    settings = Settings(
        qweather_api_key=API_KEY,
        qweather_api_host=API_HOST,
    )
    return QWeatherClient(settings, http)  # type: ignore[arg-type]


def test_six_methods_build_official_paths_and_coordinate_orders() -> None:
    http = CapturingHttpClient()
    client = _client(http)

    client.current_conditions(SOURCE_ID)
    client.hourly_weather_24(SOURCE_ID)
    client.current_air_quality(SOURCE_ID)
    client.hourly_air_quality_24(SOURCE_ID)
    client.indices_3day(SOURCE_ID)
    client.alerts(SOURCE_ID)

    assert [call["endpoint"] for call in http.calls] == [
        "current_conditions",
        "hourly_weather_24",
        "current_air_quality",
        "hourly_air_quality_24",
        "indices_3day",
        "alerts",
    ]
    assert [call["path"] for call in http.calls] == [
        "weather/v1/current/31.16/121.46",
        "weather/v1/hourly/31.16/121.46",
        "airquality/v1/current/31.16/121.46",
        "airquality/v1/hourly/31.16/121.46",
        "v7/indices/3d",
        "weatheralert/v1/current/31.16/121.46",
    ]
    assert http.calls[0]["params"] == {"localTime": "true", "lang": "zh"}
    assert http.calls[1]["params"] == {"hours": 24, "localTime": "true", "lang": "zh"}
    assert http.calls[2]["params"] == {"lang": "zh"}
    assert http.calls[3]["params"] == {"lang": "zh"}
    assert http.calls[4]["params"] == {
        "location": "121.46,31.16",
        "type": "0",
        "lang": "zh",
    }
    assert http.calls[5]["params"] == {"localTime": "true", "lang": "zh"}
    assert all(call["base_url"] == API_HOST for call in http.calls)
    assert all(call["headers"] == {"X-QW-Api-Key": API_KEY} for call in http.calls)


def test_api_key_only_enters_authentication_header() -> None:
    http = CapturingHttpClient()
    client = _client(http)

    client.current_conditions(SOURCE_ID)

    call = http.calls[0]
    public_request_parts = (call["base_url"], call["path"], call.get("params"))
    assert API_KEY not in repr(public_request_parts)
    assert API_KEY not in repr(client)
    assert call["headers"]["X-QW-Api-Key"] == API_KEY


def test_transport_error_does_not_expose_api_key() -> None:
    http = CapturingHttpClient(failure=ApiRequestError("current_conditions", 401))
    client = _client(http)

    with pytest.raises(ApiRequestError) as captured:
        client.current_conditions(SOURCE_ID)

    assert captured.value.status_code == 401
    assert API_KEY not in str(captured.value)
    assert API_KEY not in repr(captured.value)


@pytest.mark.parametrize(
    "source_id",
    [
        "31.16,121.46",
        "qweather:31.161,121.46",
        "qweather:31.16,121.461",
        "qweather:91.00,121.46",
        "qweather:31.16,181.00",
        "qweather:31.16/121.46",
    ],
)
def test_invalid_source_id_is_rejected_before_transport(source_id: str) -> None:
    http = CapturingHttpClient()
    client = _client(http)

    with pytest.raises(ValueError):
        client.current_conditions(source_id)

    assert http.calls == []
