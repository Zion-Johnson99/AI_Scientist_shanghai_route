import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from weather_api_data.history_store import HistoryStore, HistoryStoreError, InvalidRecordError
from weather_api_data.models import NormalizedRecord, Status

BUSINESS_TABLES = (
    "weather_observations",
    "weather_forecasts",
    "air_quality_observations",
    "air_quality_forecasts",
    "climate_actuals",
    "life_indices",
    "alerts",
)
ALL_TABLES = {"runs", "sources", *BUSINESS_TABLES}
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "history_records.json"


def _load_records() -> list[NormalizedRecord]:
    items = cast(list[dict[str, object]], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    return [
        NormalizedRecord(
            dataset_type=cast(str, item["dataset_type"]),
            dataset_role=cast(str, item["dataset_role"]),
            granularity=cast(str, item["granularity"]),
            location_key=cast(str, item["location_key"]),
            probe_point_ids=tuple(cast(list[str], item["probe_point_ids"])),
            business_time=cast(str | None, item["business_time"]),
            fetched_at=cast(str, item["fetched_at"]),
            valid_until=cast(str | None, item["valid_until"]),
            status=cast(Status, item["status"]),
            source=cast(Mapping[str, object], item["source"]),
            values=cast(Mapping[str, object], item["values"]),
            units=cast(Mapping[str, object], item["units"]),
            completeness=cast(float, item["completeness"]),
            missing_fields=tuple(cast(list[str], item["missing_fields"])),
            raw_data=cast(Mapping[str, object], item["raw_data"]),
        )
        for item in items
    ]


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "weathercn_history.sqlite3"


@pytest.fixture
def store(database_path: Path) -> Iterator[HistoryStore]:
    history_store = HistoryStore(database_path)
    yield history_store
    history_store.close()


def _query(
    database_path: Path, sql: str, parameters: tuple[object, ...] = ()
) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(database_path)
    try:
        return cast(list[tuple[object, ...]], connection.execute(sql, parameters).fetchall())
    finally:
        connection.close()


def _count(database_path: Path, table: str) -> int:
    return cast(int, _query(database_path, f"SELECT COUNT(*) FROM {table}")[0][0])


def test_initialization_creates_nine_tables_and_wal(database_path: Path) -> None:
    store = HistoryStore(database_path)
    store.close()

    table_names = {
        cast(str, row[0])
        for row in _query(
            database_path,
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
        )
    }

    assert table_names == ALL_TABLES
    assert _query(database_path, "PRAGMA journal_mode")[0][0] == "wal"


def test_business_tables_expose_quality_and_query_columns(database_path: Path) -> None:
    store = HistoryStore(database_path)
    store.close()

    required_columns = {
        "status",
        "completeness",
        "dataset_role",
        "granularity",
        "valid_until",
    }
    for table in BUSINESS_TABLES:
        columns = {
            cast(str, row[1]) for row in _query(database_path, f"PRAGMA table_info({table})")
        }
        assert required_columns <= columns


def test_write_records_routes_every_dataset_and_uses_canonical_json(
    store: HistoryStore, database_path: Path
) -> None:
    inserted = store.write_records(_load_records())

    assert inserted == {table: 1 for table in BUSINESS_TABLES}
    assert all(_count(database_path, table) == 1 for table in BUSINESS_TABLES)
    assert _count(database_path, "sources") == 1
    source_json = cast(str, _query(database_path, "SELECT source_json FROM sources")[0][0])
    assert source_json == '{"meta":{"id":7,"region":"CN"},"name":"WeatherCN"}'
    record_json = cast(
        str,
        _query(database_path, "SELECT record_json FROM weather_observations")[0][0],
    )
    assert record_json == json.dumps(
        _load_records()[0].to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_observation_is_idempotent_but_different_sources_are_preserved(
    store: HistoryStore, database_path: Path
) -> None:
    observation = _load_records()[0]
    store.write_records([observation, observation])
    assert _count(database_path, "weather_observations") == 1

    other_source = replace(
        observation, source={"name": "WeatherCN", "meta": {"id": 8, "region": "CN"}}
    )
    store.write_records([other_source])

    assert _count(database_path, "weather_observations") == 2
    assert _count(database_path, "sources") == 2
    assert (
        len({cast(str, row[0]) for row in _query(database_path, "SELECT source_key FROM sources")})
        == 2
    )


def test_observation_updates_to_higher_quality_and_rejects_later_regression(
    store: HistoryStore, database_path: Path
) -> None:
    base = _load_records()[0]
    partial = replace(
        base,
        fetched_at="2026-08-24T12:00:00+00:00",
        status="partial",
        completeness=0.5,
        values={"temperature": 25.0},
        missing_fields=("relative_humidity_pct",),
        raw_data={"version": "partial"},
    )
    complete = replace(
        base,
        fetched_at="2026-08-24T12:10:00+00:00",
        status="ok",
        completeness=1.0,
        values={"temperature": 28.0},
        missing_fields=(),
        raw_data={"version": "ok"},
    )
    worse = replace(
        base,
        fetched_at="2026-08-24T12:20:00+00:00",
        status="partial",
        completeness=0.8,
        values={"temperature": 99.0},
        missing_fields=("weather_text",),
        raw_data={"version": "regression"},
    )

    assert store.write_records([partial])["weather_observations"] == 1
    assert store.write_records([complete])["weather_observations"] == 1
    assert store.write_records([complete])["weather_observations"] == 0
    assert store.write_records([worse])["weather_observations"] == 0

    status, completeness, fetched_at, record_json = _query(
        database_path,
        "SELECT status, completeness, fetched_at, record_json FROM weather_observations",
    )[0]
    assert status == "ok"
    assert completeness == 1.0
    assert cast(str, fetched_at).startswith("2026-08-24T12:10:00")
    assert json.loads(cast(str, record_json))["raw_data"] == {"version": "ok"}


def test_ok_replaces_stale_record_at_equal_completeness(
    store: HistoryStore, database_path: Path
) -> None:
    base = _load_records()[0]
    stale = replace(
        base,
        fetched_at="2026-08-24T12:00:00+00:00",
        status="stale",
        completeness=1.0,
        raw_data={"version": "stale"},
    )
    fresh = replace(
        base,
        fetched_at="2026-08-24T12:10:00+00:00",
        status="ok",
        completeness=1.0,
        raw_data={"version": "fresh"},
    )

    assert store.write_records([stale])["weather_observations"] == 1
    assert store.write_records([fresh])["weather_observations"] == 1

    status, completeness, record_json = _query(
        database_path,
        "SELECT status, completeness, record_json FROM weather_observations",
    )[0]
    assert status == "ok"
    assert completeness == 1.0
    assert json.loads(cast(str, record_json))["raw_data"] == {"version": "fresh"}


def test_weather_observation_window_24h_uses_shanghai_slots_and_latest_records(
    store: HistoryStore,
) -> None:
    base = _load_records()[0]
    location_key = "qweather:31.190,121.438"
    records = [
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-26T09:59:59+08:00",
            fetched_at="2026-08-26T10:00:10+08:00",
            values={"temperature": 1.0},
        ),
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-26T10:05:00+08:00",
            fetched_at="2026-08-26T10:05:10+08:00",
            values={"temperature": 10.0},
        ),
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-26T10:55:00+08:00",
            fetched_at="2026-08-26T10:55:10+08:00",
            values={"temperature": 11.0},
        ),
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-27T00:00:00+00:00",
            fetched_at="2026-08-27T00:00:10+00:00",
            values={"temperature": 20.0},
        ),
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-27T09:00:00+08:00",
            fetched_at="2026-08-27T09:01:00+08:00",
            source={"name": "older-fetch"},
            values={"temperature": 30.0},
        ),
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-27T09:00:00+08:00",
            fetched_at="2026-08-27T09:02:00+08:00",
            source={"name": "newer-fetch"},
            values={"temperature": 31.0},
        ),
        replace(
            base,
            location_key=location_key,
            business_time="2026-08-27T09:45:00+08:00",
            fetched_at="2026-08-27T09:45:10+08:00",
            values={"temperature": 99.0},
        ),
        replace(
            base,
            location_key="qweather:other",
            business_time="2026-08-27T08:30:00+08:00",
            fetched_at="2026-08-27T08:30:10+08:00",
            values={"temperature": 88.0},
        ),
    ]
    store.write_records(records)

    window = store.weather_observation_window_24h(
        end_at=datetime(2026, 8, 27, 9, 30, tzinfo=timezone(timedelta(hours=8))),
        location_key=location_key,
    )

    selected = cast(list[dict[str, object]], window["records"])
    assert [record["business_time"] for record in selected] == [
        "2026-08-26T10:55:00+08:00",
        "2026-08-27T00:00:00+00:00",
        "2026-08-27T09:00:00+08:00",
    ]
    assert [cast(dict[str, object], record["values"])["temperature"] for record in selected] == [
        11.0,
        20.0,
        31.0,
    ]
    summary = cast(dict[str, object], window["summary"])
    assert summary["status"] == "partial"
    assert summary["expected_hours"] == 24
    assert summary["available_hours"] == 3
    missing_hours = cast(list[str], summary["missing_hours"])
    assert len(missing_hours) == 21
    assert "2026-08-26T10:00:00+08:00" not in missing_hours
    assert "2026-08-27T08:00:00+08:00" not in missing_hours
    assert "2026-08-27T09:00:00+08:00" not in missing_hours


def test_weather_observation_window_24h_returns_complete_legacy_location_window(
    store: HistoryStore,
) -> None:
    base = _load_records()[0]
    start = datetime(2026, 8, 26, 10, tzinfo=timezone(timedelta(hours=8)))
    store.write_records(
        [
            replace(
                base,
                business_time=(start + timedelta(hours=offset)).isoformat(),
                fetched_at=(start + timedelta(hours=offset, minutes=1)).isoformat(),
                values={"temperature": float(offset)},
            )
            for offset in range(24)
        ]
    )

    window = store.weather_observation_window_24h(
        end_at=datetime(2026, 8, 27, 9, tzinfo=timezone(timedelta(hours=8))),
        location_key=base.location_key,
    )

    assert len(cast(list[object], window["records"])) == 24
    assert window["summary"] == {
        "status": "ok",
        "expected_hours": 24,
        "available_hours": 24,
        "missing_hours": [],
    }


def test_weather_observation_window_24h_reports_no_data_and_validates_inputs(
    store: HistoryStore,
) -> None:
    window = store.weather_observation_window_24h(
        end_at=datetime(2026, 8, 27, 9, tzinfo=timezone(timedelta(hours=8))),
        location_key="missing",
    )
    assert window == {
        "records": [],
        "summary": {
            "status": "no_data",
            "expected_hours": 24,
            "available_hours": 0,
            "missing_hours": [
                (
                    datetime(2026, 8, 26, 10, tzinfo=timezone(timedelta(hours=8)))
                    + timedelta(hours=i)
                ).isoformat()
                for i in range(24)
            ],
        },
    }

    with pytest.raises(HistoryStoreError, match="end_at 需包含时区信息"):
        store.weather_observation_window_24h(
            end_at=datetime(2026, 8, 27, 9),
            location_key="missing",
        )
    with pytest.raises(HistoryStoreError, match="location_key 为空"):
        store.weather_observation_window_24h(
            end_at=datetime(2026, 8, 27, 9, tzinfo=timezone.utc),
            location_key=" ",
        )


@pytest.mark.parametrize(
    ("record_index", "table"),
    ((1, "weather_forecasts"), (3, "air_quality_forecasts")),
)
def test_forecasts_keep_versions_from_different_fetches(
    record_index: int, table: str, store: HistoryStore, database_path: Path
) -> None:
    forecast = _load_records()[record_index]
    newer = replace(forecast, fetched_at="2026-08-24T12:10:00+00:00")

    store.write_records([forecast, forecast, newer])

    assert _count(database_path, table) == 2


@pytest.mark.parametrize(
    ("record_index", "table", "identity_field", "identity_value"),
    (
        (5, "life_indices", "index_id", 128),
        (6, "alerts", "alert_id", 999),
    ),
)
def test_life_indices_and_alerts_include_business_identity_in_uniqueness(
    record_index: int,
    table: str,
    identity_field: str,
    identity_value: int,
    store: HistoryStore,
    database_path: Path,
) -> None:
    original = _load_records()[record_index]
    values = dict(original.values)
    values[identity_field] = identity_value

    store.write_records([original, replace(original, values=values)])

    assert _count(database_path, table) == 2


def test_invalid_record_rolls_back_entire_batch(store: HistoryStore, database_path: Path) -> None:
    valid = _load_records()[0]
    invalid = replace(valid, dataset_type="unsupported")

    with pytest.raises(InvalidRecordError, match="unsupported"):
        store.write_records([valid, invalid])

    assert _count(database_path, "weather_observations") == 0
    assert _count(database_path, "sources") == 0


def test_prune_history_is_dry_run_then_deletes_strictly_before_365_day_cutoff(
    store: HistoryStore, database_path: Path
) -> None:
    base = _load_records()[0]
    now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=365)
    older = replace(
        base,
        business_time="2025-08-23T11:59:59+00:00",
        fetched_at=(cutoff - timedelta(seconds=1)).isoformat(),
    )
    boundary = replace(
        base,
        business_time="2025-08-24T12:00:00+00:00",
        fetched_at=cutoff.isoformat(),
    )
    newer = replace(
        base,
        business_time="2025-08-24T12:00:01+00:00",
        fetched_at=(cutoff + timedelta(seconds=1)).isoformat(),
    )
    store.write_records([older, boundary, newer])

    expected = {table: int(table == "weather_observations") for table in BUSINESS_TABLES}
    assert store.prune_history(cutoff.isoformat()) == expected
    assert _count(database_path, "weather_observations") == 3

    assert store.prune_history(cutoff.isoformat(), apply=True) == expected
    assert _count(database_path, "weather_observations") == 2
    fetched_at = [
        cast(str, row[0])
        for row in _query(
            database_path,
            "SELECT fetched_at FROM weather_observations ORDER BY fetched_at",
        )
    ]
    assert fetched_at[0].startswith("2025-08-24T12:00:00")


def test_run_start_and_finish_keep_canonical_metadata(
    store: HistoryStore, database_path: Path
) -> None:
    store.start_run(
        "run-001",
        started_at="2026-08-24T12:00:00+00:00",
        metadata={"zone": "xuhui", "attempt": 1},
    )
    store.finish_run(
        "run-001",
        finished_at="2026-08-24T12:10:00+00:00",
        status="completed",
        summary={"written": 7, "errors": 0},
    )

    rows = _query(
        database_path,
        "SELECT run_id, status, metadata_json, summary_json, finished_at FROM runs",
    )
    assert rows == [
        (
            "run-001",
            "completed",
            '{"attempt":1,"zone":"xuhui"}',
            '{"errors":0,"written":7}',
            "2026-08-24T12:10:00.000000+00:00",
        )
    ]


def test_finish_unknown_run_reports_clear_error(store: HistoryStore) -> None:
    with pytest.raises(HistoryStoreError, match="run-missing"):
        store.finish_run(
            "run-missing",
            finished_at="2026-08-24T12:10:00+00:00",
            status="failed",
        )
