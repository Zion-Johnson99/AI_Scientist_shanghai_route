import json

from xuhui_route_builder.cli import export_demo


def test_export_demo_writes_web_dataset_files(tmp_path) -> None:
    export_demo(tmp_path)
    web_dir = tmp_path / "data" / "web"

    expected_files = {
        "xuhui_boundary.geojson",
        "xuhui_entries.geojson",
        "xuhui_routes.geojson",
        "route_catalog.json",
        "poi_catalog.json",
        "access_cases.json",
    }

    assert expected_files <= {path.name for path in web_dir.iterdir()}
    routes = json.loads((web_dir / "xuhui_routes.geojson").read_text(encoding="utf-8"))
    catalog = json.loads((web_dir / "route_catalog.json").read_text(encoding="utf-8"))
    pois = json.loads((web_dir / "poi_catalog.json").read_text(encoding="utf-8"))
    access_cases = json.loads((web_dir / "access_cases.json").read_text(encoding="utf-8"))

    assert len(routes["features"]) == 150
    assert len(catalog) == 150
    assert pois["type"] == "FeatureCollection"
    assert len(access_cases) >= 10
