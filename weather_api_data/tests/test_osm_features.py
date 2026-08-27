import json
from pathlib import Path

from weather_api_data.osm_features import (
    extract_segment_features,
    load_spatial_feature_catalog,
)
from weather_api_data.route_segments import RouteSegment


def _segment() -> RouteSegment:
    return RouteSegment(
        segment_id="R1_S0001",
        route_id="R1",
        segment_index=1,
        length_m=100.0,
        coordinates_wgs84=((121.4690, 31.2323), (121.4700, 31.2323)),
        midpoint_wgs84=(121.4695, 31.2323),
        pm25_grid_id=None,
        source_properties={
            "road_names": ["滨江绿道"],
            "tags": ["滨江", "绿道"],
            "turn_count": 2,
            "actual_distance_m": 1000,
            "nearby_pois": [],
            "network_source": "fixture-route-network",
        },
    )


def _write_catalog(path: Path) -> None:
    features = [
        {
            "type": "Feature",
            "properties": {
                "feature_type": "road",
                "road_class": "primary",
                "source_id": "osm:way/road-1",
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[121.4688, 31.2323], [121.4702, 31.2323]],
            },
        },
        {
            "type": "Feature",
            "properties": {"feature_type": "railway", "source_id": "osm:way/rail-1"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[121.4695, 31.229], [121.4695, 31.231]],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "feature_type": "poi",
                "poi_category": "commercial",
                "source_id": "osm:node/poi-1",
            },
            "geometry": {"type": "Point", "coordinates": [121.4695, 31.2324]},
        },
        {
            "type": "Feature",
            "properties": {"feature_type": "intersection", "source_id": "osm:node/j-1"},
            "geometry": {"type": "Point", "coordinates": [121.4696, 31.2323]},
        },
        {
            "type": "Feature",
            "properties": {"feature_type": "green", "source_id": "osm:way/green-1"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [121.4690, 31.2322],
                        [121.4696, 31.2322],
                        [121.4696, 31.2325],
                        [121.4690, 31.2325],
                        [121.4690, 31.2322],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {"feature_type": "water", "source_id": "osm:way/water-1"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [121.4696, 31.2322],
                        [121.4701, 31.2322],
                        [121.4701, 31.2325],
                        [121.4696, 31.2325],
                        [121.4696, 31.2322],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "feature_type": "acoustic_zone",
                "zone_class": "2",
                "source_id": "shanghai-acoustic:zone-2",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [121.468, 31.231],
                        [121.471, 31.231],
                        [121.471, 31.234],
                        [121.468, 31.234],
                        [121.468, 31.231],
                    ]
                ],
            },
        },
    ]
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def test_catalog_features_are_measured_in_projected_crs(tmp_path: Path) -> None:
    catalog_path = tmp_path / "features.geojson"
    _write_catalog(catalog_path)

    catalog = load_spatial_feature_catalog(catalog_path)
    features = extract_segment_features(_segment(), catalog)

    assert features.status == "ok"
    assert features.completeness == 1.0
    assert features.road_class_score == 0.8
    assert features.distance_pressure_score is not None
    assert features.poi_pressure_score is not None
    assert features.intersection_pressure_score is not None
    assert features.acoustic_zone_score == 0.4
    assert features.green_water_mitigation is not None
    assert "osm:way/road-1" in features.source_ids
    assert "shanghai-acoustic:zone-2" in features.source_ids


def test_missing_catalog_uses_traceable_route_metadata_as_partial_baseline() -> None:
    features = extract_segment_features(_segment(), None)

    assert features.status == "partial"
    assert features.completeness < 1.0
    assert features.road_class_score is not None
    assert features.intersection_pressure_score is not None
    assert features.green_water_mitigation is not None
    assert features.distance_pressure_score is None
    assert features.acoustic_zone_score is None
    assert "fixture-route-network" in features.source_ids
