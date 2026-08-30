import json
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "web"
REPOSITORY_ROOT = WEB_ROOT.parents[1]


def test_default_web_data_contains_all_90_status_labelled_routes() -> None:
    routes = json.loads(
        (DATA_ROOT / "xuhui_routes.geojson").read_text(encoding="utf-8")
    )
    catalog = json.loads((DATA_ROOT / "route_catalog.json").read_text(encoding="utf-8"))

    assert len(routes["features"]) == 90
    assert len(catalog) == 90
    assert all(
        item.get("start_location", {}).get("name")
        and isinstance(item["start_location"].get("lng_gcj02"), float)
        and isinstance(item["start_location"].get("lat_gcj02"), float)
        for item in catalog
    )
    assert {
        mode: sum(route["route_mode"] == mode for route in catalog)
        for mode in ("walk", "run", "bike")
    } == {
        "walk": 30,
        "run": 30,
        "bike": 30,
    }
    assert all(
        route["validation_status"] in {"accepted", "needs_review"} for route in catalog
    )


def test_windows_launcher_starts_the_complete_local_application() -> None:
    launcher_path = REPOSITORY_ROOT / "start-local-app.ps1"
    launcher = launcher_path.read_text(encoding="utf-8-sig")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert launcher_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "[switch]$UseQwen" in launcher
    assert '$offlineMode = if ($UseQwen) { "0" } else { "1" }' in launcher
    assert "$env:EVALUATION_MODEL_QWEN_OFFLINE = $offlineMode" in launcher
    assert "evaluation-model-qwen-api.exe" in launcher
    assert '-m", "http.server", "8123' in launcher
    assert "http://127.0.0.1:8124/api/v1/health" in launcher
    assert "http://127.0.0.1:8123/web/" in launcher
    assert "-WindowStyle Hidden" in launcher
    assert "Stop-Process" in launcher
    assert "Get-EnvironmentRefreshTier" in launcher
    assert "scheduled-refresh" in launcher
    assert '"weather", "hourly", "daily"' in launcher
    assert "current.aqi" in launcher
    assert "current.life_indices" in launcher
    assert "routes.items" in launcher
    assert "Get-Content -LiteralPath $Path -Raw -Encoding UTF8" in launcher
    assert "Get-Content -LiteralPath $dashboardPath -Raw -Encoding UTF8" in launcher
    assert 'PSObject.Properties["expires_at"]' in launcher
    assert "$existingHealth.qwen.offline" in launcher
    assert "请先在原命令窗口按 Ctrl+C" in launcher
    assert "$nextEnvironmentCheck" in launcher
    assert "运行期间环境数据刷新失败" in launcher
    assert "AddMinutes(30)" in launcher
    assert "AddMinutes(1)" not in launcher
    assert "环境数据已更新，更新时间：" in launcher
    assert "环境数据未更新，上次更新时间：" in launcher
    assert "AQI 状态" not in launcher
    assert "数值 $aqiValue" not in launcher
    assert ".\\start-local-app.ps1" in readme
    assert ".\\start-local-app.ps1 -UseQwen" in readme
    assert "启动时按数据新鲜度" in readme
    assert "运行期间每 30 分钟复查" in readme


def test_macos_linux_launcher_starts_the_complete_local_application() -> None:
    launcher_path = REPOSITORY_ROOT / "start-local-app.sh"
    launcher = launcher_path.read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert launcher.startswith("#!/usr/bin/env bash")
    assert "--use-qwen" in launcher
    assert ".venv/bin/evaluation-model-qwen-api" in launcher
    assert ".venv/bin/weather-api-data" in launcher
    assert ".venv/bin/python" in launcher
    assert "EVALUATION_MODEL_QWEN_OFFLINE" in launcher
    assert "python -m http.server" not in launcher
    assert '"-m" "http.server" "8123"' in launcher
    assert "http://127.0.0.1:8124/api/v1/health" in launcher
    assert "http://127.0.0.1:8123/web/" in launcher
    assert "trap cleanup EXIT INT TERM" in launcher
    assert "environment_check_interval_seconds=1800" in launcher
    assert "环境数据已更新，更新时间：" in launcher
    assert "环境数据未更新，上次更新时间：" in launcher
    assert "AQI 状态" not in launcher
    assert "bash ./start-local-app.sh" in readme
    assert "bash ./start-local-app.sh --use-qwen" in readme


def test_index_declares_inline_favicon_to_avoid_404() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html


def test_index_presents_the_health_map_product_shell() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert "<title>徐汇户外健康地图</title>" in html
    assert "<h1>徐汇户外健康地图</h1>" in html
    assert "qweather-icons@1.8.0/font/qweather-icons.css" in html
    assert 'id="environmentPanel"' in html
    assert 'class="environment-panel"' in html
    for internal_copy in [
        "Xuhui Route Builder",
        "严格验收",
        "Route match",
        "已切换",
        "数据待接入",
        "待评估",
    ]:
        assert internal_copy not in html


def test_navigation_shell_uses_a_short_manual_start_flow() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    for element_id in [
        "navigationBackButton",
        "navigationRouteName",
        "startInput",
        "startPickButton",
        "navigateButton",
        "startSportButton",
        "inlineNavigationGuide",
        "inlineNavigationPreviousButton",
        "inlineNavigationNextButton",
        "inlineNavigationEndButton",
    ]:
        assert f'id="{element_id}"' in html

    assert "搜索上海地点" in html
    assert "规划接驳路线" in html
    assert "进入导航预览" in html
    assert 'id="navigationRouteSelect"' not in html
    assert 'id="navigationSportModeTabs"' not in html
    assert 'id="startNavigationButton"' not in html
    assert 'id="endNavigationButton"' not in html
    assert "实时接驳" not in html
    assert "定位精度" not in html


def test_glass_shell_keeps_primary_controls_touch_friendly_and_responsive() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    primary_actions = css[
        css.index(".primary-action,") : css.index(".primary-action {")
    ]
    assert "min-height: 44px;" in primary_actions
    assert ".environment-panel" in css
    assert ".route-dock__exposure-grid" in css
    assert ".route-dock__exposure-card" in css
    assert ".route-dock__exposure-reading" in css
    assert '.route-dock__exposure-card[data-status="partial"]' in css
    assert '.route-dock__exposure-card[data-status="stale"]' in css
    assert '.route-dock__exposure-card[data-status="no_data"]' in css
    assert "backdrop-filter" in css
    assert "@media (min-width: 981px) and (max-width: 1180px)" in css
    assert "@media (max-width: 980px)" in css
    assert "@media (max-width: 520px)" in css


def test_frontend_assets_share_a_cache_busting_release_version() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")

    release = "v=20260828-recommendation-1"
    assert f"./styles/main.css?{release}" in html
    assert f"./src/main.js?{release}" in html
    assert f"./data-loader.js?{release}" in main_js
    assert f"./navigation-session.js?{release}" in main_js
    assert f"./map.js?{release}" in main_js
    assert f"./route-dock.js?{release}" in main_js
    assert f"./route-ui.js?{release}" in main_js
    assert f"./recommendation-api.js?{release}" in main_js
    assert f"./recommendation-ui.js?{release}" in main_js
    assert f"./profile-store.js?{release}" in main_js
    assert "DATA_RELEASE" in data_loader_js
    assert 'cache: "no-store"' in data_loader_js
    for data_path in [
        "xuhui_boundary.geojson",
        "xuhui_entries.geojson",
        "xuhui_routes.geojson",
        "route_catalog.json",
        "poi_catalog.json",
    ]:
        assert data_path in data_loader_js


def test_route_detail_hides_internal_review_note() -> None:
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    assert 'class="route-review-note"' not in route_ui_js
    assert "reviewNoteSummary" not in route_ui_js
    assert ".route-review-note" not in css


def test_main_wires_planned_access_request_to_inline_navigation() -> None:
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert (
        'import { createNavigationController } from "./navigation-session.js?'
        in main_js
    )
    assert "onStartInlineNavigation" in main_js
    assert "beginInlineNavigation" in main_js
    assert "createEnvironmentPanel" in main_js
    assert "buildRouteExposureModel" in main_js
    assert "startEnvironmentDashboardPolling" in main_js
    assert "onEndInlineNavigation" in main_js
    assert "inlineNavigationPreviousButton" in main_js
    assert "inlineNavigationNextButton" in main_js
    assert "navigationController.previous()" in main_js
    assert "navigationController.next()" in main_js
    assert "updateInlineNavigation" not in main_js
    assert "navigator.geolocation" not in main_js
    assert "watchPosition" not in main_js
    assert "rerouteFrom" not in main_js
    assert "shouldReroute" not in main_js
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


def test_product_shell_separates_recommendation_from_compact_route_browsing() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    for element_id in [
        "recommendationTab",
        "browseTab",
        "recommendationView",
        "zoneFilter",
        "sportModeTabs",
        "distanceFilter",
        "routeSelect",
    ]:
        assert f'id="{element_id}"' in html

    for removed_id in [
        "routeSelectionTab",
        "routeNavigationTab",
        "keywordInput",
        "preferCoffee",
        "preferToilet",
        "preferStore",
        "preferPark",
        "planButton",
    ]:
        assert f'id="{removed_id}"' not in html
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
    assert (
        'tab.querySelector("span").textContent = `${routes.length} 条`;' in route_ui_js
    )
    assert "routeShapeCounts" not in route_ui_js
    assert "环" in route_ui_js
    assert "单" in route_ui_js
    assert "30 条" not in html
    assert "90 条城市运动候选路线" not in html


def test_product_tabs_and_sport_filters_expose_complete_accessibility_state() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'class="mode-tabs" role="tablist"' in html
    assert 'aria-controls="recommendationView"' in html
    assert 'aria-controls="routeSelectionView"' in html
    assert 'role="tabpanel"' in html
    assert 'class="sport-mode-tabs" role="group"' in html
    assert 'aria-pressed="true"' in html
    assert "aria-selected" in main_js
    assert 'event.key === "ArrowRight"' in main_js
    assert 'setAttribute("aria-pressed"' in route_ui_js
    assert 'element("h2", "recommendation-panel__title"' in (
        WEB_ROOT / "src" / "recommendation-ui.js"
    ).read_text(encoding="utf-8")


def test_small_screen_uses_full_map_with_overlay_drawer_and_visible_action() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    mobile_css = css[css.rindex("@media (max-width: 980px)") :]
    assert "position: fixed" in mobile_css
    assert "height: 100dvh" in mobile_css
    assert "inset: 0" in mobile_css
    assert "max-height: min(56dvh, 520px)" in mobile_css
    assert ".recommendation-route__navigate" in mobile_css
    assert "position: sticky" in mobile_css


def test_preference_filters_use_real_nearby_pois_only() -> None:
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert "PREFERENCE_KEYWORDS" not in route_ui_js
    assert "preferences.every((preference) => hits.has(preference))" in route_ui_js
    assert "route.nearby_pois" in route_ui_js
    assert "route.preference_hits" not in route_ui_js


def test_route_browser_uses_single_select_and_updates_preview_with_filters() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'id="routeSelect"' in html
    assert 'id="routeTabs"' not in html
    assert 'id="resultTabs"' not in html
    assert "地图中的路线" in html
    assert "selectBestRoute" in route_ui_js
    assert "options.onShowRoute(route, state.filters.preferences)" in route_ui_js
    assert "renderRouteSelect" in route_ui_js
    assert "initializeRouteSelection" in route_ui_js
    assert (
        'controls.zoneFilter.addEventListener("change", refreshPreview)' in route_ui_js
    )
    assert (
        'controls.distanceFilter.addEventListener("change", refreshPreview)'
        in route_ui_js
    )
    assert "onShowRoute(route, selectedPreferences)" in main_js
    assert (
        "showSingleRoute(map, feature, data.entries, data.pois, selectedPreferences)"
        in main_js
    )
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

    boundary_block = map_js[
        map_js.index("export function drawBoundary") : map_js.index(
            "export function showRouteResults"
        )
    ]
    route_block = map_js[
        map_js.index("export function showRouteResults") : map_js.index(
            "export function showSingleRoute"
        )
    ]
    assert "zIndex: 30" in boundary_block
    assert "zIndex: active ? 100 : 70" in route_block


def test_web_loads_pois_and_supports_manual_navigation_controls() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    for element_id in [
        "startPickButton",
        "navigationModeSummary",
        "startSportButton",
        "inlineNavigationGuide",
        "inlineNavigationInstruction",
        "inlineNavigationRemaining",
        "inlineNavigationPreviousButton",
        "inlineNavigationNextButton",
        "inlineNavigationEndButton",
    ]:
        assert f'id="{element_id}"' in html

    for removed_element_id in [
        "startNavigationButton",
        "endNavigationButton",
        "waypointInput",
        "waypointPickButton",
        "endInput",
        "endPickButton",
        "navigationMode",
    ]:
        assert f'id="{removed_element_id}"' not in html

    assert "poi_catalog.json" in data_loader_js
    assert "nearby_pois" in route_ui_js
    assert "preference_hits" not in route_ui_js
    assert "enablePointPicker" in map_js
    assert "setNavigationPoint" in map_js
    assert "navigationServiceMode" in map_js
    assert "focusSportRoute" in map_js
    assert "previewSportRoute" in map_js
    assert "navigationPlanFromResult" in map_js
    assert "AMap.Driving" not in html
    assert 'addEventListener("click"' in map_js
    assert "containerToLngLat" in map_js


def test_sidebar_route_picker_does_not_depend_on_an_internal_scrolling_route_list() -> (
    None
):
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
    assert (
        "flex-shrink: 0"
        in css[css.index(".mode-tabs {") : css.index(".mode-tabs button {")]
    )


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
