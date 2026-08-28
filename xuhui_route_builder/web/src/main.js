import {
  loadRouteData,
  startEnvironmentDashboardPolling,
} from "./data-loader.js?v=20260828-recommendation-1";
import {
  buildRouteExposureModel,
  createEnvironmentPanel,
} from "./environment-ui.js?v=20260828-recommendation-1";
import {
  beginInlineNavigation,
  clearInlineNavigation,
  clearRouteResults,
  createMap,
  drawBoundary,
  enablePointPicker,
  endNavigationSession,
  planNavigation,
  resolveUserLocation,
  showUserLocation,
  showRoutePreviews,
  showSingleRoute,
  startNavigationSession,
} from "./map.js?v=20260828-recommendation-1";
import { createNavigationController } from "./navigation-session.js?v=20260828-recommendation-1";
import { loadHealthProfile, saveHealthProfile, HEALTH_PROFILE_STORAGE_KEY } from "./profile-store.js?v=20260828-recommendation-1";
import { createRecommendationApi } from "./recommendation-api.js?v=20260828-recommendation-1";
import { createProfileDialog, createRecommendationUI } from "./recommendation-ui.js?v=20260828-recommendation-1";
import { createRouteDock } from "./route-dock.js?v=20260828-recommendation-1";
import { renderRoutePlanner } from "./route-ui.js?v=20260828-recommendation-1";

async function bootstrap() {
  const map = await createMap("map");
  const data = await loadRouteData();
  const recommendationApi = createRecommendationApi();
  let questionnaire = null;
  let questionnaireError = null;
  try {
    questionnaire = await recommendationApi.questionnaire();
  } catch (error) {
    questionnaireError = error;
    console.error("推荐问卷加载失败", { error });
  }
  const routeDock = createRouteDock();
  const routeFeaturesById = new Map(data.routes.features.map((feature) => [feature.properties.route_id, feature]));
  const catalog = enrichCatalog(data.catalog, data.entries);
  const guide = inlineNavigationGuideControls();
  const environmentContainer = document.querySelector("#environmentPanel");
  const recommendationContainer = document.querySelector("#recommendationView");
  const selectionView = document.querySelector("#routeSelectionView");
  const navigationView = document.querySelector("#routeNavigationView");
  const modeTabs = [...document.querySelectorAll("[data-product-view]")];
  const locationControls = getLocationControls();
  const hadSavedProfile = Boolean(globalThis.localStorage?.getItem?.(HEALTH_PROFILE_STORAGE_KEY));
  let healthProfile = loadHealthProfile();
  let currentLocation = null;
  let currentProductView = "recommendation";
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
  let planner = null;
  let activeNavigation = null;
  let recommendationUI = null;

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
    onPreviewRoutes(routes, onSelectRoute) {
      const features = routes
        .map((route) => routeFeaturesById.get(route.route_id))
        .filter(Boolean);
      if (features.length !== routes.length) {
        console.warn("部分候选路线缺少地图路径数据", {
          requestedCount: routes.length,
          renderedCount: features.length,
        });
      }
      showRoutePreviews(map, features, onSelectRoute);
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
        routeDock.show(
          route,
          buildRouteExposureModel(data.environmentDashboard, route.route_id),
        );
      } else {
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
      setProductView(currentProductView);
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
    onPickLocation: requestLocation,
    onRecommend: (profile) => recommendationApi.recommend(profile),
    onReloadQuestionnaire: () => recommendationApi.questionnaire(),
    shouldSelectRoute: () => currentProductView === "recommendation",
    onSelectRoute(routeId) {
      planner.selectRoute(routeId);
    },
    async onNavigate(routeId) {
      const origin = currentLocation || await requestLocation();
      if (origin) planner.openNavigation(routeId, origin);
    },
    onOpenProfile: () => profileDialog.open(),
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
  bindLocationControls();
  bindLayerControls();
  setProductView("recommendation");

  function setProductView(view) {
    currentProductView = view === "browse" ? "browse" : "recommendation";
    modeTabs.forEach((tab) => {
      const active = tab.dataset.productView === currentProductView;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    navigationView.hidden = true;
    recommendationContainer.hidden = currentProductView !== "recommendation";
    recommendationContainer.classList.toggle("active", currentProductView === "recommendation");
    selectionView.hidden = currentProductView !== "browse";
    selectionView.classList.toggle("active", currentProductView === "browse");
    if (currentProductView === "browse") {
      planner.showBrowse();
    } else {
      const routeId = recommendationUI.getCurrentRouteId();
      if (routeId) planner.selectRoute(routeId);
    }
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
    locationControls.status.textContent = "位置已用于路线推荐和前往起点。";
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
