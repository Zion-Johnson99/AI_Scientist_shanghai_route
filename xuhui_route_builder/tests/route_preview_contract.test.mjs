import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  clearRouteResults,
  previewMarkerOffset,
  routePreviewCardModel,
  showRoutePreviews,
} from "../web/src/map.js";

const previewRoutes = [
  {
    type: "Feature",
    properties: {
      route_id: "XH_WALK_0001",
      route_name: "植物园北区园路单环线",
      route_mode: "walk",
      distance_m: 2113,
      start_location: { lng_gcj02: 121.440378, lat_gcj02: 31.208333 },
    },
    geometry: {
      type: "LineString",
      coordinates: [[121.440378, 31.208333], [121.442, 31.207]],
    },
  },
  {
    type: "Feature",
    properties: {
      route_id: "XH_WALK_0002",
      route_name: "短线",
      route_mode: "walk",
      actual_distance_m: 970,
      start_location: { lng_gcj02: 121.440378, lat_gcj02: 31.208333 },
    },
    geometry: {
      type: "LineString",
      coordinates: [[121.440378, 31.208333], [121.443, 31.209]],
    },
  },
];

test("预览卡片截断长名称并保留两位公里数和完整无障碍文本", () => {
  assert.deepEqual(routePreviewCardModel(previewRoutes[0]), {
    routeId: "XH_WALK_0001",
    fullName: "植物园北区园路单环线",
    shortName: "植物园北区园…",
    distanceText: "2.11 公里",
    ariaLabel: "植物园北区园路单环线，2.11 公里",
  });
  assert.equal(routePreviewCardModel(previewRoutes[1]).shortName, "短线");
  assert.equal(routePreviewCardModel(previewRoutes[1]).distanceText, "0.97 公里");
});

test("共起点卡片低倍局部堆叠，高倍放大后展开为可点击间距", () => {
  const compact = [0, 1, 2, 3].map((index) => previewMarkerOffset(index, 4, 13));
  const expanded = [0, 1, 2, 3].map((index) => previewMarkerOffset(index, 4, 15));

  assert.ok(Math.max(...compact.map(({ x }) => x)) - Math.min(...compact.map(({ x }) => x)) < 60);
  assert.ok(Math.max(...expanded.map(({ x }) => x)) - Math.min(...expanded.map(({ x }) => x)) >= 150);
  assert.ok(new Set(expanded.map(({ x, y }) => `${x},${y}`)).size === expanded.length);
});

test("地图预览使用统一淡蓝连续线、无方向箭头，卡片点击回传路线", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const { mapContext, added } = createMapContext();
    const selected = [];

    showRoutePreviews(mapContext, previewRoutes, (routeId) => selected.push(routeId));

    const lines = added.filter((overlay) => overlay instanceof mapContext.AMap.Polyline);
    const markers = added.filter((overlay) => overlay instanceof mapContext.AMap.Marker);
    assert.equal(lines.length, 2);
    assert.equal(markers.length, 2);
    assert.ok(lines.every((line) => line.options.strokeColor === "#3d91ff"));
    assert.ok(lines.every((line) => line.options.strokeWeight === 4));
    assert.ok(lines.every((line) => line.options.strokeOpacity === 0.34));
    assert.ok(lines.every((line) => line.options.showDir === false));

    markers[0].options.content.click();
    assert.deepEqual(selected, ["XH_WALK_0001"]);
    assert.equal(markers[0].options.content.title, "植物园北区园路单环线");
    assert.equal(markers[0].options.content.attributes["aria-label"], "植物园北区园路单环线，2.11 公里");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("清理路线时同步移除预览折线、卡片和缩放监听", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const { mapContext, removed, events } = createMapContext();
    showRoutePreviews(mapContext, previewRoutes, () => {});

    clearRouteResults(mapContext);

    assert.equal(removed.length, 4);
    assert.equal(mapContext.routePreviewLayers.length, 0);
    assert.equal(mapContext.routePreviewMarkers.length, 0);
    assert.deepEqual(events.off, ["zoomend"]);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("浏览路线保留地图预览，推荐结果使用单路线聚焦", () => {
  const routeUi = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");
  const main = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");

  assert.ok(routeUi.includes("options.onPreviewRoutes"));
  assert.ok(routeUi.includes("renderSelectionPreview"));
  assert.ok(routeUi.includes("openNavigation(routeId, origin = null)"));
  assert.ok(main.includes("showRoutePreviews"));
  assert.ok(main.includes("onPreviewRoutes"));
  assert.ok(main.includes("showSingleRoute"));
});

test("推荐初始态复用浏览路线选项卡，已有推荐结果才切换为推荐路线", () => {
  const routeUi = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");
  const main = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");

  assert.ok(routeUi.includes("showBrowsePreviews()"));
  assert.match(main, /else\s*\{\s*recommendationFeatures = \[\];\s*planner\.showBrowsePreviews\(\);/s);
});

test("接驳导航返回时退出内嵌导航视图", () => {
  const routeUi = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");

  assert.ok(routeUi.includes("controls.navigationBackButton.addEventListener"));
  assert.ok(routeUi.includes("options.onNavigationViewChange?.(false)"));
});

function createDocumentStub() {
  return {
    createElement(tagName) {
      return {
        tagName: tagName.toUpperCase(),
        className: "",
        dataset: {},
        attributes: {},
        children: [],
        title: "",
        type: "",
        setAttribute(name, value) { this.attributes[name] = value; },
        append(...children) { this.children.push(...children); },
        addEventListener(type, handler) { this.listeners ||= {}; this.listeners[type] = handler; },
        click() { this.listeners?.click?.({ stopPropagation() {} }); },
      };
    },
  };
}

function createMapContext() {
  class Overlay {
    constructor(options) { this.options = options; }
    on() {}
    setOffset(offset) { this.offset = offset; }
  }
  const added = [];
  const removed = [];
  const events = { on: [], off: [] };
  const mapContext = {
    AMap: {
      Polyline: class Polyline extends Overlay {},
      Marker: class Marker extends Overlay {},
      Pixel: class Pixel {
        constructor(x, y) { this.x = x; this.y = y; }
      },
    },
    amap: {
      add(overlay) { added.push(overlay); },
      remove(overlays) { removed.push(...overlays); },
      setFitView() {},
      getZoom() { return 13; },
      on(type) { events.on.push(type); },
      off(type) { events.off.push(type); },
    },
    routeLayers: new Map(),
    routePreviewLayers: [],
    routePreviewMarkers: [],
    routePreviewZoomHandler: null,
    entryLayers: [],
    poiLayers: [],
  };
  return { mapContext, added, removed, events };
}
