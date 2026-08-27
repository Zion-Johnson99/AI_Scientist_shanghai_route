import { loadRouteData } from "./data-loader.js?v=20260827-health-map-1";
import {
  buildRouteExposureModel,
  createEnvironmentPanel,
} from "./environment-ui.js?v=20260827-health-map-1";
import {
  beginInlineNavigation,
  clearInlineNavigation,
  clearRouteResults,
  createMap,
  drawBoundary,
  enablePointPicker,
  endNavigationSession,
  planNavigation,
  showRoutePreviews,
  showSingleRoute,
  startNavigationSession,
} from "./map.js?v=20260827-health-map-1";
import { createNavigationController } from "./navigation-session.js?v=20260827-health-map-1";
import { createRouteDock } from "./route-dock.js?v=20260827-health-map-1";
import { renderRoutePlanner } from "./route-ui.js?v=20260827-health-map-1";

async function bootstrap() {
  const map = await createMap("map");
  const data = await loadRouteData();
  const routeDock = createRouteDock();
  const routeFeaturesById = new Map(data.routes.features.map((feature) => [feature.properties.route_id, feature]));
  const catalog = enrichCatalog(data.catalog, data.entries);
  const guide = inlineNavigationGuideControls();
  createEnvironmentPanel(document.querySelector("#environmentPanel"), data.environmentDashboard);
  let planner = null;
  let activeNavigation = null;

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
  });
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

bootstrap().catch((error) => {
  const detail = document.querySelector("#routeDetail");
  detail.textContent = error.message;
});
