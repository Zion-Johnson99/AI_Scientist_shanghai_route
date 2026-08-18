import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildNavigationRequest,
  filterCandidateRoutes,
  filterNavigationRoutes,
  selectBestRoute,
  startPlannedNavigation,
  resetNavigationForModeChange,
  resetPlannedNavigationForRouteChange,
  routeOptionLabel,
  selectNavigationRoute,
} from "../web/src/route-ui.js";
import { navigationServiceMode } from "../web/src/map.js";

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

test("导航页使用独立运动类型选项卡并置于路线和用户位置之前", () => {
  const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
  const modeIndex = html.indexOf('id="navigationSportModeTabs"');
  const routeIndex = html.indexOf('id="navigationRouteSelect"');
  const originIndex = html.indexOf('id="startInput"');

  assert.ok(modeIndex >= 0);
  assert.ok(html.includes('data-navigation-mode="walk"'));
  assert.equal(html.match(/data-navigation-mode=/g)?.length, 3);
  assert.ok(modeIndex < routeIndex && routeIndex < originIndex);
});

test("导航路线下拉只保留当前运动类型的严格验收路线", () => {
  const routes = filterNavigationRoutes(navigationCatalog, "bike");

  assert.deepEqual(routes.map((item) => item.route_id), ["XH_BIKE_0001"]);
});

test("自动推荐跳过待考证路线", () => {
  const selected = selectBestRoute([
    { ...route, route_id: "XH_RUN_REVIEW", validation_status: "needs_review" },
    { ...route, route_id: "XH_RUN_ACCEPTED", validation_status: "accepted" },
  ]);

  assert.equal(selected.route_id, "XH_RUN_ACCEPTED");
});

test("切换导航运动类型会清除路线和旧接驳结果", () => {
  assert.deepEqual(resetNavigationForModeChange("planned"), {
    navigationStatus: "editing",
    selectedRouteId: "",
    plannedRequest: null,
    launchDisabled: true,
  });
  assert.equal(resetNavigationForModeChange("idle").navigationStatus, "idle");
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

test("接驳尚未规划时不会启动网页内导航", () => {
  let starts = 0;

  assert.equal(startPlannedNavigation("editing", null, { routeId: "XH_RUN_0001" }, {
    onStartInlineNavigation: () => starts += 1,
  }), false);
  assert.equal(starts, 0);
});

test("缺少网页导航处理器时不会伪报启动成功", () => {
  const request = buildNavigationRequest(route, { text: "上海南站" });

  assert.equal(startPlannedNavigation("planned", { path: [[121.45, 31.19], [121.46, 31.18]] }, request, {}), false);
});

test("接驳规划后把路径和请求交给网页内导航", () => {
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
    name: "用户位置",
  });

  assert.deepEqual(request, {
    origin: {
      lng_gcj02: 121.451,
      lat_gcj02: 31.191,
      name: "用户位置",
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
  assert.deepEqual(resetPlannedNavigationForRouteChange("sporting"), {
    navigationStatus: "editing",
    statusText: "目标路线已切换，请重新规划到新路线起点的接驳。",
    startSportDisabled: true,
  });
  assert.equal(resetPlannedNavigationForRouteChange("idle"), null);
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

test("路线下拉项包含名称、片区、距离和验收状态", () => {
  assert.equal(
    routeOptionLabel({
      route_name: "东上澳塘滨水短线",
      region_zone: "康健—桂江绿廊",
      distance_m: 4338,
      route_shape: "one_way",
      validation_status: "accepted",
    }),
    "东上澳塘滨水短线｜康健—桂江绿廊｜4.3 km｜单程｜严格验收",
  );
});

test("公园与补给筛选使用正式偏好字段", () => {
  const catalog = [
    {
      route_id: "XH_WALK_0001",
      route_name: "测试路线",
      route_mode: "walk",
      region_zone: "徐汇滨江",
      target_distance_m: 1500,
      tags: [],
      preference_hits: ["park_gate", "convenience"],
    },
  ];

  const routes = filterCandidateRoutes(catalog, {
    zone: "all",
    keyword: "",
    mode: "walk",
    distance: "all",
    preferences: ["park_gate", "convenience"],
  });

  assert.equal(routes.length, 1);
});
