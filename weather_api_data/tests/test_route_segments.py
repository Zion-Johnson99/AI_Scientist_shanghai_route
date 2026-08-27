import json
from pathlib import Path

import pytest

from weather_api_data import route_segments
from weather_api_data.route_segments import (
    assign_pm25_grids,
    build_route_segments_document,
    load_route_segments,
)


def test_split_route_merges_a_tiny_tail_into_the_previous_segment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def identity(x_value: float, y_value: float) -> tuple[float, float]:
        return x_value, y_value

    monkeypatch.setattr(route_segments, "gcj02_to_wgs84", identity)
    monkeypatch.setattr(route_segments, "wgs84_to_utm51", identity)
    monkeypatch.setattr(route_segments, "utm51_to_wgs84", identity)
    route_path = tmp_path / "tiny_tail.geojson"
    route_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"route_id": "R_TINY_TAIL"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0.0, 0.0], [200.01, 0.0]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    segments = load_route_segments(route_path, target_length_m=100.0)

    assert [segment.length_m for segment in segments] == pytest.approx([100.0, 100.01])
    assert min(segment.length_m for segment in segments) >= 10.0


def _write_routes(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "route_id": "R_LONG",
                            "road_names": ["测试路"],
                            "network_source": "fixture-route-network",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.47, 31.20], [121.47, 31.2025]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"route_id": "R_SHORT"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.48, 31.20], [121.48, 31.2002]],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_routes_are_split_in_epsg32651_with_stable_ids(tmp_path: Path) -> None:
    route_path = tmp_path / "routes.geojson"
    _write_routes(route_path)

    segments = load_route_segments(route_path, target_length_m=100.0)
    long_segments = [segment for segment in segments if segment.route_id == "R_LONG"]
    short_segments = [segment for segment in segments if segment.route_id == "R_SHORT"]

    assert [segment.segment_id for segment in long_segments] == [
        "R_LONG_S0001",
        "R_LONG_S0002",
        "R_LONG_S0003",
    ]
    assert [segment.length_m for segment in long_segments[:2]] == pytest.approx([100.0, 100.0])
    assert 70.0 < long_segments[-1].length_m < 90.0
    assert len(short_segments) == 1
    assert 15.0 < short_segments[0].length_m < 30.0
    assert all(segment.pm25_grid_id is None for segment in segments)


def test_route_segment_document_is_jsonable(tmp_path: Path) -> None:
    route_path = tmp_path / "routes.geojson"
    _write_routes(route_path)

    document = build_route_segments_document(route_path)
    encoded = json.dumps(document, ensure_ascii=False)

    assert document["route_count"] == 2
    assert document["segment_count"] == 4
    assert document["source_crs"] == "GCJ-02"
    assert document["analysis_crs"] == "EPSG:32651"
    assert "R_LONG_S0001" in encoded


def test_segments_are_assigned_to_nearest_pm25_grid_with_distance(tmp_path: Path) -> None:
    route_path = tmp_path / "routes.geojson"
    _write_routes(route_path)
    grid_path = tmp_path / "pm25_grid_latest.json"
    grid_path.write_text(
        json.dumps(
            {
                "grids": [
                    {"grid_id": "G_NEAR", "longitude": 121.4655, "latitude": 31.2010},
                    {"grid_id": "G_FAR", "longitude": 121.50, "latitude": 31.25},
                ]
            }
        ),
        encoding="utf-8",
    )

    segments = assign_pm25_grids(load_route_segments(route_path), grid_path)

    assert all(segment.pm25_grid_id == "G_NEAR" for segment in segments)
    assert all(segment.pm25_grid_distance_m is not None for segment in segments)
    assert all(segment.pm25_grid_source == str(grid_path.resolve()) for segment in segments)

    unmatched = assign_pm25_grids(
        load_route_segments(route_path),
        grid_path,
        max_distance_m=1.0,
    )
    assert all(segment.pm25_grid_id is None for segment in unmatched)
    assert all(segment.pm25_grid_distance_m is not None for segment in unmatched)
    assert all(segment.pm25_grid_source == str(grid_path.resolve()) for segment in unmatched)


def test_existing_route_portfolio_contains_90_routes() -> None:
    route_path = (
        Path(__file__).parents[2] / "xuhui_route_builder" / "data" / "web" / "xuhui_routes.geojson"
    )

    document = build_route_segments_document(route_path)

    assert document["route_count"] == 90
    assert isinstance(document["segment_count"], int)
    assert document["segment_count"] > 90
