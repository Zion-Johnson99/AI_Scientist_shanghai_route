import { loadRouteData } from "./data-loader.js";
import { createMap, drawBoundary, drawEntries, drawRoutes, highlightRoute } from "./map.js";
import { renderRoutes } from "./route-ui.js";

async function bootstrap() {
  const map = createMap("map");
  const data = await loadRouteData();
  drawBoundary(map, data.boundary);
  drawEntries(map, data.entries);
  const routeLayers = drawRoutes(map, data.routes);
  renderRoutes(data.catalog, (routeId) => highlightRoute(routeLayers, routeId));
}

bootstrap().catch((error) => {
  const detail = document.querySelector("#routeDetail");
  detail.textContent = error.message;
});
