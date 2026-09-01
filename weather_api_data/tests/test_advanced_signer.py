from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from weather_api_data.advanced_signer import AdvancedSigner, SignedAuth


def test_sign_uses_crlf_hmac_md5_and_raw_base64() -> None:
    signer = AdvancedSigner(api_key="test-api-key", secret="test-secret")
    now_utc = datetime(2026, 8, 24, 12, 34, 56, tzinfo=timezone.utc)

    signed = signer.sign("currentconditions", now_utc=now_utc)

    assert signed == SignedAuth(
        request_date="20260824123",
        access_key="F37dHOv2WqAQ3Gjv+83gKw==",
    )
    assert "+" in signed.access_key
    assert signed.access_key.endswith("==")
    assert "%" not in signed.access_key


def test_request_date_uses_ten_minute_utc_time_slice() -> None:
    signer = AdvancedSigner(api_key="test-api-key", secret="test-secret")

    first = signer.sign("airquality", datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc))
    same_slice = signer.sign("airquality", datetime(2026, 8, 24, 12, 39, 59, tzinfo=timezone.utc))
    next_slice = signer.sign("airquality", datetime(2026, 8, 24, 12, 40, tzinfo=timezone.utc))

    assert first.request_date == "20260824123"
    assert same_slice.request_date == first.request_date
    assert next_slice.request_date == "20260824124"


def test_sign_converts_aware_time_to_utc() -> None:
    signer = AdvancedSigner(api_key="test-api-key", secret="test-secret")
    china_time = datetime(2026, 8, 25, 0, 4, tzinfo=timezone(timedelta(hours=8)))

    signed = signer.sign("forecasts24hour", now_utc=china_time)

    assert signed.request_date == "20260824160"


@pytest.mark.parametrize("api_content_type", ("CurrentConditions", "current/v1"))
def test_sign_rejects_uppercase_and_path_content_types(api_content_type: str) -> None:
    signer = AdvancedSigner(api_key="test-api-key", secret="test-secret")

    with pytest.raises(ValueError, match="api_content_type"):
        signer.sign(api_content_type)


def test_sign_rejects_naive_datetime() -> None:
    signer = AdvancedSigner(api_key="test-api-key", secret="test-secret")

    with pytest.raises(ValueError, match="时区"):
        signer.sign("indices", now_utc=datetime(2026, 8, 24, 12, 34))


def test_signed_auth_is_immutable() -> None:
    signed = SignedAuth(request_date="20260824123", access_key="placeholder")

    with pytest.raises(FrozenInstanceError):
        signed.request_date = "20260824124"  # type: ignore[misc]
