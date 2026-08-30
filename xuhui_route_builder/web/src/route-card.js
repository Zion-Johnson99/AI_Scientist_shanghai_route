import { routeMediaFor } from "./route-media.js";

const ROUTE_MODE_LABELS = {
  walk: "步行",
  run: "跑步",
  bike: "骑行",
};

export function routeCardModel(route, {
  environment = null,
  preferredLabel = "",
  selected = false,
  mediaMap,
} = {}) {
  const routeRecord = routeRecordOf(route);
  const routeId = String(routeRecord?.route_id || "").trim();
  if (!routeId) {
    throw new Error("路线卡缺少 route_id。");
  }
  const routeName = String(routeRecord?.route_name || "未命名路线").trim() || "未命名路线";
  const durationText = formatDuration(routeRecord?.duration_min);
  const distanceText = formatDistance(routeRecord?.distance_m ?? routeRecord?.actual_distance_m);
  const pm25Text = formatPm25(pm25MetricOf(route, environment));
  const primaryLabel = Number(route?.final_rank) === 1 ? "首选" : "";
  const rankLabel = String(preferredLabel || primaryLabel).trim();
  const mode = normalizeRouteMode(routeRecord?.route_mode);
  const modeLabel = ROUTE_MODE_LABELS[routeRecord?.route_mode]
    || firstText(routeRecord?.tags)
    || "路线";

  return {
    routeId,
    routeName,
    labelText: rankLabel || modeLabel,
    rankLabel,
    mode,
    modeLabel,
    durationText,
    distanceText,
    pm25Text,
    journeyText: `${durationText} · ${distanceText} · ${pm25Text}`,
    media: routeMediaFor(routeId, mediaMap),
    selected: Boolean(selected),
  };
}

export function createRouteCard(model, { onSelect, onPreview } = {}) {
  if (!model?.routeId) {
    throw new Error("路线卡模型缺少 routeId。");
  }
  const hasCover = Boolean(model.media?.cover);
  const card = element(
    "article",
    `route-card${hasCover ? " route-card--has-cover" : " route-card--placeholder"}${model.selected ? " is-selected" : ""}`,
  );
  card.dataset.routeId = model.routeId;
  card.setAttribute("data-route-id", model.routeId);
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.setAttribute("aria-current", String(Boolean(model.selected)));
  card.setAttribute("aria-label", `查看路线 ${model.routeName}`);

  const media = element("div", "route-card__media");
  if (hasCover) {
    const image = element("img", "route-card__image");
    image.setAttribute("src", model.media.cover);
    image.setAttribute("alt", model.routeName);
    image.setAttribute("loading", "lazy");
    image.addEventListener("error", () => {
      media.className += " route-card__media--placeholder";
      media.replaceChildren(createMediaPlaceholder());
    });
    media.append(image);
  } else {
    media.className += " route-card__media--placeholder";
    media.append(createMediaPlaceholder());
  }
  card.append(media);

  const body = element("div", "route-card__body");
  const topline = element("div", "route-card__topline");
  if (model.rankLabel) {
    topline.append(element("span", "route-card__rank", model.rankLabel));
  }
  const mode = element("span", "route-card__mode");
  mode.append(createSportIcon(model.mode), element("span", "route-card__mode-label", model.modeLabel));
  topline.append(mode);

  const metrics = element("div", "route-card__metrics");
  body.append(
    topline,
    element("strong", "route-card__name", model.routeName),
    metrics,
  );
  metrics.append(
    createMetric("duration", model.durationText),
    element("span", "route-card__metric-separator", " · "),
    createMetric("distance", model.distanceText),
    element("span", "route-card__metric-separator", " · "),
    createMetric("pm25", model.pm25Text, createAirIcon()),
  );
  card.append(body);

  const select = () => onSelect?.(model.routeId, model);
  card.addEventListener("click", select);
  card.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key) || event.repeat) return;
    event.preventDefault();
    select();
  });
  card.addEventListener("mouseenter", () => onPreview?.(model.routeId, model));
  card.addEventListener("mouseleave", () => onPreview?.(null, model));
  card.addEventListener("focus", () => onPreview?.(model.routeId, model));
  card.addEventListener("blur", () => onPreview?.(null, model));
  return card;
}

function createMetric(name, text, icon = null) {
  const metric = element("span", `route-card__metric route-card__metric--${name}`);
  if (icon) metric.append(icon);
  metric.append(element("span", "route-card__metric-text", text));
  return metric;
}

function createSportIcon(mode) {
  const paths = {
    walk: '<circle cx="10.8" cy="3.3" r="1.6"/><path d="m9.8 6.1-2 3.5 2.7 2.1-1.7 5.1M10 7l3 2.1 2.1-.2M10.5 11.7l3.4 4.5"/>',
    run: '<circle cx="12.7" cy="3" r="1.5"/><path d="m9.3 6.2 3.1 1.6 2.5 2.2M11.8 7.6l-2.3 3.7-3.4 1.2M9.6 11.2l3.6 1.4 2.2 3.8M9.6 11.4l-2 4.8"/>',
    bike: '<circle cx="5.1" cy="13.4" r="3.1"/><circle cx="14.9" cy="13.4" r="3.1"/><path d="m5.1 13.4 3.1-5.5h3.2l3.5 5.5M8.2 7.9l3.2 5.5H5.1M10.4 5.5h2.3M11.4 13.4l2.3-5.5"/>',
  };
  const icon = element("span", `route-card__sport-icon route-card__sport-icon--${mode || "route"}`);
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = `<svg viewBox="0 0 20 20" focusable="false">${paths[mode] || '<path d="M3 14.5 7.5 10l3 2.8L16.5 6M14 6h2.5v2.5"/>'}</svg>`;
  return icon;
}

function createAirIcon() {
  const icon = element("span", "route-card__air-icon");
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML = '<svg viewBox="0 0 18 18" focusable="false"><circle cx="4" cy="6" r="1.3"/><circle cx="8.6" cy="4.2" r="1"/><circle cx="12.5" cy="7.2" r="1.5"/><path d="M3 11.4c2.5-1.4 4.7-1.4 6.6 0 1.6 1.2 3.4 1.2 5.4.2"/></svg>';
  return icon;
}

function createMediaPlaceholder() {
  const placeholder = element("span", "route-card__placeholder");
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", "路线图片待补充");
  placeholder.innerHTML = '<svg viewBox="0 0 52 52" focusable="false" aria-hidden="true"><circle cx="36" cy="15" r="4"/><path d="M8 39.5 19.5 26l7 7 5-5 12.5 11.5M8 10.5h36v31H8z"/></svg>';
  return placeholder;
}

function routeRecordOf(route) {
  if (route?.type === "Feature") return route.properties;
  return route?.route?.route || route?.route || route;
}

function pm25MetricOf(route, environment) {
  return environment?.pm25
    || environment?.pm2_5
    || route?.route?.environment_summary?.pm2_5
    || route?.environment_summary?.pm2_5
    || null;
}

function formatDuration(value) {
  const duration = Number(value);
  return Number.isFinite(duration) && duration > 0 ? `${Math.round(duration)} 分钟` : "时间待确认";
}

function formatDistance(value) {
  const distance = Number(value);
  return Number.isFinite(distance) && distance > 0 ? `${(distance / 1000).toFixed(1)} km` : "距离待确认";
}

function formatPm25(metric) {
  if (metric?.status === "stale" || metric?.displayValue === "数据更新中") {
    return "PM2.5 数据更新中";
  }
  const value = Number(metric?.value ?? metric?.displayValue);
  if (!Number.isFinite(value)) {
    return "PM2.5 暂无数据";
  }
  const displayValue = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `PM2.5 ${displayValue} µg/m³`;
}

function firstText(values) {
  return (values || []).map((value) => String(value || "").trim()).find(Boolean) || "";
}

function normalizeRouteMode(value) {
  const mode = String(value || "").trim();
  return Object.hasOwn(ROUTE_MODE_LABELS, mode) ? mode : "";
}

function element(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}
