"""分层刷新任务的互斥、发布与运行状态编排。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

Tier = Literal["weather", "hourly", "daily"]
RefreshCallback = Callable[[], Mapping[str, object]]

_TIERS: tuple[Tier, ...] = ("weather", "hourly", "daily")
_USABLE_REFRESH_STATUSES = frozenset({"ok", "partial"})
_USABLE_PUBLISH_STATUSES = frozenset({"ok", "partial", "stale"})
_DEFAULT_LOCK_TTL = timedelta(hours=1)
_LOGGER = logging.getLogger("weather_api_data.scheduler")


class SchedulerLockedError(RuntimeError):
    """表示已有调度刷新持有进程锁。"""


class SchedulerRefreshError(RuntimeError):
    """表示刷新回调未产生可用结果。"""


class SchedulerPublishError(RuntimeError):
    """表示发布回调未产生可用网页快照。"""


def run_scheduled_refresh(
    *,
    tier: str,
    runtime_dir: str | Path,
    weather_refresh: RefreshCallback,
    hourly_refresh: RefreshCallback,
    daily_refresh: RefreshCallback,
    publish: RefreshCallback,
    now_fn: Callable[[], datetime] | None = None,
    lock_ttl: timedelta = _DEFAULT_LOCK_TTL,
) -> dict[str, object]:
    """在进程锁内执行一个刷新层级。随后发布网页数据包。"""

    if tier not in _TIERS:
        raise ValueError("tier 需为 weather、hourly 或 daily")
    if lock_ttl <= timedelta(0):
        raise ValueError("lock_ttl 需大于 0")
    selected_tier: Tier = tier
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    attempted_datetime = _utc_datetime(clock())
    attempted_at = attempted_datetime.isoformat()
    runtime_path = Path(runtime_dir)
    state_path = runtime_path / "scheduler_state.json"
    lock_path = runtime_path / "scheduled_refresh.lock"
    runtime_path.mkdir(parents=True, exist_ok=True)

    lock_token = _acquire_lock(
        lock_path,
        tier=selected_tier,
        created_at=attempted_at,
        now=attempted_datetime,
        lock_ttl=lock_ttl,
    )
    if lock_token is None:
        error = _error_context(
            SchedulerLockedError("已有调度刷新正在运行"),
            stage="lock",
        )
        state = _state_document(
            attempted_at=attempted_at,
            last_success=_load_last_success(state_path),
            status="locked",
            tier=selected_tier,
            error=error,
        )
        try:
            _atomic_write_json(state_path, state)
        except (OSError, TypeError, ValueError) as exc:
            return _state_write_failure(state, exc)
        return dict(state)

    try:
        return _run_locked(
            tier=selected_tier,
            state_path=state_path,
            attempted_at=attempted_at,
            refresh_callbacks={
                "weather": weather_refresh,
                "hourly": hourly_refresh,
                "daily": daily_refresh,
            },
            publish=publish,
        )
    finally:
        _release_lock(lock_path, lock_token)


def _run_locked(
    *,
    tier: Tier,
    state_path: Path,
    attempted_at: str,
    refresh_callbacks: Mapping[Tier, RefreshCallback],
    publish: RefreshCallback,
) -> dict[str, object]:
    try:
        last_success = _load_last_success(state_path)
    except (OSError, TypeError, ValueError) as exc:
        state = _state_document(
            attempted_at=attempted_at,
            last_success=None,
            status="fatal",
            tier=tier,
            error=_error_context(exc, stage="state"),
        )
        try:
            _atomic_write_json(state_path, state)
        except (OSError, TypeError, ValueError) as write_exc:
            return _state_write_failure(state, write_exc)
        return dict(state)

    refresh_result: dict[str, object] | None = None
    refresh_error: dict[str, object] | None = None
    try:
        refresh_result = _callback_result(refresh_callbacks[tier](), stage="refresh")
        if not _is_refresh_usable(refresh_result):
            raise SchedulerRefreshError(
                f"刷新结果不可用: status={refresh_result.get('status', 'missing')}"
            )
    except Exception as exc:
        refresh_error = _error_context(exc, stage="refresh")
        _LOGGER.warning(
            "调度刷新失败 tier=%s error=%s",
            tier,
            refresh_error,
            exc_info=True,
        )

    publish_result: dict[str, object] | None = None
    publish_error: dict[str, object] | None = None
    try:
        publish_result = _callback_result(publish(), stage="publish")
        if not _is_publish_usable(publish_result):
            raise SchedulerPublishError(
                f"发布结果不可用: status={publish_result.get('status', 'missing')}"
            )
    except Exception as exc:
        publish_error = _error_context(exc, stage="publish")
        _LOGGER.exception("网页数据发布失败 tier=%s error=%s", tier, publish_error)

    publish_is_usable = publish_result is not None and _is_publish_usable(publish_result)
    refresh_is_usable = refresh_result is not None and _is_refresh_usable(refresh_result)
    if not publish_is_usable:
        status = "fatal"
        error = dict(publish_error) if publish_error is not None else refresh_error
        if error is not None and refresh_error is not None:
            error["refresh_error"] = refresh_error
    elif not refresh_is_usable:
        status = "partial"
        error = refresh_error
    else:
        assert refresh_result is not None
        assert publish_result is not None
        status = (
            "partial"
            if refresh_result["status"] == "partial" or publish_result["status"] != "ok"
            else "ok"
        )
        error = None

    state = _state_document(
        attempted_at=attempted_at,
        last_success=attempted_at if refresh_is_usable and publish_is_usable else last_success,
        status=status,
        tier=tier,
        error=error,
    )
    result = dict(state)
    result["refresh"] = refresh_result
    result["publish"] = publish_result
    try:
        _atomic_write_json(state_path, state)
    except (OSError, TypeError, ValueError) as exc:
        return _state_write_failure(result, exc)
    return result


def _callback_result(result: object, *, stage: str) -> dict[str, object]:
    if not isinstance(result, Mapping):
        raise TypeError(f"{stage} 回调需返回映射")
    return dict(cast(Mapping[str, object], result))


def _is_refresh_usable(result: Mapping[str, object]) -> bool:
    return result.get("status") in _USABLE_REFRESH_STATUSES


def _is_publish_usable(result: Mapping[str, object]) -> bool:
    return result.get("status") in _USABLE_PUBLISH_STATUSES


def _state_document(
    *,
    attempted_at: str,
    last_success: str | None,
    status: str,
    tier: Tier,
    error: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "last_attempt": attempted_at,
        "last_success": last_success,
        "status": status,
        "tier": tier,
        "error": dict(error) if error is not None else None,
    }


def _error_context(exc: Exception, *, stage: str) -> dict[str, object]:
    return {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
    }


def _state_write_failure(result: Mapping[str, object], exc: Exception) -> dict[str, object]:
    _LOGGER.exception("调度状态写入失败 path=scheduler_state.json", exc_info=exc)
    failed = dict(result)
    failed["status"] = "fatal"
    failed["error"] = _error_context(exc, stage="state")
    return failed


def _load_last_success(path: Path) -> str | None:
    if not path.exists():
        return None
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("scheduler_state.json 顶层需为对象")
    state = cast(dict[str, object], payload)
    value = state.get("last_success")
    if value is not None and not isinstance(value, str):
        raise ValueError("scheduler_state.json 的 last_success 需为字符串或 null")
    return value


def _acquire_lock(
    path: Path,
    *,
    tier: Tier,
    created_at: str,
    now: datetime,
    lock_ttl: timedelta,
) -> str | None:
    token = _create_lock(path, tier=tier, created_at=created_at)
    if token is not None:
        return token
    if not _lock_is_stale(path, now=now, lock_ttl=lock_ttl):
        return None

    stale_path = path.with_name(f".{path.name}.{uuid4().hex}.stale")
    try:
        os.replace(path, stale_path)
    except FileNotFoundError:
        pass
    except OSError:
        _LOGGER.exception("陈旧调度锁隔离失败 path=%s", path)
        return None
    else:
        _LOGGER.warning("已隔离陈旧调度锁 source=%s target=%s", path, stale_path)
    return _create_lock(path, tier=tier, created_at=created_at)


def _create_lock(path: Path, *, tier: Tier, created_at: str) -> str | None:
    token = uuid4().hex
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {"created_at": created_at, "pid": os.getpid(), "tier": tier, "token": token},
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return token


def _lock_is_stale(path: Path, *, now: datetime, lock_ttl: timedelta) -> bool:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
        lock = cast(dict[str, object], payload)
        created_at = lock.get("created_at")
        if not isinstance(created_at, str):
            return False
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None or created.utcoffset() is None:
            return False
        return now - created.astimezone(timezone.utc) > lock_ttl
    except (OSError, ValueError):
        return False


def _release_lock(path: Path, token: str) -> None:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and cast(dict[str, object], payload).get("token") == token:
            path.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        _LOGGER.exception("调度锁释放失败 path=%s", path)


def _atomic_write_json(path: Path, document: Mapping[str, object]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except (OSError, TypeError, ValueError):
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_fn 需返回含时区的 datetime")
    return value.astimezone(timezone.utc)


__all__ = [
    "RefreshCallback",
    "SchedulerLockedError",
    "SchedulerPublishError",
    "SchedulerRefreshError",
    "Tier",
    "run_scheduled_refresh",
]
