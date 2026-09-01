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
import { routeMediaFor } from "../web/src/route-media.js";

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

test("推荐结果展示未满足的显式偏好", () => {
  const result = resultFixture("ok");
  result.profile_conflicts = ["当前条件下没有已核实的厕所路线，已保留其他条件较优的结果。"];

  const model = buildRecommendationViewModel(result);

  assert.match(model.notice, /没有已核实的厕所/);
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
    lng_gcj02: 121.433095,
    lat_gcj02: 31.199005,
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

test("Komoot 式顶部筛选轨只显示七项图标与分类名称", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const filterHost = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, filterHost, questionnaire, profile: localProfile, location });

    const filters = findByClass(filterHost, "recommendation-filters");
    assert.ok(filters);
    assert.doesNotMatch(filters.textContent, /现在|1 km|综合均衡|5 km 附近|不限/);
    assert.equal(findAllByClass(filters, "recommendation-filter__chip").length, 7);
    assert.equal(findAllByClass(filters, "recommendation-filter__icon").length, 7);
    for (const icon of ["time", "distance", "goal", "scope", "route", "rest", "scenery"]) {
      assert.ok(findByAttribute(filters, "data-filter-icon", icon));
    }
    assert.equal(findByClass(filters, "recommendation-filters__arrow"), null);

    const goalChip = findByAttribute(filters, "aria-label", "设置运动目标");
    goalChip.listeners.click();
    assert.equal(goalChip.attributes["aria-expanded"], "true");
    const popover = findByClass(filterHost, "recommendation-filter__popover");
    assert.ok(popover);
    assert.equal(findByClass(popover, "recommendation-filter__title").textContent, "运动目标");
    assert.ok(findByAttribute(popover, "aria-label", "关闭运动目标筛选"));
    assert.ok(findByText(popover, "恢复默认"));
    assert.ok(findByText(popover, "完成"));

    findByText(popover, "完成").listeners.click();
    const timeChip = findByAttribute(filterHost, "aria-label", "设置时间");
    timeChip.listeners.click();
    findByText(filterHost, "2 小时后").listeners.click();
    assert.equal(controller.getAnswers().target_time, "plus_2h");
    assert.ok(findByClass(filterHost, "recommendation-filter__popover"));
    findByText(filterHost, "恢复默认").listeners.click();
    assert.equal(controller.getAnswers().target_time, "now");
    findByText(filterHost, "完成").listeners.click();
    assert.equal(findByClass(filterHost, "recommendation-filter__popover"), null);

    controller.setDetailOpen(true);
    assert.ok(String(findByClass(filterHost, "recommendation-filters").className).includes("is-detail-open"));
    controller.setDetailOpen(false);
    assert.doesNotMatch(String(findByClass(filterHost, "recommendation-filters").className), /is-detail-open/);

    const source = readFileSync(new URL("../web/src/recommendation-ui.js", import.meta.url), "utf8");
    assert.doesNotMatch(source, /function\s+filterArrow\s*\(/);
    assert.doesNotMatch(source, /function\s+scrollFilters\s*\(/);
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
    assert.match(second.textContent, /14 min/);
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
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      getRouteEnvironment: () => ({ pm25: { value: 99, status: "ok", unit: "μg/m³" } }),
    });

    controller.showResult(result);
    const second = findByAttribute(container, "aria-label", "查看路线 公园小环线");
    assert.match(second.textContent, /PM2.5 12.4 µg\/m³/);
    assert.equal(second.textContent.includes("PM2.5 99"), false);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("推荐接口的 PM2.5 过期时，路线卡回退到页面当前环境数据", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const result = resultFixture("ok");
    result.final_routes[1].route.environment_summary = {
      pm2_5: { value: 22, status: "stale", unit: "μg/m³" },
    };
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      getRouteEnvironment: (routeId) => (
        routeId === "route-2"
          ? { pm25: { value: 12.4, status: "ok", unit: "μg/m³" } }
          : null
      ),
    });

    controller.showResult(result);
    const second = findByAttribute(container, "aria-label", "查看路线 公园小环线");
    assert.match(second.textContent, /PM2.5 12.4 µg\/m³/);
    assert.equal(second.textContent.includes("数据更新中"), false);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("环境轮询取得新数据后刷新已有推荐卡 PM2.5", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const result = resultFixture("ok");
    result.final_routes[1].route.environment_summary = {};
    let pm25 = 12.4;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      getRouteEnvironment: (routeId) => (
        routeId === "route-2"
          ? { pm25: { value: pm25, status: "ok", unit: "μg/m³" } }
          : null
      ),
    });

    controller.showResult(result);
    assert.match(
      findByAttribute(container, "aria-label", "查看路线 公园小环线").textContent,
      /PM2.5 12.4 µg\/m³/,
    );

    pm25 = 10.8;
    controller.refreshEnvironment();

    assert.match(
      findByAttribute(container, "aria-label", "查看路线 公园小环线").textContent,
      /PM2.5 10.8 µg\/m³/,
    );
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

    controller.closeChat();
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
    assert.equal(findByAttribute(composer, "aria-label", "发送路线需求"), null);
    assert.doesNotMatch(String(composer.className), /has-draft/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问输入非空后才显示圆形导航发送按钮", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });
    controller.openChat();

    const input = findByAttribute(container, "aria-label", "描述路线需求");
    input.listeners.input({ target: { value: "想跑 5 公里" } });

    const composer = findByClass(container, "recommendation-chat__composer");
    const send = findByAttribute(composer, "aria-label", "发送路线需求");
    assert.match(String(composer.className), /has-draft/);
    assert.ok(send, "非空输入缺少独立导航发送按钮");
    assert.equal(send.textContent.trim(), "", "导航按钮应使用图标表达发送");

    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "   " } });
    const emptyComposer = findByClass(container, "recommendation-chat__composer");
    assert.doesNotMatch(String(emptyComposer.className), /has-draft/);
    assert.equal(findByAttribute(emptyComposer, "aria-label", "发送路线需求"), null);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问输入时永久挂载文本框并复用同一个发送按钮", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({ container, questionnaire, profile: localProfile, location });
    controller.openChat();

    const input = findByAttribute(container, "aria-label", "描述路线需求");
    input.focus();
    input.value = "滨江";
    input.listeners.input({ target: input });
    const firstSend = findByAttribute(container, "aria-label", "发送路线需求");

    assert.equal(findByAttribute(container, "aria-label", "描述路线需求"), input);
    assert.equal(globalThis.document.activeElement, input, "输入时文本框被重新挂载并丢失焦点");
    assert.ok(firstSend);

    input.value = "滨江慢跑";
    input.listeners.input({ target: input });
    assert.equal(findByAttribute(container, "aria-label", "描述路线需求"), input);
    assert.equal(findByAttribute(container, "aria-label", "发送路线需求"), firstSend, "草稿变化时重复创建发送按钮");

    input.value = "   ";
    input.listeners.input({ target: input });
    assert.equal(findByAttribute(container, "aria-label", "描述路线需求"), input);
    assert.equal(findByAttribute(container, "aria-label", "发送路线需求"), null);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("新建聊天清空当前会话并留在千问面板", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({
        reply: "你更偏好公园还是滨江？",
        ready: false,
        preference_patch: { interests: ["quiet"] },
      }),
    });
    controller.openChat();
    const input = findByAttribute(container, "aria-label", "描述路线需求");
    input.listeners.input({ target: { value: "想走安静路线" } });
    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });
    assert.match(container.textContent, /想走安静路线/);
    assert.match(container.textContent, /你更偏好公园还是滨江/);

    controller.newChat();

    assert.equal(controller.isChatOpen(), true);
    assert.match(container.textContent, /你今天想走一条怎样的路线/);
    assert.doesNotMatch(container.textContent, /想走安静路线|你更偏好公园还是滨江/);
    const resetInput = findByAttribute(container, "aria-label", "描述路线需求");
    assert.equal(resetInput.value, "");
    assert.equal(findByAttribute(container, "aria-label", "发送路线需求"), null);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("推荐提问点击后直接发送给千问", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const requests = [];
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async (payload) => {
        requests.push(payload);
        return { reply: "还想补充什么偏好吗？", ready: false, preference_patch: {} };
      },
    });
    controller.openChat();

    const example = findAllByClass(container, "recommendation-chat__example")[1];
    const exampleText = example.textContent;
    await example.listeners.click();

    assert.equal(requests.length, 1);
    assert.equal(requests[0].message, exampleText);
    assert.match(container.textContent, /还想补充什么偏好吗/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("Enter 直接发送且 Shift+Enter 保留换行", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let requestCount = 0;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => {
        requestCount += 1;
        return { reply: "收到", ready: false, preference_patch: {} };
      },
    });
    controller.openChat();

    let input = findByAttribute(container, "aria-label", "描述路线需求");
    input.listeners.input({ target: { value: "安静的跑步路线" } });
    input = findByAttribute(container, "aria-label", "描述路线需求");
    assert.equal(typeof input.listeners.keydown, "function", "输入框缺少 Enter 键盘提交处理");
    let enterPrevented = false;
    await input.listeners.keydown({
      key: "Enter",
      shiftKey: false,
      preventDefault() { enterPrevented = true; },
    });
    assert.equal(enterPrevented, true);
    assert.equal(requestCount, 1);

    input = findByAttribute(container, "aria-label", "描述路线需求");
    input.listeners.input({ target: { value: "第一行" } });
    input = findByAttribute(container, "aria-label", "描述路线需求");
    let shiftEnterPrevented = false;
    await input.listeners.keydown({
      key: "Enter",
      shiftKey: true,
      preventDefault() { shiftEnterPrevented = true; },
    });
    assert.equal(shiftEnterPrevented, false);
    assert.equal(requestCount, 1);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("中文输入法组合态按 Enter 只确认候选且不提交", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let requestCount = 0;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => {
        requestCount += 1;
        return { reply: "收到", ready: false, preference_patch: {} };
      },
    });
    controller.openChat();

    const input = findByAttribute(container, "aria-label", "描述路线需求");
    assert.equal(typeof input.listeners.compositionstart, "function");
    assert.equal(typeof input.listeners.compositionend, "function");
    input.value = "徐汇滨江";
    input.listeners.input({ target: input });
    input.listeners.compositionstart();
    let composingPrevented = false;
    await input.listeners.keydown({
      key: "Enter",
      shiftKey: false,
      isComposing: false,
      preventDefault() { composingPrevented = true; },
    });
    assert.equal(composingPrevented, false);
    assert.equal(requestCount, 0);

    input.listeners.compositionend({ target: input });
    await input.listeners.keydown({
      key: "Enter",
      shiftKey: false,
      isComposing: false,
      preventDefault() {},
    });
    assert.equal(requestCount, 1);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问处理中展示 Komoot 式公开进度状态", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let resolveIntent;
    const intent = new Promise((resolve) => { resolveIntent = resolve; });
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: () => intent,
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "滨江跑步" } });

    const pending = findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });
    const progress = findByClass(container, "recommendation-chat__progress");
    assert.ok(progress, "chatBusy 时缺少公开进度状态");
    assert.equal(progress.attributes["aria-live"], "polite");
    assert.match(progress.textContent, /正在理解路线需求|正在匹配合适路线/);
    assert.equal(findAllByClass(progress, "recommendation-chat__progress-dot").length, 3);

    resolveIntent({ reply: "请再补充距离", ready: false, preference_patch: {} });
    await pending;
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问 ready 后自动推荐并在对话内最多展示三张专用无图卡", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let recommendationCount = 0;
    let recommendationProfile = null;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({
        reply: "正在为你匹配路线。",
        ready: true,
        preference_patch: { free_text: "安静滨江" },
      }),
      onRecommend: async (payload) => {
        recommendationCount += 1;
        recommendationProfile = payload;
        return resultFixture("ok");
      },
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "安静的滨江路线" } });

    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    const cards = findAllByClass(container, "recommendation-chat__route-card");
    assert.equal(recommendationCount, 1);
    assert.equal(controller.isChatOpen(), true);
    assert.equal(cards.length, 3);
    assert.equal(findAllByClass(container, "recommendation-chat__media").length, 3);
    assert.equal(container.textContent.includes("开始推荐"), false);
    assert.equal(findAllByClass(container, "route-card").length, 0, "聊天卡应与普通推荐卡区分");
    assert.equal(recommendationProfile.free_text, "安静滨江");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问未就绪时只追加追问且不请求推荐", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let recommendationCount = 0;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({
        reply: "你希望走多远？",
        ready: false,
        preference_patch: {},
      }),
      onRecommend: async () => {
        recommendationCount += 1;
        return resultFixture("ok");
      },
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "想散步" } });

    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    assert.equal(recommendationCount, 0);
    assert.match(findByClass(container, "recommendation-chat__message--assistant").textContent, /你希望走多远/);
    assert.equal(findAllByClass(container, "recommendation-chat__route-card").length, 0);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("聊天路线卡点击后保持聊天态并触发统一详情", async () => {
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
      onInterpretIntent: async () => ({ reply: "为你找到三条路线。", ready: true, preference_patch: {} }),
      onRecommend: async () => resultFixture("ok"),
      onSelectRoute: (routeId) => selected.push(routeId),
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "推荐路线" } });
    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    const cards = findAllByClass(container, "recommendation-chat__route-card");
    assert.equal(cards.length, 3, "聊天内应先渲染三张专用路线卡");
    const second = cards[1];
    second.listeners.click();

    assert.equal(controller.isChatOpen(), true);
    assert.equal(controller.getCurrentRouteId(), "route-2");
    assert.deepEqual(selected, ["route-2"]);
    assert.ok(findByClass(container, "recommendation-chat"));
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问最终推荐卡封面破图后回退路线图片占位", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const routeId = "XH_WALK_0001";
    const media = routeMediaFor(routeId);
    assert.ok(media.cover, `${routeId} 应作为千问推荐卡封面样例`);

    const result = resultFixture("ok");
    result.final_routes[0].route.route.route_id = routeId;
    result.final_routes[0].route.route.route_name = "西岸油罐艺术短线";
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({ reply: "为你找到三条路线。", ready: true, preference_patch: {} }),
      onRecommend: async () => result,
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "推荐路线" } });
    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    const card = findAllByClass(container, "recommendation-chat__route-card")[0];
    const image = findByTag(card, "IMG");
    assert.ok(image, "千问最终推荐卡应渲染路线封面");
    assert.equal(image.attributes.src, media.cover);
    assert.equal(typeof image.listeners.error, "function");
    image.listeners.error();
    assert.equal(findByTag(card, "IMG"), null);
    const fallback = findByClass(card, "recommendation-chat__media-label");
    assert.ok(fallback, "破图后应恢复路线图片占位");
    assert.equal(fallback.textContent, "路线照片");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问 route_mode 意图补丁自动切换运动方式及默认距离", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({
        reply: "已切换为跑步路线。",
        ready: false,
        preference_patch: { route_mode: "run" },
      }),
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "我想跑步" } });

    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    assert.equal(controller.getAnswers().route_mode, "run");
    assert.equal(controller.getAnswers().distance_range, "run_mid");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问明确距离随 route_mode 同步到顶部筛选与最终请求", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const intentQuestionnaire = {
      ...questionnaire,
      route_modes: [...questionnaire.route_modes, { value: "bike", label: "骑行" }],
      distance_ranges: {
        ...questionnaire.distance_ranges,
        bike: [
          { value: "bike_short", label: "5–10 公里", distance_min_m: 5000, target_distance_m: 8000, distance_max_m: 10000 },
          { value: "bike_ten", label: "8–12 公里", distance_min_m: 8000, target_distance_m: 10000, distance_max_m: 12000 },
        ],
      },
      interests: [...questionnaire.interests, { value: "waterfront", label: "滨江" }],
      route_shapes: [...questionnaire.route_shapes, { value: "loop", label: "环线" }],
    };
    const message = "周末骑行 10 公里左右，想看滨江风景，最后回到出发点";
    let recommendationProfile = null;
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container,
      questionnaire: intentQuestionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({
        reply: "条件已整理。",
        ready: true,
        preference_patch: {
          route_mode: "bike",
          distance_min_m: 8000,
          target_distance_m: 10000,
          distance_max_m: 12000,
          target_time: "2026-09-06T01:00:00.000Z",
          route_shape: "loop",
          interests: ["waterfront"],
        },
      }),
      onRecommend: async (payload) => {
        recommendationProfile = payload;
        return resultFixture("ok");
      },
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: message } });

    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    const answers = controller.getAnswers();
    assert.equal(answers.route_mode, "bike");
    assert.equal(answers.distance_range, "bike_ten");
    assert.equal(answers.target_time, "custom");
    assert.equal(answers.route_shape, "loop");
    assert.deepEqual(answers.interests, ["waterfront"]);
    assert.equal(recommendationProfile.distance_min_m, 8000);
    assert.equal(recommendationProfile.target_distance_m, 10000);
    assert.equal(recommendationProfile.distance_max_m, 12000);
    assert.equal(recommendationProfile.target_time, "2026-09-06T01:00:00.000Z");
    assert.equal(recommendationProfile.route_shape, "loop");
    assert.deepEqual(recommendationProfile.interests, ["waterfront"]);
    assert.equal(recommendationProfile.free_text, message, "千问未返回 free_text 时应保留原始聊天需求");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("后续片区意图取代先前半径且不形成 AND 过约束", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    let turn = 0;
    let recommendationProfile = null;
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => {
        turn += 1;
        return turn === 1
          ? { reply: "已设置附近范围。", ready: false, preference_patch: { search_radius_m: 5000 } }
          : { reply: "已改为徐汇滨江。", ready: true, preference_patch: { area_ids: ["west_bund"] } };
      },
      onRecommend: async (payload) => {
        recommendationProfile = payload;
        return resultFixture("ok");
      },
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "先看 5 公里附近" } });
    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "改成徐汇滨江" } });
    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    assert.equal(controller.getAnswers().search_scope, "area");
    assert.equal(controller.getAnswers().area_id, "west_bund");
    assert.equal(recommendationProfile.search_radius_m, null);
    assert.deepEqual(recommendationProfile.area_ids, ["west_bund"]);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("意图响应新字段不透传到下轮严格 schema 上下文", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const requests = [];
    const container = globalThis.document.createElement("div");
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async (request) => {
        requests.push(request);
        return { reply: "请继续补充。", ready: false, preference_patch: { future_signal: "new-contract-field" } };
      },
    });
    controller.openChat();
    for (const message of ["想散步", "现在出发"]) {
      findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: message } });
      await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });
    }

    assert.equal(requests.length, 2);
    assert.equal(requests[1].context.preferences.future_signal, undefined);
    assert.equal(requests[1].context.preferences.free_text, "想散步");
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问空值补丁不覆盖前端已解析的推荐时间", async () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const container = globalThis.document.createElement("div");
    let recommendationProfile = null;
    const controller = createRecommendationUI({
      container,
      questionnaire,
      profile: localProfile,
      location,
      onInterpretIntent: async () => ({
        reply: "条件完整，开始推荐。",
        ready: true,
        preference_patch: { target_time: null },
      }),
      onRecommend: async (payload) => {
        recommendationProfile = payload;
        return resultFixture("ok");
      },
    });
    controller.openChat();
    findByAttribute(container, "aria-label", "描述路线需求").listeners.input({ target: { value: "现在出发" } });

    await findByClass(container, "recommendation-chat__composer").listeners.submit({ preventDefault() {} });

    assert.match(String(recommendationProfile?.target_time || ""), /^\d{4}-\d{2}-\d{2}T/);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("千问样式契约固定全高留白、底部起始区与纯白简约表面", () => {
  const css = readFileSync(new URL("../web/styles/recommendation.css", import.meta.url), "utf8");

  assert.match(css, /\.recommendation-view\.active:has\(\.recommendation-chat\)\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/s);
  assert.match(css, /\.recommendation-chat\s*\{[^}]*height:\s*100%/s);
  assert.match(css, /\.recommendation-chat__starter\s*\{[^}]*margin-top:\s*auto/s);
  assert.match(css, /\.recommendation-chat__composer\s*\{[^}]*background:\s*transparent/s);
  assert.match(css, /\.recommendation-chat__example\s*\{[^}]*border:\s*0/s);
});

test("公共标题栏提供新建聊天、折叠和唯一退出入口", () => {
  const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
  const mainJs = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");
  const headerStart = html.indexOf('id="workbenchHeader"');
  const headerEnd = html.indexOf("</header>", headerStart);
  const qwenStart = html.indexOf('id="workbenchQwenButton"');
  const qwenEnd = html.indexOf("</button>", qwenStart) + "</button>".length;
  const qwenButton = html.slice(qwenStart, qwenEnd);
  const newChatStart = html.indexOf('id="workbenchNewChatButton"');
  const newChatEnd = html.indexOf("</button>", newChatStart) + "</button>".length;
  const newChatButton = html.slice(newChatStart, newChatEnd);
  const chatCloseStart = html.indexOf('id="workbenchChatCloseButton"');
  const chatCloseTag = html.slice(chatCloseStart, html.indexOf(">", chatCloseStart) + 1);
  const bodyStart = html.indexOf('id="workbenchBody"');
  const qwenHandlerStart = mainJs.indexOf('workbench.qwenButton.addEventListener("click"');
  const qwenHandlerEnd = mainJs.indexOf("workbench.collapseButton.addEventListener", qwenHandlerStart);
  const qwenHandler = mainJs.slice(qwenHandlerStart, qwenHandlerEnd);

  assert.ok(headerStart >= 0, "缺少公共工作台标题栏");
  assert.ok(qwenStart > headerStart, "新建聊天入口应位于公共标题栏中");
  assert.ok(chatCloseStart > headerStart && chatCloseStart < headerEnd, "聊天关闭按钮应与新建和收起按钮位于同一标题栏");
  assert.ok(bodyStart > qwenStart, "新建聊天入口应位于可折叠正文之外");
  assert.match(qwenButton, /data-workbench-qwen/);
  assert.match(qwenButton, /aria-label="打开千问路线助手"/);
  assert.match(qwenButton, /<img[^>]*qwen-color\.png/);
  assert.doesNotMatch(qwenButton, /新建千问聊天|<svg/);
  assert.ok(newChatStart > qwenEnd && newChatStart < chatCloseStart, "新建聊天应是进入聊天后新增的独立按钮");
  assert.match(newChatButton, /data-workbench-new-chat/);
  assert.match(newChatButton, /aria-label="新建千问聊天"/);
  assert.match(newChatButton, /\shidden(?:\s|>)/);
  assert.match(newChatButton, /<svg[\s\S]*?<path[\s\S]*?<path/);
  assert.match(qwenHandler, /recommendationUI\.newChat\(\)/);
  assert.doesNotMatch(qwenHandler, /closeChat\(\)/);
  assert.match(mainJs, /newChatButton\.addEventListener\("click"[\s\S]*?recommendationUI\.newChat\(\)/);
  assert.match(mainJs, /qwenButton\.hidden\s*=\s*uiState\.chatOpen/);
  assert.match(mainJs, /newChatButton\.hidden\s*=\s*!uiState\.chatOpen/);
  assert.match(chatCloseTag, /data-workbench-chat-close/);
  assert.match(chatCloseTag, /aria-label="关闭千问聊天"/);
  assert.match(chatCloseTag, /\shidden(?:\s|>)/);
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
      if (documentStub.activeElement && this.contains(documentStub.activeElement)) {
        documentStub.activeElement = null;
      }
      this.children.forEach((child) => { child.parentElement = null; });
      this.children = [];
      this.append(...children);
      this._text = "";
    }

    remove() {
      if (!this.parentElement) return;
      this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
      this.parentElement = null;
    }

    setAttribute(name, value) {
      this.attributes[name] = String(value);
    }

    addEventListener(name, callback) {
      this.listeners[name] = callback;
    }

    requestSubmit() {
      return this.listeners.submit?.({ preventDefault() {} });
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

function findByTag(node, tagName) {
  if (node.tagName === tagName) return node;
  for (const child of node.children || []) {
    const found = findByTag(child, tagName);
    if (found) return found;
  }
  return null;
}
