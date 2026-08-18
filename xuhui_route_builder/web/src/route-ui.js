const MODE_LABELS = {
  run: "跑步",
  walk: "步行",
  bike: "骑行",
  access: "接驳",
};

const NAVIGATION_POINT_LABELS = {
  origin: "用户位置",
};

export function renderRoutePlanner(catalog, options) {
  const controls = getControls();
  updateModeCounts(catalog, controls);
  populateZoneFilter(controls.zoneFilter, catalog);
  populateNavigationRoutes(controls.navigationRouteSelect, filterNavigationRoutes(catalog, "walk"));

  const state = {
    activeAppTab: "selection",
    selectedRouteId: "",
    filters: readSelectionFilters(controls),
    filteredRoutes: [],
    navigationMode: "walk",
    navigationStatus: "idle",
    navigationPoints: { origin: null },
    plannedNavigationRequest: null,
    plannedNavigationPlan: null,
  };

  bindAppTabs(state, controls, options);
  bindSelectionControls(catalog, state, controls, options);
  bindNavigationControls(catalog, state, controls, options);
  setNavigationControlsEnabled(controls, false);
  initializeRouteSelection(catalog, state, controls, options);
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
      if (filters.distance !== "all" && routeDistanceBand(route) !== filters.distance) {
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

export function filterNavigationRoutes(catalog, mode) {
  return catalog.filter((route) => route.route_mode === mode);
}

function bindAppTabs(state, controls, options) {
  controls.appTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeAppTab = tab.dataset.appTab;
      switchAppTab(state, controls);
    });
  });
}

function bindSelectionControls(catalog, state, controls, options) {
  controls.planButton.addEventListener("click", () => runSearch(catalog, state, controls, options));
  controls.resetButton.addEventListener("click", () => {
    resetSelectionControls(controls);
    initializeRouteSelection(catalog, state, controls, options);
  });

  controls.sportModeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      controls.sportModeTabs.forEach((item) => item.classList.toggle("active", item === tab));
      initializeRouteSelection(catalog, state, controls, options);
    });
  });

  controls.keywordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSearch(catalog, state, controls, options);
    }
  });

  controls.routeSelect.addEventListener("change", () => {
    const route = findRoute(state.filteredRoutes, controls.routeSelect.value);
    if (route) {
      showRoute(route, catalog, state, controls, options, "已切换到所选路线。");
    }
  });
}

function bindNavigationControls(catalog, state, controls, options) {
  const handleMapPick = (result) => {
    if (result.error) {
      controls.navigationStatus.textContent = result.error;
      return;
    }
    const point = result.point;
    state.navigationPoints.origin = point;
    controls.startInput.value = formatPoint(point);
    controls.navigationStatus.textContent = `${NAVIGATION_POINT_LABELS[result.role]}已选：${formatPoint(point)}`;
  };

  controls.startNavigationButton.addEventListener("click", () => {
    state.navigationStatus = "editing";
    state.navigationPoints = { origin: null };
    state.plannedNavigationRequest = null;
    state.plannedNavigationPlan = null;
    options.onStartNavigation(handleMapPick);
    setNavigationControlsEnabled(controls, true);
    controls.startSportButton.disabled = true;
    controls.navigationStatus.textContent = "可输入地点，或点击点选后在地图设置用户位置。";
  });

  controls.endNavigationButton.addEventListener("click", () => {
    resetNavigationState(state, controls);
    options.onEndNavigation();
  });

  controls.startPickButton.addEventListener("click", () => {
    try {
      ensureNavigationEditing(state);
      options.onPickNavigationPoint("origin");
      controls.navigationStatus.textContent = "请在徐汇区内点击用户位置。";
    } catch (error) {
      controls.navigationStatus.textContent = error.message;
    }
  });

  controls.navigationModeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      state.navigationMode = tab.dataset.navigationMode;
      controls.navigationModeTabs.forEach((item) => item.classList.toggle("active", item === tab));
      const reset = resetNavigationForModeChange(state.navigationStatus);
      state.navigationStatus = reset.navigationStatus;
      state.selectedRouteId = reset.selectedRouteId;
      state.plannedNavigationRequest = reset.plannedRequest;
      state.plannedNavigationPlan = null;
      controls.startSportButton.disabled = reset.launchDisabled;
      populateNavigationRoutes(
        controls.navigationRouteSelect,
        filterNavigationRoutes(catalog, state.navigationMode),
      );
      renderNavigationMode(null, controls);
      options.onClearRoutes();
      options.onRouteMetrics?.(null);
      controls.navigationStatus.textContent = "运动类型已切换，请选择该类型的目标路线。";
    });
  });

  controls.navigationRouteSelect.addEventListener("change", () => {
    const route = selectNavigationRoute(catalog, controls.navigationRouteSelect.value, options);
    if (!route) {
      return;
    }
    state.selectedRouteId = route.route_id;
    state.plannedNavigationRequest = null;
    state.plannedNavigationPlan = null;
    const reset = resetPlannedNavigationForRouteChange(state.navigationStatus);
    if (reset) {
      state.navigationStatus = reset.navigationStatus;
      controls.navigationStatus.textContent = reset.statusText;
    }
    controls.startSportButton.disabled = true;
    renderDetail(route, controls.detail);
    renderNavigationMode(route, controls);
    controls.navigationStatus.textContent = `已选择${route.route_name}，请设置用户位置。`;
  });

  controls.navigateButton.addEventListener("click", () => {
    const route = findRoute(catalog, controls.navigationRouteSelect.value);
    let request;
    try {
      ensureNavigationEditing(state);
      const origin = navigationValue(controls.startInput.value, state.navigationPoints.origin);
      request = buildNavigationRequest(route, origin);
    } catch (error) {
      controls.navigationStatus.textContent = error.message;
      return;
    }
    controls.navigationStatus.textContent = "正在调用高德路线导航...";
    options.onNavigate(request)
      .then((plan) => {
        state.navigationStatus = "planned";
        state.plannedNavigationRequest = request;
        state.plannedNavigationPlan = plan;
        controls.navigationStatus.textContent = `${plan.summary} 可以开始网页内导航。`;
        controls.startSportButton.disabled = false;
      })
      .catch((error) => {
        state.plannedNavigationRequest = null;
        state.plannedNavigationPlan = null;
        controls.startSportButton.disabled = true;
        controls.navigationStatus.textContent = error.message;
      });
  });

  controls.startInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      controls.navigateButton.click();
    }
  });

  controls.startSportButton.addEventListener("click", () => {
    try {
      if (!startPlannedNavigation(
        state.navigationStatus,
        state.plannedNavigationPlan,
        state.plannedNavigationRequest,
        options,
      )) {
        controls.navigationStatus.textContent = "请先完成到路线起点的接驳规划。";
        return;
      }
      state.navigationStatus = "navigating";
      controls.startSportButton.disabled = true;
      controls.navigationStatus.textContent = "网页内导航已启动，正在获取实时位置。";
    } catch (error) {
      controls.navigationStatus.textContent = error.message;
    }
  });
}

export function selectNavigationRoute(catalog, routeId, options) {
  const route = findRoute(catalog, routeId);
  if (!route) {
    return null;
  }
  options.onSelect(route.route_id);
  options.onRouteMetrics?.(route);
  return route;
}

export function startPlannedNavigation(navigationStatus, plan, request, options) {
  if (navigationStatus !== "planned" || !plan || !request) {
    return false;
  }
  if (!options.onStartInlineNavigation) {
    return false;
  }
  options.onStartInlineNavigation({ plan, request });
  return true;
}

export function resetNavigationForModeChange(navigationStatus) {
  return {
    navigationStatus: navigationStatus === "idle" ? "idle" : "editing",
    selectedRouteId: "",
    plannedRequest: null,
    launchDisabled: true,
  };
}

export function resetPlannedNavigationForRouteChange(navigationStatus) {
  if (!new Set(["planned", "sporting"]).has(navigationStatus)) {
    return null;
  }
  return {
    navigationStatus: "editing",
    statusText: "目标路线已切换，请重新规划到新路线起点的接驳。",
    startSportDisabled: true,
  };
}

function runSearch(catalog, state, controls, options) {
  state.filters = readSelectionFilters(controls);
  state.filteredRoutes = filterCandidateRoutes(catalog, state.filters);
  const route = selectBestRoute(state.filteredRoutes);
  renderRouteSelect(state.filteredRoutes, controls, route?.route_id || "");
  if (!route) {
    state.selectedRouteId = "";
    renderEmptySelection(controls, options, "无推荐路线，请调整片区、类型、距离或关键词。");
    return;
  }
  showRoute(route, catalog, state, controls, options, `已从 ${state.filteredRoutes.length} 条匹配路线中推荐最优路线。`);
}

export function selectBestRoute(routes) {
  return routes[0] || null;
}

function initializeRouteSelection(catalog, state, controls, options) {
  state.filters = readSelectionFilters(controls);
  state.filteredRoutes = filterCandidateRoutes(catalog, state.filters);
  state.selectedRouteId = "";
  renderRouteSelect(state.filteredRoutes, controls, "");
  controls.summary.textContent = `当前有 ${state.filteredRoutes.length} 条候选路线，点击筛选后显示推荐路线。`;
  controls.detail.innerHTML = "";
  options.onClearRoutes();
  options.onRouteMetrics?.(null);
}

function renderRouteSelect(routes, controls, selectedRouteId) {
  controls.routeSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = routes.length ? "请选择一条路线" : "无匹配路线";
  placeholder.disabled = routes.length > 0;
  placeholder.selected = !selectedRouteId;
  controls.routeSelect.appendChild(placeholder);
  for (const route of routes) {
    const option = document.createElement("option");
    option.value = route.route_id;
    option.textContent = routeOptionLabel(route);
    option.selected = route.route_id === selectedRouteId;
    controls.routeSelect.appendChild(option);
  }
  controls.routeSelect.disabled = routes.length === 0;
  controls.routeOptionCount.textContent = `${routes.length} 条候选路线`;
}

function showRoute(route, catalog, state, controls, options, summary) {
  state.selectedRouteId = route.route_id;
  controls.routeSelect.value = route.route_id;
  renderDetail(route, controls.detail);
  syncNavigationRoute(route, catalog, state, controls);
  controls.summary.textContent = summary;
  options.onShowRoute(route);
  options.onRouteMetrics?.(route);
}

function renderEmptySelection(controls, options, message) {
  controls.summary.textContent = message;
  controls.detail.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
  controls.routeSelect.value = "";
  options.onClearRoutes();
  options.onRouteMetrics?.(null);
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
    mode: controls.sportModeTabs.find((tab) => tab.classList.contains("active"))?.dataset.routeMode || "walk",
    distance: controls.distanceFilter.value,
    preferences: controls.preferences.filter((input) => input.checked).map((input) => input.value),
  };
}

export function buildNavigationRequest(route, origin) {
  if (!origin) {
    throw new Error("请先选择或输入用户位置。");
  }
  if (!route) {
    throw new Error("请先选择一条正式路线。");
  }
  const destination = route.start_location;
  if (!destination || !Number.isFinite(destination.lng_gcj02) || !Number.isFinite(destination.lat_gcj02)) {
    throw new Error(`路线 ${route.route_id || "未知"} 缺少正式起点数据。`);
  }
  return {
    origin,
    destination,
    routeId: route.route_id,
    routeMode: route.route_mode,
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
  state.navigationPoints = { origin: null };
  state.plannedNavigationRequest = null;
  state.plannedNavigationPlan = null;
  controls.startInput.value = "";
  controls.startSportButton.disabled = true;
  setNavigationControlsEnabled(controls, false);
  controls.navigationStatus.textContent = "先选择运动类型和目标路线，再设置用户位置。";
}

function setNavigationControlsEnabled(controls, enabled) {
  for (const control of [
    controls.startInput,
    controls.navigateButton,
    controls.startPickButton,
  ]) {
    control.disabled = !enabled;
  }
  controls.endNavigationButton.disabled = !enabled;
}

export function routeOptionLabel(route) {
  const status = route.validation_status === "accepted" ? "严格验收" : "待考证";
  return `${route.route_name}｜${route.region_zone}｜${(Number(route.distance_m || 0) / 1000).toFixed(1)} km｜${status}`;
}

function renderDetail(route, detail) {
  const startName = route.start_location?.name || "路线起点";
  const endName = route.end_location?.name || "路线终点";
  const endpointHtml = route.route_shape === "strict_loop"
    ? `<span><b>起终</b>${escapeHtml(startName)}</span>`
    : `<span><b>起</b>${escapeHtml(startName)}</span><i></i><span><b>终</b>${escapeHtml(endName)}</span>`;
  const status = route.validation_status === "accepted" ? "严格验收" : "待考证";
  detail.innerHTML = `
    <div class="route-card-topline">
      <span class="mode-pill" data-mode="${escapeHtml(route.route_mode)}">${MODE_LABELS[route.route_mode] || route.route_mode}</span>
      <span class="status-pill" data-status="${escapeHtml(route.validation_status)}">${escapeHtml(status)}</span>
    </div>
    <h2>${escapeHtml(route.route_name)}</h2>
    <p class="route-card-place">${escapeHtml(route.region_zone)} · ${Number(route.distance_m || 0).toFixed(0)} 米 · ${Number(route.duration_min || 0).toFixed(0)} 分钟</p>
    <div class="route-endpoints">${endpointHtml}</div>
    <p class="route-source">来源：${escapeHtml(route.source_name || "路线数据源")}</p>
    <p class="route-review-note">${escapeHtml(reviewNoteSummary(route.review_note))}</p>
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
    }
  }
  return score;
}

function matchesPreferences(route, preferences) {
  const hits = route.preference_hits || [];
  return preferences.every((preference) => hits.includes(preference));
}

function routePriority(route) {
  const tagText = normalizeText((route.tags || []).join(" "));
  let score = 0;
  if (route.validation_status === "accepted") {
    score += 30;
  }
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
    selectionView: document.querySelector("#routeSelectionView"),
    navigationView: document.querySelector("#routeNavigationView"),
    zoneFilter: document.querySelector("#zoneFilter"),
    keywordInput: document.querySelector("#keywordInput"),
    sportModeTabs: [...document.querySelectorAll("#sportModeTabs [data-route-mode]")],
    distanceFilter: document.querySelector("#distanceFilter"),
    planButton: document.querySelector("#planButton"),
    resetButton: document.querySelector("#resetButton"),
    summary: document.querySelector("#routeSummary"),
    routeSelect: document.querySelector("#routeSelect"),
    routeOptionCount: document.querySelector("#routeOptionCount"),
    detail: document.querySelector("#routeDetail"),
    navigationModeTabs: [...document.querySelectorAll("#navigationSportModeTabs [data-navigation-mode]")],
    navigationRouteSelect: document.querySelector("#navigationRouteSelect"),
    startNavigationButton: document.querySelector("#startNavigationButton"),
    endNavigationButton: document.querySelector("#endNavigationButton"),
    startInput: document.querySelector("#startInput"),
    startPickButton: document.querySelector("#startPickButton"),
    navigationModeSummary: document.querySelector("#navigationModeSummary"),
    navigateButton: document.querySelector("#navigateButton"),
    startSportButton: document.querySelector("#startSportButton"),
    navigationStatus: document.querySelector("#navigationStatus"),
    preferences: [
      document.querySelector("#preferCoffee"),
      document.querySelector("#preferToilet"),
      document.querySelector("#preferStore"),
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

function updateModeCounts(catalog, controls) {
  for (const tab of controls.sportModeTabs) {
    const count = catalog.filter((route) => route.route_mode === tab.dataset.routeMode).length;
    tab.querySelector("span").textContent = `${count} 条`;
  }
  for (const tab of controls.navigationModeTabs) {
    const count = catalog.filter((route) => route.route_mode === tab.dataset.navigationMode).length;
    tab.querySelector("span").textContent = `${count} 条`;
  }
}

function populateNavigationRoutes(select, catalog) {
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = catalog.length ? "请选择目标路线" : "该类型暂无路线";
  placeholder.disabled = catalog.length > 0;
  placeholder.selected = true;
  select.appendChild(placeholder);
  for (const route of catalog) {
    const option = document.createElement("option");
    option.value = route.route_id;
    option.textContent = `${route.route_name} · ${route.distance_level}`;
    select.appendChild(option);
  }
  select.disabled = catalog.length === 0;
}

function routeDistanceBand(route) {
  const distance = Number(route.target_distance_m || route.distance_m || 0);
  const bands = {
    walk: [[1000, 2000], [2000, 3500], [3500, 5000]],
    run: [[3000, 5000], [5000, 10000], [10000, 15000]],
    bike: [[5000, 10000], [10000, 20000], [20000, 30000]],
  }[route.route_mode] || [];
  const index = bands.findIndex(([lower, upper], bandIndex) =>
    distance >= lower && (distance < upper || bandIndex === bands.length - 1 && distance === upper));
  return ["short", "medium", "long"][index] || "outside";
}

function reviewNoteSummary(note) {
  const text = String(note || "验收说明待补充");
  if (text.startsWith("Overpass 校验异常")) {
    return "OSM 路网服务超时，贴路率仍待复核；完整错误记录见验收清单。";
  }
  return text;
}

function renderNavigationMode(route, controls) {
  controls.navigationModeSummary.textContent = route
    ? `${MODE_LABELS[route.route_mode] || route.route_mode}接驳 · 终点为路线起点`
    : "接驳方式随所选路线自动确定";
}

function syncNavigationRoute(route, catalog, state, controls) {
  state.navigationMode = route.route_mode;
  controls.navigationModeTabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.navigationMode === route.route_mode);
  });
  populateNavigationRoutes(
    controls.navigationRouteSelect,
    filterNavigationRoutes(catalog, route.route_mode),
  );
  controls.navigationRouteSelect.value = route.route_id;
}

function resetSelectionControls(controls) {
  controls.zoneFilter.value = "all";
  controls.keywordInput.value = "";
  controls.sportModeTabs.forEach((tab, index) => tab.classList.toggle("active", index === 0));
  controls.distanceFilter.value = "all";
  controls.preferences.forEach((input) => {
    input.checked = false;
  });
}

function findRoute(catalog, routeId) {
  return catalog.find((route) => route.route_id === routeId);
}

function formatPoint(point) {
  return `${Number(point.lng_gcj02).toFixed(6)},${Number(point.lat_gcj02).toFixed(6)}`;
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
