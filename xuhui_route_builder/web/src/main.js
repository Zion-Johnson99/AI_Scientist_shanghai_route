import {
  loadRouteData,
  startEnvironmentDashboardPolling,
} from "./data-loader.js?v=20260830-ui-6";
import {
  buildRouteExposureModel,
  createEnvironmentPanel,
} from "./environment-ui.js?v=20260830-ui-6";
import {
  beginInlineNavigation,
  clearInlineNavigation,
  clearRouteResults,
  createMap,
  createRecommendationMapController,
  drawBoundary,
  enablePointPicker,
  endNavigationSession,
  highlightRoutePreview,
  planNavigation,
  resolveUserLocation,
  showUserLocation,
  showRoutePreviews,
  showSingleRoute,
  startNavigationSession,
} from "./map.js?v=20260830-ui-6";
import { createNavigationController } from "./navigation-session.js?v=20260830-ui-6";
import { loadHealthProfile, saveHealthProfile, HEALTH_PROFILE_STORAGE_KEY } from "./profile-store.js?v=20260830-ui-6";
import { createRecommendationApi } from "./recommendation-api.js?v=20260830-ui-6";
import { createProfileDialog, createRecommendationUI } from "./recommendation-ui.js?v=20260830-ui-6";
import { buildRouteDockSource, createRouteDock } from "./route-dock.js?v=20260830-ui-6";
import { renderRoutePlanner } from "./route-ui.js?v=20260830-ui-6";

const RECOMMENDATION_MAP_CARDS_ENABLED = false;

async function bootstrap() {
  const map = await createMap("map");
  const data = await loadRouteData();
  const recommendationApi = createRecommendationApi();
  const uiState = {
    productView: "recommendation",
    chatOpen: false,
    sidebarCollapsed: false,
    detailSource: null,
  };
  let planner = null;
  let recommendationUI = null;
  let questionnaire = null;
  let questionnaireError = null;
  try {
    questionnaire = await recommendationApi.questionnaire();
  } catch (error) {
    questionnaireError = error;
    console.error("推荐问卷加载失败", { error });
  }
  const routeDock = createRouteDock(undefined, {
    async onNavigate(route) {
      const routeId = route?.properties?.route_id || route?.route_id;
      if (!routeId) {
        console.error("路线详情缺少 route_id", { route });
        return;
      }
      const origin = currentLocation || await requestLocation();
      if (origin) planner.openNavigation(routeId, origin);
    },
    onClose({ source, routeId }) {
      uiState.detailSource = null;
      if (source === "recommendation") {
        uiState.productView = "recommendation";
        uiState.chatOpen = false;
        renderProductView();
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
  const navigationView = document.querySelector("#routeNavigationView");
  const modeTabs = [...document.querySelectorAll("[data-product-view]")];
  const workbench = getWorkbenchControls();
  const locationControls = getLocationControls();
  const hadSavedProfile = Boolean(globalThis.localStorage?.getItem?.(HEALTH_PROFILE_STORAGE_KEY));
  let healthProfile = loadHealthProfile();
  let currentLocation = null;
  let pendingLocationResolver = null;
  let environmentGeneratedAt = data.environmentDashboard?.metadata?.generated_at || null;
  let environmentPanel = createEnvironmentPanel(environmentContainer, data.environmentDashboard);
  startEnvironmentDashboardPolling((nextDashboard) => {
    const nextGeneratedAt = nextDashboard?.metadata?.generated_at || null;
    if (nextGeneratedAt && nextGeneratedAt === environmentGeneratedAt) return;
    const wasOpen = environmentContainer.classList.contains("is-expanded");
    data.environmentDashboard = nextDashboard;
    environmentGeneratedAt = nextGeneratedAt;
    environmentPanel.destroy();
    environmentPanel = createEnvironmentPanel(environmentContainer, nextDashboard);
    environmentPanel.setOpen(wasOpen);
  });
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
      document.querySelector("#navigationStatus").textContent = navigationStatusText(progress);
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
    onPickNavigationPoint(role, onPicked) {
      startNavigationSession(map, onPicked);
      enablePointPicker(map, role);
    },
    onLocationChange(point) {
      commitLocation({ ...point, label: point.label || "地图点" });
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
    onNavigationViewChange(open) {
      if (open) {
        recommendationContainer.hidden = true;
        recommendationContainer.classList.remove("active");
        selectionView.hidden = true;
        navigationView.hidden = false;
        document.querySelector(".mode-tabs").hidden = true;
        return;
      }
      document.querySelector(".mode-tabs").hidden = false;
      setProductView(uiState.productView);
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
    questionnaire,
    profile: healthProfile,
    location: currentLocation,
    onRecommend: (profile) => recommendationApi.recommend(profile),
    onInterpretIntent: (request) => recommendationApi.interpretIntent(request),
    onReloadQuestionnaire: () => recommendationApi.questionnaire(),
    shouldSelectRoute: () => uiState.productView === "recommendation" || uiState.chatOpen,
    onChatStateChange(open) {
      uiState.chatOpen = Boolean(open);
      renderProductView();
      syncWorkbench();
    },
    onShowRoutes(routes) {
      uiState.productView = "recommendation";
      uiState.chatOpen = false;
      recommendationFeatures = recommendationFeaturesFromResult(routes, routeFeaturesById);
      recommendationMap.showRoutes(recommendationFeatures, data.entries, data.pois, recommendationUI.getAnswers().interests);
      uiState.detailSource = null;
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
      routeDock.show({
        route: buildRouteDockSource(routeFeature, route),
        environment: buildRouteExposureModel(data.environmentDashboard, routeId),
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
    },
    onRestartRecommendation() {
      uiState.detailSource = null;
      routeDock.hide();
      showRecommendationIdleMap();
    },
  });
  if (questionnaireError) recommendationUI.showError(questionnaireError);

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
    if (uiState.chatOpen) recommendationUI.closeChat();
    else recommendationUI.openChat();
  });
  workbench.collapseButton.addEventListener("click", () => {
    setSidebarCollapsed(!uiState.sidebarCollapsed);
  });
  bindLocationControls();
  bindRouteModeControls();
  bindLayerControls();
  setProductView("recommendation");

  function setProductView(view) {
    uiState.productView = view === "browse" ? "browse" : "recommendation";
    if (uiState.chatOpen) recommendationUI.closeChat();
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
  }

  function renderProductView() {
    const visibleView = uiState.chatOpen ? "recommendation" : uiState.productView;
    modeTabs.forEach((tab) => {
      const active = tab.dataset.productView === uiState.productView;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    navigationView.hidden = true;
    recommendationContainer.hidden = visibleView !== "recommendation";
    recommendationContainer.classList.toggle("active", visibleView === "recommendation");
    selectionView.hidden = visibleView !== "browse";
    selectionView.classList.toggle("active", visibleView === "browse");
    document.querySelector(".mode-tabs").hidden = uiState.chatOpen;
  }

  function syncWorkbench() {
    workbench.title.textContent = uiState.chatOpen
      ? "千问路线助手"
      : uiState.productView === "browse" ? "浏览路线" : "帮我推荐";
    workbench.qwenButton.setAttribute("aria-expanded", String(uiState.chatOpen));
    workbench.qwenButton.setAttribute("aria-label", uiState.chatOpen ? "关闭千问路线助手" : "打开千问路线助手");
    workbench.qwenButton.title = uiState.chatOpen ? "关闭千问路线助手" : "千问路线助手";
    workbench.sidebar.classList.toggle("is-collapsed", uiState.sidebarCollapsed);
    workbench.sidebar.dataset.collapsed = String(uiState.sidebarCollapsed);
    workbench.collapseButton.setAttribute("aria-expanded", String(!uiState.sidebarCollapsed));
    workbench.collapseButton.setAttribute("aria-label", uiState.sidebarCollapsed ? "展开路线工作台" : "折叠路线工作台");
    workbench.collapseButton.title = uiState.sidebarCollapsed ? "展开工作台" : "折叠工作台";
  }

  function setSidebarCollapsed(collapsed) {
    uiState.sidebarCollapsed = Boolean(collapsed);
    syncWorkbench();
    globalThis.requestAnimationFrame?.(() => map.amap.resize?.());
    globalThis.setTimeout?.(() => map.amap.resize?.(), 200);
  }

  function requestLocation() {
    if (pendingLocationResolver) return Promise.resolve(null);
    setLocationEditorOpen(true);
    locationControls.input.focus();
    return new Promise((resolve) => {
      pendingLocationResolver = resolve;
    });
  }

  function finishLocationRequest(value) {
    const resolve = pendingLocationResolver;
    pendingLocationResolver = null;
    setLocationEditorOpen(false);
    resolve?.(value);
  }

  function commitLocation(location) {
    currentLocation = location;
    locationControls.label.textContent = location.label || "已选位置";
    locationControls.status.textContent = "";
    showUserLocation(map, location);
    recommendationUI.setLocation(location);
    finishLocationRequest(location);
    return location;
  }

  function bindLocationControls() {
    locationControls.toggle.addEventListener("click", () => {
      const open = locationControls.editor.hidden;
      if (!open && pendingLocationResolver) finishLocationRequest(null);
      else setLocationEditorOpen(open);
    });
    locationControls.search.addEventListener("click", async () => {
      locationControls.status.textContent = "正在查找地点…";
      try {
        commitLocation(await resolveUserLocation(map, { text: locationControls.input.value }));
      } catch (error) {
        locationControls.status.textContent = errorMessage(error);
      }
    });
    locationControls.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        locationControls.search.click();
      }
    });
    locationControls.pick.addEventListener("click", () => {
      startNavigationSession(map, (result) => {
        if (result?.error) {
          locationControls.status.textContent = result.error;
          return;
        }
        if (result?.point) {
          const point = { ...result.point, label: "地图点" };
          showUserLocation(map, point);
          endNavigationSession(map);
          commitLocation(point);
        }
      });
      enablePointPicker(map, "origin");
      locationControls.status.textContent = "请在地图上点击出发位置。";
    });
  }

  function bindRouteModeControls() {
    const buttons = [...document.querySelectorAll("[data-route-mode]")];
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        buttons.forEach((candidate) => {
          const active = candidate === button;
          candidate.classList.toggle("is-selected", active);
          candidate.setAttribute("aria-pressed", String(active));
        });
        recommendationUI.setRouteMode(button.dataset.routeMode);
      });
    });
  }

  function setLocationEditorOpen(open) {
    locationControls.editor.hidden = !open;
    locationControls.toggle.setAttribute("aria-expanded", String(open));
  }

  function bindLayerControls() {
    const button = document.querySelector("#mapLayerButton");
    const legend = document.querySelector("#mapLegend");
    button.addEventListener("click", () => {
      const open = legend.hidden;
      legend.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    });
  }
}

function getLocationControls() {
  return {
    toggle: document.querySelector("#locationButton"),
    label: document.querySelector("#locationLabel"),
    editor: document.querySelector("#locationEditor"),
    input: document.querySelector("#locationInput"),
    search: document.querySelector("#locationSearchButton"),
    pick: document.querySelector("#locationPickButton"),
    status: document.querySelector("#locationStatus"),
  };
}

function getWorkbenchControls() {
  return {
    sidebar: document.querySelector("#workbenchSidebar"),
    title: document.querySelector("#workbenchTitle"),
    qwenButton: document.querySelector("#workbenchQwenButton"),
    collapseButton: document.querySelector("#workbenchCollapseButton"),
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

function navigationStatusText(progress) {
  return `第 ${progress.stepNumber}/${progress.stepCount} 步 · ${progress.instruction}`;
}

function formatDistance(value) {
  const meters = Math.max(0, Number(value || 0));
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value || 0));
  return `${Math.max(0, Math.ceil(seconds / 60))} 分钟`;
}

function showRouteFeature(map, routeFeaturesById, routeId, data, selectedPreferences = []) {
  const feature = routeFeaturesById.get(routeId);
  if (!feature) {
    clearRouteResults(map);
    const message = `路线 ${routeId} 缺少地图路径数据，请刷新页面后重试。`;
    document.querySelector("#routeDetail").textContent = message;
    document.querySelector("#routeSummary").textContent = "路线加载失败";
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
  const detail = document.querySelector("#routeDetail");
  detail.textContent = error.message;
});
