"""和风天气活动配置与 WeatherCN 历史配置校验。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ADVANCED_BASE_URLS = {
    "test": "https://apidev.weathercn.com",
    "production": "https://api.weathercn.com",
}
STANDARD_BASE_URL = "https://openapi.weathercn.com"
MAX_JITTER_SECONDS = 0.25
POLLEN_HARD_MAX_CALLS_PER_RUN = 60
QWEATHER_HARD_MAX_CALLS_PER_RUN = 80
SHANGHAI_NOISE_API_URL = "https://data.sh.gov.cn/interface/O5485687412025006/59015"
SHANGHAI_NOISE_HARD_MAX_CALLS_PER_RUN = 20


class ConfigurationError(ValueError):
    """表示数据提供方配置缺失或值越界。"""


def _parse_bool(values: dict[str, str], name: str, default: bool) -> bool:
    raw_value = values.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} 需使用 true 或 false，当前值为 {raw_value!r}")


def _parse_int(values: dict[str, str], name: str, default: int) -> int:
    raw_value = values.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} 需使用整数，当前值为 {raw_value!r}") from error


def _parse_float(values: dict[str, str], name: str, default: float) -> float:
    raw_value = values.get(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} 需使用数值，当前值为 {raw_value!r}") from error


def _optional_secret(values: dict[str, str], name: str) -> str | None:
    value = values.get(name)
    return value if value else None


def _load_values(env_file: str | Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if env_file is not None:
        for name, value in dotenv_values(env_file).items():
            if value is not None:
                values[name] = value
    values.update(
        (name, value)
        for name, value in os.environ.items()
        if name in {"WEATHER_PROVIDER", "WEATHER_HISTORY_ENABLED", "WEATHER_HISTORY_RETENTION_DAYS"}
        or name.startswith(("WEATHERCN_", "QWEATHER_", "POLLEN_", "SHANGHAI_NOISE_"))
    )
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    """气象与暴露数据不可变运行配置。"""

    provider: str = "advanced"
    weather_provider: str = "qweather"
    advanced_api_key: str | None = field(default=None, repr=False)
    advanced_secret: str | None = field(default=None, repr=False)
    advanced_env: str = "test"
    advanced_base_url: str = ADVANCED_BASE_URLS["test"]
    standard_api_key: str | None = field(default=None, repr=False)
    standard_enabled: bool = False
    standard_base_url: str = STANDARD_BASE_URL
    history_enabled: bool = True
    history_retention_days: int = 365
    max_calls_per_run: int = 150
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 20.0
    max_retries: int = 2
    min_interval_seconds: float = 1.0
    jitter_max_seconds: float = MAX_JITTER_SECONDS
    qweather_enabled: bool = True
    qweather_api_key: str | None = field(default=None, repr=False)
    qweather_api_host: str | None = None
    qweather_max_calls_per_run: int = QWEATHER_HARD_MAX_CALLS_PER_RUN
    qweather_connect_timeout_seconds: float = 5.0
    qweather_read_timeout_seconds: float = 20.0
    qweather_max_retries: int = 2
    qweather_min_interval_seconds: float = 0.1
    qweather_reference_point_id: str = "XH_ENT_0009"
    pollen_enabled: bool = False
    pollen_api_key: str | None = field(default=None, repr=False)
    pollen_max_calls_per_run: int = POLLEN_HARD_MAX_CALLS_PER_RUN
    pollen_min_interval_seconds: float = 1.0
    shanghai_noise_enabled: bool = False
    shanghai_noise_token: str | None = field(default=None, repr=False)
    shanghai_noise_api_url: str = SHANGHAI_NOISE_API_URL
    shanghai_noise_page_size: int = 100
    shanghai_noise_max_calls_per_run: int = 4
    shanghai_noise_connect_timeout_seconds: float = 5.0
    shanghai_noise_read_timeout_seconds: float = 30.0
    shanghai_noise_min_interval_seconds: float = 0.2
    shanghai_noise_max_age_hours: int = 48

    def __post_init__(self) -> None:
        if self.weather_provider != "qweather":
            raise ConfigurationError("WEATHER_PROVIDER 当前仅支持 qweather")
        if self.provider not in {"advanced", "standard"}:
            raise ConfigurationError("WEATHERCN_PROVIDER 仅支持 advanced 或 standard")

        expected_advanced_url = ADVANCED_BASE_URLS.get(self.advanced_env)
        if expected_advanced_url is None:
            raise ConfigurationError("WEATHERCN_ADVANCED_ENV 仅支持 test 或 production")
        if self.advanced_base_url not in ADVANCED_BASE_URLS.values():
            raise ConfigurationError(
                "WEATHERCN_ADVANCED_BASE_URL 仅允许 WeatherCN 进阶测试或正式域名"
            )
        if self.advanced_base_url != expected_advanced_url:
            raise ConfigurationError("WEATHERCN_ADVANCED_BASE_URL 与 WEATHERCN_ADVANCED_ENV 不匹配")
        if self.standard_base_url != STANDARD_BASE_URL:
            raise ConfigurationError(f"WEATHERCN_STANDARD_BASE_URL 固定为 {STANDARD_BASE_URL}")

        positive_values = {
            "WEATHER_HISTORY_RETENTION_DAYS": self.history_retention_days,
            "WEATHERCN_MAX_CALLS_PER_RUN": self.max_calls_per_run,
            "WEATHERCN_CONNECT_TIMEOUT_SECONDS": self.connect_timeout_seconds,
            "WEATHERCN_READ_TIMEOUT_SECONDS": self.read_timeout_seconds,
        }
        for name, value in positive_values.items():
            if value <= 0:
                raise ConfigurationError(f"{name} 需大于 0")
        if self.max_retries < 0:
            raise ConfigurationError("WEATHERCN_MAX_RETRIES 需大于或等于 0")
        if self.min_interval_seconds < 0:
            raise ConfigurationError("WEATHERCN_MIN_INTERVAL_SECONDS 需大于或等于 0")
        if not 0 <= self.jitter_max_seconds <= MAX_JITTER_SECONDS:
            raise ConfigurationError(
                f"WEATHERCN_JITTER_MAX_SECONDS 需位于 0 至 {MAX_JITTER_SECONDS} 之间"
            )
        if not 1 <= self.qweather_max_calls_per_run <= QWEATHER_HARD_MAX_CALLS_PER_RUN:
            raise ConfigurationError(
                f"QWEATHER_MAX_CALLS_PER_RUN 需位于 1 至 {QWEATHER_HARD_MAX_CALLS_PER_RUN} 之间"
            )
        qweather_positive_values = {
            "QWEATHER_CONNECT_TIMEOUT_SECONDS": self.qweather_connect_timeout_seconds,
            "QWEATHER_READ_TIMEOUT_SECONDS": self.qweather_read_timeout_seconds,
        }
        for name, value in qweather_positive_values.items():
            if value <= 0:
                raise ConfigurationError(f"{name} 需大于 0")
        if self.qweather_max_retries < 0:
            raise ConfigurationError("QWEATHER_MAX_RETRIES 需大于或等于 0")
        if self.qweather_min_interval_seconds < 0:
            raise ConfigurationError("QWEATHER_MIN_INTERVAL_SECONDS 需大于或等于 0")
        if not self.qweather_reference_point_id.strip():
            raise ConfigurationError("QWEATHER_REFERENCE_POINT_ID 需为非空点位 ID")
        if self.qweather_api_host is not None:
            _validate_qweather_api_host(self.qweather_api_host)
        if not 1 <= self.pollen_max_calls_per_run <= POLLEN_HARD_MAX_CALLS_PER_RUN:
            raise ConfigurationError(
                f"POLLEN_MAX_CALLS_PER_RUN 需位于 1 至 {POLLEN_HARD_MAX_CALLS_PER_RUN} 之间"
            )
        if self.pollen_min_interval_seconds < 0:
            raise ConfigurationError("POLLEN_MIN_INTERVAL_SECONDS 需大于或等于 0")
        if not 1 <= self.shanghai_noise_page_size <= 100:
            raise ConfigurationError("SHANGHAI_NOISE_PAGE_SIZE 需位于 1 至 100")
        if not 1 <= self.shanghai_noise_max_calls_per_run <= SHANGHAI_NOISE_HARD_MAX_CALLS_PER_RUN:
            raise ConfigurationError(
                "SHANGHAI_NOISE_MAX_CALLS_PER_RUN 需位于 1 至 "
                f"{SHANGHAI_NOISE_HARD_MAX_CALLS_PER_RUN}"
            )
        for name, value in {
            "SHANGHAI_NOISE_CONNECT_TIMEOUT_SECONDS": self.shanghai_noise_connect_timeout_seconds,
            "SHANGHAI_NOISE_READ_TIMEOUT_SECONDS": self.shanghai_noise_read_timeout_seconds,
        }.items():
            if value <= 0:
                raise ConfigurationError(f"{name} 需大于 0")
        if self.shanghai_noise_min_interval_seconds < 0:
            raise ConfigurationError("SHANGHAI_NOISE_MIN_INTERVAL_SECONDS 需大于或等于 0")
        if self.shanghai_noise_max_age_hours <= 0:
            raise ConfigurationError("SHANGHAI_NOISE_MAX_AGE_HOURS 需大于 0")
        _validate_https_endpoint(self.shanghai_noise_api_url, "SHANGHAI_NOISE_API_URL")

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        """从可选 .env 与操作系统环境变量加载配置。"""

        values = _load_values(env_file)
        advanced_env = values.get("WEATHERCN_ADVANCED_ENV", "test").strip().lower()
        default_advanced_url = ADVANCED_BASE_URLS.get(advanced_env, ADVANCED_BASE_URLS["test"])
        return cls(
            provider=values.get("WEATHERCN_PROVIDER", "advanced").strip().lower(),
            weather_provider=values.get("WEATHER_PROVIDER", "qweather").strip().lower(),
            advanced_api_key=_optional_secret(values, "WEATHERCN_ADVANCED_API_KEY"),
            advanced_secret=_optional_secret(values, "WEATHERCN_ADVANCED_SECRET"),
            advanced_env=advanced_env,
            advanced_base_url=values.get(
                "WEATHERCN_ADVANCED_BASE_URL", default_advanced_url
            ).rstrip("/"),
            standard_api_key=_optional_secret(values, "WEATHERCN_STANDARD_API_KEY"),
            standard_enabled=_parse_bool(values, "WEATHERCN_STANDARD_ENABLED", False),
            standard_base_url=values.get("WEATHERCN_STANDARD_BASE_URL", STANDARD_BASE_URL).rstrip(
                "/"
            ),
            history_enabled=_parse_bool(values, "WEATHER_HISTORY_ENABLED", True),
            history_retention_days=_parse_int(values, "WEATHER_HISTORY_RETENTION_DAYS", 365),
            max_calls_per_run=_parse_int(values, "WEATHERCN_MAX_CALLS_PER_RUN", 150),
            connect_timeout_seconds=_parse_float(values, "WEATHERCN_CONNECT_TIMEOUT_SECONDS", 5.0),
            read_timeout_seconds=_parse_float(values, "WEATHERCN_READ_TIMEOUT_SECONDS", 20.0),
            max_retries=_parse_int(values, "WEATHERCN_MAX_RETRIES", 2),
            min_interval_seconds=_parse_float(values, "WEATHERCN_MIN_INTERVAL_SECONDS", 1.0),
            jitter_max_seconds=_parse_float(
                values, "WEATHERCN_JITTER_MAX_SECONDS", MAX_JITTER_SECONDS
            ),
            qweather_enabled=_parse_bool(values, "QWEATHER_ENABLED", True),
            qweather_api_key=_optional_secret(values, "QWEATHER_API_KEY"),
            qweather_api_host=_optional_secret(values, "QWEATHER_API_HOST"),
            qweather_max_calls_per_run=_parse_int(
                values,
                "QWEATHER_MAX_CALLS_PER_RUN",
                QWEATHER_HARD_MAX_CALLS_PER_RUN,
            ),
            qweather_connect_timeout_seconds=_parse_float(
                values,
                "QWEATHER_CONNECT_TIMEOUT_SECONDS",
                5.0,
            ),
            qweather_read_timeout_seconds=_parse_float(
                values,
                "QWEATHER_READ_TIMEOUT_SECONDS",
                20.0,
            ),
            qweather_max_retries=_parse_int(values, "QWEATHER_MAX_RETRIES", 2),
            qweather_min_interval_seconds=_parse_float(
                values,
                "QWEATHER_MIN_INTERVAL_SECONDS",
                0.1,
            ),
            qweather_reference_point_id=values.get(
                "QWEATHER_REFERENCE_POINT_ID",
                "XH_ENT_0009",
            ).strip(),
            pollen_enabled=_parse_bool(values, "POLLEN_ENABLED", False),
            pollen_api_key=_optional_secret(values, "POLLEN_API_KEY"),
            pollen_max_calls_per_run=_parse_int(
                values,
                "POLLEN_MAX_CALLS_PER_RUN",
                POLLEN_HARD_MAX_CALLS_PER_RUN,
            ),
            pollen_min_interval_seconds=_parse_float(
                values,
                "POLLEN_MIN_INTERVAL_SECONDS",
                1.0,
            ),
            shanghai_noise_enabled=_parse_bool(values, "SHANGHAI_NOISE_ENABLED", False),
            shanghai_noise_token=_optional_secret(values, "SHANGHAI_NOISE_TOKEN"),
            shanghai_noise_api_url=values.get(
                "SHANGHAI_NOISE_API_URL",
                SHANGHAI_NOISE_API_URL,
            ).strip(),
            shanghai_noise_page_size=_parse_int(values, "SHANGHAI_NOISE_PAGE_SIZE", 100),
            shanghai_noise_max_calls_per_run=_parse_int(
                values,
                "SHANGHAI_NOISE_MAX_CALLS_PER_RUN",
                4,
            ),
            shanghai_noise_connect_timeout_seconds=_parse_float(
                values,
                "SHANGHAI_NOISE_CONNECT_TIMEOUT_SECONDS",
                5.0,
            ),
            shanghai_noise_read_timeout_seconds=_parse_float(
                values,
                "SHANGHAI_NOISE_READ_TIMEOUT_SECONDS",
                30.0,
            ),
            shanghai_noise_min_interval_seconds=_parse_float(
                values,
                "SHANGHAI_NOISE_MIN_INTERVAL_SECONDS",
                0.2,
            ),
            shanghai_noise_max_age_hours=_parse_int(
                values,
                "SHANGHAI_NOISE_MAX_AGE_HOURS",
                48,
            ),
        )

    def validate_advanced(self) -> None:
        """校验进阶接口所需的两项凭据。"""

        missing: list[str] = []
        if not self.advanced_api_key:
            missing.append("WEATHERCN_ADVANCED_API_KEY")
        if not self.advanced_secret:
            missing.append("WEATHERCN_ADVANCED_SECRET")
        if missing:
            raise ConfigurationError(f"缺少进阶接口配置：{', '.join(missing)}")

    def validate_standard(self) -> None:
        """在标准接口启用时校验密钥。"""

        if self.standard_enabled and not self.standard_api_key:
            raise ConfigurationError("标准接口已启用，缺少 WEATHERCN_STANDARD_API_KEY")

    def validate_qweather(self) -> None:
        """在和风活动来源启用时校验 Key 与专属 API Host。"""

        if not self.qweather_enabled:
            raise ConfigurationError("和风活动来源已关闭，请设置 QWEATHER_ENABLED=true")
        missing: list[str] = []
        if not self.qweather_api_key:
            missing.append("QWEATHER_API_KEY")
        if not self.qweather_api_host:
            missing.append("QWEATHER_API_HOST")
        if missing:
            raise ConfigurationError(f"缺少和风接口配置：{', '.join(missing)}")
        api_host = self.qweather_api_host
        assert api_host is not None
        _validate_qweather_api_host(api_host)

    def validate_pollen(self) -> None:
        """在 Google Pollen 接口启用时校验独立密钥。"""

        if self.pollen_enabled and not self.pollen_api_key:
            raise ConfigurationError("花粉接口已启用，缺少 POLLEN_API_KEY")

    def validate_shanghai_noise(self) -> None:
        """在上海噪声接口启用时校验 token。"""

        if self.shanghai_noise_enabled and not self.shanghai_noise_token:
            raise ConfigurationError("上海噪声接口已启用，缺少 SHANGHAI_NOISE_TOKEN")


def _validate_qweather_api_host(value: str) -> None:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError("QWEATHER_API_HOST 端口格式无效") from error
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".qweatherapi.com")
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("QWEATHER_API_HOST 需为不含路径、端口和查询参数的 HTTPS 专属域名")


def _validate_https_endpoint(value: str, name: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.strip("/")
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(f"{name} 需为不含凭据和查询参数的 HTTPS 接口地址")


__all__ = [
    "POLLEN_HARD_MAX_CALLS_PER_RUN",
    "QWEATHER_HARD_MAX_CALLS_PER_RUN",
    "SHANGHAI_NOISE_API_URL",
    "SHANGHAI_NOISE_HARD_MAX_CALLS_PER_RUN",
    "ConfigurationError",
    "Settings",
]
