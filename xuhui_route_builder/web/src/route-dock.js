import { routeMediaFor } from "./route-media.js?v=20260831-ui-35";

const MODE_LABELS = { walk: "步行", run: "跑步", bike: "骑行" };
const SHAPE_LABELS = {
  strict_loop: "闭环路线",
  loop: "环线路线",
  one_way: "单向路线",
  out_and_back: "折返路线",
};
const EXPOSURE_LABELS = { pm25: "PM2.5", pollen: "花粉", noise: "噪声" };
const EXPOSURE_DETAILS = {
  pm25: "PM2.5：沿路线汇总的 1 km 网格值。",
  pollen: "花粉为约 1 km 网格采样形成的当天风险指数。",
  noise: "噪声：沿路线分段汇总的 0–100 风险指数。",
};
const DATA_STATE_TEXT = {
  stale: "数据更新中",
  no_data: "暂无数据",
};
const HOUR_MS = 60 * 60 * 1000;
const FORECAST_POINT_COUNT = 4;
const KEY_POI_TYPES = new Set(["toilet", "convenience", "coffee", "park_gate"]);

export function buildRouteDockModel(route, routeEnvironment) {
  const properties = route?.properties || route || {};
  const distance = Number(properties.distance_m);
  const duration = Number(properties.duration_min);
  const distanceText = Number.isFinite(distance) && distance > 0
    ? `${(distance / 1000).toFixed(1)} km`
    : "距离待确认";
  const durationText = Number.isFinite(duration) && duration > 0
    ? `${Math.round(duration)} 分钟`
    : "时间待确认";
  const exposures = Object.fromEntries(Object.keys(EXPOSURE_LABELS).map((key) => [
    key,
    buildExposureModel(key, routeEnvironment?.[key]),
  ]));
  const routeId = String(properties.route_id || "");
  return {
    routeId,
    routeName: properties.route_name || "已选路线",
    routeMode: properties.route_mode || "walk",
    modeLabel: MODE_LABELS[properties.route_mode] || "户外运动",
    distanceText,
    durationText,
    journeyText: `${distanceText} · ${durationText}`,
    shapeText: SHAPE_LABELS[properties.route_shape] || "路线形态待确认",
    regionText: String(properties.region_zone || properties.area_name || "所在片区待确认"),
    startName: routeEndpoint(properties, "start"),
    endName: routeEndpoint(properties, "end"),
    exposures,
    waypoints: routeWaypoints(properties),
    objectiveHighlights: buildObjectiveHighlights(properties),
    media: routeMediaFor(routeId),
  };
}

export function buildRouteDockSource(routeFeature, recommendationRoute) {
  const routeRecord = recommendationRoute?.source?.route?.route;
  if (!routeRecord) return routeFeature;
  return {
    ...routeFeature,
    properties: {
      ...(routeFeature?.properties || {}),
      distance_m: routeRecord.distance_m ?? routeFeature?.properties?.distance_m,
      duration_min: routeRecord.duration_min ?? routeFeature?.properties?.duration_min,
      route_shape: routeRecord.route_shape ?? routeFeature?.properties?.route_shape,
      region_zone: routeRecord.region_zone ?? routeFeature?.properties?.region_zone,
      start_location: routeRecord.start_location ?? routeFeature?.properties?.start_location,
      end_location: routeRecord.end_location ?? routeFeature?.properties?.end_location,
      waypoint_names: routeRecord.waypoint_names ?? routeFeature?.properties?.waypoint_names,
      ordered_nodes: routeRecord.ordered_nodes ?? routeFeature?.properties?.ordered_nodes,
      tags: routeRecord.tags ?? routeFeature?.properties?.tags,
      nearby_pois: routeRecord.nearby_pois ?? routeFeature?.properties?.nearby_pois,
    },
  };
}

export function buildRouteForecastModel(dashboard, targetTime, now = () => new Date()) {
  const startTime = resolveForecastStart(targetTime, now);
  const weatherRecords = [dashboard?.current?.weather, ...(dashboard?.forecast?.weather_hourly || [])]
    .filter(Boolean);
  const aqiRecords = [dashboard?.current?.aqi, ...(dashboard?.forecast?.aqi_hourly || [])]
    .filter(Boolean);
  const points = Array.from({ length: FORECAST_POINT_COUNT }, (_, index) => {
    const time = new Date(startTime.valueOf() + index * HOUR_MS);
    const weather = nearestHourlyRecord(weatherRecords, time);
    const aqi = nearestHourlyRecord(aqiRecords, time);
    const temperature = availableNumber(weather, "temperature_c");
    const precipitationProbability = availableNumber(weather, "precipitation_probability_pct");
    const precipitation = availableNumber(weather, "precipitation_mm");
    const aqiValue = availableNumber(aqi, "aqi");
    return {
      time: time.toISOString(),
      timeLabel: formatHour(time),
      weatherText: availableText(weather, "weather_text") || "天气暂无",
      temperatureText: temperature === null ? "—" : `${formatNumber(temperature)}°`,
      precipitationText: precipitationProbability !== null
        ? `降水 ${formatNumber(precipitationProbability)}%`
        : precipitation !== null ? `降水 ${formatNumber(precipitation)} mm` : "降水 —",
      aqiText: aqiValue === null ? "AQI —" : `AQI ${formatNumber(aqiValue)} · ${aqiLevel(aqiValue)}`,
    };
  });
  return { startTime: startTime.toISOString(), points };
}

export function buildObjectiveHighlights(route) {
  const properties = route?.properties || route || {};
  const highlights = [];
  const shape = SHAPE_LABELS[properties.route_shape];
  if (shape) highlights.push(`路线形态：${shape}`);
  const tags = cleanNames(properties.tags).slice(0, 3);
  if (tags.length) highlights.push(`路线标签：${tags.join("、")}`);
  const verifiedPois = cleanNames((properties.nearby_pois || [])
    .filter((poi) => poi?.verification_status === "verified" && poi?.route_relation === "along_route")
    .map((poi) => poi?.poi_name))
    .slice(0, 3);
  if (verifiedPois.length) highlights.push(`沿途已核验：${verifiedPois.join("、")}`);
  return highlights.slice(0, 3);
}

export function createRouteDock(
  container = document.querySelector(".map-wrap"),
  { onNavigate, onClose } = {},
) {
  if (!container) throw new Error("缺少地图容器，无法初始化路线详情。");

  const root = document.createElement("section");
  let activeRoute = null;
  let activeSource = "browse";
  let returnFocusTo = null;
  let navigationPending = false;
  root.className = "route-dock route-dock--detail";
  root.hidden = true;
  root.tabIndex = -1;
  root.setAttribute("aria-label", "当前路线详情");
  root.innerHTML = `
    <div class="route-dock__scroll">
      <div class="route-dock__gallery" data-dock-gallery aria-label="路线图片"></div>
      <header class="route-dock__head">
        <div class="route-dock__identity">
          <span class="route-dock__mode" data-dock-mode></span>
          <strong data-dock-route-name></strong>
        </div>
        <button class="route-dock__close" type="button" aria-label="关闭路线详情" data-dock-close>×</button>
      </header>
      <section class="route-dock__metrics" aria-label="路线核心数据">
        ${metricItem("⏱", "duration", "时间")}
        ${metricItem("↔", "distance", "距离")}
        ${metricItem("◌", "pm25-core", "PM2.5")}
      </section>
      <section class="route-dock__exposures" aria-label="环境数据">
        <h3>沿途环境</h3>
        <div class="route-dock__exposure-list">
          ${exposureRow("pm25", "PM2.5")}
          ${exposureRow("pollen", "花粉")}
          ${exposureRow("noise", "噪声")}
        </div>
      </section>
      <section class="route-dock__forecast" aria-label="未来三小时环境">
        <h3>未来 3 小时</h3>
        <div class="route-dock__forecast-list" data-dock-forecast-list></div>
      </section>
      <section class="route-dock__overview" aria-label="路线概览">
        <h3>Overview</h3>
        <ol class="route-dock__overview-list" data-dock-overview-list></ol>
      </section>
      <section class="route-dock__highlights" data-dock-objective hidden>
        <h3>路线亮点</h3>
        <p data-dock-objective-text></p>
      </section>
      <p class="route-dock__degraded" data-dock-degraded role="status" hidden>千问解释暂未返回，当前展示已验证的客观路线信息。</p>
      <section class="route-dock__recommendation" data-dock-recommendation hidden>
        <div data-dock-advantages hidden>
          <h3>推荐优点</h3>
          <ul class="route-dock__bullet-list" data-dock-advantage-list></ul>
        </div>
        <div data-dock-suggestions hidden>
          <h3>出行建议</h3>
          <ul class="route-dock__bullet-list route-dock__bullet-list--suggestion" data-dock-suggestion-list></ul>
        </div>
      </section>
      <div class="route-dock__environment-notes" aria-label="环境数据说明">
        <p data-dock-pm25-detail></p>
        <p data-dock-pollen-detail></p>
        <p data-dock-noise-detail></p>
      </div>
    </div>
    <footer class="route-dock__actions">
      <button type="button" class="route-dock__navigate" data-dock-navigate>前往起点</button>
    </footer>`;
  container.appendChild(root);

  function closeFromUser() {
    if (root.hidden || !activeRoute) return;
    const detail = { source: activeSource, routeId: routeIdOf(activeRoute) };
    const focusTarget = returnFocusTo;
    root.hidden = true;
    activeRoute = null;
    returnFocusTo = null;
    onClose?.(detail);
    focusTarget?.focus?.();
  }

  root.querySelector("[data-dock-close]").addEventListener("click", closeFromUser);
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || root.hidden) return;
    event.preventDefault();
    closeFromUser();
  });
  const navigateButton = root.querySelector("[data-dock-navigate]");
  navigateButton.addEventListener("click", async () => {
    if (!activeRoute || !onNavigate || navigationPending) return;
    const route = activeRoute;
    const routeId = routeIdOf(route);
    navigationPending = true;
    navigateButton.disabled = true;
    navigateButton.setAttribute("aria-busy", "true");
    navigateButton.textContent = "正在规划…";
    let failed = false;
    try {
      await onNavigate(route);
    } catch (error) {
      failed = true;
      console.error("启动路线导航失败", {
        routeId,
        error,
      });
    } finally {
      navigationPending = false;
      navigateButton.disabled = false;
      navigateButton.setAttribute("aria-busy", "false");
      navigateButton.textContent = failed ? "重试前往起点" : "前往起点";
    }
  });

  return {
    element: root,
    show({
      route,
      environment,
      source,
      objectiveHighlights,
      qwenAdvantages,
      qwenSuggestions,
      explanationSource,
      dashboard,
      targetTime,
    } = {}) {
      if (!route) throw new Error("缺少路线数据，无法打开路线详情。");
      activeRoute = route;
      activeSource = source === "recommendation" ? "recommendation" : "browse";
      returnFocusTo = document.activeElement || null;
      renderRouteDock(root, buildRouteDockModel(route, environment), {
        source: activeSource,
        objectiveHighlights,
        qwenAdvantages,
        qwenSuggestions,
        explanationSource,
        forecast: buildRouteForecastModel(dashboard, targetTime),
      });
      root.hidden = false;
      root.focus?.();
    },
    hide() {
      root.hidden = true;
      activeRoute = null;
      returnFocusTo = null;
    },
    dismiss: closeFromUser,
  };
}

function renderRouteDock(root, model, detail) {
  root.dataset.mode = model.routeMode;
  root.dataset.source = detail.source;
  setText(root, "[data-dock-mode]", model.modeLabel);
  setText(root, "[data-dock-route-name]", model.routeName);
  setText(root, "[data-dock-duration]", model.durationText);
  setText(root, "[data-dock-distance]", model.distanceText);
  setText(root, "[data-dock-pm25-core]", model.exposures.pm25.compactText);
  renderGallery(root.querySelector("[data-dock-gallery]"), model.media, model.routeName);
  for (const [key, exposure] of Object.entries(model.exposures)) {
    setText(root, `[data-dock-${key}-value]`, exposure.valueText);
    setText(root, `[data-dock-${key}-risk]`, exposure.riskLevel);
    setText(root, `[data-dock-${key}-detail]`, exposure.detail);
    root.querySelector(`[data-dock-exposure="${key}"]`).dataset.status = exposure.status;
  }
  renderForecast(root.querySelector("[data-dock-forecast-list]"), detail.forecast);
  renderOverview(root.querySelector("[data-dock-overview-list]"), model);
  const objective = cleanSummaryItems(
    detail.objectiveHighlights?.length ? detail.objectiveHighlights : model.objectiveHighlights,
    1,
  );
  const objectiveSection = root.querySelector("[data-dock-objective]");
  setText(root, "[data-dock-objective-text]", objective[0] || "");
  objectiveSection.hidden = objective.length === 0;
  renderRecommendation(root, detail);
}

function renderRecommendation(root, detail) {
  const recommendation = root.querySelector("[data-dock-recommendation]");
  const degraded = root.querySelector("[data-dock-degraded]");
  const qwenAvailable = detail.source === "recommendation" && detail.explanationSource === "qwen";
  const explanationDegraded = detail.source === "recommendation"
    && ["degraded", "python_fallback"].includes(detail.explanationSource);
  const advantages = qwenAvailable ? cleanSummaryItems(detail.qwenAdvantages, 3) : [];
  const suggestions = qwenAvailable ? cleanSummaryItems(detail.qwenSuggestions, 2) : [];
  const advantageGroup = root.querySelector("[data-dock-advantages]");
  const suggestionGroup = root.querySelector("[data-dock-suggestions]");
  renderSummaryList(root.querySelector("[data-dock-advantage-list]"), advantages);
  renderSummaryList(root.querySelector("[data-dock-suggestion-list]"), suggestions);
  advantageGroup.hidden = !advantages.length;
  suggestionGroup.hidden = !suggestions.length;
  recommendation.hidden = !advantages.length && !suggestions.length;
  degraded.hidden = !explanationDegraded;
}

function renderGallery(container, media, routeName) {
  container.replaceChildren();
  const paths = [media?.cover, ...(media?.gallery || [])].slice(0, 3);
  container.hidden = false;
  Array.from({ length: 3 }, (_, index) => {
    const path = paths[index];
    if (path) {
      const image = document.createElement("img");
      image.src = path;
      image.alt = `${routeName} 路线照片 ${index + 1}`;
      image.loading = "lazy";
      image.addEventListener("error", () => image.replaceWith(galleryPlaceholder()));
      return image;
    }
    return galleryPlaceholder();
  }).forEach((item) => container.append(item));
}

function galleryPlaceholder() {
  const placeholder = document.createElement("div");
  placeholder.className = "route-dock__gallery-placeholder";
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", "路线图片待补充");
  placeholder.innerHTML = '<svg aria-hidden="true" viewBox="0 0 48 48"><circle cx="33" cy="15" r="3.5"/><path d="M8 36.5 18.5 25l6.5 6 5-5 10 10.5M8 10.5h32v28H8z"/></svg>';
  return placeholder;
}

function renderOverview(list, model) {
  list.replaceChildren();
  const endpointNames = new Set([model.startName, model.endName].map(normalizeOverviewName));
  const seenWaypoints = new Set();
  const waypoints = model.waypoints.filter((name) => {
    const normalized = normalizeOverviewName(name);
    if (!normalized || endpointNames.has(normalized) || seenWaypoints.has(normalized)) return false;
    seenWaypoints.add(normalized);
    return true;
  });
  const nodes = [
    { marker: "A", label: "起点", name: model.startName },
    ...waypoints.map((name, index) => ({ marker: String(index + 1), label: "途经点", name })),
    { marker: "B", label: "终点", name: model.endName },
  ];
  nodes.forEach(({ marker, label, name }) => {
    const item = document.createElement("li");
    item.className = "route-dock__overview-item";
    const markerElement = document.createElement("span");
    markerElement.className = "route-dock__overview-marker";
    markerElement.textContent = marker;
    const content = document.createElement("span");
    content.className = "route-dock__overview-content";
    const labelElement = document.createElement("small");
    labelElement.textContent = label;
    const nameElement = document.createElement("strong");
    nameElement.textContent = name;
    content.append(labelElement, nameElement);
    item.append(markerElement, content);
    list.append(item);
  });
}

function normalizeOverviewName(value) {
  return String(value || "").trim().toLocaleLowerCase("zh-CN");
}

function renderForecast(container, forecast) {
  container.replaceChildren();
  (forecast?.points || []).forEach((point) => {
    const item = document.createElement("article");
    item.className = "route-dock__forecast-point";
    const time = document.createElement("time");
    time.dateTime = point.time;
    time.textContent = point.timeLabel;
    const weather = document.createElement("strong");
    weather.textContent = `${point.weatherText} ${point.temperatureText}`;
    const precipitation = document.createElement("span");
    precipitation.textContent = point.precipitationText;
    const aqi = document.createElement("span");
    aqi.textContent = point.aqiText;
    item.append(time, weather, precipitation, aqi);
    container.append(item);
  });
}

function renderSummaryList(list, values) {
  list.replaceChildren();
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  });
}

function cleanSummaryItems(values, limit) {
  return cleanNames(values).slice(0, limit);
}

function buildExposureModel(key, exposure) {
  const status = String(exposure?.status || "no_data");
  const displayValue = String(exposure?.displayValue || DATA_STATE_TEXT.no_data);
  const available = status === "ok" || status === "partial";
  const riskLevel = available && exposure?.riskLevel ? String(exposure.riskLevel) : "";
  const valueText = available
    ? key === "pm25"
      ? `${displayValue} ${normalizePm25Unit(exposure.unit)}`
      : `${displayValue} / 100`
    : displayValue;
  return {
    label: EXPOSURE_LABELS[key],
    status,
    valueText,
    compactText: available && key !== "pm25" && riskLevel
      ? `${riskLevel} · ${displayValue}`
      : valueText,
    riskLevel,
    detail: EXPOSURE_DETAILS[key],
  };
}

function normalizePm25Unit(unit) {
  return String(unit || "µg/m³").replace(/^μg\//, "µg/");
}

function metricItem(icon, key, label) {
  return `<span class="route-dock__metric" title="${label}"><i aria-hidden="true">${icon}</i><strong data-dock-${key}></strong></span>`;
}

function exposureRow(key, label) {
  return `<article class="route-dock__exposure-row" data-dock-exposure="${key}">
    <div class="route-dock__exposure-label"><strong>${label}</strong></div>
    <div class="route-dock__exposure-reading"><strong data-dock-${key}-value></strong><span data-dock-${key}-risk></span></div>
  </article>`;
}

function resolveForecastStart(targetTime, now) {
  const current = now();
  const fallback = current instanceof Date && Number.isFinite(current.valueOf()) ? current : new Date();
  const mode = targetTime?.target_time ?? targetTime;
  if (mode === "plus_2h") return new Date(fallback.valueOf() + 2 * HOUR_MS);
  if (mode === "custom") {
    const custom = new Date(targetTime?.custom_time || "");
    return Number.isFinite(custom.valueOf()) ? custom : fallback;
  }
  if (!mode || mode === "now") return fallback;
  const parsed = new Date(mode);
  return Number.isFinite(parsed.valueOf()) ? parsed : fallback;
}

function nearestHourlyRecord(records, target) {
  let nearest = null;
  let distance = Number.POSITIVE_INFINITY;
  records.forEach((record) => {
    const businessTime = new Date(record?.business_time || "");
    const nextDistance = Math.abs(businessTime.valueOf() - target.valueOf());
    if (Number.isFinite(nextDistance) && nextDistance < distance) {
      nearest = record;
      distance = nextDistance;
    }
  });
  return distance <= HOUR_MS ? nearest : null;
}

function availableNumber(record, key) {
  if (!["ok", "partial"].includes(record?.status)) return null;
  const rawValue = record?.values?.[key];
  if (rawValue === null || rawValue === undefined || rawValue === "") return null;
  const value = Number(rawValue);
  return Number.isFinite(value) ? value : null;
}

function availableText(record, key) {
  if (!["ok", "partial"].includes(record?.status)) return "";
  return String(record?.values?.[key] || "").trim();
}

function formatHour(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(value);
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function aqiLevel(value) {
  if (value <= 50) return "优";
  if (value <= 100) return "良";
  if (value <= 150) return "轻度污染";
  if (value <= 200) return "中度污染";
  if (value <= 300) return "重度污染";
  return "严重污染";
}

function routeEndpoint(properties, role) {
  const direct = String(properties?.[`${role}_location`]?.name || "").trim();
  if (direct) return direct;
  const nodes = Array.isArray(properties?.ordered_nodes) ? properties.ordered_nodes : [];
  const node = role === "start" ? nodes[0] : nodes.at(-1);
  return String(node?.node_name || node?.name || `${role === "start" ? "起" : "终"}点待确认`);
}

function routeWaypoints(properties) {
  return routeSemanticWaypoints(properties).map(({ name }) => name);
}

export function routeSemanticWaypoints(
  properties,
  { pois = { features: [] }, selectedPreferences = [], requireCoordinates = false } = {},
) {
  const result = [];
  const seenNames = new Set([
    normalizeOverviewName(routeEndpoint(properties, "start")),
    normalizeOverviewName(routeEndpoint(properties, "end")),
  ]);
  const poiById = new Map((pois?.features || []).map((poi) => [poi?.properties?.poi_id, poi]));
  const preferenceOrder = new Map(selectedPreferences.map((preference, index) => [preference, index]));
  const nearbyPois = [...(properties?.nearby_pois || [])]
    .filter((poi) => poi?.route_relation === "along_route")
    .filter((poi) => poi?.verification_status === "verified")
    .filter((poi) => KEY_POI_TYPES.has(poi?.poi_type))
    .sort((left, right) => {
      const fallbackRank = preferenceOrder.size;
      const leftRank = preferenceOrder.get(left.poi_type) ?? fallbackRank;
      const rightRank = preferenceOrder.get(right.poi_type) ?? fallbackRank;
      return leftRank - rightRank || Number(left.distance_m || 0) - Number(right.distance_m || 0);
    });

  for (const related of nearbyPois) {
    const feature = poiById.get(related.poi_id);
    const position = validPosition(feature?.geometry?.coordinates);
    const name = String(feature?.properties?.poi_name || related.poi_name || "").trim();
    const normalized = normalizeOverviewName(name);
    if (!normalized || seenNames.has(normalized)) continue;
    if (requireCoordinates && !position) continue;
    seenNames.add(normalized);
    result.push({ name, poiType: related.poi_type, position });
    if (result.length >= 3) return result;
  }

  const nodes = Array.isArray(properties?.ordered_nodes) ? properties.ordered_nodes.slice(1, -1) : [];
  for (const node of nodes) {
    const name = String(node?.node_name || node?.name || "").trim();
    const normalized = normalizeOverviewName(name);
    const position = validPosition([node?.lng_gcj02, node?.lat_gcj02]);
    if (!isDisplayWaypointName(name) || !position || seenNames.has(normalized)) continue;
    seenNames.add(normalized);
    result.push({ name, poiType: null, position });
    if (result.length >= 3) break;
  }
  return result;
}

function validPosition(value) {
  if (!Array.isArray(value) || value.length < 2) return null;
  const position = [Number(value[0]), Number(value[1])];
  return position.every(Number.isFinite) ? position : null;
}

function cleanNames(values) {
  const unique = new Set();
  for (const value of Array.isArray(values) ? values : []) {
    const name = String(value || "").trim();
    if (isDisplayWaypointName(name)) unique.add(name);
  }
  return [...unique];
}

export function isDisplayWaypointName(value) {
  const name = String(value || "").trim();
  return Boolean(name)
    && !/^(?:路线)?(?:起点|终点|起终点)$/i.test(name)
    && !/(?:实测)?节点\s*\d+$/i.test(name);
}

function routeIdOf(route) {
  return String(route?.properties?.route_id || route?.route_id || "");
}

function setText(root, selector, value) {
  root.querySelector(selector).textContent = value;
}
