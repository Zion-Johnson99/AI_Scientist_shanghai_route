import assert from "node:assert/strict";
import test from "node:test";

import {
  createNavigationController,
  createNavigationSession,
  updateNavigationSession,
} from "../web/src/navigation-session.js";
import { navigationPlanFromResult } from "../web/src/map.js";

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

test("导航会话从完整接驳路径开始", () => {
  const session = createNavigationSession(plan);

  assert.equal(session.status, "navigating");
  assert.equal(session.totalDistanceM, 190);
  assert.equal(session.path.length, 3);
  assert.equal(session.steps[0].instruction, "沿龙腾大道向东");
});

test("沿路线前进会更新已走路径、剩余距离和当前指令", () => {
  const session = createNavigationSession(plan);
  const progress = updateNavigationSession(session, {
    lng: 121.46105,
    lat: 31.1800,
    accuracy: 8,
    heading: 90,
  });

  assert.equal(progress.status, "navigating");
  assert.ok(progress.progressRatio > 0.45 && progress.progressRatio < 0.65);
  assert.ok(progress.remainingDistanceM < 110);
  assert.equal(progress.instruction, "直行到达运动路线起点");
  assert.ok(progress.traveledPath.length >= 2);
  assert.ok(progress.remainingPath.length >= 2);
});

test("距离规划路线超过五十米会进入偏航状态", () => {
  const session = createNavigationSession(plan);
  const progress = updateNavigationSession(session, {
    lng: 121.4610,
    lat: 31.1807,
    accuracy: 10,
  });

  assert.equal(progress.status, "off_route");
  assert.equal(progress.shouldReroute, true);
  assert.ok(progress.distanceFromRouteM > 50);
});

test("进入终点二十五米范围会完成接驳", () => {
  const session = createNavigationSession(plan);
  const progress = updateNavigationSession(session, {
    lng: 121.4619,
    lat: 31.1800,
    accuracy: 6,
  });

  assert.equal(progress.status, "arrived");
  assert.equal(progress.remainingDistanceM, 0);
  assert.equal(progress.instruction, "已到达运动路线起点");
});

test("浏览器定位控制器启用高精度监听并可结束", () => {
  let successHandler = null;
  let clearedId = null;
  const updates = [];
  const geolocation = {
    watchPosition(onSuccess, _onError, options) {
      successHandler = onSuccess;
      assert.equal(options.enableHighAccuracy, true);
      return 17;
    },
    clearWatch(id) {
      clearedId = id;
    },
  };
  const controller = createNavigationController({
    geolocation,
    onProgress: (progress) => updates.push(progress),
  });

  controller.start(plan);
  successHandler({
    coords: { longitude: 121.4605, latitude: 31.1800, accuracy: 7, heading: 90 },
    timestamp: 1234,
  });
  controller.stop();

  assert.equal(updates.length, 1);
  assert.equal(updates[0].position.accuracy, 7);
  assert.equal(clearedId, 17);
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
