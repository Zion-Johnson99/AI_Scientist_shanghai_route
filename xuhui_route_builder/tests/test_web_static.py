import json
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "web"


def test_default_web_data_contains_eleven_network_matched_routes() -> None:
    routes = json.loads((DATA_ROOT / "xuhui_routes.geojson").read_text(encoding="utf-8"))
    catalog = json.loads((DATA_ROOT / "route_catalog.json").read_text(encoding="utf-8"))

    assert len(routes["features"]) == 11
    assert len(catalog) == 11
    assert all(route["snap_ratio"] >= 0.98 for route in catalog)
    assert {route["route_id"] for route in catalog}.isdisjoint(
        {"XH_RUN_0004", "XH_WALK_0007", "XH_BIKE_0011", "XH_BIKE_0015"}
    )


def test_index_declares_inline_favicon_to_avoid_404() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html


def test_frontend_assets_share_a_cache_busting_release_version() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    release = "v=20260712-route-picker-2"
    assert f"./styles/main.css?{release}" in html
    assert f"./src/main.js?{release}" in html
    assert f'./data-loader.js?{release}' in main_js
    assert f'./map.js?{release}' in main_js
    assert f'./route-ui.js?{release}' in main_js


def test_index_uses_amap_js_loader_without_leaflet_stack() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert "webapi.amap.com/maps" in html
    assert "window.XUHUI_AMAP_JS_KEY" in html
    assert "./local-amap-config.js" in html
    assert "缺少本地高德 Key 配置" in html
    assert "AMap.GeoJSON" in html
    assert "leaflet" not in html.lower()


def test_startup_does_not_draw_full_route_or_entry_layers() -> None:
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "drawBoundary" in main_js
    assert "drawEntries(map, data.entries)" not in main_js
    assert "drawRoutes(map, data.routes)" not in main_js
    assert "showSingleRoute" in main_js


def test_route_controls_support_local_candidate_search_and_preferences() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    for element_id in [
        "routeSelectionTab",
        "routeNavigationTab",
        "keywordInput",
        "zoneFilter",
        "modeFilter",
        "distanceFilter",
        "preferCoffee",
        "preferToilet",
        "preferStore",
        "preferMetro",
        "preferPark",
        "planButton",
        "routeTabs",
    ]:
        assert f'id="{element_id}"' in html

    assert "route-selection-view" in html
    assert "route-navigation-view" in html
    assert "startInput" in html
    assert "endInput" in html
    assert "filterCandidateRoutes" in route_ui_js
    assert "onShowRoute" in route_ui_js
    assert "onNavigate" in route_ui_js
    assert "selectBestRoute" in route_ui_js
    assert "renderRouteTabs" in route_ui_js
    assert "onShowRoute" in route_ui_js


def test_route_picker_uses_compact_route_tabs_and_single_route_selection() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'id="routeTabs"' in html
    assert 'id="resultTabs"' not in html
    assert "选择一条路线" in html
    assert "selectBestRoute" in route_ui_js
    assert "无推荐路线" in route_ui_js
    assert "options.onShowRoute(route)" in route_ui_js
    assert "showSingleRoute" in main_js
    assert "showRouteResults(map, routeFeatures" not in main_js


def test_map_draws_a_thin_single_route_with_landmark_markers() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    assert "export function showSingleRoute" in map_js
    assert 'role: "start"' in map_js
    assert 'role: "end"' in map_js
    assert 'role: "landmark"' in map_js
    assert "Math.min(3" in map_js
    assert "weight: 4" in map_js
    assert ".amap-route-marker" in css
    assert ".route-tabs" in css


def test_web_loads_pois_and_supports_navigation_session_controls() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    for element_id in [
        "startNavigationButton",
        "endNavigationButton",
        "startPickButton",
        "waypointInput",
        "waypointPickButton",
        "endPickButton",
    ]:
        assert f'id="{element_id}"' in html

    assert "poi_catalog.json" in data_loader_js
    assert "preference_hits" in route_ui_js
    assert "startNavigationSession" in map_js
    assert "endNavigationSession" in map_js
    assert "enablePointPicker" in map_js
    assert "setNavigationPoint" in map_js
    assert "isPointInsideXuhui" in map_js
    assert "addEventListener(\"click\"" in map_js
    assert "containerToLngLat" in map_js


def test_sidebar_route_tabs_have_independent_horizontal_scroll() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    route_tabs_block = css[css.index(".route-tabs {") : css.index(".route-tab {")]

    assert "overflow-x: auto" in route_tabs_block
    assert "display: flex" in route_tabs_block


def test_map_module_uses_amap_and_keeps_community_nodes_result_scoped() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    assert "AMap.Map" in map_js
    assert "AMap.GeoJSON" in map_js
    assert "AMap.Polyline" in map_js
    assert "L." not in map_js
    assert "community_node" in map_js
    assert "relatedEntryIds" in map_js
    for route_mode in ["run", "walk", "bike", "access"]:
        assert route_mode in map_js
