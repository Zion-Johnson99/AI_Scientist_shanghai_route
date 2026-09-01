import assert from "node:assert/strict";
import test from "node:test";

import {
  loadEnvironmentDashboard,
  loadRouteData,
  startEnvironmentDashboardPolling,
} from "../web/src/data-loader.js";

test("环境看板优先读取无缓存在线发布地址", async () => {
  const previousFetch = globalThis.fetch;
  const previousUrl = globalThis.XUHUI_ENVIRONMENT_DASHBOARD_URL;
  const requestedUrls = [];
  const dashboard = { metadata: { generated_at: "2099-09-01T00:15:00+08:00" } };

  globalThis.XUHUI_ENVIRONMENT_DASHBOARD_URL =
    "https://environment.example.com/environment_dashboard.json";
  globalThis.fetch = async (url, options) => {
    requestedUrls.push({ url, options });
    return { ok: true, async json() { return dashboard; } };
  };

  try {
    assert.strictEqual(await loadEnvironmentDashboard(), dashboard);
    assert.match(
      requestedUrls[0].url,
      /^https:\/\/environment\.example\.com\/environment_dashboard\.json\?v=/,
    );
    assert.deepEqual(requestedUrls[0].options, { cache: "no-store" });
  } finally {
    globalThis.fetch = previousFetch;
    if (previousUrl === undefined) {
      delete globalThis.XUHUI_ENVIRONMENT_DASHBOARD_URL;
    } else {
      globalThis.XUHUI_ENVIRONMENT_DASHBOARD_URL = previousUrl;
    }
  }
});

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

test("环境看板每分钟自动读取最新数据", async () => {
  const previousFetch = globalThis.fetch;
  const previousSetInterval = globalThis.setInterval;
  const dashboard = { metadata: { generated_at: "2099-08-28T12:00:00+08:00" } };
  const requestedPaths = [];
  let scheduledCallback = null;
  let scheduledDelay = null;

  globalThis.fetch = async (url) => {
    requestedPaths.push(url.split("?")[0]);
    return {
      ok: true,
      async json() {
        return dashboard;
      },
    };
  };
  globalThis.setInterval = (callback, delay) => {
    scheduledCallback = callback;
    scheduledDelay = delay;
    return 17;
  };

  try {
    let received = null;
    const timerId = startEnvironmentDashboardPolling((nextDashboard) => {
      received = nextDashboard;
    });

    assert.equal(timerId, 17);
    assert.equal(scheduledDelay, 60_000);
    assert.equal(typeof scheduledCallback, "function");
    await scheduledCallback();
    assert.deepEqual(requestedPaths, ["../data/web/environment_dashboard.json"]);
    assert.strictEqual(received, dashboard);
  } finally {
    globalThis.fetch = previousFetch;
    globalThis.setInterval = previousSetInterval;
  }
});
