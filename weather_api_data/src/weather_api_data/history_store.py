"""标准化气象与空气质量记录的 SQLite 历史库。"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from weather_api_data.models import NormalizedRecord

BUSINESS_TABLES = (
    "weather_observations",
    "weather_forecasts",
    "air_quality_observations",
    "air_quality_forecasts",
    "climate_actuals",
    "life_indices",
    "alerts",
)
DATASET_TABLES = {
    "weather_observation": "weather_observations",
    "weather_forecast": "weather_forecasts",
    "air_quality_observation": "air_quality_observations",
    "air_quality_forecast": "air_quality_forecasts",
    "climate_actual": "climate_actuals",
    "life_index": "life_indices",
    "weather_alert": "alerts",
}
TABLE_UNIQUE_COLUMNS = {
    "weather_observations": ("location_key", "business_time", "source_key"),
    "weather_forecasts": ("location_key", "business_time", "fetched_at", "source_key"),
    "air_quality_observations": ("location_key", "business_time", "source_key"),
    "air_quality_forecasts": ("location_key", "business_time", "fetched_at", "source_key"),
    "climate_actuals": ("location_key", "business_time", "source_key"),
    "life_indices": ("location_key", "business_time", "index_id", "source_key"),
    "alerts": ("location_key", "business_time", "alert_id", "source_key"),
}
IDENTITY_FIELDS = {"life_index": "index_id", "weather_alert": "alert_id"}
VALID_STATUSES = {"ok", "partial", "stale", "no_data", "error"}
SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
WEATHER_WINDOW_HOURS = 24


class HistoryStoreError(RuntimeError):
    """表示历史库初始化、写入或清理失败。"""


class InvalidRecordError(HistoryStoreError):
    """表示标准化记录不满足历史库约束。"""


def _canonical_json(value: object, context: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise HistoryStoreError(f"{context} 无法序列化为 JSON") from error


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise HistoryStoreError(f"{field_name} 需使用 ISO 8601 时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoryStoreError(f"{field_name} 需包含时区信息")
    return parsed


def _normalize_timestamp(value: str, field_name: str) -> str:
    return (
        _parse_timestamp(value, field_name)
        .astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
    )


def _business_table_schema(
    table: str,
    unique_columns: tuple[str, ...],
    identity_column: str | None = None,
) -> str:
    identity_definition = f"{identity_column} TEXT NOT NULL," if identity_column else ""
    uniqueness = ", ".join(unique_columns)
    return f"""
        CREATE TABLE IF NOT EXISTS {table} (
            record_id INTEGER PRIMARY KEY,
            location_key TEXT NOT NULL,
            business_time TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            source_key TEXT NOT NULL,
            {identity_definition}
            dataset_role TEXT NOT NULL,
            granularity TEXT NOT NULL,
            valid_until TEXT,
            status TEXT NOT NULL,
            completeness REAL NOT NULL,
            record_json TEXT NOT NULL,
            UNIQUE ({uniqueness}),
            FOREIGN KEY (source_key) REFERENCES sources(source_key)
        )
    """


def _upsert_statement(table: str, columns: list[str]) -> str:
    conflict_columns = ", ".join(TABLE_UNIQUE_COLUMNS[table])
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in (
            "fetched_at",
            "dataset_role",
            "granularity",
            "valid_until",
            "status",
            "completeness",
            "record_json",
        )
    )
    placeholders = ", ".join("?" for _ in columns)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_columns}) DO UPDATE SET {updates} "
        f"WHERE excluded.completeness > {table}.completeness "
        f"OR (excluded.completeness = {table}.completeness "
        f"AND {table}.status = 'stale' AND excluded.status = 'ok')"
    )


class HistoryStore:
    """按数据类型归档 NormalizedRecord 并管理运行记录。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.database_path)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._create_schema()
        except sqlite3.Error as error:
            raise HistoryStoreError(f"初始化 SQLite 历史库失败: {self.database_path}") from error

    def _create_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                summary_json TEXT
            ) WITHOUT ROWID
            """,
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_key TEXT PRIMARY KEY,
                source_json TEXT NOT NULL
            ) WITHOUT ROWID
            """,
            _business_table_schema(
                "weather_observations",
                ("location_key", "business_time", "source_key"),
            ),
            _business_table_schema(
                "weather_forecasts",
                ("location_key", "business_time", "fetched_at", "source_key"),
            ),
            _business_table_schema(
                "air_quality_observations",
                ("location_key", "business_time", "source_key"),
            ),
            _business_table_schema(
                "air_quality_forecasts",
                ("location_key", "business_time", "fetched_at", "source_key"),
            ),
            _business_table_schema(
                "climate_actuals",
                ("location_key", "business_time", "source_key"),
            ),
            _business_table_schema(
                "life_indices",
                ("location_key", "business_time", "index_id", "source_key"),
                "index_id",
            ),
            _business_table_schema(
                "alerts",
                ("location_key", "business_time", "alert_id", "source_key"),
                "alert_id",
            ),
        )
        with self._connection:
            for statement in statements:
                self._connection.execute(statement)

    def close(self) -> None:
        """关闭 SQLite 连接。"""

        self._connection.close()

    def write_records(self, records: Iterable[object]) -> dict[str, int]:
        """在单个事务中批量写入标准化记录。"""

        inserted: dict[str, int] = {table: 0 for table in BUSINESS_TABLES}
        try:
            with self._connection:
                for position, record in enumerate(records):
                    if not isinstance(record, NormalizedRecord):
                        raise InvalidRecordError(f"第 {position + 1} 条记录需使用 NormalizedRecord")
                    table, source_key, source_json, fetched_at, identity = self._prepare_record(
                        record
                    )
                    self._write_source(source_key, source_json)
                    columns = [
                        "location_key",
                        "business_time",
                        "fetched_at",
                        "source_key",
                    ]
                    parameters: list[object] = [
                        record.location_key,
                        record.business_time,
                        fetched_at,
                        source_key,
                    ]
                    if identity is not None:
                        identity_name, identity_value = identity
                        columns.append(identity_name)
                        parameters.append(identity_value)
                    columns.extend(
                        (
                            "dataset_role",
                            "granularity",
                            "valid_until",
                            "status",
                            "completeness",
                            "record_json",
                        )
                    )
                    parameters.extend(
                        (
                            record.dataset_role,
                            record.granularity,
                            record.valid_until,
                            record.status,
                            record.completeness,
                            _canonical_json(record.to_dict(), "NormalizedRecord"),
                        )
                    )
                    cursor = self._connection.execute(
                        _upsert_statement(table, columns),
                        parameters,
                    )
                    if cursor.rowcount == 1:
                        inserted[table] += 1
        except sqlite3.Error as error:
            raise HistoryStoreError("SQLite 批量写入失败，事务已回滚") from error
        return inserted

    def _prepare_record(
        self, record: NormalizedRecord
    ) -> tuple[str, str, str, str, tuple[str, str] | None]:
        table = DATASET_TABLES.get(record.dataset_type)
        if table is None:
            raise InvalidRecordError(f"不支持的 dataset_type: {record.dataset_type or '<empty>'}")
        if not record.location_key.strip():
            raise InvalidRecordError("location_key 为空")
        if not record.business_time:
            raise InvalidRecordError("business_time 为空")
        if record.status not in VALID_STATUSES:
            raise InvalidRecordError(f"不支持的 status: {record.status}")
        if not math.isfinite(record.completeness) or not 0 <= record.completeness <= 1:
            raise InvalidRecordError("completeness 需位于 0 至 1 之间")
        try:
            fetched_at = _normalize_timestamp(record.fetched_at, "fetched_at")
            source_json = _canonical_json(record.to_dict()["source"], "source")
        except HistoryStoreError as error:
            raise InvalidRecordError(str(error)) from error
        source_key = hashlib.sha256(source_json.encode("utf-8")).hexdigest()

        identity: tuple[str, str] | None = None
        identity_name = IDENTITY_FIELDS.get(record.dataset_type)
        if identity_name is not None:
            identity_value = record.values.get(identity_name)
            if (
                isinstance(identity_value, bool)
                or not isinstance(identity_value, (str, int))
                or not str(identity_value).strip()
            ):
                raise InvalidRecordError(f"{record.dataset_type} 缺少有效 {identity_name}")
            identity = (identity_name, str(identity_value))
        return table, source_key, source_json, fetched_at, identity

    def _write_source(self, source_key: str, source_json: str) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO sources (source_key, source_json) VALUES (?, ?)",
            (source_key, source_json),
        )
        row = self._connection.execute(
            "SELECT source_json FROM sources WHERE source_key = ?", (source_key,)
        ).fetchone()
        if row is None or row[0] != source_json:
            raise HistoryStoreError(f"source_key 冲突: {source_key}")

    def weather_observation_window_24h(
        self,
        *,
        end_at: datetime,
        location_key: str,
    ) -> dict[str, object]:
        """返回指定空间来源最近 24 个上海本地整点槽中的真实天气观测。"""

        if end_at.tzinfo is None or end_at.utcoffset() is None:
            raise HistoryStoreError("end_at 需包含时区信息")
        if not location_key.strip():
            raise HistoryStoreError("location_key 为空")

        end_local = end_at.astimezone(SHANGHAI_TIMEZONE)
        end_hour = end_local.replace(minute=0, second=0, microsecond=0)
        start_hour = end_hour - timedelta(hours=WEATHER_WINDOW_HOURS - 1)
        try:
            rows = self._connection.execute(
                """
                SELECT business_time, fetched_at, record_json
                FROM weather_observations
                WHERE location_key = ?
                """,
                (location_key,),
            ).fetchall()
        except sqlite3.Error as error:
            raise HistoryStoreError("读取最近 24 小时天气观测失败") from error

        selected: dict[datetime, tuple[datetime, datetime, dict[str, object]]] = {}
        for business_time_value, fetched_at_value, record_json_value in rows:
            if not all(
                isinstance(value, str)
                for value in (business_time_value, fetched_at_value, record_json_value)
            ):
                raise HistoryStoreError("weather_observations 包含非文本时间或记录")
            business_time = _parse_timestamp(business_time_value, "business_time")
            fetched_at = _parse_timestamp(fetched_at_value, "fetched_at")
            if business_time > end_at:
                continue
            business_local = business_time.astimezone(SHANGHAI_TIMEZONE)
            slot = business_local.replace(minute=0, second=0, microsecond=0)
            if not start_hour <= slot <= end_hour:
                continue
            try:
                decoded = json.loads(record_json_value)
            except json.JSONDecodeError as error:
                raise HistoryStoreError("weather_observations record_json 无法解析") from error
            if not isinstance(decoded, dict):
                raise HistoryStoreError("weather_observations record_json 顶层应为对象")
            decoded_mapping = cast(dict[object, object], decoded)
            record: dict[str, object] = {str(key): value for key, value in decoded_mapping.items()}
            candidate = (business_time, fetched_at, record)
            existing = selected.get(slot)
            if existing is None or candidate[:2] > existing[:2]:
                selected[slot] = candidate

        expected_slots = tuple(
            start_hour + timedelta(hours=offset) for offset in range(WEATHER_WINDOW_HOURS)
        )
        records = [selected[slot][2] for slot in expected_slots if slot in selected]
        missing_hours = [slot.isoformat() for slot in expected_slots if slot not in selected]
        available_hours = len(records)
        status = "ok" if available_hours == WEATHER_WINDOW_HOURS else "partial"
        if available_hours == 0:
            status = "no_data"
        return {
            "records": records,
            "summary": {
                "status": status,
                "expected_hours": WEATHER_WINDOW_HOURS,
                "available_hours": available_hours,
                "missing_hours": missing_hours,
            },
        }

    def start_run(
        self,
        run_id: str,
        started_at: str,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """创建运行记录并标记为 running。"""

        if not run_id.strip():
            raise HistoryStoreError("run_id 为空")
        normalized_started_at = _normalize_timestamp(started_at, "started_at")
        metadata_json = _canonical_json(metadata or {}, "run metadata")
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO runs (run_id, started_at, status, metadata_json)
                    VALUES (?, ?, 'running', ?)
                    """,
                    (run_id, normalized_started_at, metadata_json),
                )
        except sqlite3.IntegrityError as error:
            raise HistoryStoreError(f"run_id 已存在: {run_id}") from error
        except sqlite3.Error as error:
            raise HistoryStoreError(f"创建运行记录失败: {run_id}") from error

    def finish_run(
        self,
        run_id: str,
        finished_at: str,
        status: str,
        summary: Mapping[str, object] | None = None,
    ) -> None:
        """完成已存在的运行记录。"""

        if not status.strip() or status == "running":
            raise HistoryStoreError("finish_run 需提供非 running 状态")
        normalized_finished_at = _normalize_timestamp(finished_at, "finished_at")
        summary_json = _canonical_json(summary or {}, "run summary")
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    UPDATE runs
                    SET finished_at = ?, status = ?, summary_json = ?
                    WHERE run_id = ?
                    """,
                    (normalized_finished_at, status, summary_json, run_id),
                )
                if cursor.rowcount != 1:
                    raise HistoryStoreError(f"未找到 run_id: {run_id}")
        except sqlite3.Error as error:
            raise HistoryStoreError(f"更新运行记录失败: {run_id}") from error

    def prune_history(self, cutoff: str, apply: bool = False) -> dict[str, int]:
        """统计或删除 fetched_at 严格早于截止时间的业务记录。"""

        normalized_cutoff = _normalize_timestamp(cutoff, "cutoff")
        counts: dict[str, int] = {}
        try:
            with self._connection:
                for table in BUSINESS_TABLES:
                    row = self._connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE fetched_at < ?",
                        (normalized_cutoff,),
                    ).fetchone()
                    if row is None:
                        raise HistoryStoreError(f"统计历史记录失败: {table}")
                    counts[table] = int(row[0])
                    if apply and counts[table]:
                        self._connection.execute(
                            f"DELETE FROM {table} WHERE fetched_at < ?",
                            (normalized_cutoff,),
                        )
        except sqlite3.Error as error:
            raise HistoryStoreError("清理 SQLite 历史记录失败") from error
        return counts


__all__ = ["HistoryStore", "HistoryStoreError", "InvalidRecordError"]
