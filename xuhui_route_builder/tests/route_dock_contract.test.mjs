import assert from "node:assert/strict";
import test from "node:test";

import { buildRouteDockModel } from "../web/src/route-dock.js";
import { clearRouteResults, showRouteResults, showSingleRoute } from "../web/src/map.js";

const sampleRoute = {
  type: "Feature",
  properties: {
    route_id: "XH_RUN_0001",
    route_name: "徐汇滨江跑步线",
    route_mode: "run",
    route_shape: "one_way",
    distance_m: 4820,
    duration_min: 31.6,
    waypoint_names: ["龙美术馆", "滨江滑板公园"],
    ordered_nodes: [{ node_name: "起点" }, { node_name: "龙美术馆" }, { node_name: "终点" }],
  },
  geometry: {
    type: "LineString",
    coordinates: [[121.45, 31.18], [121.46, 31.19]],
  },
};

test("dock 概览使用现有路线距离和时长，环境不生成虚构分数", () => {
  const model = buildRouteDockModel(sampleRoute.properties);

  assert.equal(model.modeLabel, "跑步");
  assert.equal(model.distanceText, "4.8 km");
  assert.equal(model.durationText, "32 分钟");
  assert.equal(model.environmentStatus, "数据待接入");
  assert.equal(model.environmentAssessment, "待评估");
  assert.deepEqual(model.waypoints, ["龙美术馆", "滨江滑板公园"]);
  assert.equal(JSON.stringify(model).includes("88"), false);
});

test("dock 在 waypoint_names 缺失时回退到 ordered_nodes 的中间节点", () => {
  const properties = { ...sampleRoute.properties, waypoint_names: [] };
  const model = buildRouteDockModel(properties);

  assert.deepEqual(model.waypoints, ["龙美术馆"]);
});

test("路线使用外描边和主色双层，清理时不留残层", () => {
  class Polyline {
    constructor(options) {
      this.options = options;
      this.events = new Map();
    }

    on(name, callback) {
      this.events.set(name, callback);
    }

    getExtData() {
      return this.options.extData;
    }

    setOptions(options) {
      Object.assign(this.options, options);
    }
  }

  const added = [];
  const removed = [];
  const mapContext = {
    AMap: { Polyline },
    amap: {
      add(overlay) { added.push(overlay); },
      remove(overlays) { removed.push(...overlays); },
      setFitView() {},
    },
    routeLayers: new Map(),
    entryLayers: [],
    poiLayers: [],
  };

  showRouteResults(mapContext, [sampleRoute], { features: [] }, { features: [] }, "XH_RUN_0001");

  assert.equal(added.length, 2);
  const [halo, main] = added;
  assert.equal(halo.options.extData.layerRole, "halo");
  assert.equal(main.options.extData.layerRole, "main");
  assert.ok(halo.options.strokeWeight > main.options.strokeWeight);
  assert.equal(main.options.showDir, true);
  assert.equal(halo.options.showDir, false);

  clearRouteResults(mapContext);
  assert.deepEqual(removed, [halo, main]);
  assert.equal(mapContext.routeLayers.size, 0);
});

test("单路线在端点标记完成后重新聚焦自身范围", () => {
  class Overlay {
    constructor(options) { this.options = options; }
    on() {}
  }
  const fitCalls = [];
  const mapContext = {
    AMap: { Polyline: Overlay, Marker: Overlay, Pixel: class {} },
    amap: {
      add() {},
      remove() {},
      setFitView(...args) { fitCalls.push(args); },
    },
    routeLayers: new Map(),
    entryLayers: [],
    poiLayers: [],
  };

  showSingleRoute(mapContext, sampleRoute, { features: [] }, { features: [] });

  assert.equal(fitCalls.length, 2);
  assert.equal(fitCalls.at(-1)[0].length, 3);
  assert.equal(fitCalls.at(-1)[1], true);
  assert.equal(fitCalls.at(-1)[3], 18);
});
