from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class RequestLimiter:
    def __init__(self, *, per_minute: int, daily_total: int) -> None:
        if per_minute <= 0 or daily_total <= 0:
            raise ValueError("限流值需大于 0")
        self._per_minute = per_minute
        self._daily_total = daily_total
        self._minute_requests: dict[str, deque[float]] = defaultdict(deque)
        self._daily_date = datetime.now(timezone.utc).date()
        self._daily_count = 0
        self._lock = Lock()

    def acquire(self, client_key: str) -> RateLimitDecision:
        now = monotonic()
        today = datetime.now(timezone.utc).date()
        with self._lock:
            self._reset_daily_if_needed(today)
            requests = self._minute_requests[client_key]
            while requests and now - requests[0] >= 60:
                requests.popleft()
            if len(requests) >= self._per_minute:
                retry_after = max(1, round(60 - (now - requests[0])))
                return RateLimitDecision(False, retry_after)
            if self._daily_count >= self._daily_total:
                return RateLimitDecision(False, self._seconds_until_tomorrow())
            requests.append(now)
            self._daily_count += 1
            return RateLimitDecision(True)

    def _reset_daily_if_needed(self, today: date) -> None:
        if today == self._daily_date:
            return
        self._daily_date = today
        self._daily_count = 0
        self._minute_requests.clear()

    @staticmethod
    def _seconds_until_tomorrow() -> int:
        now = datetime.now(timezone.utc)
        return max(1, 86400 - (now.hour * 3600 + now.minute * 60 + now.second))
