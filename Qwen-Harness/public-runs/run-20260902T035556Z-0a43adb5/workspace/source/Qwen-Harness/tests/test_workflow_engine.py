"""Tests for the workflow engine: stage ordering, gate failures, retry, and skip logic."""

import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qwen_harness.workflow.engine import (
    WorkflowEngine,
    StageResult,
    StageStatus,
    WorkflowConfig,
    StageConfig,
    GateConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stage_config(name: str, gate_pass: bool = True) -> StageConfig:
    return StageConfig(
        name=name,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        gate=GateConfig(condition="always_pass" if gate_pass else "always_fail"),
    )


def _make_workflow_config(stages: list[StageConfig]) -> WorkflowConfig:
    return WorkflowConfig(name="test-workflow", version="1.0", stages=stages)


def _default_workflow() -> WorkflowConfig:
    return _make_workflow_config(
        [
            _make_stage_config("goal"),
            _make_stage_config("evidence"),
            _make_stage_config("hypothesis"),
            _make_stage_config("experiment"),
            _make_stage_config("analysis"),
            _make_stage_config("publish"),
        ]
    )


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "test-run-001"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture
def engine(tmp_run_dir: Path) -> WorkflowEngine:
    wf = _default_workflow()
    return WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)


# ---------------------------------------------------------------------------
# Stage ordering
# ---------------------------------------------------------------------------


class TestStageOrdering:
    def test_stages_execute_in_configured_order(self, engine: WorkflowEngine):
        """Stages must execute in the order defined in the workflow config."""
        executed: list[str] = []

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            executed.append(stage_name)
            return {"status": "ok", "stage": stage_name}

        engine.set_executor(fake_executor)
        engine.run_all()

        assert executed == [
            "goal",
            "evidence",
            "hypothesis",
            "experiment",
            "analysis",
            "publish",
        ]

    def test_single_stage_execution(self, engine: WorkflowEngine):
        """Running a single stage by name executes only that stage."""
        executed: list[str] = []

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            executed.append(stage_name)
            return {"result": "done"}

        engine.set_executor(fake_executor)
        engine.run_stage("evidence")

        assert executed == ["evidence"]

    def test_unknown_stage_raises(self, engine: WorkflowEngine):
        """Requesting a stage not in the workflow raises ValueError."""
        with pytest.raises(ValueError, match="Unknown stage"):
            engine.run_stage("nonexistent_stage")


# ---------------------------------------------------------------------------
# Gate failures
# ---------------------------------------------------------------------------


class TestGateFailures:
    def test_gate_failure_stops_workflow(self, tmp_run_dir: Path):
        """When a gate fails, subsequent stages are not executed."""
        stages = [
            _make_stage_config("goal", gate_pass=True),
            _make_stage_config("evidence", gate_pass=False),
            _make_stage_config("hypothesis", gate_pass=True),
        ]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        executed: list[str] = []

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            executed.append(stage_name)
            return {"data": stage_name}

        eng.set_executor(fake_executor)
        result = eng.run_all()

        assert "goal" in executed
        assert "evidence" in executed
        assert "hypothesis" not in executed
        assert result.status == StageStatus.GATE_FAILED
        assert result.failed_stage == "evidence"

    def test_gate_failure_records_in_state(self, tmp_run_dir: Path):
        """Gate failure is recorded in the run state."""
        stages = [
            _make_stage_config("goal", gate_pass=False),
        ]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            return {}

        eng.set_executor(fake_executor)
        eng.run_all()

        state = eng.get_state()
        assert state["current_stage"] == "goal"
        assert state["status"] == "gate_failed"


# ---------------------------------------------------------------------------
# Output validation and retry
# ---------------------------------------------------------------------------


class TestOutputValidationRetry:
    def test_invalid_output_triggers_retry(self, tmp_run_dir: Path):
        """If stage output fails schema validation, the engine retries once."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        call_count = 0

        def flaky_executor(stage_name: str, stage_input: dict) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Return invalid output (missing required field)
                return {"invalid": True}
            return {"status": "ok", "stage": stage_name}

        # Override output schema to require 'status' field
        wf.stages[0].output_schema = {
            "type": "object",
            "required": ["status"],
        }

        eng.set_executor(flaky_executor)
        result = eng.run_all()

        assert call_count == 2
        assert result.status == StageStatus.COMPLETED

    def test_retry_exhausted_marks_retryable(self, tmp_run_dir: Path):
        """If retry also fails validation, stage is marked retryable."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        wf.stages[0].output_schema = {
            "type": "object",
            "required": ["status"],
        }
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def always_invalid(stage_name: str, stage_input: dict) -> dict:
            return {"bad": "output"}

        eng.set_executor(always_invalid)
        result = eng.run_all()

        assert result.status == StageStatus.RETRYABLE
        assert result.retry_count == 1

    def test_no_fallback_to_free_text(self, tmp_run_dir: Path):
        """On validation failure, engine does not accept free-text fallback."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        wf.stages[0].output_schema = {
            "type": "object",
            "required": ["structured_field"],
        }
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def returns_string(stage_name: str, stage_input: dict):
            return "free text response"

        eng.set_executor(returns_string)
        result = eng.run_all()

        # Must not accept non-dict output
        assert result.status == StageStatus.RETRYABLE


# ---------------------------------------------------------------------------
# Skip logic (input hash unchanged)
# ---------------------------------------------------------------------------


class TestSkipLogic:
    def test_skip_when_input_hash_unchanged(self, tmp_run_dir: Path):
        """If a stage's input hash matches the previous successful run, skip it."""
        stages = [
            _make_stage_config("goal"),
            _make_stage_config("evidence"),
        ]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        executed: list[str] = []

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            executed.append(stage_name)
            return {"status": "ok"}

        eng.set_executor(fake_executor)

        # First run: both stages execute
        eng.run_all()
        assert executed == ["goal", "evidence"]

        # Simulate completed state with input hashes
        input_data = {"goal_text": "test"}
        input_hash = hashlib.sha256(
            json.dumps(input_data, sort_keys=True).encode()
        ).hexdigest()

        eng.mark_stage_completed("goal", input_hash=input_hash, output={"status": "ok"})
        eng.mark_stage_completed("evidence", input_hash=input_hash, output={"status": "ok"})

        # Second run with same input: stages should be skipped
        executed.clear()
        eng2 = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)
        eng2.set_executor(fake_executor)
        eng2.load_state()
        result = eng2.run_all(input_data=input_data)

        assert executed == []
        assert result.status == StageStatus.SKIPPED

    def test_no_skip_when_input_hash_changed(self, tmp_run_dir: Path):
        """If input hash differs, the stage re-executes."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        executed: list[str] = []

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            executed.append(stage_name)
            return {"status": "ok"}

        eng.set_executor(fake_executor)

        # Mark as completed with old hash
        old_hash = hashlib.sha256(b"old_input").hexdigest()
        eng.mark_stage_completed("goal", input_hash=old_hash, output={"status": "ok"})

        # Run with different input
        new_input = {"goal_text": "new goal"}
        eng2 = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)
        eng2.set_executor(fake_executor)
        eng2.load_state()
        eng2.run_all(input_data=new_input)

        assert executed == ["goal"]

    def test_skip_only_applies_to_completed_stages(self, tmp_run_dir: Path):
        """Stages that failed or are retryable are not skipped."""
        stages = [
            _make_stage_config("goal"),
            _make_stage_config("evidence"),
        ]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        executed: list[str] = []

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            executed.append(stage_name)
            return {"status": "ok"}

        eng.set_executor(fake_executor)

        # Mark goal as completed, evidence as retryable
        input_hash = hashlib.sha256(b"input").hexdigest()
        eng.mark_stage_completed("goal", input_hash=input_hash, output={"status": "ok"})
        eng.mark_stage_retryable("evidence")

        eng2 = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)
        eng2.set_executor(fake_executor)
        eng2.load_state()
        eng2.run_all(input_data={"key": "input"})

        # goal skipped, evidence re-executed
        assert "goal" not in executed
        assert "evidence" in executed


# ---------------------------------------------------------------------------
# Stage result and state persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_stage_output_written_to_disk(self, tmp_run_dir: Path):
        """Each stage output is written to stages/<name>/output.json."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            return {"status": "ok", "answer": 42}

        eng.set_executor(fake_executor)
        eng.run_all()

        output_path = tmp_run_dir / "stages" / "goal" / "output.json"
        assert output_path.exists()
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["answer"] == 42

    def test_stage_input_written_to_disk(self, tmp_run_dir: Path):
        """Each stage input is written to stages/<name>/input.json."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            return {"status": "ok"}

        eng.set_executor(fake_executor)
        eng.run_all(input_data={"goal_text": "test goal"})

        input_path = tmp_run_dir / "stages" / "goal" / "input.json"
        assert input_path.exists()
        data = json.loads(input_path.read_text(encoding="utf-8"))
        assert data["goal_text"] == "test goal"

    def test_audit_trail_written(self, tmp_run_dir: Path):
        """Each stage execution writes an audit.json with timing and status."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def fake_executor(stage_name: str, stage_input: dict) -> dict:
            return {"status": "ok"}

        eng.set_executor(fake_executor)
        eng.run_all()

        audit_path = tmp_run_dir / "stages" / "goal" / "audit.json"
        assert audit_path.exists()
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert "started_at" in audit
        assert "completed_at" in audit
        assert audit["status"] == "completed"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_executor_exception_marks_stage_error(self, tmp_run_dir: Path):
        """If the executor raises, the stage is marked as error."""
        stages = [_make_stage_config("goal")]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def failing_executor(stage_name: str, stage_input: dict) -> dict:
            raise RuntimeError("simulated failure")

        eng.set_executor(failing_executor)
        result = eng.run_all()

        assert result.status == StageStatus.ERROR
        assert "simulated failure" in result.error_message

    def test_error_includes_stage_name(self, tmp_run_dir: Path):
        """Error result includes the stage where failure occurred."""
        stages = [
            _make_stage_config("goal"),
            _make_stage_config("evidence"),
        ]
        wf = _make_workflow_config(stages)
        eng = WorkflowEngine(workflow=wf, run_dir=tmp_run_dir)

        def fail_on_evidence(stage_name: str, stage_input: dict) -> dict:
            if stage_name == "evidence":
                raise ValueError("evidence source unavailable")
            return {"status": "ok"}

        eng.set_executor(fail_on_evidence)
        result = eng.run_all()

        assert result.failed_stage == "evidence"
        assert result.status == StageStatus.ERROR
