from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, cast

import pytest
import requests

from weather_api_data.shanghai_sthj_client import (
    ShanghaiSthjBatchResult,
    ShanghaiSthjClient,
    ShanghaiSthjFetchResult,
    ShanghaiSthjRequestError,
    ShanghaiSthjResponseError,
)
from weather_api_data.shanghai_sthj_normalizer import normalize_station_observation

FIXED_NOW = datetime(2026, 8, 25, 1, 2, 3, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        text: str = "response-body",
        payload: object = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(
        self,
        get_outcome: FakeResponse | BaseException,
        post_outcomes: list[FakeResponse | BaseException],
    ) -> None:
        self.get_outcome = get_outcome
        self.post_outcomes = list(post_outcomes)
        self.get_calls: list[tuple[str, dict[str, object]]] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        if isinstance(self.get_outcome, BaseException):
            raise self.get_outcome
        return self.get_outcome

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        outcome = self.post_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _page(latest_time: str = "2026-08-24 18:00:00") -> FakeResponse:
    return FakeResponse(
        200,
        text=f"<script>var lastLstAqiStr = '{latest_time}';</script>",
    )


def _payload(observed_at: str = "2026-08-24 18:00:00") -> dict[str, object]:
    return {
        "100": [{"lstAqi": observed_at, "aqi": "42", "siteId": "80"}],
        "101": [
            {
                "lstAqi": observed_at,
                "value": "0.017",
                "aqi": "24",
                "siteId": "80",
            }
        ],
    }


def test_client_uses_one_session_and_exact_request_contract_for_default_stations() -> None:
    session = FakeSession(
        _page(),
        [
            FakeResponse(200, payload=_payload()),
            FakeResponse(200, payload=_payload()),
            FakeResponse(404, text="not found"),
        ],
    )
    client = ShanghaiSthjClient(
        cast(requests.Session, session),
        timeout=(4.0, 12.0),
        utcnow_fn=lambda: FIXED_NOW,
    )

    batch = client.fetch_stations()
    results = batch.results

    assert isinstance(batch, ShanghaiSthjBatchResult)
    assert batch.errors == ()
    assert batch.request_count == 4
    assert [result.station_id for result in results] == ["80", "207", "1"]
    assert [result.status for result in results] == ["ok", "ok", "no_data"]
    assert [result.status_code for result in results] == [200, 200, 404]
    assert session.get_calls == [(client.DETAIL_PAGE_URL, {"timeout": (4.0, 12.0)})]
    assert [call[1]["data"] for call in session.post_calls] == [
        {"lstAqi": "2026-08-24 18:00:00", "siteId": station_id} for station_id in ("80", "207", "1")
    ]
    for url, kwargs in session.post_calls:
        assert url == client.HOURLY_DATA_URL
        assert kwargs["timeout"] == (4.0, 12.0)
        assert kwargs["headers"] == {
            "Referer": client.DETAIL_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
    assert results[0].latest_time == "2026-08-24 18:00:00"
    assert results[0].fetched_at == FIXED_NOW
    assert results[0].source_url == client.HOURLY_DATA_URL


def test_client_maps_blank_success_response_to_no_data() -> None:
    session = FakeSession(_page(), [FakeResponse(200, text="   ")])

    batch = ShanghaiSthjClient(cast(requests.Session, session)).fetch_stations(("80",))
    result = batch.results[0]

    assert result.status == "no_data"
    assert result.status_code == 200
    assert result.payload is None


def test_client_rejects_detail_page_without_latest_time() -> None:
    session = FakeSession(FakeResponse(200, text="<html>changed page</html>"), [])

    with pytest.raises(ShanghaiSthjResponseError, match="lastLstAqiStr"):
        ShanghaiSthjClient(cast(requests.Session, session)).fetch_stations(("80",))

    assert session.post_calls == []


def test_client_wraps_request_exception_with_station_context() -> None:
    session = FakeSession(_page(), [requests.Timeout("socket timed out")])

    batch = ShanghaiSthjClient(cast(requests.Session, session)).fetch_stations(("207",))
    error = batch.errors[0]

    assert isinstance(error, ShanghaiSthjRequestError)
    assert error.station_id == "207"
    assert "207" in str(error)
    assert "socket timed out" not in str(error)
    assert batch.results == ()
    assert batch.request_count == 2


def test_client_preserves_successful_stations_when_one_station_fails() -> None:
    session = FakeSession(
        _page(),
        [
            FakeResponse(200, payload=_payload()),
            FakeResponse(500, text="server error"),
            FakeResponse(200, payload=_payload()),
        ],
    )

    batch = ShanghaiSthjClient(cast(requests.Session, session)).fetch_stations()

    assert [result.station_id for result in batch.results] == ["80", "1"]
    assert len(batch.errors) == 1
    assert isinstance(batch.errors[0], ShanghaiSthjResponseError)
    assert batch.errors[0].station_id == "207"
    assert batch.request_count == 4


def test_normalizer_selects_latest_business_time_from_both_array_orders() -> None:
    payload = {
        "100": [
            {"lstAqi": "2026-08-24 17:00:00", "aqi": "35"},
            {"lstAqi": "2026-08-24 18:00:00", "aqi": "42"},
        ],
        "101": [
            {"lstAqi": "2026-08-24 18:00:00", "value": "0.017", "aqi": "24"},
            {"lstAqi": "2026-08-24 17:00:00", "value": "0.012", "aqi": "17"},
        ],
    }
    result = ShanghaiSthjFetchResult(
        station_id="80",
        latest_time="2026-08-24 18:00:00",
        status_code=200,
        payload=payload,
        fetched_at=FIXED_NOW,
        source_url="https://example.test/hourly",
        status="ok",
    )

    record = normalize_station_observation(
        result,
        zone_ids=("xuhui", "west-riverfront"),
    )

    assert record["observed_at"] == "2026-08-24T18:00:00+08:00"
    assert record["values"] == {
        "aqi": 42,
        "pm2_5_ug_m3": 17.0,
        "pm2_5_iaqi": 24,
    }


def test_normalizer_rejects_payload_from_another_station() -> None:
    result = ShanghaiSthjFetchResult(
        station_id="207",
        latest_time="2026-08-24 18:00:00",
        status_code=200,
        payload=_payload(),
        fetched_at=FIXED_NOW,
        source_url="https://example.test/hourly",
        status="ok",
    )

    record = normalize_station_observation(result, zone_ids=("station-zone",))

    assert record["spatial_id"] == "207"
    assert record["status"] == "partial"
    assert record["observed_at"] is None
    assert record["values"] == {}


def test_normalizer_maps_required_metadata_units_and_raw_data() -> None:
    payload = _payload()
    for pollutant_id in ("100", "101"):
        records = cast(list[dict[str, object]], payload[pollutant_id])
        for record in records:
            record["siteId"] = "207"
    result = ShanghaiSthjFetchResult(
        station_id="207",
        latest_time="2026-08-24 18:00:00",
        status_code=200,
        payload=payload,
        fetched_at=FIXED_NOW,
        source_url="https://example.test/hourly",
        status="ok",
    )

    record = normalize_station_observation(result, zone_ids=("xuhui",))

    assert record == {
        "provider": "shanghai_sthj",
        "data_role": "station_observation",
        "spatial_basis": "station",
        "spatial_id": "207",
        "zone_ids": ["xuhui"],
        "observed_at": "2026-08-24T18:00:00+08:00",
        "fetched_at": "2026-08-25T01:02:03+00:00",
        "values": {"aqi": 42, "pm2_5_ug_m3": 17.0, "pm2_5_iaqi": 24},
        "units": {"aqi": "index", "pm2_5_ug_m3": "ug/m3", "pm2_5_iaqi": "index"},
        "status": "ok",
        "is_estimated": False,
        "components": [],
        "source_url": "https://example.test/hourly",
        "raw_data": payload,
    }


@pytest.mark.parametrize(
    ("payload", "fetch_status", "expected_status"),
    [
        (None, "no_data", "no_data"),
        ({"100": [], "101": []}, "ok", "no_data"),
        ({"100": [{"aqi": "42"}], "101": []}, "ok", "partial"),
    ],
)
def test_normalizer_marks_missing_observation_data(
    payload: object,
    fetch_status: Literal["ok", "no_data"],
    expected_status: str,
) -> None:
    result = ShanghaiSthjFetchResult(
        station_id="1",
        latest_time="2026-08-24 18:00:00",
        status_code=404 if fetch_status == "no_data" else 200,
        payload=payload,
        fetched_at=FIXED_NOW,
        source_url="https://example.test/hourly",
        status=fetch_status,
    )

    record = normalize_station_observation(result, zone_ids=())

    assert record["status"] == expected_status
    assert record["spatial_id"] == "1"
    assert record["is_estimated"] is False
