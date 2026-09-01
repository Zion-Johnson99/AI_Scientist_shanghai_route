"""上海公共数据开放平台噪声原始观测客户端。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal, cast

import requests

SHANGHAI_NOISE_API_URL = "https://data.sh.gov.cn/interface/O5485687412025006/59015"
SHANGHAI_NOISE_SUCCESS_CODE = "000000"

NoiseFetchStatus = Literal["ok", "no_data"]
JsonScalar = str | int | float | bool | None

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShanghaiNoiseObservation:
    """平台返回的单条噪声原始观测。"""

    raw_data: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_data", MappingProxyType(dict(self.raw_data)))


@dataclass(frozen=True, slots=True)
class ShanghaiNoiseFetchResult:
    """一页噪声观测与公共数据平台返回元信息。"""

    total: int
    observations: tuple[ShanghaiNoiseObservation, ...]
    status: NoiseFetchStatus
    fetched_at: datetime
    source_url: str
    api_code: str
    api_message: str | None
    provider_message: str | None


class ShanghaiNoiseRequestError(RuntimeError):
    """不携带 token 或网络底层信息的请求错误。"""

    def __init__(self, source_url: str) -> None:
        self.source_url = source_url
        super().__init__("上海公共数据噪声请求遇到网络错误")


class ShanghaiNoiseResponseError(RuntimeError):
    """响应状态或数据形状不符合平台约定。"""

    def __init__(
        self,
        detail: str,
        source_url: str,
        *,
        status_code: int | None = None,
        api_code: str | None = None,
    ) -> None:
        self.detail = detail
        self.source_url = source_url
        self.status_code = status_code
        self.api_code = api_code
        super().__init__(f"上海公共数据噪声响应异常：{detail}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _optional_message(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


class ShanghaiNoiseClient:
    """通过 POST JSON 读取上海公共数据噪声观测。"""

    def __init__(
        self,
        session: requests.Session,
        *,
        token: str,
        endpoint: str = SHANGHAI_NOISE_API_URL,
        timeout: tuple[float, float] = (5.0, 20.0),
        utcnow_fn: Callable[[], datetime] = _utcnow,
    ) -> None:
        if not token.strip():
            raise ValueError("上海公共数据 token 不得为空")
        if not endpoint.strip():
            raise ValueError("上海公共数据接口地址不得为空")
        if timeout[0] <= 0 or timeout[1] <= 0:
            raise ValueError("连接和读取超时需大于 0")
        self._session = session
        self._token = token
        self._endpoint = endpoint
        self._timeout = timeout
        self._utcnow = utcnow_fn

    def fetch(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        query_fields: Mapping[str, JsonScalar] | None = None,
    ) -> ShanghaiNoiseFetchResult:
        """读取一页原始观测。其他文档字段通过 query_fields 传入。"""

        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("上海噪声接口 limit 需位于 1 至 100")
        if isinstance(offset, bool) or offset < 0:
            raise ValueError("上海噪声接口 offset 需为非负整数")
        body: dict[str, JsonScalar] = {"limit": limit, "offset": offset}
        if query_fields is not None:
            if "limit" in query_fields or "offset" in query_fields:
                raise ValueError("query_fields 不得覆盖 limit 或 offset")
            if any(not key.strip() for key in query_fields):
                raise ValueError("query_fields 字段名需为非空字符串")
            body.update(query_fields)

        try:
            response = self._session.post(
                self._endpoint,
                json=body,
                headers={"token": self._token},
                timeout=self._timeout,
            )
        except requests.RequestException:
            raise ShanghaiNoiseRequestError(self._endpoint) from None

        if not 200 <= response.status_code <= 299:
            raise ShanghaiNoiseResponseError(
                f"HTTP 状态码 {response.status_code}",
                self._endpoint,
                status_code=response.status_code,
            )
        try:
            outer_payload = cast(object, response.json())
        except ValueError:
            raise ShanghaiNoiseResponseError(
                "外层 JSON 无法解析",
                self._endpoint,
                status_code=response.status_code,
            ) from None

        outer = _mapping(outer_payload)
        if outer is None:
            raise self._response_error("外层响应需为对象", response.status_code)
        api_code = outer.get("code")
        if not isinstance(api_code, str):
            raise self._response_error("外层响应缺少 code", response.status_code)
        if api_code != SHANGHAI_NOISE_SUCCESS_CODE:
            raise self._response_error(
                f"平台错误码 {api_code}",
                response.status_code,
                api_code=api_code,
            )

        inner = self._parse_inner(outer.get("data"), response.status_code)
        if inner.get("state") is not True:
            raise self._response_error("内层 state 未表示成功", response.status_code)
        total = inner.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise self._response_error("内层 total 需为非负整数", response.status_code)

        raw_records = inner.get("data")
        if raw_records is None:
            if total != 0:
                raise self._response_error("data 为 null 时 total 需为 0", response.status_code)
            records: list[object] = []
        elif isinstance(raw_records, list):
            records = cast(list[object], raw_records)
        else:
            raise self._response_error("内层 data 需为数组或 null", response.status_code)

        observations: list[ShanghaiNoiseObservation] = []
        for raw_record in records:
            record = _mapping(raw_record)
            if record is None:
                raise self._response_error("观测记录需为对象", response.status_code)
            observations.append(ShanghaiNoiseObservation(record))

        status: NoiseFetchStatus = "ok" if observations else "no_data"
        _LOGGER.info(
            "上海公共数据噪声采集完成 offset=%s limit=%s page_count=%s total=%s status=%s",
            offset,
            limit,
            len(observations),
            total,
            status,
        )
        return ShanghaiNoiseFetchResult(
            total=total,
            observations=tuple(observations),
            status=status,
            fetched_at=self._utcnow(),
            source_url=self._endpoint,
            api_code=api_code,
            api_message=_optional_message(outer.get("message")),
            provider_message=_optional_message(inner.get("message")),
        )

    def _parse_inner(self, value: object, status_code: int) -> Mapping[str, object]:
        if isinstance(value, str):
            try:
                value = cast(object, json.loads(value))
            except json.JSONDecodeError:
                raise self._response_error("内层 data JSON 无法解析", status_code) from None
        inner = _mapping(value)
        if inner is None:
            raise self._response_error("外层 data 需为 JSON 对象或其字符串", status_code)
        return inner

    def _response_error(
        self,
        detail: str,
        status_code: int,
        *,
        api_code: str | None = None,
    ) -> ShanghaiNoiseResponseError:
        return ShanghaiNoiseResponseError(
            detail,
            self._endpoint,
            status_code=status_code,
            api_code=api_code,
        )


__all__ = [
    "SHANGHAI_NOISE_API_URL",
    "SHANGHAI_NOISE_SUCCESS_CODE",
    "JsonScalar",
    "ShanghaiNoiseClient",
    "ShanghaiNoiseFetchResult",
    "ShanghaiNoiseObservation",
    "ShanghaiNoiseRequestError",
    "ShanghaiNoiseResponseError",
]
