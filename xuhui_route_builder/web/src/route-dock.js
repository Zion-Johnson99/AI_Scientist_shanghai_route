import { routeMediaFor } from "./route-media.js";

const MODE_LABELS = { walk: "步行", run: "跑步", bike: "骑行" };
const SHAPE_LABELS = {
  strict_loop: "闭环路线",
  loop: "环线路线",
  one_way: "单向路线",
  out_and_back: "折返路线",
};
const EXPOSURE_LABELS = { pm25: "PM2.5", pollen: "花粉", noise: "噪声" };
const EXPOSURE_DETAILS = {
  pm25: "PM2.5 为沿路线汇总的 1 km 网格估计值。",
  pollen: "花粉为约 1 km 网格采样形成的当天风险指数。",
  noise: "噪声为约 100 m 路段的 0–100 风险代理。",
};
const STATUS_LABELS = {
  ok: "已更新",
  partial: "估计数据",
  stale: "数据更新中",
  no_data: "暂无数据",
};

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
    buildExposureModel(key, routeEnvironment?.[key], routeEnvironment?.details?.[key]),
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
      <section class="route-dock__facts" aria-label="路线数据">
        ${factRow("时间", "duration")}
        ${factRow("距离", "distance")}
        ${factRow("路线形态", "shape")}
        ${factRow("所在片区", "region")}
      </section>
      <p class="route-dock__journey" data-dock-journey></p>
      <section class="route-dock__path" aria-label="路线节点">
        <dl class="route-dock__endpoints">
          <div><dt>起点</dt><dd data-dock-start></dd></div>
          <div><dt>终点</dt><dd data-dock-end></dd></div>
        </dl>
        <div class="route-dock__waypoints">
          <h3>途经点</h3>
          <ol data-dock-waypoint-list></ol>
        </div>
      </section>
      <section class="route-dock__exposures" aria-label="环境数据">
        <h3>沿途环境</h3>
        <div class="route-dock__exposure-list">
          ${exposureRow("pm25", "PM2.5")}
          ${exposureRow("pollen", "花粉")}
          ${exposureRow("noise", "噪声")}
        </div>
      </section>
      <section class="route-dock__highlights" data-dock-objective hidden>
        <h3>路线亮点</h3>
        <ul class="route-dock__bullet-list" data-dock-objective-list></ul>
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
    </div>
    <footer class="route-dock__actions">
      <button type="button" class="route-dock__navigate" data-dock-navigate>前往起点</button>
    </footer>`;
  container.appendChild(root);

  function closeFromUser() {
    if (root.hidden || !activeRoute) return;
    const detail = { source: activeSource, routeId: routeIdOf(activeRoute) };
    root.hidden = true;
    onClose?.(detail);
    returnFocusTo?.focus?.();
    returnFocusTo = null;
  }

  root.querySelector("[data-dock-close]").addEventListener("click", closeFromUser);
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || root.hidden) return;
    event.preventDefault();
    closeFromUser();
  });
  root.querySelector("[data-dock-navigate]").addEventListener("click", () => {
    if (!activeRoute || !onNavigate) return;
    try {
      const pending = onNavigate(activeRoute);
      pending?.catch?.((error) => console.error("打开路线接驳失败", {
        routeId: routeIdOf(activeRoute),
        error,
      }));
    } catch (error) {
      console.error("打开路线接驳失败", { routeId: routeIdOf(activeRoute), error });
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
      });
      root.hidden = false;
      root.focus?.();
    },
    hide() {
      root.hidden = true;
      returnFocusTo = null;
    },
  };
}

function renderRouteDock(root, model, detail) {
  root.dataset.mode = model.routeMode;
  root.dataset.source = detail.source;
  setText(root, "[data-dock-mode]", model.modeLabel);
  setText(root, "[data-dock-route-name]", model.routeName);
  setText(root, "[data-dock-journey]", model.journeyText);
  setText(root, "[data-dock-duration]", model.durationText);
  setText(root, "[data-dock-distance]", model.distanceText);
  setText(root, "[data-dock-shape]", model.shapeText);
  setText(root, "[data-dock-region]", model.regionText);
  setText(root, "[data-dock-start]", model.startName);
  setText(root, "[data-dock-end]", model.endName);
  renderGallery(root.querySelector("[data-dock-gallery]"), model.media, model.routeName);
  for (const [key, exposure] of Object.entries(model.exposures)) {
    setText(root, `[data-dock-${key}-value]`, exposure.valueText);
    setText(root, `[data-dock-${key}-risk]`, exposure.riskLevel);
    setText(root, `[data-dock-${key}-status]`, exposure.statusLabel);
    setText(root, `[data-dock-${key}-detail]`, exposure.detail);
    root.querySelector(`[data-dock-exposure="${key}"]`).dataset.status = exposure.status;
  }
  renderWaypointList(root.querySelector("[data-dock-waypoint-list]"), model.waypoints);
  const objective = cleanSummaryItems(
    detail.objectiveHighlights?.length ? detail.objectiveHighlights : model.objectiveHighlights,
    3,
  );
  renderSectionList(root, "[data-dock-objective]", "[data-dock-objective-list]", objective);
  renderRecommendation(root, detail);
}

function renderRecommendation(root, detail) {
  const recommendation = root.querySelector("[data-dock-recommendation]");
  const degraded = root.querySelector("[data-dock-degraded]");
  const qwenAvailable = detail.source === "recommendation" && detail.explanationSource === "qwen";
  const advantages = qwenAvailable ? cleanSummaryItems(detail.qwenAdvantages, 3) : [];
  const suggestions = qwenAvailable ? cleanSummaryItems(detail.qwenSuggestions, 2) : [];
  const advantageGroup = root.querySelector("[data-dock-advantages]");
  const suggestionGroup = root.querySelector("[data-dock-suggestions]");
  renderSummaryList(root.querySelector("[data-dock-advantage-list]"), advantages);
  renderSummaryList(root.querySelector("[data-dock-suggestion-list]"), suggestions);
  advantageGroup.hidden = !advantages.length;
  suggestionGroup.hidden = !suggestions.length;
  recommendation.hidden = !advantages.length && !suggestions.length;
  degraded.hidden = detail.source !== "recommendation" || qwenAvailable;
}

function renderGallery(container, media, routeName) {
  container.replaceChildren();
  const paths = [...new Set([...(media?.gallery || []), media?.cover].filter(Boolean))].slice(0, 3);
  container.hidden = paths.length === 0;
  paths.forEach((path, index) => {
    const image = document.createElement("img");
    image.src = path;
    image.alt = `${routeName} 路线照片 ${index + 1}`;
    image.loading = "lazy";
    container.append(image);
  });
}

function renderWaypointList(list, values) {
  list.replaceChildren();
  if (!values.length) {
    const item = document.createElement("li");
    item.className = "route-dock__empty-waypoint";
    item.textContent = "暂无明确途经点";
    list.appendChild(item);
    return;
  }
  values.forEach((name) => {
    const item = document.createElement("li");
    item.textContent = name;
    list.appendChild(item);
  });
}

function renderSectionList(root, sectionSelector, listSelector, values) {
  const section = root.querySelector(sectionSelector);
  renderSummaryList(root.querySelector(listSelector), values);
  section.hidden = !values.length;
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

function buildExposureModel(key, exposure, detail) {
  const status = String(exposure?.status || "no_data");
  const displayValue = String(exposure?.displayValue || STATUS_LABELS.no_data);
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
    statusLabel: STATUS_LABELS[status] || STATUS_LABELS.no_data,
    valueText,
    compactText: available && key !== "pm25" && riskLevel
      ? `${riskLevel} · ${displayValue}`
      : valueText,
    riskLevel,
    detail: String(detail || EXPOSURE_DETAILS[key]),
  };
}

function normalizePm25Unit(unit) {
  return String(unit || "µg/m³").replace(/^μg\//, "µg/");
}

function factRow(label, key) {
  return `<div><span>${label}</span><strong data-dock-${key}></strong></div>`;
}

function exposureRow(key, label) {
  return `<article class="route-dock__exposure-row" data-dock-exposure="${key}">
    <div class="route-dock__exposure-label"><strong>${label}</strong><span data-dock-${key}-status></span></div>
    <div class="route-dock__exposure-reading"><strong data-dock-${key}-value></strong><span data-dock-${key}-risk></span></div>
    <p data-dock-${key}-detail></p>
  </article>`;
}

function routeEndpoint(properties, role) {
  const direct = String(properties?.[`${role}_location`]?.name || "").trim();
  if (direct) return direct;
  const nodes = Array.isArray(properties?.ordered_nodes) ? properties.ordered_nodes : [];
  const node = role === "start" ? nodes[0] : nodes.at(-1);
  return String(node?.node_name || node?.name || `${role === "start" ? "起" : "终"}点待确认`);
}

function routeWaypoints(properties) {
  const explicit = cleanNames(properties.waypoint_names);
  if (explicit.length) return explicit.slice(0, 4);
  const nodes = Array.isArray(properties.ordered_nodes) ? properties.ordered_nodes.slice(1, -1) : [];
  return cleanNames(nodes.map((node) => node?.node_name || node?.name)).slice(0, 4);
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
  return Boolean(name) && !/节点\s*\d+$/i.test(name);
}

function routeIdOf(route) {
  return String(route?.properties?.route_id || route?.route_id || "");
}

function setText(root, selector, value) {
  root.querySelector(selector).textContent = value;
}
