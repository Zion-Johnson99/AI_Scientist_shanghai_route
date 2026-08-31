const LIFE_INDEX_NAMES = [
  "运动指数",
  "穿衣指数",
  "紫外线指数",
  "过敏指数",
  "舒适度指数",
  "防晒指数",
];

const DAY_LABELS = ["今天", "明天", "后天"];
const DISPLAY_STATUS = {
  no_data: "暂无数据",
  stale: "数据更新中",
};
const ALERT_SEVERITY_RANK = {
  extreme: 4,
  severe: 3,
  moderate: 2,
  minor: 1,
};

export function buildCurrentEnvironmentModel(dashboard) {
  const weather = dashboard?.current?.weather;
  const aqiRecord = dashboard?.current?.aqi;
  const weatherStatus = recordStatus(weather, weather?.values?.temperature_c);
  const aqiStatus = recordStatus(aqiRecord, aqiRecord?.values?.aqi);
  const weatherAvailable = hasDisplayValue(weatherStatus);
  const aqiAvailable = hasDisplayValue(aqiStatus);
  const values = weather?.values || {};
  const temperature = weatherAvailable ? finiteNumber(values.temperature_c) : null;
  const humidity = weatherAvailable ? finiteNumber(values.relative_humidity_pct) : null;
  const windSpeed = weatherAvailable ? finiteNumber(values.wind_speed_kmh) : null;
  const precipitation = weatherAvailable ? finiteNumber(values.precipitation_mm) : null;
  const aqi = aqiAvailable ? finiteNumber(aqiRecord?.values?.aqi) : null;

  return {
    location: "徐汇区",
    status: combinedStatus(weatherStatus, aqiStatus),
    weatherStatus,
    aqiStatus,
    temperature,
    temperatureText: temperature === null ? statusText(weatherStatus) : `${formatNumber(temperature)}°`,
    weatherText: weatherAvailable ? String(values.weather_text || "天气更新中") : statusText(weatherStatus),
    weatherIcon: weatherAvailable && values.weather_icon ? String(values.weather_icon) : null,
    humidity,
    humidityText: humidity === null ? statusText(weatherStatus) : `${formatNumber(humidity)}%`,
    windDirection: weatherAvailable ? windDirectionName(values.wind_direction_deg) : statusText(weatherStatus),
    windSpeed,
    windText: windSpeed === null
      ? statusText(weatherStatus)
      : `${windDirectionName(values.wind_direction_deg)} ${formatNumber(windSpeed)} km/h`,
    precipitation,
    precipitationText: precipitation === null
      ? statusText(weatherStatus)
      : `${formatNumber(precipitation)} mm`,
    aqi,
    aqiText: aqi === null ? statusText(aqiStatus) : formatNumber(aqi),
    aqiLevel: aqi === null ? statusText(aqiStatus) : aqiLevel(aqi),
    alerts: normalizeAlerts(dashboard?.current?.alerts),
    updatedAt: weather?.business_time || weather?.fetched_at || null,
    validUntil: weather?.valid_until || aqiRecord?.valid_until || null,
  };
}

export function buildForecastEnvironmentModel(dashboard) {
  const forecast = dashboard?.forecast || {};
  const weatherHours = (forecast.weather_hourly || []).slice(0, 24).map((record) => {
    const values = record?.values || {};
    const status = recordStatus(record, values.temperature_c);
    const available = hasDisplayValue(status);
    const temperature = available ? finiteNumber(values.temperature_c) : null;
    return {
      time: record?.business_time || null,
      timeLabel: hourLabel(record?.business_time),
      status,
      temperature,
      temperatureText: temperature === null ? statusText(status) : `${formatNumber(temperature)}°`,
      weatherText: available ? String(values.weather_text || "天气更新中") : statusText(status),
      weatherIcon: available && values.weather_icon ? String(values.weather_icon) : null,
      humidity: available ? finiteNumber(values.relative_humidity_pct) : null,
      windDirection: available ? windDirectionName(values.wind_direction_deg) : statusText(status),
      windSpeed: available ? finiteNumber(values.wind_speed_kmh) : null,
      precipitation: available ? finiteNumber(values.precipitation_mm) : null,
      precipitationProbability: available
        ? finiteNumber(values.precipitation_probability_pct)
        : null,
    };
  });
  const aqiHours = (forecast.aqi_hourly || []).slice(0, 24).map((record) => {
    const value = record?.values?.aqi;
    const status = recordStatus(record, value);
    const aqi = hasDisplayValue(status) ? finiteNumber(value) : null;
    return {
      time: record?.business_time || null,
      timeLabel: hourLabel(record?.business_time),
      status,
      aqi,
      aqiText: aqi === null ? statusText(status) : formatNumber(aqi),
      level: aqi === null ? statusText(status) : aqiLevel(aqi),
    };
  });

  const lifeRecords = forecast.life_indices_daily || [];
  const dates = forecastDates(dashboard);
  const indexDays = dates.map((date, dayIndex) => ({
    date,
    label: DAY_LABELS[dayIndex],
    indices: LIFE_INDEX_NAMES.map((name) => {
      const record = lifeRecords.find((item) => (
        item?.values?.local_date_time === date && item?.values?.name === name
      ));
      const category = record?.values?.category;
      const status = recordStatus(record, category);
      const available = hasDisplayValue(status);
      return {
        name,
        status,
        category: available ? String(category) : statusText(status),
        value: available ? String(record?.values?.value ?? "") : null,
        text: available ? String(record?.values?.text || "") : statusText(status),
      };
    }),
  }));

  return {
    status: String(forecast.status || combinedStatus(
      ...weatherHours.map(({ status }) => status),
      ...aqiHours.map(({ status }) => status),
    )),
    weatherHours,
    aqiHours,
    indexDays,
  };
}

export function buildRouteExposureModel(dashboard, routeId) {
  const route = dashboard?.routes?.items?.find((item) => item?.route_id === routeId);
  const details = {
    pm25: "PM2.5 为沿路线汇总的 1 km 网格估计值。",
    pollen: "花粉为约 1 km 网格采样形成的当天风险指数。",
    noise: "噪声为约 100 m 路段的 0–100 风险代理。",
  };
  if (!route) {
    return {
      routeId,
      status: "no_data",
      pm25: emptyExposure("PM2.5"),
      pollen: emptyExposure("花粉"),
      noise: emptyExposure("噪声"),
      details,
    };
  }

  const today = dashboardDate(dashboard);
  const pollen = (route.pollen_daily || []).find((item) => item?.business_time === today);
  return {
    routeId,
    status: String(route.status || "partial"),
    pm25: exposureMetric("PM2.5", route.pm2_5, { digits: 1 }),
    pollen: exposureMetric("花粉", pollen, { digits: 1, risk: true }),
    noise: exposureMetric("噪声", route.noise, { digits: 1, risk: true }),
    details,
  };
}

export function createEnvironmentPanel(
  container,
  dashboard,
  { documentRoot = globalThis.document } = {},
) {
  if (!container) {
    throw new Error("环境面板缺少挂载容器。");
  }
  const current = buildCurrentEnvironmentModel(dashboard);
  const forecast = buildForecastEnvironmentModel(dashboard);
  const listeners = [];
  container.classList.add("environment-panel--ready");
  container.innerHTML = renderPanel(current, forecast);

  const details = container.querySelector(".environment-details");
  const toggle = container.querySelector(".environment-toggle");
  const tabButtons = [...container.querySelectorAll("[data-environment-tab]")];
  const views = [...container.querySelectorAll("[data-environment-view]")];
  const dayButtons = [...container.querySelectorAll("[data-index-day]")];
  const dayPanels = [...container.querySelectorAll("[data-index-panel]")];

  function listen(element, type, handler) {
    if (!element) return;
    element.addEventListener(type, handler);
    listeners.push([element, type, handler]);
  }

  function closeLayerMenu() {
    const legend = documentRoot?.querySelector?.("#mapLegend");
    const button = documentRoot?.querySelector?.("#mapLayerButton");
    if (legend) legend.hidden = true;
    button?.setAttribute?.("aria-expanded", "false");
  }

  function closeProfileDialog() {
    documentRoot?.querySelector?.(".profile-dialog[open]")?.close?.();
  }

  function setOpen(open, { restoreFocus = false } = {}) {
    if (!details || !toggle) return;
    if (open) {
      closeLayerMenu();
      closeProfileDialog();
    }
    details.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", environmentToggleLabel(current, open));
    container.classList.toggle("is-expanded", open);
    if (!open && restoreFocus) toggle.focus?.();
  }

  listen(toggle, "click", () => setOpen(Boolean(details?.hidden)));
  listen(documentRoot, "click", (event) => {
    const target = event?.target;
    if (!target) return;
    const layerControl = target.closest?.("#mapLayerButton") || target.closest?.("#mapLegend");
    const profileControl = target.closest?.("#profileSettingsButton");
    if (profileControl) closeLayerMenu();
    if (layerControl) closeProfileDialog();
    if (!container.contains?.(target)) setOpen(false);
    if (!layerControl && !target.closest?.("#mapLegend")) closeLayerMenu();
  });
  listen(documentRoot, "keydown", (event) => {
    if (event?.key === "Escape" && !details?.hidden) {
      setOpen(false, { restoreFocus: true });
    }
  });
  tabButtons.forEach((button) => listen(button, "click", () => {
    const selected = button.dataset.environmentTab;
    tabButtons.forEach((item) => {
      const active = item.dataset.environmentTab === selected;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
    });
    views.forEach((view) => {
      const active = view.dataset.environmentView === selected;
      view.hidden = !active;
      view.classList.toggle("is-active", active);
    });
  }));
  dayButtons.forEach((button) => listen(button, "click", () => {
    const selected = button.dataset.indexDay;
    dayButtons.forEach((item) => {
      const active = item.dataset.indexDay === selected;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
    });
    dayPanels.forEach((panel) => {
      panel.hidden = panel.dataset.indexPanel !== selected;
    });
  }));

  setOpen(false);
  return {
    current,
    forecast,
    setOpen,
    destroy() {
      listeners.forEach(([element, type, handler]) => element.removeEventListener(type, handler));
      container.classList.remove("environment-panel--ready", "is-expanded");
      container.innerHTML = "";
    },
  };
}

function renderPanel(current, forecast) {
  const icon = weatherIconMarkup(current.weatherIcon, current.weatherText);
  const summaryTemperature = current.temperature === null ? "—" : current.temperatureText;
  const summaryHumidity = current.humidity === null ? "—" : current.humidityText;
  const summaryWind = current.windSpeed === null ? "—" : current.windText;
  const summaryPrecipitation = current.precipitation === null ? "—" : current.precipitationText;
  const alerts = renderAlerts(current.alerts);
  const alertDot = current.alerts.length
    ? '<span class="environment-alert-dot" aria-label="当前有环境预警"></span>'
    : "";
  return `
    <section class="environment-summary" aria-label="徐汇区当前环境">
      <div class="environment-summary__primary" aria-hidden="true">
        <div>
          <div class="environment-summary__location">${escapeHtml(current.location)}</div>
          <div class="environment-summary__condition">${icon}<span>${escapeHtml(current.weatherText)}</span></div>
        </div>
        <div class="environment-summary__temperature">${escapeHtml(summaryTemperature)}</div>
      </div>
      <div class="environment-summary__metrics" aria-hidden="true">
        ${summaryMetric("湿度", summaryHumidity)}
        ${summaryMetric("风", summaryWind)}
        ${summaryMetric("降水", summaryPrecipitation)}
        ${summaryAqiMetric(current)}
      </div>
      <button class="environment-toggle" type="button" aria-expanded="false" aria-haspopup="dialog" aria-controls="environmentDetails" aria-label="${escapeHtml(environmentToggleLabel(current, false))}">
        <span class="environment-toggle__summary">
          <span class="environment-toggle__item environment-toggle__item--weather">
            <span class="environment-toggle__icon" aria-hidden="true">${icon}</span>
            <span class="environment-toggle__label">天气</span>
            <strong>${escapeHtml(current.weatherText)}</strong>
          </span>
          <span class="environment-toggle__item environment-toggle__item--temperature">
            ${environmentIconMarkup("temperature")}
            <span class="environment-toggle__label">温度</span>
            <strong>${escapeHtml(current.temperatureText)}</strong>
          </span>
          <span class="environment-toggle__item environment-toggle__item--humidity">
            ${environmentIconMarkup("humidity")}
            <span class="environment-toggle__label">湿度</span>
            <strong>${escapeHtml(current.humidityText)}</strong>
          </span>
          ${environmentToggleAqi(current)}
        </span>
        ${alertDot}
        <svg class="environment-toggle__chevron" aria-hidden="true" focusable="false" viewBox="0 0 20 20"><path d="m6 8 4 4 4-4" /></svg>
      </button>
    </section>
    <section id="environmentDetails" class="environment-details" role="dialog" aria-label="环境详情" hidden>
      ${alerts}
      <div class="environment-tabs" role="tablist" aria-label="环境数据">
        ${tabButton("now", "现在", true)}
        ${tabButton("hourly", "24 小时", false)}
        ${tabButton("indices", "指数", false)}
      </div>
      <div class="environment-view is-active" data-environment-view="now">
        ${renderNow(current)}
      </div>
      <div class="environment-view" data-environment-view="hourly" hidden>
        ${renderHourly(forecast)}
      </div>
      <div class="environment-view" data-environment-view="indices" hidden>
        ${renderIndices(forecast.indexDays)}
      </div>
    </section>`;
}

function renderNow(current) {
  return `<div class="environment-now-grid">
    ${nowCard("天气", current.weatherText, current.temperature === null ? "" : current.temperatureText, current.weatherStatus)}
    ${nowCard("湿度", current.humidityText, "相对湿度", current.weatherStatus)}
    ${nowCard("风向风速", current.windText, "当前风况", current.weatherStatus)}
    ${nowCard("降水", current.precipitationText, "当前降水", current.weatherStatus)}
    ${nowCard("AQI", current.aqiText, current.aqi === null ? "" : current.aqiLevel, current.aqiStatus)}
  </div>`;
}

function renderHourly(forecast) {
  const availableWeather = forecast.weatherHours.filter((hour) => hour.temperature !== null);
  const weather = availableWeather.length
    ? forecast.weatherHours.map((hour) => {
      const available = hour.temperature !== null;
      const condition = available
        ? `${weatherIconMarkup(hour.weatherIcon, hour.weatherText)}<span>${escapeHtml(hour.weatherText)}</span>`
        : "";
      const precipitation = available
        ? `<span>降水 ${escapeHtml(metricText(hour.precipitationProbability, "%", hour.status))}</span>`
        : "";
      return `<article class="environment-hour">
        <time>${escapeHtml(hour.timeLabel)}</time>
        <div class="environment-hour__weather">${condition}</div>
        <strong>${available ? escapeHtml(hour.temperatureText) : "—"}</strong>
        ${precipitation}
      </article>`;
    }).join("")
    : emptyMarkup(`24 小时天气${statusText(hourlyEmptyStatus(forecast.weatherHours))}`);
  const availableAqi = forecast.aqiHours.filter((hour) => hour.aqi !== null);
  const aqi = availableAqi.length
    ? forecast.aqiHours.map((hour) => {
      const available = hour.aqi !== null;
      return `<article class="environment-aqi-point">
        <time>${escapeHtml(hour.timeLabel)}</time><strong>${available ? escapeHtml(hour.aqiText) : "—"}</strong>${
          available ? `<span>${escapeHtml(hour.level)}</span>` : ""
        }
      </article>`;
    }).join("")
    : emptyMarkup(`24 小时 AQI ${statusText(hourlyEmptyStatus(forecast.aqiHours))}`);
  return `<section aria-label="未来 24 小时天气">
      <h3>24 小时天气</h3><div class="environment-hourly">${weather}</div>
    </section>
    <section aria-label="未来 24 小时 AQI">
      <h3>24 小时 AQI</h3><div class="environment-aqi-chart">${aqi}</div>
    </section>`;
}

function renderIndices(indexDays) {
  if (!indexDays.length) return emptyMarkup();
  const switches = indexDays.map((day, index) => (
    `<button class="environment-day-button${index === 0 ? " is-active" : ""}" type="button" data-index-day="${escapeHtml(day.date)}" aria-selected="${index === 0}">${escapeHtml(day.label)}</button>`
  )).join("");
  const panels = indexDays.map((day, index) => (
    `<div class="environment-index-grid" data-index-panel="${escapeHtml(day.date)}"${index === 0 ? "" : " hidden"}>${day.indices.map((item) => (
      `<article class="environment-index-card">
        <span>${escapeHtml(item.name)}</span><strong>${escapeHtml(item.category)}</strong><p>${escapeHtml(item.text)}</p>
      </article>`
    )).join("")}</div>`
  )).join("");
  return `<div class="environment-day-switch" role="tablist" aria-label="生活指数日期">${switches}</div>${panels}`;
}

function summaryMetric(label, value) {
  return `<div class="environment-summary__metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function summaryAqiMetric(current) {
  if (current.aqi === null) return summaryMetric("AQI", "—");
  const tone = aqiTone(current.aqi);
  return `<div class="environment-summary__metric environment-summary__metric--aqi">
    <span>AQI</span>
    <strong class="environment-summary__aqi">
      <span class="environment-summary__aqi-number">${escapeHtml(current.aqiText)}</span>
      <span class="environment-summary__aqi-level environment-summary__aqi-level--${tone}">${escapeHtml(current.aqiLevel)}</span>
    </strong>
  </div>`;
}

function environmentToggleAqi(current) {
  if (current.aqi === null) {
    return `<span class="environment-toggle__item environment-toggle__item--aqi">
      ${environmentIconMarkup("aqi")}
      <span class="environment-toggle__label">AQI</span>
      <strong>${escapeHtml(current.aqiText)}</strong>
    </span>`;
  }
  const tone = aqiTone(current.aqi);
  return `<span class="environment-toggle__item environment-toggle__item--aqi">
    ${environmentIconMarkup("aqi")}
    <span class="environment-toggle__label">AQI</span>
    <strong class="environment-toggle__aqi">
      <span class="environment-toggle__aqi-number">${escapeHtml(current.aqiText)}</span>
      <span class="environment-toggle__aqi-level environment-toggle__aqi-level--${tone}">${escapeHtml(current.aqiLevel)}</span>
    </strong>
  </span>`;
}

function environmentToggleLabel(current, open) {
  const aqi = current.aqi === null
    ? current.aqiText
    : `${current.aqiText} ${current.aqiLevel}`;
  const action = open ? "收起环境详情" : "展开环境详情";
  return `当前环境：${current.weatherText}，温度 ${current.temperatureText}，湿度 ${current.humidityText}，AQI ${aqi}。${action}`;
}

function environmentIconMarkup(type) {
  const paths = {
    temperature: '<path d="M10 14.76V5a2 2 0 0 1 4 0v9.76a4 4 0 1 1-4 0Z"></path><path d="M12 9v7"></path>',
    humidity: '<path d="M12 2.7S6 9.25 6 14a6 6 0 0 0 12 0c0-4.75-6-11.3-6-11.3Z"></path><path d="M9.5 15.5c.7 1 1.55 1.5 2.5 1.5"></path>',
    aqi: '<path d="M4 8h10a2 2 0 1 0-2-2"></path><path d="M4 12h15a2 2 0 1 1-2 2"></path><path d="M4 16h7"></path>',
  };
  return `<svg class="environment-toggle__icon" data-environment-icon="${type}" aria-hidden="true" focusable="false" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[type]}</svg>`;
}

function nowCard(label, value, description, status) {
  const detail = description
    ? `<small class="environment-status" data-status="${escapeHtml(status)}">${escapeHtml(description)}</small>`
    : "";
  return `<article class="environment-now-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${detail}</article>`;
}

function tabButton(value, label, active) {
  return `<button class="environment-tab${active ? " is-active" : ""}" type="button" role="tab" data-environment-tab="${value}" aria-selected="${active}">${label}</button>`;
}

function weatherIconMarkup(icon, label) {
  return icon
    ? `<i class="qi-${escapeHtml(icon)}" aria-label="${escapeHtml(label)}"></i>`
    : "";
}

function emptyMarkup(message = "暂无数据") {
  return `<div class="environment-empty">${escapeHtml(message)}</div>`;
}

function hourlyEmptyStatus(hours) {
  return hours.some(({ status }) => status === "stale") ? "stale" : "no_data";
}

function renderAlerts(alerts) {
  if (!alerts.length) return "";
  const [primary, ...others] = alerts;
  const title = others.length ? `当前 ${alerts.length} 条气象预警` : primary.title;
  const text = others.length
    ? `${primary.title}；另有${others.map((alert) => alert.title).join("、")}`
    : primary.text;
  return `<div class="environment-alerts" role="status"><div class="environment-alert"><strong>${escapeHtml(title)}</strong>${
    text ? `<span>${escapeHtml(text)}</span>` : ""
  }</div></div>`;
}

function normalizeAlerts(alerts) {
  return (Array.isArray(alerts) ? alerts : [])
    .filter((alert) => hasDisplayValue(recordStatus(alert, alert?.values || alert)))
    .map((alert) => {
      const values = alert?.values || alert || {};
      return {
        title: String(values.title || values.summary || values.type || "天气预警"),
        text: String(values.text || values.description || ""),
        severity: String(values.level || values.severity || "warning"),
      };
    })
    .sort((left, right) => (
      (ALERT_SEVERITY_RANK[right.severity.toLowerCase()] || 0)
      - (ALERT_SEVERITY_RANK[left.severity.toLowerCase()] || 0)
    ));
}

function exposureMetric(label, record, options = {}) {
  const status = recordStatus(record, record?.value, "expires_at");
  const value = hasDisplayValue(status) ? finiteNumber(record?.value) : null;
  const rounded = value === null ? null : roundTo(value, options.digits ?? 1);
  return {
    label,
    value: rounded,
    displayValue: rounded === null ? statusText(status) : formatNumber(rounded),
    unit: rounded === null ? "" : String(record?.unit || ""),
    status,
    confidence: record?.confidence || null,
    estimated: Boolean(record?.estimated),
    riskLevel: options.risk && rounded !== null ? riskLevelName(record?.risk_level, rounded) : null,
    spatialScale: record?.spatial_scale || null,
  };
}

function emptyExposure(label) {
  return {
    label,
    value: null,
    displayValue: DISPLAY_STATUS.no_data,
    unit: "",
    status: "no_data",
    confidence: null,
    estimated: false,
    riskLevel: null,
    spatialScale: null,
  };
}

function recordStatus(record, value, expiryKey = "valid_until") {
  if (!record) return "no_data";
  if (record.status === "stale") return "stale";
  if (!["ok", "partial"].includes(record.status)) return "no_data";
  const expiresAt = record?.[expiryKey];
  if (expiresAt) {
    const expiry = Date.parse(expiresAt);
    if (Number.isFinite(expiry) && expiry <= Date.now()) return "stale";
  }
  if (!hasValue(value)) return "no_data";
  return record.status;
}

function combinedStatus(...statuses) {
  const available = statuses.filter(Boolean);
  if (!available.length || available.every((status) => status === "no_data")) return "no_data";
  if (available.some((status) => status === "stale")) return "stale";
  if (available.some((status) => status === "partial" || status === "no_data")) return "partial";
  return "ok";
}

function statusText(status) {
  return DISPLAY_STATUS[status] || (status === "partial" ? "数据更新中" : "暂无数据");
}

function hasDisplayValue(status) {
  return status === "ok" || status === "partial";
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== "";
}

function finiteNumber(value) {
  if (!hasValue(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function roundTo(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function formatNumber(value) {
  return Number.isInteger(Number(value)) ? String(Number(value)) : String(roundTo(Number(value), 1));
}

function metricText(value, unit, status) {
  const number = finiteNumber(value);
  return number === null ? statusText(status) : `${formatNumber(number)}${unit}`;
}

function windDirectionName(value) {
  const degrees = finiteNumber(value);
  if (degrees === null) return "风向更新中";
  const names = ["北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风"];
  return names[Math.round(((degrees % 360) + 360) % 360 / 45) % names.length];
}

function aqiLevel(value) {
  if (value <= 50) return "优";
  if (value <= 100) return "良";
  if (value <= 150) return "轻度污染";
  if (value <= 200) return "中度污染";
  if (value <= 300) return "重度污染";
  return "严重污染";
}

function aqiTone(value) {
  if (value <= 50) return "excellent";
  if (value <= 100) return "good";
  if (value <= 150) return "light";
  if (value <= 200) return "moderate";
  if (value <= 300) return "heavy";
  return "severe";
}

function riskLevelName(level, value) {
  const names = { low: "低", medium: "中", high: "高", very_high: "很高" };
  if (names[level]) return names[level];
  if (value < 34) return "低";
  if (value < 67) return "中";
  return "高";
}

function hourLabel(value) {
  const match = String(value || "").match(/T(\d{2}:\d{2})/);
  return match?.[1] || "--:--";
}

function forecastDates(dashboard) {
  const start = dashboardDate(dashboard);
  return DAY_LABELS.map((_, offset) => addDate(start, offset));
}

function dashboardDate(dashboard) {
  const value = dashboard?.metadata?.generated_at;
  const direct = String(value || "").match(/^\d{4}-\d{2}-\d{2}/)?.[0];
  if (direct) return direct;
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
}

function addDate(date, offset) {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]);
}
