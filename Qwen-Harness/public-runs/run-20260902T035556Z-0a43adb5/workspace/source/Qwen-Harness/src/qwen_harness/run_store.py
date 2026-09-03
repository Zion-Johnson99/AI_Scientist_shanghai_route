"""Run store: manages run directories, manifests, state, locks, and events.

All writes use atomic file replacement (temp file -> flush -> fsync -> os.replace)
to prevent corruption on interruption.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "RunStore",
    "RunManifest",
    "RunState",
    "RunLock",
    "LockConflictError",
    "atomic_write_json",
    "read_json_safe",
    "compute_file_sha256",
]

HARNESS_VERSION = "0.1.0"


class LockConflictError(Exception):
    """Raised when a lock is held by a live process."""

    def __init__(self, message: str, lock_data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.lock_data = lock_data


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically: temp file -> flush -> fsync -> os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json_safe(path: Path) -> dict[str, Any] | None:
    """Read a JSON file safely.

    Returns None for missing files, corrupted JSON, or empty files.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.strip():
        return None
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RunManifest:
    """Represents run_manifest.json content."""

    def __init__(
        self,
        run_id: str,
        created_at: str,
        repo_root: str,
        git_branch: str,
        git_head: str,
        worktree_clean: bool,
        harness_version: str,
        python_version: str,
        platform_info: str,
        model: str,
        temperature: float,
        seed: int,
        reasoning_effort: str,
        workflow_name: str,
        workflow_version: str,
        skills_hash: str,
        config_hash: str,
        data_hash: str,
        network_allowed: bool,
        write_allowed: bool,
    ) -> None:
        self.run_id = run_id
        self.created_at = created_at
        self.repo_root = repo_root
        self.git_branch = git_branch
        self.git_head = git_head
        self.worktree_clean = worktree_clean
        self.harness_version = harness_version
        self.python_version = python_version
        self.platform_info = platform_info
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self.reasoning_effort = reasoning_effort
        self.workflow_name = workflow_name
        self.workflow_version = workflow_version
        self.skills_hash = skills_hash
        self.config_hash = config_hash
        self.data_hash = data_hash
        self.network_allowed = network_allowed
        self.write_allowed = write_allowed

    @property
    def workflow(self) -> str:
        """Configured workflow name exposed by the manifest contract."""
        return self.workflow_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "repo_root": self.repo_root,
            "git_branch": self.git_branch,
            "git_head": self.git_head,
            "worktree_clean": self.worktree_clean,
            "harness_version": self.harness_version,
            "python_version": self.python_version,
            "platform": self.platform_info,
            "model": self.model,
            "temperature": self.temperature,
            "seed": self.seed,
            "reasoning_effort": self.reasoning_effort,
            "workflow_name": self.workflow_name,
            "workflow": self.workflow_name,
            "workflow_version": self.workflow_version,
            "skills_hash": self.skills_hash,
            "config_hash": self.config_hash,
            "data_hash": self.data_hash,
            "network_allowed": self.network_allowed,
            "write_allowed": self.write_allowed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunManifest":
        return cls(
            run_id=data["run_id"],
            created_at=data["created_at"],
            repo_root=data["repo_root"],
            git_branch=data["git_branch"],
            git_head=data["git_head"],
            worktree_clean=data["worktree_clean"],
            harness_version=data["harness_version"],
            python_version=data["python_version"],
            platform_info=data["platform"],
            model=data["model"],
            temperature=data["temperature"],
            seed=data["seed"],
            reasoning_effort=data["reasoning_effort"],
            workflow_name=data.get("workflow", data["workflow_name"]),
            workflow_version=data["workflow_version"],
            skills_hash=data["skills_hash"],
            config_hash=data["config_hash"],
            data_hash=data["data_hash"],
            network_allowed=data["network_allowed"],
            write_allowed=data["write_allowed"],
        )


class RunState:
    """Represents state.json content for a run."""

    def __init__(
        self,
        run_id: str,
        workflow: str,
        status: str = "initialized",
        current_stage: str | None = None,
        completed_stages: list[str] | None = None,
        failed_stages: dict[str, str] | None = None,
        retryable_stages: list[str] | None = None,
        started_at: str | None = None,
        updated_at: str | None = None,
        error: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.workflow = workflow
        self.status = status
        self.current_stage = current_stage
        self.completed_stages = completed_stages if completed_stages is not None else []
        self.failed_stages = failed_stages if failed_stages is not None else {}
        self.retryable_stages = retryable_stages if retryable_stages is not None else []
        self.started_at = started_at
        self.updated_at = updated_at
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow,
            "status": self.status,
            "current_stage": self.current_stage,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "retryable_stages": self.retryable_stages,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        return cls(
            run_id=data["run_id"],
            workflow=data["workflow"],
            status=data.get("status", "initialized"),
            current_stage=data.get("current_stage"),
            completed_stages=data.get("completed_stages", []),
            failed_stages=data.get("failed_stages", {}),
            retryable_stages=data.get("retryable_stages", []),
            started_at=data.get("started_at"),
            updated_at=data.get("updated_at"),
            error=data.get("error"),
        )


class RunLock:
    """Represents lock.json content."""

    def __init__(self, pid: int, acquired_at: str, run_id: str) -> None:
        self.pid = pid
        self.acquired_at = acquired_at
        self.run_id = run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "acquired_at": self.acquired_at,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunLock":
        return cls(
            pid=data["pid"],
            acquired_at=data["acquired_at"],
            run_id=data["run_id"],
        )


class RunStore:
    """Manages run directories under a base path."""

    def __init__(self, base_dir: Path, run_id: str | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.run_id = run_id
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def run_dir(self) -> Path:
        """Directory for the run bound to this store."""
        return self._run_dir(self._require_run_id())

    def _require_run_id(self, run_id: str | None = None) -> str:
        resolved = run_id or self.run_id
        if resolved is None:
            raise ValueError("run_id is required for an unbound RunStore")
        return resolved

    def _run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def create_run(
        self,
        goal: str,
        workflow: str,
        model: str = "qwen3.8-max",
        temperature: float = 0.2,
        seed: int = 1234,
        reasoning_effort: str = "medium",
    ) -> tuple[str, Path]:
        """Create a new run directory with manifest and initial state."""
        run_id = (
            f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest = self.create_manifest(
            run_id=run_id,
            goal=goal,
            workflow=workflow,
            model=model,
            temperature=temperature,
            seed=seed,
            reasoning_effort=reasoning_effort,
        )
        atomic_write_json(run_dir / "run_manifest.json", manifest.to_dict())

        state = self.init_state(run_id=run_id, workflow=workflow)
        atomic_write_json(run_dir / "state.json", state.to_dict())

        return run_id, run_dir

    def create_manifest(
        self,
        goal: str,
        workflow: str,
        model: str = "qwen3.8-max",
        temperature: float = 0.2,
        seed: int = 1234,
        reasoning_effort: str = "medium",
        run_id: str | None = None,
    ) -> RunManifest:
        """Create a RunManifest with the given parameters."""
        resolved_run_id = self._require_run_id(run_id)
        manifest = RunManifest(
            run_id=resolved_run_id,
            created_at=_now_iso(),
            repo_root=str(Path.cwd()),
            git_branch="unknown",
            git_head="unknown",
            worktree_clean=True,
            harness_version=HARNESS_VERSION,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform_info=platform.platform(),
            model=model,
            temperature=temperature,
            seed=seed,
            reasoning_effort=reasoning_effort,
            workflow_name=workflow,
            workflow_version="1.0",
            skills_hash="pending",
            config_hash="pending",
            data_hash="pending",
            network_allowed=False,
            write_allowed=True,
        )
        atomic_write_json(
            self._run_dir(resolved_run_id) / "run_manifest.json",
            manifest.to_dict(),
        )
        return manifest

    def init_state(self, workflow: str, run_id: str | None = None) -> RunState:
        """Initialize state for a new run."""
        resolved_run_id = self._require_run_id(run_id)
        now = _now_iso()
        state = RunState(
            run_id=resolved_run_id,
            workflow=workflow,
            status="running",
            current_stage=None,
            completed_stages=[],
            failed_stages={},
            retryable_stages=[],
            started_at=now,
            updated_at=now,
        )
        self.save_state(state, run_id=resolved_run_id)
        return state

    def load_state(self, run_id: str | None = None) -> RunState:
        """Load state.json for a run.

        Raises FileNotFoundError if state.json does not exist.
        Raises ValueError if state.json is corrupted or invalid.
        """
        resolved_run_id = self._require_run_id(run_id)
        state_path = self._run_dir(resolved_run_id) / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"state.json not found for run {resolved_run_id}: {state_path}")
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"Cannot read state.json for run {resolved_run_id}: {exc}") from exc
        if not content.strip():
            raise ValueError(f"state.json is empty for run {resolved_run_id}")
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"state.json is corrupted for run {resolved_run_id}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"state.json is not a JSON object for run {resolved_run_id}")
        if "run_id" not in data or "workflow" not in data:
            raise ValueError(f"state.json missing required fields for run {resolved_run_id}")
        return RunState.from_dict(data)

    def save_state(self, state: RunState, run_id: str | None = None) -> None:
        """Persist state atomically."""
        resolved_run_id = self._require_run_id(run_id)
        state.updated_at = _now_iso()
        atomic_write_json(self._run_dir(resolved_run_id) / "state.json", state.to_dict())

    def advance_stage(self, current_stage: str, next_stage: str) -> RunState:
        """Advance the run to the next stage.

        Marks the current stage as completed (if any) and sets current_stage to next_stage.
        """
        state = self.load_state()
        if current_stage not in state.completed_stages:
            state.completed_stages.append(current_stage)
        state.current_stage = next_stage
        state.status = "running"
        self.save_state(state)
        return state

    def mark_stage_completed(self, stage: str) -> RunState:
        """Mark a stage as completed."""
        state = self.load_state()
        if stage not in state.completed_stages:
            state.completed_stages.append(stage)
        if state.current_stage == stage:
            state.current_stage = None
        state.updated_at = _now_iso()
        self.save_state(state)
        return state

    def mark_stage_failed(self, stage: str, error: str) -> RunState:
        """Mark a stage as failed with an error message."""
        state = self.load_state()
        state.failed_stages[stage] = error
        state.current_stage = stage
        state.status = "failed"
        state.error = error
        state.updated_at = _now_iso()
        self.save_state(state)
        return state

    def mark_stage_retryable(self, stage: str) -> RunState:
        """Mark a stage as retryable."""
        state = self.load_state()
        if stage not in state.retryable_stages:
            state.retryable_stages.append(stage)
        if stage in state.failed_stages:
            del state.failed_stages[stage]
        state.status = "retryable"
        state.updated_at = _now_iso()
        self.save_state(state)
        return state

    def mark_completed(self) -> RunState:
        """Mark the entire run as completed."""
        state = self.load_state()
        if state.current_stage is not None:
            if state.current_stage not in state.completed_stages:
                state.completed_stages.append(state.current_stage)
            state.current_stage = None
        state.status = "completed"
        state.updated_at = _now_iso()
        self.save_state(state)
        return state

    def recover(self) -> RunState:
        """Recover a run: load state and convert failed to retryable.

        Raises FileNotFoundError if state.json is missing.
        Raises ValueError if state.json is corrupted.
        """
        state = self.load_state()
        if state.status == "failed":
            for stage in list(state.failed_stages.keys()):
                if stage not in state.retryable_stages:
                    state.retryable_stages.append(stage)
            state.failed_stages = {}
            state.status = "retryable"
            self.save_state(state)
        return state

    def acquire_lock(self) -> RunLock:
        """Acquire a lock for the run.

        Raises LockConflictError if a live process holds the lock.
        If the lock holder pid is dead, the lock is reclaimed.
        """
        run_id = self._require_run_id()
        lock_path = self._run_dir(run_id) / "lock.json"
        lock = RunLock(
            pid=os.getpid(),
            acquired_at=_now_iso(),
            run_id=run_id,
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                fd = os.open(
                    lock_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                )
            except FileExistsError:
                existing = read_json_safe(lock_path)
                if existing is not None:
                    pid = int(existing.get("pid", 0))
                    if _pid_alive(pid):
                        raise LockConflictError(
                            f"Run {run_id} is locked by live process {pid}",
                            lock_data=existing,
                        )
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(lock.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            return lock

    def release_lock(self) -> None:
        """Release the lock for a run."""
        lock_path = self.run_dir / "lock.json"
        if lock_path.exists():
            lock_path.unlink()

    def append_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Append an event to events.jsonl."""
        events_path = self.run_dir / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_type": event_type,
            "data": data,
            "timestamp": _now_iso(),
        }
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def list_runs(self, limit: int = 10) -> list[str]:
        """List run IDs sorted by creation time (newest first)."""
        if not self.base_dir.exists():
            return []
        runs = []
        for entry in self.base_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("run-"):
                runs.append(entry.name)
        runs.sort(reverse=True)
        return runs[:limit]
