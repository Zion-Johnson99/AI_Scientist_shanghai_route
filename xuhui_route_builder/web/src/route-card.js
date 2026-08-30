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
  const modeLabel = ROUTE_MODE_LABELS[routeRecord?.route_mode]
    || firstText(routeRecord?.tags)
    || "路线";

  return {
    routeId,
    routeName,
    labelText: String(preferredLabel || primaryLabel || modeLabel),
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
    `route-card${hasCover ? "" : " route-card--text-only"}${model.selected ? " is-selected" : ""}`,
  );
  card.dataset.routeId = model.routeId;
  card.setAttribute("data-route-id", model.routeId);
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.setAttribute("aria-current", String(Boolean(model.selected)));
  card.setAttribute("aria-label", `查看路线 ${model.routeName}`);

  if (hasCover) {
    const media = element("div", "route-card__media");
    const image = element("img", "route-card__image");
    image.setAttribute("src", model.media.cover);
    image.setAttribute("alt", model.routeName);
    image.setAttribute("loading", "lazy");
    media.append(image);
    card.append(media);
  }

  const body = element("div", "route-card__body");
  body.append(
    element("span", "route-card__label", model.labelText),
    element("strong", "route-card__name", model.routeName),
    element("span", "route-card__journey", model.journeyText),
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

function element(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}
