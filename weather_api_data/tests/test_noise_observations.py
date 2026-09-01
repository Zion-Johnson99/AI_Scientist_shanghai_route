from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from weather_api_data.noise_observations import (
    XUHUI_NOISE_POINT_IDS,
    build_noise_calibration,
    clean_noise_observations,
    write_noise_data_products,
)

SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


def _record(
    record_id: str,
    pointid: str,
    stime: str,
    laeq: object,
    *,
    deleted: object = "0",
    updated_at: str = "2026-08-26 10:10:00",
) -> dict[str, object]:
    return {
        "id": record_id,
        "stime": stime,
        "l90": "46.1",
        "pointid": pointid,
        "jhpt_delete": deleted,
        "fs": "2.4",
        "ywsj_date": stime,
        "laeq": laeq,
        "shidu": "71",
        "qw": "29.4",
        "sd": "1.3",
        "jhpt_update_time": updated_at,
        "lmin": "42.0",
        "l50": "49.2",
        "yl": "0",
        "qy": "1006.2",
        "l10": "55.8",
        "lmax": "67.4",
    }


def test_cleaner_filters_scope_deleted_zero_invalid_and_duplicate_records() -> None:
    pointid = XUHUI_NOISE_POINT_IDS[0]
    records: list[object] = [
        _record("old", pointid, "2026-08-26 10:00:00", "52.0"),
        _record(
            "new",
            pointid,
            "2026-08-26 10:00:00",
            "54.0",
            updated_at="2026-08-26 10:20:00",
        ),
        _record("deleted", pointid, "2026-08-26 11:00:00", "55", deleted="1"),
        _record("zero", pointid, "2026-08-26 12:00:00", "0"),
        _record("bad-time", pointid, "invalid", "56"),
        _record("other", "310101000001", "2026-08-26 13:00:00", "57"),
        "not-an-object",
    ]

    result = clean_noise_observations(records)

    assert result.input_count == 7
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.record_id == "new"
    assert observation.point_id == pointid
    assert observation.observed_at == datetime(2026, 8, 26, 10, tzinfo=SHANGHAI_TIMEZONE)
    assert observation.laeq == 54.0
    assert observation.l10 == 55.8
    assert observation.l50 == 49.2
    assert observation.l90 == 46.1
    assert result.discarded == {
        "invalid_record": 1,
        "outside_xuhui": 1,
        "deleted": 1,
        "invalid_time": 1,
        "invalid_laeq": 1,
        "invalid_distribution": 0,
        "duplicate": 1,
    }


def test_cleaner_parses_optional_numbers_and_keeps_invalid_optional_values_missing() -> None:
    record = _record("1", XUHUI_NOISE_POINT_IDS[1], "2026-08-26T10:00:00+08:00", 51)
    record["l10"] = "bad"
    record["shidu"] = None

    observation = clean_noise_observations([record]).observations[0]

    assert observation.laeq == 51.0
    assert observation.l10 is None
    assert observation.shidu is None
    assert observation.qw == 29.4
    assert observation.updated_at == datetime(2026, 8, 26, 10, 10, tzinfo=SHANGHAI_TIMEZONE)


def test_cleaner_accepts_uppercase_csv_headers_and_rejects_invalid_distribution() -> None:
    valid = {
        key.upper(): value
        for key, value in _record(
            "upper",
            XUHUI_NOISE_POINT_IDS[0],
            "2026-08-26 10:00:00",
            "53.0",
        ).items()
    }
    invalid = _record(
        "bad-order",
        XUHUI_NOISE_POINT_IDS[0],
        "2026-08-26 11:00:00",
        "53.0",
    )
    invalid["l10"] = "40"
    invalid["l50"] = "50"
    invalid["l90"] = "60"

    result = clean_noise_observations([valid, invalid])

    assert [item.record_id for item in result.observations] == ["upper"]
    assert result.discarded["invalid_distribution"] == 1


def test_calibration_reports_station_and_district_robust_laeq_baselines() -> None:
    point_a, point_b = XUHUI_NOISE_POINT_IDS[:2]
    records = [
        _record("1", point_a, "2026-08-26 08:00:00", "48"),
        _record("2", point_a, "2026-08-26 09:00:00", "52"),
        _record("3", point_b, "2026-08-26 08:30:00", "60"),
    ]

    document = build_noise_calibration(records)

    assert document["status"] == "partial"
    assert document["metric"] == "LAeq"
    assert document["unit"] == "dB(A)"
    assert document["station_count"] == 2
    assert document["observation_count"] == 3
    district = cast(dict[str, object], document["district_baseline"])
    assert district == {
        "laeq_median": 52.0,
        "sample_count": 3,
        "observed_from": "2026-08-26T08:00:00+08:00",
        "observed_to": "2026-08-26T09:00:00+08:00",
    }
    stations = cast(list[dict[str, object]], document["station_baselines"])
    assert stations == [
        {
            "pointid": point_a,
            "laeq_median": 50.0,
            "sample_count": 2,
            "observed_from": "2026-08-26T08:00:00+08:00",
            "observed_to": "2026-08-26T09:00:00+08:00",
        },
        {
            "pointid": point_b,
            "laeq_median": 60.0,
            "sample_count": 1,
            "observed_from": "2026-08-26T08:30:00+08:00",
            "observed_to": "2026-08-26T08:30:00+08:00",
        },
    ]
    calibration = cast(dict[str, object], document["calibration"])
    assert calibration == {
        "target": "noise_risk_score",
        "score_range": [0, 100],
        "method": "observed_laeq_median_anchor",
        "district_anchor": 52.0,
        "station_anchors": {point_a: 50.0, point_b: 60.0},
        "zone_anchors": {"2": 50.0, "3": 60.0},
    }
    assert "segment_laeq" not in document
    assert "segment_db" not in document


def test_calibration_returns_explicit_no_data_document() -> None:
    document = build_noise_calibration(
        [_record("zero", XUHUI_NOISE_POINT_IDS[0], "2026-08-26 12:00:00", 0)]
    )

    assert document["status"] == "no_data"
    assert document["district_baseline"] is None
    assert document["station_baselines"] == []
    assert document["calibration"] == {
        "target": "noise_risk_score",
        "score_range": [0, 100],
        "method": "observed_laeq_median_anchor",
        "district_anchor": None,
        "station_anchors": {},
        "zone_anchors": {},
    }


def test_write_noise_data_products_normalizes_csv_and_records_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    rows = [
        _record("1", XUHUI_NOISE_POINT_IDS[0], "2026-08-26 08:00:00", "50"),
        _record("2", "310101000001", "2026-08-26 08:00:00", "60"),
    ]
    headers = list(rows[0])
    source.write_text(
        ",".join(name.upper() for name in headers)
        + "\n"
        + "\n".join(",".join(str(row[name]) for name in headers) for row in rows)
        + "\n",
        encoding="utf-8-sig",
    )

    result = write_noise_data_products(source, tmp_path / "processed")

    assert result.observations_path.is_file()
    assert result.calibration_path.is_file()
    calibration = cast(dict[str, object], result.calibration)
    assert calibration["observation_count"] == 1
    provenance = cast(dict[str, object], calibration["provenance"])
    assert provenance["dataset_id"] == "O5485687412025006"
    assert len(cast(str, provenance["source_sha256"])) == 64
    assert "310104320001" in result.observations_path.read_text(encoding="utf-8-sig")
