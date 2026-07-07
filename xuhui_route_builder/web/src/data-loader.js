export async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`数据加载失败: ${path}`);
  }
  return response.json();
}

export async function loadRouteData() {
  const [boundary, entries, routes, catalog] = await Promise.all([
    loadJson("../data/web/xuhui_boundary.geojson"),
    loadJson("../data/web/xuhui_entries.geojson"),
    loadJson("../data/web/xuhui_routes.geojson"),
    loadJson("../data/web/route_catalog.json"),
  ]);
  return { boundary, entries, routes, catalog };
}
