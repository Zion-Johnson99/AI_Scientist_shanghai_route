from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def test_index_declares_inline_favicon_to_avoid_404() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html


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
    assert "showRouteResults" in main_js


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
        "resultTabs",
    ]:
        assert f'id="{element_id}"' in html

    assert "route-selection-view" in html
    assert "route-navigation-view" in html
    assert "startInput" in html
    assert "endInput" in html
    assert "filterCandidateRoutes" in route_ui_js
    assert "onSearch" in route_ui_js
    assert "onNavigate" in route_ui_js
    assert "recommend" in route_ui_js
    assert "convenient" in route_ui_js
    assert "candidate" in route_ui_js
    assert "candidate_rank" in route_ui_js


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


def test_sidebar_route_list_has_independent_scroll_constraint() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    route_list_block = css[css.index(".route-list {") : css.index(".route-item {")]

    assert "overflow-y: auto" in route_list_block
    assert "max-height" in route_list_block


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
