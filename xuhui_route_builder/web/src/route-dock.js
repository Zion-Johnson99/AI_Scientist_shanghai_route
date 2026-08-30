const MODE_LABELS = {
  walk: "步行",
  run: "跑步",
  bike: "骑行",
};

const EXPOSURE_LABELS = {
  pm25: "PM2.5",
  pollen: "花粉",
  noise: "噪声",
};

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
  return {
    routeName: properties.route_name || "已选路线",
    routeMode: properties.route_mode || "walk",
    modeLabel: MODE_LABELS[properties.route_mode] || "户外运动",
    distanceText,
    durationText,
    journeyText: `${distanceText} · ${durationText}`,
    exposures,
    waypoints: routeWaypoints(properties),
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
      waypoint_names: routeRecord.waypoint_names ?? routeFeature?.properties?.waypoint_names,
      ordered_nodes: routeRecord.ordered_nodes ?? routeFeature?.properties?.ordered_nodes,
    },
  };
}

export function createRouteDock(
  container = document.querySelector(".map-wrap"),
  { onNavigate } = {},
) {
  if (!container) {
    throw new Error("缺少地图容器，无法初始化路线信息条。");
  }

  const root = document.createElement("section");
  let activeRoute = null;
  root.className = "route-dock route-dock--detail";
  root.hidden = true;
  root.setAttribute("aria-label", "当前路线信息");
  root.innerHTML = `
    <header class="route-dock__head">
      <div class="route-dock__identity">
        <span class="route-dock__mode" data-dock-mode></span>
        <strong data-dock-route-name></strong>
      </div>
      <button class="route-dock__close" type="button" aria-label="关闭路线详情" data-dock-close>×</button>
    </header>
    <div class="route-dock__tabs" role="tablist" aria-label="路线数据切换">
      <button class="active" type="button" role="tab" aria-selected="true" data-dock-tab="overview">概览</button>
      <button type="button" role="tab" aria-selected="false" data-dock-tab="environment">环境</button>
      <button type="button" role="tab" aria-selected="false" data-dock-tab="waypoints">途经点</button>
    </div>
    <div class="route-dock__panel active" role="tabpanel" data-dock-panel="overview">
      <div class="route-dock__overview-grid">
        <div class="route-dock__metric route-dock__metric--journey">
          <span>距离 · 时间</span><strong data-dock-journey></strong>
        </div>
        <div class="route-dock__metric route-dock__metric--environment">
          <span>PM2.5</span><strong data-dock-overview-pm25></strong>
        </div>
        <div class="route-dock__metric route-dock__metric--environment">
          <span>花粉</span><strong data-dock-overview-pollen></strong>
        </div>
        <div class="route-dock__metric route-dock__metric--environment">
          <span>噪声</span><strong data-dock-overview-noise></strong>
        </div>
      </div>
      <section class="route-dock__recommendation" data-dock-recommendation hidden>
        <h3>推荐亮点</h3>
        <ul class="route-dock__bullet-list" data-dock-advantage-list></ul>
        <h3>出行建议</h3>
        <ul class="route-dock__bullet-list route-dock__bullet-list--suggestion" data-dock-suggestion-list></ul>
      </section>
    </div>
    <div class="route-dock__panel route-dock__environment" role="tabpanel" data-dock-panel="environment" hidden>
      <div class="route-dock__exposure-grid">
        ${exposureCard("pm25", "PM2.5")}
        ${exposureCard("pollen", "花粉")}
        ${exposureCard("noise", "噪声")}
      </div>
    </div>
    <div class="route-dock__panel route-dock__waypoints" role="tabpanel" data-dock-panel="waypoints" hidden>
      <ol data-dock-waypoint-list></ol>
    </div>
    <footer class="route-dock__actions">
      <button type="button" class="route-dock__navigate" data-dock-navigate>前往起点</button>
    </footer>
  `;
  container.appendChild(root);

  const tabs = [...root.querySelectorAll("[data-dock-tab]")];
  const panels = [...root.querySelectorAll("[data-dock-panel]")];
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => selectDockTab(tabs, panels, tab.dataset.dockTab));
  });
  root.querySelector("[data-dock-close]").addEventListener("click", () => {
    root.hidden = true;
  });
  root.querySelector("[data-dock-navigate]").addEventListener("click", () => {
    if (!activeRoute || !onNavigate) return;
    try {
      const pending = onNavigate(activeRoute);
      pending?.catch?.((error) => console.error("打开路线接驳失败", { error }));
    } catch (error) {
      console.error("打开路线接驳失败", { error });
    }
  });

  return {
    element: root,
    show(route, routeEnvironment, recommendationSummary = null) {
      activeRoute = route;
      const model = buildRouteDockModel(route, routeEnvironment);
      renderRouteDock(root, model, recommendationSummary);
      selectDockTab(tabs, panels, "overview");
      root.hidden = false;
    },
    hide() {
      root.hidden = true;
    },
  };
}

function renderRouteDock(root, model, recommendationSummary) {
  root.dataset.mode = model.routeMode;
  setText(root, "[data-dock-mode]", model.modeLabel);
  setText(root, "[data-dock-route-name]", model.routeName);
  setText(root, "[data-dock-journey]", model.journeyText);
  for (const [key, exposure] of Object.entries(model.exposures)) {
    setText(root, `[data-dock-overview-${key}]`, exposure.compactText);
    setText(root, `[data-dock-${key}-value]`, exposure.valueText);
    setText(root, `[data-dock-${key}-risk]`, exposure.riskLevel);
    setText(root, `[data-dock-${key}-status]`, exposure.statusLabel);
    setText(root, `[data-dock-${key}-detail]`, exposure.detail);
    root.querySelector(`[data-dock-exposure="${key}"]`).dataset.status = exposure.status;
  }

  const list = root.querySelector("[data-dock-waypoint-list]");
  list.replaceChildren();
  renderRecommendationSummary(root, recommendationSummary);
  if (!model.waypoints.length) {
    const item = document.createElement("li");
    item.className = "route-dock__empty-waypoint";
    item.textContent = "暂无明确途经点";
    list.appendChild(item);
    return;
  }
  model.waypoints.forEach((name, index) => {
    const item = document.createElement("li");
    item.innerHTML = `<span>${index + 1}</span>`;
    item.append(document.createTextNode(name));
    list.appendChild(item);
  });
}

function renderRecommendationSummary(root, summary) {
  const section = root.querySelector("[data-dock-recommendation]");
  const advantages = cleanSummaryItems(summary?.advantages, 3);
  const suggestions = cleanSummaryItems(summary?.suggestions, 2);
  section.hidden = !advantages.length && !suggestions.length;
  renderSummaryList(root.querySelector("[data-dock-advantage-list]"), advantages);
  renderSummaryList(root.querySelector("[data-dock-suggestion-list]"), suggestions);
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
  return [...new Set((Array.isArray(values) ? values : [])
    .map((value) => String(value || "").trim())
    .filter(Boolean))].slice(0, limit);
}

function buildExposureModel(key, exposure, detail) {
  const status = String(exposure?.status || "no_data");
  const displayValue = String(exposure?.displayValue || STATUS_LABELS.no_data);
  const available = status === "ok" || status === "partial";
  const riskLevel = available && exposure?.riskLevel ? String(exposure.riskLevel) : "";
  const valueText = available
    ? key === "pm25"
      ? `${displayValue} ${exposure.unit || "µg/m³"}`
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

function exposureCard(key, label) {
  return `<article class="route-dock__exposure-card" data-dock-exposure="${key}">
    <header><strong>${label}</strong><span data-dock-${key}-status></span></header>
    <div class="route-dock__exposure-reading">
      <strong data-dock-${key}-value></strong><span data-dock-${key}-risk></span>
    </div>
    <p data-dock-${key}-detail></p>
  </article>`;
}

function routeWaypoints(properties) {
  const explicit = cleanNames(properties.waypoint_names);
  if (explicit.length) {
    return explicit;
  }
  const nodes = Array.isArray(properties.ordered_nodes) ? properties.ordered_nodes.slice(1, -1) : [];
  return cleanNames(nodes.map((node) => node?.node_name || node?.name));
}

function cleanNames(values) {
  const unique = new Set();
  for (const value of Array.isArray(values) ? values : []) {
    const name = String(value || "").trim();
    if (isDisplayWaypointName(name)) {
      unique.add(name);
    }
  }
  return [...unique];
}

export function isDisplayWaypointName(value) {
  const name = String(value || "").trim();
  return Boolean(name) && !/节点\s*\d+$/i.test(name);
}

function selectDockTab(tabs, panels, selectedTab) {
  tabs.forEach((tab) => {
    const active = tab.dataset.dockTab === selectedTab;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  panels.forEach((panel) => {
    const active = panel.dataset.dockPanel === selectedTab;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function setText(root, selector, value) {
  root.querySelector(selector).textContent = value;
}
