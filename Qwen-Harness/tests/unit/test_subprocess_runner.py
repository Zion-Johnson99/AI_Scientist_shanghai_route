from __future__ import annotations

from pathlib import Path

from qwen_harness.subprocess_runner import CommandSpec, SafeSubprocessRunner


def test_python_command_stdout_is_always_utf8(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    runtime_root = repo_root / "runtime"
    repo_root.mkdir()
    runtime_root.mkdir()
    runner = SafeSubprocessRunner(repo_root, runtime_root)

    audit = runner.run(
        CommandSpec(
            command_id="utf8-json",
            argv=["python", "-c", 'print(\'{"名称": "徐汇滨江"}\')'],
            cwd=repo_root,
        )
    )

    assert Path(audit.stdout_path).read_text(encoding="utf-8").strip() == ('{"名称": "徐汇滨江"}')
