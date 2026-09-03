"""Tests for the offline harness run copy and its manifest."""

from __future__ import annotations

import json
from pathlib import Path

COPY_ROOT = Path(__file__).resolve().parents[1]
#: <run>/workspace/source/Qwen-Harness, so the run directory is three levels up.
RUN_ROOT = COPY_ROOT.parents[2]


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert isinstance(payload, dict)
    return payload


def test_run_copy_manifest_present() -> None:
    manifest = read_json(COPY_ROOT / "run_copy_manifest.json")
    assert manifest["source_run_id"] == RUN_ROOT.name
    assert manifest["offline"] is True
    assert manifest["dashscope_api_used"] is False
    assert manifest["provider"] == "qoder_session"
    assert manifest["model_name"] == "qwen3.8-max"
    assert manifest["billing_channel"] == "qoder_credits"
    assert isinstance(manifest["copied_files"], list)


def test_copied_files_exist_and_hash_matches() -> None:
    manifest = read_json(COPY_ROOT / "run_copy_manifest.json")
    for entry in manifest["copied_files"]:
        target = COPY_ROOT / entry["relative_path"]
        assert target.is_file(), entry["relative_path"]
        assert target.stat().st_size == entry["bytes"]
        digest = __import__("hashlib").sha256(target.read_bytes()).hexdigest()
        assert digest == entry["sha256"], entry["relative_path"]


def test_reproduce_entry_declares_no_network() -> None:
    text = (COPY_ROOT / "reproduce_harness.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "QwenModelClient" not in text
    assert "from_env" not in text
    #: The entry is required to record ``dashscope_api_used`` in its manifest, so the
    #: bare word has to be allowed. What may not appear is an SDK import or a
    #: module-qualified call, which is what would actually reach a paid endpoint.
    assert "import dashscope" not in lowered
    assert "dashscope." not in lowered


def test_run_manifest_provider_channel() -> None:
    manifest = read_json(RUN_ROOT / "run_manifest.json")
    assert manifest["provider"] == "qoder_session"
    assert manifest["model_name"] == "qwen3.8-max"
    assert manifest["dashscope_api_used"] is False
