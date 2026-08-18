import json
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "web"


def test_default_web_data_contains_all_90_status_labelled_routes() -> None:
    routes = json.loads((DATA_ROOT / "xuhui_routes.geojson").read_text(encoding="utf-8"))
    catalog = json.loads((DATA_ROOT / "route_catalog.json").read_text(encoding="utf-8"))

    assert len(routes["features"]) == 90
    assert len(catalog) == 90
    assert all(
        item.get("start_location", {}).get("name")
        and isinstance(item["start_location"].get("lng_gcj02"), float)
        and isinstance(item["start_location"].get("lat_gcj02"), float)
        for item in catalog
    )
    assert {mode: sum(route["route_mode"] == mode for route in catalog) for mode in ("walk", "run", "bike")} == {
        "walk": 30,
        "run": 30,
        "bike": 30,
    }
    assert all(route["validation_status"] in {"accepted", "needs_review"} for route in catalog)


def test_index_declares_inline_favicon_to_avoid_404() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html


def test_frontend_assets_share_a_cache_busting_release_version() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")

    release = "v=20260818-portfolio-1"
    assert f"./styles/main.css?{release}" in html
    assert f"./src/main.js?{release}" in html
    assert f'./data-loader.js?{release}' in main_js
    assert f'./navigation-session.js?{release}' in main_js
    assert f'./map.js?{release}' in main_js
    assert f'./route-dock.js?{release}' in main_js
    assert f'./route-ui.js?{release}' in main_js
    assert "DATA_RELEASE" in data_loader_js
    assert "cache: \"no-store\"" in data_loader_js
    for data_path in [
        "xuhui_boundary.geojson",
        "xuhui_entries.geojson",
        "xuhui_routes.geojson",
        "route_catalog.json",
        "poi_catalog.json",
    ]:
        assert data_path in data_loader_js


def test_main_wires_planned_access_request_to_inline_navigation() -> None:
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert 'import { createNavigationController } from "./navigation-session.js?' in main_js
    assert "onStartInlineNavigation" in main_js
    assert "beginInlineNavigation" in main_js
    assert "updateInlineNavigation" in main_js
    assert "launchAmapNavigation" not in main_js


def test_route_selection_reports_missing_geometry_instead_of_failing_silently() -> None:
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "showRouteFeature" in main_js
    assert "缺少地图路径数据" in main_js
    assert "if (feature)" not in main_js


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
        "sportModeTabs",
        "distanceFilter",
        "preferCoffee",
        "preferToilet",
        "preferStore",
        "preferPark",
        "planButton",
        "routeSelect",
    ]:
        assert f'id="{element_id}"' in html

    assert 'id="preferMetro"' not in html
    assert 'id="preferStore" type="checkbox" value="convenience"' in html
    assert 'id="preferPark" type="checkbox" value="park_gate"' in html
    assert "metro:" not in route_ui_js

    assert "route-selection-view" in html
    assert "route-navigation-view" in html
    assert "startInput" in html
    assert "endInput" not in html
    assert "waypointInput" not in html
    assert "navigationModeSummary" in html
    assert "startSportButton" in html
    assert "filterCandidateRoutes" in route_ui_js
    assert "onShowRoute" in route_ui_js
    assert "onNavigate" in route_ui_js
    assert "selectBestRoute" in route_ui_js
    assert "renderRouteSelect" in route_ui_js
    assert "data-route-mode" in html
    assert "onShowRoute" in route_ui_js
    assert "updateModeCounts(catalog, controls)" in route_ui_js
    assert 'tab.querySelector("span").textContent = `${routes.length} 条`;' in route_ui_js
    assert "routeShapeCounts" not in route_ui_js
    assert "环" in route_ui_js
    assert "单" in route_ui_js
    assert "30 条" not in html
    assert "90 条城市运动候选路线" not in html


def test_preference_filters_use_verified_route_hits_only() -> None:
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert "PREFERENCE_KEYWORDS" not in route_ui_js
    assert "preferences.every((preference) => hits.includes(preference))" in route_ui_js


def test_route_picker_uses_single_select_and_waits_for_explicit_search() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'id="routeSelect"' in html
    assert 'id="routeTabs"' not in html
    assert 'id="resultTabs"' not in html
    assert "选择一条路线" in html
    assert "selectBestRoute" in route_ui_js
    assert "无推荐路线" in route_ui_js
    assert "options.onShowRoute(route)" in route_ui_js
    assert "renderRouteSelect" in route_ui_js
    assert "initializeRouteSelection" in route_ui_js
    assert "runSearch(catalog, state, controls, options);" not in route_ui_js[\
        route_ui_js.index("export function renderRoutePlanner") : route_ui_js.index("export function filterCandidateRoutes")\
    ]
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
    assert ".route-picker" in css


def test_map_uses_route_shape_and_real_waypoint_coordinates() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    assert 'bike: { color: "#7C3AED"' in map_js
    assert 'route_shape === "strict_loop"' in map_js
    assert 'label: "起终点"' in map_js
    assert "ordered_nodes" in map_js
    assert "node.node_name || node.name" in map_js
    assert "Math.round(((index + 1) * (path.length - 1))" not in map_js


def test_all_route_shapes_show_direction_arrows() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    assert "showDir: true" in map_js
    assert 'showDir: properties.route_shape === "one_way"' not in map_js


def test_selected_route_layer_stays_above_the_xuhui_boundary() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    boundary_block = map_js[map_js.index("export function drawBoundary") : map_js.index("export function showRouteResults")]
    route_block = map_js[map_js.index("export function showRouteResults") : map_js.index("export function showSingleRoute")]
    assert "zIndex: 30" in boundary_block
    assert "zIndex: active ? 100 : 70" in route_block


def test_web_loads_pois_and_supports_navigation_session_controls() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    for element_id in [
        "startNavigationButton",
        "endNavigationButton",
        "startPickButton",
        "navigationModeSummary",
        "startSportButton",
        "inlineNavigationGuide",
        "inlineNavigationInstruction",
        "inlineNavigationRemaining",
        "inlineNavigationAccuracy",
        "inlineNavigationEndButton",
    ]:
        assert f'id="{element_id}"' in html

    for removed_element_id in ["waypointInput", "waypointPickButton", "endInput", "endPickButton", "navigationMode"]:
        assert f'id="{removed_element_id}"' not in html

    assert "poi_catalog.json" in data_loader_js
    assert "preference_hits" in route_ui_js
    assert "startNavigationSession" in map_js
    assert "endNavigationSession" in map_js
    assert "enablePointPicker" in map_js
    assert "setNavigationPoint" in map_js
    assert "isPointInsideXuhui" in map_js
    assert "navigationServiceMode" in map_js
    assert "focusSportRoute" in map_js
    assert "previewSportRoute" in map_js
    assert "navigationPlanFromResult" in map_js
    assert "beginInlineNavigation" in map_js
    assert "updateInlineNavigation" in map_js
    assert "AMap.Driving" not in html
    assert "addEventListener(\"click\"" in map_js
    assert "containerToLngLat" in map_js


def test_sidebar_route_picker_does_not_depend_on_an_internal_scrolling_route_list() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    selection_block = css[
        css.index(".route-selection-view.active {") : css.index(".field-grid {")
    ]

    assert "minmax(190px, 1fr)" not in selection_block


def test_mobile_inline_navigation_expands_map_to_avoid_route_dock_overlap() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert ".map-wrap.inline-navigation-active" in css
    assert "min-height: 68dvh" in css
    assert 'classList.add("inline-navigation-active")' in main_js
    assert 'classList.remove("inline-navigation-active")' in main_js
    assert ".route-picker" in css
    assert ".route-tabs" not in css
    assert "flex-shrink: 0" in css[css.index(".mode-tabs {") : css.index(".mode-tabs button {")]


def test_route_selection_preserves_content_rows_before_scrolling() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    selection_block = css[
        css.index(".route-selection-view.active {") : css.index(".field-grid {")
    ]

    assert "flex: 1 1 0;" in selection_block
    assert "grid-template-rows: max-content max-content;" in selection_block
    assert "overflow-y: auto;" in selection_block


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
