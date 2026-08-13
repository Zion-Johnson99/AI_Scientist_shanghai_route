import assert from "node:assert/strict";
import test from "node:test";

import {
  buildNavigationRequest,
  filterCandidateRoutes,
  resetPlannedNavigationForRouteChange,
  routeOptionLabel,
} from "../web/src/route-ui.js";
import { navigationServiceMode } from "../web/src/map.js";

const route = {
  route_id: "XH_RUN_0001",
  route_name: "徐汇滨江跑步线",
  route_mode: "run",
  start_location: {
    name: "星美术馆入口",
    lng_gcj02: 121.462,
    lat_gcj02: 31.184,
  },
};

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
      validation_status: "accepted",
    }),
    "东上澳塘滨水短线｜康健—桂江绿廊｜4.3 km｜严格验收",
  );
});
