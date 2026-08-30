import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildObjectiveHighlights,
  buildRouteForecastModel,
  buildRouteDockModel,
  buildRouteDockSource,
  createRouteDock,
} from "../web/src/route-dock.js";
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
  assert.match(model.exposures.pm25.detail, /1 km/);
  assert.match(model.exposures.pollen.detail, /当天/);
  assert.match(model.exposures.noise.detail, /沿路线分段.*0–100.*风险指数/);
  assert.doesNotMatch(JSON.stringify(model), /分贝|实测|已更新|估计数据|约 100 m 路段的 0–100 风险代理/);
  assert.deepEqual(model.waypoints, ["龙美术馆", "滨江滑板公园"]);
  assert.equal("healthScore" in model, false);
  assert.equal("recommendation" in model, false);
  assert.equal(JSON.stringify(model).includes("未来 PM2.5"), false);
  assert.equal(JSON.stringify(model).includes("未来花粉"), false);
});

test("dock 对缺失、过期和 partial 环境状态使用稳定读数", () => {
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
  assert.equal(degraded.exposures.noise.compactText, "暂无数据");
  assert.equal("statusLabel" in degraded.exposures.pollen, false);
});

test("未来 3 小时从推荐计划时间起展示四个真实天气与 AQI 点", () => {
  const dashboard = forecastDashboard();
  const forecast = buildRouteForecastModel(
    dashboard,
    { target_time: "plus_2h" },
    () => new Date("2026-08-30T08:00:00+08:00"),
  );

  assert.equal(forecast.startTime, "2026-08-30T02:00:00.000Z");
  assert.deepEqual(forecast.points.map((point) => point.timeLabel), ["10:00", "11:00", "12:00", "13:00"]);
  assert.equal(forecast.points[0].weatherText, "多云");
  assert.equal(forecast.points[0].temperatureText, "27°");
  assert.equal(forecast.points[0].precipitationText, "降水 20%");
  assert.equal(forecast.points[0].aqiText, "AQI 45 · 优");
  assert.doesNotMatch(JSON.stringify(forecast), /pm25|PM2\.5|µg\/m³/);
});

test("浏览路线和无法解析的推荐时间都从当前时刻开始", () => {
  const dashboard = forecastDashboard();
  const now = () => new Date("2026-08-30T08:00:00+08:00");
  const browse = buildRouteForecastModel(dashboard, undefined, now);
  const invalidRecommendation = buildRouteForecastModel(
    dashboard,
    { target_time: "custom", custom_time: "" },
    now,
  );

  assert.equal(browse.startTime, "2026-08-30T00:00:00.000Z");
  assert.equal(invalidRecommendation.startTime, browse.startTime);
});

test("推荐详情把评分结果中的距离时间合并到地图路线", () => {
  const source = buildRouteDockSource(sampleRoute, {
    source: {
      route: {
        route: { distance_m: 868, duration_min: 12 },
      },
    },
  });
  const model = buildRouteDockModel(source);

  assert.equal(model.journeyText, "0.9 km · 12 分钟");
});

test("createRouteDock.show 以单页参数展示千问短优点与建议", () => {
  const previousDocument = globalThis.document;
  const { document, root, nodes } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const container = { appendChild(element) { this.child = element; } };
    const navigationTargets = [];
    const closed = [];
    const dock = createRouteDock(container, {
      onNavigate: (route) => navigationTargets.push(route.properties.route_id),
      onClose: (detail) => closed.push(detail),
    });

    dock.show({
      route: sampleRoute,
      environment: sampleEnvironment,
      source: "recommendation",
      objectiveHighlights: ["滨江步道连续"],
      qwenAdvantages: ["距离符合目标", "PM2.5 在候选中较低"],
      qwenSuggestions: ["雨天留意湿滑路面"],
      explanationSource: "qwen",
    });

    assert.equal(container.child, root);
    assert.equal(root.hidden, false);
    assert.equal(nodes["[data-dock-route-name]"].textContent, "徐汇滨江跑步线");
    assert.equal(nodes["[data-dock-duration]"].textContent, "32 分钟");
    assert.equal(nodes["[data-dock-distance]"].textContent, "4.8 km");
    assert.equal(nodes["[data-dock-pm25-core]"].textContent, "15.3 µg/m³");
    assert.equal(nodes["[data-dock-pm25-value]"].textContent, "15.3 µg/m³");
    assert.equal(nodes["[data-dock-noise-risk]"].textContent, "中");
    assert.equal(nodes["[data-dock-noise-detail]"].textContent, "噪声：沿路线分段汇总的 0–100 风险指数。");
    assert.equal(nodes["[data-dock-exposure=\"noise\"]"].dataset.status, "partial");
    assert.equal(nodes["[data-dock-overview-list]"].children.length, 4);
    assert.equal(nodes["[data-dock-overview-list]"].children[0].children[0].textContent, "A");
    assert.equal(nodes["[data-dock-overview-list]"].children.at(-1).children[0].textContent, "B");
    assert.equal(nodes["[data-dock-gallery]"].hidden, false);
    assert.equal(nodes["[data-dock-gallery]"].children.length, 3);
    assert.equal(nodes["[data-dock-forecast-list]"].children.length, 4);
    assert.equal(nodes["[data-dock-objective]"].hidden, false);
    assert.equal(nodes["[data-dock-objective-text]"].textContent, "滨江步道连续");
    assert.equal(nodes["[data-dock-recommendation]"].hidden, false);
    assert.equal(nodes["[data-dock-degraded]"].hidden, true);
    assert.deepEqual(
      nodes["[data-dock-advantage-list]"].children.map((item) => item.textContent),
      ["距离符合目标", "PM2.5 在候选中较低"],
    );
    assert.deepEqual(
      nodes["[data-dock-suggestion-list]"].children.map((item) => item.textContent),
      ["雨天留意湿滑路面"],
    );
    nodes["[data-dock-navigate]"].listeners.click();
    assert.deepEqual(navigationTargets, ["XH_RUN_0001"]);

    nodes["[data-dock-close]"].listeners.click();
    assert.deepEqual(closed, [{ source: "recommendation", routeId: "XH_RUN_0001" }]);
    assert.equal(root.hidden, true);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("圆形叉号触发带来源信息的关闭流程", () => {
  const previousDocument = globalThis.document;
  const { document, root, nodes } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const closed = [];
    let focusCount = 0;
    document.activeElement = { focus() { focusCount += 1; } };
    const dock = createRouteDock({ appendChild() {} }, { onClose: (detail) => closed.push(detail) });
    const detail = { route: sampleRoute, environment: sampleEnvironment, source: "browse" };

    dock.show(detail);
    assert.match(root.innerHTML, /route-dock__close/);
    assert.match(root.innerHTML, /aria-label="关闭路线详情"/);
    nodes["[data-dock-close]"].listeners.click();

    assert.deepEqual(closed, [{ source: "browse", routeId: "XH_RUN_0001" }]);
    assert.equal(focusCount, 1);
    assert.equal(root.hidden, true);

    dock.show(detail);
    dock.hide();
    assert.deepEqual(closed, [{ source: "browse", routeId: "XH_RUN_0001" }]);

    dock.show(detail);
    dock.dismiss();
    assert.deepEqual(closed, [
      { source: "browse", routeId: "XH_RUN_0001" },
      { source: "browse", routeId: "XH_RUN_0001" },
    ]);
    assert.equal(root.hidden, true);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("Escape 与圆形叉号共用带来源信息的关闭流程", () => {
  const previousDocument = globalThis.document;
  const { document, root } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const closed = [];
    const dock = createRouteDock({ appendChild() {} }, { onClose: (detail) => closed.push(detail) });
    const detail = { route: sampleRoute, environment: sampleEnvironment, source: "browse" };

    dock.show(detail);
    let prevented = false;
    root.listeners.keydown({ key: "Escape", preventDefault: () => { prevented = true; } });

    assert.deepEqual(closed, [{ source: "browse", routeId: "XH_RUN_0001" }]);
    assert.equal(prevented, true);
    assert.equal(root.hidden, true);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("工作台收起时通过详情关闭语义恢复对应路线总览", () => {
  const mainSource = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");

  assert.match(
    mainSource,
    /function setSidebarCollapsed\(collapsed\)\s*\{[\s\S]*?if \(nextCollapsed && uiState\.detailSource\)\s*\{[\s\S]*?routeDock\.dismiss\(\);[\s\S]*?\}/,
  );
});

test("Overview 自动移除与起终点重复的途经点", () => {
  const previousDocument = globalThis.document;
  const { document, nodes } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const dock = createRouteDock({ appendChild() {} });
    dock.show({
      route: {
        ...sampleRoute,
        properties: {
          ...sampleRoute.properties,
          waypoint_names: ["起点", "龙美术馆", "终点"],
        },
      },
      environment: sampleEnvironment,
      source: "browse",
    });

    const overview = nodes["[data-dock-overview-list]"].children;
    assert.deepEqual(overview.map((item) => item.children[0].textContent), ["A", "1", "B"]);
    assert.deepEqual(overview.map((item) => item.children[1].children[1].textContent), [
      "起点",
      "龙美术馆",
      "终点",
    ]);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("dock 在 waypoint_names 缺失时回退到 ordered_nodes 的中间节点", () => {
  const properties = { ...sampleRoute.properties, waypoint_names: [] };
  const model = buildRouteDockModel(properties);

  assert.deepEqual(model.waypoints, ["龙美术馆"]);
});

test("客观亮点只使用路线标签、形态和已核验沿途 POI", () => {
  const highlights = buildObjectiveHighlights({
    route_shape: "strict_loop",
    tags: ["滨江", "艺术", "滨江"],
    nearby_pois: [
      { poi_name: "公共厕所", verification_status: "verified", route_relation: "along_route" },
      { poi_name: "未核验咖啡店", verification_status: "pending", route_relation: "along_route" },
      { poi_name: "远离路线的驿站", verification_status: "verified", route_relation: "nearby" },
    ],
  });

  assert.deepEqual(highlights, [
    "路线形态：闭环路线",
    "路线标签：滨江、艺术",
    "沿途已核验：公共厕所",
  ]);
  assert.equal(highlights.join(" ").includes("未核验咖啡店"), false);
  assert.equal(highlights.join(" ").includes("远离路线的驿站"), false);
});

test("浏览详情隐藏千问内容，降级推荐显示轻提示且隐藏建议", () => {
  const previousDocument = globalThis.document;
  const { document, nodes } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const dock = createRouteDock({ appendChild() {} });
    dock.show({
      route: sampleRoute,
      environment: sampleEnvironment,
      source: "browse",
      qwenAdvantages: ["不应出现在浏览详情"],
      qwenSuggestions: ["不应出现在浏览详情"],
      explanationSource: "qwen",
    });
    assert.equal(nodes["[data-dock-recommendation]"].hidden, true);
    assert.equal(nodes["[data-dock-degraded]"].hidden, true);

    dock.show({
      route: sampleRoute,
      environment: sampleEnvironment,
      source: "recommendation",
      objectiveHighlights: ["路线形态：单向路线"],
      qwenAdvantages: ["迟到解释"],
      qwenSuggestions: ["迟到建议"],
      explanationSource: "degraded",
    });
    assert.equal(nodes["[data-dock-degraded]"].hidden, false);
    assert.equal(nodes["[data-dock-recommendation]"].hidden, true);
    assert.equal(nodes["[data-dock-suggestions]"].hidden, true);
    assert.equal(nodes["[data-dock-objective]"].hidden, false);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问详情最多展示 3 条优点和 2 条建议", () => {
  const previousDocument = globalThis.document;
  const { document, nodes } = createDockDocumentStub();
  globalThis.document = document;
  try {
    const dock = createRouteDock({ appendChild() {} });
    dock.show({
      route: sampleRoute,
      environment: sampleEnvironment,
      source: "recommendation",
      explanationSource: "qwen",
      qwenAdvantages: ["距离合适", "空气较好", "绿地连续", "交通便利"],
      qwenSuggestions: ["避开高峰", "留意花粉", "携带补给"],
    });

    assert.deepEqual(
      nodes["[data-dock-advantage-list]"].children.map((item) => item.textContent),
      ["距离合适", "空气较好", "绿地连续"],
    );
    assert.deepEqual(
      nodes["[data-dock-suggestion-list]"].children.map((item) => item.textContent),
      ["避开高峰", "留意花粉"],
    );
  } finally {
    globalThis.document = previousDocument;
  }
});

test("详情只渲染一个底部前往起点操作", () => {
  const previousDocument = globalThis.document;
  const { document, root } = createDockDocumentStub();
  globalThis.document = document;
  try {
    createRouteDock({ appendChild() {} });

    assert.equal((root.innerHTML.match(/data-dock-navigate/g) || []).length, 1);
    assert.match(
      root.innerHTML,
      /<\/div>\s*<footer class="route-dock__actions">\s*<button[^>]*data-dock-navigate>\u524d\u5f80\u8d77\u70b9<\/button>\s*<\/footer>/,
    );
  } finally {
    globalThis.document = previousDocument;
  }
});

test("详情保留三类环境读数，状态字移除且三行口径位于滚动区底部", () => {
  const previousDocument = globalThis.document;
  const { document, root } = createDockDocumentStub();
  globalThis.document = document;
  try {
    createRouteDock({ appendChild() {} });

    assert.match(root.innerHTML, /data-dock-exposure="pm25"/);
    assert.match(root.innerHTML, /data-dock-exposure="pollen"/);
    assert.match(root.innerHTML, /data-dock-exposure="noise"/);
    assert.doesNotMatch(root.innerHTML, /data-dock-(?:pm25|pollen|noise)-status|已更新|估计数据/);
    assert.match(
      root.innerHTML,
      /route-dock__environment-notes[\s\S]*data-dock-pm25-detail[\s\S]*data-dock-pollen-detail[\s\S]*data-dock-noise-detail[\s\S]*<\/div>\s*<\/div>\s*<footer/,
    );
  } finally {
    globalThis.document = previousDocument;
  }
});

test("右侧详情采用单页信息流，不再渲染概览、环境和途经点页签", () => {
  const previousDocument = globalThis.document;
  const { document, root } = createDockDocumentStub();
  globalThis.document = document;
  try {
    createRouteDock({ appendChild() {} });

    assert.doesNotMatch(root.innerHTML, /data-dock-tab|data-dock-panel|role="tab(?:list|panel)?"/);
    assert.doesNotMatch(root.innerHTML, /<button[^>]*>\s*(?:概览|环境|途经点)\s*<\/button>/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("详情样式固定右侧宽度、圆形叉号与底部主操作", () => {
  const css = readFileSync(new URL("../web/styles/main.css", import.meta.url), "utf8");

  assert.match(css, /\.route-dock\.route-dock--detail\s*\{[\s\S]*?width:\s*min\(390px,/);
  assert.match(css, /\.route-dock__close\s*\{[\s\S]*?border-radius:\s*50%/);
  assert.match(css, /\.route-dock__actions\s*\{[\s\S]*?position:\s*sticky;[\s\S]*?bottom:\s*0;/);
  assert.match(css, /\.route-dock__navigate\s*\{[\s\S]*?background:\s*var\(--brand-blue\)/);
});

function createDockDocumentStub() {
  const nodes = {};
  const textSelectors = [
    "[data-dock-mode]",
    "[data-dock-route-name]",
    "[data-dock-duration]",
    "[data-dock-distance]",
    "[data-dock-pm25-core]",
    "[data-dock-objective-text]",
  ];
  for (const key of ["pm25", "pollen", "noise"]) {
    textSelectors.push(
      `[data-dock-${key}-value]`,
      `[data-dock-${key}-risk]`,
      `[data-dock-${key}-detail]`,
    );
    nodes[`[data-dock-exposure="${key}"]`] = elementStub();
  }
  textSelectors.forEach((selector) => { nodes[selector] = elementStub(); });
  nodes["[data-dock-gallery]"] = listStub();
  nodes["[data-dock-forecast-list]"] = listStub();
  nodes["[data-dock-overview-list]"] = listStub();
  nodes["[data-dock-objective]"] = elementStub();
  nodes["[data-dock-degraded]"] = elementStub();
  nodes["[data-dock-recommendation]"] = elementStub();
  nodes["[data-dock-advantages]"] = elementStub();
  nodes["[data-dock-suggestions]"] = elementStub();
  nodes["[data-dock-advantage-list]"] = listStub();
  nodes["[data-dock-suggestion-list]"] = listStub();
  nodes["[data-dock-close]"] = elementStub();
  nodes["[data-dock-navigate]"] = elementStub();

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
    listeners: {},
    html: "",
    set innerHTML(value) { this.html = value; },
    get innerHTML() { return this.html; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, listener) { this.listeners[name] = listener; },
    querySelector(selector) { return nodes[selector]; },
    querySelectorAll(selector) {
      if (selector === "[data-dock-tab]") return tabs;
      if (selector === "[data-dock-panel]") return panels;
      return [];
    },
  };
  const document = {
    activeElement: null,
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
    listeners: {},
    addEventListener(name, listener) { this.listeners[name] = listener; },
    append(...children) { this.children.push(...children); },
  };
}

function listStub() {
  return {
    children: [],
    replaceChildren() { this.children = []; },
    append(...children) { this.children.push(...children); },
  };
}

function forecastDashboard() {
  const hourlyRecord = (hour, values, status = "ok") => ({
    business_time: `2026-08-30T${String(hour).padStart(2, "0")}:00:00+08:00`,
    status,
    values,
  });
  return {
    current: {
      weather: hourlyRecord(8, {
        weather_text: "晴",
        temperature_c: 25,
        precipitation_probability_pct: 0,
      }),
      aqi: hourlyRecord(8, { aqi: 36 }),
    },
    forecast: {
      weather_hourly: [9, 10, 11, 12, 13, 14].map((hour) => hourlyRecord(hour, {
        weather_text: "多云",
        temperature_c: hour + 17,
        precipitation_probability_pct: hour * 2,
      })),
      aqi_hourly: [9, 10, 11, 12, 13, 14].map((hour) => hourlyRecord(hour, { aqi: hour + 35 }, "partial")),
    },
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
