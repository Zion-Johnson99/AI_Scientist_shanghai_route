from xuhui_route_builder.demo_dataset import build_demo_dataset


def test_demo_dataset_contains_no_simulated_routes() -> None:
    dataset = build_demo_dataset()
    assert dataset.routes == []


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


def test_demo_module_has_no_simulated_route_symbols() -> None:
    import xuhui_route_builder.demo_dataset as module

    for name in ("ZONE_CORRIDORS", "_build_routes", "_make_route", "_seed_polyline", "_densify"):
        assert not hasattr(module, name)
