from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

import pytest
import requests

from weather_api_data.advanced_client import AdvancedClient
from weather_api_data.advanced_signer import AdvancedSigner, SignedAuth
from weather_api_data.config import ConfigurationError, Settings
from weather_api_data.http_client import ApiRequestError, HttpClient, HttpResult
from weather_api_data.standard_client import StandardClient

ParamValue = str | bytes | int | float | Sequence[str | bytes | int | float] | None


@dataclass(frozen=True, slots=True)
class CapturedCall:
    endpoint: str
    base_url: str
    path: str
    params: dict[str, ParamValue]
    headers: dict[str, str]


class FakeHttpClient(HttpClient):
    """仅替代传输边界并完整记录客户端交给 requests 的输入。"""

    def __init__(self, outcomes: list[HttpResult | BaseException] | None = None) -> None:
        self.calls: list[CapturedCall] = []
        self.outcomes = list(outcomes or [])

    def get_json(
        self,
        endpoint: str,
        base_url: str,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
        headers: dict[str, str] | None = None,
        max_retries_override: int | None = None,
    ) -> HttpResult:
        del max_retries_override
        self.calls.append(
            CapturedCall(
                endpoint=endpoint,
                base_url=base_url,
                path=path,
                params=dict(params or {}),
                headers=dict(headers or {}),
            )
        )
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return HttpResult(
            payload={"endpoint": endpoint},
            status_code=200,
            expires=None,
            fetched_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )


@dataclass(slots=True)
class FakeResponse:
    status_code: int
    payload: object
    headers: dict[str, str]

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, outcomes: list[FakeResponse | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        del url, kwargs
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def real_http_client(settings: Settings, session: FakeSession) -> HttpClient:
    return HttpClient(
        cast(requests.Session, session),
        settings,
        sleep_fn=lambda _seconds: None,
        uniform_fn=lambda _low, _high: 0.0,
    )


class RecordingSigner:
    def __init__(self) -> None:
        self.content_types: list[str] = []

    def sign(self, api_content_type: str, now_utc: datetime | None = None) -> SignedAuth:
        del now_utc
        self.content_types.append(api_content_type)
        return SignedAuth(request_date="20260824073", access_key="raw+/=access")


@pytest.fixture
def advanced_settings() -> Settings:
    return Settings(advanced_api_key="raw-api-key", advanced_secret="raw-secret")


def make_advanced_client(
    settings: Settings,
) -> tuple[AdvancedClient, FakeHttpClient, RecordingSigner]:
    http = FakeHttpClient()
    signer = RecordingSigner()
    client = AdvancedClient(settings, http, signer=cast(AdvancedSigner, signer))
    return client, http, signer


@pytest.mark.parametrize(
    ("method_name", "args", "path", "content_type", "extra_params"),
    [
        (
            "geoposition",
            (31.2345, 121.2344),
            "locations/v1/cities/geoposition/search",
            "locations",
            {"q": "31.235,121.234"},
        ),
        (
            "current_conditions",
            ("101021200",),
            "currentconditions/v1/101021200",
            "currentconditions",
            {"details": "true"},
        ),
        (
            "historical_24",
            ("101021200",),
            "currentconditions/v1/101021200/historical/24",
            "currentconditions",
            {"details": "true"},
        ),
        (
            "hourly_weather_24",
            ("101021200",),
            "forecasts/v1/hourly/24hour/101021200",
            "forecasts",
            {"details": "true", "metric": "true"},
        ),
        (
            "current_air_quality",
            ("101021200",),
            "airquality/v1/global/observations/101021200",
            "airquality",
            {},
        ),
        (
            "hourly_air_quality_24",
            ("101021200",),
            "airqualityforecast/v1/hourly/24hour/101021200",
            "airqualityforecast",
            {},
        ),
        (
            "indices_1day",
            ("101021200",),
            "indices/v1/daily/1day/101021200/groups/100",
            "indices",
            {"details": "true"},
        ),
        (
            "indices_5day",
            ("101021200",),
            "indices/v1/daily/5day/101021200/groups/100",
            "indices",
            {"details": "true"},
        ),
        (
            "alerts",
            ("101021200",),
            "alerts/v1/101021200",
            "alerts",
            {"details": "true"},
        ),
        (
            "climo_actuals",
            ("101021200", 2025, 8),
            "climo/v1/actuals/101021200",
            "climo",
            {"start": "2025/08/01", "end": "2025/08/31"},
        ),
    ],
)
def test_advanced_methods_build_exact_paths_signatures_and_params(
    advanced_settings: Settings,
    method_name: str,
    args: tuple[object, ...],
    path: str,
    content_type: str,
    extra_params: dict[str, str],
) -> None:
    client, http, signer = make_advanced_client(advanced_settings)

    result = getattr(client, method_name)(*args)

    assert result.status_code == 200
    assert signer.content_types == [content_type]
    assert http.calls == [
        CapturedCall(
            endpoint=method_name,
            base_url=advanced_settings.advanced_base_url,
            path=path,
            params={
                "apikey": "raw-api-key",
                "requestDate": "20260824073",
                "accessKey": "raw+/=access",
                "language": "zh-CN",
                **extra_params,
            },
            headers={},
        )
    ]


def test_advanced_client_validates_credentials_even_with_injected_signer() -> None:
    with pytest.raises(ConfigurationError, match="WEATHERCN_ADVANCED_API_KEY"):
        AdvancedClient(
            Settings(advanced_secret="raw-secret"),
            FakeHttpClient(),
            signer=cast(AdvancedSigner, RecordingSigner()),
        )


@pytest.mark.parametrize("location_key", ["", "101/021", "101\\021", "101 021", "101\t021"])
def test_advanced_client_rejects_unsafe_location_keys_before_transport(
    advanced_settings: Settings, location_key: str
) -> None:
    client, http, signer = make_advanced_client(advanced_settings)

    with pytest.raises(ValueError, match="LocationKey"):
        client.current_conditions(location_key)

    assert http.calls == []
    assert signer.content_types == []


@pytest.mark.parametrize(
    ("year", "month"),
    [(2024, 1), (2026, 1), (2025, 0), (2025, 13)],
)
def test_climo_actuals_rejects_out_of_scope_dates_before_signing(
    advanced_settings: Settings, year: int, month: int
) -> None:
    client, http, signer = make_advanced_client(advanced_settings)

    with pytest.raises(ValueError):
        client.climo_actuals("101021200", year, month)

    assert http.calls == []
    assert signer.content_types == []


def test_disabled_standard_client_rejects_before_transport() -> None:
    http = FakeHttpClient()
    client = StandardClient(Settings(standard_enabled=False), http)

    with pytest.raises(ConfigurationError, match="未启用"):
        client.probe_geoposition(31.2345, 121.2344)

    assert http.calls == []
    assert client.closed is False


def test_enabled_standard_client_validates_api_key_at_initialization() -> None:
    with pytest.raises(ConfigurationError, match="WEATHERCN_STANDARD_API_KEY"):
        StandardClient(Settings(standard_enabled=True), FakeHttpClient())


def test_standard_probe_uses_verified_query_authentication_without_language() -> None:
    settings = Settings(standard_enabled=True, standard_api_key="standard-secret")
    http = FakeHttpClient()
    client = StandardClient(settings, http)

    result = client.probe_geoposition(31.2345, 121.2344)

    assert result.status_code == 200
    assert http.calls == [
        CapturedCall(
            endpoint="probe_geoposition",
            base_url=settings.standard_base_url,
            path="locations/v1/cities/geoposition/search.json",
            params={
                "q": "31.235,121.234",
                "apikey": "standard-secret",
            },
            headers={},
        )
    ]
    assert "language" not in http.calls[0].params
    assert client.closed is True


def test_standard_client_allows_only_one_http_attempt() -> None:
    settings = Settings(standard_enabled=True, standard_api_key="standard-secret")
    http = FakeHttpClient()
    client = StandardClient(settings, http)

    client.probe_geoposition(31.2345, 121.2344)

    with pytest.raises(ConfigurationError, match="已关闭"):
        client.probe_geoposition(31.2345, 121.2344)
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    "first_error",
    [
        ApiRequestError(endpoint="probe_geoposition", status_code=403),
        RuntimeError("unexpected transport failure"),
    ],
)
def test_standard_client_closes_after_any_first_attempt_error(first_error: BaseException) -> None:
    settings = Settings(standard_enabled=True, standard_api_key="standard-secret")
    http = FakeHttpClient([first_error])
    client = StandardClient(settings, http)

    assert client.closed is False
    with pytest.raises(type(first_error)):
        client.probe_geoposition(31.2345, 121.2344)
    assert client.closed is True

    with pytest.raises(ConfigurationError, match="已关闭"):
        client.probe_geoposition(31.2345, 121.2344)
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("simulated connection failure"),
        FakeResponse(status_code=503, payload={"error": "temporary"}, headers={}),
    ],
    ids=["network", "server-error"],
)
def test_standard_probe_never_retries_transport_failure(
    failure: BaseException | FakeResponse,
) -> None:
    settings = Settings(
        standard_enabled=True,
        standard_api_key="standard-secret",
        max_retries=2,
        min_interval_seconds=0,
        jitter_max_seconds=0,
    )
    session = FakeSession([failure, FakeResponse(200, {"unexpected": True}, {})])
    client = StandardClient(settings, real_http_client(settings, session))

    with pytest.raises(ApiRequestError):
        client.probe_geoposition(31.2345, 121.2344)

    assert session.calls == 1
    assert client.closed is True


def test_standard_probe_success_uses_exactly_one_transport_attempt() -> None:
    settings = Settings(
        standard_enabled=True,
        standard_api_key="standard-secret",
        max_retries=2,
        min_interval_seconds=0,
        jitter_max_seconds=0,
    )
    session = FakeSession([FakeResponse(200, {"Key": "101021200"}, {})])
    client = StandardClient(settings, real_http_client(settings, session))

    result = client.probe_geoposition(31.2345, 121.2344)

    assert result.payload == {"Key": "101021200"}
    assert session.calls == 1
    assert client.closed is True


def test_advanced_client_keeps_configured_default_retries(advanced_settings: Settings) -> None:
    settings = Settings(
        advanced_api_key=advanced_settings.advanced_api_key,
        advanced_secret=advanced_settings.advanced_secret,
        max_retries=2,
        min_interval_seconds=0,
        jitter_max_seconds=0,
    )
    session = FakeSession(
        [
            FakeResponse(503, {"error": "temporary"}, {}),
            FakeResponse(200, [{"WeatherText": "Sunny"}], {}),
        ]
    )
    signer = RecordingSigner()
    client = AdvancedClient(
        settings,
        real_http_client(settings, session),
        signer=cast(AdvancedSigner, signer),
    )

    result = client.current_conditions("101021200")

    assert result.status_code == 200
    assert session.calls == 2


@pytest.mark.parametrize("override", [-1, 3])
def test_http_retry_override_rejects_values_outside_configured_range(override: int) -> None:
    settings = Settings(max_retries=2, min_interval_seconds=0, jitter_max_seconds=0)
    session = FakeSession([FakeResponse(200, {}, {})])
    http = real_http_client(settings, session)

    with pytest.raises(ValueError, match="重试"):
        http.get_json(
            "test",
            settings.advanced_base_url,
            "test/path",
            max_retries_override=override,
        )

    assert session.calls == 0
