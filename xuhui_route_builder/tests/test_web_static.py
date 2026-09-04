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
    assert "$lifeIndicesNeedHourlyRefresh = $false" in launcher
    assert (
        "Test-RecordExpired -Record $indexRecord -Now $now -RefreshMarginMinutes 5"
        in launcher
    )
    assert "$lifeIndicesNeedHourlyRefresh `" in launcher
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
    assert "Get-StartupEnvironmentRefreshTier" in launcher
    assert "$startupCacheMaxAgeMinutes = 30" in launcher
    assert "Test-EnvironmentDashboardCacheFresh" in launcher
    assert "$age.TotalMinutes -lt $MaxAgeMinutes" in launcher
    assert "环境数据缓存仍有效" in launcher
    assert "Show-StationRefreshSummary -Dashboard $currentDashboard" in launcher
    assert "Show-StationRefreshSummary" in launcher
    assert "环境数据已发布，状态：" in launcher
    assert "环境数据未生成新快照" in launcher
    assert "站点 $stationId" in launcher
    assert "temporal_weight_factor" in launcher
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
    assert "startup_cache_max_age_minutes=30" in launcher
    assert 'action == "startup-cache-fresh"' in launcher
    assert "age_seconds < max_age_minutes * 60" in launcher
    assert "life_indices_need_hourly_refresh = any(" in launcher
    assert "expired(item, now, margin_minutes=5)" in launcher
    assert (
        'life_indices_need_hourly_refresh\n    or expired(current.get("aqi"), now, margin_minutes=5)'
        in launcher
    )
    assert "环境数据缓存仍有效" in launcher
    assert 'print_refresh_summary "cache"' in launcher
    assert 'refresh_environment "startup"' in launcher
    assert "print_refresh_summary" in launcher
    assert "环境数据已发布，状态：" in launcher
    assert "环境数据未生成新快照" in launcher
    assert "temporal_weight_factor" in launcher
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


def test_health_map_wires_a_static_place_layer_without_replacing_route_flows() -> None:
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    assert "showHealthMapPlaces," in main_js
    assert "showHealthMapPlaces(map, data.entries, data.pois);" in main_js
    assert "new AMap.LabelsLayer" in map_js
    assert "new AMap.LabelMarker" in map_js
    assert "interactive: false" in map_js
    assert "planner = renderRoutePlanner(catalog" in main_js
    assert "createRecommendationMapController(map" in main_js


def test_product_toolbar_owns_the_single_location_mode_environment_and_profile_entries() -> (
    None
):
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    toolbar = html[
        html.index('<header class="product-toolbar"') : html.index("</header>")
        + len("</header>")
    ]

    for element_id in [
        "locationInput",
        "sportModeTabs",
        "environmentPanel",
        "profileSettingsButton",
    ]:
        assert f'id="{element_id}"' in toolbar
        assert html.count(f'id="{element_id}"') == 1

    assert "选一条适合当下环境的城市运动路线" not in html
    assert 'class="route-search-shell"' in toolbar
    assert '<summary class="sport-mode-trigger"' in toolbar
    assert 'class="sport-mode-trigger__label">步行</span>' in toolbar
    assert 'class="sport-mode-menu"' in toolbar
    assert 'id="locationInput" type="search" placeholder="搜索地点"' in toolbar
    assert 'id="locationCurrentButton"' in toolbar
    assert 'id="locationSuggestions"' in toolbar
    assert "AMap.Geolocation" in html
    assert "AMap.AutoComplete" not in html
    assert "AMap.PlaceSearch" not in html
    assert "./local-tencent-config.js" in html
    assert 'class="profile-action__label">个人档案</span>' in toolbar
    assert 'class="map-layer-button__label">图层</span>' in html
    assert "./styles/recommendation.css?v=20260831-ui-35" in html
    for mode_id, route_mode in [
        ("toolbarWalkMode", "walk"),
        ("toolbarRunMode", "run"),
        ("toolbarBikeMode", "bike"),
    ]:
        assert f'id="{mode_id}"' in toolbar
        assert f'data-route-mode="{route_mode}"' in toolbar


def test_sidebar_exposes_a_persistent_workbench_header_outside_its_body() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    sidebar = html[
        html.index('<aside id="workbenchSidebar"') : html.index(
            '<section class="map-wrap"'
        )
    ]
    header = sidebar[
        sidebar.index('<header id="workbenchHeader"') : sidebar.index("</header>")
        + len("</header>")
    ]
    body = sidebar[
        sidebar.index('<div id="workbenchBody"') : sidebar.rindex("</div>")
        + len("</div>")
    ]

    assert 'data-collapsed="false"' in sidebar
    assert 'id="workbenchTitle"' in header
    assert 'aria-live="polite"' in header
    assert ">帮我推荐</h2>" in header
    assert 'id="workbenchQwenButton"' in header
    assert "data-workbench-qwen" in header
    assert 'aria-controls="recommendationView"' in header
    assert 'aria-label="打开千问路线助手"' in header
    assert 'title="千问路线助手"' in header
    assert 'src="./assets/qwen-color.png"' in header
    assert 'id="workbenchNewChatButton"' in header
    assert "data-workbench-new-chat" in header
    assert 'aria-label="新建千问聊天"' in header
    assert 'id="workbenchCollapseButton"' in header
    assert "data-workbench-collapse" in header
    assert 'aria-controls="workbenchBody"' in header
    assert 'aria-expanded="true"' in header
    assert 'class="mode-tabs"' in body
    assert 'id="recommendationView"' in body
    assert 'id="routeSelectionView"' in body
    assert 'id="routeNavigationView"' not in body


def test_environment_and_profile_form_the_right_aligned_toolbar_group() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    environment_start = css.index(".product-toolbar .environment-panel {")
    environment_block = css[environment_start : css.index("}", environment_start)]
    profile_start = css.index(".profile-action {")
    profile_block = css[profile_start : css.index("}", profile_start)]

    assert "margin-left: auto;" in environment_block
    assert "margin-left: auto;" not in profile_block


def test_toolbar_controls_share_a_46px_alignment_grid() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    for selector in [
        ".route-search-shell {",
        ".product-toolbar .environment-toggle {",
        ".profile-action {",
    ]:
        start = css.index(selector)
        block = css[start : css.index("}", start)]
        assert "height: 46px;" in block

    search_start = css.index(".route-search-shell {")
    search_block = css[search_start : css.index("}", search_start)]
    assert "flex: 0 1 520px;" in search_block
    assert "width: clamp(400px, 36vw, 560px);" in search_block
    assert "background: #ffffff;" in search_block

    sport_start = css.index(".product-toolbar .sport-mode-tabs {")
    sport_block = css[sport_start : css.index("}", sport_start)]
    assert "display: block;" in sport_block
    assert "padding: 0;" in sport_block
    assert "border: 0;" in sport_block


def test_location_search_uses_tencent_suggestions_geolocation_and_nearby_refresh() -> (
    None
):
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "AMap.AutoComplete" not in html
    assert "AMap.PlaceSearch" not in html
    assert "AMap.Geolocation" in html
    assert "createTencentSuggestionSearch" in main_js
    assert "createLocationServices" in main_js
    assert "createLocationController" in main_js
    assert "locationControls.current" in main_js
    assert "locationServices.suggest" in main_js
    assert "locationServices.locate" in main_js
    assert "shouldShowCurrentLocationOption" in main_js
    assert "locationControls.current.hidden" in main_js
    assert "refreshNearbyRoutes" in main_js
    assert "createMapPointSelection" in main_js
    assert 'map.amap.on("click"' in main_js
    assert "event.target !== map.amap" not in main_js
    assert "从这里出发" in main_js
    assert "locationSearchButton" not in html + main_js
    assert "locationPickButton" not in html + main_js


def test_toolbar_environment_suggestions_and_start_pin_have_product_styles() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    assert ".environment-toggle__item" in css
    assert ".environment-toggle__aqi-level" in css
    assert ".location-suggestion" in css
    assert ".location-suggestion.is-active" in css
    assert "max-height: min(416px, calc(100vh - 190px));" in css
    assert ".amap-location-candidate" not in css + main_js
    assert ".map-location-confirmation" in css
    assert ".map-location-confirmation__confirm" in css
    marker_start = css.index(".amap-user-location {")
    marker_block = css[marker_start : css.index("}", marker_start)]
    assert "width: 72px;" in marker_block
    assert "height: 48px;" in marker_block
    assert ".amap-user-location__pin" in css
    assert ".amap-user-location__label" in css
    assert "startPointMarkerContent" in map_js
    assert "startPointMarkerContent" in main_js
    assert "amap-user-location--candidate" in map_js
    assert 'ariaLabel = "出发点"' in map_js
    assert '<span class="amap-user-location__label">出发点</span>' in map_js
    assert 'anchor: "bottom-center"' in map_js


def test_product_toolbar_and_workbench_use_the_komoot_visual_shell() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    for token in [
        "--surface-toolbar: #ffffff;",
        "--surface-main: #ffffff;",
        "--surface-brand-soft: #ede9de;",
        "--brand-primary: #4f6814;",
        "--brand-primary-hover: #3f5310;",
        "--ink: #1e2a24;",
        "--muted: #66736c;",
        "--line: rgba(30, 42, 36, 0.12);",
        "--focus: #81964a;",
        "--walk: #197cff;",
    ]:
        assert token in css.lower()
    assert ".product-toolbar" in css
    assert ".product-toolbar__actions" in css
    assert ".workbench-header" in css
    assert ".workbench-header__actions" in css
    assert ".workbench-qwen-button" in css
    assert ".workbench-collapse-button" in css
    assert ".sidebar.is-collapsed .workbench-body" in css
    assert "height: 66px;" in css
    assert "border-radius: 24px;" in css
    assert ".product-toolbar .environment-panel .environment-summary" in css
    assert ".environment-alert-dot" in css
    assert ".profile-action__label" in css
    assert ".map-layer-button__label" in css
    assert ".map-legend" in css
    assert "[hidden]" in css
    assert "display: none !important;" in css

    shell_start = css.index("/* 0830 unified route workspace shell */")
    shell_css = css[shell_start:]
    sidebar_start = shell_css.index(".sidebar {")
    sidebar_block = shell_css[sidebar_start : shell_css.index("}", sidebar_start)]
    collapsed_map = shell_css.index(".app-shell:has(.sidebar.is-collapsed) .map-wrap")
    map_start = shell_css.index("\n.map-wrap {", collapsed_map) + 1
    map_block = shell_css[map_start : shell_css.index("}", map_start)]

    assert "grid-template-columns: minmax(0, 1fr);" in shell_css
    assert "position: absolute;" in sidebar_block
    assert "left: 16px;" in sidebar_block
    assert "border: 0;" in sidebar_block
    assert "margin: 0;" in map_block
    assert "border-radius: 0;" in map_block


def test_xh_logo_uses_the_approved_komoot_olive_palette() -> None:
    logo = (WEB_ROOT / "xh-logo.svg").read_text(encoding="utf-8")

    assert logo.count("#4F6814") == 2
    assert "#B8C88D" in logo
    assert "#0b2856" not in logo.lower()
    assert "#197cff" not in logo.lower()


def test_route_detail_uses_a_vertical_shell_with_the_action_at_the_bottom() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    dock_start = css.index(".route-dock.route-dock--detail {")
    dock_block = css[dock_start : css.index("}", dock_start)]
    head_start = css.index(".route-dock--detail .route-dock__head {")
    head_block = css[head_start : css.index("}", head_start)]
    action_start = css.index(".route-dock__actions {")
    action_block = css[action_start : css.index("}", action_start)]
    mobile_start = css.index("@media (max-width: 980px)", dock_start)
    mobile_end = css.index("@media (max-width: 500px)", mobile_start)
    mobile_detail = css[mobile_start:mobile_end]

    assert "display: flex;" in dock_block
    assert "flex-direction: column;" in dock_block
    assert "left: 436px;" in dock_block
    assert "right: auto;" in dock_block
    assert "border: 0;" in dock_block
    assert "flex-direction: row;" in head_block
    assert "bottom: 0;" in action_block
    assert "z-index: 460;" in mobile_detail


def test_navigation_shell_uses_direct_inline_preview() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    for element_id in [
        "inlineNavigationGuide",
        "inlineNavigationPreviousButton",
        "inlineNavigationNextButton",
        "inlineNavigationEndButton",
    ]:
        assert f'id="{element_id}"' in html

    for removed_element_id in [
        "routeNavigationView",
        "navigationBackButton",
        "navigationRouteName",
        "startInput",
        "startPickButton",
        "navigateButton",
        "startSportButton",
        "navigationRouteSelect",
        "navigationSportModeTabs",
        "startNavigationButton",
        "endNavigationButton",
    ]:
        assert f'id="{removed_element_id}"' not in html

    assert "规划接驳路线" not in html
    assert "进入导航预览" not in html


def test_workbench_shell_keeps_primary_controls_touch_friendly_and_responsive() -> None:
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
    assert ".sidebar.is-collapsed" in css
    assert ".app-shell:has(.sidebar.is-collapsed)" in css
    assert "@media (min-width: 981px) and (max-width: 1180px)" in css
    assert "@media (max-width: 980px)" in css
    assert "@media (max-width: 520px)" in css


def test_frontend_assets_share_a_cache_busting_release_version() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")

    release = "v=20260831-ui-35"
    logo_release = "v=20260904-logo-svg"
    brand_release = "v=20260904-logo-refine"
    runtime_release = "v=20260901-environment-2"
    route_animation_release = "v=20260901-ui-36"
    assert html.count(f"./xh-logo.svg?{logo_release}") == 2
    assert "./xh-logo-full.png?" not in html
    assert f"./styles/main.css?{brand_release}" in html
    assert f"./styles/recommendation.css?{release}" in html
    assert f"./src/main.js?{route_animation_release}" in html
    assert f"./data-loader.js?{runtime_release}" in main_js
    assert f"./navigation-session.js?{release}" in main_js
    assert f"./map.js?{route_animation_release}" in main_js
    assert f"./route-dock.js?{runtime_release}" in main_js
    assert f"./route-ui.js?{runtime_release}" in main_js
    assert f"./recommendation-api.js?{release}" in main_js
    assert f"./recommendation-ui.js?{runtime_release}" in main_js
    assert f"./profile-store.js?{release}" in main_js
    recommendation_ui_js = (WEB_ROOT / "src" / "recommendation-ui.js").read_text(
        encoding="utf-8"
    )
    assert f"./route-card.js?{runtime_release}" in recommendation_ui_js
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")
    assert f"./route-card.js?{runtime_release}" in route_ui_js
    route_card_js = (WEB_ROOT / "src" / "route-card.js").read_text(encoding="utf-8")
    route_dock_js = (WEB_ROOT / "src" / "route-dock.js").read_text(encoding="utf-8")
    route_media_js = (WEB_ROOT / "src" / "route-media.js").read_text(encoding="utf-8")
    assert f"./route-media.js?{release}" in route_card_js
    assert f"./route-media.js?{release}" in route_dock_js
    assert f"../../data/web/route_media_manifest.json?{release}" in route_media_js
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


def test_runtime_config_and_environment_assets_use_current_release() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    environment_release = "v=20260901-environment-2"
    route_animation_release = "v=20260901-ui-36"
    assert f"./local-amap-config.js?{environment_release}" in html
    assert f"./local-tencent-config.js?{environment_release}" in html
    assert f"./src/main.js?{route_animation_release}" in html
    assert f"./environment-ui.js?{environment_release}" in main_js


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


def test_recommendation_home_disables_browse_route_previews_by_default() -> None:
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")

    assert "if (resultRoutes.length)" in main_js
    assert "const RECOMMENDATION_MAP_CARDS_ENABLED = false;" in main_js
    assert "planner.showBrowsePreviews();" in main_js
    assert "clearRouteResults(map);" in main_js


def test_product_shell_separates_recommendation_from_compact_route_browsing() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    for element_id in [
        "recommendationTab",
        "browseTab",
        "recommendationView",
        "sportModeTabs",
        "distanceFilter",
        "preferenceFilter",
        "browseRouteList",
        "browseRouteEmpty",
    ]:
        assert f'id="{element_id}"' in html

    for removed_id in [
        "routeSelectionTab",
        "routeNavigationTab",
        "zoneFilter",
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
    assert "route-navigation-view" not in html
    assert "startInput" not in html
    assert "endInput" not in html
    assert "waypointInput" not in html
    assert "navigationModeSummary" not in html
    assert "startSportButton" not in html
    assert "filterCandidateRoutes" in route_ui_js
    assert "onNavigate" in route_ui_js
    assert "selectBestRoute" in route_ui_js
    assert "renderBrowseRouteList" in route_ui_js
    assert "data-route-mode" in html
    assert "createRouteCard" in route_ui_js
    assert "updateModeCounts(catalog, controls)" in route_ui_js
    assert (
        'tab.setAttribute("aria-label", `${modeLabel}，${routes.length} 条路线`);'
        in route_ui_js
    )
    assert 'tab.querySelector("span")' not in route_ui_js
    assert "routeShapeCounts" not in route_ui_js
    assert "30 条" not in html
    assert "90 条城市运动候选路线" not in html
    assert "休息与补给" in html
    assert '<option value="coffee">咖啡</option>' in html
    assert '<option value="toilet">公共厕所</option>' in html
    assert '<option value="convenience">便利补给</option>' in html


def test_product_tabs_and_sport_filters_expose_complete_accessibility_state() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'class="mode-tabs" role="tablist"' in html
    assert 'aria-controls="recommendationView"' in html
    assert 'aria-controls="routeSelectionView"' in html
    assert 'role="tabpanel"' in html
    assert 'id="sportModeTabs" class="sport-mode-tabs"' in html
    assert 'class="sport-mode-menu" role="group"' in html
    assert 'aria-pressed="true"' in html
    assert "aria-selected" in main_js
    assert 'event.key === "ArrowRight"' in main_js
    assert 'setAttribute("aria-pressed"' in route_ui_js
    assert 'id="workbenchTitle"' in html
    assert 'id="workbenchQwenButton"' in html


def test_small_screen_uses_full_map_with_overlay_drawer_and_visible_action() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    mobile_css = css[css.rindex("@media (max-width: 980px)") :]
    assert "position: fixed" in mobile_css
    assert "height: 100dvh" in mobile_css
    assert "inset: 0" in mobile_css
    assert "max-height: min(76dvh, 680px)" in mobile_css
    assert ".browse-controls .two-columns" in mobile_css
    assert ".route-dock__navigate" in css
    assert "position: sticky" in mobile_css


def test_preference_filters_use_real_nearby_pois_only() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'id="preferenceFilter"' in html
    assert "PREFERENCE_KEYWORDS" not in route_ui_js
    assert "preferences.every((preference) => hits.has(preference))" in route_ui_js
    assert "route.nearby_pois" in route_ui_js
    assert "route.preference_hits" not in route_ui_js
    assert 'controls.preferenceFilter.value === "all"' in route_ui_js
    assert "[controls.preferenceFilter.value]" in route_ui_js


def test_route_browser_uses_shared_cards_and_updates_preview_with_filters() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (WEB_ROOT / "src" / "main.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")

    assert 'id="routeSelect"' not in html
    assert 'id="browseRouteList"' in html
    assert 'id="browseRouteEmpty"' in html
    assert 'id="routeTabs"' not in html
    assert 'id="resultTabs"' not in html
    assert "地图中的路线" in html
    assert "createRouteCard" in route_ui_js
    assert "options.onRouteMetrics?.(route)" in route_ui_js
    assert "restoreBrowseOverview()" in route_ui_js
    assert "renderBrowseRouteList" in route_ui_js
    assert "initializeRouteSelection" in route_ui_js
    assert (
        'controls.distanceFilter.addEventListener("change", refreshPreview)'
        in route_ui_js
    )
    assert (
        'controls.preferenceFilter.addEventListener("change", refreshPreview)'
        in route_ui_js
    )
    assert "onPreviewRoutes(routes, onSelectRoute, onPreviewRoute)" in main_js
    assert "planner.restoreBrowseOverview()" in main_js
    assert (
        "showSingleRoute(map, feature, data.entries, data.pois, selectedPreferences)"
        in main_js
    )
    assert "showRouteResults(map, routeFeatures" not in main_js


def test_map_draws_a_thin_single_route_with_landmark_markers() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")

    assert "export function showSingleRoute" in map_js
    assert '"start-end" : "start"' in map_js
    assert 'role: "end"' in map_js
    assert 'role: "landmark"' in map_js
    assert "routeSemanticWaypoints" in map_js
    assert "weight: 4" in map_js
    assert ".amap-route-marker" in css
    assert ".amap-route-option" in css


def test_map_uses_route_shape_and_real_waypoint_coordinates() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")
    dock_js = (WEB_ROOT / "src" / "route-dock.js").read_text(encoding="utf-8")

    assert 'bike: { color: "#6F5AB7"' in map_js
    assert '["strict_loop", "loop"].includes(properties.route_shape)' in map_js
    assert 'label: isLoop ? "A/B" : "A"' in map_js
    assert "ordered_nodes" in dock_js
    assert "node?.node_name || node?.name" in dock_js
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


def test_xuhui_boundary_uses_a_visible_neutral_green_outline() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")
    boundary_block = map_js[
        map_js.index("export function drawBoundary") : map_js.index(
            "export function showRouteResults"
        )
    ]

    assert 'strokeColor: "#5B6C63"' in boundary_block
    assert "strokeWeight: 3" in boundary_block
    assert "strokeOpacity: 0.78" in boundary_block
    assert "fillOpacity: 0.04" in boundary_block


def test_web_loads_pois_and_supports_direct_navigation_preview() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    data_loader_js = (WEB_ROOT / "src" / "data-loader.js").read_text(encoding="utf-8")
    route_ui_js = (WEB_ROOT / "src" / "route-ui.js").read_text(encoding="utf-8")
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    for element_id in [
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
        "startPickButton",
        "navigationModeSummary",
        "startSportButton",
        "routeNavigationView",
    ]:
        assert f'id="{removed_element_id}"' not in html

    assert "poi_catalog.json" in data_loader_js
    assert "nearby_pois" in route_ui_js
    assert "preference_hits" not in route_ui_js
    assert "startDirectNavigation" in route_ui_js
    assert "enablePointPicker" in map_js
    assert "setNavigationPoint" in map_js
    assert "navigationServiceMode" in map_js
    assert "focusSportRoute" in map_js
    assert "previewSportRoute" in map_js
    assert "navigationPlanFromResult" in map_js
    assert "AMap.Driving" not in html
    assert 'addEventListener("click"' in map_js
    assert "containerToLngLat" in map_js


def test_sidebar_route_picker_uses_an_independent_scrolling_route_list() -> None:
    css = (WEB_ROOT / "styles" / "main.css").read_text(encoding="utf-8")
    selection_block = css[
        css.index(".route-selection-view.active {") : css.index(".field-grid {")
    ]
    list_start = css.index(".browse-route-list {")
    list_block = css[list_start : css.index("}", list_start)]

    assert (
        "grid-template-rows: max-content max-content minmax(0, 1fr);" in selection_block
    )
    assert "overflow: hidden;" in selection_block
    assert "min-height: 0;" in list_block
    assert "grid-row: 2;" in list_block
    assert "overflow-y: auto;" in list_block


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
    assert (
        "grid-template-rows: max-content max-content minmax(0, 1fr);" in selection_block
    )
    assert "overflow: hidden;" in selection_block


def test_map_module_uses_amap_and_hides_raw_entry_and_poi_points() -> None:
    map_js = (WEB_ROOT / "src" / "map.js").read_text(encoding="utf-8")

    assert "AMap.Map" in map_js
    assert "AMap.GeoJSON" in map_js
    assert "AMap.Polyline" in map_js
    assert "L." not in map_js
    assert "amap-entry-dot" not in map_js
    assert "amap-poi-dot" not in map_js
    assert "relatedEntryIds" not in map_js
    for route_mode in ["run", "walk", "bike", "access"]:
        assert route_mode in map_js
