import assert from "node:assert/strict";
import test from "node:test";

import { loadRouteData } from "../web/src/data-loader.js";

test("路线数据加载包含统一环境看板", async () => {
  const previousFetch = globalThis.fetch;
  const requestedPaths = [];
  const fixtures = {
    "../data/web/xuhui_boundary.geojson": { name: "boundary" },
    "../data/web/xuhui_entries.geojson": { name: "entries" },
    "../data/web/xuhui_routes.geojson": { name: "routes" },
    "../data/web/route_catalog.json": { name: "catalog" },
    "../data/web/poi_catalog.json": { name: "pois" },
    "../data/web/environment_dashboard.json": { name: "environment-dashboard" },
  };

  globalThis.fetch = async (url) => {
    const path = url.split("?")[0];
    requestedPaths.push(path);
    return {
      ok: true,
      async json() {
        return fixtures[path];
      },
    };
  };

  try {
    const data = await loadRouteData();

    assert.deepEqual(requestedPaths, Object.keys(fixtures));
    assert.strictEqual(data.environmentDashboard, fixtures["../data/web/environment_dashboard.json"]);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
