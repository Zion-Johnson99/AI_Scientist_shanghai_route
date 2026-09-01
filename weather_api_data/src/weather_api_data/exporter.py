"""固定四类环境 JSON 文档的原子导出。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from weather_api_data.archive import redact_credentials
from weather_api_data.models import NormalizedRecord

SCHEMA_VERSION = "1.0"
_OUTPUT_NAMES = (
    "environment_regions.json",
    "environment_latest.json",
    "environment_hourly.json",
    "run_report.json",
)
_EXPOSURE_OUTPUT_NAMES = frozenset(
    {
        "pollen_grid_scores.json",
        "noise_segments.json",
        "noise_observation_latest.json",
        "route_environment.json",
        "grid_environment_latest.json",
    }
)
_Input = Mapping[str, object] | Sequence[NormalizedRecord]


class Exporter:
    """一次原子写出四类固定名称的公开 JSON 文档。"""

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir).resolve(strict=False)

    def export(
        self,
        environment_regions: _Input,
        environment_latest: _Input,
        environment_hourly: _Input,
        run_report: _Input,
        *,
        schema_version: str = SCHEMA_VERSION,
        generated_at: str | datetime | None = None,
    ) -> dict[str, Path]:
        """为固定输出补齐元数据并逐文件原子替换。"""

        generated = _generated_at(generated_at)
        inputs = (
            environment_regions,
            environment_latest,
            environment_hourly,
            run_report,
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        documents: list[tuple[Path, Mapping[str, object]]] = []
        for name, value in zip(_OUTPUT_NAMES, inputs, strict=True):
            target = _inside(self._output_dir, self._output_dir / name)
            document = _document(value, schema_version, generated)
            documents.append((target, document))
            paths[name] = target
        _atomic_json_group(documents)
        return paths


def export_exposure_documents(
    output_dir: str | Path,
    values: Mapping[str, Mapping[str, object]],
    *,
    schema_version: str = SCHEMA_VERSION,
    generated_at: str | datetime | None = None,
) -> dict[str, Path]:
    """按固定文件名原子写出花粉、噪声和路线暴露文档。"""

    names = set(values)
    if not names or not names <= _EXPOSURE_OUTPUT_NAMES:
        raise ValueError(f"暴露输出文件名仅允许 {sorted(_EXPOSURE_OUTPUT_NAMES)}")
    root = Path(output_dir).resolve(strict=False)
    generated = _generated_at(generated_at)
    documents: list[tuple[Path, Mapping[str, object]]] = []
    paths: dict[str, Path] = {}
    for name in sorted(values):
        target = _inside(root, root / name)
        documents.append((target, _document(values[name], schema_version, generated)))
        paths[name] = target
    root.mkdir(parents=True, exist_ok=True)
    _atomic_json_group(documents)
    return paths


def _document(value: _Input, schema_version: str, generated_at: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        converted = _jsonable(value)
        assert isinstance(converted, dict)
        document: dict[str, object] = cast(dict[str, object], converted)
    else:
        records: list[object] = []
        for item in value:
            records.append(item.to_dict())
        document = {"records": records}
    document["schema_version"] = schema_version
    document["generated_at"] = generated_at
    sanitized = redact_credentials(document)
    assert isinstance(sanitized, dict)
    return cast(dict[str, object], sanitized)


def _jsonable(value: object) -> object:
    if isinstance(value, NormalizedRecord):
        return value.to_dict()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast(list[object] | tuple[object, ...], value)
        return [_jsonable(item) for item in items]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"不支持 JSON 序列化的类型: {type(value).__name__}")


def _atomic_json_group(documents: Sequence[tuple[Path, Mapping[str, object]]]) -> None:
    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    try:
        staged = [(target, _stage_json(target, document)) for target, document in documents]
        for target, _temp_path in staged:
            backups[target] = _backup(target)
        for target, temp_path in staged:
            os.replace(temp_path, target)
            committed.append(target)
    except Exception:
        for target in reversed(committed):
            backup = backups.get(target)
            if backup is None:
                if target.exists():
                    target.unlink()
            else:
                shutil.copyfile(backup, target)
                backup.unlink()
                backups[target] = None
        raise
    finally:
        for _target, temp_path in staged:
            if temp_path.exists():
                temp_path.unlink()
        for backup in backups.values():
            if backup is not None and backup.exists():
                backup.unlink()


def _stage_json(target: Path, document: Mapping[str, object]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
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
        except Exception:
            handle.close()
            temp_path.unlink(missing_ok=True)
            raise
    return temp_path


def _backup(target: Path) -> Path | None:
    if not target.exists():
        return None
    with tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".bak",
        delete=False,
    ) as handle:
        backup = Path(handle.name)
    try:
        shutil.copyfile(target, backup)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("输出路径超出 output_dir") from None
    return resolved


def _generated_at(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


__all__ = ["SCHEMA_VERSION", "Exporter", "export_exposure_documents"]
