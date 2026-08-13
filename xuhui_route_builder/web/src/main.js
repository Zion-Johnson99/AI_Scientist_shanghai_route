import { loadRouteData } from "./data-loader.js?v=20260813-route-geometry-1";
import {
  clearRouteResults,
  createMap,
  drawBoundary,
  enablePointPicker,
  endNavigationSession,
  focusSportRoute,
  planNavigation,
  showSingleRoute,
  startNavigationSession,
} from "./map.js?v=20260813-route-geometry-1";
import { renderRoutePlanner } from "./route-ui.js?v=20260813-route-geometry-1";

async function bootstrap() {
  const map = await createMap("map");
  const data = await loadRouteData();
  const routeFeaturesById = new Map(data.routes.features.map((feature) => [feature.properties.route_id, feature]));
  const catalog = enrichCatalog(data.catalog, data.entries);

  drawBoundary(map, data.boundary);
  renderRoutePlanner(catalog, {
    onShowRoute(route) {
      showRouteFeature(map, routeFeaturesById, route.route_id, data);
    },
    onClearRoutes() {
      clearRouteResults(map);
    },
    onSelect(routeId) {
      showRouteFeature(map, routeFeaturesById, routeId, data);
    },
    onStartNavigation(onPick) {
      startNavigationSession(map, onPick);
    },
    onEndNavigation() {
      endNavigationSession(map);
    },
    onPickNavigationPoint(role) {
      enablePointPicker(map, role);
    },
    onNavigate(request) {
      return planNavigation(map, request);
    },
    onStartSport(routeId) {
      focusSportRoute(map, routeId);
    },
  });
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
