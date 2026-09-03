"""CLI entry point for weather_api_data.

Subcommands:
  config-check      Check API keys and configuration availability.
  dry-run           Validate pipeline flow without calling external APIs.
  scheduled-refresh Execute tiered data refresh (weather/hourly/daily).
  publish-web       Generate environment_dashboard.json to web data directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from weather_api_data.pipeline import (
    PipelineConfig,
    PipelineResult,
    check_config,
    dry_run,
    scheduled_refresh,
)
from weather_api_data.web_export import publish_web


def _find_repo_root() -> Path:
    """Walk up from this file to find the repository root (contains pyproject.toml)."""
    current = Path(__file__).resolve()
    for parent in [current.parent] + list(current.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
        if parent.name == "weather_api_data" and (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _get_config() -> PipelineConfig:
    """Build pipeline configuration from environment and defaults."""
    return PipelineConfig(
        repo_root=_find_repo_root(),
        exports_dir=Path("runtime/exports"),
        web_output_dir=Path("runtime/exports/web"),
    )


def cmd_config_check(args: argparse.Namespace) -> int:
    """Check API keys and configuration availability."""
    config = _get_config()
    result = check_config(config)

    output: dict[str, Any] = {
        "command": "config-check",
        "status": result.status,
        "checks": result.checks,
        "warnings": result.warnings,
        "errors": result.errors,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Config check: {result.status}")
        for check_name, check_result in result.checks.items():
            symbol = "\u2713" if check_result else "\u2717"
            print(f"  {symbol} {check_name}")
        for warning in result.warnings:
            print(f"  WARNING: {warning}")
        for error in result.errors:
            print(f"  ERROR: {error}")

    return 0 if result.status == "ok" else 2


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Validate pipeline flow without calling external APIs."""
    config = _get_config()
    result = dry_run(config)

    output: dict[str, Any] = {
        "command": "dry-run",
        "status": result.status,
        "steps": result.steps,
        "warnings": result.warnings,
        "errors": result.errors,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Dry run: {result.status}")
        for step in result.steps:
            print(f"  - {step}")
        for warning in result.warnings:
            print(f"  WARNING: {warning}")
        for error in result.errors:
            print(f"  ERROR: {error}")

    return 0 if result.status == "ok" else 2


def cmd_scheduled_refresh(args: argparse.Namespace) -> int:
    """Execute tiered data refresh."""
    valid_tiers = ("weather", "hourly", "daily")
    if args.tier not in valid_tiers:
        print(
            json.dumps(
                {
                    "error_type": "invalid_argument",
                    "message": f"Invalid tier '{args.tier}'. Must be one of: {', '.join(valid_tiers)}",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    config = _get_config()

    if args.offline:
        result = PipelineResult(
            status="stale",
            steps=["offline_mode: using last-known-good snapshot"],
            warnings=["No network access; using cached data"],
            errors=[],
        )
    else:
        result = scheduled_refresh(config, tier=args.tier)

    output: dict[str, Any] = {
        "command": "scheduled-refresh",
        "tier": args.tier,
        "status": result.status,
        "steps": result.steps,
        "warnings": result.warnings,
        "errors": result.errors,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Scheduled refresh ({args.tier}): {result.status}")
        for step in result.steps:
            print(f"  - {step}")
        for warning in result.warnings:
            print(f"  WARNING: {warning}")
        for error in result.errors:
            print(f"  ERROR: {error}")

    if result.status == "ok":
        return 0
    elif result.status in ("stale", "partial"):
        return 0
    else:
        return 3


def cmd_publish_web(args: argparse.Namespace) -> int:
    """Generate environment_dashboard.json to web data directory."""
    config = _get_config()

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        repo_root = config.repo_root
        output_path = (repo_root / "runtime" / "exports" / "web" / "environment_dashboard.json").resolve()

    # Boundary check: output must remain within the repo root
    try:
        output_path.relative_to(repo_root)
    except ValueError:
        print(
            json.dumps(
                {
                    "error_type": "path_boundary_violation",
                    "message": f"Output path escapes repository root: {output_path}",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    result = publish_web(config, output_path=output_path)

    output: dict[str, Any] = {
        "command": "publish-web",
        "status": result.status,
        "output_path": str(output_path),
        "route_count": result.route_count,
        "warnings": result.warnings,
        "errors": result.errors,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Publish web: {result.status}")
        print(f"  Output: {output_path}")
        print(f"  Routes: {result.route_count}")
        for warning in result.warnings:
            print(f"  WARNING: {warning}")
        for error in result.errors:
            print(f"  ERROR: {error}")

    return 0 if result.status == "ok" else 3


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="weather-api-data",
        description="Multi-source environmental data pipeline for Xuhui district routes.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # config-check
    subparsers.add_parser("config-check", help="Check API keys and configuration availability")

    # dry-run
    subparsers.add_parser("dry-run", help="Validate pipeline flow without calling external APIs")

    # scheduled-refresh
    refresh_parser = subparsers.add_parser("scheduled-refresh", help="Execute tiered data refresh")
    refresh_parser.add_argument(
        "--tier",
        required=True,
        choices=["weather", "hourly", "daily"],
        help="Refresh tier",
    )
    refresh_parser.add_argument("--offline", action="store_true", help="Use last-known-good snapshot")

    # publish-web
    publish_parser = subparsers.add_parser("publish-web", help="Generate environment_dashboard.json")
    publish_parser.add_argument("--output", type=str, default=None, help="Output file path")

    args = parser.parse_args()

    handlers = {
        "config-check": cmd_config_check,
        "dry-run": cmd_dry_run,
        "scheduled-refresh": cmd_scheduled_refresh,
        "publish-web": cmd_publish_web,
    }

    handler = handlers.get(args.command)
    if handler is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(2)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
