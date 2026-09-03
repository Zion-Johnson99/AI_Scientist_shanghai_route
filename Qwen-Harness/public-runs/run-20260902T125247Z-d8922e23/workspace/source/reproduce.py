"""Single reproduction entry point for the generated workspace.

Guarantees no paid-LLM credential reaches any child process.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SOURCE_ROOT: Path = Path(__file__).resolve().parent
SCRIPT: Path = SOURCE_ROOT / "scripts" / "generate_all.py"
FORBIDDEN_ENV_KEYS: tuple[str, ...] = ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "BAILIAN_API_KEY")
STAGES: tuple[str, ...] = ("all", "routes", "environment", "evaluation", "web", "checks")


def clean_environment() -> dict[str, str]:
    """Return the process environment with every LLM credential removed."""
    return {key: value for key, value in os.environ.items() if key not in FORBIDDEN_ENV_KEYS}


def credentials_present() -> dict[str, bool]:
    """Report presence only, never values."""
    return {key: key in os.environ for key in FORBIDDEN_ENV_KEYS}


def main() -> int:
    """Dispatch to the stage runner with a scrubbed environment."""
    parser = argparse.ArgumentParser(description="Reproduce the round-2 build.")
    parser.add_argument("--stage", default="all", choices=STAGES)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    presence = credentials_present()
    sys.stdout.write(f"[reproduce] scrubbed_keys={sorted(k for k, v in presence.items() if v)}\n")
    sys.stdout.write("[reproduce] provider=qoder_session model=qwen3.8-max online_llm=false\n")
    sys.stdout.flush()
    generated_at = args.generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    command = [sys.executable, str(SCRIPT), "--stage", args.stage, "--generated-at", generated_at]
    completed = subprocess.run(command, cwd=str(SOURCE_ROOT), env=clean_environment(), check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
