"""WeatherCN 标准接口最小探测客户端。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from weather_api_data.config import ConfigurationError, Settings
from weather_api_data.http_client import HttpClient, HttpResult

COORDINATE_QUANTUM = Decimal("0.001")


class StandardClient:
    """仅开放标准接口的经纬度定位探测。"""

    def __init__(self, settings: Settings, http_client: HttpClient) -> None:
        if settings.standard_enabled:
            settings.validate_standard()
        self._settings = settings
        self._http = http_client
        self._closed = False

    @property
    def closed(self) -> bool:
        """返回该标准接口探针是否已被使用。"""

        return self._closed

    def probe_geoposition(self, latitude: float, longitude: float) -> HttpResult:
        if not self._settings.standard_enabled:
            raise ConfigurationError("WeatherCN 标准接口未启用")
        if self._closed:
            raise ConfigurationError("WeatherCN 标准接口探针已关闭")
        self._closed = True
        api_key = self._settings.standard_api_key
        assert api_key is not None
        coordinates = f"{_coordinate(latitude)},{_coordinate(longitude)}"
        return self._http.get_json(
            endpoint="probe_geoposition",
            base_url=self._settings.standard_base_url,
            path="locations/v1/cities/geoposition/search.json",
            params={"q": coordinates, "apikey": api_key},
            max_retries_override=0,
        )


def _coordinate(value: float) -> str:
    decimal_value = Decimal(str(value))
    if not decimal_value.is_finite():
        raise ValueError("坐标需为有限数值")
    return format(decimal_value.quantize(COORDINATE_QUANTUM, rounding=ROUND_HALF_UP), ".3f")


__all__ = ["StandardClient"]
