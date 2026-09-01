"""和风天气坐标端点客户端。"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from weather_api_data.config import Settings
from weather_api_data.http_client import HttpClient, HttpResult

_COORDINATE_QUANTUM = Decimal("0.01")


class QWeatherApiError(RuntimeError):
    """表示和风旧版端点返回非成功业务码。"""

    def __init__(self, endpoint: str, provider_code: str) -> None:
        self.endpoint = endpoint
        self.provider_code = provider_code
        super().__init__(f"和风接口返回业务码 {provider_code}")


def qweather_source_id(latitude: float, longitude: float) -> str:
    """生成与和风两位小数坐标请求一致的稳定来源 ID。"""

    return f"qweather:{_coordinate(latitude, -90, 90)},{_coordinate(longitude, -180, 180)}"


def coordinates_from_source_id(source_id: str) -> tuple[str, str]:
    """从稳定来源 ID 返回纬度、经度字符串。"""

    prefix, separator, coordinates = source_id.partition(":")
    if prefix != "qweather" or not separator:
        raise ValueError("和风 source_id 需使用 qweather:纬度,经度")
    latitude, comma, longitude = coordinates.partition(",")
    if not comma or "," in longitude:
        raise ValueError("和风 source_id 需使用 qweather:纬度,经度")
    expected = qweather_source_id(_number(latitude), _number(longitude))
    if source_id != expected:
        raise ValueError("和风 source_id 坐标需固定保留两位小数")
    return latitude, longitude


class QWeatherClient:
    """封装和风六类活动业务请求并始终使用请求头认证。"""

    def __init__(self, settings: Settings, http_client: HttpClient) -> None:
        settings.validate_qweather()
        api_key = settings.qweather_api_key
        api_host = settings.qweather_api_host
        assert api_key is not None
        assert api_host is not None
        self._base_url = api_host.rstrip("/")
        self._http = http_client
        self._headers = {"X-QW-Api-Key": api_key}

    def current_conditions(self, source_id: str) -> HttpResult:
        latitude, longitude = coordinates_from_source_id(source_id)
        return self._request(
            "current_conditions",
            f"weather/v1/current/{latitude}/{longitude}",
            {"localTime": "true", "lang": "zh"},
        )

    def hourly_weather_24(self, source_id: str) -> HttpResult:
        latitude, longitude = coordinates_from_source_id(source_id)
        return self._request(
            "hourly_weather_24",
            f"weather/v1/hourly/{latitude}/{longitude}",
            {"hours": 24, "localTime": "true", "lang": "zh"},
        )

    def current_air_quality(self, source_id: str) -> HttpResult:
        latitude, longitude = coordinates_from_source_id(source_id)
        return self._request(
            "current_air_quality",
            f"airquality/v1/current/{latitude}/{longitude}",
            {"lang": "zh"},
        )

    def hourly_air_quality_24(self, source_id: str) -> HttpResult:
        latitude, longitude = coordinates_from_source_id(source_id)
        return self._request(
            "hourly_air_quality_24",
            f"airquality/v1/hourly/{latitude}/{longitude}",
            {"lang": "zh"},
        )

    def indices_3day(self, source_id: str) -> HttpResult:
        latitude, longitude = coordinates_from_source_id(source_id)
        result = self._request(
            "indices_3day",
            "v7/indices/3d",
            {"type": "0", "location": f"{longitude},{latitude}", "lang": "zh"},
        )
        payload = result.payload
        if (
            not isinstance(payload, dict)
            or str(cast(dict[str, object], payload).get("code")) != "200"
        ):
            provider_code = (
                str(cast(dict[str, object], payload).get("code"))
                if isinstance(payload, dict)
                else "invalid_payload"
            )
            raise QWeatherApiError("indices_3day", provider_code)
        return result

    def alerts(self, source_id: str) -> HttpResult:
        latitude, longitude = coordinates_from_source_id(source_id)
        return self._request(
            "alerts",
            f"weatheralert/v1/current/{latitude}/{longitude}",
            {"localTime": "true", "lang": "zh"},
        )

    def _request(
        self,
        endpoint: str,
        path: str,
        params: dict[str, str | int],
    ) -> HttpResult:
        return self._http.get_json(
            endpoint=endpoint,
            base_url=self._base_url,
            path=path,
            params=params,
            headers=self._headers,
        )


def _coordinate(value: float, minimum: int, maximum: int) -> str:
    if isinstance(value, bool) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("和风坐标超出 WGS84 合法范围")
    return format(Decimal(str(value)).quantize(_COORDINATE_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _number(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError("和风 source_id 坐标需为数值") from error
    if not math.isfinite(number):
        raise ValueError("和风 source_id 坐标需为有限数值")
    return number


__all__ = [
    "QWeatherApiError",
    "QWeatherClient",
    "coordinates_from_source_id",
    "qweather_source_id",
]
