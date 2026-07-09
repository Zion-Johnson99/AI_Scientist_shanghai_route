from xuhui_route_builder.demo_dataset import build_demo_dataset


def test_demo_dataset_contains_150_routes_with_required_fields() -> None:
    dataset = build_demo_dataset()
    entry_ids = {entry.entry_id for entry in dataset.entries}

    assert len(dataset.routes) == 150
    assert len({route.route_id for route in dataset.routes}) == 150
    assert {route.route_mode for route in dataset.routes} >= {"walk", "run", "bike"}
    assert all(route.polyline_gcj02 for route in dataset.routes)
    assert all(route.actual_distance_m > 0 for route in dataset.routes)
    assert all(route.duration_s > 0 for route in dataset.routes)
    assert all(route.region_zone for route in dataset.routes)
    assert all(route.source_url for route in dataset.routes)
    assert all(route.confidence in {"高", "中高", "中"} for route in dataset.routes)
    assert all(route.route_inside_ratio is not None and route.route_inside_ratio >= 0.8 for route in dataset.routes)
    assert all(route.start_entry_id in entry_ids for route in dataset.routes)
    assert all(route.end_entry_id in entry_ids for route in dataset.routes)


def test_demo_boundary_is_not_manual_rectangle() -> None:
    dataset = build_demo_dataset()
    ring = dataset.boundary["geometry"]["coordinates"][0]

    assert dataset.boundary["properties"]["adcode"] == "310104"
    assert dataset.boundary["properties"]["source_api"] == "datav.aliyun.boundary"
    assert len(ring) > 10
    assert len({point[0] for point in ring}) > 4
    assert len({point[1] for point in ring}) > 4


def test_demo_entries_include_visibility_and_community_nodes() -> None:
    dataset = build_demo_dataset()
    entry_types = {entry.entry_type for entry in dataset.entries}
    community_nodes = [entry for entry in dataset.entries if entry.entry_type == "community_node"]

    assert {"metro_exit", "park_gate", "riverside_access", "community_node", "office_cluster", "scenic_node"} <= entry_types
    assert community_nodes
    assert all(entry.default_visible is False for entry in community_nodes)


def test_demo_dataset_exports_poi_and_access_cases() -> None:
    dataset = build_demo_dataset()

    assert len(dataset.pois) >= 30
    assert {poi.poi_type for poi in dataset.pois} >= {"coffee", "toilet", "convenience", "metro", "park_gate"}
    assert len(dataset.access_cases) >= 10
    assert all(case.distance_m > 0 for case in dataset.access_cases)
    assert all(case.duration_s > 0 for case in dataset.access_cases)


def test_demo_routes_cover_preference_tags() -> None:
    dataset = build_demo_dataset()
    tags = {tag for route in dataset.routes for tag in route.tags}

    assert {"咖啡", "厕所", "便利店", "地铁", "公园入口"} <= tags


def test_demo_routes_are_built_from_real_route_seeds_with_poi_hits() -> None:
    dataset = build_demo_dataset()
    source_urls = {route.source_url for route in dataset.routes}
    motherline_names = {route.route_name.split("·")[0] for route in dataset.routes}

    assert len(source_urls) >= 10
    assert len(motherline_names) >= 10
    assert all(route.source_method == "real_route_seed" for route in dataset.routes)
    assert all(route.geometry_source == "amap_direction" for route in dataset.routes)
    assert all(route.source_level in {"official", "media", "curated"} for route in dataset.routes)
    assert all(route.waypoint_names for route in dataset.routes)
    assert all(route.nearby_pois for route in dataset.routes)
    assert all(route.preference_hits for route in dataset.routes)
