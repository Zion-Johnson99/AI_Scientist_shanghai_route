from __future__ import annotations

import argparse
from pathlib import Path

from .config import PROJECT_ROOT
from .demo_dataset import build_demo_dataset
from .exporters import (
    build_access_catalog,
    build_feature_collection,
    build_poi_feature_collection,
    build_route_catalog,
    build_route_feature_collection,
    write_access_cases_csv,
    write_entries_csv,
    write_json,
)
from .routes import load_route_seeds


def main() -> None:
    parser = argparse.ArgumentParser(prog="xuhui-route-builder")
    parser.add_argument("command", choices=["export-samples", "export-demo", "validate-seeds"])
    args = parser.parse_args()
    if args.command == "export-samples":
        export_demo(PROJECT_ROOT)
    elif args.command == "export-demo":
        export_demo(PROJECT_ROOT)
    elif args.command == "validate-seeds":
        seeds = load_route_seeds(PROJECT_ROOT / "data" / "seeds" / "route_seeds.json")
        print(f"route_seed_count={len(seeds)}")


def export_demo(project_root: Path) -> None:
    dataset = build_demo_dataset()
    web_dir = project_root / "data" / "web"
    write_json(web_dir / "xuhui_boundary.geojson", {"type": "FeatureCollection", "features": [dataset.boundary]})
    write_json(web_dir / "xuhui_entries.geojson", build_feature_collection(dataset.entries))
    write_json(web_dir / "xuhui_routes.geojson", build_route_feature_collection(dataset.routes))
    write_json(web_dir / "route_catalog.json", build_route_catalog(dataset.routes))
    write_json(web_dir / "poi_catalog.json", build_poi_feature_collection(dataset.pois))
    write_json(web_dir / "access_cases.json", build_access_catalog(dataset.access_cases))
    write_entries_csv(project_root / "data" / "processed" / "xuhui_entry_pool.csv", dataset.entries)
    write_access_cases_csv(project_root / "data" / "processed" / "xuhui_access_cases.csv", dataset.access_cases)
    print(
        " ".join(
            [
                f"exported_entries={len(dataset.entries)}",
                f"exported_routes={len(dataset.routes)}",
                f"exported_pois={len(dataset.pois)}",
                f"exported_access_cases={len(dataset.access_cases)}",
            ]
        )
    )


if __name__ == "__main__":
    main()
