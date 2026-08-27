import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  advancePlanningRevision,
  buildNavigationRequest,
  commitNavigationPlan,
  filterCandidateRoutes,
  filterNavigationRoutes,
  navigationPrimaryActionState,
  isCurrentPlanningRevision,
  selectBestRoute,
  startPlannedNavigation,
  resetNavigationForModeChange,
  resetPlannedNavigationForRouteChange,
  routeOptionLabel,
  selectNavigationRoute,
} from "../web/src/route-ui.js";
import { navigationServiceMode, poiMarkerLabel } from "../web/src/map.js";
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

test("导航页使用独立运动类型选项卡并置于路线和出发地之前", () => {
  const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
  const modeIndex = html.indexOf('id="navigationSportModeTabs"');
  const routeIndex = html.indexOf('id="navigationRouteSelect"');
  const originIndex = html.indexOf('id="startInput"');

  assert.ok(modeIndex >= 0);
  assert.ok(html.includes('data-navigation-mode="walk"'));
  assert.equal(html.match(/data-navigation-mode=/g)?.length, 3);
  assert.ok(modeIndex < routeIndex && routeIndex < originIndex);
});

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

test("切换导航运动类型会清除路线和旧接驳结果", () => {
  assert.deepEqual(resetNavigationForModeChange(), {
    navigationStatus: "ready",
    selectedRouteId: "",
    plannedRequest: null,
    plannedPlan: null,
  });
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

test("接驳尚未规划时不会启动导航预览", () => {
  let starts = 0;

  assert.equal(startPlannedNavigation("ready", null, { routeId: "XH_RUN_0001" }, {
    onStartInlineNavigation: () => starts += 1,
  }), false);
  assert.equal(starts, 0);
});

test("缺少导航预览处理器时不会伪报启动成功", () => {
  const request = buildNavigationRequest(route, { text: "上海南站" });

  assert.equal(startPlannedNavigation("planned", { path: [[121.45, 31.19], [121.46, 31.18]] }, request, {}), false);
});

test("接驳规划后把路径和请求交给导航预览", () => {
  const request = buildNavigationRequest(route, { text: "上海南站" });
  const plan = { path: [[121.45, 31.19], [121.46, 31.18]], distance: 1200 };
  let started = null;

  assert.equal(startPlannedNavigation("planned", plan, request, {
    onStartInlineNavigation: (value) => {
      started = value;
    },
  }), true);
  assert.strictEqual(started.plan, plan);
  assert.strictEqual(started.request, request);
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

test("切换目标路线后清除旧接驳完成状态", () => {
  assert.deepEqual(resetPlannedNavigationForRouteChange(), {
    navigationStatus: "ready",
    statusText: "路线已更新，请重新规划接驳路线。",
  });
});

test("导航主操作随规划状态只显示一个按钮", () => {
  assert.deepEqual(navigationPrimaryActionState("ready"), {
    showPlan: true,
    planDisabled: false,
    showPreview: false,
    previewDisabled: true,
  });
  assert.deepEqual(navigationPrimaryActionState("planning"), {
    showPlan: true,
    planDisabled: true,
    showPreview: false,
    previewDisabled: true,
  });
  assert.deepEqual(navigationPrimaryActionState("planned"), {
    showPlan: false,
    planDisabled: false,
    showPreview: true,
    previewDisabled: false,
  });
  assert.deepEqual(navigationPrimaryActionState("previewing"), {
    showPlan: false,
    planDisabled: false,
    showPreview: true,
    previewDisabled: true,
  });
});

test("路线变化后旧规划结果失效", () => {
  const state = {
    planningRevision: 0,
    navigationStatus: "planning",
    plannedNavigationRequest: null,
    plannedNavigationPlan: null,
  };
  const oldRevision = advancePlanningRevision(state);
  const oldRequest = { routeId: "XH_RUN_0001" };
  const oldPlan = { path: [[121.45, 31.19], [121.46, 31.18]] };

  assert.equal(isCurrentPlanningRevision(state, oldRevision), true);
  advancePlanningRevision(state);
  assert.equal(isCurrentPlanningRevision(state, oldRevision), false);
  assert.equal(commitNavigationPlan(state, oldRevision, oldPlan, oldRequest), false);
  assert.equal(state.navigationStatus, "planning");
  assert.equal(state.plannedNavigationRequest, null);
  assert.equal(state.plannedNavigationPlan, null);
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

test("路线下拉项只包含名称、片区、距离和路线形态", () => {
  assert.equal(
    routeOptionLabel({
      route_name: "东上澳塘滨水短线",
      region_zone: "康健—桂江绿廊",
      distance_m: 4338,
      route_shape: "one_way",
      validation_status: "accepted",
    }),
    "东上澳塘滨水短线｜康健—桂江绿廊｜4.3 km｜单程",
  );
});

test("路线界面使用手动出发地与导航预览回调", () => {
  const source = readFileSync(new URL("../web/src/route-ui.js", import.meta.url), "utf8");

  assert.match(source, /onPickNavigationPoint/);
  assert.match(source, /onNavigate/);
  assert.match(source, /onStartInlineNavigation/);
  assert.match(source, /onEndInlineNavigation/);
  assert.match(source, /planningRevision/);
  assert.match(source, /isCurrentPlanningRevision/);
  assert.doesNotMatch(source, /onStartNavigation/);
  assert.doesNotMatch(source, /onEndNavigation/);
  assert.doesNotMatch(source, /startNavigationButton/);
  assert.doesNotMatch(source, /endNavigationButton/);
  for (const removedCopy of ["用户位置", "徐汇区内", "实时定位", "严格验收", "待考证", "已切换"]) {
    assert.equal(source.includes(removedCopy), false);
  }
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
  });

  assert.deepEqual(model.waypoints, ["起点", "桂林路钦州南路口", "终点"]);
});
