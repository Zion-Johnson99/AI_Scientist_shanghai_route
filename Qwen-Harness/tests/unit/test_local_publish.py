from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from qwen_harness.reporting import full_run_report, local_publish


def _write_generated_run(run_dir: Path) -> None:
    source = run_dir / "workspace" / "source"
    for module in local_publish.REQUIRED_SOURCE_MODULES:
        module_root = source / module
        module_root.mkdir(parents=True)
        (module_root / "pyproject.toml").write_text(f"# generated {module}\n", encoding="utf-8")

    route_root = source / "xuhui_route_builder"
    (route_root / "web").mkdir()
    (route_root / "web" / "index.html").write_text("generated web\n", encoding="utf-8")
    (route_root / "data" / "web").mkdir(parents=True)
    (route_root / "data" / "web" / "route_catalog.json").write_text("{}\n", encoding="utf-8")

    reports = run_dir / "reports"
    reports.mkdir()
    for source_name in local_publish.REPORT_PUBLISH_NAMES:
        (reports / source_name).write_text(f"generated {source_name}\n", encoding="utf-8")

    checks = run_dir / "checks"
    checks.mkdir()
    (checks / "pytest.txt").write_text("passed\n", encoding="utf-8")


def test_local_launcher_starts_generated_recommendation_api_and_static_web() -> None:
    assert "source\\evaluation_model_qwen" in local_publish.LAUNCH_SCRIPT
    assert "uvicorn" in local_publish.LAUNCH_SCRIPT
    assert "evaluation_model_qwen.api:app" in local_publish.LAUNCH_SCRIPT
    assert "evaluation-model-qwen-api" not in local_publish.LAUNCH_SCRIPT
    assert "8124/api/v1/health" in local_publish.LAUNCH_SCRIPT
    assert "缺少 pyproject.toml" in local_publish.LAUNCH_SCRIPT
    assert "健康检查未就绪" in local_publish.LAUNCH_SCRIPT
    assert "Write-Warning" in local_publish.LAUNCH_SCRIPT
    assert "网页继续以无推荐服务模式启动" in local_publish.LAUNCH_SCRIPT
    assert "Get-NetTCPConnection" in local_publish.LAUNCH_SCRIPT
    assert "$apiServiceProcessId" in local_publish.LAUNCH_SCRIPT
    assert "http.server 8130" in local_publish.LAUNCH_SCRIPT


def test_build_local_publish_uses_only_generated_workspace(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runtime" / "runs" / "run-test"
    run_dir.mkdir(parents=True)
    _write_generated_run(run_dir)

    repo_root = tmp_path / "repository"
    for module in local_publish.REQUIRED_SOURCE_MODULES:
        module_root = repo_root / module
        module_root.mkdir(parents=True)
        (module_root / "repository-only.txt").write_text("must not publish\n", encoding="utf-8")

    staged_payload = {"schema_version": "1.0", "run_id": "run-test"}
    initial_publish = run_dir / "publish"
    initial_publish.mkdir()
    (initial_publish / local_publish.WEB_PAYLOAD_NAME).write_text(
        json.dumps(staged_payload, ensure_ascii=False), encoding="utf-8"
    )

    context = SimpleNamespace(run_dir=run_dir, run_id="run-test", repo_root=repo_root)
    monkeypatch.setattr(local_publish, "_prepare_full_report", lambda _context: None)

    result = local_publish.build_local_publish(cast(Any, context))

    publish = run_dir / "publish"
    assert {path.name for path in publish.iterdir()} == {
        "checks",
        "launch-local.ps1",
        "local-product",
        "reports",
        "source",
        "source_manifest.json",
    }
    assert {path.name for path in (publish / "source").iterdir()} == set(
        local_publish.REQUIRED_SOURCE_MODULES
    )
    assert result["source_file_counts"]["Qwen-Harness"] == 1
    assert (publish / "source" / "Qwen-Harness" / "pyproject.toml").is_file()
    assert not list((publish / "source").rglob("repository-only.txt"))
    assert (publish / "local-product" / "web" / "index.html").read_text(
        encoding="utf-8"
    ) == "generated web\n"
    assert (publish / "local-product" / "data" / "web" / "route_catalog.json").is_file()
    published_payload = publish / "local-product" / "data" / "web" / local_publish.WEB_PAYLOAD_NAME
    assert json.loads(published_payload.read_text(encoding="utf-8")) == staged_payload
    assert not (publish / local_publish.WEB_PAYLOAD_NAME).exists()
    assert {path.name for path in (publish / "reports").iterdir()} == set(
        local_publish.REPORT_PUBLISH_NAMES.values()
    )
    assert (publish / "checks" / "pytest.txt").read_text(encoding="utf-8") == "passed\n"
    launcher = (publish / "launch-local.ps1").read_text(encoding="utf-8-sig")
    assert "uvicorn" in launcher
    assert "evaluation-model-qwen-api" not in launcher
    assert "网页继续以无推荐服务模式启动" in launcher
    manifest = json.loads((publish / "source_manifest.json").read_text(encoding="utf-8"))
    assert any(item["path"] == "reports/完整运行报告.md" for item in manifest["files"])
    assert any(
        item["path"] == "local-product/data/web/research_harness_latest.json"
        for item in manifest["files"]
    )


def test_build_local_publish_rejects_invalid_staged_web_payload_before_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_generated_run(run_dir)
    publish = run_dir / "publish"
    publish.mkdir()
    payload = publish / "research_harness_latest.json"
    payload.write_text("{invalid", encoding="utf-8")
    context = SimpleNamespace(run_dir=run_dir, run_id="run-test")
    monkeypatch.setattr(local_publish, "_prepare_full_report", lambda _context: None)

    with pytest.raises(ValueError, match="web_payload JSON 无效"):
        local_publish.build_local_publish(cast(Any, context))

    assert payload.read_text(encoding="utf-8") == "{invalid"


def test_build_local_publish_fails_before_replacing_publish_when_generated_source_missing(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_generated_run(run_dir)
    missing_module = run_dir / "workspace" / "source" / "weather_api_data"
    for path in missing_module.iterdir():
        path.unlink()
    missing_module.rmdir()
    publish = run_dir / "publish"
    publish.mkdir()
    marker = publish / "existing.txt"
    marker.write_text("keep on validation failure\n", encoding="utf-8")
    context = SimpleNamespace(run_dir=run_dir, run_id="run-test")
    monkeypatch.setattr(local_publish, "_prepare_full_report", lambda _context: None)

    with pytest.raises(FileNotFoundError, match="weather_api_data"):
        local_publish.build_local_publish(cast(Any, context))

    assert marker.is_file()


@pytest.mark.parametrize(
    ("relative_path", "message"),
    (
        (Path("workspace/source/xuhui_route_builder/web/index.html"), "网页入口"),
        (Path("reports/experiment_report.md"), "实验报告"),
    ),
)
def test_build_local_publish_rejects_missing_generated_web_or_report(
    tmp_path: Path,
    monkeypatch,
    relative_path: Path,
    message: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_generated_run(run_dir)
    (run_dir / relative_path).unlink()
    context = SimpleNamespace(run_dir=run_dir, run_id="run-test")
    monkeypatch.setattr(local_publish, "_prepare_full_report", lambda _context: None)

    with pytest.raises(FileNotFoundError, match=message):
        local_publish.build_local_publish(cast(Any, context))


def test_full_report_module_rows_use_only_generated_workspace(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    source_root = run_dir / "workspace" / "source"
    for module in local_publish.REQUIRED_SOURCE_MODULES:
        module_root = source_root / module
        module_root.mkdir(parents=True)
        (module_root / f"generated-{module}.py").write_text("generated = True\n", encoding="utf-8")

    def read_stage_output(stage: str) -> dict[str, object]:
        if stage == "module_preflight":
            return {
                "preflight_statuses": {
                    "route": "passed",
                    "environment": "passed",
                    "evaluation": "passed",
                }
            }
        if stage == "module_execution":
            return {
                "executed_operations": [
                    "route:generated",
                    "environment:generated",
                    "evaluation:generated",
                ]
            }
        return {}

    context = SimpleNamespace(
        run_dir=run_dir,
        state=SimpleNamespace(stage_statuses={"module_execution": "passed"}),
        read_stage_output=read_stage_output,
    )

    rows = "\n".join(full_run_report._module_rows(cast(Any, context)))

    assert "Harness 编排" in rows
    assert "Qwen-Harness" in rows
    assert "generated-Qwen-Harness.py" in rows
    assert "xuhui_route_builder" in rows
    assert "weather_api_data" in rows
    assert "evaluation_model_qwen" in rows


def test_refresh_local_publish_metadata_copies_chinese_final_report_and_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    reports = run_dir / "reports"
    publish = run_dir / "publish"
    reports.mkdir(parents=True)
    for source_name in local_publish.REPORT_PUBLISH_NAMES:
        (reports / source_name).write_text(f"running {source_name}\n", encoding="utf-8")
    (publish / "reports").mkdir(parents=True)
    (publish / "reports" / "完整运行报告.md").write_text("running\n", encoding="utf-8")
    (publish / "source" / "Qwen-Harness").mkdir(parents=True)
    (publish / "source" / "Qwen-Harness" / "README.md").write_text("source\n", encoding="utf-8")
    (publish / "source_manifest.json").write_text(
        json.dumps({"source_file_counts": {"Qwen-Harness": 1}}), encoding="utf-8"
    )
    context = SimpleNamespace(run_dir=run_dir)

    def write_final_report(_context: object) -> None:
        (reports / "full_run_report.md").write_text("passed\n", encoding="utf-8")

    monkeypatch.setattr(local_publish, "_prepare_full_report", write_final_report)

    local_publish.refresh_local_publish_metadata(cast(Any, context))

    assert (publish / "reports" / "完整运行报告.md").read_text(encoding="utf-8") == "passed\n"
    manifest = json.loads((publish / "source_manifest.json").read_text(encoding="utf-8"))
    report = next(item for item in manifest["files"] if item["path"] == "reports/完整运行报告.md")
    assert report["sha256"] == local_publish._sha256(publish / "reports" / "完整运行报告.md")
    assert manifest["source_file_counts"] == {"Qwen-Harness": 1}
