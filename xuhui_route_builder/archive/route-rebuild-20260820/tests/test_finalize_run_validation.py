import importlib.util
from pathlib import Path

import pytest


def _load_tool():
    tool_path = Path(__file__).resolve().parents[1] / "tools/finalize_run_validation.py"
    spec = importlib.util.spec_from_file_location("finalize_run_validation", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_ids() -> list[str]:
    return [f"XH_RUN_{index:04d}" for index in range(31, 61)]


def test_visual_manifest_requires_all_thirty_routes_to_pass() -> None:
    tool = _load_tool()
    manifest = {
        "routes": [
            {"route_id": route_id, "status": "pass", "image_path": f"{route_id}.png"}
            for route_id in _run_ids()
        ]
    }

    tool.assert_visual_manifest(manifest, set(_run_ids()))

    manifest["routes"][-1]["status"] = "needs_review"
    with pytest.raises(RuntimeError, match="visual audit incomplete"):
        tool.assert_visual_manifest(manifest, set(_run_ids()))


def test_quality_gate_requires_exactly_thirty_passing_run_routes() -> None:
    tool = _load_tool()
    report = {
        "results": [{"route_id": route_id, "status": "pass"} for route_id in _run_ids()]
    }

    tool.assert_run_gate(report, set(_run_ids()))

    report["results"][0]["status"] = "fail"
    with pytest.raises(RuntimeError, match="run gate incomplete"):
        tool.assert_run_gate(report, set(_run_ids()))
