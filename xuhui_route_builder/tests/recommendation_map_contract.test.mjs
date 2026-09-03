import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  createRecommendationMapController,
  healthMapPlaceModels,
  routePreviewCardModel,
  setBaseMapMode,
  showHealthMapPlaces,
  showSingleRoute,
  startPointMarkerContent,
} from "../web/src/map.js";

const routes = [
  createRoute("XH_WALK_0001", 121.42),
  createRoute("XH_WALK_0002", 121.43),
  createRoute("XH_WALK_0003", 121.44),
];

test("已确认起点与地图候选点共用同一红色图钉", () => {
  const committed = startPointMarkerContent();
  const candidate = startPointMarkerContent({ showLabel: false, ariaLabel: "待确认出发点" });

  for (const content of [committed, candidate]) {
    assert.match(content, /amap-user-location__pin/);
    assert.match(content, /M16 1C7\.72 1 1 7\.72 1 16/);
    assert.match(content, /<circle cx="16" cy="16" r="6"><\/circle>/);
  }
  assert.match(committed, /amap-user-location__label">出发点/);
  assert.match(candidate, /amap-user-location--candidate/);
  assert.doesNotMatch(candidate, /amap-user-location__label/);
});

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
  assert.deepEqual(semanticMarkerRoles(mapContext), []);
  assert.equal(fitViews.length, 1);
  assert.deepEqual(fitViews[0].overlays, routeMainLayers(mapContext));
});

test("三路线总览不再绘制原始 entry 和 POI 彩点", () => {
  const { mapContext, added } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  const entries = {
    features: [{
      properties: { entry_id: "ENTRY-1", entry_name: "公园入口", entry_type: "park_gate" },
      geometry: { type: "Point", coordinates: [121.421, 31.181] },
    }],
  };
  const pois = {
    features: [{
      properties: { poi_id: "POI-1", poi_name: "公共厕所", poi_type: "toilet" },
      geometry: { type: "Point", coordinates: [121.422, 31.182] },
    }],
  };
  const route = {
    ...routes[0],
    properties: {
      ...routes[0].properties,
      start_entry_id: "ENTRY-1",
      nearby_pois: [{
        poi_id: "POI-1",
        poi_name: "公共厕所",
        poi_type: "toilet",
        route_relation: "along_route",
        verification_status: "verified",
      }],
    },
  };

  controller.showRoutes([route], entries, pois);

  assert.equal(mapContext.entryLayers.length, 0);
  assert.equal(mapContext.poiLayers.length, 0);
  assert.deepEqual(semanticMarkerRoles(mapContext), []);
  assert.equal(added.some((overlay) => String(overlay.options?.content || "").includes("amap-entry-dot")), false);
  assert.equal(added.some((overlay) => String(overlay.options?.content || "").includes("amap-poi-dot")), false);
  assert.doesNotMatch(added.map((overlay) => overlay.options?.content || "").join(""), /toilet/);
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
  assert.deepEqual(semanticMarkerPositions(mapContext), []);
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
  assert.deepEqual(semanticMarkerPositions(mapContext), []);
});

test("聚焦路线仅显示 A B 和最多三个已核验沿途关键点", () => {
  const { mapContext } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  const route = {
    ...routes[0],
    properties: {
      ...routes[0].properties,
      nearby_pois: [
        verifiedPoi("COFFEE", "交大咖啡", "coffee", 18),
        verifiedPoi("TOILET", "汇师公共厕所", "toilet", 24),
        verifiedPoi("STORE", "天平路便利店", "convenience", 31),
        { ...verifiedPoi("NEARBY", "附近公园", "park_gate", 12), route_relation: "nearby" },
      ],
      ordered_nodes: [
        { name: "默认起点", lng_gcj02: 121.42, lat_gcj02: 31.18 },
        { name: "华山路广元西路口", lng_gcj02: 121.423, lat_gcj02: 31.183 },
        { name: "默认终点", lng_gcj02: 121.425, lat_gcj02: 31.185 },
      ],
    },
  };
  const pois = {
    features: [
      poiFeature("COFFEE", "交大咖啡", "coffee", [121.421, 31.181]),
      poiFeature("TOILET", "汇师公共厕所", "toilet", [121.422, 31.182]),
      poiFeature("STORE", "天平路便利店", "convenience", [121.423, 31.183]),
      poiFeature("NEARBY", "附近公园", "park_gate", [121.424, 31.184]),
    ],
  };

  controller.showRoutes([route], { features: [] }, pois);
  controller.focusRoute("XH_WALK_0001");

  assert.deepEqual(semanticMarkerRoles(mapContext), ["start", "landmark", "landmark", "landmark", "end"]);
  assert.deepEqual(semanticMarkerNames(mapContext), ["默认起点", "交大咖啡", "汇师公共厕所", "天平路便利店", "默认终点"]);
  assert.doesNotMatch(mapContext.semanticMarkerLayers.map((marker) => marker.options.content).join(""), /coffee|toilet|convenience/);
});

test("聚焦路线使用临时图层从起点逐段揭示到终点", () => {
  const { mapContext, added, removedCalls, flushFrame, pendingFrameCount } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes([routes[0]]);
  const sourceLayers = mapContext.routeLayers.get("XH_WALK_0001");

  controller.focusRoute("XH_WALK_0001");

  const revealMain = added.find((overlay) => overlay.options.extData?.layerRole === "reveal-main");
  assert.ok(revealMain);
  assert.equal(sourceLayers.main.options.strokeOpacity, 0);
  assert.deepEqual(revealMain.options.path, [[121.42, 31.18], [121.42, 31.18]]);
  assert.equal(pendingFrameCount(), 1);

  flushFrame(0);
  flushFrame(600);
  assert.deepEqual(revealMain.options.path[0], [121.42, 31.18]);
  assert.ok(revealMain.options.path.at(-1)[0] > 121.42);
  assert.ok(revealMain.options.path.at(-1)[0] < 121.425);

  flushFrame(1200);
  assert.deepEqual(sourceLayers.main.options.path, routes[0].geometry.coordinates);
  assert.equal(sourceLayers.main.options.strokeOpacity, 1);
  assert.equal(removedCalls.every((overlays) => !Array.isArray(overlays)), true);
  assert.equal(pendingFrameCount(), 0);
});

test("浏览路线详情复用逐段揭示动画", () => {
  const { mapContext, added, flushFrame, pendingFrameCount } = createMapContext();

  showSingleRoute(mapContext, routes[0], { features: [] }, { features: [] });

  const sourceLayers = mapContext.routeLayers.get("XH_WALK_0001");
  const revealMain = added.find((overlay) => overlay.options.extData?.layerRole === "reveal-main");
  assert.ok(revealMain);
  assert.equal(sourceLayers.main.options.strokeOpacity, 0);
  assert.deepEqual(revealMain.options.path, [[121.42, 31.18], [121.42, 31.18]]);
  assert.equal(pendingFrameCount(), 1);

  flushFrame(0);
  flushFrame(600);
  assert.ok(revealMain.options.path.at(-1)[0] > 121.42);
  assert.ok(revealMain.options.path.at(-1)[0] < 121.425);

  flushFrame(1200);
  assert.equal(sourceLayers.main.options.strokeOpacity, 1);
  assert.equal(pendingFrameCount(), 0);
});

test("返回总览会取消尚未完成的路线揭示动画", () => {
  const { mapContext, removed, pendingFrameCount } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes([routes[0]]);
  const sourceLayers = mapContext.routeLayers.get("XH_WALK_0001");
  controller.focusRoute("XH_WALK_0001");

  controller.showOverview();

  assert.equal(pendingFrameCount(), 0);
  assert.equal(removed.some((overlay) => overlay.options.extData?.layerRole === "reveal-main"), true);
  assert.equal(sourceLayers.main.options.strokeOpacity, 0.78);
  assert.deepEqual(semanticMarkerRoles(mapContext), []);
});

test("低动态偏好下详情直接显示完整路线", () => {
  const { mapContext, added, pendingFrameCount } = createMapContext({ reducedMotion: true });
  const controller = createRecommendationMapController(mapContext);
  controller.showRoutes([routes[0]]);

  controller.focusRoute("XH_WALK_0001");

  assert.equal(added.some((overlay) => overlay.options.extData?.layerRole === "reveal-main"), false);
  assert.equal(pendingFrameCount(), 0);
  assert.deepEqual(semanticMarkerRoles(mapContext), ["start", "end"]);
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

test("徐汇区边界使用中性灰绿且不再叠加竖排区名", () => {
  const source = readFileSync(new URL("../web/src/map.js", import.meta.url), "utf8");
  const drawBoundarySource = source.slice(
    source.indexOf("export function drawBoundary"),
    source.indexOf("export function fitBoundaryView"),
  );

  assert.match(drawBoundarySource, /strokeColor:\s*"#5B6C63"/);
  assert.match(drawBoundarySource, /fillColor:\s*"#5B6C63"/);
  assert.match(drawBoundarySource, /strokeWeight:\s*3/);
  assert.match(drawBoundarySource, /strokeOpacity:\s*0\.78/);
  assert.match(drawBoundarySource, /fillOpacity:\s*0\.04/);
  assert.match(drawBoundarySource, /bubble:\s*true/);
  assert.doesNotMatch(drawBoundarySource, /addBoundaryLabel/);
  assert.doesNotMatch(source, /amap-boundary-label/);
});

test("健康底图默认隐藏通用 POI，标准底图可恢复完整要素", () => {
  const source = readFileSync(new URL("../web/src/map.js", import.meta.url), "utf8");
  assert.match(source, /DEFAULT_BASE_MAP_MODE\s*=\s*"health"/);
  assert.match(source, /mapStyle:\s*"amap:\/\/styles\/fresh"/);
  assert.match(source, /features:\s*Object\.freeze\(\["bg",\s*"road",\s*"building"\]\)/);

  const calls = [];
  const mapContext = {
    amap: {
      setMapStyle(value) {
        calls.push(["style", value]);
      },
      setFeatures(value) {
        calls.push(["features", value]);
      },
    },
    baseMapMode: "health",
  };

  assert.equal(setBaseMapMode(mapContext, "standard"), "standard");
  assert.equal(mapContext.baseMapMode, "standard");
  assert.deepEqual(calls, [
    ["style", "amap://styles/normal"],
    ["features", ["bg", "point", "road", "building"]],
  ]);
  assert.throws(() => setBaseMapMode(mapContext, "unknown"), /未知底图模式/);
});

test("健康地图只选取十九个绿地、地标和补给点，并按缩放逐级显示", () => {
  const entries = JSON.parse(
    readFileSync(new URL("../data/web/xuhui_entries.geojson", import.meta.url), "utf8"),
  );
  const pois = JSON.parse(
    readFileSync(new URL("../data/web/poi_catalog.json", import.meta.url), "utf8"),
  );

  const models = healthMapPlaceModels(entries, pois);
  const categoryCounts = Object.fromEntries(
    ["green", "landmark", "supply"].map((category) => [
      category,
      models.filter((model) => model.category === category).length,
    ]),
  );

  assert.equal(models.length, 19);
  assert.deepEqual(categoryCounts, { green: 5, landmark: 5, supply: 9 });
  assert.equal(models.filter((model) => model.minZoom <= 13).length, 8);
  assert.equal(models.filter((model) => model.minZoom <= 15).length, 12);
  assert.equal(new Set(models.map((model) => model.sourceId)).size, models.length);
  assert.equal(models.every((model) => model.interactive === false), true);
  assert.equal(models.some((model) => model.name.includes("医院")), false);
  assert.equal(models.some((model) => model.name.includes("餐厅")), false);
});

test("健康地点层保持静态并只随两张底图切换显隐", () => {
  const entries = JSON.parse(
    readFileSync(new URL("../data/web/xuhui_entries.geojson", import.meta.url), "utf8"),
  );
  const pois = JSON.parse(
    readFileSync(new URL("../data/web/poi_catalog.json", import.meta.url), "utf8"),
  );
  const visibility = [];
  const added = [];

  class LabelsLayer {
    constructor(options) {
      this.options = options;
      this.markers = [];
    }

    add(marker) {
      this.markers.push(marker);
    }

    show() {
      visibility.push("show");
    }

    hide() {
      visibility.push("hide");
    }
  }

  class LabelMarker {
    constructor(options) {
      this.options = options;
    }
  }

  const mapContext = {
    AMap: { LabelsLayer, LabelMarker },
    amap: {
      add(layer) {
        added.push(layer);
      },
      remove() {},
      setMapStyle() {},
      setFeatures() {},
    },
    baseMapMode: "health",
    healthPlaceLayer: null,
    healthPlaceMarkers: [],
  };

  const markers = showHealthMapPlaces(mapContext, entries, pois);

  assert.equal(added.length, 1);
  assert.equal(markers.length, 19);
  assert.equal(mapContext.healthPlaceLayer.options.collision, true);
  assert.equal(mapContext.healthPlaceLayer.options.allowCollision, false);
  assert.equal(markers.every((marker) => marker.options.extData.interactive === false), true);
  assert.equal(markers.every((marker) => marker.options.zooms[1] === 20), true);
  assert.equal(markers.every((marker) => marker.options.icon.image.startsWith("data:image/svg+xml")), true);

  setBaseMapMode(mapContext, "standard");
  setBaseMapMode(mapContext, "health");
  assert.deepEqual(visibility, ["show", "hide", "show"]);
});

test("步行路线使用品牌蓝并继续保留白色外描边", () => {
  const source = readFileSync(new URL("../web/src/map.js", import.meta.url), "utf8");
  assert.match(source, /walk:\s*\{\s*color:\s*"#197cff",\s*weight:\s*4\s*\}/);
  assert.match(source, /strokeColor:\s*"#ffffff"/);
});

test("推荐路线根据运动模式使用图例语义色", () => {
  const { mapContext } = createMapContext();
  const controller = createRecommendationMapController(mapContext);
  const modeRoutes = [
    createRoute("XH_WALK_COLOR", 121.42, "walk"),
    createRoute("XH_RUN_COLOR", 121.43, "run"),
    createRoute("XH_BIKE_COLOR", 121.44, "bike"),
    createRoute("XH_ACCESS_COLOR", 121.45, "access"),
  ];

  controller.showRoutes(modeRoutes);

  const colors = Object.fromEntries(
    [...mapContext.routeLayers.entries()].map(([routeId, layers]) => [
      routeId,
      layers.main.options.strokeColor,
    ]),
  );
  assert.deepEqual(colors, {
    XH_WALK_COLOR: "#197cff",
    XH_RUN_COLOR: "#D45A50",
    XH_BIKE_COLOR: "#6F5AB7",
    XH_ACCESS_COLOR: "#C9872F",
  });
});

test("详情关闭按来源恢复推荐总览或当前浏览筛选总览", () => {
  const routeUiSource = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");
  const mainSource = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");

  assert.ok(routeUiSource.includes("restoreBrowseOverview("), "浏览控制器缺少 restoreBrowseOverview()");
  assert.match(mainSource, /onClose\s*\(\s*\{\s*source\s*,\s*routeId\s*\}\s*\)/, "详情关闭回调缺少 source/routeId");
  assert.match(
    mainSource,
    /if\s*\(source !== uiState\.productView\)\s*\{\s*routeDock\.hide\(\);\s*renderProductView\(\);\s*syncWorkbench\(\);\s*return;/s,
    "过期详情来源仍可能恢复另一功能的界面",
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

function createRoute(routeId, startLng, routeMode = "walk") {
  return {
    type: "Feature",
    properties: {
      route_id: routeId,
      route_name: routeId,
      route_mode: routeMode,
      start_location: { name: "默认起点", lng_gcj02: startLng, lat_gcj02: 31.18 },
      end_location: { name: "默认终点", lng_gcj02: startLng + 0.005, lat_gcj02: 31.185 },
    },
    geometry: {
      type: "LineString",
      coordinates: [[startLng, 31.18], [startLng + 0.005, 31.185]],
    },
  };
}

function createMapContext({ reducedMotion = false } = {}) {
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

    setPath(path) {
      this.options.path = path;
    }
  }

  const fitViews = [];
  const added = [];
  const removed = [];
  const removedCalls = [];
  const pendingFrames = new Map();
  let nextFrameId = 1;
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
      remove(overlays) {
        removedCalls.push(overlays);
        removed.push(...(Array.isArray(overlays) ? overlays : [overlays]));
      },
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
    semanticMarkerLayers: [],
    routeRevealMotion: {
      prefersReducedMotion: reducedMotion,
      requestFrame(callback) {
        const frameId = nextFrameId;
        nextFrameId += 1;
        pendingFrames.set(frameId, callback);
        return frameId;
      },
      cancelFrame(frameId) {
        pendingFrames.delete(frameId);
      },
    },
  };
  return {
    mapContext,
    fitViews,
    added,
    removed,
    removedCalls,
    flushFrame(timestamp) {
      const callbacks = [...pendingFrames.values()];
      pendingFrames.clear();
      callbacks.forEach((callback) => callback(timestamp));
    },
    pendingFrameCount: () => pendingFrames.size,
  };
}

function routeStates(mapContext) {
  return [...mapContext.routeLayers.values()].map(({ state }) => state);
}

function routeMainLayers(mapContext) {
  return [...mapContext.routeLayers.values()].map(({ main }) => main);
}

function semanticMarkerRoles(mapContext) {
  return mapContext.semanticMarkerLayers.map((marker) => marker.options.extData.role);
}

function semanticMarkerNames(mapContext) {
  return mapContext.semanticMarkerLayers.map((marker) => marker.options.extData.name);
}

function semanticMarkerPositions(mapContext) {
  return mapContext.semanticMarkerLayers.map((marker) => marker.options.position);
}

function verifiedPoi(poiId, poiName, poiType, distanceM) {
  return {
    poi_id: poiId,
    poi_name: poiName,
    poi_type: poiType,
    distance_m: distanceM,
    route_relation: "along_route",
    verification_status: "verified",
  };
}

function poiFeature(poiId, poiName, poiType, coordinates) {
  return {
    type: "Feature",
    properties: { poi_id: poiId, poi_name: poiName, poi_type: poiType },
    geometry: { type: "Point", coordinates },
  };
}
