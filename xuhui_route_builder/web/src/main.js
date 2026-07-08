import { loadRouteData } from "./data-loader.js";
import { clearRouteResults, createMap, drawBoundary, highlightRoute, planNavigation, showRouteResults } from "./map.js";
import { renderRoutePlanner } from "./route-ui.js";

async function bootstrap() {
  const map = await createMap("map");
  const data = await loadRouteData();
  const routeFeaturesById = new Map(data.routes.features.map((feature) => [feature.properties.route_id, feature]));
  const catalog = enrichCatalog(data.catalog, data.entries);

  drawBoundary(map, data.boundary);
  renderRoutePlanner(catalog, {
    onSearch(routes, selectedRouteId) {
      if (!routes.length) {
        clearRouteResults(map);
        return;
      }
      const routeFeatures = routes.map((route) => routeFeaturesById.get(route.route_id)).filter(Boolean);
      showRouteResults(map, routeFeatures, data.entries, selectedRouteId || routeFeatures[0]?.properties.route_id);
    },
    onSelect(routeId) {
      highlightRoute(map, routeId);
    },
    onNavigate(request) {
      return planNavigation(map, request);
    },
  });
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
