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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather_api_data.pipeline import (
    PipelineConfig,
    PipelineResult,
    check_api_keys,
    run_pipeline,
    save_snapshot,
)
from weather_api_data.route_environment import (
    generate_route_environment,
    records_to_dashboard_items,
)
from weather_api_data.web_export import publish_web


def _get_config() -> PipelineConfig:
    """Build pipeline configuration from environment and defaults."""
    api_keys: dict[str, str] = {}
    weather_key = (
        os.environ.get("WEATHER_API_KEY", "").strip()
        or os.environ.get("OPENWEATHER_API_KEY", "").strip()
    )
    aqi_key = os.environ.get("AQI_API_KEY", "").strip()
    if weather_key:
        api_keys["weather_api"] = weather_key
    if aqi_key:
        api_keys["aqi_api"] = aqi_key

    return PipelineConfig(
        exports_dir=Path("runtime/exports"),
        api_keys=api_keys,
        allow_network=True,
        tier="weather",
    )


def _sanitize(obj: Any) -> Any:
    """Recursively remove keys that look like secrets."""
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            lower_k = k.lower()
            if (
                "key" in lower_k
                or "secret" in lower_k
                or "token" in lower_k
            ):
                continue
            cleaned[k] = _sanitize(v)
        return cleaned
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    return obj


def _emit(output: dict[str, Any], as_json: bool) -> None:
    """Print output, optionally as JSON."""
    if as_json:
        print(json.dumps(_sanitize(output), ensure_ascii=False, indent=2))
    else:
        for k, v in output.items():
            if isinstance(v, list):
                print(f"{k}:")
                for item in v:
                    print(f"  - {item}")
            else:
                print(f"{k}: {v}")


def _resolve_json_flag(args: argparse.Namespace) -> bool:
    """Combine global --json and subcommand --json via logical or."""
    global_json = getattr(args, "global_json", False)
    sub_json = getattr(args, "json", False)
    return bool(global_json or sub_json)


def cmd_config_check(args: argparse.Namespace) -> int:
    """Check API keys and configuration availability."""
    config = _get_config()
    missing: list[str] = check_api_keys(config)

    warnings: list[str] = []
    if missing:
        warnings.append(f"Missing API keys: {', '.join(missing)}")

    output: dict[str, Any] = {
        "command": "config-check",
        "status": "ok",
        "warnings": warnings,
    }

    _emit(output, _resolve_json_flag(args))
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Validate pipeline flow without calling external APIs or writing."""
    config = _get_config()

    steps: list[str] = []
    warnings: list[str] = []

    missing: list[str] = check_api_keys(config)
    if missing:
        warnings.append(
            f"Missing API keys (dry-run continues): {', '.join(missing)}"
        )

    steps.append("config validated")
    steps.append(
        "pipeline stages enumerated: fetch -> transform -> snapshot"
    )
    steps.append(
        "dry-run complete: no files written, no network calls made"
    )

    output: dict[str, Any] = {
        "command": "dry-run",
        "status": "ok",
        "steps": steps,
        "warnings": warnings,
    }

    _emit(output, _resolve_json_flag(args))
    return 0


def cmd_scheduled_refresh(args: argparse.Namespace) -> int:
    """Execute tiered data refresh."""
    valid_tiers = ("weather", "hourly", "daily")
    if args.tier not in valid_tiers:
        print(
            json.dumps(
                {
                    "error_type": "invalid_argument",
                    "message": (
                        f"Invalid tier '{args.tier}'. "
                        f"Must be one of: {', '.join(valid_tiers)}"
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    config = _get_config()
    config = PipelineConfig(
        exports_dir=config.exports_dir,
        api_keys=config.api_keys,
        allow_network=config.allow_network,
        tier=args.tier,
    )

    result: PipelineResult = run_pipeline(config)

    save_snapshot(
        exports_dir=config.exports_dir,
        tier=args.tier,
        data=result.data or {},
        status=result.status,
    )

    output: dict[str, Any] = {
        "command": "scheduled-refresh",
        "status": result.status,
        "tier": args.tier,
        "stale_reason": result.stale_reason,
        "missing_items": result.missing_items,
    }

    _emit(output, _resolve_json_flag(args))
    return 0


def cmd_publish_web(args: argparse.Namespace) -> int:
    """Generate environment_dashboard.json to web data directory."""
    route_catalog_path = Path(args.route_catalog)
    geojson_path = Path(args.geojson)
    output_path = Path(args.output)

    env_result = generate_route_environment(
        route_catalog_path=route_catalog_path,
        geojson_path=geojson_path,
    )

    items = records_to_dashboard_items(env_result.records)

    status = "ok" if len(items) == 90 else "partial"

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "weather": {
            "temperature_c": None,
            "humidity_pct": None,
            "wind_speed_ms": None,
        },
        "aqi": {"status": "no_data"},
        "routes": items,
    }

    publish_web(payload, output_path)

    output: dict[str, Any] = {
        "command": "publish-web",
        "status": status,
        "route_count": len(items),
        "output_path": str(output_path),
    }

    _emit(output, _resolve_json_flag(args))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="weather-api-data",
        description="Weather and environment data pipeline CLI.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="global_json",
        help="Output results as JSON.",
    )

    subparsers = parser.add_subparsers(dest="command")

    # config-check
    p_check = subparsers.add_parser(
        "config-check",
        help="Check API keys and configuration availability.",
    )
    p_check.add_argument(
        "--json", action="store_true", default=False,
        help="Output results as JSON.",
    )
    p_check.set_defaults(func=cmd_config_check)

    # dry-run
    p_dry = subparsers.add_parser(
        "dry-run",
        help="Validate pipeline flow without calling external APIs.",
    )
    p_dry.add_argument(
        "--json", action="store_true", default=False,
        help="Output results as JSON.",
    )
    p_dry.set_defaults(func=cmd_dry_run)

    # scheduled-refresh
    p_refresh = subparsers.add_parser(
        "scheduled-refresh",
        help="Execute tiered data refresh.",
    )
    p_refresh.add_argument(
        "--tier",
        choices=("weather", "hourly", "daily"),
        default="weather",
        help="Refresh tier (default: weather).",
    )
    p_refresh.add_argument(
        "--json", action="store_true", default=False,
        help="Output results as JSON.",
    )
    p_refresh.set_defaults(func=cmd_scheduled_refresh)

    # publish-web
    p_publish = subparsers.add_parser(
        "publish-web",
        help="Generate environment_dashboard.json to web data directory.",
    )
    p_publish.add_argument(
        "--route-catalog",
        required=True,
        help="Path to route_catalog.json.",
    )
    p_publish.add_argument(
        "--geojson",
        required=True,
        help="Path to xuhui_routes.geojson.",
    )
    p_publish.add_argument(
        "--output",
        required=True,
        help="Output path for environment_dashboard.json.",
    )
    p_publish.add_argument(
        "--json", action="store_true", default=False,
        help="Output results as JSON.",
    )
    p_publish.set_defaults(func=cmd_publish_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    func = args.func
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())
