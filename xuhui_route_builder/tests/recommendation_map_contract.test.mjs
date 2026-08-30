import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createRecommendationMapController, routePreviewCardModel } from "../web/src/map.js";

const routes = [
  createRoute("XH_WALK_0001", 121.42),
  createRoute("XH_WALK_0002", 121.43),
  createRoute("XH_WALK_0003", 121.44),
];

test("推荐结果以三路线总览显示，并用一次 fitView 容纳现有路线", () => {
  const { mapContext, fitViews } = createMapContext();
  const controller = createRecommendationMapController(mapContext);

  const state = controller.showRoutes(routes);

  assert.deepEqual(state, {
    recommendedRouteIds: ["XH_WALK_0001", "XH_WALK_0002", "XH_WALK_0003"],
    hoveredRouteId: null,
    selectedRouteId: null,
    mapMode: "overview",
  });
  assert.deepEqual(routeStates(mapContext), ["overview", "overview", "overview"]);
  assert.equal(fitViews.length, 1);
  assert.deepEqual(fitViews[0].overlays, routeMainLayers(mapContext));
});

test("悬停只改变强调层级，不缩放或打开聚焦状态", () => {
  const { mapContext, fitViews } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes(routes);
  const fitViewCount = fitViews.length;

  const state = controller.previewRoute("XH_WALK_0002");

  assert.equal(state.mapMode, "preview");
  assert.equal(state.hoveredRouteId, "XH_WALK_0002");
  assert.equal(state.selectedRouteId, null);
  assert.deepEqual(routeStates(mapContext), ["preview-muted", "active", "preview-muted"]);
  assert.equal(fitViews.length, fitViewCount);
});

test("快速移过多条路线时，迟到的离开事件不会清除最后路线", () => {
  const { mapContext } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes(routes);

  controller.previewRoute("XH_WALK_0001");
  controller.previewRoute("XH_WALK_0002");
  const staleLeaveState = controller.clearPreview("XH_WALK_0001");

  assert.equal(staleLeaveState.mapMode, "preview");
  assert.equal(staleLeaveState.hoveredRouteId, "XH_WALK_0002");
  assert.deepEqual(routeStates(mapContext), ["preview-muted", "active", "preview-muted"]);

  const finalState = controller.clearPreview("XH_WALK_0002");
  assert.equal(finalState.mapMode, "overview");
  assert.equal(finalState.hoveredRouteId, null);
  assert.deepEqual(routeStates(mapContext), ["overview", "overview", "overview"]);
});

test("关闭推荐详情后恢复原三路线顺序与总览视野", () => {
  const { mapContext, fitViews } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes(routes);

  const focused = controller.focusRoute("XH_WALK_0003");

  assert.equal(focused.mapMode, "focused");
  assert.equal(focused.selectedRouteId, "XH_WALK_0003");
  assert.equal(focused.hoveredRouteId, null);
  assert.deepEqual(routeStates(mapContext), ["muted", "muted", "sporting"]);
  assert.deepEqual(fitViews.at(-1).overlays, [mapContext.routeLayers.get("XH_WALK_0003").main]);

  const overview = controller.showOverview();
  assert.equal(overview.mapMode, "overview");
  assert.equal(overview.selectedRouteId, null);
  assert.deepEqual(overview.recommendedRouteIds, routes.map((route) => route.properties.route_id));
  assert.deepEqual(routeStates(mapContext), ["overview", "overview", "overview"]);
  assert.deepEqual(fitViews.at(-1).overlays, routeMainLayers(mapContext));
});

test("浏览和推荐公用的地图小卡只显示名称和公里数", () => {
  const model = routePreviewCardModel({
    ...routes[0],
    properties: {
      ...routes[0].properties,
      route_name: "滨江慢行",
      distance_m: 868,
    },
  });

  assert.equal(model.distanceText, "0.87 公里");
  assert.equal(model.ariaLabel, "滨江慢行，0.87 公里");
  assert.equal("pm25Text" in model, false);
  assert.equal("metaText" in model, false);
});

test("详情关闭按来源恢复推荐总览或当前浏览筛选总览", () => {
  const routeUiSource = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");
  const mainSource = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");

  assert.ok(routeUiSource.includes("restoreBrowseOverview("), "浏览控制器缺少 restoreBrowseOverview()");
  assert.match(mainSource, /onClose\s*\(\s*\{\s*source\s*,\s*routeId\s*\}\s*\)/, "详情关闭回调缺少 source/routeId");
  assert.match(
    mainSource,
    /if\s*\(source === "recommendation"\)\s*\{\s*uiState\.productView = "recommendation";\s*uiState\.chatOpen = false;\s*renderProductView\(\);/s,
    "推荐详情关闭后未显式恢复推荐结果界面",
  );
  assert.ok(mainSource.includes("recommendationMap.showOverview("), "推荐详情关闭未恢复三路线总览");
  assert.ok(mainSource.includes("planner.restoreBrowseOverview("), "浏览详情关闭未恢复当前筛选总览");
});

test("地图路线事件通过明确回调同步卡片状态", () => {
  const { mapContext } = createMapContext();
  const hoverChanges = [];
  const selections = [];
  const controller = createRecommendationMapController(mapContext, {
    onRouteHover: (routeId) => hoverChanges.push(routeId),
    onRouteSelect: (routeId) => selections.push(routeId),
  });
  controller.showRoutes(routes);
  const secondLine = mapContext.routeLayers.get("XH_WALK_0002").main;

  secondLine.emit("mouseover");
  secondLine.emit("mouseout");
  secondLine.emit("click");

  assert.deepEqual(hoverChanges, ["XH_WALK_0002", null]);
  assert.deepEqual(selections, ["XH_WALK_0002"]);
  assert.equal(controller.getState().mapMode, "focused");
  assert.equal(controller.getState().selectedRouteId, "XH_WALK_0002");
});

test("过期 routeId 不改变当前推荐地图状态", () => {
  const { mapContext, fitViews } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes(routes.slice(0, 2));
  const before = controller.getState();
  const fitViewCount = fitViews.length;

  assert.deepEqual(controller.previewRoute("OLD_ROUTE"), before);
  assert.deepEqual(controller.focusRoute("OLD_ROUTE"), before);
  assert.equal(fitViews.length, fitViewCount);
});

function createRoute(routeId, startLng) {
  return {
    type: "Feature",
    properties: {
      route_id: routeId,
      route_name: routeId,
      route_mode: "walk",
    },
    geometry: {
      type: "LineString",
      coordinates: [[startLng, 31.18], [startLng + 0.005, 31.185]],
    },
  };
}

function createMapContext() {
  class Overlay {
    constructor(options) {
      this.options = options;
      this.listeners = new Map();
    }

    on(type, handler) {
      this.listeners.set(type, handler);
    }

    emit(type) {
      this.listeners.get(type)?.();
    }

    setOptions(options) {
      Object.assign(this.options, options);
    }
  }

  const fitViews = [];
  const mapContext = {
    AMap: {
      Polyline: class Polyline extends Overlay {},
    },
    amap: {
      add() {},
      remove() {},
      setFitView(overlays, immediately, padding, maxZoom) {
        fitViews.push({ overlays, immediately, padding, maxZoom });
      },
    },
    routeLayers: new Map(),
    routePreviewLayers: [],
    routePreviewMarkers: [],
    routePreviewZoomHandler: null,
    entryLayers: [],
    poiLayers: [],
  };
  return { mapContext, fitViews };
}

function routeStates(mapContext) {
  return [...mapContext.routeLayers.values()].map(({ state }) => state);
}

function routeMainLayers(mapContext) {
  return [...mapContext.routeLayers.values()].map(({ main }) => main);
}
