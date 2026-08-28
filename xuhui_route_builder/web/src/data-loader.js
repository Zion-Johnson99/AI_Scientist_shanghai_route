const DATA_RELEASE = "20260828-recommendation-1";
const ENVIRONMENT_DASHBOARD_PATH = "../data/web/environment_dashboard.json";
const ENVIRONMENT_POLL_INTERVAL_MS = 60_000;

export async function loadJson(path) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${separator}v=${DATA_RELEASE}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`数据加载失败: ${path}`);
  }
  return response.json();
}

export function loadEnvironmentDashboard() {
  return loadJson(ENVIRONMENT_DASHBOARD_PATH);
}

export async function loadRouteData() {
  const [boundary, entries, routes, catalog, pois, environmentDashboard] = await Promise.all([
    loadJson("../data/web/xuhui_boundary.geojson"),
    loadJson("../data/web/xuhui_entries.geojson"),
    loadJson("../data/web/xuhui_routes.geojson"),
    loadJson("../data/web/route_catalog.json"),
    loadJson("../data/web/poi_catalog.json"),
    loadEnvironmentDashboard(),
  ]);
  return { boundary, entries, routes, catalog, pois, environmentDashboard };
}

export function startEnvironmentDashboardPolling(onDashboard) {
  return setInterval(async () => {
    try {
      onDashboard(await loadEnvironmentDashboard());
    } catch (error) {
      console.error("环境数据自动更新失败", {
        path: ENVIRONMENT_DASHBOARD_PATH,
        intervalMs: ENVIRONMENT_POLL_INTERVAL_MS,
        error,
      });
    }
  }, ENVIRONMENT_POLL_INTERVAL_MS);
}
