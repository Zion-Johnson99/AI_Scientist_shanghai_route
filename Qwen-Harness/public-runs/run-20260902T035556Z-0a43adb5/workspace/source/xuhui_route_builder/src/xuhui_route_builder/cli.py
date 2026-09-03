"""CLI for xuhui_route_builder: validate-seeds, validate-routes, export-candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xuhui_route_builder.validation import (
    validate_catalog,
    validate_geojson,
    validate_mode_distribution,
    validate_route_id_consistency,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "web"


def _resolve_data_dir(data_dir: str | None) -> Path:
    """Resolve the data directory, defaulting to the bundled data/web."""
    if data_dir:
        return Path(data_dir)
    return DATA_DIR


def cmd_validate_seeds(args: argparse.Namespace) -> int:
    """Validate seed data files: catalog structure, mode distribution, IDs."""
    data_dir = _resolve_data_dir(args.data_dir)
    catalog_path = data_dir / "route_catalog.json"
    geojson_path = data_dir / "xuhui_routes.geojson"

    errors: list[str] = []
    warnings: list[str] = []

    # Check file existence
    if not catalog_path.exists():
        errors.append(f"route_catalog.json not found at {catalog_path}")
    if not geojson_path.exists():
        errors.append(f"xuhui_routes.geojson not found at {geojson_path}")

    if errors:
        _print_result("error", errors, warnings, data_dir)
        return 1

    # Load and validate catalog
    try:
        with open(catalog_path, encoding="utf-8") as f:
            catalog = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Failed to parse route_catalog.json: {exc}")
        _print_result("error", errors, warnings, data_dir)
        return 1

    catalog_errors = validate_catalog(catalog)
    errors.extend(catalog_errors)

    # Validate mode distribution
    mode_errors = validate_mode_distribution(catalog)
    errors.extend(mode_errors)

    # Load and validate GeoJSON
    try:
        with open(geojson_path, encoding="utf-8") as f:
            geojson = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Failed to parse xuhui_routes.geojson: {exc}")
        _print_result("error", errors, warnings, data_dir)
        return 1

    geojson_errors = validate_geojson(geojson)
    errors.extend(geojson_errors)

    # Validate route_id consistency between catalog and GeoJSON
    if not catalog_errors and not geojson_errors:
        consistency_errors = validate_route_id_consistency(catalog, geojson)
        errors.extend(consistency_errors)

    status = "pass" if not errors else "fail"
    _print_result(status, errors, warnings, data_dir)
    return 0 if not errors else 1


def cmd_validate_routes(args: argparse.Namespace) -> int:
    """Validate routes with optional network access for online verification."""
    data_dir = _resolve_data_dir(args.data_dir)

    if args.online and not args.allow_network:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "Online validation requires network authorization. "
                    "Use --allow-network to enable.",
                    "data_dir": str(data_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    # Offline validation: same as validate-seeds plus geometry checks
    catalog_path = data_dir / "route_catalog.json"
    geojson_path = data_dir / "xuhui_routes.geojson"

    errors: list[str] = []
    warnings: list[str] = []

    if not catalog_path.exists():
        errors.append(f"route_catalog.json not found at {catalog_path}")
    if not geojson_path.exists():
        errors.append(f"xuhui_routes.geojson not found at {geojson_path}")

    if errors:
        _print_result("error", errors, warnings, data_dir)
        return 1

    try:
        with open(catalog_path, encoding="utf-8") as f:
            catalog = json.load(f)
        with open(geojson_path, encoding="utf-8") as f:
            geojson = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Failed to parse data files: {exc}")
        _print_result("error", errors, warnings, data_dir)
        return 1

    # Basic structural validation
    errors.extend(validate_catalog(catalog))
    errors.extend(validate_mode_distribution(catalog))
    errors.extend(validate_geojson(geojson))

    if not errors:
        errors.extend(validate_route_id_consistency(catalog, geojson))

    # Geometry coordinate bounds check (Shanghai area approximate bounds)
    # Longitude: 120.8 - 122.2, Latitude: 30.7 - 31.9
    if not errors:
        features = geojson.get("features", [])
        for i, feature in enumerate(features):
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            route_id = feature.get("properties", {}).get("route_id", f"feature_{i}")
            for coord in coords:
                if len(coord) >= 2:
                    lon, lat = coord[0], coord[1]
                    if not (120.8 <= lon <= 122.2):
                        warnings.append(
                            f"Route {route_id}: longitude {lon} outside "
                            f"expected Shanghai bounds [120.8, 122.2]"
                        )
                    if not (30.7 <= lat <= 31.9):
                        warnings.append(
                            f"Route {route_id}: latitude {lat} outside "
                            f"expected Shanghai bounds [30.7, 31.9]"
                        )

    if args.online:
        warnings.append(
            "Online validation requested but no external service configured "
            "in this version. Structural validation only."
        )

    status = "pass" if not errors else "fail"
    _print_result(status, errors, warnings, data_dir)
    return 0 if not errors else 1


def cmd_export_candidates(args: argparse.Namespace) -> int:
    """Export candidates - disabled in v1."""
    print(
        json.dumps(
            {
                "status": "disabled",
                "command": "export-candidates",
                "reason": "export-candidates is disabled in v1. "
                "This operation requires explicit workflow authorization "
                "and is not available via CLI.",
                "suggestion": "Use the Harness workflow engine with "
                "appropriate operation authorization.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2


def _print_result(
    status: str,
    errors: list[str],
    warnings: list[str],
    data_dir: Path,
) -> None:
    """Print structured validation result as JSON."""
    result = {
        "status": status,
        "data_dir": str(data_dir),
        "error_count": len(errors),
        "warning_count": len(warnings),
    }
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for xuhui-route-builder CLI."""
    parser = argparse.ArgumentParser(
        prog="xuhui-route-builder",
        description="Xuhui Route Builder: route data validation and management",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # validate-seeds
    seeds_parser = subparsers.add_parser(
        "validate-seeds",
        help="Validate seed data files (catalog, GeoJSON, mode distribution)",
    )
    seeds_parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to data directory (default: bundled data/web)",
    )

    # validate-routes
    routes_parser = subparsers.add_parser(
        "validate-routes",
        help="Validate routes with optional online verification",
    )
    routes_parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to data directory (default: bundled data/web)",
    )
    routes_parser.add_argument(
        "--online",
        action="store_true",
        default=False,
        help="Enable online verification (requires --allow-network)",
    )
    routes_parser.add_argument(
        "--allow-network",
        action="store_true",
        default=False,
        help="Authorize network access for online verification",
    )

    # export-candidates
    subparsers.add_parser(
        "export-candidates",
        help="Export route candidates (disabled in v1)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "validate-seeds":
        return cmd_validate_seeds(args)
    elif args.command == "validate-routes":
        return cmd_validate_routes(args)
    elif args.command == "export-candidates":
        return cmd_export_candidates(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
