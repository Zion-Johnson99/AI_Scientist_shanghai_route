from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from weather_api_data.config import ConfigurationError, Settings

WEATHERCN_ENVIRONMENT_VARIABLES = (
    "WEATHER_PROVIDER",
    "WEATHERCN_PROVIDER",
    "WEATHERCN_ADVANCED_API_KEY",
    "WEATHERCN_ADVANCED_SECRET",
    "WEATHERCN_ADVANCED_ENV",
    "WEATHERCN_ADVANCED_BASE_URL",
    "WEATHERCN_STANDARD_API_KEY",
    "WEATHERCN_STANDARD_ENABLED",
    "WEATHERCN_STANDARD_BASE_URL",
    "WEATHER_HISTORY_ENABLED",
    "WEATHER_HISTORY_RETENTION_DAYS",
    "WEATHERCN_MAX_CALLS_PER_RUN",
    "WEATHERCN_CONNECT_TIMEOUT_SECONDS",
    "WEATHERCN_READ_TIMEOUT_SECONDS",
    "WEATHERCN_MAX_RETRIES",
    "WEATHERCN_MIN_INTERVAL_SECONDS",
    "WEATHERCN_JITTER_MAX_SECONDS",
    "QWEATHER_ENABLED",
    "QWEATHER_API_KEY",
    "QWEATHER_API_HOST",
    "QWEATHER_MAX_CALLS_PER_RUN",
    "QWEATHER_CONNECT_TIMEOUT_SECONDS",
    "QWEATHER_READ_TIMEOUT_SECONDS",
    "QWEATHER_MAX_RETRIES",
    "QWEATHER_MIN_INTERVAL_SECONDS",
    "QWEATHER_REFERENCE_POINT_ID",
    "POLLEN_ENABLED",
    "POLLEN_API_KEY",
    "POLLEN_MAX_CALLS_PER_RUN",
    "POLLEN_MIN_INTERVAL_SECONDS",
    "SHANGHAI_NOISE_ENABLED",
    "SHANGHAI_NOISE_TOKEN",
    "SHANGHAI_NOISE_API_URL",
    "SHANGHAI_NOISE_PAGE_SIZE",
    "SHANGHAI_NOISE_MAX_CALLS_PER_RUN",
    "SHANGHAI_NOISE_CONNECT_TIMEOUT_SECONDS",
    "SHANGHAI_NOISE_READ_TIMEOUT_SECONDS",
    "SHANGHAI_NOISE_MIN_INTERVAL_SECONDS",
    "SHANGHAI_NOISE_MAX_AGE_HOURS",
)


@pytest.fixture(autouse=True)
def clear_weathercn_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in WEATHERCN_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def load_without_dotenv(tmp_path: Path) -> Settings:
    return Settings.from_env(env_file=tmp_path / "missing.env")


def test_settings_have_safe_defaults_and_are_immutable(tmp_path: Path) -> None:
    settings = load_without_dotenv(tmp_path)

    assert settings.provider == "advanced"
    assert settings.weather_provider == "qweather"
    assert settings.advanced_env == "test"
    assert settings.advanced_base_url == "https://apidev.weathercn.com"
    assert settings.standard_base_url == "https://openapi.weathercn.com"
    assert settings.standard_enabled is False
    assert settings.history_enabled is True
    assert settings.history_retention_days == 365
    assert settings.max_calls_per_run == 150
    assert settings.connect_timeout_seconds == 5.0
    assert settings.read_timeout_seconds == 20.0
    assert settings.max_retries == 2
    assert settings.min_interval_seconds == 1.0
    assert settings.jitter_max_seconds == 0.25
    assert settings.qweather_enabled is True
    assert settings.qweather_api_key is None
    assert settings.qweather_api_host is None
    assert settings.qweather_max_calls_per_run == 80
    assert settings.qweather_connect_timeout_seconds == 5.0
    assert settings.qweather_read_timeout_seconds == 20.0
    assert settings.qweather_max_retries == 2
    assert settings.qweather_min_interval_seconds == 0.1
    assert settings.qweather_reference_point_id == "XH_ENT_0009"
    assert settings.pollen_enabled is False
    assert settings.pollen_api_key is None
    assert settings.pollen_max_calls_per_run == 60
    assert settings.pollen_min_interval_seconds == 1.0
    assert settings.shanghai_noise_enabled is False
    assert settings.shanghai_noise_token is None
    assert settings.shanghai_noise_page_size == 100
    assert settings.shanghai_noise_max_calls_per_run == 4
    assert settings.shanghai_noise_max_age_hours == 48

    with pytest.raises(FrozenInstanceError):
        settings.max_calls_per_run = 200  # type: ignore[misc]


def test_environment_overrides_dotenv_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "WEATHERCN_ADVANCED_API_KEY=file-key",
                "WEATHERCN_ADVANCED_SECRET=file-secret",
                "WEATHERCN_ADVANCED_ENV=production",
                "WEATHERCN_ADVANCED_BASE_URL=https://api.weathercn.com",
                "WEATHERCN_STANDARD_ENABLED=true",
                "WEATHERCN_STANDARD_API_KEY=file-standard-key",
                "WEATHER_HISTORY_ENABLED=true",
                "WEATHER_HISTORY_RETENTION_DAYS=180",
                "WEATHERCN_MAX_CALLS_PER_RUN=80",
                "WEATHERCN_CONNECT_TIMEOUT_SECONDS=3.5",
                "WEATHERCN_READ_TIMEOUT_SECONDS=12",
                "WEATHERCN_MAX_RETRIES=1",
                "WEATHERCN_MIN_INTERVAL_SECONDS=1.5",
                "WEATHERCN_JITTER_MAX_SECONDS=0.1",
                "QWEATHER_ENABLED=true",
                "QWEATHER_API_KEY=file-qweather-key",
                "QWEATHER_API_HOST=https://fixture.qweatherapi.com",
                "QWEATHER_MAX_CALLS_PER_RUN=70",
                "QWEATHER_CONNECT_TIMEOUT_SECONDS=2.5",
                "QWEATHER_READ_TIMEOUT_SECONDS=8",
                "QWEATHER_MAX_RETRIES=1",
                "QWEATHER_MIN_INTERVAL_SECONDS=0.2",
                "QWEATHER_REFERENCE_POINT_ID=XH_ENT_0007",
                "POLLEN_ENABLED=true",
                "POLLEN_" + "API_KEY=file-pollen-key",
                "POLLEN_MAX_CALLS_PER_RUN=55",
                "POLLEN_MIN_INTERVAL_SECONDS=1.25",
                "SHANGHAI_NOISE_ENABLED=true",
                "SHANGHAI_NOISE_TOKEN=file-noise-token",
                "SHANGHAI_NOISE_API_URL=https://data.sh.gov.cn/interface/new-noise/1",
                "SHANGHAI_NOISE_PAGE_SIZE=80",
                "SHANGHAI_NOISE_MAX_CALLS_PER_RUN=8",
                "SHANGHAI_NOISE_CONNECT_TIMEOUT_SECONDS=3",
                "SHANGHAI_NOISE_READ_TIMEOUT_SECONDS=15",
                "SHANGHAI_NOISE_MIN_INTERVAL_SECONDS=0.5",
                "SHANGHAI_NOISE_MAX_AGE_HOURS=72",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEATHERCN_MAX_CALLS_PER_RUN", "40")

    settings = Settings.from_env(env_file=env_file)

    assert settings.advanced_api_key == "file-key"
    assert settings.advanced_secret == "file-secret"
    assert settings.advanced_env == "production"
    assert settings.advanced_base_url == "https://api.weathercn.com"
    assert settings.standard_enabled is True
    assert settings.standard_api_key == "file-standard-key"
    assert settings.history_enabled is True
    assert settings.history_retention_days == 180
    assert settings.max_calls_per_run == 40
    assert settings.connect_timeout_seconds == 3.5
    assert settings.read_timeout_seconds == 12.0
    assert settings.max_retries == 1
    assert settings.min_interval_seconds == 1.5
    assert settings.jitter_max_seconds == 0.1
    assert settings.qweather_enabled is True
    assert settings.qweather_api_key == "file-qweather-key"
    assert settings.qweather_api_host == "https://fixture.qweatherapi.com"
    assert settings.qweather_max_calls_per_run == 70
    assert settings.qweather_connect_timeout_seconds == 2.5
    assert settings.qweather_read_timeout_seconds == 8.0
    assert settings.qweather_max_retries == 1
    assert settings.qweather_min_interval_seconds == 0.2
    assert settings.qweather_reference_point_id == "XH_ENT_0007"
    assert settings.pollen_enabled is True
    assert settings.pollen_api_key == "file-pollen-key"
    assert settings.pollen_max_calls_per_run == 55
    assert settings.pollen_min_interval_seconds == 1.25
    assert settings.shanghai_noise_enabled is True
    assert settings.shanghai_noise_token == "file-noise-token"
    assert settings.shanghai_noise_page_size == 80
    assert settings.shanghai_noise_max_calls_per_run == 8
    assert settings.shanghai_noise_read_timeout_seconds == 15.0
    assert settings.shanghai_noise_max_age_hours == 72


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("WEATHERCN_ADVANCED_ENV", "staging"),
        ("WEATHERCN_ADVANCED_BASE_URL", "https://example.com"),
        ("WEATHERCN_STANDARD_BASE_URL", "https://example.com"),
        ("QWEATHER_API_HOST", "https://example.com"),
    ),
)
def test_settings_reject_non_whitelisted_domains(
    name: str, value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=name):
        load_without_dotenv(tmp_path)


def test_validate_advanced_reports_all_missing_credentials(tmp_path: Path) -> None:
    settings = load_without_dotenv(tmp_path)

    with pytest.raises(ConfigurationError) as error:
        settings.validate_advanced()

    message = str(error.value)
    assert "WEATHERCN_ADVANCED_API_KEY" in message
    assert "WEATHERCN_ADVANCED_SECRET" in message


def test_standard_credentials_are_only_required_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disabled = load_without_dotenv(tmp_path)
    disabled.validate_standard()

    monkeypatch.setenv("WEATHERCN_STANDARD_ENABLED", "true")
    enabled_without_key = load_without_dotenv(tmp_path)
    with pytest.raises(ConfigurationError, match="WEATHERCN_STANDARD_API_KEY"):
        enabled_without_key.validate_standard()

    monkeypatch.setenv("WEATHERCN_STANDARD_API_KEY", "standard-placeholder")
    enabled_with_key = load_without_dotenv(tmp_path)
    enabled_with_key.validate_standard()


def test_qweather_credentials_report_both_missing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_without_dotenv(tmp_path).validate_qweather()

    message = str(error.value)
    assert "QWEATHER_API_KEY" in message
    assert "QWEATHER_API_HOST" in message

    monkeypatch.setenv("QWEATHER_API_KEY", "qweather-placeholder")
    monkeypatch.setenv("QWEATHER_API_HOST", "https://fixture.qweatherapi.com")
    load_without_dotenv(tmp_path).validate_qweather()


def test_pollen_credentials_are_only_required_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_without_dotenv(tmp_path)
    settings.validate_pollen()

    monkeypatch.setenv("POLLEN_ENABLED", "true")
    with pytest.raises(ConfigurationError, match="POLLEN_API_KEY"):
        load_without_dotenv(tmp_path).validate_pollen()

    monkeypatch.setenv("POLLEN_API_KEY", "pollen-placeholder")
    load_without_dotenv(tmp_path).validate_pollen()


def test_shanghai_noise_credentials_are_only_required_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_without_dotenv(tmp_path).validate_shanghai_noise()

    monkeypatch.setenv("SHANGHAI_NOISE_ENABLED", "true")
    with pytest.raises(ConfigurationError, match="SHANGHAI_NOISE_TOKEN"):
        load_without_dotenv(tmp_path).validate_shanghai_noise()

    monkeypatch.setenv("SHANGHAI_NOISE_TOKEN", "noise-placeholder")
    load_without_dotenv(tmp_path).validate_shanghai_noise()


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("POLLEN_MAX_CALLS_PER_RUN", "0"),
        ("POLLEN_MAX_CALLS_PER_RUN", "61"),
        ("POLLEN_MIN_INTERVAL_SECONDS", "-0.1"),
    ),
)
def test_pollen_budget_and_throttle_are_bounded(
    name: str, value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=name):
        load_without_dotenv(tmp_path)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("QWEATHER_MAX_CALLS_PER_RUN", "0"),
        ("QWEATHER_MAX_CALLS_PER_RUN", "81"),
        ("QWEATHER_CONNECT_TIMEOUT_SECONDS", "0"),
        ("QWEATHER_READ_TIMEOUT_SECONDS", "0"),
        ("QWEATHER_MAX_RETRIES", "-1"),
        ("QWEATHER_MIN_INTERVAL_SECONDS", "-0.1"),
        ("QWEATHER_REFERENCE_POINT_ID", ""),
    ),
)
def test_qweather_runtime_limits_are_bounded(
    name: str, value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError, match=name):
        load_without_dotenv(tmp_path)


def test_repr_does_not_expose_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_values = (
        "advanced-key-placeholder",
        "advanced-secret-placeholder",
        "standard-key-placeholder",
        "qweather-key-placeholder",
        "pollen-key-placeholder",
        "noise-token-placeholder",
    )
    monkeypatch.setenv("WEATHERCN_ADVANCED_API_KEY", secret_values[0])
    monkeypatch.setenv("WEATHERCN_ADVANCED_SECRET", secret_values[1])
    monkeypatch.setenv("WEATHERCN_STANDARD_API_KEY", secret_values[2])
    monkeypatch.setenv("QWEATHER_API_KEY", secret_values[3])
    monkeypatch.setenv("POLLEN_API_KEY", secret_values[4])
    monkeypatch.setenv("SHANGHAI_NOISE_TOKEN", secret_values[5])

    rendered = repr(load_without_dotenv(tmp_path))

    assert all(value not in rendered for value in secret_values)
