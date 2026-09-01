import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildNavigationRequest,
  filterCandidateRoutes,
  filterNavigationRoutes,
  isMapLocationSelectionAllowed,
  selectBestRoute,
  selectNavigationRoute,
  startDirectNavigation,
} from "../web/src/route-ui.js";
import {
  navigationServiceMode,
  planNavigation,
  poiMarkerLabel,
  resolveUserLocation,
} from "../web/src/map.js";
import { buildRouteDockModel } from "../web/src/route-dock.js";

const route = {
  route_id: "XH_RUN_0001",
  route_name: "徐汇滨江跑步线",
  route_mode: "run",
  route_shape: "one_way",
  validation_status: "accepted",
  start_location: {
    name: "星美术馆入口",
    lng_gcj02: 121.462,
    lat_gcj02: 31.184,
  },
};

const navigationCatalog = [
  { ...route, route_id: "XH_RUN_0001", route_mode: "run" },
  { ...route, route_id: "XH_WALK_0001", route_name: "衡复步行线", route_mode: "walk" },
  { ...route, route_id: "XH_BIKE_0001", route_name: "滨江骑行线", route_mode: "bike" },
  { ...route, route_id: "XH_BIKE_0002", route_name: "待考证骑行线", route_mode: "bike", validation_status: "needs_review" },
];

test("导航路线下拉保留当前运动类型的全部路线", () => {
  const routes = filterNavigationRoutes(navigationCatalog, "bike");

  assert.deepEqual(routes.map((item) => item.route_id), ["XH_BIKE_0001", "XH_BIKE_0002"]);
});

test("导航三种运动类型均保留30条路线", () => {
  const catalog = Array.from({ length: 90 }, (_, index) => ({
    route_id: `XH_${index + 1}`,
    route_mode: ["walk", "run", "bike"][Math.floor(index / 30)],
    validation_status: index % 2 ? "needs_review" : "accepted",
  }));

  for (const mode of ["walk", "run", "bike"]) {
    const routes = filterNavigationRoutes(catalog, mode);
    assert.equal(routes.length, 30);
    assert.ok(routes.some((item) => item.validation_status === "needs_review"));
  }
});

test("自动推荐跳过待考证路线", () => {
  const selected = selectBestRoute([
    { ...route, route_id: "XH_RUN_REVIEW", validation_status: "needs_review" },
    { ...route, route_id: "XH_RUN_ACCEPTED", validation_status: "accepted" },
  ]);

  assert.equal(selected.route_id, "XH_RUN_ACCEPTED");
});

test("选择导航目标路线立即显示路线并推送指标", () => {
  const shown = [];
  const metrics = [];

  const selected = selectNavigationRoute(navigationCatalog, "XH_WALK_0001", {
    onSelect: (routeId) => shown.push(routeId),
    onRouteMetrics: (selectedRoute) => metrics.push(selectedRoute),
  });

  assert.equal(selected.route_id, "XH_WALK_0001");
  assert.deepEqual(shown, ["XH_WALK_0001"]);
  assert.deepEqual(metrics, [selected]);
});

test("详情页前往起点一次完成接驳规划并打开导航预览", async () => {
  const origin = { text: "上海南站" };
  const request = buildNavigationRequest(route, origin);
  const plan = { path: [[121.45, 31.19], [121.46, 31.18]], distance: 1200 };
  const events = [];
  let started = null;

  const result = await startDirectNavigation(route, origin, {
    onNavigate: (value) => {
      events.push(["plan", value]);
      return plan;
    },
    onStartInlineNavigation: (value) => {
      events.push(["preview", value]);
      started = value;
    },
  });

  assert.deepEqual(events.map(([name]) => name), ["plan", "preview"]);
  assert.deepEqual(events[0][1], request);
  assert.strictEqual(started.plan, plan);
  assert.deepEqual(started.request, request);
  assert.deepEqual(result, { plan, request });
});

test("直接导航规划失败时不会打开预览", async () => {
  let starts = 0;

  await assert.rejects(
    startDirectNavigation(route, { text: "上海南站" }, {
      onNavigate: () => Promise.reject(new Error("高德规划失败")),
      onStartInlineNavigation: () => starts += 1,
    }),
    /高德规划失败/,
  );
  assert.equal(starts, 0);
});

test("缺少直接导航处理器时明确失败", async () => {
  await assert.rejects(
    startDirectNavigation(route, { text: "上海南站" }, {}),
    /接驳规划暂不可用/,
  );
});

test("接驳请求只包含用户起点和已选路线起点", () => {
  const request = buildNavigationRequest(route, {
    lng_gcj02: 121.451,
    lat_gcj02: 31.191,
    name: "上海南站",
  });

  assert.deepEqual(request, {
    origin: {
      lng_gcj02: 121.451,
      lat_gcj02: 31.191,
      name: "上海南站",
    },
    destination: route.start_location,
    routeId: "XH_RUN_0001",
    routeMode: "run",
  });
  assert.equal("waypoints" in request, false);
  assert.equal("mode" in request, false);
});

test("缺少正式路线起点时报告路线编号", () => {
  assert.throws(
    () => buildNavigationRequest({ ...route, start_location: null }, { lng_gcj02: 121.45, lat_gcj02: 31.19 }),
    /XH_RUN_0001.*起点数据/,
  );
});

test("跑步和步行使用步行服务，骑行使用骑行服务", () => {
  assert.equal(navigationServiceMode("walk"), "walk");
  assert.equal(navigationServiceMode("run"), "walk");
  assert.equal(navigationServiceMode("bike"), "bike");
  assert.throws(() => navigationServiceMode("drive"), /运动类型/);
});

test("前往起点规划期间保持已选正式路线的完整亮度", async () => {
  class Overlay {
    constructor(options) {
      this.options = { ...options };
    }

    setOptions(options) {
      Object.assign(this.options, options);
    }
  }

  class LngLat {
    constructor(lng, lat) {
      this.lng = lng;
      this.lat = lat;
    }

    getLng() { return this.lng; }
    getLat() { return this.lat; }
  }

  const selectedLayers = {
    routeMode: "walk",
    state: "sporting",
    halo: new Overlay({ strokeOpacity: 0.9 }),
    main: new Overlay({ strokeOpacity: 1 }),
  };
  const otherLayers = {
    routeMode: "walk",
    state: "muted",
    halo: new Overlay({ strokeOpacity: 0.12 }),
    main: new Overlay({ strokeOpacity: 0.1 }),
  };
  const mapContext = {
    AMap: {
      LngLat,
      Marker: class Marker extends Overlay {},
      Pixel: class Pixel {
        constructor(x, y) { this.x = x; this.y = y; }
      },
    },
    amap: {
      add() {},
      remove() {},
    },
    boundaryRings: [],
    routeLayers: new Map([
      ["XH_WALK_SELECTED", selectedLayers],
      ["XH_WALK_OTHER", otherLayers],
    ]),
    navigationService: null,
    navigation: {
      state: "sporting",
      planRevision: 0,
      serviceRevision: 0,
      markers: new Map(),
      points: { origin: null, destination: null },
      inlineLayers: null,
    },
    serviceHooks: {
      walking: {
        search(_origin, _destination, callback) {
          callback("complete", {
            routes: [{
              distance: 1200,
              time: 900,
              path: [[121.45, 31.19], [121.46, 31.18]],
              steps: [],
            }],
          });
        },
      },
      riding: null,
    },
  };

  await planNavigation(mapContext, {
    routeId: "XH_WALK_SELECTED",
    routeMode: "walk",
    origin: { lng_gcj02: 121.45, lat_gcj02: 31.19 },
    destination: { lng_gcj02: 121.46, lat_gcj02: 31.18 },
  });

  assert.equal(selectedLayers.state, "sporting");
  assert.equal(selectedLayers.main.options.strokeOpacity, 1);
  assert.equal(selectedLayers.halo.options.strokeOpacity, 0.9);
  assert.equal(otherLayers.state, "muted");
});

test("推荐位置接受用户主动选择的坐标且不请求设备定位", async () => {
  const location = await resolveUserLocation({}, {
    lng_gcj02: 121.437,
    lat_gcj02: 31.195,
    label: "徐家汇",
  });

  assert.deepEqual(location, {
    lng_gcj02: 121.437,
    lat_gcj02: 31.195,
    label: "徐家汇",
    source: "point",
  });
  const mapSource = readFileSync(new URL("../web/src/map.js", import.meta.url), "utf8");
  assert.doesNotMatch(mapSource, /navigator\.geolocation/);
  assert.match(mapSource, /showUserLocation/);
});

test("详情与导航预览期间锁定地图地点候选，总览恢复", () => {
  assert.equal(isMapLocationSelectionAllowed({ detailOpen: true, navigationActive: false }), false);
  assert.equal(isMapLocationSelectionAllowed({ detailOpen: false, navigationActive: true }), false);
  assert.equal(isMapLocationSelectionAllowed({ detailOpen: false, navigationActive: false }), true);
});

test("未勾选途经偏好时保留当前运动类型的全部候选路线", () => {
  const catalog = Array.from({ length: 90 }, (_, index) => ({
    route_id: `XH_${index + 1}`,
    route_name: `路线 ${index + 1}`,
    route_mode: ["walk", "run", "bike"][Math.floor(index / 30)],
    region_zone: "徐汇滨江",
    distance_m: 3000,
    tags: [],
    preference_hits: [],
  }));

  const routes = filterCandidateRoutes(catalog, {
    zone: "all",
    keyword: "",
    mode: "run",
    distance: "all",
    preferences: [],
  });

  assert.equal(routes.length, 30);
  assert.ok(routes.every((item) => item.route_mode === "run"));
});

test("普通浏览使用共享路线卡列表并保留筛选总览恢复接口", () => {
  const source = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");

  assert.match(source, /createRouteCard/);
  assert.match(source, /browseRouteList/);
  assert.match(source, /restoreBrowseOverview\(\)/);
  assert.doesNotMatch(source, /routeSelect\b/);
});

test("路线界面使用直接导航且不再绑定旧接驳页面", () => {
  const source = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");

  assert.match(source, /onNavigate/);
  assert.match(source, /onStartInlineNavigation/);
  assert.match(source, /onEndInlineNavigation/);
  assert.match(source, /startDirectNavigation/);
  assert.doesNotMatch(source, /openNavigation/);
  assert.doesNotMatch(source, /bindNavigationControls/);
  assert.doesNotMatch(source, /onPickNavigationPoint/);
  assert.doesNotMatch(source, /startPickButton/);
  assert.doesNotMatch(source, /routeNavigationView/);
  assert.doesNotMatch(source, /onStartNavigation/);
  assert.doesNotMatch(source, /onEndNavigation/);
  assert.doesNotMatch(source, /startNavigationButton/);
  assert.doesNotMatch(source, /endNavigationButton/);
  for (const removedCopy of ["用户位置", "徐汇区内", "实时定位", "严格验收", "待考证", "已切换"]) {
    assert.equal(source.includes(removedCopy), false);
  }
});

test("路线详情直接使用当前地点且地图点击随详情和导航锁定", () => {
  const source = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");

  assert.match(source, /const origin = currentLocation;/);
  assert.match(source, /planner\.startDirectNavigation\(routeId, origin\)/);
  assert.match(source, /detailOpen: Boolean\(uiState\.detailSource\)/);
  assert.match(source, /navigationActive/);
  assert.match(source, /routeId,[\s\S]*origin,[\s\S]*status: map\.navigation\.state,[\s\S]*error/);
  assert.doesNotMatch(source, /planner\.openNavigation/);
});

test("关闭路线详情会取消迟到的直接导航规划", () => {
  const source = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");
  const closeHandler = source.slice(source.indexOf("onClose({ source, routeId })"), source.indexOf("const routeFeaturesById"));

  assert.match(closeHandler, /planner\?\.endNavigationPreview\(\)/);
  assert.match(closeHandler, /stopInlineNavigation\(\)/);
  assert.match(closeHandler, /endNavigationSession\(map\)/);
});

test("途经偏好只使用真实附近POI", () => {
  const catalog = [
    {
      route_id: "XH_WALK_FALSE",
      route_name: "虚假偏好路线",
      route_mode: "walk",
      region_zone: "徐汇滨江",
      target_distance_m: 1500,
      tags: [],
      preference_hits: ["park_gate", "convenience"],
      nearby_pois: [],
    },
    {
      route_id: "XH_WALK_REAL",
      route_name: "真实偏好路线",
      route_mode: "walk",
      region_zone: "徐汇滨江",
      target_distance_m: 1500,
      tags: [],
      preference_hits: [],
      nearby_pois: [
        { poi_id: "PARK1", poi_type: "park_gate", poi_name: "邻近公园", route_relation: "nearby", distance_m: 168 },
        { poi_id: "STORE1", poi_type: "convenience", poi_name: "沿线便利店", route_relation: "along_route", distance_m: 20 },
      ],
    },
  ];

  const routes = filterCandidateRoutes(catalog, {
    zone: "all",
    keyword: "",
    mode: "walk",
    distance: "all",
    preferences: ["park_gate", "convenience"],
  });

  assert.deepEqual(routes.map((item) => item.route_id), ["XH_WALK_REAL"]);
});

test("POI标记显示真实类型和邻近公园距离", () => {
  assert.equal(poiMarkerLabel({ poi_type: "coffee" }), "咖啡");
  assert.equal(poiMarkerLabel({ poi_type: "toilet" }), "厕所");
  assert.equal(poiMarkerLabel({ poi_type: "convenience" }), "补给");
  assert.equal(poiMarkerLabel({ poi_type: "park_gate", route_relation: "along_route" }), "公园入口");
  assert.equal(poiMarkerLabel({ poi_type: "park_gate", route_relation: "nearby", distance_m: 168 }), "邻近公园·约168米");
});

test("途经点清除编号占位名称并保留真实路口", () => {
  const model = buildRouteDockModel({
    route_name: "测试路线",
    route_mode: "walk",
    distance_m: 1000,
    duration_min: 15,
    waypoint_names: ["起点", "本地实测单环节点01", "桂林路钦州南路口", "华泾龙华实测节点02", "终点"],
    ordered_nodes: [
      { name: "起点", lng_gcj02: 121.43, lat_gcj02: 31.18 },
      { name: "本地实测单环节点01", lng_gcj02: 121.431, lat_gcj02: 31.181 },
      { name: "桂林路钦州南路口", lng_gcj02: 121.432, lat_gcj02: 31.182 },
      { name: "华泾龙华实测节点02", lng_gcj02: 121.433, lat_gcj02: 31.183 },
      { name: "终点", lng_gcj02: 121.434, lat_gcj02: 31.184 },
    ],
  });

  assert.deepEqual(model.waypoints, ["桂林路钦州南路口"]);
});
