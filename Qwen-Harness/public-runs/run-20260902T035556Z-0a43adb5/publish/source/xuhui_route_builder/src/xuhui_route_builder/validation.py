"""Route validation module for xuhui_route_builder.

Validates route catalog and GeoJSON data against the 90-route contract:
- Total count: 90 routes
- Mode distribution: walk/run/bike each 30
- route_id consistency between catalog and GeoJSON
- Coordinate validity (reasonable lat/lon range for Shanghai Xuhui)
- validation_status and geometry_status fields
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Expected contract constants
EXPECTED_TOTAL_ROUTES = 90
EXPECTED_MODES = {"walk": 30, "run": 30, "bike": 30}
REQUIRED_CATALOG_FIELDS = [
    "route_id",
    "route_name",
    "route_mode",
    "validation_status",
    "geometry_status",
]
VALID_MODES = {"walk", "run", "bike"}
VALID_VALIDATION_STATUSES = {"accepted", "needs_review", "rejected"}
VALID_GEOMETRY_STATUSES = {"valid", "needs_review", "invalid"}

# Shanghai Xuhui approximate bounding box (WGS84)
XUHUI_LON_MIN = 121.35
XUHUI_LON_MAX = 121.55
XUHUI_LAT_MIN = 31.10
XUHUI_LAT_MAX = 31.25


@dataclass
class ValidationIssue:
    """A single validation issue."""

    level: str  # "error" or "warning"
    code: str
    message: str
    route_id: str | None = None


@dataclass
class ValidationResult:
    """Aggregated validation result."""

    status: str  # "pass", "fail", "error"
    total_routes: int = 0
    mode_distribution: dict[str, int] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)
    catalog_route_ids: list[str] = field(default_factory=list)
    geojson_route_ids: list[str] = field(default_factory=list)
    id_consistent: bool = True

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_routes": self.total_routes,
            "mode_distribution": self.mode_distribution,
            "id_consistent": self.id_consistent,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {
                    "level": i.level,
                    "code": i.code,
                    "message": i.message,
                    "route_id": i.route_id,
                }
                for i in self.issues
            ],
        }


def load_json_file(path: Path) -> Any:
    """Load and parse a JSON file, raising clear error on failure."""
    if not path.exists():
        raise FileNotFoundError(f"Required data file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error in {path}: {e}") from e


def validate_catalog_structure(catalog: list[dict[str, Any]]) -> list[ValidationIssue]:
    """Validate the route catalog array structure and fields."""
    issues: list[ValidationIssue] = []

    if not isinstance(catalog, list):
        issues.append(
            ValidationIssue(
                level="error",
                code="CATALOG_NOT_LIST",
                message=f"route_catalog.json top-level must be an array, got {type(catalog).__name__}",
            )
        )
        return issues

    # Check total count
    if len(catalog) != EXPECTED_TOTAL_ROUTES:
        issues.append(
            ValidationIssue(
                level="error",
                code="ROUTE_COUNT_MISMATCH",
                message=f"Expected {EXPECTED_TOTAL_ROUTES} routes, got {len(catalog)}",
            )
        )

    # Check each entry
    seen_ids: set[str] = set()
    mode_counts: dict[str, int] = {}

    for idx, entry in enumerate(catalog):
        if not isinstance(entry, dict):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="ENTRY_NOT_DICT",
                    message=f"Catalog entry at index {idx} is not a dict",
                )
            )
            continue

        route_id = entry.get("route_id")

        # Check required fields
        for fld in REQUIRED_CATALOG_FIELDS:
            if fld not in entry:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="MISSING_FIELD",
                        message=f"Missing required field '{fld}'",
                        route_id=route_id,
                    )
                )

        # Check duplicate route_id
        if route_id is not None:
            if route_id in seen_ids:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="DUPLICATE_ROUTE_ID",
                        message=f"Duplicate route_id: {route_id}",
                        route_id=route_id,
                    )
                )
            seen_ids.add(route_id)

        # Check route_mode
        mode = entry.get("route_mode")
        if mode is not None:
            if mode not in VALID_MODES:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="INVALID_MODE",
                        message=f"Invalid route_mode '{mode}', expected one of {VALID_MODES}",
                        route_id=route_id,
                    )
                )
            else:
                mode_counts[mode] = mode_counts.get(mode, 0) + 1

        # Check validation_status
        vs = entry.get("validation_status")
        if vs is not None and vs not in VALID_VALIDATION_STATUSES:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="INVALID_VALIDATION_STATUS",
                    message=f"Unexpected validation_status '{vs}'",
                    route_id=route_id,
                )
            )

        # Check geometry_status
        gs = entry.get("geometry_status")
        if gs is not None and gs not in VALID_GEOMETRY_STATUSES:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="INVALID_GEOMETRY_STATUS",
                    message=f"Unexpected geometry_status '{gs}'",
                    route_id=route_id,
                )
            )

    # Check mode distribution
    for expected_mode, expected_count in EXPECTED_MODES.items():
        actual = mode_counts.get(expected_mode, 0)
        if actual != expected_count:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="MODE_COUNT_MISMATCH",
                    message=f"Mode '{expected_mode}': expected {expected_count}, got {actual}",
                )
            )

    return issues


def validate_geojson_structure(geojson: dict[str, Any]) -> list[ValidationIssue]:
    """Validate the GeoJSON FeatureCollection structure."""
    issues: list[ValidationIssue] = []

    if not isinstance(geojson, dict):
        issues.append(
            ValidationIssue(
                level="error",
                code="GEOJSON_NOT_DICT",
                message=f"GeoJSON top-level must be an object, got {type(geojson).__name__}",
            )
        )
        return issues

    if geojson.get("type") != "FeatureCollection":
        issues.append(
            ValidationIssue(
                level="error",
                code="NOT_FEATURE_COLLECTION",
                message=f"GeoJSON type must be 'FeatureCollection', got '{geojson.get('type')}'",
            )
        )
        return issues

    features = geojson.get("features")
    if not isinstance(features, list):
        issues.append(
            ValidationIssue(
                level="error",
                code="FEATURES_NOT_LIST",
                message="GeoJSON 'features' must be an array",
            )
        )
        return issues

    if len(features) != EXPECTED_TOTAL_ROUTES:
        issues.append(
            ValidationIssue(
                level="error",
                code="FEATURE_COUNT_MISMATCH",
                message=f"Expected {EXPECTED_TOTAL_ROUTES} features, got {len(features)}",
            )
        )

    for idx, feature in enumerate(features):
        if not isinstance(feature, dict):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="FEATURE_NOT_DICT",
                    message=f"Feature at index {idx} is not a dict",
                )
            )
            continue

        route_id = feature.get("properties", {}).get("route_id")

        # Check geometry
        geometry = feature.get("geometry")
        if geometry is None:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="MISSING_GEOMETRY",
                    message="Feature has no geometry",
                    route_id=route_id,
                )
            )
            continue

        geom_type = geometry.get("type")
        if geom_type != "LineString":
            issues.append(
                ValidationIssue(
                    level="error",
                    code="INVALID_GEOMETRY_TYPE",
                    message=f"Expected geometry type 'LineString', got '{geom_type}'",
                    route_id=route_id,
                )
            )
            continue

        coordinates = geometry.get("coordinates")
        if not coordinates or not isinstance(coordinates, list):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="EMPTY_COORDINATES",
                    message="LineString coordinates are empty or not a list",
                    route_id=route_id,
                )
            )
            continue

        # Validate coordinate bounds
        for coord_idx, coord in enumerate(coordinates):
            if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="INVALID_COORDINATE",
                        message=f"Coordinate at index {coord_idx} is malformed: {coord}",
                        route_id=route_id,
                    )
                )
                break
            lon, lat = coord[0], coord[1]
            if not (XUHUI_LON_MIN <= lon <= XUHUI_LON_MAX):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="COORDINATE_OUT_OF_BOUNDS",
                        message=f"Longitude {lon} outside Xuhui range [{XUHUI_LON_MIN}, {XUHUI_LON_MAX}]",
                        route_id=route_id,
                    )
                )
                break
            if not (XUHUI_LAT_MIN <= lat <= XUHUI_LAT_MAX):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="COORDINATE_OUT_OF_BOUNDS",
                        message=f"Latitude {lat} outside Xuhui range [{XUHUI_LAT_MIN}, {XUHUI_LAT_MAX}]",
                        route_id=route_id,
                    )
                )
                break

    return issues


def validate_id_consistency(
    catalog: list[dict[str, Any]], geojson: dict[str, Any]
) -> tuple[bool, list[ValidationIssue]]:
    """Check that route_ids in catalog and GeoJSON are consistent."""
    issues: list[ValidationIssue] = []

    catalog_ids = set()
    for entry in catalog:
        if isinstance(entry, dict) and "route_id" in entry:
            catalog_ids.add(entry["route_id"])

    geojson_ids = set()
    features = geojson.get("features", []) if isinstance(geojson, dict) else []
    for feature in features:
        if isinstance(feature, dict):
            props = feature.get("properties", {})
            if isinstance(props, dict) and "route_id" in props:
                geojson_ids.add(props["route_id"])

    only_in_catalog = catalog_ids - geojson_ids
    only_in_geojson = geojson_ids - catalog_ids

    if only_in_catalog:
        issues.append(
            ValidationIssue(
                level="error",
                code="ID_ONLY_IN_CATALOG",
                message=f"route_ids in catalog but not in GeoJSON: {sorted(only_in_catalog)}",
            )
        )

    if only_in_geojson:
        issues.append(
            ValidationIssue(
                level="error",
                code="ID_ONLY_IN_GEOJSON",
                message=f"route_ids in GeoJSON but not in catalog: {sorted(only_in_geojson)}",
            )
        )

    consistent = len(only_in_catalog) == 0 and len(only_in_geojson) == 0
    return consistent, issues


def validate_seeds(data_dir: Path) -> ValidationResult:
    """Run full seed validation on the data directory.

    Checks:
    - route_catalog.json structure, count, mode distribution
    - xuhui_routes.geojson structure, geometry, coordinates
    - route_id consistency between catalog and GeoJSON

    Returns a ValidationResult with status 'pass', 'fail', or 'error'.
    """
    catalog_path = data_dir / "route_catalog.json"
    geojson_path = data_dir / "xuhui_routes.geojson"

    all_issues: list[ValidationIssue] = []

    # Load catalog
    try:
        catalog = load_json_file(catalog_path)
    except (FileNotFoundError, ValueError) as e:
        return ValidationResult(
            status="error",
            issues=[
                ValidationIssue(
                    level="error",
                    code="FILE_LOAD_ERROR",
                    message=str(e),
                )
            ],
        )

    # Load GeoJSON
    try:
        geojson = load_json_file(geojson_path)
    except (FileNotFoundError, ValueError) as e:
        return ValidationResult(
            status="error",
            issues=[
                ValidationIssue(
                    level="error",
                    code="FILE_LOAD_ERROR",
                    message=str(e),
                )
            ],
        )

    # Validate catalog
    catalog_issues = validate_catalog_structure(catalog)
    all_issues.extend(catalog_issues)

    # Validate GeoJSON
    geojson_issues = validate_geojson_structure(geojson)
    all_issues.extend(geojson_issues)

    # Validate ID consistency
    id_consistent, id_issues = validate_id_consistency(catalog, geojson)
    all_issues.extend(id_issues)

    # Compute mode distribution
    mode_distribution: dict[str, int] = {}
    if isinstance(catalog, list):
        for entry in catalog:
            if isinstance(entry, dict):
                mode = entry.get("route_mode")
                if mode in VALID_MODES:
                    mode_distribution[mode] = mode_distribution.get(mode, 0) + 1

    # Determine overall status
    has_errors = any(i.level == "error" for i in all_issues)
    status = "fail" if has_errors else "pass"

    # Extract route IDs for reporting
    catalog_route_ids: list[str] = []
    if isinstance(catalog, list):
        catalog_route_ids = [
            e.get("route_id", "") for e in catalog if isinstance(e, dict)
        ]

    geojson_route_ids: list[str] = []
    if isinstance(geojson, dict):
        for feature in geojson.get("features", []):
            if isinstance(feature, dict):
                props = feature.get("properties", {})
                if isinstance(props, dict) and "route_id" in props:
                    geojson_route_ids.append(props["route_id"])

    return ValidationResult(
        status=status,
        total_routes=len(catalog) if isinstance(catalog, list) else 0,
        mode_distribution=mode_distribution,
        issues=all_issues,
        catalog_route_ids=catalog_route_ids,
        geojson_route_ids=geojson_route_ids,
        id_consistent=id_consistent,
    )


def validate_routes_online(data_dir: Path) -> ValidationResult:
    """Validate routes with online verification (requires network).

    In v1, this performs the same local validation as validate_seeds
    and marks online checks as skipped if network is not available.
    """
    # For v1, online validation delegates to local validation
    # with a note that online checks are skipped
    result = validate_seeds(data_dir)
    result.issues.append(
        ValidationIssue(
            level="warning",
            code="ONLINE_CHECK_SKIPPED",
            message="Online route verification skipped in v1 (requires network authorization)",
        )
    )
    return result
