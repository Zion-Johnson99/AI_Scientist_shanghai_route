"""Route data models for xuhui_route_builder.

Defines RouteEntry, RouteCatalog, and GeoJSON Feature structures
used across the route module for data generation, validation, and export.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RouteMode(str, Enum):
    """Supported route modes."""

    WALK = "walk"
    RUN = "run"
    BIKE = "bike"


class ValidationStatus(str, Enum):
    """Validation status of a route."""

    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class GeometryStatus(str, Enum):
    """Geometry validation status."""

    VALID = "valid"
    SIMPLIFIED = "simplified"
    INVALID = "invalid"


class RouteEntry(BaseModel):
    """A single route entry in the route catalog.

    Each entry represents one route with metadata for identification,
    classification, and validation state.
    """

    route_id: str = Field(..., description="Unique route identifier")
    route_name: str = Field(..., description="Human-readable route name")
    route_mode: RouteMode = Field(..., description="Route mode: walk, run, or bike")
    validation_status: ValidationStatus = Field(
        default=ValidationStatus.ACCEPTED,
        description="Validation status of the route",
    )
    geometry_status: GeometryStatus = Field(
        default=GeometryStatus.VALID,
        description="Geometry validation status",
    )
    distance_m: float = Field(..., ge=0, description="Route distance in meters")
    distance_band: str = Field(default="", description="Distance band label")
    description: str = Field(default="", description="Route description")
    start_point: str = Field(default="", description="Start point description")
    end_point: str = Field(default="", description="End point description")
    tags: list[str] = Field(default_factory=list, description="Route tags")

    @field_validator("route_id")
    @classmethod
    def route_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("route_id must not be empty")
        return v

    @field_validator("route_name")
    @classmethod
    def route_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("route_name must not be empty")
        return v

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouteEntry:
        """Deserialize from dictionary."""
        return cls.model_validate(data)


class RouteCatalog(BaseModel):
    """Collection of route entries forming the complete catalog.

    Enforces the 90-route contract: 30 walk, 30 run, 30 bike.
    """

    routes: list[RouteEntry] = Field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.routes)

    @property
    def mode_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {"walk": 0, "run": 0, "bike": 0}
        for route in self.routes:
            dist[route.route_mode.value] += 1
        return dist

    @property
    def route_ids(self) -> list[str]:
        return [r.route_id for r in self.routes]

    def get_by_mode(self, mode: RouteMode) -> list[RouteEntry]:
        return [r for r in self.routes if r.route_mode == mode]

    def get_by_id(self, route_id: str) -> RouteEntry | None:
        for route in self.routes:
            if route.route_id == route_id:
                return route
        return None

    def validate_contract(self) -> list[str]:
        """Validate the 90-route contract. Returns list of violations."""
        violations: list[str] = []

        if self.total_count != 90:
            violations.append(
                f"Expected 90 routes, got {self.total_count}"
            )

        dist = self.mode_distribution
        for mode_name, expected_count in [("walk", 30), ("run", 30), ("bike", 30)]:
            actual = dist.get(mode_name, 0)
            if actual != expected_count:
                violations.append(
                    f"Expected {expected_count} {mode_name} routes, got {actual}"
                )

        ids = self.route_ids
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for rid in ids:
                if rid in seen:
                    duplicates.add(rid)
                seen.add(rid)
            violations.append(f"Duplicate route_ids: {sorted(duplicates)}")

        for route in self.routes:
            if route.validation_status != ValidationStatus.ACCEPTED:
                violations.append(
                    f"Route {route.route_id} has validation_status "
                    f"{route.validation_status.value}, expected accepted"
                )

        return violations

    def to_json(self, indent: int = 2) -> str:
        """Serialize catalog to JSON string (top-level array)."""
        return json.dumps(
            [route.to_dict() for route in self.routes],
            ensure_ascii=False,
            indent=indent,
        )

    @classmethod
    def from_json(cls, json_str: str) -> RouteCatalog:
        """Deserialize catalog from JSON string (top-level array)."""
        data = json.loads(json_str)
        if not isinstance(data, list):
            raise ValueError("route_catalog.json must be a top-level array")
        routes = [RouteEntry.from_dict(item) for item in data]
        return cls(routes=routes)

    @classmethod
    def from_file(cls, path: Path | str) -> RouteCatalog:
        """Load catalog from a JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Route catalog not found: {path}")
        return cls.from_json(path.read_text(encoding="utf-8"))

    def to_file(self, path: Path | str, indent: int = 2) -> None:
        """Write catalog to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(indent=indent), encoding="utf-8")


class GeoJSONGeometry(BaseModel):
    """GeoJSON geometry for a route (LineString)."""

    type: str = Field(default="LineString")
    coordinates: list[list[float]] = Field(
        default_factory=list,
        description="List of [longitude, latitude] coordinate pairs",
    )

    @field_validator("type")
    @classmethod
    def must_be_linestring(cls, v: str) -> str:
        if v != "LineString":
            raise ValueError(f"Expected LineString, got {v}")
        return v

    @field_validator("coordinates")
    @classmethod
    def coordinates_not_empty(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 2:
            raise ValueError("LineString must have at least 2 coordinates")
        return v


class GeoJSONProperties(BaseModel):
    """Properties attached to a GeoJSON route feature."""

    route_id: str
    route_name: str = ""
    route_mode: str = ""
    distance_m: float = 0.0
    validation_status: str = ""


class GeoJSONFeature(BaseModel):
    """A single GeoJSON Feature representing a route."""

    type: str = Field(default="Feature")
    geometry: GeoJSONGeometry
    properties: GeoJSONProperties

    @field_validator("type")
    @classmethod
    def must_be_feature(cls, v: str) -> str:
        if v != "Feature":
            raise ValueError(f"Expected Feature, got {v}")
        return v


class GeoJSONFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection containing route features."""

    type: str = Field(default="FeatureCollection")
    features: list[GeoJSONFeature] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def must_be_feature_collection(cls, v: str) -> str:
        if v != "FeatureCollection":
            raise ValueError(f"Expected FeatureCollection, got {v}")
        return v

    @property
    def route_ids(self) -> list[str]:
        return [f.properties.route_id for f in self.features]

    def validate_against_catalog(self, catalog: RouteCatalog) -> list[str]:
        """Check consistency between GeoJSON and catalog. Returns violations."""
        violations: list[str] = []

        if len(self.features) != catalog.total_count:
            violations.append(
                f"GeoJSON has {len(self.features)} features, "
                f"catalog has {catalog.total_count} routes"
            )

        geojson_ids = set(self.route_ids)
        catalog_ids = set(catalog.route_ids)

        missing_in_geojson = catalog_ids - geojson_ids
        if missing_in_geojson:
            violations.append(
                f"route_ids in catalog but not in GeoJSON: {sorted(missing_in_geojson)}"
            )

        extra_in_geojson = geojson_ids - catalog_ids
        if extra_in_geojson:
            violations.append(
                f"route_ids in GeoJSON but not in catalog: {sorted(extra_in_geojson)}"
            )

        return violations

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> GeoJSONFeatureCollection:
        """Deserialize from JSON string."""
        return cls.model_validate_json(json_str)

    @classmethod
    def from_file(cls, path: Path | str) -> GeoJSONFeatureCollection:
        """Load from a GeoJSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"GeoJSON file not found: {path}")
        return cls.from_json(path.read_text(encoding="utf-8"))

    def to_file(self, path: Path | str, indent: int = 2) -> None:
        """Write to a GeoJSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(indent=indent), encoding="utf-8")

    @classmethod
    def from_catalog_and_coordinates(
        cls,
        catalog: RouteCatalog,
        coordinates_map: dict[str, list[list[float]]],
    ) -> GeoJSONFeatureCollection:
        """Build a FeatureCollection from catalog entries and coordinate data.

        Args:
            catalog: The route catalog.
            coordinates_map: Mapping of route_id to coordinate list.

        Returns:
            A GeoJSONFeatureCollection with one feature per route.

        Raises:
            ValueError: If a route_id in catalog has no coordinates.
        """
        features: list[GeoJSONFeature] = []
        for route in catalog.routes:
            coords = coordinates_map.get(route.route_id)
            if coords is None:
                raise ValueError(
                    f"No coordinates provided for route_id: {route.route_id}"
                )
            feature = GeoJSONFeature(
                geometry=GeoJSONGeometry(coordinates=coords),
                properties=GeoJSONProperties(
                    route_id=route.route_id,
                    route_name=route.route_name,
                    route_mode=route.route_mode.value,
                    distance_m=route.distance_m,
                    validation_status=route.validation_status.value,
                ),
            )
            features.append(feature)
        return cls(features=features)
