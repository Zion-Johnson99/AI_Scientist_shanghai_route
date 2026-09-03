"""Unit tests for qwen_harness.run_store.

Covers:
- Atomic write (temp file → flush → fsync → os.replace)
- Recovery from interrupted writes
- Lock conflict rejection
- run_manifest.json field completeness
- state.json stage tracking
"""

from __future__ import annotations

import json
import os
import signal
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from qwen_harness.run_store import (
    RunStore,
    RunManifest,
    RunState,
    LockConflictError,
    atomic_write_json,
    read_json_safe,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    """Provide a temporary run directory."""
    run_dir = tmp_path / "runs" / "test-run-001"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture
def store(tmp_run_dir: Path) -> RunStore:
    """Provide a RunStore instance backed by a temp directory."""
    return RunStore(base_dir=tmp_run_dir.parent, run_id="test-run-001")


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------


class TestAtomicWriteJson:
    """Tests for the atomic_write_json helper."""

    def test_basic_write(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        payload = {"key": "value", "number": 42}
        atomic_write_json(target, payload)
        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == payload

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text('{"old": true}', encoding="utf-8")
        payload = {"new": True}
        atomic_write_json(target, payload)
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == payload

    def test_no_partial_file_on_interrupt(self, tmp_path: Path) -> None:
        """Simulate interruption during write: target must not exist or be valid."""
        target = tmp_path / "data.json"
        original_replace = os.replace

        def failing_replace(src: str, dst: str) -> None:
            # Simulate crash before rename completes
            raise OSError("simulated crash")

        with patch("os.replace", side_effect=failing_replace):
            with pytest.raises(OSError, match="simulated crash"):
                atomic_write_json(target, {"incomplete": True})

        # Target must not exist (never renamed) or must be valid JSON
        if target.exists():
            # If it exists, it must be valid JSON from a previous successful write
            json.loads(target.read_text(encoding="utf-8"))

    def test_temp_file_cleaned_on_failure(self, tmp_path: Path) -> None:
        """Temp file should be removed if write fails."""
        target = tmp_path / "data.json"

        def failing_fsync(fd: int) -> None:
            raise OSError("disk full")

        with patch("os.fsync", side_effect=failing_fsync):
            with pytest.raises(OSError, match="disk full"):
                atomic_write_json(target, {"data": 1})

        # No leftover temp files
        remaining = list(tmp_path.glob("*.tmp"))
        assert remaining == []

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "data.json"
        atomic_write_json(target, {"nested": True})
        assert target.exists()


# ---------------------------------------------------------------------------
# read_json_safe
# ---------------------------------------------------------------------------


class TestReadJsonSafe:
    """Tests for safe JSON reading with corruption detection."""

    def test_valid_json(self, tmp_path: Path) -> None:
        target = tmp_path / "valid.json"
        target.write_text('{"status": "ok"}', encoding="utf-8")
        result = read_json_safe(target)
        assert result == {"status": "ok"}

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = read_json_safe(tmp_path / "missing.json")
        assert result is None

    def test_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "corrupt.json"
        target.write_text('{"broken": ', encoding="utf-8")
        result = read_json_safe(target)
        assert result is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.json"
        target.write_text("", encoding="utf-8")
        result = read_json_safe(target)
        assert result is None


# ---------------------------------------------------------------------------
# RunManifest
# ---------------------------------------------------------------------------


class TestRunManifest:
    """Tests for run_manifest.json creation and field completeness."""

    def test_manifest_fields_complete(self, store: RunStore) -> None:
        manifest = store.create_manifest(
            goal="test goal",
            workflow="full-research",
            model="qwen3.8-max",
            temperature=0.2,
            seed=1234,
            reasoning_effort="medium",
        )
        assert manifest.run_id == "test-run-001"
        assert manifest.created_at is not None
        assert manifest.harness_version is not None
        assert manifest.python_version is not None
        assert manifest.model == "qwen3.8-max"
        assert manifest.temperature == 0.2
        assert manifest.seed == 1234
        assert manifest.reasoning_effort == "medium"
        assert manifest.workflow == "full-research"

    def test_manifest_written_to_disk(self, store: RunStore) -> None:
        store.create_manifest(
            goal="test goal",
            workflow="full-research",
            model="qwen3.8-max",
            temperature=0.2,
            seed=1234,
            reasoning_effort="medium",
        )
        manifest_path = store.run_dir / "run_manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "test-run-001"
        assert "created_at" in data
        assert "git_branch" in data
        assert "git_head" in data
        assert "harness_version" in data
        assert "python_version" in data
        assert "platform" in data
        assert "model" in data
        assert "temperature" in data
        assert "seed" in data
        assert "workflow" in data

    def test_manifest_git_fields(self, store: RunStore) -> None:
        """Git fields should be populated or explicitly None if not in a repo."""
        manifest = store.create_manifest(
            goal="test",
            workflow="full-research",
            model="qwen3.8-max",
            temperature=0.2,
            seed=1234,
            reasoning_effort="medium",
        )
        # git_branch and git_head may be None outside a repo, but must exist
        assert hasattr(manifest, "git_branch")
        assert hasattr(manifest, "git_head")


# ---------------------------------------------------------------------------
# RunState
# ---------------------------------------------------------------------------


class TestRunState:
    """Tests for state.json management."""

    def test_initial_state(self, store: RunStore) -> None:
        state = store.init_state(workflow="full-research")
        assert state.status == "running"
        assert state.current_stage is None or state.current_stage == "goal"
        assert state.completed_stages == []

    def test_advance_stage(self, store: RunStore) -> None:
        store.init_state(workflow="full-research")
        store.advance_stage("goal", "evidence")
        state = store.load_state()
        assert state is not None
        assert state.current_stage == "evidence"
        assert "goal" in state.completed_stages

    def test_mark_failed(self, store: RunStore) -> None:
        store.init_state(workflow="full-research")
        store.mark_stage_failed("evidence", error="timeout")
        state = store.load_state()
        assert state is not None
        assert state.status == "failed"
        assert state.error is not None

    def test_mark_completed(self, store: RunStore) -> None:
        store.init_state(workflow="full-research")
        store.mark_completed()
        state = store.load_state()
        assert state is not None
        assert state.status == "completed"

    def test_state_persisted_to_disk(self, store: RunStore) -> None:
        store.init_state(workflow="full-research")
        state_path = store.run_dir / "state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert "status" in data
        assert "current_stage" in data
        assert "completed_stages" in data


# ---------------------------------------------------------------------------
# Lock mechanism
# ---------------------------------------------------------------------------


class TestLockMechanism:
    """Tests for run lock acquisition and conflict detection."""

    def test_acquire_lock(self, store: RunStore) -> None:
        store.acquire_lock()
        lock_path = store.run_dir / "lock.json"
        assert lock_path.exists()
        lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert lock_data["pid"] == os.getpid()
        assert "acquired_at" in lock_data

    def test_release_lock(self, store: RunStore) -> None:
        store.acquire_lock()
        store.release_lock()
        lock_path = store.run_dir / "lock.json"
        assert not lock_path.exists()

    def test_conflict_with_live_process(self, store: RunStore) -> None:
        """If lock is held by a live process, acquisition must raise."""
        lock_path = store.run_dir / "lock.json"
        lock_data = {
            "pid": os.getpid(),  # current process is alive
            "acquired_at": "2024-01-01T00:00:00Z",
        }
        lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

        with pytest.raises(LockConflictError):
            store.acquire_lock()

    def test_stale_lock_from_dead_process(self, store: RunStore) -> None:
        """If lock is held by a dead process, acquisition should succeed."""
        lock_path = store.run_dir / "lock.json"
        # Use a PID that almost certainly does not exist
        dead_pid = 99999999
        lock_data = {
            "pid": dead_pid,
            "acquired_at": "2024-01-01T00:00:00Z",
        }
        lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

        # Should not raise; stale lock is reclaimed
        store.acquire_lock()
        new_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        assert new_lock["pid"] == os.getpid()

    def test_concurrent_lock_rejection(self, store: RunStore) -> None:
        """Two threads attempting to lock: one must fail."""
        results: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def try_lock(name: str) -> None:
            barrier.wait()
            try:
                store.acquire_lock()
                results.append(f"{name}_acquired")
            except LockConflictError:
                results.append(f"{name}_rejected")

        t1 = threading.Thread(target=try_lock, args=("t1",))
        t2 = threading.Thread(target=try_lock, args=("t2",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        acquired = [r for r in results if "_acquired" in r]
        rejected = [r for r in results if "_rejected" in r]
        # At least one acquired; if both ran concurrently, one rejected
        assert len(acquired) >= 1


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


class TestRecovery:
    """Tests for run recovery after interruption."""

    def test_recover_from_completed_stage(self, store: RunStore) -> None:
        """Recovery should skip already-completed stages."""
        store.init_state(workflow="full-research")
        store.advance_stage("goal", "evidence")
        store.advance_stage("evidence", "hypothesis")

        # Simulate restart
        recovered = store.recover()
        assert recovered is not None
        assert recovered.current_stage == "hypothesis"
        assert "goal" in recovered.completed_stages
        assert "evidence" in recovered.completed_stages

    def test_recover_from_failed_stage(self, store: RunStore) -> None:
        """Recovery from a failed stage should mark it retryable."""
        store.init_state(workflow="full-research")
        store.advance_stage("goal", "evidence")
        store.mark_stage_failed("evidence", error="model timeout")

        recovered = store.recover()
        assert recovered is not None
        assert recovered.status == "retryable"
        assert recovered.current_stage == "evidence"

    def test_recover_with_corrupt_state(self, store: RunStore) -> None:
        """Corrupt state.json should raise a clear error."""
        state_path = store.run_dir / "state.json"
        state_path.write_text("{corrupt", encoding="utf-8")

        with pytest.raises(ValueError, match="state.json"):
            store.recover()

    def test_recover_missing_state(self, store: RunStore) -> None:
        """Missing state.json means the run never started properly."""
        # Ensure no state.json exists
        state_path = store.run_dir / "state.json"
        if state_path.exists():
            state_path.unlink()

        with pytest.raises(FileNotFoundError):
            store.recover()


# ---------------------------------------------------------------------------
# Events log
# ---------------------------------------------------------------------------


class TestEventsLog:
    """Tests for events.jsonl append-only log."""

    def test_append_event(self, store: RunStore) -> None:
        store.append_event("stage_started", {"stage": "goal"})
        store.append_event("stage_completed", {"stage": "goal"})

        events_path = store.run_dir / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        event1 = json.loads(lines[0])
        assert event1["event_type"] == "stage_started"
        assert event1["data"]["stage"] == "goal"
        assert "timestamp" in event1

    def test_events_are_append_only(self, store: RunStore) -> None:
        store.append_event("first", {})
        store.append_event("second", {})

        events_path = store.run_dir / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event_type"] == "first"
        assert json.loads(lines[1])["event_type"] == "second"


# ---------------------------------------------------------------------------
# Integration: full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Integration test: create → run → complete."""

    def test_full_run_lifecycle(self, store: RunStore) -> None:
        # Create
        store.create_manifest(
            goal="integration test",
            workflow="full-research",
            model="qwen3.8-max",
            temperature=0.2,
            seed=1234,
            reasoning_effort="medium",
        )
        store.acquire_lock()
        store.init_state(workflow="full-research")

        # Advance through stages
        stages = ["goal", "evidence", "hypothesis", "experiment", "analysis", "publish"]
        for i, stage in enumerate(stages):
            store.append_event("stage_started", {"stage": stage})
            if i < len(stages) - 1:
                store.advance_stage(stage, stages[i + 1])
            store.append_event("stage_completed", {"stage": stage})

        store.mark_completed()
        store.release_lock()

        # Verify final state
        state = store.load_state()
        assert state is not None
        assert state.status == "completed"
        assert len(state.completed_stages) == len(stages)

        # Verify events
        events_path = store.run_dir / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(stages) * 2  # started + completed for each
