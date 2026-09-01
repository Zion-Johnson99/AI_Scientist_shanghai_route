"""HTTPS JSON 传输、限额与错误分类。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import cast
from urllib.parse import urlsplit

import requests

from weather_api_data.config import Settings


@dataclass(frozen=True, slots=True)
class HttpResult:
    """单次成功 HTTP 响应的业务数据与缓存元信息。"""

    payload: object
    status_code: int
    expires: str | None
    fetched_at: datetime


class ApiRequestError(RuntimeError):
    """携带安全请求上下文的 API 错误。"""

    def __init__(
        self,
        endpoint: str,
        status_code: int | None,
        retry_after: str | None = None,
        *,
        invalid_json: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        self.retry_after = retry_after
        if invalid_json:
            message = "API 响应 JSON 无法解析"
        elif status_code is None:
            message = "API 请求遇到临时网络错误"
        else:
            message = f"API 请求失败，HTTP 状态码 {status_code}"
        super().__init__(message)


class CallLimitExceeded(RuntimeError):
    """单次运行的 HTTP 尝试次数已达到硬上限。"""

    def __init__(self, endpoint: str, max_calls: int) -> None:
        self.endpoint = endpoint
        self.max_calls = max_calls
        super().__init__(f"已达到单次运行调用上限 {max_calls}")


@dataclass(slots=True)
class RequestBudget:
    """为一次运行记录所有 HTTP 尝试及重试。"""

    max_calls: int
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_calls <= 0:
            raise ValueError("max_calls 需大于 0")

    def consume(self, endpoint: str) -> None:
        """为即将发出的请求扣减一次额度。"""

        if self.calls >= self.max_calls:
            raise CallLimitExceeded(endpoint=endpoint, max_calls=self.max_calls)
        self.calls += 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HttpClient:
    """带调用预算、节流和有限重试的 HTTPS JSON 客户端。"""

    def __init__(
        self,
        session: requests.Session,
        settings: Settings,
        sleep_fn: Callable[[float], None] = time.sleep,
        uniform_fn: Callable[[float, float], float] = random.uniform,
        utcnow_fn: Callable[[], datetime] = _utcnow,
        *,
        max_calls_per_run: int | None = None,
        connect_timeout_seconds: float | None = None,
        read_timeout_seconds: float | None = None,
        max_retries: int | None = None,
        min_interval_seconds: float | None = None,
        jitter_max_seconds: float | None = None,
    ) -> None:
        self._session = session
        self._sleep = sleep_fn
        self._uniform = uniform_fn
        self._utcnow = utcnow_fn
        self._connect_timeout_seconds = (
            settings.connect_timeout_seconds
            if connect_timeout_seconds is None
            else connect_timeout_seconds
        )
        self._read_timeout_seconds = (
            settings.read_timeout_seconds if read_timeout_seconds is None else read_timeout_seconds
        )
        self._max_retries = settings.max_retries if max_retries is None else max_retries
        self._min_interval_seconds = (
            settings.min_interval_seconds if min_interval_seconds is None else min_interval_seconds
        )
        self._jitter_max_seconds = (
            settings.jitter_max_seconds if jitter_max_seconds is None else jitter_max_seconds
        )
        if self._connect_timeout_seconds <= 0 or self._read_timeout_seconds <= 0:
            raise ValueError("HTTP 超时需大于 0")
        if self._max_retries < 0:
            raise ValueError("HTTP 重试次数需大于或等于 0")
        if self._min_interval_seconds < 0 or self._jitter_max_seconds < 0:
            raise ValueError("HTTP 节流参数需大于或等于 0")
        self._budget = RequestBudget(max_calls_per_run or settings.max_calls_per_run)
        self._attempts = 0

    @property
    def call_count(self) -> int:
        """返回本实例已经执行的 HTTP 尝试次数。"""

        return self._budget.calls

    def get_json(
        self,
        endpoint: str,
        base_url: str,
        path: str,
        params: Mapping[
            str,
            str | bytes | int | float | Sequence[str | bytes | int | float] | None,
        ]
        | None = None,
        headers: dict[str, str] | None = None,
        max_retries_override: int | None = None,
    ) -> HttpResult:
        """通过 HTTPS GET 获取 JSON 与响应缓存元信息。"""

        max_retries = self._max_retries if max_retries_override is None else max_retries_override
        if not 0 <= max_retries <= self._max_retries:
            raise ValueError("请求重试覆盖次数需位于 0 至配置上限之间")
        url = self._build_url(base_url, path)
        request_headers = dict(headers or {})
        request_headers.setdefault("Accept-Encoding", "gzip, deflate")

        for retry_index in range(max_retries + 1):
            self._budget.consume(endpoint)
            self._throttle()
            try:
                response = self._session.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=(
                        self._connect_timeout_seconds,
                        self._read_timeout_seconds,
                    ),
                    allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError):
                if retry_index < max_retries:
                    continue
                raise ApiRequestError(endpoint=endpoint, status_code=None) from None

            status_code = response.status_code
            if 500 <= status_code <= 599 and retry_index < max_retries:
                continue
            if not 200 <= status_code <= 299:
                retry_after = response.headers.get("Retry-After") if status_code == 429 else None
                raise ApiRequestError(
                    endpoint=endpoint,
                    status_code=status_code,
                    retry_after=retry_after or None,
                )

            try:
                payload = cast(object, response.json())
            except ValueError:
                raise ApiRequestError(
                    endpoint=endpoint,
                    status_code=status_code,
                    invalid_json=True,
                ) from None
            return HttpResult(
                payload=payload,
                status_code=status_code,
                expires=response.headers.get("Expires"),
                fetched_at=self._utcnow(),
            )

        raise AssertionError("重试循环异常结束")

    def _throttle(self) -> None:
        if self._attempts > 0:
            jitter = self._uniform(0.0, self._jitter_max_seconds)
            self._sleep(self._min_interval_seconds + jitter)
        self._attempts += 1

    @staticmethod
    def _build_url(base_url: str, path: str) -> str:
        parsed_base = urlsplit(base_url)
        if (
            parsed_base.scheme.lower() != "https"
            or not parsed_base.netloc
            or parsed_base.query
            or parsed_base.fragment
        ):
            raise ValueError("base_url 需为不含查询参数或片段的 HTTPS 地址")
        if not path or path.startswith(("/", "\\")) or "://" in path:
            raise ValueError("path 需为非空相对路径")
        return f"{base_url.rstrip('/')}/{path}"


__all__ = [
    "ApiRequestError",
    "CallLimitExceeded",
    "HttpClient",
    "HttpResult",
    "RequestBudget",
]
