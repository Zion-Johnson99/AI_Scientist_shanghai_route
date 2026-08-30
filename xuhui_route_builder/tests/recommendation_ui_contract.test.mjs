import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRecommendationViewModel,
  buildUserProfile,
  createProfileDialog,
  createRecommendationUI,
} from "../web/src/recommendation-ui.js";

const questionnaire = {
  route_modes: [{ value: "walk", label: "步行" }, { value: "run", label: "跑步" }],
  distance_ranges: {
    walk: [{ value: "walk_short", label: "1 km", distance_min_m: 700, target_distance_m: 1000, distance_max_m: 1500 }],
    run: [{ value: "run_mid", label: "5 km", distance_min_m: 3000, target_distance_m: 5000, distance_max_m: 6000 }],
  },
  goals: [{ value: "balanced", label: "综合均衡" }],
  experience_levels: [{ value: "regular", label: "日常运动" }],
  age_groups: [{ value: "18_39", label: "18-39 岁" }],
  areas: [{ value: "west_bund", label: "徐汇滨江" }],
  interests: [{ value: "park", label: "公园" }],
  sensitivities: [{ value: "air", label: "空气" }],
  target_times: [
    { value: "now", label: "现在" },
    { value: "plus_2h", label: "2 小时后" },
    { value: "custom", label: "自定义" },
  ],
  search_scopes: [
    { value: "nearby_3000", label: "3 km 附近" },
    { value: "nearby_5000", label: "5 km 附近" },
    { value: "nearby_8000", label: "8 km 附近" },
    { value: "area", label: "指定片区" },
    { value: "all_xuhui", label: "全徐汇" },
  ],
  route_shapes: [{ value: "any", label: "不限" }],
};

const localProfile = {
  version: 1,
  age_group: "18_39",
  gender: "female",
  experience: "regular",
  sensitivities: ["air"],
};

const location = { label: "上海图书馆", lng_gcj02: 121.44, lat_gcj02: 31.18 };

test("构造 UserProfile 时性别留在本地，附近范围映射为半径", () => {
  const built = buildUserProfile({
    questionnaire,
    profile: localProfile,
    location,
    answers: {
      route_mode: "walk",
      distance_range: "walk_short",
      target_time: "plus_2h",
      goal: "balanced",
      search_scope: "nearby_5000",
      route_shape: "any",
      interests: ["park"],
      free_text: "希望安静",
    },
    now: () => new Date("2026-08-28T02:00:00.000Z"),
  });

  assert.equal(built.gender, undefined);
  assert.equal(built.version, undefined);
  assert.equal(built.target_time, "2026-08-28T04:00:00.000Z");
  assert.equal(built.search_radius_m, 5000);
  assert.deepEqual(built.origin, { lng_gcj02: 121.44, lat_gcj02: 31.18 });
  assert.deepEqual(built.area_ids, []);
  assert.equal(built.age_group, "18_39");
});

test("指定片区与全徐汇正确映射，自定义时间需有效", () => {
  const area = buildUserProfile({
    questionnaire,
    profile: localProfile,
    location,
    answers: baseAnswers({ search_scope: "area", area_id: "west_bund" }),
  });
  const all = buildUserProfile({
    questionnaire,
    profile: localProfile,
    location,
    answers: baseAnswers({ search_scope: "all_xuhui" }),
  });

  assert.equal(area.search_radius_m, null);
  assert.deepEqual(area.area_ids, ["west_bund"]);
  assert.deepEqual(all.area_ids, []);
  assert.deepEqual(all.origin, { lng_gcj02: 121.44, lat_gcj02: 31.18 });
  assert.throws(
    () => buildUserProfile({
      questionnaire,
      profile: localProfile,
      location,
      answers: baseAnswers({ target_time: "custom", custom_time: "" }),
    }),
    /自定义运动时间/,
  );
});

test("附近推荐缺少主动选择的位置时阻止请求", () => {
  assert.throws(
    () => buildUserProfile({
      questionnaire,
      profile: localProfile,
      location: null,
      answers: baseAnswers({ search_scope: "nearby_3000" }),
    }),
    /请先选择位置/,
  );
});

test("指定片区和全徐汇也需主动选择位置以计算接驳", () => {
  for (const searchScope of ["area", "all_xuhui"]) {
    assert.throws(
      () => buildUserProfile({
        questionnaire,
        profile: localProfile,
        location: null,
        answers: baseAnswers({ search_scope: searchScope, area_id: "west_bund" }),
      }),
      /请先选择位置/,
    );
  }
});

test("推荐结果模型覆盖加载、暂停、无候选、降级和正常状态", () => {
  assert.equal(buildRecommendationViewModel({ view: "loading" }).kind, "loading");
  assert.equal(buildRecommendationViewModel({ status: "paused", risk: { reasons: ["暴雨预警"] } }).kind, "paused");
  assert.equal(buildRecommendationViewModel({ status: "no_candidates" }).kind, "no_candidates");
  assert.equal(buildRecommendationViewModel(resultFixture("degraded")).kind, "degraded");
  assert.equal(buildRecommendationViewModel(resultFixture("ok")).kind, "result");
  assert.equal(buildRecommendationViewModel({ view: "error", message: "服务不可用" }).kind, "error");
});

test("结果保持接口顺序，选中备选时首选位置不变", () => {
  const model = buildRecommendationViewModel(resultFixture("ok"), "route-2");

  assert.deepEqual(model.routes.map((route) => route.routeId), ["route-1", "route-2", "route-3"]);
  assert.equal(model.selectedRouteId, "route-2");
  assert.equal(model.routes[0].isPrimary, true);
  assert.equal(model.routes[1].isSelected, true);
  assert.equal(model.routes[0].confidenceText, undefined);
  assert.equal(model.routes[0].placeholderSizePx, undefined);
});

test("加载模型使用真实阶段名称且不伪造百分比", () => {
  const model = buildRecommendationViewModel({ view: "loading" });

  assert.deepEqual(model.steps.map((step) => step.label), ["汇总偏好", "匹配路线", "准备结果"]);
  assert.equal(JSON.stringify(model).includes("%"), false);
});

test("纯 DOM 控制器初始化问卷，并对外暴露结果切换方法", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const selected = [];
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onSelectRoute: (routeId) => selected.push(routeId),
    });

    assert.equal(container.children[0].className, "recommendation-panel");
    assert.match(container.textContent, /帮我推荐/);
    assert.equal(findByAttribute(container, "aria-label", "问问千问")?.tagName, "BUTTON");
    assert.equal(container.textContent.includes("档案设置"), false);
    assert.equal(container.textContent.includes("出发位置"), false);
    controller.showResult(resultFixture("ok"));
    assert.match(container.textContent, /首选路线/);
    assert.match(container.textContent, /滨江慢行/);
    assert.deepEqual(selected, []);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("Komoot 式路线卡只显示图片框、名称、时间、距离、PM2.5 与单选控件", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const result = resultFixture("ok");
    result.final_routes[1].route.environment_summary = {
      pm2_5: {
        value: 12.4,
        unit: "μg/m³",
        business_time: "2026-08-30T06:00:00+08:00",
        spatial_scale: "1km_grid_estimate",
        estimated: true,
      },
      noise: {
        value: 47.139,
        unit: "0-100 risk index",
        spatial_scale: "about_100m_road_segment_proxy",
        estimated: true,
      },
    };
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });

    controller.showResult(result);
    const second = findByAttribute(container, "aria-label", "查看路线 公园小环线");
    assert.ok(findByClass(second, "recommendation-route__media"));
    assert.ok(findByClass(second, "recommendation-route__selector"));
    assert.equal(findByClass(second, "recommendation-route__selector").attributes.role, "radio");
    assert.match(second.textContent, /14 分钟/);
    assert.match(second.textContent, /0.9 km/);
    assert.match(second.textContent, /PM2.5 12.4/);
    assert.equal(second.textContent.includes("距离更近"), false);
    assert.equal(second.textContent.includes("路线优势"), false);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问图标进入独立聊天，叉号返回并保留已填偏好", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });
    const note = findByClass(container, "recommendation-note__control");
    note.listeners.input({ target: { value: "想走安静一点的路线" } });

    findByAttribute(container, "aria-label", "问问千问").listeners.click();
    assert.match(container.textContent, /问问千问/);
    assert.match(container.textContent, /从交大徐汇校区出发/);

    findByAttribute(container, "aria-label", "关闭千问聊天").listeners.click();
    assert.match(container.textContent, /帮我推荐/);
    assert.equal(controller.getAnswers().free_text, "想走安静一点的路线");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("路线悬停只预览，点击后由统一右侧详情列接管", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const previewed = [];
    const selected = [];
    let returned = 0;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onPreviewRoute: (routeId) => previewed.push(routeId),
      onSelectRoute: (routeId) => selected.push(routeId),
      onReturnRouteOverview: () => { returned += 1; },
    });
    controller.showResult(resultFixture("ok"));

    const second = findByAttribute(container, "aria-label", "查看路线 公园小环线");
    second.listeners.mouseenter();
    second.listeners.mouseleave();
    assert.deepEqual(previewed, ["route-2", null]);
    second.listeners.click();
    assert.equal(controller.getCurrentRouteId(), "route-2");
    assert.deepEqual(selected, ["route-2"]);
    assert.equal(findByAttribute(container, "aria-label", "公园小环线路线详情"), null);

    let prevented = false;
    container.listeners.keydown({ key: "Escape", preventDefault: () => { prevented = true; } });
    assert.equal(controller.getCurrentRouteId(), null);
    assert.equal(returned, 1);
    assert.equal(prevented, true);

  } finally {
    globalThis.document = previousDocument;
  }
});

test("重新推荐清空旧结果并通知地图恢复初始路线选项卡", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let restartCount = 0;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onRestartRecommendation: () => { restartCount += 1; },
    });
    controller.showResult(resultFixture("ok"));

    findByText(container, "重新推荐").listeners.click();

    assert.equal(restartCount, 1);
    assert.deepEqual(controller.getResultRoutes(), []);
    assert.equal(controller.getCurrentRouteId(), null);
    assert.match(container.textContent, /为我推荐路线/);
    assert.equal(container.textContent.includes("滨江慢行"), false);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("推荐页失活时保存迟到结果但不切换地图", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const selected = [];
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      shouldSelectRoute: () => false,
      onSelectRoute: (routeId) => selected.push(routeId),
    });

    controller.showResult(resultFixture("ok"));

    assert.equal(controller.getCurrentRouteId(), null);
    assert.deepEqual(selected, []);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("问卷首次加载失败后可重新拉取并恢复表单", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let reloadCount = 0;
    const controller = createRecommendationUI({
      container,
      questionnaire: null,
      profile: localProfile,
      location,
      onReloadQuestionnaire: async () => {
        reloadCount += 1;
        return questionnaire;
      },
    });

    controller.showError(new Error("问卷服务不可用"));
    const retry = findByText(container, "重新加载问卷");
    assert.ok(retry);
    await retry.listeners.click();

    assert.equal(reloadCount, 1);
    assert.match(container.textContent, /为我推荐路线/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("档案弹层支持首次跳过、重新打开和规范化保存", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const host = globalThis.document.createElement("div");
    const saved = [];
    const dialog = createProfileDialog({
      host,
      profile: {
        version: 1,
        age_group: "undisclosed",
        gender: "undisclosed",
        experience: "regular",
        sensitivities: [],
      },
      onSave: (value) => saved.push(value),
    });

    dialog.open();
    assert.equal(dialog.isOpen(), true);
    assert.match(host.textContent, /年龄/);
    assert.match(host.textContent, /性别/);
    assert.match(host.textContent, /仅保存在本机，暂不参与推荐/);
    findByText(host, "暂时跳过").listeners.click();
    assert.equal(dialog.isOpen(), false);
    assert.deepEqual(saved[0], {
      version: 1,
      age_group: "undisclosed",
      gender: "undisclosed",
      experience: "regular",
      sensitivities: [],
    });

    dialog.setProfile({ ...localProfile, sensitivities: ["air", "air"] });
    dialog.open();
    findByText(host, "保存档案").listeners.click();
    assert.equal(dialog.isOpen(), false);
    assert.deepEqual(saved[1].sensitivities, ["air"]);
    assert.equal(saved[1].gender, "female");
  } finally {
    globalThis.document = previousDocument;
  }
});

function baseAnswers(overrides = {}) {
  return {
    route_mode: "walk",
    distance_range: "walk_short",
    target_time: "now",
    goal: "balanced",
    search_scope: "nearby_3000",
    route_shape: "any",
    interests: [],
    free_text: "",
    ...overrides,
  };
}

function resultFixture(status) {
  return {
    status,
    decision_summary: "优先选择环境与距离匹配的路线",
    risk: { status: "ok", reasons: [] },
    final_routes: [
      finalRoute("route-1", "滨江慢行", 1200, 18, 0.9, "滨江环境与步行距离匹配"),
      finalRoute("route-2", "公园小环线", 900, 14, 0.8, "距离更近"),
      finalRoute("route-3", "梧桐街区", 1600, 24, 0.7, "更安静"),
      finalRoute("route-4", "第四条", 2000, 30, 0.6, "额外候选"),
    ],
  };
}

function finalRoute(routeId, routeName, distanceM, durationMin, confidence, reason) {
  return {
    final_rank: Number(routeId.at(-1)),
    personalized_fit: reason,
    advantages: ["距离符合目标", "PM2.5 在候选中较低"],
    suggestions: ["雨天留意湿滑路面"],
    cautions: [],
    route: {
      data_confidence: confidence,
      matched_preferences: [],
      risk_notes: [],
      route: {
        route_id: routeId,
        route_name: routeName,
        route_mode: "walk",
        route_shape: "strict_loop",
        distance_m: distanceM,
        duration_min: durationMin,
        confidence: "high",
      },
    },
  };
}

function createDocumentStub() {
  class NodeStub {
    constructor(tagName = "") {
      this.tagName = tagName.toUpperCase();
      this.children = [];
      this.attributes = {};
      this.dataset = {};
      this.className = "";
      this.hidden = false;
      this._text = "";
      this.listeners = {};
    }

    append(...children) {
      this.children.push(...children.filter(Boolean));
    }

    appendChild(child) {
      this.children.push(child);
      return child;
    }

    replaceChildren(...children) {
      this.children = children;
      this._text = "";
    }

    setAttribute(name, value) {
      this.attributes[name] = String(value);
    }

    addEventListener(name, callback) {
      this.listeners[name] = callback;
    }

    showModal() {
      this.open = true;
    }

    close() {
      this.open = false;
    }

    get textContent() {
      return this._text + this.children.map((child) => child.textContent || "").join("");
    }

    set textContent(value) {
      this._text = String(value);
      this.children = [];
    }
  }

  return {
    createElement(tagName) {
      return new NodeStub(tagName);
    },
  };
}

function findByText(node, text) {
  if (node.textContent === text && node.tagName === "BUTTON") {
    return node;
  }
  for (const child of node.children || []) {
    const found = findByText(child, text);
    if (found) {
      return found;
    }
  }
  return null;
}

function findByAttribute(node, name, value) {
  if (node.attributes?.[name] === value) return node;
  for (const child of node.children || []) {
    const found = findByAttribute(child, name, value);
    if (found) return found;
  }
  return null;
}

function findByClass(node, className) {
  if (String(node.className || "").split(/\s+/).includes(className)) return node;
  for (const child of node.children || []) {
    const found = findByClass(child, className);
    if (found) return found;
  }
  return null;
}
