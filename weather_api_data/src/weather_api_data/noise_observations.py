"""清洗徐汇噪声监测观测并生成风险模型校准基线。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import cast

XUHUI_NOISE_POINT_IDS = (
    "310104320001",
    "310104330002",
    "310104340004",
    "310104340006",
)
_XUHUI_POINT_ID_SET = frozenset(XUHUI_NOISE_POINT_IDS)
_SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))
_DISCARD_REASONS = (
    "invalid_record",
    "outside_xuhui",
    "deleted",
    "invalid_time",
    "invalid_laeq",
    "invalid_distribution",
    "duplicate",
)


@dataclass(frozen=True, slots=True)
class NoiseObservation:
    """一条通过范围、删除、时间与 LAeq 校验的官方站点观测。"""

    record_id: str
    point_id: str
    observed_at: datetime
    effective_at: datetime | None
    updated_at: datetime | None
    laeq: float
    l10: float | None
    l50: float | None
    l90: float | None
    lmin: float | None
    lmax: float | None
    fs: float | None
    shidu: float | None
    qw: float | None
    sd: float | None
    yl: float | None
    qy: float | None


@dataclass(frozen=True, slots=True)
class NoiseObservationBatch:
    """清洗后的观测及可审计丢弃计数。"""

    observations: tuple[NoiseObservation, ...]
    input_count: int
    discarded: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class NoiseDataProducts:
    """历史 CSV 清洗后写出的徐汇观测与校准基线。"""

    observations_path: Path
    calibration_path: Path
    calibration: Mapping[str, object]


def clean_noise_observations(records: Iterable[object]) -> NoiseObservationBatch:
    """筛选徐汇四站观测并按站点和观测时间去重。"""

    input_count = 0
    discarded: dict[str, int] = {reason: 0 for reason in _DISCARD_REASONS}
    unique: dict[tuple[str, datetime], NoiseObservation] = {}
    for value in records:
        input_count += 1
        if not isinstance(value, Mapping):
            discarded["invalid_record"] += 1
            continue
        raw_record = cast(Mapping[object, object], value)
        record = {str(key).strip().lower(): item for key, item in raw_record.items()}
        point_id = str(record.get("pointid", "")).strip()
        if point_id not in _XUHUI_POINT_ID_SET:
            discarded["outside_xuhui"] += 1
            continue
        if _is_deleted(record.get("jhpt_delete")):
            discarded["deleted"] += 1
            continue
        observed_at = _datetime(record.get("stime"))
        if observed_at is None:
            discarded["invalid_time"] += 1
            continue
        laeq = _number(record.get("laeq"))
        if laeq is None or not 0 < laeq <= 150:
            discarded["invalid_laeq"] += 1
            continue
        l10 = _number(record.get("l10"))
        l50 = _number(record.get("l50"))
        l90 = _number(record.get("l90"))
        lmin = _number(record.get("lmin"))
        lmax = _number(record.get("lmax"))
        if not _valid_distribution(
            laeq=laeq,
            l10=l10,
            l50=l50,
            l90=l90,
            lmin=lmin,
            lmax=lmax,
        ):
            discarded["invalid_distribution"] += 1
            continue
        observation = NoiseObservation(
            record_id=str(record.get("id", "")).strip(),
            point_id=point_id,
            observed_at=observed_at,
            effective_at=_datetime(record.get("ywsj_date")),
            updated_at=_datetime(record.get("jhpt_update_time")),
            laeq=laeq,
            l10=l10,
            l50=l50,
            l90=l90,
            lmin=lmin,
            lmax=lmax,
            fs=_number(record.get("fs")),
            shidu=_number(record.get("shidu")),
            qw=_number(record.get("qw")),
            sd=_number(record.get("sd")),
            yl=_number(record.get("yl")),
            qy=_number(record.get("qy")),
        )
        key = (point_id, observed_at)
        existing = unique.get(key)
        if existing is not None:
            discarded["duplicate"] += 1
            if _update_rank(observation) <= _update_rank(existing):
                continue
        unique[key] = observation
    observations = tuple(
        sorted(unique.values(), key=lambda item: (item.observed_at, item.point_id))
    )
    return NoiseObservationBatch(observations, input_count, discarded)


def build_noise_calibration(records: Iterable[object]) -> dict[str, object]:
    """计算 LAeq 中位数基线供 0 至 100 风险分值校准使用。"""

    return _calibration_document(clean_noise_observations(records))


def write_noise_data_products(source_path: Path, output_dir: Path) -> NoiseDataProducts:
    """流式读取官方 CSV 并写出徐汇清洗观测和可审计校准基线。"""

    if not source_path.is_file():
        raise FileNotFoundError(f"噪声历史 CSV 不存在: {source_path}")
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        batch = clean_noise_observations(csv.DictReader(handle))
    calibration = _calibration_document(batch)
    calibration["provenance"] = {
        "dataset_id": "O5485687412025006",
        "source_url": "https://data.sh.gov.cn/view/detail/index.html?id=O5485687412025006",
        "source_file": source_path.name,
        "source_sha256": _sha256(source_path),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    observations_path = output_dir / "xuhui_noise_observations.csv"
    calibration_path = output_dir / "xuhui_noise_baseline.json"
    _write_observations_csv(observations_path, batch.observations)
    _write_json(calibration_path, calibration)
    return NoiseDataProducts(observations_path, calibration_path, calibration)


def _calibration_document(batch: NoiseObservationBatch) -> dict[str, object]:
    by_station: dict[str, list[NoiseObservation]] = {}
    for observation in batch.observations:
        by_station.setdefault(observation.point_id, []).append(observation)
    station_baselines = [
        _baseline(station_records, point_id=point_id)
        for point_id, station_records in sorted(by_station.items())
    ]
    district_baseline = _baseline(batch.observations) if batch.observations else None
    station_anchors = {
        str(item["pointid"]): cast(float, item["laeq_median"]) for item in station_baselines
    }
    district_anchor = (
        cast(float, district_baseline["laeq_median"]) if district_baseline is not None else None
    )
    zone_pointids = {
        "2": ("310104320001",),
        "3": ("310104330002",),
        "4a": ("310104340004", "310104340006"),
    }
    zone_anchors = {
        zone_class: round(float(median(station_anchors[pointid] for pointid in pointids)), 3)
        for zone_class, pointids in zone_pointids.items()
        if all(pointid in station_anchors for pointid in pointids)
    }
    station_count = len(station_baselines)
    status = (
        "no_data"
        if not batch.observations
        else "ok"
        if station_count == len(XUHUI_NOISE_POINT_IDS)
        else "partial"
    )
    return {
        "schema_version": "1.0",
        "dataset_type": "noise_observation_calibration",
        "status": status,
        "metric": "LAeq",
        "unit": "dB(A)",
        "spatial_basis": "xuhui_monitoring_stations",
        "expected_pointids": list(XUHUI_NOISE_POINT_IDS),
        "station_count": station_count,
        "observation_count": len(batch.observations),
        "district_baseline": district_baseline,
        "station_baselines": station_baselines,
        "calibration": {
            "target": "noise_risk_score",
            "score_range": [0, 100],
            "method": "observed_laeq_median_anchor",
            "district_anchor": district_anchor,
            "station_anchors": station_anchors,
            "zone_anchors": zone_anchors,
        },
        "quality": {
            "input_count": batch.input_count,
            "retained_count": len(batch.observations),
            "discarded": dict(batch.discarded),
        },
    }


def _write_observations_csv(path: Path, observations: Sequence[NoiseObservation]) -> None:
    fieldnames = tuple(NoiseObservation.__dataclass_fields__)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for observation in observations:
                writer.writerow(
                    {name: _csv_value(getattr(observation, name)) for name in fieldnames}
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _csv_value(value: object) -> object:
    return value.isoformat() if isinstance(value, datetime) else value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _baseline(
    observations: Sequence[NoiseObservation],
    *,
    point_id: str | None = None,
) -> dict[str, object]:
    times = [observation.observed_at for observation in observations]
    result: dict[str, object] = {
        "laeq_median": round(float(median(item.laeq for item in observations)), 3),
        "sample_count": len(observations),
        "observed_from": min(times).isoformat(),
        "observed_to": max(times).isoformat(),
    }
    if point_id is not None:
        return {"pointid": point_id, **result}
    return result


def _is_deleted(value: object) -> bool:
    if value is None or value is False or value == 0:
        return False
    if isinstance(value, str) and value.strip().lower() in {"", "0", "false"}:
        return False
    return True


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SHANGHAI_TIMEZONE)
    return parsed.astimezone(_SHANGHAI_TIMEZONE)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    result = float(parsed)
    return result if math.isfinite(result) else None


def _valid_distribution(
    *,
    laeq: float,
    l10: float | None,
    l50: float | None,
    l90: float | None,
    lmin: float | None,
    lmax: float | None,
) -> bool:
    if lmin is not None and lmin > laeq:
        return False
    if lmax is not None and laeq > lmax:
        return False
    percentiles = (l90, l50, l10)
    available = [value for value in percentiles if value is not None]
    return available == sorted(available)


def _update_rank(observation: NoiseObservation) -> datetime:
    return observation.updated_at or datetime.min.replace(tzinfo=_SHANGHAI_TIMEZONE)


__all__ = [
    "XUHUI_NOISE_POINT_IDS",
    "NoiseDataProducts",
    "NoiseObservation",
    "NoiseObservationBatch",
    "build_noise_calibration",
    "clean_noise_observations",
    "write_noise_data_products",
]
