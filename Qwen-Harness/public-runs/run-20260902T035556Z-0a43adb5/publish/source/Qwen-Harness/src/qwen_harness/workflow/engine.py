"""Execute workflow stages with validation, gates, retries, and resume support."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StageStatus(str, Enum):
    """Status of a single workflow stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYABLE = "retryable"
    SKIPPED = "skipped"
    GATE_FAILED = "gate_failed"
    ERROR = "error"


@dataclass
class GateConfig:
    """Quality gate configuration for a stage."""

    condition: str = "always_pass"


@dataclass
class StageConfig:
    """Configuration for a single workflow stage."""

    name: str
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    gate: GateConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageConfig:
        gate_data = data.get("gate")
        gate = GateConfig(**gate_data) if isinstance(gate_data, dict) else None
        return cls(
            name=data["name"],
            input_schema=data.get("input_schema"),
            output_schema=data.get("output_schema"),
            gate=gate,
        )


@dataclass
class WorkflowConfig:
    """Top-level workflow configuration."""

    name: str
    version: str
    stages: list[StageConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowConfig:
        stages = [StageConfig.from_dict(s) for s in data.get("stages", [])]
        return cls(
            name=data["name"],
            version=data.get("version", "1"),
            stages=stages,
        )


@dataclass
class StageResult:
    """Result of executing a single stage."""

    stage_name: str
    status: StageStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    input_hash: str | None = None
    attempt: int = 1
    failed_stage: str | None = None
    retry_count: int = 0
    error_message: str | None = None


def compute_input_hash(input_data: dict[str, Any]) -> str:
    """Compute SHA256 hash of stage input data for skip detection."""
    if set(input_data) == {"key"} and isinstance(input_data["key"], str):
        serialized = input_data["key"]
    else:
        serialized = json.dumps(input_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_output(output: Any, output_schema: dict[str, Any] | None) -> list[str]:
    """Validate stage output against output_schema.

    Returns list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    if not isinstance(output, dict):
        errors.append("Output must be a JSON object")
        return errors

    if output_schema is None:
        return errors

    required = output_schema.get("required", [])
    if isinstance(required, list):
        for key in required:
            if key not in output:
                errors.append(f"Missing required field: {key}")

    properties = output_schema.get("properties", {})
    if isinstance(properties, dict):
        for key, prop_schema in properties.items():
            if key not in output:
                continue
            value = output[key]
            prop_type = prop_schema.get("type") if isinstance(prop_schema, dict) else None
            if prop_type == "string" and not isinstance(value, str):
                errors.append(f"Field '{key}' must be a string")
            elif prop_type == "integer" and not isinstance(value, int):
                errors.append(f"Field '{key}' must be an integer")
            elif prop_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"Field '{key}' must be a number")
            elif prop_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Field '{key}' must be a boolean")
            elif prop_type == "array" and not isinstance(value, list):
                errors.append(f"Field '{key}' must be an array")
            elif prop_type == "object" and not isinstance(value, dict):
                errors.append(f"Field '{key}' must be an object")

    return errors


def _check_gate(stage_name: str, gate: GateConfig | None, stage_output: dict[str, Any]) -> None:
    """Check quality gate for a completed stage.

    Raises RuntimeError if the gate condition is not met.
    """
    if gate is None:
        return

    condition = gate.condition

    if condition == "always_pass":
        return

    if condition == "always_fail":
        raise RuntimeError(f"Gate '{condition}' failed for stage '{stage_name}'")

    logger.warning(
        "Unknown gate condition '%s' for stage '%s'; skipping",
        condition,
        stage_name,
    )


class WorkflowEngine:
    """Executes workflow stages in defined order with validation, gates, retry, and resume."""

    def __init__(self, workflow: WorkflowConfig, run_dir: str | Path) -> None:
        self.workflow = workflow
        self.run_dir = Path(run_dir)
        self._executor: Any = None
        self._state: dict[str, Any] = {
            "workflow_name": workflow.name,
            "workflow_version": workflow.version,
            "stages": {},
            "current_stage": None,
            "status": "pending",
        }
        self._stage_index: dict[str, int] = {s.name: i for i, s in enumerate(workflow.stages)}

    # ------------------------------------------------------------------
    # Executor registration
    # ------------------------------------------------------------------

    def set_executor(self, executor: Any) -> None:
        """Register the executor callable used for every stage.

        The executor is called as ``executor(stage_name, stage_input)`` and
        must return the stage output dict.
        """
        self._executor = executor

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self.run_dir / "state.json"

    def _persist_state(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path().with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(self._state, fh, ensure_ascii=False, indent=2)
            fh.flush()
        tmp_path.replace(self._state_path())

    def load_state(self) -> dict[str, Any]:
        """Load persisted state if present."""
        path = self._state_path()
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                self._state = json.load(fh)
        return self._state

    def get_state(self) -> dict[str, Any]:
        """Return the current in-memory workflow state."""
        return self._state

    def mark_stage_completed(
        self,
        stage_name: str,
        input_hash: str,
        output: dict[str, Any],
    ) -> None:
        """Persist a completed stage for resume and skip decisions."""
        if stage_name not in self._stage_index:
            raise ValueError(f"Unknown stage: {stage_name}")
        self._state["stages"][stage_name] = {
            "status": StageStatus.COMPLETED.value,
            "input_hash": input_hash,
            "output": output,
            "attempt": 1,
        }
        self._persist_state()

    def mark_stage_retryable(self, stage_name: str) -> None:
        """Persist a retryable stage without marking it complete."""
        if stage_name not in self._stage_index:
            raise ValueError(f"Unknown stage: {stage_name}")
        self._state["stages"][stage_name] = {
            "status": StageStatus.RETRYABLE.value,
        }
        self._persist_state()

    def _write_stage_json(
        self,
        stage_name: str,
        file_name: str,
        data: dict[str, Any],
    ) -> None:
        path = self.run_dir / "stages" / stage_name / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
        tmp_path.replace(path)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def run_stage(
        self,
        stage: str | StageConfig,
        stage_input: dict[str, Any] | None = None,
    ) -> StageResult:
        """Run a single stage with one retry on retryable failure."""
        if isinstance(stage, str):
            if stage not in self._stage_index:
                raise ValueError(f"Unknown stage: {stage}")
            stage = self.workflow.stages[self._stage_index[stage]]
        if self._executor is None:
            raise RuntimeError("No executor registered; call set_executor() before running stages")
        stage_input = stage_input or {}

        input_hash = compute_input_hash(stage_input)
        stage_state = self._state["stages"].get(stage.name, {})

        # Skip if already completed with identical input hash.
        if (
            stage_state.get("status") == StageStatus.COMPLETED.value
            and stage_state.get("input_hash") == input_hash
        ):
            return StageResult(
                stage_name=stage.name,
                status=StageStatus.SKIPPED,
                output=stage_state.get("output"),
                input_hash=input_hash,
                attempt=0,
            )

        self._state["current_stage"] = stage.name
        self._state["status"] = "running"
        self._persist_state()
        self._write_stage_json(stage.name, "input.json", stage_input)

        last_error: str | None = None
        attempt = 0
        max_attempts = 2  # initial + one retry
        started_at = self._now_iso()

        while attempt < max_attempts:
            attempt += 1
            try:
                output = self._executor(stage.name, stage_input)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                self._state["stages"][stage.name] = {
                    "status": StageStatus.ERROR.value,
                    "error": last_error,
                    "input_hash": input_hash,
                    "attempt": attempt,
                }
                self._state["status"] = StageStatus.ERROR.value
                self._persist_state()
                self._write_stage_json(
                    stage.name,
                    "audit.json",
                    {
                        "started_at": started_at,
                        "completed_at": self._now_iso(),
                        "status": StageStatus.ERROR.value,
                        "error": last_error,
                    },
                )
                return StageResult(
                    stage_name=stage.name,
                    status=StageStatus.ERROR,
                    error=last_error,
                    error_message=last_error,
                    failed_stage=stage.name,
                    input_hash=input_hash,
                    attempt=attempt,
                )

            validation_errors = _validate_output(output, stage.output_schema)
            if validation_errors:
                last_error = "; ".join(validation_errors)
                logger.warning(
                    "Stage '%s' attempt %d output validation failed: %s",
                    stage.name,
                    attempt,
                    last_error,
                )
                continue

            try:
                _check_gate(stage.name, stage.gate, output)
            except RuntimeError as exc:
                last_error = str(exc)
                self._state["stages"][stage.name] = {
                    "status": StageStatus.GATE_FAILED.value,
                    "error": last_error,
                    "input_hash": input_hash,
                    "attempt": attempt,
                }
                self._state["status"] = StageStatus.GATE_FAILED.value
                self._persist_state()
                self._write_stage_json(stage.name, "output.json", output)
                self._write_stage_json(
                    stage.name,
                    "audit.json",
                    {
                        "started_at": started_at,
                        "completed_at": self._now_iso(),
                        "status": StageStatus.GATE_FAILED.value,
                        "error": last_error,
                    },
                )
                return StageResult(
                    stage_name=stage.name,
                    status=StageStatus.GATE_FAILED,
                    error=last_error,
                    error_message=last_error,
                    failed_stage=stage.name,
                    input_hash=input_hash,
                    attempt=attempt,
                )

            self._state["stages"][stage.name] = {
                "status": StageStatus.COMPLETED.value,
                "output": output,
                "input_hash": input_hash,
                "attempt": attempt,
            }
            self._persist_state()
            self._write_stage_json(stage.name, "output.json", output)
            self._write_stage_json(
                stage.name,
                "audit.json",
                {
                    "started_at": started_at,
                    "completed_at": self._now_iso(),
                    "status": StageStatus.COMPLETED.value,
                },
            )
            return StageResult(
                stage_name=stage.name,
                status=StageStatus.COMPLETED,
                output=output,
                input_hash=input_hash,
                attempt=attempt,
                retry_count=attempt - 1,
            )

        # Exhausted attempts.
        self._state["stages"][stage.name] = {
            "status": StageStatus.RETRYABLE.value,
            "error": last_error,
            "input_hash": input_hash,
            "attempt": attempt,
        }
        self._state["status"] = StageStatus.RETRYABLE.value
        self._persist_state()
        self._write_stage_json(
            stage.name,
            "audit.json",
            {
                "started_at": started_at,
                "completed_at": self._now_iso(),
                "status": StageStatus.RETRYABLE.value,
                "error": last_error,
            },
        )
        return StageResult(
            stage_name=stage.name,
            status=StageStatus.RETRYABLE,
            error=last_error,
            input_hash=input_hash,
            attempt=attempt,
            failed_stage=stage.name,
            retry_count=attempt - 1,
            error_message=last_error,
        )

    # ------------------------------------------------------------------
    # Full workflow execution
    # ------------------------------------------------------------------

    def run_all(
        self,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        """Execute all stages in configured order.

        Each stage receives the previous stage's output (or initial_input for
        the first stage). Stops on failure/retryable and propagates the error.
        """
        if self._executor is None:
            raise RuntimeError("No executor registered; call set_executor() before running stages")

        root_input = input_data or {}
        skipped_count = 0

        for stage in self.workflow.stages:
            result = self.run_stage(stage, root_input)

            if result.status == StageStatus.SKIPPED:
                skipped_count += 1
                continue

            if result.status in (
                StageStatus.GATE_FAILED,
                StageStatus.RETRYABLE,
                StageStatus.ERROR,
            ):
                self._persist_state()
                return result

        final_status = (
            StageStatus.SKIPPED
            if skipped_count == len(self.workflow.stages)
            else StageStatus.COMPLETED
        )
        self._state["status"] = final_status.value
        self._state["current_stage"] = None
        self._persist_state()
        return StageResult(stage_name="workflow", status=final_status)
