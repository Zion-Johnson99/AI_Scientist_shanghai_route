"""Data loaders for route catalog and environment dashboard.

Provides load_data() which reads route_catalog.json and
environment_dashboard.json, validates structure, and returns
typed objects for downstream scoring.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evaluation_model_qwen.models import (
    EnvironmentRecord,
    EnvironmentDashboard,
    RouteEntry,
)

logger = logging.getLogger(__name__)


class DataLoadError(Exception):
    """Raised when required data files are missing or unparseable."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class DataValidationError(Exception):
    """Raised when data structure does not meet contract requirements."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        self.details = details or []
        super().__init__(message)


def _read_json(path: Path) -> Any:
    """Read and parse a JSON file, raising DataLoadError on failure."""
    if not path.exists():
        raise DataLoadError(f"Required data file not found: {path}", path=str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataLoadError(
            f"Cannot read data file: {path} ({exc})", path=str(path)
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataLoadError(
            f"Invalid JSON in data file: {path} ({exc})", path=str(path)
        ) from exc


def load_route_catalog(catalog_path: Path) -> list[RouteEntry]:
    """Load and validate route_catalog.json.

    Contract:
    - Top-level is a JSON array of 90 items.
    - Each item has route_id, route_name, route_mode, validation_status,
      geometry_status.
    - walk/run/bike each have 30 routes.

    Returns:
        List of validated RouteEntry objects.

    Raises:
        DataLoadError: File missing or unparseable.
        DataValidationError: Structure does not meet contract.
    """
    raw = _read_json(catalog_path)

    if not isinstance(raw, list):
        raise DataValidationError(
            f"route_catalog.json top-level must be an array, got {type(raw).__name__}"
        )

    if len(raw) != 90:
        logger.warning(
            "route_catalog.json contains %d items, expected 90", len(raw)
        )

    entries: list[RouteEntry] = []
    errors: list[str] = []

    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"Item at index {idx} is not an object")
            continue
        try:
            entry = RouteEntry.model_validate(item)
            entries.append(entry)
        except ValidationError as exc:
            errors.append(f"Item at index {idx}: {exc.error_count()} validation error(s)")
            # Log first error detail for debugging
            for err in exc.errors()[:3]:
                field = ".".join(str(loc) for loc in err["loc"])
                logger.warning(
                    "route_catalog item %d field '%s': %s",
                    idx,
                    field,
                    err["msg"],
                )

    if errors:
        raise DataValidationError(
            f"route_catalog.json has {len(errors)} invalid item(s)",
            details=errors[:10],
        )

    # Check mode distribution
    mode_counts: dict[str, int] = {}
    for entry in entries:
        mode_counts[entry.route_mode] = mode_counts.get(entry.route_mode, 0) + 1

    for mode in ("walk", "run", "bike"):
        count = mode_counts.get(mode, 0)
        if count != 30:
            logger.warning(
                "Mode '%s' has %d routes, expected 30", mode, count
            )

    # Check for duplicate route_ids
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for entry in entries:
        if entry.route_id in seen_ids:
            duplicates.append(entry.route_id)
        seen_ids.add(entry.route_id)

    if duplicates:
        raise DataValidationError(
            f"route_catalog.json contains {len(duplicates)} duplicate route_id(s)",
            details=duplicates[:10],
        )

    logger.info(
        "Loaded %d routes from %s (modes: %s)",
        len(entries),
        catalog_path.name,
        mode_counts,
    )
    return entries


def load_environment_dashboard(dashboard_path: Path) -> EnvironmentDashboard:
    """Load and validate environment_dashboard.json.

    Contract:
    - Top-level keys: metadata, current, forecast, routes.
    - routes.items is a list of 90 items.
    - Each item has route_id, pm2_5, noise, pollen_daily.

    Returns:
        Validated EnvironmentDashboard object.

    Raises:
        DataLoadError: File missing or unparseable.
        DataValidationError: Structure does not meet contract.
    """
    raw = _read_json(dashboard_path)

    if not isinstance(raw, dict):
        raise DataValidationError(
            f"environment_dashboard.json top-level must be an object, "
            f"got {type(raw).__name__}"
        )

    required_keys = {"metadata", "current", "forecast", "routes"}
    missing_keys = required_keys - set(raw.keys())
    if missing_keys:
        raise DataValidationError(
            f"environment_dashboard.json missing required top-level keys: "
            f"{sorted(missing_keys)}"
        )

    # Validate routes section
    routes_section = raw.get("routes", {})
    if not isinstance(routes_section, dict):
        raise DataValidationError(
            "environment_dashboard.json 'routes' must be an object"
        )

    items = routes_section.get("items", [])
    if not isinstance(items, list):
        raise DataValidationError(
            "environment_dashboard.json 'routes.items' must be an array"
        )

    if len(items) != 90:
        logger.warning(
            "environment_dashboard.json routes.items has %d items, expected 90",
            len(items),
        )

    # Validate each route environment record
    env_records: list[EnvironmentRecord] = []
    errors: list[str] = []

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"routes.items[{idx}] is not an object")
            continue
        try:
            record = EnvironmentRecord.model_validate(item)
            env_records.append(record)
        except ValidationError as exc:
            errors.append(
                f"routes.items[{idx}]: {exc.error_count()} validation error(s)"
            )
            for err in exc.errors()[:3]:
                field = ".".join(str(loc) for loc in err["loc"])
                logger.warning(
                    "environment_dashboard routes.items[%d] field '%s': %s",
                    idx,
                    field,
                    err["msg"],
                )

    if errors:
        raise DataValidationError(
            f"environment_dashboard.json has {len(errors)} invalid route record(s)",
            details=errors[:10],
        )

    dashboard = EnvironmentDashboard(
        metadata=raw["metadata"],
        current=raw["current"],
        forecast=raw["forecast"],
        routes=routes_section,
        route_records=env_records,
    )

    logger.info(
        "Loaded environment dashboard with %d route records from %s",
        len(env_records),
        dashboard_path.name,
    )
    return dashboard


def load_data(
    route_catalog_path: Path | str,
    environment_dashboard_path: Path | str,
) -> tuple[list[RouteEntry], EnvironmentDashboard]:
    """Load both route catalog and environment dashboard.

    This is the primary entry point used by scoring and service layers.

    Args:
        route_catalog_path: Path to route_catalog.json.
        environment_dashboard_path: Path to environment_dashboard.json.

    Returns:
        Tuple of (route_entries, environment_dashboard).

    Raises:
        DataLoadError: Any required file is missing or unparseable.
        DataValidationError: Data structure violates contract.
    """
    catalog_path = Path(route_catalog_path)
    dashboard_path = Path(environment_dashboard_path)

    routes = load_route_catalog(catalog_path)
    dashboard = load_environment_dashboard(dashboard_path)

    # Cross-check: route_ids in environment should match catalog
    catalog_ids = {r.route_id for r in routes}
    env_ids = {r.route_id for r in dashboard.route_records}

    missing_in_env = catalog_ids - env_ids
    if missing_in_env:
        logger.warning(
            "%d route(s) in catalog have no environment data: %s",
            len(missing_in_env),
            sorted(missing_in_env)[:5],
        )

    extra_in_env = env_ids - catalog_ids
    if extra_in_env:
        logger.warning(
            "%d route(s) in environment dashboard not in catalog: %s",
            len(extra_in_env),
            sorted(extra_in_env)[:5],
        )

    return routes, dashboard
