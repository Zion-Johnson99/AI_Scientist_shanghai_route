const DATA_RELEASE = "20260817-inline-navigation-2";

export async function loadJson(path) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${separator}v=${DATA_RELEASE}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`数据加载失败: ${path}`);
  }
  return response.json();
}

export async function loadRouteData() {
  const [boundary, entries, routes, catalog, pois] = await Promise.all([
    loadJson("../data/web/xuhui_boundary.geojson"),
    loadJson("../data/web/xuhui_entries.geojson"),
    loadJson("../data/web/xuhui_routes.geojson"),
    loadJson("../data/web/route_catalog.json"),
    loadJson("../data/web/poi_catalog.json"),
  ]);
  return { boundary, entries, routes, catalog, pois };
}
