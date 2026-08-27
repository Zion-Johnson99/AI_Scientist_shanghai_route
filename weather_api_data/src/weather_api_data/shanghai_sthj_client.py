"""上海市生态环境局徐汇区站点小时数据客户端。"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, cast

import requests

FetchStatus = Literal["ok", "no_data"]

_LOGGER = logging.getLogger(__name__)
_LATEST_TIME_PATTERN = re.compile(r"lastLstAqiStr\s*=\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True, slots=True)
class ShanghaiSthjFetchResult:
    """单站原始响应及采集元信息。"""

    station_id: str
    latest_time: str
    status_code: int
    payload: object
    fetched_at: datetime
    source_url: str
    status: FetchStatus


class ShanghaiSthjRequestError(RuntimeError):
    """携带站点和请求阶段上下文的网络错误。"""

    def __init__(self, operation: str, source_url: str, station_id: str | None) -> None:
        self.operation = operation
        self.source_url = source_url
        self.station_id = station_id
        context = f"站点 {station_id}" if station_id is not None else "徐汇详情页"
        super().__init__(f"上海市生态环境局请求失败：{context}，阶段 {operation}")


class ShanghaiSthjResponseError(RuntimeError):
    """响应状态或响应形状不符合采集约定。"""

    def __init__(
        self,
        detail: str,
        source_url: str,
        *,
        station_id: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.detail = detail
        self.source_url = source_url
        self.station_id = station_id
        self.status_code = status_code
        context = f"站点 {station_id}" if station_id is not None else "徐汇详情页"
        super().__init__(f"上海市生态环境局响应异常：{context}，{detail}")


ShanghaiSthjStationError = ShanghaiSthjRequestError | ShanghaiSthjResponseError


@dataclass(frozen=True, slots=True)
class ShanghaiSthjBatchResult:
    """一轮站点请求的成功结果、单站错误和实际请求数。"""

    results: tuple[ShanghaiSthjFetchResult, ...]
    errors: tuple[ShanghaiSthjStationError, ...]
    request_count: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShanghaiSthjClient:
    """通过同一个页面会话低频读取徐汇区站点小时数据。"""

    DETAIL_PAGE_URL = (
        "https://link.sthj.sh.gov.cn/aqi/kqzl/"
        "kqzlCountyhourlydataController/subarea/toSubareaDetail.do?groupid=204"
    )
    HOURLY_DATA_URL = (
        "https://link.sthj.sh.gov.cn/aqi/kqzl/"
        "KqzlSitehourlydataController/getSiteHourlyDataBySiteId.do"
    )
    DEFAULT_STATION_IDS = ("80", "207", "1")
    result_type = ShanghaiSthjFetchResult

    def __init__(
        self,
        session: requests.Session,
        *,
        timeout: tuple[float, float] = (5.0, 30.0),
        utcnow_fn: Callable[[], datetime] = _utcnow,
    ) -> None:
        if timeout[0] <= 0 or timeout[1] <= 0:
            raise ValueError("连接和读取超时需大于 0")
        self._session = session
        self._timeout = timeout
        self._utcnow = utcnow_fn

    def fetch_stations(
        self,
        station_ids: Sequence[str] = DEFAULT_STATION_IDS,
    ) -> ShanghaiSthjBatchResult:
        """读取页面时间令牌。在同一会话中依次获取指定站点。"""

        latest_time = self._fetch_latest_time()
        results: list[ShanghaiSthjFetchResult] = []
        errors: list[ShanghaiSthjStationError] = []
        for station_id in station_ids:
            try:
                results.append(self._fetch_station(station_id, latest_time))
            except (ShanghaiSthjRequestError, ShanghaiSthjResponseError) as error:
                errors.append(error)
                _LOGGER.warning(
                    "上海站点采集失败 station_id=%s error_type=%s",
                    station_id,
                    type(error).__name__,
                )
        return ShanghaiSthjBatchResult(
            results=tuple(results),
            errors=tuple(errors),
            request_count=1 + len(station_ids),
        )

    def _fetch_latest_time(self) -> str:
        try:
            response = self._session.get(self.DETAIL_PAGE_URL, timeout=self._timeout)
        except requests.RequestException:
            raise ShanghaiSthjRequestError(
                "detail_page_get",
                self.DETAIL_PAGE_URL,
                None,
            ) from None

        if not 200 <= response.status_code <= 299:
            raise ShanghaiSthjResponseError(
                f"详情页 HTTP 状态码 {response.status_code}",
                self.DETAIL_PAGE_URL,
                status_code=response.status_code,
            )

        match = _LATEST_TIME_PATTERN.search(response.text)
        if match is None or not match.group(1).strip():
            raise ShanghaiSthjResponseError(
                "详情页缺少 lastLstAqiStr",
                self.DETAIL_PAGE_URL,
                status_code=response.status_code,
            )
        return match.group(1).strip()

    def _fetch_station(self, station_id: str, latest_time: str) -> ShanghaiSthjFetchResult:
        headers = {
            "Referer": self.DETAIL_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        try:
            response = self._session.post(
                self.HOURLY_DATA_URL,
                data={"lstAqi": latest_time, "siteId": station_id},
                headers=headers,
                timeout=self._timeout,
            )
        except requests.RequestException:
            raise ShanghaiSthjRequestError(
                "station_hourly_post",
                self.HOURLY_DATA_URL,
                station_id,
            ) from None

        fetched_at = self._utcnow()
        if response.status_code == 404 or not response.text.strip():
            return self._result(
                station_id,
                latest_time,
                response.status_code,
                None,
                fetched_at,
                "no_data",
            )
        if not 200 <= response.status_code <= 299:
            raise ShanghaiSthjResponseError(
                f"小时数据 HTTP 状态码 {response.status_code}",
                self.HOURLY_DATA_URL,
                station_id=station_id,
                status_code=response.status_code,
            )

        try:
            payload = cast(object, response.json())
        except ValueError:
            raise ShanghaiSthjResponseError(
                "小时数据 JSON 无法解析",
                self.HOURLY_DATA_URL,
                station_id=station_id,
                status_code=response.status_code,
            ) from None
        status: FetchStatus = "no_data" if payload in (None, {}, []) else "ok"
        return self._result(
            station_id,
            latest_time,
            response.status_code,
            payload,
            fetched_at,
            status,
        )

    def _result(
        self,
        station_id: str,
        latest_time: str,
        status_code: int,
        payload: object,
        fetched_at: datetime,
        status: FetchStatus,
    ) -> ShanghaiSthjFetchResult:
        _LOGGER.info(
            "上海站点采集完成 station_id=%s http_status=%s status=%s",
            station_id,
            status_code,
            status,
        )
        return ShanghaiSthjFetchResult(
            station_id=station_id,
            latest_time=latest_time,
            status_code=status_code,
            payload=payload,
            fetched_at=fetched_at,
            source_url=self.HOURLY_DATA_URL,
            status=status,
        )


__all__ = [
    "ShanghaiSthjBatchResult",
    "ShanghaiSthjClient",
    "ShanghaiSthjFetchResult",
    "ShanghaiSthjRequestError",
    "ShanghaiSthjResponseError",
]
