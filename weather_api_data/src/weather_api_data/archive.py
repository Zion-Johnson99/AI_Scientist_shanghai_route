"""脱敏原始响应的 GZIP 归档与安全清理。"""

from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+", flags=re.ASCII)
_SENSITIVE_KEYS = {
    "authorization",
    "apikey",
    "signature",
    "xgwapikey",
    "xqwapikey",
    "accesskey",
    "secret",
    "apisecret",
    "clientsecret",
    "token",
    "accesstoken",
    "password",
}
_QWEATHER_SOURCE_ID = re.compile(
    r"qweather:(-?\d{1,2}\.\d{2}),(-?\d{1,3}\.\d{2})",
    flags=re.ASCII,
)


@dataclass(frozen=True, slots=True)
class PruneResult:
    """清理候选或实际删除文件的统计。"""

    file_count: int
    total_bytes: int


class Archive:
    """将允许归档的响应限制在指定根目录内。"""

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir).resolve(strict=False)

    @property
    def root_dir(self) -> Path:
        """返回用于磁盘审计的只读归档根路径。"""

        return self._root

    def archive(
        self,
        endpoint: str,
        location_key: str,
        fetched_at: datetime,
        payload: object,
    ) -> Path | None:
        """脱敏并压缩单次原始响应且直接跳过定位响应。"""

        if endpoint.casefold() == "geoposition":
            return None
        safe_endpoint = _identifier(endpoint, "endpoint")
        safe_location = _archive_location_identifier(location_key)
        fetched_utc = _utc(fetched_at)
        directory = self._root.joinpath(
            fetched_utc.strftime("%Y"),
            fetched_utc.strftime("%m"),
            fetched_utc.strftime("%d"),
            safe_endpoint,
            safe_location,
        )
        filename = f"{fetched_utc.strftime('%Y%m%dT%H%M%S_%fZ')}_{uuid4().hex}.json.gz"
        target = _inside(self._root, directory / filename)
        directory.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=directory,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = _inside(self._root, Path(temp_file.name))
            with gzip.open(temp_path, "wt", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    redact_credentials(payload),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return target

    def prune(self, cutoff: datetime, apply: bool = False) -> PruneResult:
        """统计或删除 mtime 严格早于 cutoff 的归档文件。"""

        if not self._root.exists():
            return PruneResult(file_count=0, total_bytes=0)
        cutoff_timestamp = _utc(cutoff).timestamp()
        candidates: list[tuple[Path, int]] = []
        for candidate in self._root.rglob("*.json.gz"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            safe_path = _inside(self._root, candidate)
            stat = safe_path.stat()
            if stat.st_mtime < cutoff_timestamp:
                candidates.append((safe_path, stat.st_size))

        if apply:
            for path, _size in candidates:
                _inside(self._root, path).unlink()
        return PruneResult(
            file_count=len(candidates),
            total_bytes=sum(size for _path, size in candidates),
        )


def redact_credentials(value: object) -> object:
    """递归移除大小写及分隔符形式不同的认证字段。"""

    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        sanitized: dict[str, object] = {}
        for key, item in mapping.items():
            string_key = str(key)
            normalized_key = re.sub(r"[^a-z0-9]", "", string_key.casefold())
            if normalized_key in _SENSITIVE_KEYS:
                continue
            sanitized[string_key] = redact_credentials(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        items = cast(list[object] | tuple[object, ...], value)
        return [redact_credentials(item) for item in items]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _identifier(value: str, name: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None or ".." in value:
        raise ValueError(f"{name} 含危险路径标识")
    return value


def _archive_location_identifier(value: str) -> str:
    match = _QWEATHER_SOURCE_ID.fullmatch(value)
    if match is not None:
        latitude, longitude = match.groups()
        return f"qweather_{latitude.replace('-', 'm').replace('.', '_')}_{longitude.replace('-', 'm').replace('.', '_')}"
    return _identifier(value, "location_key")


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("归档路径超出根目录") from None
    return resolved


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["Archive", "PruneResult", "redact_credentials"]
