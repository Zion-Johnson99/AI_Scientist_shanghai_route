const MODE_LABELS = {
  walk: "步行",
  run: "跑步",
  bike: "骑行",
};

export function buildRouteDockModel(route) {
  const properties = route?.properties || route || {};
  const distance = Number(properties.distance_m);
  const duration = Number(properties.duration_min);
  return {
    routeName: properties.route_name || "已选路线",
    routeMode: properties.route_mode || "walk",
    modeLabel: MODE_LABELS[properties.route_mode] || "户外运动",
    distanceText: Number.isFinite(distance) && distance > 0 ? `${(distance / 1000).toFixed(1)} km` : "距离待确认",
    durationText: Number.isFinite(duration) && duration > 0 ? `${Math.round(duration)} 分钟` : "时间待确认",
    environmentStatus: "数据待接入",
    environmentAssessment: "待评估",
    waypoints: routeWaypoints(properties),
  };
}

export function createRouteDock(container = document.querySelector(".map-wrap")) {
  if (!container) {
    throw new Error("缺少地图容器，无法初始化路线信息条。");
  }

  const root = document.createElement("section");
  root.className = "route-dock";
  root.hidden = true;
  root.setAttribute("aria-label", "当前路线信息");
  root.innerHTML = `
    <header class="route-dock__head">
      <div class="route-dock__identity">
        <span class="route-dock__mode" data-dock-mode></span>
        <strong data-dock-route-name></strong>
      </div>
      <div class="route-dock__tabs" role="tablist" aria-label="路线数据切换">
        <button class="active" type="button" role="tab" aria-selected="true" data-dock-tab="overview">概览</button>
        <button type="button" role="tab" aria-selected="false" data-dock-tab="environment">环境</button>
        <button type="button" role="tab" aria-selected="false" data-dock-tab="waypoints">途经点</button>
      </div>
    </header>
    <div class="route-dock__panel active" role="tabpanel" data-dock-panel="overview">
      <div class="route-dock__metric route-dock__metric--mode">
        <span>运动类型</span><strong data-dock-overview-mode></strong>
      </div>
      <div class="route-dock__metric route-dock__metric--distance">
        <span>全程距离</span><strong data-dock-distance></strong>
      </div>
      <div class="route-dock__metric route-dock__metric--duration">
        <span>预计时间</span><strong data-dock-duration></strong>
      </div>
      <div class="route-dock__metric route-dock__metric--environment">
        <span>环境状况</span><strong>待评估</strong>
      </div>
    </div>
    <div class="route-dock__panel route-dock__environment" role="tabpanel" data-dock-panel="environment" hidden>
      <span class="route-dock__status-dot" aria-hidden="true"></span>
      <div><strong data-dock-environment-status></strong><p>空气质量、噪声、天气等环境指标接入后显示</p></div>
      <span class="route-dock__pending" data-dock-environment-assessment></span>
    </div>
    <div class="route-dock__panel route-dock__waypoints" role="tabpanel" data-dock-panel="waypoints" hidden>
      <ol data-dock-waypoint-list></ol>
    </div>
  `;
  container.appendChild(root);

  const tabs = [...root.querySelectorAll("[data-dock-tab]")];
  const panels = [...root.querySelectorAll("[data-dock-panel]")];
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => selectDockTab(tabs, panels, tab.dataset.dockTab));
  });

  return {
    element: root,
    show(route) {
      const model = buildRouteDockModel(route);
      renderRouteDock(root, model);
      root.hidden = false;
    },
    hide() {
      root.hidden = true;
    },
  };
}

function renderRouteDock(root, model) {
  root.dataset.mode = model.routeMode;
  setText(root, "[data-dock-mode]", model.modeLabel);
  setText(root, "[data-dock-route-name]", model.routeName);
  setText(root, "[data-dock-overview-mode]", model.modeLabel);
  setText(root, "[data-dock-distance]", model.distanceText);
  setText(root, "[data-dock-duration]", model.durationText);
  setText(root, "[data-dock-environment-status]", model.environmentStatus);
  setText(root, "[data-dock-environment-assessment]", model.environmentAssessment);

  const list = root.querySelector("[data-dock-waypoint-list]");
  list.replaceChildren();
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
