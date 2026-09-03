import {
  loadEnvironmentDashboard,
  loadJson,
  startEnvironmentDashboardPolling,
} from "./data-loader.js?v=20260901-environment-2";
import {
  buildRouteExposureModel,
  createEnvironmentPanel,
} from "./environment-ui.js?v=20260901-environment-2";
import {
  beginInlineNavigation,
  clearInlineNavigation,
  clearRouteResults,
  createMap,
  createRecommendationMapController,
  drawBoundary,
  endNavigationSession,
  fitBoundaryView,
  highlightRoutePreview,
  planNavigation,
  setBaseMapMode,
  showHealthMapPlaces,
  showUserLocation,
  showRoutePreviews,
  showSingleRoute,
  startPointMarkerContent,
} from "./map.js?v=20260901-ui-36";
import { createNavigationController } from "./navigation-session.js?v=20260831-ui-35";
import {
  buildLocalLocationCandidates,
  createLocationServices,
  createLocationController,
  createMapPointSelection,
  createTencentSuggestionSearch,
  shouldShowCurrentLocationOption,
} from "./location-control.js?v=20260831-ui-35";
import { loadHealthProfile, saveHealthProfile, HEALTH_PROFILE_STORAGE_KEY } from "./profile-store.js?v=20260831-ui-35";
import { createRecommendationApi } from "./recommendation-api.js?v=20260831-ui-35";
import {
  DEFAULT_RECOMMENDATION_LOCATION,
  buildInitialRecommendationResult,
  createProfileDialog,
  createRecommendationUI,
} from "./recommendation-ui.js?v=20260901-environment-2";
import { buildRouteDockSource, createRouteDock } from "./route-dock.js?v=20260901-environment-2";
import {
  isMapLocationSelectionAllowed,
  renderRoutePlanner,
} from "./route-ui.js?v=20260901-environment-2";

const RECOMMENDATION_MAP_CARDS_ENABLED = false;
const LOCAL_BOOTSTRAP_QUESTIONNAIRE = createBootstrapQuestionnaire();

async function bootstrap() {
  const recommendationApi = createRecommendationApi();
  const mapPromise = createMap("map");
  const routeDataPromise = loadBootstrapRouteData();
  const environmentPromise = loadEnvironmentDashboard().catch((error) => {
    console.warn("环境数据后台加载失败，先显示本地路线", { error });
    return null;
  });
  const questionnairePromise = recommendationApi.questionnaire()
    .then((value) => ({ value, error: null }))
    .catch((error) => ({ value: null, error }));
  const map = await mapPromise;
  const data = await routeDataPromise;
  const uiState = {
    productView: "recommendation",
    chatOpen: false,
    sidebarCollapsed: false,
    detailSource: null,
  };
  let planner = null;
  let recommendationUI = null;
  let questionnaire = LOCAL_BOOTSTRAP_QUESTIONNAIRE;
  const routeDock = createRouteDock(undefined, {
    async onNavigate(route) {
      const routeId = route?.properties?.route_id || route?.route_id;
      const origin = currentLocation;
      if (!routeId) {
        const error = new Error("路线详情缺少 route_id。");
        console.error("直接导航启动失败", {
          routeId: null,
          origin,
          status: map.navigation.state,
          error,
        });
        throw error;
      }
      if (!origin) {
        const error = new Error("尚未确认出发位置，请先使用顶部地点搜索。");
        console.error("直接导航启动失败", {
          routeId,
          origin: null,
          status: map.navigation.state,
          error,
        });
        throw error;
      }
      try {
        return await planner.startDirectNavigation(routeId, origin);
      } catch (error) {
        console.error("直接导航启动失败", {
          routeId,
          origin,
          status: map.navigation.state,
          error,
        });
        throw error;
      }
    },
    onClose({ source, routeId }) {
      if (!planner?.endNavigationPreview()) {
        stopInlineNavigation();
        endNavigationSession(map);
      }
      uiState.detailSource = null;
      recommendationUI?.setDetailOpen(false);
      if (source !== uiState.productView) {
        routeDock.hide();
        renderProductView();
        syncWorkbench();
        return;
      }
      if (source === "recommendation") {
        if (recommendationUI?.returnToOverview) recommendationUI.returnToOverview();
        else recommendationMap.showOverview();
      } else if (source === "browse") {
        planner.restoreBrowseOverview();
      } else {
        console.warn("路线详情关闭来源未知", { source, routeId });
      }
      document.querySelector(`[data-route-id="${routeId}"]`)?.focus?.();
      syncWorkbench();
    },
  });
  const routeFeaturesById = new Map(data.routes.features.map((feature) => [feature.properties.route_id, feature]));
  const catalog = enrichCatalog(data.catalog, data.entries);
  const guide = inlineNavigationGuideControls();
  const environmentContainer = document.querySelector("#environmentPanel");
  const recommendationContainer = document.querySelector("#recommendationView");
  const selectionView = document.querySelector("#routeSelectionView");
  const modeTabs = [...document.querySelectorAll("[data-product-view]")];
  const workbench = getWorkbenchControls();
  const locationControls = getLocationControls();
  const hadSavedProfile = Boolean(globalThis.localStorage?.getItem?.(HEALTH_PROFILE_STORAGE_KEY));
  let healthProfile = loadHealthProfile();
  let currentLocation = { ...DEFAULT_RECOMMENDATION_LOCATION };
  let locationCandidates = [];
  let activeLocationCandidateIndex = 0;
  let locationSearchRevision = 0;
  let locationSearchTimer = null;
  const locationServices = createLocationServices(map, {
    localCandidates: buildLocalLocationCandidates(data.entries, data.pois),
    searchSuggestions: createTencentSuggestionSearch({
      key: globalThis.XUHUI_TENCENT_SEARCH_KEY,
    }),
  });
  const locationController = createLocationController({
    initialLocation: currentLocation,
    onCommit: (location) => commitLocation(location),
  });
  let mapLocationCandidateMarker = null;
  let mapLocationInfoWindow = null;
  let mapLocationRevision = 0;
  const mapPointSelection = createMapPointSelection({
    onConfirm: (location) => locationController.commitCandidate(location),
  });
  let environmentGeneratedAt = data.environmentDashboard?.metadata?.generated_at || null;
  let environmentPanel = createEnvironmentPanel(environmentContainer, data.environmentDashboard);
  function applyEnvironmentDashboard(nextDashboard) {
    if (!nextDashboard) return;
    const nextGeneratedAt = nextDashboard?.metadata?.generated_at || null;
    if (nextGeneratedAt && nextGeneratedAt === environmentGeneratedAt) return;
    const wasOpen = environmentContainer.classList.contains("is-expanded");
    data.environmentDashboard = nextDashboard;
    environmentGeneratedAt = nextGeneratedAt;
    environmentPanel.destroy();
    environmentPanel = createEnvironmentPanel(environmentContainer, nextDashboard);
    environmentPanel.setOpen(wasOpen);
    recommendationUI?.refreshEnvironment();
    if (recommendationUI) refreshNearbyRoutes();
  }
  void environmentPromise.then(applyEnvironmentDashboard);
  startEnvironmentDashboardPolling(applyEnvironmentDashboard);
  let activeNavigation = null;
  let recommendationFeatures = [];

  const recommendationMap = createRecommendationMapController(map, {
    onRouteHover(routeId) {
      recommendationUI?.setHoveredRoute(routeId);
    },
    onRouteSelect(routeId) {
      recommendationUI?.selectRoute(routeId);
    },
  });

  const navigationController = createNavigationController({
    onProgress(progress) {
      renderInlineNavigationProgress(guide, progress);
    },
  });

  function stopInlineNavigation() {
    if (navigationController.getSession()?.status === "previewing") {
      navigationController.stop();
    }
    clearInlineNavigation(map);
    hideInlineNavigationGuide(guide);
    activeNavigation = null;
  }

  guide.previousButton.addEventListener("click", () => navigationController.previous());
  guide.nextButton.addEventListener("click", () => navigationController.next());
  guide.endButton.addEventListener("click", () => {
    if (!planner?.endNavigationPreview()) {
      stopInlineNavigation();
      endNavigationSession(map);
    }
  });

  drawBoundary(map, data.boundary);
  showHealthMapPlaces(map, data.entries, data.pois);
  planner = renderRoutePlanner(catalog, {
    getRouteEnvironment(routeId) {
      return buildRouteExposureModel(data.environmentDashboard, routeId);
    },
    onPreviewRoute(routeId) {
      highlightRoutePreview(map, routeId);
    },
    onPreviewRoutes(routes, onSelectRoute, onPreviewRoute) {
      const features = routes
        .map((route) => routeFeaturesById.get(route.route_id))
        .map((feature) => featureWithEnvironment(feature, data.environmentDashboard))
        .filter(Boolean);
      if (features.length !== routes.length) {
        console.warn("部分候选路线缺少地图路径数据", {
          requestedCount: routes.length,
          renderedCount: features.length,
        });
      }
      showRoutePreviews(map, features, onSelectRoute, onPreviewRoute);
      uiState.detailSource = null;
      routeDock.hide();
    },
    onShowRoute(route, selectedPreferences) {
      stopInlineNavigation();
      endNavigationSession(map);
      showRouteFeature(map, routeFeaturesById, route.route_id, data, selectedPreferences);
    },
    onClearRoutes() {
      stopInlineNavigation();
      endNavigationSession(map);
      clearRouteResults(map);
      uiState.detailSource = null;
      routeDock.hide();
    },
    onSelect(routeId) {
      stopInlineNavigation();
      endNavigationSession(map);
      showRouteFeature(map, routeFeaturesById, routeId, data);
    },
    onNavigate(request) {
      return planNavigation(map, request);
    },
    onStartInlineNavigation(payload) {
      stopInlineNavigation();
      try {
        beginInlineNavigation(map, payload.plan);
        activeNavigation = payload;
        showInlineNavigationGuide(guide, payload.plan);
        navigationController.start(payload.plan);
      } catch (error) {
        clearInlineNavigation(map);
        hideInlineNavigationGuide(guide);
        activeNavigation = null;
        throw error;
      }
    },
    onEndInlineNavigation() {
      stopInlineNavigation();
      endNavigationSession(map);
    },
    onRouteMetrics(route) {
      if (route) {
        uiState.detailSource = "browse";
        routeDock.show({
          route,
          environment: buildRouteExposureModel(data.environmentDashboard, route.route_id),
          dashboard: data.environmentDashboard,
          targetTime: "now",
          source: "browse",
          objectiveHighlights: [],
          qwenAdvantages: [],
          qwenSuggestions: [],
          explanationSource: "route_data",
        });
      } else {
        uiState.detailSource = null;
        routeDock.hide();
      }
    },
  });

  const profileDialog = createProfileDialog({
    host: document.querySelector("#profileModalHost"),
    profile: healthProfile,
    onSave(nextProfile) {
      healthProfile = saveHealthProfile(nextProfile);
      recommendationUI?.setProfile(healthProfile);
    },
  });

  recommendationUI = createRecommendationUI({
    container: recommendationContainer,
    filterHost: document.querySelector(".map-wrap"),
    questionnaire,
    profile: healthProfile,
    location: currentLocation,
    getRouteEnvironment: (routeId) => buildRouteExposureModel(data.environmentDashboard, routeId),
    onRecommend: (profile) => recommendationApi.recommend(profile),
    onInterpretIntent: (request) => recommendationApi.interpretIntent(request),
    onReloadQuestionnaire: async () => {
      const nextQuestionnaire = await recommendationApi.questionnaire();
      questionnaire = nextQuestionnaire;
      return nextQuestionnaire;
    },
    shouldSelectRoute: () => uiState.productView === "recommendation" || uiState.chatOpen,
    onChatStateChange(open) {
      uiState.chatOpen = Boolean(open);
      if (!uiState.chatOpen && uiState.detailSource === "recommendation") {
        uiState.detailSource = null;
        routeDock.hide();
      }
      renderProductView();
      syncWorkbench();
    },
    onRouteModeChange(mode) {
      syncRouteModeControls(mode);
    },
    onShowRoutes(routes, context = {}) {
      uiState.productView = "recommendation";
      const chatResult = context.source === "chat" || recommendationUI.isChatOpen();
      if (!chatResult) uiState.chatOpen = false;
      recommendationFeatures = recommendationFeaturesFromResult(routes, routeFeaturesById);
      recommendationMap.showRoutes(recommendationFeatures, data.entries, data.pois, recommendationUI.getAnswers().interests);
      uiState.detailSource = null;
      recommendationUI.setDetailOpen(false);
      routeDock.hide();
      renderProductView();
      syncWorkbench();
    },
    onPreviewRoute(routeId, route) {
      if (routeId) recommendationMap.previewRoute(routeId);
      else recommendationMap.clearPreview(recommendationRouteId(route));
    },
    onSelectRoute(routeId, route) {
      recommendationMap.focusRoute(routeId);
      const routeFeature = routeFeaturesById.get(routeId);
      if (!routeFeature) {
        console.error("推荐路线缺少地图路径数据", { routeId });
        routeDock.hide();
        return;
      }
      uiState.detailSource = "recommendation";
      recommendationUI.setDetailOpen(true);
      routeDock.show({
        route: buildRouteDockSource(routeFeature, route),
        environment: buildRouteExposureModel(data.environmentDashboard, routeId),
        dashboard: data.environmentDashboard,
        targetTime: recommendationUI.getAnswers(),
        source: "recommendation",
        objectiveHighlights: [],
        qwenAdvantages: route?.advantages,
        qwenSuggestions: route?.suggestions,
        explanationSource: route?.explanationSource,
      });
      syncWorkbench();
    },
    onReturnRouteOverview() {
      if (recommendationFeatures.length) recommendationMap.showOverview();
      routeDock.hide();
      recommendationUI.setDetailOpen(false);
    },
    onRestartRecommendation() {
      uiState.detailSource = null;
      routeDock.hide();
      recommendationUI.setDetailOpen(false);
      showRecommendationIdleMap();
    },
  });
  commitLocation(currentLocation, { refreshRoutes: false });
  const initialResult = buildInitialRecommendationResult({
    catalog,
    questionnaire,
    answers: recommendationUI.getAnswers(),
    location: currentLocation,
    getRouteEnvironment: (routeId) => buildRouteExposureModel(data.environmentDashboard, routeId),
  });
  recommendationUI.showResult(initialResult);
  void questionnairePromise.then(({ value, error }) => {
    if (value) {
      questionnaire = value;
      recommendationUI.setQuestionnaire(value);
    } else {
      console.warn("推荐问卷后台加载失败，继续使用本地默认配置", { error });
    }
    refreshNearbyRoutes();
  });

  document.querySelector("#profileSettingsButton").addEventListener("click", () => profileDialog.open());
  if (!hadSavedProfile) profileDialog.open();

  modeTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => setProductView(tab.dataset.productView));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const nextTab = modeTabs[(index + direction + modeTabs.length) % modeTabs.length];
      nextTab.focus();
      setProductView(nextTab.dataset.productView);
    });
  });
  workbench.qwenButton.addEventListener("click", () => {
    if (uiState.sidebarCollapsed) setSidebarCollapsed(false);
    recommendationUI.newChat();
  });
  workbench.newChatButton.addEventListener("click", () => {
    recommendationUI.newChat();
  });
  workbench.collapseButton.addEventListener("click", () => {
    setSidebarCollapsed(!uiState.sidebarCollapsed);
  });
  workbench.chatCloseButton.addEventListener("click", () => {
    recommendationUI.closeChat();
  });
  bindLocationControls();
  bindMapLocationPicker();
  bindRouteModeControls();
  bindLayerControls();
  setProductView("recommendation");

  function setProductView(view) {
    const nextView = view === "browse" ? "browse" : "recommendation";
    const viewChanged = nextView !== uiState.productView;
    uiState.productView = nextView;
    if (uiState.chatOpen) recommendationUI.closeChat();
    if (viewChanged) {
      uiState.detailSource = null;
      routeDock.hide();
    }
    renderProductView();
    if (uiState.productView === "browse") {
      planner.showBrowse();
    } else {
      const resultRoutes = recommendationUI.getResultRoutes();
      if (resultRoutes.length) {
        recommendationFeatures = recommendationFeaturesFromResult(resultRoutes, routeFeaturesById);
        recommendationMap.showRoutes(recommendationFeatures, data.entries, data.pois, recommendationUI.getAnswers().interests);
      } else {
        showRecommendationIdleMap();
      }
      const routeId = recommendationUI.getCurrentRouteId();
      if (routeId) recommendationMap.focusRoute(routeId);
    }
    syncWorkbench();
  }

  function showRecommendationIdleMap() {
    recommendationFeatures = [];
    if (RECOMMENDATION_MAP_CARDS_ENABLED) {
      planner.showBrowsePreviews();
      return;
    }
    clearRouteResults(map);
    fitBoundaryView(map);
  }

  function renderProductView() {
    const visibleView = uiState.chatOpen ? "recommendation" : uiState.productView;
    modeTabs.forEach((tab) => {
      const active = tab.dataset.productView === uiState.productView;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    recommendationContainer.hidden = visibleView !== "recommendation";
    recommendationContainer.classList.toggle("active", visibleView === "recommendation");
    recommendationUI?.setFiltersVisible(visibleView === "recommendation" && !uiState.chatOpen);
    selectionView.hidden = visibleView !== "browse";
    selectionView.classList.toggle("active", visibleView === "browse");
    document.querySelector(".mode-tabs").hidden = uiState.chatOpen;
  }

  function syncWorkbench() {
    recommendationUI?.setDetailOpen(uiState.detailSource === "recommendation");
    workbench.title.textContent = uiState.chatOpen
      ? "千问路线助手"
      : uiState.productView === "browse" ? "浏览路线" : "帮我推荐";
    workbench.qwenButton.hidden = uiState.chatOpen;
    workbench.newChatButton.hidden = !uiState.chatOpen;
    workbench.chatCloseButton.hidden = !uiState.chatOpen;
    workbench.sidebar.classList.toggle("is-collapsed", uiState.sidebarCollapsed);
    workbench.sidebar.dataset.collapsed = String(uiState.sidebarCollapsed);
    workbench.collapseButton.setAttribute("aria-expanded", String(!uiState.sidebarCollapsed));
    workbench.collapseButton.setAttribute("aria-label", uiState.sidebarCollapsed ? "展开路线工作台" : "折叠路线工作台");
    workbench.collapseButton.title = uiState.sidebarCollapsed ? "展开工作台" : "折叠工作台";
  }

  function setSidebarCollapsed(collapsed) {
    const nextCollapsed = Boolean(collapsed);
    uiState.sidebarCollapsed = nextCollapsed;
    if (nextCollapsed && uiState.detailSource) {
      routeDock.dismiss();
    }
    syncWorkbench();
    globalThis.requestAnimationFrame?.(() => map.amap.resize?.());
    globalThis.setTimeout?.(() => map.amap.resize?.(), 200);
  }

  function commitLocation(location, { refreshRoutes = true } = {}) {
    currentLocation = location;
    locationControls.input.value = "";
    syncCurrentLocationOption();
    locationCandidates = [];
    activeLocationCandidateIndex = 0;
    renderLocationSuggestions();
    clearMapLocationCandidate();
    locationControls.status.textContent = "";
    showUserLocation(map, location);
    recommendationUI.setLocation(location);
    setLocationEditorOpen(false);
    if (refreshRoutes) refreshNearbyRoutes();
    return location;
  }

  function bindLocationControls() {
    syncCurrentLocationOption();
    locationControls.toggle.addEventListener("click", () => {
      const open = locationControls.editor.hidden;
      setLocationEditorOpen(open);
    });
    locationControls.input.addEventListener("focus", () => setLocationEditorOpen(true));
    locationControls.input.addEventListener("input", () => {
      const query = locationControls.input.value;
      syncCurrentLocationOption(query);
      locationController.setQuery(query);
      setLocationEditorOpen(true);
      queueLocationSuggestions(query);
    });
    locationControls.input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!locationCandidates.length) return;
        event.preventDefault();
        const offset = event.key === "ArrowDown" ? 1 : -1;
        activeLocationCandidateIndex = (
          activeLocationCandidateIndex + offset + locationCandidates.length
        ) % locationCandidates.length;
        renderLocationSuggestions();
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        submitLocationInput();
        return;
      }
      if (event.key === "Escape") setLocationEditorOpen(false);
    });
    locationControls.current.addEventListener("click", locateCurrentPosition);
    document.addEventListener("click", (event) => {
      if (!event.target.closest?.(".route-search-shell")) setLocationEditorOpen(false);
    });
  }

  function syncCurrentLocationOption(query = locationControls.input.value) {
    locationControls.current.hidden = !shouldShowCurrentLocationOption(query);
  }

  function bindMapLocationPicker() {
    map.amap.on("click", (event) => {
      const navigationActive = Boolean(activeNavigation)
        || ["planning", "planned", "previewing"].includes(map.navigation.state);
      if (!isMapLocationSelectionAllowed({
        detailOpen: Boolean(uiState.detailSource),
        navigationActive,
      })) return;
      const lng = Number(event?.lnglat?.getLng?.() ?? event?.lnglat?.lng);
      const lat = Number(event?.lnglat?.getLat?.() ?? event?.lnglat?.lat);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) return;
      showMapLocationCandidate({ label: "已选位置", lng_gcj02: lng, lat_gcj02: lat });
    });
  }

  function showMapLocationCandidate(point) {
    clearMapLocationCandidate();
    const candidate = mapPointSelection.preview(point);
    const revision = ++mapLocationRevision;
    const card = document.createElement("section");
    card.className = "map-location-confirmation";
    card.setAttribute("aria-label", "确认路线起点");
    const close = document.createElement("button");
    close.type = "button";
    close.className = "map-location-confirmation__close";
    close.setAttribute("aria-label", "取消地图选点");
    close.textContent = "×";
    const title = document.createElement("strong");
    title.textContent = candidate.label;
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "map-location-confirmation__confirm";
    confirm.textContent = "从这里出发";
    card.append(close, title, confirm);
    close.addEventListener("click", (event) => {
      event.stopPropagation();
      clearMapLocationCandidate();
    });
    confirm.addEventListener("click", (event) => {
      event.stopPropagation();
      mapPointSelection.confirm();
    });

    mapLocationCandidateMarker = new map.AMap.Marker({
      position: [candidate.lng_gcj02, candidate.lat_gcj02],
      content: startPointMarkerContent({ showLabel: false, ariaLabel: "待确认出发点" }),
      anchor: "bottom-center",
      zIndex: 130,
    });
    mapLocationInfoWindow = new map.AMap.InfoWindow({
      isCustom: true,
      content: card,
      closeWhenClickMap: false,
      offset: new map.AMap.Pixel(0, -42),
    });
    map.amap.add(mapLocationCandidateMarker);
    mapLocationInfoWindow.open(map.amap, [candidate.lng_gcj02, candidate.lat_gcj02]);
    locationServices.reverse(candidate).then((resolved) => {
      if (revision !== mapLocationRevision || !mapPointSelection.getCandidate()) return;
      mapPointSelection.preview(resolved);
      title.textContent = resolved.label;
    }).catch((error) => {
      console.warn("地图选点地址解析失败", { point: candidate, error });
    });
  }

  function clearMapLocationCandidate() {
    mapLocationRevision += 1;
    if (mapLocationCandidateMarker) map.amap.remove(mapLocationCandidateMarker);
    mapLocationInfoWindow?.close?.();
    mapLocationCandidateMarker = null;
    mapLocationInfoWindow = null;
    mapPointSelection.cancel();
  }

  function queueLocationSuggestions(query) {
    globalThis.clearTimeout?.(locationSearchTimer);
    const keyword = String(query || "").trim();
    const revision = ++locationSearchRevision;
    if (!keyword) {
      locationCandidates = [];
      locationControls.status.textContent = "";
      renderLocationSuggestions();
      return;
    }
    locationControls.status.textContent = "正在查找地点…";
    locationSearchTimer = globalThis.setTimeout?.(async () => {
      try {
        const candidates = await locationServices.suggest(keyword);
        if (revision !== locationSearchRevision) return;
        locationCandidates = candidates;
        activeLocationCandidateIndex = 0;
        locationControls.status.textContent = candidates.length ? "" : "没有找到匹配地点。";
        renderLocationSuggestions();
      } catch (error) {
        if (revision !== locationSearchRevision) return;
        locationCandidates = [];
        locationControls.status.textContent = errorMessage(error);
        renderLocationSuggestions();
        console.error("地点联想搜索失败", { query: keyword, error });
      }
    }, 220);
  }

  async function submitLocationInput() {
    if (locationCandidates.length) {
      locationController.commitActiveCandidate(locationCandidates, activeLocationCandidateIndex);
      return;
    }
    const query = String(locationControls.input.value || "").trim();
    if (!query) return;
    globalThis.clearTimeout?.(locationSearchTimer);
    const revision = ++locationSearchRevision;
    locationControls.status.textContent = "正在确定地点…";
    try {
      const candidates = await locationServices.suggest(query);
      if (revision !== locationSearchRevision) return;
      locationCandidates = candidates;
      activeLocationCandidateIndex = 0;
      if (!candidates.length) {
        locationControls.status.textContent = "没有找到匹配地点。";
        renderLocationSuggestions();
        return;
      }
      locationController.commitCandidate(candidates[0]);
    } catch (error) {
      if (revision !== locationSearchRevision) return;
      locationControls.status.textContent = errorMessage(error);
      console.error("腾讯地点搜索失败", { query, error });
    }
  }

  async function locateCurrentPosition() {
    locationController.beginLocating();
    locationControls.current.disabled = true;
    locationControls.status.textContent = "正在定位…";
    try {
      locationController.commitGeolocation(await locationServices.locate());
    } catch (error) {
      const state = locationController.failGeolocation(error);
      locationControls.status.textContent = state.error;
      console.error("设备定位失败", { error });
    } finally {
      locationControls.current.disabled = false;
    }
  }

  function renderLocationSuggestions() {
    locationControls.suggestions.replaceChildren(...locationCandidates.map((candidate, index) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = `location-suggestion${index === activeLocationCandidateIndex ? " is-active" : ""}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(index === activeLocationCandidateIndex));
      const name = document.createElement("strong");
      name.textContent = candidate.label;
      const address = document.createElement("small");
      address.textContent = candidate.address || "上海";
      option.append(name, address);
      option.addEventListener("mouseenter", () => {
        activeLocationCandidateIndex = index;
        [...locationControls.suggestions.children].forEach((child, childIndex) => {
          const active = childIndex === index;
          child.classList.toggle("is-active", active);
          child.setAttribute("aria-selected", String(active));
        });
      });
      option.addEventListener("click", () => locationController.commitCandidate(candidate));
      return option;
    }));
  }

  function refreshNearbyRoutes() {
    if (!questionnaire || !recommendationUI) return;
    const result = buildInitialRecommendationResult({
      catalog,
      questionnaire,
      answers: recommendationUI.getAnswers(),
      location: currentLocation,
      getRouteEnvironment: (routeId) => buildRouteExposureModel(data.environmentDashboard, routeId),
    });
    recommendationUI.showResult(result);
  }

  function bindRouteModeControls() {
    const buttons = [...document.querySelectorAll("[data-route-mode]")];
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.routeMode;
        syncRouteModeControls(mode);
        recommendationUI.setRouteMode(mode);
        refreshNearbyRoutes();
      });
    });
  }

  function syncRouteModeControls(mode) {
    const buttons = [...document.querySelectorAll("[data-route-mode]")];
    const selected = buttons.find((button) => button.dataset.routeMode === mode);
    if (!selected) return;
    buttons.forEach((button) => {
      const active = button === selected;
      button.classList.toggle("active", active);
      button.classList.toggle("is-selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
    locationController.setMode(mode);
    locationControls.modeLabel.textContent = selected.querySelector("b")?.textContent || "步行";
    const icon = selected.querySelector("svg")?.cloneNode(true);
    if (icon && locationControls.modeIcon) {
      locationControls.modeIcon.replaceWith(icon);
      locationControls.modeIcon = icon;
    }
    locationControls.modeDetails.open = false;
  }

  function setLocationEditorOpen(open) {
    locationControls.editor.hidden = !open;
    locationControls.toggle.setAttribute("aria-expanded", String(open));
  }

  function bindLayerControls() {
    const button = document.querySelector("#mapLayerButton");
    const legend = document.querySelector("#mapLegend");
    const modeButtons = [...legend.querySelectorAll("[data-base-map-mode]")];
    button.addEventListener("click", () => {
      const open = legend.hidden;
      legend.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    });

    modeButtons.forEach((modeButton) => {
      modeButton.addEventListener("click", () => {
        const mode = modeButton.dataset.baseMapMode;
        setBaseMapMode(map, mode);
        modeButtons.forEach((candidate) => {
          const selected = candidate === modeButton;
          candidate.classList.toggle("is-selected", selected);
          candidate.setAttribute("aria-pressed", String(selected));
        });
      });
    });
  }
}

function getLocationControls() {
  const modeDetails = document.querySelector("#sportModeTabs");
  const modeTrigger = modeDetails.querySelector(".sport-mode-trigger");
  return {
    toggle: document.querySelector("#locationButton"),
    editor: document.querySelector("#locationEditor"),
    input: document.querySelector("#locationInput"),
    current: document.querySelector("#locationCurrentButton"),
    suggestions: document.querySelector("#locationSuggestions"),
    status: document.querySelector("#locationStatus"),
    modeDetails,
    modeTrigger,
    modeLabel: modeTrigger.querySelector(".sport-mode-trigger__label"),
    modeIcon: modeTrigger.querySelector("svg:not(.sport-mode-trigger__chevron)"),
  };
}

function getWorkbenchControls() {
  return {
    sidebar: document.querySelector("#workbenchSidebar"),
    title: document.querySelector("#workbenchTitle"),
    qwenButton: document.querySelector("#workbenchQwenButton"),
    newChatButton: document.querySelector("#workbenchNewChatButton"),
    collapseButton: document.querySelector("#workbenchCollapseButton"),
    chatCloseButton: document.querySelector("#workbenchChatCloseButton"),
  };
}

function inlineNavigationGuideControls() {
  return {
    root: document.querySelector("#inlineNavigationGuide"),
    state: document.querySelector("#inlineNavigationState"),
    instruction: document.querySelector("#inlineNavigationInstruction"),
    remaining: document.querySelector("#inlineNavigationRemaining"),
    duration: document.querySelector("#inlineNavigationDuration"),
    progress: document.querySelector("#inlineNavigationProgress"),
    previousButton: document.querySelector("#inlineNavigationPreviousButton"),
    nextButton: document.querySelector("#inlineNavigationNextButton"),
    endButton: document.querySelector("#inlineNavigationEndButton"),
  };
}

function showInlineNavigationGuide(guide, plan) {
  guide.root.hidden = false;
  guide.root.parentElement.classList.add("inline-navigation-active");
  guide.root.dataset.status = "previewing";
  guide.state.textContent = "导航预览";
  guide.instruction.textContent = plan.steps?.[0]?.instruction || "沿接驳路线前往运动路线起点";
  guide.remaining.textContent = formatDistance(plan.distance);
  guide.duration.textContent = formatDuration(plan.duration);
  guide.progress.style.width = "0%";
}

function renderInlineNavigationProgress(guide, progress) {
  guide.root.hidden = false;
  guide.root.dataset.status = progress.status;
  guide.state.textContent = `第 ${progress.stepNumber} / ${progress.stepCount} 步`;
  guide.instruction.textContent = progress.instruction;
  guide.remaining.textContent = formatDistance(progress.totalDistanceM);
  guide.duration.textContent = formatDuration(progress.totalDurationS);
  guide.progress.style.width = `${Math.round(progress.progressRatio * 100)}%`;
  guide.previousButton.disabled = !progress.canGoPrevious;
  guide.nextButton.disabled = !progress.canGoNext;
}

function hideInlineNavigationGuide(guide) {
  guide.root.hidden = true;
  guide.root.parentElement.classList.remove("inline-navigation-active");
  delete guide.root.dataset.status;
  guide.progress.style.width = "0%";
  guide.previousButton.disabled = true;
  guide.nextButton.disabled = true;
}

function formatDistance(value) {
  const meters = Math.max(0, Number(value || 0));
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value || 0));
  return `${Math.max(0, Math.ceil(seconds / 60))} 分钟`;
}

async function loadBootstrapRouteData() {
  const [boundary, entries, routes, catalog, pois] = await Promise.all([
    loadJson("../data/web/xuhui_boundary.geojson"),
    loadJson("../data/web/xuhui_entries.geojson"),
    loadJson("../data/web/xuhui_routes.geojson"),
    loadJson("../data/web/route_catalog.json"),
    loadJson("../data/web/poi_catalog.json"),
  ]);
  return {
    boundary,
    entries,
    routes,
    catalog,
    pois,
    environmentDashboard: null,
  };
}

function createBootstrapQuestionnaire() {
  return {
    route_modes: [
      bootstrapOption("walk", "步行"),
      bootstrapOption("run", "跑步"),
      bootstrapOption("bike", "骑行"),
    ],
    distance_ranges: {
      walk: [
        bootstrapDistanceRange(700, 1500, 1000),
        bootstrapDistanceRange(1500, 3000, 2500),
        bootstrapDistanceRange(3000, 5000, 4000),
      ],
      run: [
        bootstrapDistanceRange(1000, 3000, 2000),
        bootstrapDistanceRange(3000, 6000, 5000),
        bootstrapDistanceRange(6000, 10000, 8000),
        bootstrapDistanceRange(10000, 14000, 12000),
      ],
      bike: [
        bootstrapDistanceRange(5000, 10000, 8000),
        bootstrapDistanceRange(10000, 20000, 15000),
        bootstrapDistanceRange(20000, 30000, 25000),
      ],
    },
    goals: [
      bootstrapOption("balanced", "综合均衡"),
      bootstrapOption("health_environment", "健康环境"),
      bootstrapOption("distance_training", "固定距离训练"),
      bootstrapOption("relax", "放松"),
      bootstrapOption("scenery", "观景"),
      bootstrapOption("family", "亲子"),
      bootstrapOption("nearby", "就近运动"),
    ],
    experience_levels: [
      bootstrapOption("beginner", "初学"),
      bootstrapOption("regular", "经常运动"),
      bootstrapOption("frequent", "高频训练"),
    ],
    age_groups: [
      bootstrapOption("under_18", "18 岁以下"),
      bootstrapOption("18_39", "18-39 岁"),
      bootstrapOption("40_59", "40-59 岁"),
      bootstrapOption("60_plus", "60 岁及以上"),
      bootstrapOption("undisclosed", "不透露"),
    ],
    areas: [
      bootstrapOption("west_bund", "徐汇滨江"),
      bootstrapOption("shanghai_botanical_garden", "上海植物园"),
      bootstrapOption("xujiahui", "徐家汇"),
      bootstrapOption("longhua", "龙华"),
      bootstrapOption("hengfu", "衡复风貌区"),
      bootstrapOption("caohejing", "漕河泾"),
      bootstrapOption("huajing", "华泾"),
      bootstrapOption("kangjian", "康健"),
    ],
    interests: [
      bootstrapOption("waterfront", "滨水"),
      bootstrapOption("park", "公园"),
      bootstrapOption("quiet", "安静"),
      bootstrapOption("coffee", "咖啡"),
      bootstrapOption("toilet", "厕所"),
      bootstrapOption("convenience", "补给"),
    ],
    sensitivities: [
      bootstrapOption("air", "空气"),
      bootstrapOption("pollen", "花粉"),
      bootstrapOption("heat", "高温"),
      bootstrapOption("noise", "噪声"),
    ],
    target_times: [
      bootstrapOption("now", "现在"),
      bootstrapOption("plus_2h", "两小时后"),
      bootstrapOption("custom", "自定义时间"),
    ],
    search_scopes: [
      bootstrapOption("nearby_3000", "附近 3 公里"),
      bootstrapOption("nearby_5000", "附近 5 公里"),
      bootstrapOption("nearby_8000", "附近 8 公里"),
      bootstrapOption("area", "指定片区"),
      bootstrapOption("all_xuhui", "全徐汇区"),
    ],
    route_shapes: [
      bootstrapOption("any", "不限"),
      bootstrapOption("strict_loop", "环线"),
      bootstrapOption("one_way", "单程"),
    ],
  };
}

function bootstrapOption(value, label) {
  return { value, label };
}

function bootstrapDistanceRange(low, high, target) {
  return {
    value: `${low}_${high}_${target}`,
    label: `${low / 1000}–${high / 1000} 公里`,
    distance_min_m: low,
    target_distance_m: target,
    distance_max_m: high,
  };
}

function showRouteFeature(map, routeFeaturesById, routeId, data, selectedPreferences = []) {
  const feature = routeFeaturesById.get(routeId);
  if (!feature) {
    clearRouteResults(map);
    const message = `路线 ${routeId} 缺少地图路径数据，请刷新页面后重试。`;
    console.error(message, { routeId, loadedFeatureCount: routeFeaturesById.size });
    return;
  }
  showSingleRoute(map, feature, data.entries, data.pois, selectedPreferences);
}

function enrichCatalog(catalog, entries) {
  const entriesById = new Map((entries.features || []).map((entry) => [entry.properties.entry_id, entry.properties]));
  return catalog.map((route) => {
    const startEntry = entriesById.get(route.start_entry_id);
    const endEntry = entriesById.get(route.end_entry_id);
    return {
      ...route,
      start_entry_name: startEntry?.entry_name || "",
      end_entry_name: endEntry?.entry_name || "",
      start_entry_type: startEntry?.entry_type || "",
      end_entry_type: endEntry?.entry_type || "",
      start_entry_location: entryLocation(startEntry),
      end_entry_location: entryLocation(endEntry),
    };
  });
}

function recommendationFeaturesFromResult(routes, routeFeaturesById) {
  const features = (routes || [])
    .map((route) => routeFeaturesById.get(recommendationRouteId(route)))
    .filter(Boolean);
  if (features.length !== (routes || []).length) {
    console.warn("部分推荐路线缺少地图路径数据", {
      requestedCount: (routes || []).length,
      renderedCount: features.length,
    });
  }
  return features;
}

function featureWithEnvironment(feature, dashboard) {
  if (!feature) return null;
  const routeId = feature.properties?.route_id;
  return {
    ...feature,
    properties: {
      ...feature.properties,
      route_environment: buildRouteExposureModel(dashboard, routeId),
    },
  };
}

function recommendationRouteId(route) {
  return route?.route?.route?.route_id || null;
}

function entryLocation(entry) {
  const lng = entry?.lng_gcj02;
  const lat = entry?.lat_gcj02;
  if (typeof lng !== "number" || typeof lat !== "number") {
    return "";
  }
  return `${lng},${lat}`;
}

function errorMessage(error) {
  return error instanceof Error ? error.message : "操作失败，请重试。";
}

bootstrap().catch((error) => {
  console.error("应用启动失败", { error });
  const recommendationView = document.querySelector("#recommendationView");
  if (!recommendationView) return;
  recommendationView.hidden = false;
  recommendationView.textContent = errorMessage(error);
});
