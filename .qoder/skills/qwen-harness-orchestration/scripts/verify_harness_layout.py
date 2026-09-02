#!/usr/bin/env python3
"""Deterministic layout check for Qwen-Harness (stdlib only, no network).

Checks per docs/qwen-harness-build/02 §4.5:
  1. Required directories and files exist.
  2. pyproject.toml declares the qwen-harness console script.
  3. Workflow configs parse; stage handlers present; referenced skill names
     exist under .qoder/skills/.
  4. .env.example contains no secret values.
  5. runtime/ is excluded by Qwen-Harness/.gitignore.

Usage: python verify_harness_layout.py [--repo-root PATH]
Exit codes: 0 PASS, 1 FAIL, 2 usage/setup error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_PATHS = [
    "README.md",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "config/harness.json",
    "config/source_policy.json",
    "config/experiment_variants.json",
    "config/quality_gates.json",
    "config/workflows/full-research.json",
    "config/workflows/research-only.json",
    "config/workflows/reproduce-existing.json",
    "examples/goals/multisource-route.json",
    "src/qwen_harness/__init__.py",
    "src/qwen_harness/cli.py",
    "src/qwen_harness/config.py",
    "src/qwen_harness/paths.py",
    "src/qwen_harness/models.py",
    "src/qwen_harness/run_store.py",
    "src/qwen_harness/subprocess_runner.py",
    "src/qwen_harness/skills.py",
    "src/qwen_harness/llm/client.py",
    "src/qwen_harness/workflow/engine.py",
    "src/qwen_harness/workflow/resume.py",
    "src/qwen_harness/adapters/route_builder.py",
    "src/qwen_harness/adapters/environment_data.py",
    "src/qwen_harness/adapters/evaluation_model.py",
    "src/qwen_harness/adapters/web_product.py",
    "tests",
    "runtime",
]

CORE_SKILLS = {
    "qwen-harness-orchestration",
    "scientific-evidence-hypothesis",
    "xuhui-route-builder-engineering",
    "weather-environment-pipeline",
    "evaluation-qwen-experiments",
    "web-product-integration",
}

SECRET_LINE = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})")


def fail(problems: list[str], message: str) -> None:
    problems.append(message)


def check_paths(harness: Path, problems: list[str]) -> None:
    for rel in REQUIRED_PATHS:
        path = harness / rel
        if not path.exists():
            fail(problems, f"missing required path: Qwen-Harness/{rel}")


def check_console_script(harness: Path, problems: list[str]) -> None:
    pyproject = harness / "pyproject.toml"
    if not pyproject.exists():
        fail(problems, "missing Qwen-Harness/pyproject.toml")
        return
    text = pyproject.read_text(encoding="utf-8")
    try:
        import tomllib

        data = tomllib.loads(text)
        scripts = data.get("project", {}).get("scripts", {})
        if scripts.get("qwen-harness") != "qwen_harness.cli:main":
            fail(
                problems,
                "pyproject.toml must declare qwen-harness = \"qwen_harness.cli:main\"",
            )
    except ModuleNotFoundError:
        if not re.search(
            r'^\s*qwen-harness\s*=\s*"qwen_harness\.cli:main"\s*$', text, re.MULTILINE
        ):
            fail(problems, "pyproject.toml lacks the qwen-harness console script")


def check_workflows(harness: Path, skills_root: Path, problems: list[str]) -> None:
    workflows = harness / "config" / "workflows"
    if not workflows.is_dir():
        fail(problems, "missing Qwen-Harness/config/workflows/")
        return
    for path in sorted(workflows.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(problems, f"{path.name}: invalid JSON ({exc})")
            continue
        stages = data.get("stages", [])
        if not isinstance(stages, list) or not stages:
            fail(problems, f"{path.name}: 'stages' must be a non-empty list")
            continue
        names = set()
        for stage in stages:
            if not isinstance(stage, dict):
                fail(problems, f"{path.name}: stage entry must be an object")
                continue
            name = stage.get("name")
            handler = stage.get("handler")
            if not name or not handler:
                fail(problems, f"{path.name}: stage missing 'name' or 'handler'")
            elif name in names:
                fail(problems, f"{path.name}: duplicate stage '{name}'")
            names.add(name)
            for skill in stage.get("required_skills", []) or []:
                skill_dir = skills_root / skill
                if not (skill_dir / "SKILL.md").is_file():
                    fail(
                        problems,
                        f"{path.name}: stage '{name}' references missing skill '{skill}'",
                    )
        used = set()
        for stage in stages:
            if isinstance(stage, dict):
                used.update(stage.get("required_skills", []) or [])
        if not used & CORE_SKILLS:
            fail(problems, f"{path.name}: references none of the six core project skills")


def check_env_example(harness: Path, problems: list[str]) -> None:
    env_file = harness / ".env.example"
    if not env_file.exists():
        fail(problems, "missing Qwen-Harness/.env.example")
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if SECRET_LINE.search(line):
            fail(problems, f".env.example contains a secret-looking value: {line[:40]}...")
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip()
            if key.strip().upper().endswith(("KEY", "TOKEN", "SECRET", "PASSWORD")) and value:
                fail(problems, f".env.example credential '{key.strip()}' must stay empty")


def check_gitignore(harness: Path, problems: list[str]) -> None:
    gitignore = harness / ".gitignore"
    if not gitignore.exists():
        fail(problems, "missing Qwen-Harness/.gitignore")
        return
    lines = [
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    runtime_patterns = {"runtime", "runtime/", "runtime/*", "runtime/**"}
    if not any(pattern.lstrip("/") in runtime_patterns for pattern in lines):
        fail(problems, ".gitignore must exclude runtime/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Qwen-Harness layout")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args()

    repo_root = args.repo_root or Path(__file__).resolve().parents[4]
    harness = repo_root / "Qwen-Harness"
    skills_root = repo_root / ".qoder" / "skills"
    if not harness.is_dir():
        print("FAIL: Qwen-Harness/ directory not found")
        return 1

    problems: list[str] = []
    check_paths(harness, problems)
    check_console_script(harness, problems)
    check_workflows(harness, skills_root, problems)
    check_env_example(harness, problems)
    check_gitignore(harness, problems)

    if problems:
        for item in problems:
            print(f"FAIL: {item}")
        print(f"RESULT: FAIL ({len(problems)} problem(s))")
        return 1
    print("PASS: Qwen-Harness layout, console script, workflow skills, .env.example and .gitignore checks all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
