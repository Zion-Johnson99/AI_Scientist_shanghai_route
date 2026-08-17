import { loadRouteData } from "./data-loader.js?v=20260817-inline-navigation-2";
import {
  beginInlineNavigation,
  clearInlineNavigation,
  clearRouteResults,
  createMap,
  drawBoundary,
  enablePointPicker,
  endNavigationSession,
  focusSportRoute,
  planNavigation,
  showSingleRoute,
  startNavigationSession,
  updateInlineNavigation,
} from "./map.js?v=20260817-inline-navigation-2";
import { createNavigationController } from "./navigation-session.js?v=20260817-inline-navigation-2";
import { createRouteDock } from "./route-dock.js?v=20260817-inline-navigation-2";
import { renderRoutePlanner } from "./route-ui.js?v=20260817-inline-navigation-2";

async function bootstrap() {
  const map = await createMap("map");
  const data = await loadRouteData();
  const routeDock = createRouteDock();
  const routeFeaturesById = new Map(data.routes.features.map((feature) => [feature.properties.route_id, feature]));
  const catalog = enrichCatalog(data.catalog, data.entries);
  const guide = inlineNavigationGuideControls();
  let activeNavigation = null;
  let reroutePending = false;
  let lastRerouteAt = 0;

  const navigationController = createNavigationController({
    geolocation: navigator.geolocation,
    onProgress(progress) {
      updateInlineNavigation(map, progress);
      renderInlineNavigationProgress(guide, progress);
      document.querySelector("#navigationStatus").textContent = navigationStatusText(progress);

      if (progress.status === "arrived") {
        focusSportRoute(map, activeNavigation.request.routeId);
        return;
      }
      if (progress.shouldReroute) {
        void rerouteFrom(progress);
      }
    },
    onError(error) {
      renderInlineNavigationError(guide, error.message);
      document.querySelector("#navigationStatus").textContent = error.message;
      console.error("网页内导航定位失败", {
        routeId: activeNavigation?.request?.routeId,
        state: map.navigation.state,
        error,
      });
    },
  });

  async function rerouteFrom(progress) {
    const now = Date.now();
    if (!activeNavigation || reroutePending || now - lastRerouteAt < 15000) {
      return;
    }
    reroutePending = true;
    lastRerouteAt = now;
    guide.state.textContent = "正在重算路线";
    try {
      const plan = await planNavigation(map, {
        ...activeNavigation.request,
        origin: {
          lng_gcj02: progress.position.lng,
          lat_gcj02: progress.position.lat,
          name: "实时位置",
        },
      });
      activeNavigation.plan = plan;
      navigationController.replacePlan(plan);
      beginInlineNavigation(map, plan);
      guide.state.textContent = "路线已更新";
    } catch (error) {
      renderInlineNavigationError(guide, `偏航重算失败：${error.message}`);
      console.error("网页内导航偏航重算失败", {
        routeId: activeNavigation.request.routeId,
        position: progress.position,
        error,
      });
    } finally {
      reroutePending = false;
    }
  }

  function stopInlineNavigation() {
    navigationController.stop();
    clearInlineNavigation(map);
    hideInlineNavigationGuide(guide);
    activeNavigation = null;
    reroutePending = false;
  }

  guide.endButton.addEventListener("click", () => {
    document.querySelector("#endNavigationButton").click();
  });

  drawBoundary(map, data.boundary);
  renderRoutePlanner(catalog, {
    onShowRoute(route) {
      showRouteFeature(map, routeFeaturesById, route.route_id, data);
    },
    onClearRoutes() {
      stopInlineNavigation();
      clearRouteResults(map);
      routeDock.hide();
    },
    onSelect(routeId) {
      showRouteFeature(map, routeFeaturesById, routeId, data);
    },
    onStartNavigation(onPick) {
      startNavigationSession(map, onPick);
    },
    onEndNavigation() {
      stopInlineNavigation();
      endNavigationSession(map);
    },
    onPickNavigationPoint(role) {
      enablePointPicker(map, role);
    },
    onNavigate(request) {
      return planNavigation(map, request);
    },
    onStartInlineNavigation(payload) {
      activeNavigation = payload;
      showInlineNavigationGuide(guide, payload.plan);
      navigationController.start(payload.plan);
      beginInlineNavigation(map, payload.plan);
    },
    onRouteMetrics(route) {
      if (route) {
        routeDock.show(route);
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
    accuracy: document.querySelector("#inlineNavigationAccuracy"),
    progress: document.querySelector("#inlineNavigationProgress"),
    endButton: document.querySelector("#inlineNavigationEndButton"),
  };
}

function showInlineNavigationGuide(guide, plan) {
  guide.root.hidden = false;
  guide.root.parentElement.classList.add("inline-navigation-active");
  guide.root.dataset.status = "locating";
  guide.state.textContent = "正在定位";
  guide.instruction.textContent = plan.steps?.[0]?.instruction || "沿接驳路线前往运动路线起点";
  guide.remaining.textContent = formatDistance(plan.distance);
  guide.duration.textContent = formatDuration(plan.duration);
  guide.accuracy.textContent = "等待定位";
  guide.progress.style.width = "0%";
}

function renderInlineNavigationProgress(guide, progress) {
  guide.root.hidden = false;
  guide.root.dataset.status = progress.status;
  guide.state.textContent = {
    navigating: "实时导航中",
    off_route: "已偏离路线",
    arrived: "已到达起点",
  }[progress.status] || "实时接驳";
  guide.instruction.textContent = progress.instruction;
  guide.remaining.textContent = formatDistance(progress.remainingDistanceM);
  guide.duration.textContent = formatDuration(progress.remainingDurationS);
  guide.accuracy.textContent = progress.position.accuracy
    ? `±${Math.round(progress.position.accuracy)} 米`
    : "精度未知";
  guide.progress.style.width = `${Math.round(progress.progressRatio * 100)}%`;
}

function renderInlineNavigationError(guide, message) {
  guide.root.hidden = false;
  guide.root.dataset.status = "error";
  guide.state.textContent = "定位异常";
  guide.instruction.textContent = message;
}

function hideInlineNavigationGuide(guide) {
  guide.root.hidden = true;
  guide.root.parentElement.classList.remove("inline-navigation-active");
  delete guide.root.dataset.status;
  guide.progress.style.width = "0%";
}

function navigationStatusText(progress) {
  if (progress.status === "arrived") {
    return "已到达所选运动路线起点，可以开始运动。";
  }
  if (progress.status === "off_route") {
    return "检测到偏航，正在网页内重新规划接驳路线。";
  }
  return `${progress.instruction}，剩余 ${formatDistance(progress.remainingDistanceM)}。`;
}

function formatDistance(value) {
  const meters = Math.max(0, Number(value || 0));
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

function formatDuration(value) {
  const seconds = Math.max(0, Number(value || 0));
  return `${Math.max(0, Math.ceil(seconds / 60))} 分钟`;
}

function showRouteFeature(map, routeFeaturesById, routeId, data) {
  const feature = routeFeaturesById.get(routeId);
  if (!feature) {
    clearRouteResults(map);
    const message = `路线 ${routeId} 缺少地图路径数据，请刷新页面后重试。`;
    document.querySelector("#routeDetail").textContent = message;
    document.querySelector("#routeSummary").textContent = "路线加载失败";
    console.error(message, { routeId, loadedFeatureCount: routeFeaturesById.size });
    return;
  }
  showSingleRoute(map, feature, data.entries, data.pois);
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
