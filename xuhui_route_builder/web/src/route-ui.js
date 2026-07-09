const PREFERENCE_KEYWORDS = {
  coffee: ["咖啡", "coffee"],
  toilet: ["厕所", "卫生间", "洗手间"],
  store: ["便利店", "补给", "商店"],
  metro: ["地铁", "metro", "站"],
  park: ["公园入口", "公园", "绿地", "植物园"],
};

const MODE_LABELS = {
  run: "跑步",
  walk: "步行",
  bike: "骑行",
  access: "接驳",
};

const RANK_LABELS = {
  recommended: "推荐",
  convenient: "便捷",
  candidate: "候选",
};

const NAVIGATION_POINT_LABELS = {
  origin: "起点",
  waypoint: "途经点",
  destination: "终点",
};

export function renderRoutePlanner(catalog, options) {
  const controls = getControls();
  populateZoneFilter(controls.zoneFilter, catalog);
  populateNavigationRoutes(controls.navigationRouteSelect, catalog);

  const state = {
    activeAppTab: "selection",
    activeResultTab: "recommend",
    selectedRouteId: catalog[0]?.route_id || "",
    filters: readSelectionFilters(controls),
    groups: buildGroups(catalog, readSelectionFilters(controls)),
    navigationStatus: "idle",
    navigationPoints: {
      origin: null,
      waypoint: null,
      destination: null,
    },
  };

  bindAppTabs(state, controls, options);
  bindResultTabs(state, controls, options);
  bindSelectionControls(catalog, state, controls, options);
  bindNavigationControls(catalog, state, controls, options);
  setNavigationControlsEnabled(controls, false);

  paintResults(state, controls, options);
  if (catalog[0]) {
    renderDetail(catalog[0], controls.detail);
  }
}

export function filterCandidateRoutes(catalog, filters) {
  const textFilters = [filters.keyword].map(normalizeText).filter(Boolean);

  return catalog
    .map((route, index) => ({
      route,
      index,
      score: scoreRoute(route, textFilters, filters.preferences),
    }))
    .filter(({ route, score }) => {
      if (filters.zone !== "all" && route.region_zone !== filters.zone) {
        return false;
      }
      if (filters.mode !== "all" && route.route_mode !== filters.mode) {
        return false;
      }
      if (filters.distance !== "all" && route.distance_level !== filters.distance) {
        return false;
      }
      if (filters.preferences.length && !matchesPreferences(route, filters.preferences)) {
        return false;
      }
      if (!textFilters.length) {
        return true;
      }
      return score > 0;
    })
    .sort((a, b) => b.score - a.score || routePriority(b.route) - routePriority(a.route) || a.index - b.index)
    .map(({ route }) => route);
}

function bindAppTabs(state, controls, options) {
  controls.appTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeAppTab = tab.dataset.appTab;
      switchAppTab(state, controls);
      if (state.activeAppTab === "selection") {
        paintResults(state, controls, options);
      }
    });
  });
}

function bindResultTabs(state, controls, options) {
  controls.resultTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeResultTab = tab.dataset.resultTab;
      paintResults(state, controls, options);
    });
  });
}

function bindSelectionControls(catalog, state, controls, options) {
  controls.planButton.addEventListener("click", () => runSearch(catalog, state, controls, options));
  controls.resetButton.addEventListener("click", () => {
    resetSelectionControls(controls);
    state.filters = readSelectionFilters(controls);
    state.groups = buildGroups(catalog, state.filters);
    state.activeResultTab = "recommend";
    paintResults(state, controls, options);
  });

  for (const control of [controls.zoneFilter, controls.modeFilter, controls.distanceFilter]) {
    control.addEventListener("change", () => runSearch(catalog, state, controls, options));
  }

  controls.keywordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSearch(catalog, state, controls, options);
    }
  });

  controls.preferences.forEach((input) => {
    input.addEventListener("change", () => runSearch(catalog, state, controls, options));
  });
}

function bindNavigationControls(catalog, state, controls, options) {
  const handleMapPick = (result) => {
    if (result.error) {
      controls.navigationStatus.textContent = result.error;
      return;
    }
    const point = result.point;
    state.navigationPoints[result.role] = point;
    inputForRole(result.role, controls).value = formatPoint(point);
    controls.navigationStatus.textContent = `${NAVIGATION_POINT_LABELS[result.role]}已选：${formatPoint(point)}`;
  };

  controls.startNavigationButton.addEventListener("click", () => {
    state.navigationStatus = "editing";
    state.navigationPoints = { origin: null, waypoint: null, destination: null };
    options.onStartNavigation(handleMapPick);
    setNavigationControlsEnabled(controls, true);
    controls.navigationStatus.textContent = "导航已开始，可输入地点或点击点选按钮后在地图取点。";
  });

  controls.endNavigationButton.addEventListener("click", () => {
    resetNavigationState(state, controls);
    options.onEndNavigation();
  });

  for (const [role, button] of [
    ["origin", controls.startPickButton],
    ["waypoint", controls.waypointPickButton],
    ["destination", controls.endPickButton],
  ]) {
    button.addEventListener("click", () => {
      try {
        ensureNavigationEditing(state);
        options.onPickNavigationPoint(role);
        controls.navigationStatus.textContent = `请在徐汇区内点击${NAVIGATION_POINT_LABELS[role]}。`;
      } catch (error) {
        controls.navigationStatus.textContent = error.message;
      }
    });
  }

  controls.navigationRouteSelect.addEventListener("change", () => {
    const route = findRoute(catalog, controls.navigationRouteSelect.value);
    if (!route) {
      return;
    }
    state.selectedRouteId = route.route_id;
    renderDetail(route, controls.detail);
    options.onSelect(route.route_id);
  });

  controls.navigateButton.addEventListener("click", () => {
    const route = findRoute(catalog, controls.navigationRouteSelect.value);
    let request;
    try {
      request = readNavigationRequest(route, state, controls);
    } catch (error) {
      controls.navigationStatus.textContent = error.message;
      return;
    }
    controls.navigationStatus.textContent = "正在调用高德路线导航...";
    options.onNavigate(request)
      .then((summary) => {
        state.navigationStatus = "planned";
        controls.navigationStatus.textContent = summary;
      })
      .catch((error) => {
        controls.navigationStatus.textContent = error.message;
      });
  });

  for (const input of [controls.startInput, controls.waypointInput, controls.endInput]) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        controls.navigateButton.click();
      }
    });
  }
}

function runSearch(catalog, state, controls, options) {
  state.filters = readSelectionFilters(controls);
  state.groups = buildGroups(catalog, state.filters);
  paintResults(state, controls, options);
}

function buildGroups(catalog, filters) {
  const candidate = filterCandidateRoutes(catalog, filters);
  return {
    recommend: candidate.filter((route) => route.candidate_rank === "recommended").sort((a, b) => routePriority(b) - routePriority(a)),
    convenient: candidate.filter((route) => route.candidate_rank === "convenient").sort((a, b) => Number(a.duration_min || 0) - Number(b.duration_min || 0)),
    candidate,
  };
}

function paintResults(state, controls, options) {
  controls.resultTabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.resultTab === state.activeResultTab);
  });

  const visibleRoutes = state.groups[state.activeResultTab] || [];
  const total = state.groups.candidate.length;
  controls.summary.textContent = total
    ? `已匹配 ${total} 条路线，当前显示 ${tabLabel(state.activeResultTab)} ${visibleRoutes.length} 条。`
    : "暂无匹配路线，放宽片区、距离或关键词。";

  controls.list.innerHTML = "";
  if (!visibleRoutes.length) {
    controls.list.innerHTML = `<div class="empty-state">没有匹配路线。</div>`;
    controls.detail.innerHTML = "";
    options.onSearch([], "", state.filters);
    return;
  }

  const visibleOnMap = visibleRoutes.slice(0, 24);
  if (!visibleOnMap.some((route) => route.route_id === state.selectedRouteId)) {
    state.selectedRouteId = visibleOnMap[0].route_id;
  }

  for (const route of visibleRoutes) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "route-item";
    item.dataset.routeId = route.route_id;
    item.dataset.mode = route.route_mode;
    item.innerHTML = routeItemTemplate(route);
    item.addEventListener("click", () => {
      selectRoute(route, state, controls, options);
    });
    controls.list.appendChild(item);
  }

  const selectedRoute = findRoute(visibleRoutes, state.selectedRouteId) || visibleRoutes[0];
  selectRoute(selectedRoute, state, controls, options, { skipSearch: true });
  options.onSearch(visibleOnMap, selectedRoute.route_id, state.filters);
}

function selectRoute(route, state, controls, options, flags = {}) {
  state.selectedRouteId = route.route_id;
  setActive(route.route_id);
  renderDetail(route, controls.detail);
  syncNavigationRoute(route.route_id, controls);
  options.onSelect(route.route_id);
  if (!flags.skipSearch) {
    const visibleRoutes = state.groups[state.activeResultTab] || [];
    options.onSearch(visibleRoutes.slice(0, 24), route.route_id, state.filters);
  }
}

function switchAppTab(state, controls) {
  controls.appTabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.appTab === state.activeAppTab);
  });
  controls.selectionView.classList.toggle("active", state.activeAppTab === "selection");
  controls.navigationView.classList.toggle("active", state.activeAppTab === "navigation");
}

function readSelectionFilters(controls) {
  return {
    zone: controls.zoneFilter.value,
    keyword: controls.keywordInput.value.trim(),
    mode: controls.modeFilter.value,
    distance: controls.distanceFilter.value,
    preferences: controls.preferences.filter((input) => input.checked).map((input) => input.value),
  };
}

function readNavigationRequest(route, state, controls) {
  ensureNavigationEditing(state);
  const origin = navigationValue(controls.startInput.value, state.navigationPoints.origin);
  const waypoint = navigationValue(controls.waypointInput.value, state.navigationPoints.waypoint);
  const destination =
    navigationValue(controls.endInput.value, state.navigationPoints.destination) ||
    route?.start_entry_location ||
    route?.end_entry_location ||
    route?.start_entry_name ||
    "";

  if (!origin) {
    throw new Error("请先选择或输入导航起点。");
  }
  if (!destination) {
    throw new Error("请先选择或输入导航终点。");
  }

  return {
    origin,
    waypoints: waypoint ? [waypoint] : [],
    destination,
    mode: controls.navigationMode.value,
    routeId: route?.route_id || "",
    routeName: route?.route_name || "",
  };
}

function navigationValue(text, point) {
  if (point) {
    return point;
  }
  const trimmed = text.trim();
  return trimmed ? { text: trimmed } : null;
}

function ensureNavigationEditing(state) {
  if (state.navigationStatus === "idle") {
    throw new Error("请先点击开始导航。");
  }
}

function resetNavigationState(state, controls) {
  state.navigationStatus = "idle";
  state.navigationPoints = { origin: null, waypoint: null, destination: null };
  controls.startInput.value = "";
  controls.waypointInput.value = "";
  controls.endInput.value = "";
  setNavigationControlsEnabled(controls, false);
  controls.navigationStatus.textContent = "点击开始导航后，可输入地点或在徐汇区内点选。";
}

function setNavigationControlsEnabled(controls, enabled) {
  for (const control of [
    controls.startInput,
    controls.waypointInput,
    controls.endInput,
    controls.navigationMode,
    controls.navigateButton,
    controls.startPickButton,
    controls.waypointPickButton,
    controls.endPickButton,
  ]) {
    control.disabled = !enabled;
  }
  controls.endNavigationButton.disabled = !enabled;
}

function inputForRole(role, controls) {
  const inputs = {
    origin: controls.startInput,
    waypoint: controls.waypointInput,
    destination: controls.endInput,
  };
  return inputs[role];
}

function routeItemTemplate(route) {
  const tags = (route.tags || []).slice(0, 4).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  return `
    <strong>${escapeHtml(route.route_name)}</strong>
    <span class="meta">${escapeHtml(route.region_zone)} · ${MODE_LABELS[route.route_mode] || route.route_mode} · ${escapeHtml(route.distance_level)} · ${Number(route.duration_min || 0).toFixed(1)} 分钟</span>
    <span class="rank">${RANK_LABELS[route.candidate_rank] || "候选"}</span>
    <span class="tag-row">${tags}</span>
  `;
}

function renderDetail(route, detail) {
  const tags = (route.tags || []).join("、") || "暂无标签";
  const startName = route.start_entry_name || route.start_entry_id || "入口待核验";
  const endName = route.end_entry_name || route.end_entry_id || "入口待核验";
  const source = route.source_name ? `${route.source_name} · ${route.source_level || "curated"}` : "来源待核验";
  const poiText = (route.nearby_pois || []).map((poi) => `${poi.poi_name} ${poi.distance_m}米`).join("、") || "暂无偏好点";
  detail.innerHTML = `
    <h2>${escapeHtml(route.route_name)}</h2>
    <p>${escapeHtml(route.region_zone)} · ${MODE_LABELS[route.route_mode] || route.route_mode} · ${escapeHtml(route.distance_level)}</p>
    <dl>
      <div><dt>入口</dt><dd>${escapeHtml(startName)} → ${escapeHtml(endName)}</dd></div>
      <div><dt>距离</dt><dd>${Number(route.distance_m || route.target_distance_m || 0).toFixed(0)} 米，预计 ${Number(route.duration_min || 0).toFixed(1)} 分钟</dd></div>
      <div><dt>途经</dt><dd>${escapeHtml((route.waypoint_names || []).join("、") || "待核验")}</dd></div>
      <div><dt>偏好</dt><dd>${escapeHtml(poiText)}</dd></div>
      <div><dt>来源</dt><dd>${escapeHtml(source)}</dd></div>
      <div><dt>标签</dt><dd>${escapeHtml(tags)}</dd></div>
    </dl>
    <p>${escapeHtml(route.score_note || "当前阶段展示候选路线，后续接入环境暴露评分。")}</p>
  `;
}

function scoreRoute(route, textFilters, preferences) {
  const searchable = normalizeText([
    route.route_name,
    route.region_zone,
    route.distance_level,
    route.route_mode,
    route.start_entry_name,
    route.end_entry_name,
    route.candidate_rank,
    ...(route.tags || []),
    ...(route.feature_tags || []),
    ...(route.waypoint_names || []),
    ...(route.nearby_pois || []).map((poi) => poi.poi_name),
  ].join(" "));

  let score = 0;
  for (const text of textFilters) {
    if (searchable.includes(text)) {
      score += 8;
    }
  }
  for (const preference of preferences) {
    if ((route.preference_hits || []).includes(preference)) {
      score += 12;
      continue;
    }
    const keywords = PREFERENCE_KEYWORDS[preference] || [];
    if (keywords.some((keyword) => searchable.includes(normalizeText(keyword)))) {
      score += 2;
    }
  }
  return score;
}

function matchesPreferences(route, preferences) {
  const hits = route.preference_hits || [];
  if (preferences.every((preference) => hits.includes(preference))) {
    return true;
  }
  const searchable = normalizeText([...(route.tags || []), ...(route.nearby_pois || []).map((poi) => poi.poi_name)].join(" "));
  return preferences.every((preference) => (PREFERENCE_KEYWORDS[preference] || []).some((keyword) => searchable.includes(normalizeText(keyword))));
}

function routePriority(route) {
  const tagText = normalizeText((route.tags || []).join(" "));
  let score = 0;
  if (route.candidate_rank === "recommended") {
    score += 10;
  }
  if (tagText.includes("绿地") || tagText.includes("公园") || tagText.includes("滨江")) {
    score += 6;
  }
  if (tagText.includes("夜跑") || tagText.includes("梧桐")) {
    score += 3;
  }
  score += Math.max(0, 6000 - Number(route.distance_m || route.target_distance_m || 0)) / 1000;
  score += (route.preference_hits || []).length;
  return score;
}

function getControls() {
  return {
    appTabs: [...document.querySelectorAll("[data-app-tab]")],
    resultTabs: [...document.querySelectorAll("#resultTabs [data-result-tab]")],
    selectionView: document.querySelector("#routeSelectionView"),
    navigationView: document.querySelector("#routeNavigationView"),
    zoneFilter: document.querySelector("#zoneFilter"),
    keywordInput: document.querySelector("#keywordInput"),
    modeFilter: document.querySelector("#modeFilter"),
    distanceFilter: document.querySelector("#distanceFilter"),
    planButton: document.querySelector("#planButton"),
    resetButton: document.querySelector("#resetButton"),
    summary: document.querySelector("#routeSummary"),
    list: document.querySelector("#routeList"),
    detail: document.querySelector("#routeDetail"),
    navigationRouteSelect: document.querySelector("#navigationRouteSelect"),
    startNavigationButton: document.querySelector("#startNavigationButton"),
    endNavigationButton: document.querySelector("#endNavigationButton"),
    startInput: document.querySelector("#startInput"),
    startPickButton: document.querySelector("#startPickButton"),
    waypointInput: document.querySelector("#waypointInput"),
    waypointPickButton: document.querySelector("#waypointPickButton"),
    endInput: document.querySelector("#endInput"),
    endPickButton: document.querySelector("#endPickButton"),
    navigationMode: document.querySelector("#navigationMode"),
    navigateButton: document.querySelector("#navigateButton"),
    navigationStatus: document.querySelector("#navigationStatus"),
    preferences: [
      document.querySelector("#preferCoffee"),
      document.querySelector("#preferToilet"),
      document.querySelector("#preferStore"),
      document.querySelector("#preferMetro"),
      document.querySelector("#preferPark"),
    ],
  };
}

function populateZoneFilter(select, catalog) {
  const zones = [...new Set(catalog.map((route) => route.region_zone).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  for (const zone of zones) {
    const option = document.createElement("option");
    option.value = zone;
    option.textContent = zone;
    select.appendChild(option);
  }
}

function populateNavigationRoutes(select, catalog) {
  select.innerHTML = "";
  for (const route of catalog) {
    const option = document.createElement("option");
    option.value = route.route_id;
    option.textContent = `${route.route_name} · ${route.distance_level}`;
    select.appendChild(option);
  }
}

function syncNavigationRoute(routeId, controls) {
  if (controls.navigationRouteSelect.value !== routeId) {
    controls.navigationRouteSelect.value = routeId;
  }
}

function resetSelectionControls(controls) {
  controls.zoneFilter.value = "all";
  controls.keywordInput.value = "";
  controls.modeFilter.value = "all";
  controls.distanceFilter.value = "all";
  controls.preferences.forEach((input) => {
    input.checked = false;
  });
}

function setActive(routeId) {
  document.querySelectorAll(".route-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.routeId === routeId);
  });
}

function findRoute(catalog, routeId) {
  return catalog.find((route) => route.route_id === routeId);
}

function formatPoint(point) {
  return `${Number(point.lng_gcj02).toFixed(6)},${Number(point.lat_gcj02).toFixed(6)}`;
}

function tabLabel(tab) {
  const labels = {
    recommend: "推荐",
    convenient: "便捷",
    candidate: "候选",
  };
  return labels[tab] || tab;
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char];
  });
}
