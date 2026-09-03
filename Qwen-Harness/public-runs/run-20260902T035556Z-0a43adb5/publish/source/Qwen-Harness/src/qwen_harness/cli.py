"""Qwen-Harness CLI entry point.

Subcommands: run, resume, status, report, publish, doctor, validate, list-runs.
Exit codes:
  0 - success
  1 - quality gate not passed
  2 - configuration/input/contract error
  3 - model API or external source failure without fallback
  4 - module command failure
  5 - run state corruption, lock conflict, or recovery failure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from qwen_harness.run_store import RunStore, RunState, RunManifest
from qwen_harness.workflow.engine import WorkflowEngine


# ---------------------------------------------------------------------------
# Exit code constants
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_GATE_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_API_FAILURE = 3
EXIT_MODULE_FAILURE = 4
EXIT_STATE_CORRUPT = 5


# ---------------------------------------------------------------------------
# Error output helper
# ---------------------------------------------------------------------------

def emit_error(
    error_type: str,
    message: str,
    run_id: str | None = None,
    stage: str | None = None,
    suggestion: str | None = None,
) -> None:
    """Print structured error to stderr."""
    payload: dict[str, Any] = {
        "error_type": error_type,
        "message": message,
    }
    if run_id is not None:
        payload["run_id"] = run_id
    if stage is not None:
        payload["stage"] = stage
    if suggestion is not None:
        payload["suggestion"] = suggestion
    click.echo(json.dumps(payload, ensure_ascii=False), err=True)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(name="qwen-harness")
@click.version_option(package_name="qwen-harness", prog_name="qwen-harness")
def cli() -> None:
    """Qwen-Harness: structured research orchestration CLI."""


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@cli.command(name="run")
@click.option("--goal", type=str, default=None, help="Research goal text.")
@click.option("--goal-file", type=click.Path(exists=False), default=None, help="Path to goal JSON file.")
@click.option(
    "--workflow",
    type=click.Choice(["full-research", "research-only", "reproduce-existing"]),
    default="full-research",
    help="Workflow to execute.",
)
@click.option("--offline", is_flag=True, default=False, help="Run without network access.")
@click.option("--allow-network", is_flag=True, default=False, help="Explicitly allow network access.")
@click.option(
    "--refresh-environment",
    type=click.Choice(["none", "weather", "hourly", "daily"]),
    default="none",
    help="Environment refresh tier.",
)
@click.option(
    "--approval-mode",
    type=click.Choice(["auto", "critical", "all"]),
    default="auto",
    help="Approval mode for gated operations.",
)
@click.option("--publish-web", is_flag=True, default=False, help="Publish web payload after run.")
@click.option("--max-iterations", type=int, default=3, help="Maximum iteration count.")
def run_command(
    goal: str | None,
    goal_file: str | None,
    workflow: str,
    offline: bool,
    allow_network: bool,
    refresh_environment: str,
    approval_mode: str,
    publish_web: bool,
    max_iterations: int,
) -> None:
    """Execute a research workflow."""
    # Validate goal input
    if goal is None and goal_file is None:
        emit_error(
            error_type="config_error",
            message="Either --goal or --goal-file must be provided.",
            suggestion="Provide --goal 'text' or --goal-file path/to/goal.json",
        )
        sys.exit(EXIT_CONFIG_ERROR)

    if goal is not None and goal_file is not None:
        emit_error(
            error_type="config_error",
            message="Only one of --goal or --goal-file may be provided.",
            suggestion="Remove one of the goal options.",
        )
        sys.exit(EXIT_CONFIG_ERROR)

    # Resolve goal text
    goal_text: str
    if goal_file is not None:
        goal_path = Path(goal_file)
        if not goal_path.exists():
            emit_error(
                error_type="config_error",
                message=f"Goal file not found: {goal_file}",
                suggestion="Check the path to the goal file.",
            )
            sys.exit(EXIT_CONFIG_ERROR)
        try:
            with open(goal_path, "r", encoding="utf-8") as f:
                goal_data = json.load(f)
            goal_text = goal_data.get("question", goal_data.get("title", str(goal_data)))
        except (json.JSONDecodeError, OSError) as exc:
            emit_error(
                error_type="config_error",
                message=f"Failed to parse goal file: {exc}",
                suggestion="Ensure the goal file is valid JSON.",
            )
            sys.exit(EXIT_CONFIG_ERROR)
    else:
        goal_text = goal  # type: ignore[assignment]

    # Network permission check
    network_allowed = allow_network and not offline
    if offline and allow_network:
        emit_error(
            error_type="config_error",
            message="--offline and --allow-network are mutually exclusive.",
            suggestion="Remove one of the conflicting flags.",
        )
        sys.exit(EXIT_CONFIG_ERROR)

    # Load harness config
    config = _load_harness_config()
    if config is None:
        emit_error(
            error_type="config_error",
            message="Harness configuration file not found or invalid.",
            suggestion="Ensure Qwen-Harness/config/harness.json exists and is valid JSON.",
        )
        sys.exit(EXIT_CONFIG_ERROR)

    # Load workflow definition
    workflow_def = _load_workflow(workflow)
    if workflow_def is None:
        emit_error(
            error_type="config_error",
            message=f"Workflow definition not found: {workflow}",
            suggestion="Check Qwen-Harness/config/workflows/ directory.",
        )
        sys.exit(EXIT_CONFIG_ERROR)

    # Create run store and initialize
    try:
        store = RunStore(config)
        run_id = store.create_run(
            goal_text=goal_text,
            workflow_name=workflow,
            offline=offline,
            network_allowed=network_allowed,
            refresh_environment=refresh_environment,
            approval_mode=approval_mode,
            publish_web=publish_web,
            max_iterations=max_iterations,
        )
    except Exception as exc:
        emit_error(
            error_type="state_error",
            message=f"Failed to create run: {exc}",
            suggestion="Check runtime/runs directory permissions.",
        )
        sys.exit(EXIT_STATE_CORRUPT)

    # Execute workflow
    try:
        engine = WorkflowEngine(
            store=store,
            run_id=run_id,
            workflow_def=workflow_def,
            config=config,
            offline=offline,
            network_allowed=network_allowed,
        )
        result = engine.execute()
    except KeyboardInterrupt:
        emit_error(
            error_type="interrupted",
            message="Run interrupted by user.",
            run_id=run_id,
            suggestion="Use 'qwen-harness resume' to continue.",
        )
        sys.exit(EXIT_STATE_CORRUPT)
    except Exception as exc:
        error_type = _classify_exception(exc)
        emit_error(
            error_type=error_type,
            message=str(exc),
            run_id=run_id,
            stage=getattr(exc, "stage", None),
            suggestion=_suggestion_for_error(error_type),
        )
        sys.exit(_exit_code_for_error(error_type))

    # Report result
    if result.status == "completed":
        click.echo(json.dumps({
            "run_id": run_id,
            "status": "completed",
            "workflow": workflow,
            "stages_completed": result.stages_completed,
        }, ensure_ascii=False, indent=2))
        sys.exit(EXIT_SUCCESS)
    elif result.status == "gate_failed":
        emit_error(
            error_type="gate_failed",
            message=f"Quality gate not passed at stage: {result.failed_stage}",
            run_id=run_id,
            stage=result.failed_stage,
            suggestion="Review stage output and gate conditions.",
        )
        sys.exit(EXIT_GATE_FAILED)
    else:
        emit_error(
            error_type="execution_error",
            message=f"Run ended with status: {result.status}",
            run_id=run_id,
            stage=result.failed_stage,
        )
        sys.exit(_exit_code_for_error(result.status))


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------

@cli.command(name="resume")
@click.argument("run_id", type=str)
def resume_command(run_id: str) -> None:
    """Resume a previously interrupted run."""
    config = _load_harness_config()
    if config is None:
        emit_error(
            error_type="config_error",
            message="Harness configuration file not found or invalid.",
        )
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        store = RunStore(config)
        state = store.load_state(run_id)
    except FileNotFoundError:
        emit_error(
            error_type="state_error",
            message=f"Run not found: {run_id}",
            run_id=run_id,
            suggestion="Use 'qwen-harness list-runs' to see available runs.",
        )
        sys.exit(EXIT_STATE_CORRUPT)
    except Exception as exc:
        emit_error(
            error_type="state_error",
            message=f"Failed to load run state: {exc}",
            run_id=run_id,
        )
        sys.exit(EXIT_STATE_CORRUPT)

    # Check lock
    if store.is_locked(run_id):
        emit_error(
            error_type="lock_conflict",
            message=f"Run {run_id} is locked by another process.",
            run_id=run_id,
            suggestion="Wait for the other process to finish or remove stale lock.",
        )
        sys.exit(EXIT_STATE_CORRUPT)

    # Load workflow
    workflow_def = _load_workflow(state.workflow_name)
    if workflow_def is None:
        emit_error(
            error_type="config_error",
            message=f"Workflow definition not found: {state.workflow_name}",
            run_id=run_id,
        )
        sys.exit(EXIT_CONFIG_ERROR)

    # Resume execution
    try:
        engine = WorkflowEngine(
            store=store,
            run_id=run_id,
            workflow_def=workflow_def,
            config=config,
            offline=state.offline,
            network_allowed=state.network_allowed,
        )
        result = engine.resume()
    except Exception as exc:
        error_type = _classify_exception(exc)
        emit_error(
            error_type=error_type,
            message=str(exc),
            run_id=run_id,
            stage=getattr(exc, "stage", None),
        )
        sys.exit(_exit_code_for_error(error_type))

    if result.status == "completed":
        click.echo(json.dumps({
            "run_id": run_id,
            "status": "completed",
            "resumed": True,
        }, ensure_ascii=False, indent=2))
        sys.exit(EXIT_SUCCESS)
    else:
        emit_error(
            error_type="execution_error",
            message=f"Resumed run ended with status: {result.status}",
            run_id=run_id,
            stage=result.failed_stage,
        )
        sys.exit(_exit_code_for_error(result.status))


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command(name="status")
@click.argument("run_id", type=str)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def status_command(run_id: str, as_json: bool) -> None:
    """Show run status."""
    config = _load_harness_config()
    if config is None:
        emit_error(error_type="config_error", message="Harness configuration not found.")
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        store = RunStore(config)
        state = store.load_state(run_id)
    except FileNotFoundError:
        emit_error(
            error_type="state_error",
            message=f"Run not found: {run_id}",
            run_id=run_id,
        )
        sys.exit(EXIT_STATE_CORRUPT)

    if as_json:
        click.echo(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(f"Run: {run_id}")
        click.echo(f"Status: {state.status}")
        click.echo(f"Current stage: {state.current_stage}")
        click.echo(f"Workflow: {state.workflow_name}")

    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@cli.command(name="report")
@click.argument("run_id", type=str)
def report_command(run_id: str) -> None:
    """Generate report for a completed run."""
    config = _load_harness_config()
    if config is None:
        emit_error(error_type="config_error", message="Harness configuration not found.")
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        store = RunStore(config)
        state = store.load_state(run_id)
    except FileNotFoundError:
        emit_error(
            error_type="state_error",
            message=f"Run not found: {run_id}",
            run_id=run_id,
        )
        sys.exit(EXIT_STATE_CORRUPT)

    if state.status != "completed":
        emit_error(
            error_type="state_error",
            message=f"Run {run_id} is not completed (status: {state.status}).",
            run_id=run_id,
            suggestion="Complete or resume the run first.",
        )
        sys.exit(EXIT_STATE_CORRUPT)

    # Generate report
    report_path = store.run_dir(run_id) / "reports"
    report_path.mkdir(parents=True, exist_ok=True)

    report_data = {
        "run_id": run_id,
        "workflow": state.workflow_name,
        "status": state.status,
        "stages_completed": state.stages_completed,
        "generated_at": _now_iso(),
    }

    report_file = report_path / "experiment_report.md"
    _atomic_write_json(report_file, report_data)

    click.echo(f"Report generated: {report_file}")
    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

@cli.command(name="publish")
@click.argument("run_id", type=str)
def publish_command(run_id: str) -> None:
    """Publish run results to web payload."""
    config = _load_harness_config()
    if config is None:
        emit_error(error_type="config_error", message="Harness configuration not found.")
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        store = RunStore(config)
        state = store.load_state(run_id)
    except FileNotFoundError:
        emit_error(
            error_type="state_error",
            message=f"Run not found: {run_id}",
            run_id=run_id,
        )
        sys.exit(EXIT_STATE_CORRUPT)

    if state.status != "completed":
        emit_error(
            error_type="state_error",
            message=f"Run {run_id} is not completed.",
            run_id=run_id,
        )
        sys.exit(EXIT_STATE_CORRUPT)

    # Publish web payload
    publish_dir = store.run_dir(run_id) / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": run_id,
        "published_at": _now_iso(),
        "status": "published",
    }

    payload_file = publish_dir / "research_harness_latest.json"
    _atomic_write_json(payload_file, payload)

    # Also copy to web data directory if it exists
    web_data_dir = Path("xuhui_route_builder/data/web")
    if web_data_dir.exists():
        target = web_data_dir / "research_harness_latest.json"
        _atomic_write_json(target, payload)
        click.echo(f"Published to: {target}")
    else:
        click.echo(f"Published to run directory: {payload_file}")

    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

@cli.command(name="doctor")
def doctor_command() -> None:
    """Check harness health and configuration."""
    issues: list[str] = []

    # Check config
    config = _load_harness_config()
    if config is None:
        issues.append("config/harness.json not found or invalid")
    else:
        required_keys = ["model", "temperature", "seed", "reasoning_effort", "run_dir"]
        for key in required_keys:
            if key not in config:
                issues.append(f"config/harness.json missing key: {key}")

    # Check workflows
    workflows_dir = _harness_root() / "config" / "workflows"
    if not workflows_dir.exists():
        issues.append("config/workflows/ directory not found")
    else:
        for wf_name in ["full-research", "research-only", "reproduce-existing"]:
            wf_file = workflows_dir / f"{wf_name}.json"
            if not wf_file.exists():
                issues.append(f"Workflow file missing: {wf_file}")

    # Check runtime directory
    if config is not None:
        run_dir = Path(config.get("run_dir", "runtime/runs"))
        if not run_dir.is_absolute():
            run_dir = _harness_root() / run_dir
        if not run_dir.exists():
            issues.append(f"Run directory does not exist: {run_dir}")

    if issues:
        click.echo("Issues found:", err=True)
        for issue in issues:
            click.echo(f"  - {issue}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    else:
        click.echo("All checks passed.")
        sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@cli.command(name="validate")
@click.option("--scope", type=click.Choice(["all", "config", "data", "schema"]), default="all")
def validate_command(scope: str) -> None:
    """Validate harness configuration and data integrity."""
    errors: list[str] = []

    if scope in ("all", "config"):
        config = _load_harness_config()
        if config is None:
            errors.append("harness.json: not found or invalid")

    if scope in ("all", "data"):
        # Check route data
        route_catalog = Path("xuhui_route_builder/data/web/route_catalog.json")
        if route_catalog.exists():
            try:
                with open(route_catalog, "r", encoding="utf-8") as f:
                    routes = json.load(f)
                if not isinstance(routes, list) or len(routes) != 90:
                    errors.append(f"route_catalog.json: expected 90 items, got {len(routes) if isinstance(routes, list) else 'non-list'}")
            except json.JSONDecodeError:
                errors.append("route_catalog.json: invalid JSON")
        else:
            errors.append("route_catalog.json: not found")

        # Check environment dashboard
        env_dashboard = Path("xuhui_route_builder/data/web/environment_dashboard.json")
        if env_dashboard.exists():
            try:
                with open(env_dashboard, "r", encoding="utf-8") as f:
                    dashboard = json.load(f)
                required_keys = ["metadata", "current", "forecast", "routes"]
                for key in required_keys:
                    if key not in dashboard:
                        errors.append(f"environment_dashboard.json: missing key '{key}'")
            except json.JSONDecodeError:
                errors.append("environment_dashboard.json: invalid JSON")
        else:
            errors.append("environment_dashboard.json: not found")

    if errors:
        for err in errors:
            click.echo(f"  FAIL: {err}", err=True)
        sys.exit(EXIT_CONFIG_ERROR)
    else:
        click.echo("Validation passed.")
        sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# list-runs
# ---------------------------------------------------------------------------

@cli.command(name="list-runs")
@click.option("--limit", type=int, default=10, help="Maximum number of runs to list.")
def list_runs_command(limit: int) -> None:
    """List recent runs."""
    config = _load_harness_config()
    if config is None:
        emit_error(error_type="config_error", message="Harness configuration not found.")
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        store = RunStore(config)
        runs = store.list_runs(limit=limit)
    except Exception as exc:
        emit_error(
            error_type="state_error",
            message=f"Failed to list runs: {exc}",
        )
        sys.exit(EXIT_STATE_CORRUPT)

    if not runs:
        click.echo("No runs found.")
    else:
        for run_info in runs:
            click.echo(
                f"{run_info['run_id']}  {run_info['status']:<12}  "
                f"{run_info['workflow']:<20}  {run_info['created_at']}"
            )

    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _harness_root() -> Path:
    """Return the Qwen-Harness root directory."""
    return Path(__file__).resolve().parent.parent.parent


def _load_harness_config() -> dict[str, Any] | None:
    """Load and parse harness.json configuration."""
    config_path = _harness_root() / "config" / "harness.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_workflow(workflow_name: str) -> dict[str, Any] | None:
    """Load workflow definition by name."""
    wf_path = _harness_root() / "config" / "workflows" / f"{workflow_name}.json"
    if not wf_path.exists():
        return None
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write JSON to a file (temp -> flush -> fsync -> replace)."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _classify_exception(exc: Exception) -> str:
    """Classify an exception into an error type string."""
    exc_type_name = type(exc).__name__
    if "api" in exc_type_name.lower() or "model" in exc_type_name.lower():
        return "api_failure"
    if "module" in exc_type_name.lower() or "command" in exc_type_name.lower():
        return "module_failure"
    if "state" in exc_type_name.lower() or "lock" in exc_type_name.lower():
        return "state_error"
    if "config" in exc_type_name.lower() or "schema" in exc_type_name.lower():
        return "config_error"
    return "execution_error"


def _exit_code_for_error(error_type: str) -> int:
    """Map error type to exit code."""
    mapping = {
        "gate_failed": EXIT_GATE_FAILED,
        "config_error": EXIT_CONFIG_ERROR,
        "api_failure": EXIT_API_FAILURE,
        "module_failure": EXIT_MODULE_FAILURE,
        "state_error": EXIT_STATE_CORRUPT,
        "lock_conflict": EXIT_STATE_CORRUPT,
    }
    return mapping.get(error_type, EXIT_CONFIG_ERROR)


def _suggestion_for_error(error_type: str) -> str:
    """Return a suggestion string for the given error type."""
    suggestions = {
        "gate_failed": "Review stage output and quality gate conditions.",
        "config_error": "Check configuration files and input parameters.",
        "api_failure": "Check API connectivity and credentials. Consider --offline mode.",
        "module_failure": "Check module installation and data files.",
        "state_error": "Check run directory integrity. Use 'qwen-harness doctor' for diagnostics.",
        "lock_conflict": "Wait for the other process or remove stale lock file.",
    }
    return suggestions.get(error_type, "Check logs for details.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
