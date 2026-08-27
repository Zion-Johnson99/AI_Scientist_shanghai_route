"""Google Pollen 日级预报客户端与安全响应解析。"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Literal, cast

import requests

from weather_api_data.config import ConfigurationError, Settings
from weather_api_data.http_client import CallLimitExceeded, RequestBudget

POLLEN_LOOKUP_URL = "https://pollen.googleapis.com/v1/forecast:lookup"
POLLEN_TYPE_CODES = ("GRASS", "TREE", "WEED")

PollenDataStatus = Literal["ok", "no_data"]


@dataclass(frozen=True, slots=True)
class PollenTypeIndex:
    """单类花粉在一天内的 Google 指数。缺失类型明确保留 no_data。"""

    code: str
    index_value: int | None
    index_code: str | None
    category: str | None
    in_season: bool | None
    status: PollenDataStatus

    @classmethod
    def no_data(cls, code: str, *, in_season: bool | None = None) -> PollenTypeIndex:
        return cls(
            code=code,
            index_value=None,
            index_code=None,
            category=None,
            in_season=in_season,
            status="no_data",
        )


@dataclass(frozen=True, slots=True)
class PollenForecastDay:
    """一个业务日期的三类花粉指数。"""

    forecast_date: str
    pollen_types: Mapping[str, PollenTypeIndex]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pollen_types", MappingProxyType(dict(self.pollen_types)))


@dataclass(frozen=True, slots=True)
class PollenLookupResult:
    """单坐标查询结果。不保存 Google 原始响应或认证 URL。"""

    latitude: float
    longitude: float
    days: tuple[PollenForecastDay, ...]
    status: PollenDataStatus
    fetched_at: datetime
    expires: str | None
    source_url: str = POLLEN_LOOKUP_URL


class PollenApiError(RuntimeError):
    """脱敏后的 Google Pollen 请求错误。"""

    def __init__(
        self,
        status_code: int | None,
        *,
        retry_after: str | None = None,
        invalid_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        if invalid_json:
            message = "Google Pollen 响应 JSON 无法解析"
        elif status_code is None:
            message = "Google Pollen 请求遇到网络错误"
        else:
            message = f"Google Pollen 请求失败，HTTP 状态码 {status_code}"
        super().__init__(message)


class PollenRunStopped(RuntimeError):
    """表示本轮预算耗尽或此前出现需停机的 HTTP 状态。"""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _index_value(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        return None
    return value


def _forecast_date(value: object) -> str | None:
    date_fields = _mapping(value)
    if date_fields is None:
        return None
    year = date_fields.get("year")
    month = date_fields.get("month")
    day = date_fields.get("day")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (year, month, day)):
        return None
    try:
        return date(cast(int, year), cast(int, month), cast(int, day)).isoformat()
    except ValueError:
        return None


def parse_pollen_forecast(payload: object) -> tuple[PollenForecastDay, ...]:
    """从 Google 响应提取日值。未知或缺失字段安全降为 no_data。"""

    root = _mapping(payload)
    if root is None:
        return ()
    daily_info = root.get("dailyInfo")
    if not isinstance(daily_info, list):
        return ()

    parsed_days: list[PollenForecastDay] = []
    for raw_day in cast(list[object], daily_info):
        day = _mapping(raw_day)
        if day is None:
            continue
        forecast_date = _forecast_date(day.get("date"))
        if forecast_date is None:
            continue

        pollen_types = {code: PollenTypeIndex.no_data(code) for code in POLLEN_TYPE_CODES}
        raw_types = day.get("pollenTypeInfo")
        if isinstance(raw_types, list):
            for raw_type in cast(list[object], raw_types):
                type_info = _mapping(raw_type)
                if type_info is None:
                    continue
                code = _text(type_info.get("code"))
                if code not in POLLEN_TYPE_CODES:
                    continue
                in_season = _boolean(type_info.get("inSeason"))
                index_info = _mapping(type_info.get("indexInfo"))
                if index_info is None:
                    pollen_types[code] = PollenTypeIndex.no_data(
                        code,
                        in_season=in_season,
                    )
                    continue
                index_value = _index_value(index_info.get("value"))
                if index_value is None:
                    pollen_types[code] = PollenTypeIndex.no_data(
                        code,
                        in_season=in_season,
                    )
                    continue
                pollen_types[code] = PollenTypeIndex(
                    code=code,
                    index_value=index_value,
                    index_code=_text(index_info.get("code")),
                    category=_text(index_info.get("category")),
                    in_season=in_season,
                    status="ok",
                )
        parsed_days.append(
            PollenForecastDay(
                forecast_date=forecast_date,
                pollen_types=pollen_types,
            )
        )
    return tuple(parsed_days)


class PollenClient:
    """具有独立预算、节流和终止状态的 Google Pollen 客户端。"""

    def __init__(
        self,
        session: requests.Session,
        settings: Settings,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        utcnow_fn: Callable[[], datetime] = _utcnow,
    ) -> None:
        settings.validate_pollen()
        if not settings.pollen_enabled:
            raise ConfigurationError("花粉接口未启用，请设置 POLLEN_ENABLED=true")
        if settings.pollen_api_key is None:
            raise AssertionError("validate_pollen 未拦截缺失密钥")
        self._session = session
        self._api_key = settings.pollen_api_key
        self._timeout = (
            settings.connect_timeout_seconds,
            settings.read_timeout_seconds,
        )
        self._min_interval_seconds = settings.pollen_min_interval_seconds
        self._sleep = sleep_fn
        self._utcnow = utcnow_fn
        self._budget = RequestBudget(settings.pollen_max_calls_per_run)
        self._stopped_status_code: int | None = None

    @property
    def call_count(self) -> int:
        return self._budget.calls

    def lookup(
        self,
        *,
        latitude: float,
        longitude: float,
        days: int = 5,
        language_code: str = "zh-CN",
    ) -> PollenLookupResult:
        """查询单个 WGS84 坐标。401、403、429 会锁停本客户端。"""

        if self._stopped_status_code is not None:
            raise PollenRunStopped(
                "本轮花粉请求已因终止状态停止",
                status_code=self._stopped_status_code,
            )
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("花粉查询坐标需为有效 WGS84 经纬度")
        if not 1 <= days <= 5:
            raise ValueError("Google Pollen 查询天数需位于 1 至 5 之间")
        try:
            self._budget.consume("google_pollen_forecast_lookup")
        except CallLimitExceeded:
            raise PollenRunStopped("本轮花粉调用预算已耗尽") from None
        if self.call_count > 1:
            self._sleep(self._min_interval_seconds)

        try:
            response = self._session.get(
                POLLEN_LOOKUP_URL,
                params={
                    "key": self._api_key,
                    "location.latitude": latitude,
                    "location.longitude": longitude,
                    "days": days,
                    "languageCode": language_code,
                },
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise PollenApiError(status_code=None) from None

        status_code = response.status_code
        if not 200 <= status_code <= 299:
            retry_after = response.headers.get("Retry-After") if status_code == 429 else None
            if status_code in {401, 403, 429}:
                self._stopped_status_code = status_code
            raise PollenApiError(
                status_code=status_code,
                retry_after=retry_after or None,
            )
        try:
            payload = cast(object, response.json())
        except ValueError:
            raise PollenApiError(status_code=status_code, invalid_json=True) from None

        forecast_days = parse_pollen_forecast(payload)
        has_index = any(
            pollen_type.status == "ok"
            for forecast_day in forecast_days
            for pollen_type in forecast_day.pollen_types.values()
        )
        status: PollenDataStatus = "ok" if has_index else "no_data"
        return PollenLookupResult(
            latitude=latitude,
            longitude=longitude,
            days=forecast_days,
            status=status,
            fetched_at=self._utcnow(),
            expires=response.headers.get("Expires"),
        )


__all__ = [
    "POLLEN_LOOKUP_URL",
    "PollenApiError",
    "PollenClient",
    "PollenForecastDay",
    "PollenLookupResult",
    "PollenRunStopped",
    "PollenTypeIndex",
    "parse_pollen_forecast",
]
