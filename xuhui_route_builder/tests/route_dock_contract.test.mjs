import assert from "node:assert/strict";
import test from "node:test";

import { buildRouteDockModel, createRouteDock } from "../web/src/route-dock.js";
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

const sampleEnvironment = {
  routeId: "XH_RUN_0001",
  status: "partial",
  pm25: {
    label: "PM2.5",
    value: 15.3,
    displayValue: "15.3",
    unit: "µg/m³",
    status: "ok",
  },
  pollen: {
    label: "花粉",
    value: 31.5,
    displayValue: "31.5",
    unit: "0-100 risk index",
    status: "partial",
    riskLevel: "低",
  },
  noise: {
    label: "噪声",
    value: 36.8,
    displayValue: "36.8",
    unit: "0-100 risk index",
    status: "partial",
    riskLevel: "中",
  },
  details: {
    pm25: "PM2.5 为沿路线汇总的 1 km 网格估计值。",
    pollen: "花粉为约 1 km 网格采样形成的当天风险指数。",
    noise: "噪声为约 100 m 路段的 0–100 风险代理。",
  },
};

test("dock 概览使用真实路线信息和三类路线暴露，不生成综合分数", () => {
  const model = buildRouteDockModel(sampleRoute.properties, sampleEnvironment);

  assert.equal(model.modeLabel, "跑步");
  assert.equal(model.distanceText, "4.8 km");
  assert.equal(model.durationText, "32 分钟");
  assert.equal(model.journeyText, "4.8 km · 32 分钟");
  assert.equal(model.exposures.pm25.label, "PM2.5");
  assert.equal(model.exposures.pm25.compactText, "15.3 µg/m³");
  assert.equal(model.exposures.pollen.compactText, "低 · 31.5");
  assert.equal(model.exposures.noise.compactText, "中 · 36.8");
  assert.equal(model.exposures.pollen.statusLabel, "估计数据");
  assert.match(model.exposures.pm25.detail, /1 km.*估计/);
  assert.match(model.exposures.pollen.detail, /当天/);
  assert.match(model.exposures.noise.detail, /约 100 m.*0–100.*风险代理/);
  assert.doesNotMatch(JSON.stringify(model), /分贝|实测/);
  assert.deepEqual(model.waypoints, ["龙美术馆", "滨江滑板公园"]);
  assert.equal("healthScore" in model, false);
  assert.equal("recommendation" in model, false);
  assert.equal(JSON.stringify(model).includes("未来 PM2.5"), false);
  assert.equal(JSON.stringify(model).includes("未来花粉"), false);
});

test("dock 对缺失、过期和 partial 环境状态使用稳定文案", () => {
  const missing = buildRouteDockModel(sampleRoute.properties);
  assert.equal(missing.exposures.pm25.compactText, "暂无数据");
  assert.equal(missing.exposures.pollen.compactText, "暂无数据");
  assert.equal(missing.exposures.noise.compactText, "暂无数据");

  const degraded = buildRouteDockModel(sampleRoute.properties, {
    ...sampleEnvironment,
    pm25: { displayValue: "数据更新中", status: "stale" },
    noise: { displayValue: "暂无数据", status: "no_data" },
  });
  assert.equal(degraded.exposures.pm25.compactText, "数据更新中");
  assert.equal(degraded.exposures.pm25.statusLabel, "数据更新中");
  assert.equal(degraded.exposures.noise.compactText, "暂无数据");
  assert.equal(degraded.exposures.noise.statusLabel, "暂无数据");
  assert.equal(degraded.exposures.pollen.statusLabel, "估计数据");
});

test("createRouteDock.show 接收路线环境并保留隐藏行为", () => {
  const previousDocument = globalThis.document;
  const { document, root, nodes } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const container = { appendChild(element) { this.child = element; } };
    const dock = createRouteDock(container);

    dock.show(sampleRoute, sampleEnvironment);

    assert.equal(container.child, root);
    assert.equal(root.hidden, false);
    assert.equal(nodes["[data-dock-route-name]"].textContent, "徐汇滨江跑步线");
    assert.equal(nodes["[data-dock-journey]"].textContent, "4.8 km · 32 分钟");
    assert.equal(nodes["[data-dock-overview-pm25]"].textContent, "15.3 µg/m³");
    assert.equal(nodes["[data-dock-pm25-value]"].textContent, "15.3 µg/m³");
    assert.equal(nodes["[data-dock-noise-risk]"].textContent, "中");
    assert.equal(nodes["[data-dock-noise-detail]"].textContent, sampleEnvironment.details.noise);
    assert.equal(nodes["[data-dock-exposure=\"noise\"]"].dataset.status, "partial");
    assert.equal(nodes["[data-dock-waypoint-list]"].children.length, 2);

    dock.hide();
    assert.equal(root.hidden, true);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("dock 在 waypoint_names 缺失时回退到 ordered_nodes 的中间节点", () => {
  const properties = { ...sampleRoute.properties, waypoint_names: [] };
  const model = buildRouteDockModel(properties);

  assert.deepEqual(model.waypoints, ["龙美术馆"]);
});

function createDockDocumentStub() {
  const nodes = {};
  const textSelectors = [
    "[data-dock-mode]",
    "[data-dock-route-name]",
    "[data-dock-journey]",
    "[data-dock-overview-pm25]",
    "[data-dock-overview-pollen]",
    "[data-dock-overview-noise]",
  ];
  for (const key of ["pm25", "pollen", "noise"]) {
    textSelectors.push(
      `[data-dock-${key}-value]`,
      `[data-dock-${key}-risk]`,
      `[data-dock-${key}-status]`,
      `[data-dock-${key}-detail]`,
    );
    nodes[`[data-dock-exposure="${key}"]`] = elementStub();
  }
  textSelectors.forEach((selector) => { nodes[selector] = elementStub(); });
  nodes["[data-dock-waypoint-list]"] = {
    children: [],
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
  };

  const tabs = ["overview", "environment", "waypoints"].map((dockTab) => (
    elementStub({ dockTab })
  ));
  const panels = ["overview", "environment", "waypoints"].map((dockPanel) => (
    elementStub({ dockPanel })
  ));
  const root = {
    dataset: {},
    hidden: false,
    attributes: {},
    html: "",
    set innerHTML(value) { this.html = value; },
    get innerHTML() { return this.html; },
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelector(selector) { return nodes[selector]; },
    querySelectorAll(selector) {
      if (selector === "[data-dock-tab]") return tabs;
      if (selector === "[data-dock-panel]") return panels;
      return [];
    },
  };
  const document = {
    createElement(tagName) {
      if (tagName === "section") return root;
      return elementStub();
    },
    createTextNode(value) { return { textContent: value }; },
  };
  return { document, root, nodes };
}

function elementStub(dataset = {}) {
  return {
    dataset,
    textContent: "",
    children: [],
    attributes: {},
    classList: { toggle() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener() {},
    append(...children) { this.children.push(...children); },
  };
}

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
