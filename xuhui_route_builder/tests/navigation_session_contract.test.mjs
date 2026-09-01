import assert from "node:assert/strict";
import test from "node:test";

import {
  createNavigationController,
  createNavigationSession,
  navigationPreviewState,
} from "../web/src/navigation-session.js";
import {
  clearRouteResults,
  endNavigationSession,
  navigationPlanFromResult,
  planNavigation,
  setNavigationPoint,
} from "../web/src/map.js";

const plan = {
  distance: 190,
  duration: 150,
  path: [
    [121.4600, 31.1800],
    [121.4610, 31.1800],
    [121.4620, 31.1800],
  ],
  steps: [
    { instruction: "沿龙腾大道向东", distance: 95 },
    { instruction: "直行到达运动路线起点", distance: 95 },
  ],
};

test("导航预览从高德规划的第一步开始", () => {
  const session = createNavigationSession(plan);
  const state = navigationPreviewState(session);

  assert.equal(session.status, "previewing");
  assert.equal(state.currentStepIndex, 0);
  assert.equal(state.stepNumber, 1);
  assert.equal(state.stepCount, 2);
  assert.equal(state.instruction, "沿龙腾大道向东");
  assert.equal(state.stepDistanceM, 95);
  assert.equal(state.totalDistanceM, 190);
  assert.equal(state.totalDurationS, 150);
  assert.equal(state.canGoPrevious, false);
  assert.equal(state.canGoNext, true);
  assert.equal(state.progressRatio, 0);
});

test("无分步结果时仍提供一条完整路线预览", () => {
  const session = createNavigationSession({ ...plan, steps: [] });
  const state = navigationPreviewState(session);

  assert.equal(state.stepCount, 1);
  assert.equal(state.instruction, "沿接驳路线前往运动路线起点");
  assert.equal(state.stepDistanceM, 190);
});

test("导航预览控制器支持下一步、上一步和边界停留", () => {
  const updates = [];
  const controller = createNavigationController({
    onProgress: (state) => updates.push(state),
  });

  assert.equal(controller.start(plan).currentStepIndex, 0);
  assert.equal(controller.next().currentStepIndex, 1);
  assert.equal(controller.next().currentStepIndex, 1);
  assert.equal(controller.previous().currentStepIndex, 0);
  assert.equal(controller.previous().currentStepIndex, 0);
  assert.deepEqual(updates.map((state) => state.currentStepIndex), [0, 1, 1, 0, 0]);
});

test("导航预览不访问设备定位，结束后回到空闲状态", () => {
  let endedState = null;
  const geolocation = {
    watchPosition() {
      throw new Error("导航预览不应读取设备定位");
    },
    clearWatch() {
      throw new Error("导航预览不应管理设备定位监听");
    },
  };
  const controller = createNavigationController({
    geolocation,
    onEnd: (state) => {
      endedState = state;
    },
  });

  controller.start(plan);
  const stopped = controller.stop();

  assert.equal(stopped.status, "idle");
  assert.equal(controller.getSession().status, "idle");
  assert.equal(endedState.status, "idle");
});

test("尚未开始预览时无法切换步骤", () => {
  const controller = createNavigationController();

  assert.throws(() => controller.next(), /尚未开始/);
  assert.throws(() => controller.previous(), /尚未开始/);
});

test("缺少完整路径时拒绝创建导航预览", () => {
  assert.throws(
    () => createNavigationSession({ path: [[121.46, 31.18]], steps: [] }),
    /缺少可预览的坐标数据/,
  );
});

test("上海地图选取的起点可位于徐汇区外，目的地仍受路线边界约束", () => {
  const mapContext = createMapContext();
  const origin = setNavigationPoint(mapContext, "origin", {
    lng_gcj02: 121.326,
    lat_gcj02: 31.200,
    label: "上海虹桥站",
  });

  assert.equal(origin.lng_gcj02, 121.326);
  assert.throws(
    () => setNavigationPoint(mapContext, "destination", origin),
    /点位不在徐汇区范围内/,
  );
});

test("上海地点文本解析后可从徐汇区外规划到正式路线起点", async () => {
  const mapContext = createMapContext();
  mapContext.serviceHooks.geocoder = {
    getLocation(text, callback) {
      assert.equal(text, "上海虹桥站");
      callback("complete", {
        geocodes: [{ location: new mapContext.AMap.LngLat(121.326, 31.200) }],
      });
    },
  };

  const result = await planNavigation(mapContext, {
    origin: { text: "上海虹桥站" },
    destination: { lng_gcj02: 121.440, lat_gcj02: 31.180 },
    routeId: "XH_WALK_0001",
    routeMode: "walk",
  });

  assert.equal(result.routeId, "XH_WALK_0001");
  assert.equal(mapContext.navigation.points.origin.lng_gcj02, 121.326);
  assert.equal(mapContext.navigation.points.destination.lng_gcj02, 121.440);
});

test("结束导航后迟到的旧规划不会写回状态和点位", async () => {
  const { mapContext, searches } = createDeferredMapContext();
  const pending = planNavigation(mapContext, navigationRequest("OLD", 121.326));
  await waitForSearches(searches, 1);

  endNavigationSession(mapContext);
  searches[0].callback("complete", navigationResult("旧规划"));

  await assert.rejects(pending, /规划已取消，请重新规划/);
  assert.equal(mapContext.navigation.state, "idle");
  assert.equal(mapContext.navigation.points.origin, null);
  assert.equal(mapContext.navigation.points.destination, null);
  assert.equal(mapContext.navigationService, null);
});

test("新规划完成后迟到的旧结果不会覆盖新点位或清理新服务", async () => {
  const { mapContext, searches, service } = createDeferredMapContext();
  const oldPending = planNavigation(mapContext, navigationRequest("OLD", 121.326));
  await waitForSearches(searches, 1);
  const newPending = planNavigation(mapContext, navigationRequest("NEW", 121.510));
  await waitForSearches(searches, 2);

  searches[1].callback("complete", navigationResult("新规划"));
  const latest = await newPending;
  const clearCountAfterLatest = service.clearCount;
  searches[0].callback("complete", navigationResult("旧规划"));

  await assert.rejects(oldPending, /规划已取消，请重新规划/);
  assert.equal(latest.routeId, "NEW");
  assert.equal(mapContext.navigation.state, "planned");
  assert.equal(mapContext.navigation.points.origin.lng_gcj02, 121.510);
  assert.equal(mapContext.navigationService, service);
  assert.equal(service.clearCount, clearCountAfterLatest);
});

test("路线图层切换后迟到的规划不会恢复旧导航状态", async () => {
  const { mapContext, searches } = createDeferredMapContext();
  const pending = planNavigation(mapContext, navigationRequest("OLD", 121.326));
  await waitForSearches(searches, 1);

  clearRouteResults(mapContext);
  searches[0].callback("complete", navigationResult("旧规划"));

  await assert.rejects(pending, /规划已取消，请重新规划/);
  assert.equal(mapContext.navigation.state, "editing");
  assert.equal(mapContext.navigation.points.origin, null);
  assert.equal(mapContext.navigation.points.destination, null);
  assert.equal(mapContext.navigationService, null);
});

test("高德步行结果保留路径坐标和分步指令", () => {
  const result = navigationPlanFromResult({
    routes: [{
      distance: 180,
      time: 140,
      steps: [
        {
          instruction: "沿龙腾大道向东",
          distance: 180,
          path: [
            { getLng: () => 121.46, getLat: () => 31.18 },
            { getLng: () => 121.462, getLat: () => 31.18 },
          ],
        },
      ],
    }],
  });

  assert.equal(result.distance, 180);
  assert.equal(result.duration, 140);
  assert.deepEqual(result.path, [[121.46, 31.18], [121.462, 31.18]]);
  assert.deepEqual(result.steps[0], {
    instruction: "沿龙腾大道向东",
    distance: 180,
  });
});

test("高德骑行结果可读取 rides 分步结构", () => {
  const result = navigationPlanFromResult({
    paths: [{
      distance: 260,
      duration: 200,
      rides: [{
        instruction: "沿滨江绿道骑行",
        distance: 260,
        path: [[121.46, 31.18], [121.463, 31.18]],
      }],
    }],
  });

  assert.equal(result.steps[0].instruction, "沿滨江绿道骑行");
  assert.equal(result.path.length, 2);
});

function createMapContext() {
  class LngLat {
    constructor(lng, lat) {
      this.lng = lng;
      this.lat = lat;
    }

    getLng() {
      return this.lng;
    }

    getLat() {
      return this.lat;
    }
  }

  class Marker {
    constructor(options) {
      this.options = options;
    }
  }

  class Pixel {
    constructor(x, y) {
      this.x = x;
      this.y = y;
    }
  }

  const result = {
    routes: [{
      distance: 1500,
      time: 1200,
      steps: [{
        instruction: "步行前往路线起点",
        distance: 1500,
        path: [[121.326, 31.200], [121.440, 31.180]],
      }],
    }],
  };
  const walking = {
    clear() {},
    search(origin, destination, callback) {
      assert.equal(origin.getLng(), 121.326);
      assert.equal(destination.getLng(), 121.440);
      callback("complete", result);
    },
  };

  return {
    AMap: { LngLat, Marker, Pixel },
    amap: {
      add() {},
      remove() {},
    },
    boundaryRings: [[
      [121.40, 31.15],
      [121.48, 31.15],
      [121.48, 31.22],
      [121.40, 31.22],
    ]],
    routeLayers: new Map(),
    routePreviewLayers: [],
    routePreviewMarkers: [],
    routePreviewZoomHandler: null,
    entryLayers: [],
    poiLayers: [],
    navigationService: null,
    navigation: {
      state: "editing",
      markers: new Map(),
      points: { origin: null, destination: null },
    },
    serviceHooks: {
      geocoder: null,
      walking,
      riding: null,
    },
  };
}

function createDeferredMapContext() {
  const mapContext = createMapContext();
  const searches = [];
  const service = {
    clearCount: 0,
    clear() {
      this.clearCount += 1;
    },
    search(origin, destination, callback) {
      searches.push({ origin, destination, callback });
    },
  };
  mapContext.serviceHooks.walking = service;
  return { mapContext, searches, service };
}

function navigationRequest(routeId, originLng) {
  return {
    origin: { lng_gcj02: originLng, lat_gcj02: 31.200 },
    destination: { lng_gcj02: 121.440, lat_gcj02: 31.180 },
    routeId,
    routeMode: "walk",
  };
}

function navigationResult(instruction) {
  return {
    routes: [{
      distance: 1500,
      time: 1200,
      steps: [{
        instruction,
        distance: 1500,
        path: [[121.326, 31.200], [121.440, 31.180]],
      }],
    }],
  };
}

async function waitForSearches(searches, count) {
  for (let attempt = 0; attempt < 10 && searches.length < count; attempt += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(searches.length, count);
}
