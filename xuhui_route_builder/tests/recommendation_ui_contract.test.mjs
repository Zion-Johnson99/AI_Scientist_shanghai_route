import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DEFAULT_RECOMMENDATION_LOCATION,
  buildInitialRecommendationResult,
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

test("首屏默认从交大徐汇校区筛选步行短线并按接驳距离稳定排序", () => {
  const routes = [
    localRoute("route-far", 121.45, 31.2015, 1000),
    localRoute("route-near-a", 121.434, 31.2015, 900),
    localRoute("route-near-b", 121.434, 31.2015, 1100),
    localRoute("route-too-long", 121.4331, 31.2015, 2000),
    { ...localRoute("route-run", 121.4331, 31.2015, 1000), route_mode: "run" },
  ];
  const result = buildInitialRecommendationResult({
    catalog: routes,
    questionnaire,
    answers: baseAnswers({ search_scope: "nearby_5000" }),
    location: DEFAULT_RECOMMENDATION_LOCATION,
  });

  assert.deepEqual(DEFAULT_RECOMMENDATION_LOCATION, {
    label: "上海交通大学徐汇校区",
    lng_gcj02: 121.433,
    lat_gcj02: 31.2015,
  });
  assert.deepEqual(
    result.final_routes.map((route) => route.route.route.route_id),
    ["route-near-a", "route-near-b", "route-far"],
  );
  assert.ok(result.final_routes[0].route.start_access_distance_m < result.final_routes[2].route.start_access_distance_m);
});

test("首屏本地路线卡使用与详情同源的路线环境数据", () => {
  const result = buildInitialRecommendationResult({
    catalog: [localRoute("route-near", 121.434, 31.2015, 900)],
    questionnaire,
    answers: baseAnswers({ search_scope: "nearby_5000" }),
    location: DEFAULT_RECOMMENDATION_LOCATION,
    getRouteEnvironment: (routeId) => ({
      routeId,
      pm25: { value: 11.2, status: "ok", unit: "µg/m³" },
      pollen: { value: 22.1, status: "ok" },
      noise: { value: 35.4, status: "partial" },
    }),
  });

  assert.equal(result.final_routes[0].route.environment_summary.pm2_5.value, 11.2);
  assert.equal(buildRecommendationViewModel(result).routes[0].pm25Text, "PM2.5 11.2 µg/m³");
});

test("Komoot 式顶部筛选轨承载默认值、弹层与横向箭头", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const filterHost = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, filterHost, questionnaire, profile: localProfile, location });

    const filters = findByClass(filterHost, "recommendation-filters");
    assert.ok(filters);
    assert.match(filters.textContent, /现在/);
    assert.match(filters.textContent, /1 km/);
    assert.match(filters.textContent, /综合均衡/);
    assert.match(filters.textContent, /5 km 附近/);
    assert.match(filters.textContent, /不限/);

    const goalChip = findByAttribute(filters, "aria-label", "设置运动目标");
    goalChip.listeners.click();
    assert.equal(goalChip.attributes["aria-expanded"], "true");
    assert.ok(findByClass(filterHost, "recommendation-filter__popover"));

    const viewport = findByClass(filterHost, "recommendation-filters__viewport");
    const track = findByClass(filterHost, "recommendation-filters__track");
    findByAttribute(filterHost, "aria-label", "向右浏览筛选项").listeners.click();
    assert.equal(viewport.scrollCalls.length, 0);
    assert.ok(track.scrollCalls[0].left > 0);
    controller.setDetailOpen(true);
    assert.ok(String(findByClass(filterHost, "recommendation-filters").className).includes("is-detail-open"));
  } finally {
    globalThis.document = previousDocument;
  }
});

test("移动端重建筛选轨保留滚动位置且弹层不写入桌面坐标", () => {
  const previousDocument = globalThis.document;
  const previousMatchMedia = globalThis.matchMedia;
  globalThis.document = createDocumentStub();
  globalThis.matchMedia = () => ({ matches: true });
  try {
    const container = globalThis.document.createElement("div");
    const filterHost = globalThis.document.createElement("div");
    createRecommendationUI({ container, filterHost, questionnaire, profile: localProfile, location });
    const firstTrack = findByClass(filterHost, "recommendation-filters__track");
    firstTrack.scrollLeft = 420;

    findByAttribute(filterHost, "aria-label", "设置景观与环境").listeners.click();

    const nextTrack = findByClass(filterHost, "recommendation-filters__track");
    const popover = findByClass(filterHost, "recommendation-filter__popover");
    assert.equal(nextTrack.scrollLeft, 420);
    assert.equal(popover.style.left || "", "");
    assert.equal(popover.style.top || "", "");
  } finally {
    globalThis.document = previousDocument;
    globalThis.matchMedia = previousMatchMedia;
  }
});

test("筛选弹层支持 Escape、外部点击、焦点进入与返回 chip", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const filterHost = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, filterHost, questionnaire, profile: localProfile, location });
    findByAttribute(filterHost, "aria-label", "设置运动目标").listeners.click();
    const popover = findByClass(filterHost, "recommendation-filter__popover");
    assert.equal(globalThis.document.activeElement, popover);

    findByClass(filterHost, "recommendation-filters").listeners.keydown({ key: "Escape", preventDefault() {} });
    assert.equal(findByClass(filterHost, "recommendation-filter__popover"), null);
    assert.equal(globalThis.document.activeElement.attributes["aria-label"], "设置运动目标");

    findByAttribute(filterHost, "aria-label", "设置运动目标").listeners.click();
    globalThis.document.listeners.pointerdown({ target: globalThis.document.createElement("div") });
    assert.equal(findByClass(filterHost, "recommendation-filter__popover"), null);

    findByAttribute(filterHost, "aria-label", "设置运动目标").listeners.click();
    controller.setDetailOpen(true);
    assert.equal(findByClass(filterHost, "recommendation-filter__popover"), null);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("左栏只保留三张卡、补充需求和底部推荐按钮", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });
    controller.showResult(resultFixture("ok"));

    assert.ok(findByClass(container, "recommendation-workspace"));
    assert.equal(findAllByClass(container, "route-card").length, 3);
    assert.ok(findByClass(container, "recommendation-results-list"));
    assert.ok(findByClass(container, "recommendation-workspace__footer"));
    assert.ok(findByClass(container, "recommendation-note__control"));
    assert.ok(findByText(container, "为我推荐路线"));
    assert.equal(findByClass(container, "recommendation-question"), null);
    assert.equal(findByClass(container, "recommendation-form__summary"), null);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("三种运动方式默认采用各自第二档距离，其余筛选保持不变", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const configured = {
      ...questionnaire,
      route_modes: [
        { value: "run", label: "跑步" },
        { value: "walk", label: "步行" },
        { value: "bike", label: "骑行" },
      ],
      distance_ranges: {
        ...questionnaire.distance_ranges,
        walk: [
          { value: "walk_short", label: "0.7–1.5 公里", distance_min_m: 700, target_distance_m: 1000, distance_max_m: 1500 },
          { value: "walk_standard", label: "1.5–3 公里", distance_min_m: 1500, target_distance_m: 2500, distance_max_m: 3000 },
          { value: "walk_long", label: "3–5 公里", distance_min_m: 3000, target_distance_m: 4000, distance_max_m: 5000 },
        ],
        run: [
          { value: "run_short", label: "1–3 公里", distance_min_m: 1000, target_distance_m: 2000, distance_max_m: 3000 },
          { value: "run_standard", label: "3–6 公里", distance_min_m: 3000, target_distance_m: 5000, distance_max_m: 6000 },
          { value: "run_long", label: "6–10 公里", distance_min_m: 6000, target_distance_m: 8000, distance_max_m: 10000 },
        ],
        bike: [
          { value: "bike_short", label: "5–10 公里", distance_min_m: 5000, target_distance_m: 8000, distance_max_m: 10000 },
          { value: "bike_standard", label: "10–20 公里", distance_min_m: 10000, target_distance_m: 15000, distance_max_m: 20000 },
          { value: "bike_long", label: "20–30 公里", distance_min_m: 20000, target_distance_m: 25000, distance_max_m: 30000 },
        ],
      },
    };
    const controller = createRecommendationUI({ container, questionnaire: configured, profile: localProfile, location });

    assert.equal(controller.getAnswers().route_mode, "walk");
    assert.equal(controller.getAnswers().distance_range, "walk_standard");
    assert.equal(controller.getAnswers().search_scope, "nearby_5000");

    controller.setRouteMode("run");
    assert.equal(controller.getAnswers().distance_range, "run_standard");
    assert.equal(controller.getAnswers().search_scope, "nearby_5000");

    controller.setRouteMode("bike");
    assert.equal(controller.getAnswers().distance_range, "bike_standard");
    assert.equal(controller.getAnswers().goal, "balanced");

    controller.setRouteMode("walk");
    assert.equal(controller.getAnswers().distance_range, "walk_standard");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("提交时保留旧卡并在原按钮显示正在推荐，且阻止重复请求", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let resolveRecommendation;
    let requestCount = 0;
    const recommendation = new Promise((resolve) => { resolveRecommendation = resolve; });
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onRecommend: async () => {
        requestCount += 1;
        return recommendation;
      },
    });
    controller.showResult(resultFixture("ok"));
    const form = findByClass(container, "recommendation-form");
    const firstRequest = form.listeners.submit({ preventDefault() {} });
    const secondRequest = form.listeners.submit({ preventDefault() {} });

    assert.equal(requestCount, 1);
    assert.match(container.textContent, /滨江慢行/);
    const loadingButton = findByText(container, "正在推荐中");
    assert.equal(loadingButton.attributes["aria-busy"], "true");
    assert.equal(loadingButton.disabled, true);

    resolveRecommendation(resultFixture("ok"));
    await Promise.all([firstRequest, secondRequest]);
    assert.ok(findByText(container, "为我推荐路线"));
  } finally {
    globalThis.document = previousDocument;
  }
});

test("推荐失败时有旧结果保留三卡和行内提示，无旧结果才显示整页错误", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const withRoutes = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container: withRoutes,
      questionnaire,
      profile: localProfile,
      location,
      onRecommend: async () => { throw new Error("服务断开"); },
    });
    controller.showResult(resultFixture("ok"));
    await findByClass(withRoutes, "recommendation-form").listeners.submit({ preventDefault() {} });
    assert.equal(findAllByClass(withRoutes, "route-card").length, 3);
    assert.match(findByClass(withRoutes, "recommendation-workspace__error").textContent, /服务断开/);
    assert.equal(findByClass(withRoutes, "recommendation-state--error"), null);

    const empty = globalThis.document.createElement("div");
    const emptyController = createRecommendationUI({ container: empty, questionnaire, profile: localProfile, location });
    emptyController.showError(new Error("初始加载失败"));
    assert.ok(findByClass(empty, "recommendation-state--error"));
    assert.equal(findAllByClass(empty, "route-card").length, 0);
  } finally {
    globalThis.document = previousDocument;
  }
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
    assert.ok(findByClass(container, "recommendation-form"));
    assert.equal(findByAttribute(container, "aria-label", "问问千问"), null);
    assert.equal(container.textContent.includes("档案设置"), false);
    assert.equal(container.textContent.includes("出发位置"), false);
    controller.showResult(resultFixture("ok"));
    assert.match(container.textContent, /首选/);
    assert.match(container.textContent, /备选 1/);
    assert.match(container.textContent, /备选 2/);
    assert.equal(container.textContent.includes("首选路线"), false);
    assert.match(container.textContent, /滨江慢行/);
    assert.deepEqual(selected, []);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("Komoot 式路线卡以整卡交互，不再创建单独 radio", () => {
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
    assert.ok(findByClass(second, "route-card--placeholder"));
    assert.ok(findByClass(second, "route-card__media"));
    assert.ok(findByClass(second, "route-card__placeholder"));
    assert.equal(findByAttribute(second, "role", "radio"), null);
    assert.match(second.textContent, /14 分钟/);
    assert.match(second.textContent, /0.9 km/);
    assert.equal(second.textContent.includes("距离更近"), false);
    assert.equal(second.textContent.includes("路线优势"), false);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("推荐左栏路线卡的 PM2.5 始终带 µg/m³", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const result = resultFixture("ok");
    result.final_routes[1].route.environment_summary = {
      pm2_5: { value: 12.4, status: "ok", unit: "μg/m³" },
    };
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });

    controller.showResult(result);
    const second = findByAttribute(container, "aria-label", "查看路线 公园小环线");
    assert.match(second.textContent, /PM2.5 12.4 µg\/m³/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("关闭千问聊天恢复进入前的推荐结果、选中路线与滚动位置", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });
    controller.showResult(resultFixture("ok"));
    controller.selectRoute("route-2");
    container.scrollTop = 184;

    controller.openChat();
    assert.ok(findByClass(container, "recommendation-chat"));
    assert.match(container.textContent, /从交大徐汇校区出发/);
    container.scrollTop = 0;

    findByAttribute(container, "aria-label", "关闭千问聊天").listeners.click();
    assert.match(container.textContent, /为你推荐/);
    assert.match(container.textContent, /公园小环线/);
    assert.equal(controller.getCurrentRouteId(), "route-2");
    assert.equal(container.scrollTop, 184);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问空态使用顶部说明与底部交互区，并保留可提交输入框", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });

    controller.openChat();

    const chat = findByClass(container, "recommendation-chat");
    const notice = findByClass(chat, "recommendation-chat__notice");
    const starter = findByClass(chat, "recommendation-chat__starter");
    const composer = findByClass(chat, "recommendation-chat__composer");
    assert.ok(notice, "缺少顶部轻量说明");
    assert.ok(starter, "缺少靠底的问题与建议区");
    assert.match(starter.textContent, /你今天想走一条怎样的路线/);
    assert.equal(composer.tagName, "FORM");
    assert.ok(findByAttribute(composer, "aria-label", "描述路线需求"));
    assert.ok(findByAttribute(composer, "aria-label", "发送路线需求"));
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问样式契约固定全高留白、底部起始区与纯白简约表面", () => {
  const css = readFileSync(new URL("../web/styles/recommendation.css", import.meta.url), "utf8");

  assert.match(css, /\.recommendation-view\.active:has\(\.recommendation-chat\)\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/s);
  assert.match(css, /\.recommendation-chat\s*\{[^}]*height:\s*100%/s);
  assert.match(css, /\.recommendation-chat__starter\s*\{[^}]*margin-top:\s*auto/s);
  assert.match(css, /\.recommendation-chat__composer\s*\{[^}]*background:\s*#fff(?:fff)?/s);
  assert.match(css, /\.recommendation-chat__example\s*\{[^}]*border:\s*0/s);
});

test("公共标题栏让千问入口在推荐、浏览、结果和折叠态持续可见", () => {
  const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
  const headerStart = html.indexOf('id="workbenchHeader"');
  const qwenStart = html.indexOf('id="workbenchQwenButton"');
  const bodyStart = html.indexOf('id="workbenchBody"');

  assert.ok(headerStart >= 0, "缺少公共工作台标题栏");
  assert.ok(qwenStart > headerStart, "千问入口应位于公共标题栏中");
  assert.ok(bodyStart > qwenStart, "千问入口应位于可折叠正文之外");
  assert.match(html, /id="workbenchQwenButton"[^>]*data-workbench-qwen[^>]*aria-expanded="false"/);
  assert.match(html, /id="workbenchCollapseButton"[^>]*data-workbench-collapse[^>]*aria-controls="workbenchBody"/);
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

test("控制器仍支持清空旧结果并通知地图恢复初始状态", () => {
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

    controller.restartRecommendation();

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

function localRoute(routeId, lng, lat, distanceM) {
  return {
    route_id: routeId,
    route_name: routeId,
    route_mode: "walk",
    route_shape: "one_way",
    distance_m: distanceM,
    duration_min: Math.round(distanceM / 75),
    start_location: { name: `${routeId} 起点`, lng_gcj02: lng, lat_gcj02: lat },
    end_location: { name: `${routeId} 终点`, lng_gcj02: lng + 0.001, lat_gcj02: lat },
    validation_status: "accepted",
    popular_area_ids: [],
  };
}

function createDocumentStub() {
  let documentStub;
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
      this.disabled = false;
      this.clientWidth = 600;
      this.scrollCalls = [];
      this.scrollLeft = 0;
      this.style = {};
      this.classList = {
        add: (...names) => this.#setClasses(names, true),
        remove: (...names) => this.#setClasses(names, false),
        toggle: (name, force) => this.#setClasses([name], force),
        contains: (name) => String(this.className).split(/\s+/).includes(name),
      };
    }

    append(...children) {
      children.filter(Boolean).forEach((child) => {
        child.parentElement = this;
        this.children.push(child);
      });
    }

    appendChild(child) {
      child.parentElement = this;
      this.children.push(child);
      return child;
    }

    replaceChildren(...children) {
      this.children = [];
      this.append(...children);
      this._text = "";
    }

    setAttribute(name, value) {
      this.attributes[name] = String(value);
    }

    addEventListener(name, callback) {
      this.listeners[name] = callback;
    }

    scrollBy(options) {
      this.scrollCalls.push(options);
      this.scrollLeft += Number(options?.left || 0);
      this.listeners.scroll?.({ target: this });
    }

    focus() {
      documentStub.activeElement = this;
    }

    contains(target) {
      return this === target || this.children.some((child) => child.contains?.(target));
    }

    getBoundingClientRect() {
      return { left: 20, right: 320, top: 20, bottom: 60, width: 300, height: 40 };
    }

    #setClasses(names, enabled) {
      const classes = new Set(String(this.className || "").split(/\s+/).filter(Boolean));
      names.forEach((name) => enabled ? classes.add(name) : classes.delete(name));
      this.className = [...classes].join(" ");
      return enabled;
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

  documentStub = {
    activeElement: null,
    listeners: {},
    createElement(tagName) {
      return new NodeStub(tagName);
    },
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
    removeEventListener(name, callback) {
      if (this.listeners[name] === callback) delete this.listeners[name];
    },
  };
  return documentStub;
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

function findAllByClass(node, className, matches = []) {
  if (String(node.className || "").split(/\s+/).includes(className)) matches.push(node);
  for (const child of node.children || []) findAllByClass(child, className, matches);
  return matches;
}
