from __future__ import annotations

import argparse
from pathlib import Path

from .config import PROJECT_ROOT
from .entries import sample_entries
from .exporters import build_feature_collection, build_route_catalog, build_route_feature_collection, write_entries_csv, write_json
from .geo import parse_lng_lat
from .models import CandidateRoute
from .routes import load_route_seeds
from .scoring_placeholder import attach_score_placeholder


def main() -> None:
    parser = argparse.ArgumentParser(prog="xuhui-route-builder")
    parser.add_argument("command", choices=["export-samples", "validate-seeds"])
    args = parser.parse_args()
    if args.command == "export-samples":
        export_samples(PROJECT_ROOT)
    elif args.command == "validate-seeds":
        seeds = load_route_seeds(PROJECT_ROOT / "data" / "seeds" / "route_seeds.json")
        print(f"route_seed_count={len(seeds)}")


def export_samples(project_root: Path) -> None:
    entries = sample_entries()
    routes = _sample_routes()
    web_dir = project_root / "data" / "web"
    write_json(web_dir / "xuhui_entries.geojson", build_feature_collection(entries))
    write_json(web_dir / "xuhui_routes.geojson", build_route_feature_collection(routes))
    write_json(web_dir / "route_catalog.json", build_route_catalog(routes))
    write_entries_csv(project_root / "data" / "processed" / "xuhui_entry_pool.csv", entries)
    print(f"exported_entries={len(entries)} exported_routes={len(routes)}")


def _sample_routes() -> list[CandidateRoute]:
    coords = [
        ["121.4598,31.1592", "121.4565,31.1640", "121.4520,31.1700"],
        ["121.4460,31.2050", "121.4420,31.2068", "121.4390,31.2080"],
        ["121.4382,31.1493", "121.4350,31.1515", "121.4330,31.1480", "121.4382,31.1493"],
    ]
    names = ["徐汇滨江舒心跑", "衡复音乐街区 Citywalk", "上海植物园南区花园环线"]
    modes = ["run", "walk", "walk"]
    targets = [3000, 2600, 3000]
    zones = ["徐汇滨江", "衡复风貌区", "上海植物园"]
    tags = [["滨江", "夜跑"], ["历史建筑", "梧桐"], ["绿地", "花粉提示"]]
    routes: list[CandidateRoute] = []
    for idx, route_points in enumerate(coords, start=1):
        route = CandidateRoute(
            route_id=f"XH_SAMPLE_{idx:04d}",
            route_name=names[idx - 1],
            route_mode=modes[idx - 1],
            target_distance_m=targets[idx - 1],
            actual_distance_m=targets[idx - 1],
            duration_s=targets[idx - 1] // 2,
            start_entry_id=f"XH_ENT_{idx:04d}",
            end_entry_id=f"XH_ENT_{idx:04d}",
            region_zone=zones[idx - 1],
            polyline_gcj02=[parse_lng_lat(point) for point in route_points],
            tags=tags[idx - 1],
            source_method="manual_sample",
        )
        routes.append(attach_score_placeholder(route))
    return routes


if __name__ == "__main__":
    main()
