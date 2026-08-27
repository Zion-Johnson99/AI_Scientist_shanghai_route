from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

import weather_api_data.archive as archive_module
import weather_api_data.exporter as exporter_module
from weather_api_data.archive import Archive, PruneResult
from weather_api_data.exporter import Exporter, export_exposure_documents
from weather_api_data.models import NormalizedRecord

FETCHED_AT = datetime(2026, 8, 24, 8, 9, 10, 123456, tzinfo=timezone.utc)
GENERATED_AT = "2026-08-24T08:10:00+00:00"


def normalized_record() -> NormalizedRecord:
    return NormalizedRecord(
        dataset_type="weather_observation",
        dataset_role="operational",
        granularity="current",
        location_key="101021200",
        probe_point_ids=("xuhui",),
        business_time="2026-08-24T16:00:00+08:00",
        fetched_at=FETCHED_AT.isoformat(),
        valid_until=None,
        status="ok",
        source={"name": "WeatherCN", "Authorization": "nested-secret"},
        values={"temperature_c": 30.0},
        units={"temperature_c": "C"},
        completeness=1.0,
        missing_fields=(),
        raw_data={"Api_Key": "raw-secret", "safe": {"value": 1}},
    )


def test_archive_writes_utf8_gzip_and_recursively_removes_credentials(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "raw")
    payload = {
        "city": "徐汇",
        "Authorization": "Bearer secret",
        "nested": {
            "api key": "secret-1",
            "apikey": "secret-2",
            "API_KEY": "secret-3",
            "Signature": "secret-4",
            "X-Gw-API-Key": "secret-5",
            "safe": [{"accessKey": "secret-6", "temperature": 30}],
        },
    }

    saved_path = archive.archive("current_conditions", "101021200", FETCHED_AT, payload)

    assert saved_path is not None
    assert saved_path.resolve().is_relative_to((tmp_path / "raw").resolve())
    with gzip.open(saved_path, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved == {
        "city": "徐汇",
        "nested": {"safe": [{"temperature": 30}]},
    }


def test_archive_excludes_geoposition_without_creating_files(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    archive = Archive(root)

    result = archive.archive("geoposition", "ignored", FETCHED_AT, {"Key": "value"})

    assert result is None
    assert not root.exists()


@pytest.mark.parametrize(
    ("endpoint", "location_key"),
    [
        ("../escape", "101021200"),
        ("/absolute", "101021200"),
        ("C:\\absolute", "101021200"),
        ("current_conditions", "../escape"),
        ("current_conditions", "/absolute"),
        ("current_conditions", "unsafe location"),
    ],
)
def test_archive_rejects_unsafe_identifiers_before_writing(
    tmp_path: Path, endpoint: str, location_key: str
) -> None:
    root = tmp_path / "raw"
    archive = Archive(root)

    with pytest.raises(ValueError):
        archive.archive(endpoint, location_key, FETCHED_AT, {"safe": True})

    assert not root.exists()


def test_archive_names_do_not_collide_within_the_same_second(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "raw")

    first = archive.archive("alerts", "101021200", FETCHED_AT, {"value": 1})
    second = archive.archive("alerts", "101021200", FETCHED_AT, {"value": 2})

    assert first is not None
    assert second is not None
    assert first != second
    assert first.exists()
    assert second.exists()


def test_archive_accepts_qweather_source_id_and_removes_qweather_header(
    tmp_path: Path,
) -> None:
    archive = Archive(tmp_path / "raw")

    saved_path = archive.archive(
        "current_conditions",
        "qweather:31.18,121.45",
        FETCHED_AT,
        {"X-QW-Api-Key": "secret", "temperature": 30},
    )

    assert saved_path is not None
    assert saved_path.parent.name == "qweather_31_18_121_45"
    with gzip.open(saved_path, "rt", encoding="utf-8") as handle:
        assert json.load(handle) == {"temperature": 30}


def test_archive_serialization_failure_leaves_no_final_or_temp_file(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    archive = Archive(root)

    with pytest.raises(TypeError):
        archive.archive("alerts", "101021200", FETCHED_AT, {"bad": object()})

    assert not list(root.rglob("*.json.gz"))
    assert not list(root.rglob("*.tmp"))


def test_archive_failure_preserves_existing_same_name_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "raw"
    archive = Archive(root)
    fixed_uuid = UUID("00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(archive_module, "uuid4", lambda: fixed_uuid)
    target = archive.archive("alerts", "101021200", FETCHED_AT, {"value": "old"})
    assert target is not None
    old_bytes = target.read_bytes()

    with pytest.raises(TypeError):
        archive.archive("alerts", "101021200", FETCHED_AT, {"bad": object()})

    assert target.read_bytes() == old_bytes
    assert not list(root.rglob("*.tmp"))


def test_archive_replace_failure_preserves_existing_file_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "raw"
    archive = Archive(root)
    fixed_uuid = UUID("00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(archive_module, "uuid4", lambda: fixed_uuid)
    target = archive.archive("alerts", "101021200", FETCHED_AT, {"value": "old"})
    assert target is not None
    old_bytes = target.read_bytes()

    def fail_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        del source, destination
        raise OSError("simulated archive replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated archive replace failure"):
        archive.archive("alerts", "101021200", FETCHED_AT, {"value": "new"})

    assert target.read_bytes() == old_bytes
    assert not list(root.rglob("*.tmp"))


def test_prune_uses_strict_mtime_boundary_and_dry_run_has_no_writes(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "raw")
    old_path = archive.archive("alerts", "old", FETCHED_AT, {"value": "old"})
    boundary_path = archive.archive("alerts", "boundary", FETCHED_AT, {"value": "boundary"})
    new_path = archive.archive("alerts", "new", FETCHED_AT, {"value": "new"})
    assert old_path is not None
    assert boundary_path is not None
    assert new_path is not None
    cutoff = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    os.utime(old_path, (cutoff.timestamp() - 1, cutoff.timestamp() - 1))
    os.utime(boundary_path, (cutoff.timestamp(), cutoff.timestamp()))
    os.utime(new_path, (cutoff.timestamp() + 1, cutoff.timestamp() + 1))
    old_size = old_path.stat().st_size

    dry_run = archive.prune(cutoff, apply=False)

    assert dry_run == PruneResult(file_count=1, total_bytes=old_size)
    assert old_path.exists()
    assert boundary_path.exists()
    assert new_path.exists()

    applied = archive.prune(cutoff, apply=True)

    assert applied == dry_run
    assert not old_path.exists()
    assert boundary_path.exists()
    assert new_path.exists()


def test_exporter_writes_only_four_documents_with_metadata_and_plain_records(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"
    exporter = Exporter(output_dir)
    record = normalized_record()

    paths = exporter.export(
        environment_regions={"regions": [{"location_key": "101021200"}]},
        environment_latest=[record],
        environment_hourly=(record,),
        run_report={
            "schema_version": "caller-schema",
            "generated_at": "caller-generated-at",
            "status": "ok",
        },
        schema_version="1.0",
        generated_at=GENERATED_AT,
    )

    expected_names = {
        "environment_regions.json",
        "environment_latest.json",
        "environment_hourly.json",
        "run_report.json",
    }
    assert set(paths) == expected_names
    assert {path.name for path in output_dir.iterdir()} == expected_names
    assert not (output_dir / "route_environment.json").exists()

    documents = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    for name in expected_names - {"run_report.json"}:
        assert documents[name]["schema_version"] == "1.0"
        assert documents[name]["generated_at"] == GENERATED_AT
    assert documents["run_report.json"]["schema_version"] == "1.0"
    assert documents["run_report.json"]["generated_at"] == GENERATED_AT
    assert documents["environment_latest.json"]["records"][0]["dataset_type"] == (
        "weather_observation"
    )
    assert isinstance(documents["environment_latest.json"]["records"][0], dict)


def test_exporter_recursively_removes_credentials_from_every_document(tmp_path: Path) -> None:
    exporter = Exporter(tmp_path / "output")
    sensitive = {
        "safe": {"value": 1},
        "authorization": "secret-1",
        "API Key": "secret-2",
        "signature": "secret-3",
        "x-gw-api-key": "secret-4",
    }

    paths = exporter.export(
        environment_regions=sensitive,
        environment_latest=[normalized_record()],
        environment_hourly={"nested": [sensitive]},
        run_report=sensitive,
        generated_at=GENERATED_AT,
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths.values())
    for secret in (
        "secret-1",
        "secret-2",
        "secret-3",
        "secret-4",
        "nested-secret",
        "raw-secret",
    ):
        assert secret not in combined


def test_atomic_replace_failure_preserves_old_file_and_removes_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    old_contents = {
        name: f'{{"old": "{name}"}}\n'
        for name in (
            "environment_regions.json",
            "environment_latest.json",
            "environment_hourly.json",
            "run_report.json",
        )
    }
    for name, content in old_contents.items():
        (output_dir / name).write_text(content, encoding="utf-8")
    real_replace = os.replace

    def fail_latest(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        if Path(destination).name == "environment_latest.json":
            raise OSError("simulated replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(exporter_module.os, "replace", fail_latest)
    exporter = Exporter(output_dir)

    with pytest.raises(OSError, match="simulated replace failure"):
        exporter.export(
            environment_regions={"regions": []},
            environment_latest={"records": []},
            environment_hourly={"records": []},
            run_report={"status": "ok"},
            generated_at=GENERATED_AT,
        )

    for name, content in old_contents.items():
        assert (output_dir / name).read_text(encoding="utf-8") == content
    assert not list(output_dir.glob("*.tmp"))
    assert not list(output_dir.glob("*.bak"))
    assert not (output_dir / "route_environment.json").exists()


def test_backup_failure_leaves_existing_group_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    target = output_dir / "environment_regions.json"
    old_content = '{"old": true}\n'
    target.write_text(old_content, encoding="utf-8")

    def fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("simulated backup failure")

    monkeypatch.setattr(exporter_module.shutil, "copyfile", fail_copy)

    with pytest.raises(OSError, match="simulated backup failure"):
        Exporter(output_dir).export(
            environment_regions={"regions": []},
            environment_latest={"records": []},
            environment_hourly={"records": []},
            run_report={"status": "ok"},
            generated_at=GENERATED_AT,
        )

    assert target.read_text(encoding="utf-8") == old_content
    assert not list(output_dir.glob("*.tmp"))
    assert not list(output_dir.glob("*.bak"))


def test_exposure_exporter_writes_selected_fixed_names_as_one_sanitized_group(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"

    paths = export_exposure_documents(
        output_dir,
        {
            "pollen_grid_scores.json": {
                "dataset_type": "pollen_grid_scores",
                "API Key": "secret-value",
            },
            "noise_segments.json": {"dataset_type": "noise_segment_risk"},
            "route_environment.json": {"dataset_type": "route_environment"},
        },
        generated_at=GENERATED_AT,
    )

    assert set(paths) == {
        "pollen_grid_scores.json",
        "noise_segments.json",
        "route_environment.json",
    }
    assert {path.name for path in output_dir.iterdir()} == set(paths)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths.values())
    assert "secret-value" not in combined
    assert GENERATED_AT in combined


def test_exposure_exporter_rejects_unapproved_filename_before_writing(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    with pytest.raises(ValueError, match="输出文件名"):
        export_exposure_documents(
            output_dir,
            {"unexpected.json": {"status": "ok"}},
        )

    assert not output_dir.exists()
