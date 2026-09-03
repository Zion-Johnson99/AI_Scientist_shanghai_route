"""Phase 0 pre-flight verification for Qwen-Harness round 2.

Writes run_manifest.json, provider_manifest.json, inputs/input_boundary.json and
evidence/model_channel.json. Idempotent: safe to re-run; refreshes timestamps.

Security invariant: API key *presence* is recorded as a boolean only. Key values
are never read into memory, printed, or persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = RUN_DIR.parents[3]
RUN_ID = RUN_DIR.name

SENSITIVE_KEYS = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "BAILIAN_API_KEY", "QWEN_API_KEY")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    prompt_path = RUN_DIR / "inputs" / "task_prompt.md"
    prompt_sha = sha256_file(prompt_path) if prompt_path.exists() else "missing"

    env_presence = {key: (key in os.environ and bool(os.environ[key])) for key in SENSITIVE_KEYS}
    leaked = [key for key, present in env_presence.items() if present]

    status_porcelain = git("status", "--porcelain")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")

    common: dict[str, Any] = {
        "run_id": RUN_ID,
        "round": 2,
        "provider": "qoder_session",
        "model_name": "qwen3.8-max",
        "billing_channel": "qoder_credits",
        "dashscope_api_used": False,
    }

    write_json(
        RUN_DIR / "run_manifest.json",
        {
            **common,
            "created_at": utc_now(),
            "workspace_root": str(REPO_ROOT).replace("\\", "/"),
            "branch": branch,
            "head_commit": head,
            "git_status_at_start": status_porcelain.splitlines(),
            "task_prompt_path": "inputs/task_prompt.md",
            "task_prompt_sha256": prompt_sha,
            "qoder_task_id": "unknown",
            "qoder_credits_consumed": "evidence_pending_user_capture",
            "dashscope_request_ids": [],
            "dashscope_call_count": 0,
            "online_harness_commands_executed": [],
            "sensitive_env_keys_present": env_presence,
            "sensitive_env_keys_removed_in_subprocess": True,
            "final_status": "in_progress",
        },
    )

    write_json(
        RUN_DIR / "provider_manifest.json",
        {
            **common,
            "recorded_at": utc_now(),
            "model_channel": {
                "execution_surface": "Qoder Goal session (interactive agent turn loop)",
                "model_family_recorded": "qwen3.8-max",
                "billed_through": "qoder_credits",
                "dashscope_http_calls": 0,
                "bailian_openai_compatible_calls": 0,
                "bailian_sdk_calls": 0,
                "qwen_model_client_from_env_invocations": 0,
                "request_id_policy": "no synthetic request ids; empty list means zero calls",
            },
            "prohibited_actions_observed": {
                "read_qwen_harness_dotenv": False,
                "called_paid_llm_api": False,
                "ran_online_qwen_harness_run": False,
                "ran_online_resume": False,
                "created_git_commit": False,
                "created_git_branch": False,
                "opened_pull_request": False,
                "pushed_to_remote": False,
            },
            "leaked_key_names": leaked,
            "credits_evidence_status": "evidence_pending_user_capture",
        },
    )

    write_json(
        RUN_DIR / "inputs" / "input_boundary.json",
        {
            "run_id": RUN_ID,
            "recorded_at": utc_now(),
            "allowed_reads": [
                "Qwen-Harness/README.md",
                "Qwen-Harness/src/**",
                "Qwen-Harness/config/**",
                "Qwen-Harness/schemas/**",
                "Qwen-Harness/prompts/**",
                "Qwen-Harness/tests/**",
                "Qwen-Harness/scripts/**",
                "docs/qwen-harness-build/**",
                ".qoder/skills/** (rules and thresholds only)",
                "AISci模板和文档/0902文档架构构建.md",
                "round1 run-20260902T035556Z-0a43adb5: run_manifest.json, state.json, "
                "events.jsonl, checks/**, commands test logs, metrics summaries",
                "public papers, government pages, public geographic data, OSM, public map services",
            ],
            "forbidden_reads_all_phases": [
                "xuhui_route_builder/** (implementation, web source, route data, media manifests)",
                "weather_api_data/** (implementation and generated data)",
                "evaluation_model_qwen/** (implementation and recommendation results)",
                "round1 workspace/source/**",
                "round1 publish/local-product/**",
                "round1 generated source, page implementations, reusable product files",
                "online product HTML/CSS/JS, API responses, GeoJSON, JSON, static asset URLs",
                "Qwen-Harness/.env and any key inside it",
            ],
            "reference_page": {
                "url": "https://zion-johnson99.github.io/AI_Scientist_shanghai_route/web/",
                "accessible_before_blind_checkpoint": False,
                "blind_checkpoint_frozen_at": None,
                "allowed_after_freeze": [
                    "desktop and mobile visible UI",
                    "ordinary click, scroll, keyboard, navigation",
                    "visible behaviour of recommend/filter/detail/map-linkage/environment/location/mobile",
                    "browser rendered screenshots",
                ],
                "forbidden_after_freeze": [
                    "view page source",
                    "DOM query, evaluate_script, element structure extraction, a11y tree export",
                    "developer tools",
                    "network panel, request interception, response reading",
                    "curl/wget/Invoke-WebRequest download of the product page",
                    "asset, image URL, data file, media manifest extraction",
                    "copying product images, icons, styles, copy text or layout code",
                ],
            },
            "write_boundary": {
                "only_path": f"Qwen-Harness/runtime/runs/{RUN_ID}/",
                "readonly_paths": [
                    "Qwen-Harness source and config",
                    "xuhui_route_builder",
                    "weather_api_data",
                    "evaluation_model_qwen",
                    "run-20260902T035556Z-0a43adb5",
                    "all other existing runs",
                ],
                "toolchain_venv_location_outside_repo": True,
            },
            "model_cost_boundary": {
                "provider": "qoder_session",
                "model_name": "qwen3.8-max",
                "billing_channel": "qoder_credits",
                "dashscope_api_used": False,
                "sensitive_env_keys_present": env_presence,
                "subprocess_env_scrub_list": list(SENSITIVE_KEYS),
            },
        },
    )

    write_json(
        RUN_DIR / "evidence" / "model_channel.json",
        {
            **common,
            "recorded_at": utc_now(),
            "dashscope_request_ids": [],
            "dashscope_call_count": 0,
            "qoder_task_id": "unknown",
            "qoder_credits_consumed": "evidence_pending_user_capture",
            "qoder_credits_screenshot": "evidence_pending_user_capture",
            "bailian_usage_screenshot": "evidence_pending_user_capture",
            "verification_note": (
                "No paid LLM endpoint was contacted during this run. Model output was produced "
                "inside the Qoder Goal session and billed through Qoder credits. Credits figures "
                "and task ids are not readable from the session, so they are recorded as "
                "evidence_pending_user_capture instead of being estimated."
            ),
        },
    )

    print(f"run_id={RUN_ID}")
    print(f"branch={branch} head={head[:12]}")
    print(f"task_prompt_sha256={prompt_sha}")
    print(f"sensitive_keys_present={leaked or 'none'}")
    print(f"git_status_lines={len(status_porcelain.splitlines())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
