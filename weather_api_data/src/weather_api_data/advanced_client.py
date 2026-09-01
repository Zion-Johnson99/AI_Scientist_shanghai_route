"""WeatherCN 进阶接口客户端。"""

from __future__ import annotations

import calendar
from decimal import ROUND_HALF_UP, Decimal

from weather_api_data.advanced_signer import AdvancedSigner
from weather_api_data.config import Settings
from weather_api_data.http_client import HttpClient, HttpResult

COORDINATE_QUANTUM = Decimal("0.001")


class AdvancedClient:
    """组装进阶端点路径、签名参数与业务查询参数。"""

    def __init__(
        self,
        settings: Settings,
        http_client: HttpClient,
        signer: AdvancedSigner | None = None,
    ) -> None:
        settings.validate_advanced()
        api_key = settings.advanced_api_key
        secret = settings.advanced_secret
        assert api_key is not None
        assert secret is not None
        self._settings = settings
        self._http = http_client
        self._api_key = api_key
        self._signer = signer or AdvancedSigner(api_key=api_key, secret=secret)

    def geoposition(self, latitude: float, longitude: float) -> HttpResult:
        coordinates = f"{_coordinate(latitude)},{_coordinate(longitude)}"
        return self._request(
            "geoposition",
            "locations/v1/cities/geoposition/search",
            {"q": coordinates},
        )

    def current_conditions(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "current_conditions",
            f"currentconditions/v1/{key}",
            {"details": "true"},
        )

    def historical_24(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "historical_24",
            f"currentconditions/v1/{key}/historical/24",
            {"details": "true"},
        )

    def hourly_weather_24(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "hourly_weather_24",
            f"forecasts/v1/hourly/24hour/{key}",
            {"details": "true", "metric": "true"},
        )

    def current_air_quality(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "current_air_quality",
            f"airquality/v1/global/observations/{key}",
        )

    def hourly_air_quality_24(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "hourly_air_quality_24",
            f"airqualityforecast/v1/hourly/24hour/{key}",
        )

    def indices_1day(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "indices_1day",
            f"indices/v1/daily/1day/{key}/groups/100",
            {"details": "true"},
        )

    def indices_5day(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "indices_5day",
            f"indices/v1/daily/5day/{key}/groups/100",
            {"details": "true"},
        )

    def alerts(self, location_key: str) -> HttpResult:
        key = _location_key(location_key)
        return self._request(
            "alerts",
            f"alerts/v1/{key}",
            {"details": "true"},
        )

    def climo_actuals(self, location_key: str, year: int, month: int) -> HttpResult:
        key = _location_key(location_key)
        if year != 2025:
            raise ValueError("climo_actuals 年份仅支持 2025")
        if not 1 <= month <= 12:
            raise ValueError("climo_actuals 月份需位于 1 至 12")
        last_day = calendar.monthrange(year, month)[1]
        return self._request(
            "climo_actuals",
            f"climo/v1/actuals/{key}",
            {
                "start": f"{year}/{month:02d}/01",
                "end": f"{year}/{month:02d}/{last_day:02d}",
            },
        )

    def _request(
        self,
        endpoint: str,
        path: str,
        extra_params: dict[str, str] | None = None,
    ) -> HttpResult:
        content_type = path.partition("/")[0]
        auth = self._signer.sign(content_type)
        params = {
            "apikey": self._api_key,
            "requestDate": auth.request_date,
            "accessKey": auth.access_key,
            "language": "zh-CN",
            **(extra_params or {}),
        }
        return self._http.get_json(
            endpoint=endpoint,
            base_url=self._settings.advanced_base_url,
            path=path,
            params=params,
        )


def _location_key(value: str) -> str:
    if (
        not value
        or "/" in value
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("LocationKey 需为不含斜杠或空白的非空文本")
    return value


def _coordinate(value: float) -> str:
    decimal_value = Decimal(str(value))
    if not decimal_value.is_finite():
        raise ValueError("坐标需为有限数值")
    return format(decimal_value.quantize(COORDINATE_QUANTUM, rounding=ROUND_HALF_UP), ".3f")


__all__ = ["AdvancedClient"]
