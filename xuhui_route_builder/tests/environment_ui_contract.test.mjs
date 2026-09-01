import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCurrentEnvironmentModel,
  buildForecastEnvironmentModel,
  buildRouteExposureModel,
  createEnvironmentPanel,
} from "../web/src/environment-ui.js";

const FUTURE = "2099-08-27T23:59:59+08:00";

function record(values, overrides = {}) {
  return {
    business_time: "2099-08-27T10:00:00+08:00",
    fetched_at: "2099-08-27T09:55:00+08:00",
    valid_until: FUTURE,
    status: "ok",
    values,
    ...overrides,
  };
}

function lifeIndex(date, name, category) {
  return record({
    local_date_time: date,
    name,
    category,
    value: "2",
    text: `${name}${category}`,
  }, { business_time: `${date}T00:00:00+08:00` });
}

function dashboardFixture() {
  const indexNames = ["运动指数", "穿衣指数", "紫外线指数", "过敏指数", "舒适度指数", "防晒指数"];
  return {
    metadata: { generated_at: "2099-08-27T10:05:00+08:00", status: "partial" },
    current: {
      status: "ok",
      alerts: [],
      weather: record({
        temperature_c: 26.4,
        weather_text: "多云",
        weather_icon: "101",
        relative_humidity_pct: 68,
        wind_direction_deg: 45,
        wind_speed_kmh: 12.3,
        precipitation_mm: 0.2,
      }),
      aqi: record({ aqi: 42 }),
    },
    forecast: {
      status: "partial",
      weather_hourly: [record({
        temperature_c: 27,
        weather_text: "晴",
        weather_icon: "100",
        relative_humidity_pct: 60,
        wind_direction_deg: 90,
        wind_speed_kmh: 10,
        precipitation_mm: 0,
        precipitation_probability_pct: 10,
      }, { business_time: "2099-08-27T11:00:00+08:00" })],
      aqi_hourly: [record({ aqi: 48 }, {
        business_time: "2099-08-27T11:00:00+08:00",
        status: "partial",
      })],
      pm2_5_hourly: [record({ pm2_5_ug_m3: null }, { status: "partial" })],
      pollen_grid_daily: [{ value: 99 }],
      life_indices_daily: ["2099-08-27", "2099-08-28", "2099-08-29"]
        .flatMap((date) => indexNames.map((name) => lifeIndex(date, name, "适宜"))),
    },
    routes: {
      status: "partial",
      count: 1,
      items: [{
        route_id: "XH_WALK_0001",
        status: "partial",
        pm2_5: {
          value: 15.339681,
          unit: "µg/m³",
          status: "ok",
          confidence: "medium",
          estimated: true,
          spatial_scale: "1km_grid_estimate",
        },
        pollen_daily: [
          {
            business_time: "2099-08-27",
            value: 31.47,
            unit: "0-100 risk index",
            status: "partial",
            confidence: "low",
            risk_level: "low",
            estimated: true,
            expires_at: FUTURE,
            spatial_scale: "about_1000m_grid_sample",
          },
          {
            business_time: "2099-08-28",
            value: 88,
            unit: "0-100 risk index",
            status: "partial",
            risk_level: "high",
            expires_at: FUTURE,
          },
        ],
        noise: {
          value: 36.807,
          unit: "0-100 risk index",
          status: "partial",
          confidence: "low",
          risk_level: "medium",
          estimated: true,
          spatial_scale: "about_100m_road_segment_proxy",
        },
      }],
    },
  };
}

test("当前环境模型保留天气、湿度、风、降水和 AQI，空预警隐藏", () => {
  const model = buildCurrentEnvironmentModel(dashboardFixture());

  assert.equal(model.location, "徐汇区");
  assert.equal(model.temperature, 26.4);
  assert.equal(model.weatherText, "多云");
  assert.equal(model.weatherIcon, "101");
  assert.equal(model.humidity, 68);
  assert.equal(model.windDirection, "东北风");
  assert.equal(model.windSpeed, 12.3);
  assert.equal(model.precipitation, 0.2);
  assert.equal(model.aqi, 42);
  assert.equal(model.aqiLevel, "优");
  assert.deepEqual(model.alerts, []);
});

test("过期当前记录保留最后一次成功数值并标记等待更新", () => {
  const dashboard = dashboardFixture();
  dashboard.current.weather.valid_until = "2000-01-01T00:00:00+08:00";
  dashboard.current.aqi.valid_until = "2000-01-01T00:00:00+08:00";

  const model = buildCurrentEnvironmentModel(dashboard);

  assert.equal(model.weatherStatus, "stale");
  assert.equal(model.temperature, 26.4);
  assert.equal(model.temperatureText, "26.4°");
  assert.equal(model.humidity, 68);
  assert.equal(model.humidityText, "68%");
  assert.equal(model.aqiStatus, "stale");
  assert.equal(model.aqi, 42);
  assert.equal(model.aqiText, "42");
  assert.equal(model.weatherFreshnessText, "等待更新");
  assert.equal(model.aqiFreshnessText, "等待更新");
});

test("过期天气保留旧值，缺失 AQI 保持暂无数据", () => {
  const dashboard = dashboardFixture();
  dashboard.current.weather.valid_until = "2000-01-01T00:00:00+08:00";
  dashboard.current.aqi = { status: "no_data", values: {} };

  const model = buildCurrentEnvironmentModel(dashboard);

  assert.equal(model.weatherStatus, "stale");
  assert.equal(model.temperature, 26.4);
  assert.equal(model.temperatureText, "26.4°");
  assert.equal(model.weatherFreshnessText, "等待更新");
  assert.equal(model.aqiStatus, "no_data");
  assert.equal(model.aqi, null);
  assert.equal(model.aqiText, "暂无数据");
});

test("后端显式 stale 状态保留最后 AQI 并标记等待更新", () => {
  const dashboard = dashboardFixture();
  dashboard.current.aqi = record({ aqi: 88 }, { status: "stale" });

  const model = buildCurrentEnvironmentModel(dashboard);

  assert.equal(model.aqiStatus, "stale");
  assert.equal(model.aqi, 88);
  assert.equal(model.aqiText, "88");
  assert.equal(model.aqiFreshnessText, "等待更新");
});

test("有效预警映射标题和正文，过期预警被过滤", () => {
  const dashboard = dashboardFixture();
  dashboard.current.alerts = [
    record({ summary: "上海市暴雨蓝色预警", text: "局部将出现强降水", level: "Moderate" }),
    record({ summary: "过期预警" }, { valid_until: "2000-01-01T00:00:00+08:00" }),
  ];

  const model = buildCurrentEnvironmentModel(dashboard);

  assert.deepEqual(model.alerts, [{
    title: "上海市暴雨蓝色预警",
    text: "局部将出现强降水",
    severity: "Moderate",
  }]);
  assert.equal(model.updatedAt, "2099-08-27T10:00:00+08:00");
  assert.equal(model.validUntil, FUTURE);
});

test("未来模型只包含 24 小时天气、AQI 和三天六类生活指数", () => {
  const model = buildForecastEnvironmentModel(dashboardFixture());

  assert.equal(model.weatherHours.length, 1);
  assert.equal(model.weatherHours[0].temperature, 27);
  assert.equal(model.aqiHours.length, 1);
  assert.equal(model.aqiHours[0].aqi, 48);
  assert.equal(model.indexDays.length, 3);
  assert.deepEqual(model.indexDays.map(({ label }) => label), ["今天", "明天", "后天"]);
  assert.ok(model.indexDays.every(({ indices }) => indices.length === 6));
  assert.ok(model.indexDays.every(({ indices }) => indices.some(({ name }) => name === "过敏指数")));

  const serialized = JSON.stringify(model);
  assert.equal(serialized.includes("pm2_5"), false);
  assert.equal(serialized.includes("pollen"), false);
});

test("路线环境只取当天 PM2.5、花粉和噪声，并保留真实空间尺度", () => {
  const model = buildRouteExposureModel(dashboardFixture(), "XH_WALK_0001");

  assert.equal(model.routeId, "XH_WALK_0001");
  assert.equal(model.pm25.value, 15.3);
  assert.equal(model.pm25.unit, "µg/m³");
  assert.equal(model.pollen.value, 31.5);
  assert.equal(model.pollen.riskLevel, "低");
  assert.equal(model.noise.value, 36.8);
  assert.equal(model.noise.riskLevel, "中");
  assert.match(model.details.pm25, /1 km.*估计/);
  assert.match(model.details.pollen, /约 1 km.*当天/);
  assert.match(model.details.noise, /约 100 m.*风险代理/);
  assert.doesNotMatch(JSON.stringify(model), /分贝|实测/);
  assert.equal(JSON.stringify(model).includes("88"), false);
});

test("路线不存在时返回稳定空态", () => {
  const model = buildRouteExposureModel(dashboardFixture(), "XH_RUN_9999");

  assert.equal(model.status, "no_data");
  assert.equal(model.pm25.displayValue, "暂无数据");
  assert.equal(model.pollen.displayValue, "暂无数据");
  assert.equal(model.noise.displayValue, "暂无数据");
});

test("环境面板自行管理展开、页签和指数日期切换", () => {
  const container = createPanelStub();
  const panel = createEnvironmentPanel(container, dashboardFixture());

  assert.ok(container.innerHTML.includes("徐汇区"));
  assert.ok(container.innerHTML.includes("data-environment-tab=\"now\""));
  assert.ok(container.innerHTML.includes("data-environment-tab=\"hourly\""));
  assert.ok(container.innerHTML.includes("data-environment-tab=\"indices\""));
  assert.ok(container.innerHTML.includes('aria-haspopup="dialog"'));
  assert.ok(container.innerHTML.includes('class="environment-details" role="dialog"'));
  assert.equal(container.innerHTML.includes("environment-alerts"), false);
  assert.equal(container.innerHTML.includes("PM2.5"), false);
  assert.equal(container.innerHTML.includes("未来花粉"), false);

  container.toggle.click();
  assert.equal(container.details.hidden, false);
  assert.equal(container.toggle.attributes["aria-expanded"], "true");

  container.tabButtons[1].click();
  assert.equal(container.tabButtons[1].classList.contains("is-active"), true);
  assert.equal(container.views[1].hidden, false);
  assert.equal(container.views[0].hidden, true);

  container.dayButtons[2].click();
  assert.equal(container.dayButtons[2].classList.contains("is-active"), true);
  assert.equal(container.dayPanels[2].hidden, false);
  assert.equal(container.dayPanels[0].hidden, true);

  panel.destroy();
  assert.equal(container.innerHTML, "");
});

test("环境弹层支持外部点击、Escape、焦点返回和同层入口互斥", () => {
  const documentRoot = createDocumentStub();
  const container = createPanelStub();
  const panel = createEnvironmentPanel(container, dashboardFixture(), { documentRoot });

  container.toggle.click();
  assert.equal(container.details.hidden, false);
  documentRoot.keydown("Escape");
  assert.equal(container.details.hidden, true);
  assert.equal(container.toggle.focusCount, 1);

  container.toggle.click();
  documentRoot.click(outsideTarget());
  assert.equal(container.details.hidden, true);

  documentRoot.legend.hidden = false;
  documentRoot.layerButton.setAttribute("aria-expanded", "true");
  documentRoot.profileDialog.open = true;
  container.toggle.click();
  assert.equal(documentRoot.legend.hidden, true);
  assert.equal(documentRoot.layerButton.attributes["aria-expanded"], "false");
  assert.equal(documentRoot.profileDialog.closeCount, 1);

  documentRoot.click(controlTarget("#profileSettingsButton"));
  assert.equal(container.details.hidden, true);

  panel.destroy();
  assert.equal(documentRoot.listenerCount(), 0);
});

test("预警只在按钮显示状态点，详情不展示状态和时间元数据", () => {
  const dashboard = dashboardFixture();
  dashboard.current.alerts = [
    record({ summary: "上海市暴雨蓝色预警", text: "局部将出现强降水", level: "Moderate" }),
  ];
  const container = createPanelStub();
  createEnvironmentPanel(container, dashboard);

  const summary = panelSummary(container.innerHTML);
  const details = container.innerHTML.slice(container.innerHTML.indexOf('class="environment-details"'));
  assert.match(summary, /environment-summary__primary" aria-hidden="true"/);
  assert.match(summary, /environment-summary__metrics" aria-hidden="true"/);
  assert.match(summary, /environment-alert-dot/);
  assert.doesNotMatch(summary, /上海市暴雨蓝色预警/);
  assert.match(details, /上海市暴雨蓝色预警/);
  assert.doesNotMatch(details, /数据状态/);
  assert.doesNotMatch(details, /业务时间/);
  assert.doesNotMatch(details, /有效期/);
});

test("多条有效预警按等级聚合成一张提示卡", () => {
  const dashboard = dashboardFixture();
  dashboard.current.alerts = [
    record({ summary: "上海市暴雨蓝色预警", text: "局部将出现强降水", level: "minor" }),
    record({ summary: "上海市雷电黄色预警", text: "可能发生雷电活动", level: "moderate" }),
  ];
  const container = createPanelStub();
  createEnvironmentPanel(container, dashboard);

  const details = container.innerHTML.slice(container.innerHTML.indexOf('class="environment-details"'));
  assert.equal((details.match(/class="environment-alert"/g) || []).length, 1);
  assert.match(details, /当前 2 条气象预警/);
  assert.ok(details.indexOf("上海市雷电黄色预警") < details.indexOf("上海市暴雨蓝色预警"));
});

test("摘要缺值使用短横线，过期值保留并标明等待更新", () => {
  const missingDashboard = dashboardFixture();
  missingDashboard.current.aqi = { status: "no_data", values: {} };
  const missingContainer = createPanelStub();
  createEnvironmentPanel(missingContainer, missingDashboard);
  assert.match(panelSummary(missingContainer.innerHTML), /<span>AQI<\/span><strong>—<\/strong>/);
  assert.match(missingContainer.innerHTML, /<span>AQI<\/span><strong>暂无数据<\/strong>/);

  const staleDashboard = dashboardFixture();
  staleDashboard.current.weather.valid_until = "2000-01-01T00:00:00+08:00";
  staleDashboard.current.aqi = { status: "no_data", values: {} };
  const staleContainer = createPanelStub();
  createEnvironmentPanel(staleContainer, staleDashboard);
  const staleSummary = panelSummary(staleContainer.innerHTML);
  const staticSummary = staleSummary.slice(0, staleSummary.indexOf('<button class="environment-toggle"'));
  assert.match(staticSummary, /多云（等待更新）/);
  assert.match(staticSummary, /environment-summary__temperature">26\.4°<\/div>/);
  assert.match(staticSummary, /<span>湿度<\/span><strong>68%<\/strong>/);
  assert.match(staticSummary, /<span>AQI<\/span><strong>—<\/strong>/);
  assert.match(staleContainer.innerHTML, /<span>湿度<\/span><strong>68%<\/strong><small[^>]*>相对湿度 · 等待更新<\/small>/);
  assert.match(staleContainer.innerHTML, /<span>AQI<\/span><strong>暂无数据<\/strong>/);

  const staleWeatherCard = nowCardHtml(staleContainer.innerHTML, "天气");
  const missingAqiCard = nowCardHtml(staleContainer.innerHTML, "AQI");
  assert.equal(occurrences(staleWeatherCard, "等待更新"), 1);
  assert.match(staleWeatherCard, /<strong>多云<\/strong>/);
  assert.match(staleWeatherCard, /<small[^>]*>26\.4° · 等待更新<\/small>/);
  assert.equal(occurrences(missingAqiCard, "暂无数据"), 1);
  assert.doesNotMatch(missingAqiCard, /<small/);

  const normalContainer = createPanelStub();
  createEnvironmentPanel(normalContainer, dashboardFixture());
  assert.match(nowCardHtml(normalContainer.innerHTML, "天气"), /<small[^>]*>26\.4°<\/small>/);
  assert.match(nowCardHtml(normalContainer.innerHTML, "AQI"), /<small[^>]*>优<\/small>/);
});

test("AQI 摘要分开展示数值和空气质量等级", () => {
  const container = createPanelStub();
  createEnvironmentPanel(container, dashboardFixture());
  const summary = panelSummary(container.innerHTML);

  assert.match(summary, /environment-summary__metric--aqi/);
  assert.match(summary, /environment-summary__aqi-number">42<\/span>/);
  assert.match(summary, /environment-summary__aqi-level environment-summary__aqi-level--excellent">优<\/span>/);
});

test("横条摘要以图标和文字完整展示天气、温度、湿度及 AQI 等级", () => {
  const container = createPanelStub();
  createEnvironmentPanel(container, dashboardFixture());
  const toggle = environmentToggleHtml(container.innerHTML);

  assert.match(toggle, /aria-label="当前环境：多云，温度 26\.4°，湿度 68%，AQI 42 优。展开环境详情"/);
  assert.match(toggle, /environment-toggle__item--weather[\s\S]*qi-101[\s\S]*<span[^>]*>天气<\/span>[\s\S]*<strong>多云<\/strong>/);
  assert.match(toggle, /environment-toggle__item--temperature[\s\S]*data-environment-icon="temperature"[\s\S]*<span[^>]*>温度<\/span>[\s\S]*<strong>26\.4°<\/strong>/);
  assert.match(toggle, /environment-toggle__item--humidity[\s\S]*data-environment-icon="humidity"[\s\S]*<span[^>]*>湿度<\/span>[\s\S]*<strong>68%<\/strong>/);
  assert.match(toggle, /environment-toggle__item--aqi[\s\S]*data-environment-icon="aqi"[\s\S]*<span[^>]*>AQI<\/span>[\s\S]*environment-toggle__aqi-number">42<\/span>[\s\S]*environment-toggle__aqi-level environment-toggle__aqi-level--excellent">优<\/span>/);
  assert.match(toggle, /<svg class="environment-toggle__chevron"[\s\S]*viewBox="0 0 20 20"[\s\S]*<path d="m6 8 4 4 4-4"/);
  assert.doesNotMatch(toggle, />⌄<\/span>/);
  assert.equal(container.toggle.attributes["aria-label"], "当前环境：多云，温度 26.4°，湿度 68%，AQI 42 优。展开环境详情");

  container.toggle.click();
  assert.equal(container.toggle.attributes["aria-label"], "当前环境：多云，温度 26.4°，湿度 68%，AQI 42 优。收起环境详情");
});

test("横条摘要保留过期天气数值并区分缺失 AQI", () => {
  const dashboard = dashboardFixture();
  dashboard.current.weather.valid_until = "2000-01-01T00:00:00+08:00";
  dashboard.current.aqi = { status: "no_data", values: {} };
  const container = createPanelStub();
  createEnvironmentPanel(container, dashboard);
  const toggle = environmentToggleHtml(container.innerHTML);

  assert.match(toggle, /aria-label="当前环境：多云（等待更新），温度 26\.4°，湿度 68%，AQI 暂无数据。展开环境详情"/);
  assert.match(toggle, /environment-toggle__item--weather[\s\S]*<strong>多云<\/strong>[\s\S]*<span class="environment-toggle__label">等待更新<\/span>/);
  assert.match(toggle, /environment-toggle__item--temperature[\s\S]*<strong>26\.4°<\/strong>/);
  assert.match(toggle, /environment-toggle__item--humidity[\s\S]*<strong>68%<\/strong>/);
  assert.match(toggle, /environment-toggle__item--aqi[\s\S]*<strong>暂无数据<\/strong>/);
  assert.doesNotMatch(toggle, /environment-toggle__aqi-level/);
});

test("24 小时全量不可用时聚合为空态，混合数据以短横线保留时间轴", () => {
  const unavailable = dashboardFixture();
  unavailable.forecast.weather_hourly = Array.from({ length: 24 }, (_, hour) => record({
    temperature_c: 30,
    weather_text: "晴",
  }, {
    business_time: `2099-08-27T${String(hour).padStart(2, "0")}:00:00+08:00`,
    status: "stale",
  }));
  unavailable.forecast.aqi_hourly = Array.from({ length: 24 }, (_, hour) => ({
    business_time: `2099-08-27T${String(hour).padStart(2, "0")}:00:00+08:00`,
    status: "no_data",
    values: {},
  }));
  const unavailableContainer = createPanelStub();
  const unavailablePanel = createEnvironmentPanel(unavailableContainer, unavailable);
  assert.equal(unavailablePanel.forecast.weatherHours.length, 24);
  assert.equal(unavailablePanel.forecast.aqiHours.length, 24);

  const unavailableWeather = hourlySection(unavailableContainer.innerHTML, "未来 24 小时天气");
  const unavailableAqi = hourlySection(unavailableContainer.innerHTML, "未来 24 小时 AQI");
  assert.equal(occurrences(unavailableWeather, "数据更新中"), 1);
  assert.match(unavailableWeather, /24 小时天气数据更新中/);
  assert.equal(occurrences(unavailableWeather, 'class="environment-hour"'), 0);
  assert.equal(occurrences(unavailableAqi, "暂无数据"), 1);
  assert.match(unavailableAqi, /24 小时 AQI 暂无数据/);
  assert.equal(occurrences(unavailableAqi, 'class="environment-aqi-point"'), 0);

  const mixed = dashboardFixture();
  mixed.forecast.weather_hourly = [
    mixed.forecast.weather_hourly[0],
    ...unavailable.forecast.weather_hourly.slice(1),
  ];
  mixed.forecast.aqi_hourly = [
    mixed.forecast.aqi_hourly[0],
    ...unavailable.forecast.aqi_hourly.slice(1),
  ];
  const mixedContainer = createPanelStub();
  const mixedPanel = createEnvironmentPanel(mixedContainer, mixed);
  assert.equal(mixedPanel.forecast.weatherHours.length, 24);
  assert.equal(mixedPanel.forecast.aqiHours.length, 24);

  const mixedWeather = hourlySection(mixedContainer.innerHTML, "未来 24 小时天气");
  const mixedAqi = hourlySection(mixedContainer.innerHTML, "未来 24 小时 AQI");
  assert.equal(occurrences(mixedWeather, 'class="environment-hour"'), 24);
  assert.equal(occurrences(mixedAqi, 'class="environment-aqi-point"'), 24);
  assert.doesNotMatch(mixedWeather, /数据更新中|暂无数据/);
  assert.doesNotMatch(mixedAqi, /数据更新中|暂无数据/);
  assert.equal(occurrences(mixedWeather, "<strong>—</strong>"), 23);
  assert.equal(occurrences(mixedAqi, "<strong>—</strong>"), 23);
});

function panelSummary(html) {
  return html.slice(0, html.indexOf("</section>") + "</section>".length);
}

function environmentToggleHtml(html) {
  const match = html.match(/<button class="environment-toggle"[\s\S]*?<\/button>/);
  assert.ok(match, "未找到横条环境摘要按钮");
  return match[0];
}

function occurrences(value, pattern) {
  return value.split(pattern).length - 1;
}

function nowCardHtml(html, label) {
  const match = html.match(new RegExp(`<article class="environment-now-card"><span>${label}</span>[\\s\\S]*?</article>`));
  assert.ok(match, `未找到${label}卡片`);
  return match[0];
}

function hourlySection(html, label) {
  const match = html.match(new RegExp(`<section aria-label="${label}">[\\s\\S]*?</section>`));
  assert.ok(match, `未找到${label}`);
  return match[0];
}

function createPanelStub() {
  const toggle = interactiveElement();
  const details = { hidden: true };
  const tabButtons = ["now", "hourly", "indices"].map((environmentTab) => (
    interactiveElement({ environmentTab })
  ));
  const views = ["now", "hourly", "indices"].map((environmentView, index) => ({
    dataset: { environmentView },
    hidden: index !== 0,
    classList: classList(index === 0),
  }));
  const dayButtons = ["2099-08-27", "2099-08-28", "2099-08-29"].map((indexDay, index) => (
    interactiveElement({ indexDay }, index === 0)
  ));
  const dayPanels = ["2099-08-27", "2099-08-28", "2099-08-29"].map((indexPanel, index) => ({
    dataset: { indexPanel },
    hidden: index !== 0,
  }));
  return {
    innerHTML: "",
    toggle,
    details,
    tabButtons,
    views,
    dayButtons,
    dayPanels,
    classList: classList(),
    contains(target) { return target === this || target === toggle || target === details; },
    querySelector(selector) {
      return selector === ".environment-toggle" ? toggle
        : selector === ".environment-details" ? details
          : null;
    },
    querySelectorAll(selector) {
      return selector === "[data-environment-tab]" ? tabButtons
        : selector === "[data-environment-view]" ? views
          : selector === "[data-index-day]" ? dayButtons
            : selector === "[data-index-panel]" ? dayPanels
              : [];
    },
  };
}

function interactiveElement(dataset = {}, active = false) {
  return {
    dataset,
    attributes: {},
    classList: classList(active),
    listeners: {},
    focusCount: 0,
    addEventListener(type, handler) { this.listeners[type] = handler; },
    removeEventListener(type) { delete this.listeners[type]; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    focus() { this.focusCount += 1; },
    click() { this.listeners.click?.(); },
  };
}

function createDocumentStub() {
  const listeners = new Map();
  const layerButton = interactiveElement();
  const legend = { hidden: true };
  const profileDialog = {
    open: false,
    closeCount: 0,
    close() {
      this.open = false;
      this.closeCount += 1;
    },
  };
  return {
    layerButton,
    legend,
    profileDialog,
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type) { listeners.delete(type); },
    querySelector(selector) {
      return selector === "#mapLayerButton" ? layerButton
        : selector === "#mapLegend" ? legend
          : selector === ".profile-dialog[open]" && profileDialog.open ? profileDialog
            : null;
    },
    click(target) { listeners.get("click")?.({ target }); },
    keydown(key) { listeners.get("keydown")?.({ key }); },
    listenerCount() { return listeners.size; },
  };
}

function outsideTarget() {
  return { closest() { return null; } };
}

function controlTarget(selector) {
  return { closest(candidate) { return candidate === selector ? this : null; } };
}

function classList(active = false) {
  const values = new Set(active ? ["is-active"] : []);
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    toggle(name, force) {
      if (force ?? !values.has(name)) values.add(name);
      else values.delete(name);
    },
    contains(name) { return values.has(name); },
  };
}
