const MODE_LABELS = {
  run: "跑步",
  walk: "步行",
  bike: "骑行",
  access: "接驳",
};

export function renderRoutePlanner(catalog, options) {
  const controls = getControls();
  updateModeCounts(catalog, controls);
  populateZoneFilter(controls.zoneFilter, catalog);

  const state = {
    selectedRouteId: "",
    filters: readSelectionFilters(controls),
    filteredRoutes: [],
    navigationMode: "walk",
    navigationStatus: "ready",
    navigationPoints: { origin: null },
    plannedNavigationRequest: null,
    plannedNavigationPlan: null,
    planningRevision: 0,
  };

  bindSelectionControls(catalog, state, controls, options);
  bindNavigationControls(catalog, state, controls, options);
  renderNavigationPrimaryAction(state.navigationStatus, controls);
  initializeRouteSelection(catalog, state, controls, options);

  return {
    showBrowse() {
      controls.selectionView.hidden = false;
      controls.navigationView.hidden = true;
      renderSelectionPreview(state.filteredRoutes, catalog, state, controls, options);
    },
    selectRoute(routeId) {
      const route = findRoute(catalog, routeId);
      if (!route) return null;
      showRoute(route, catalog, state, controls, options);
      return route;
    },
    openNavigation(routeId, origin = null) {
      const route = findRoute(catalog, routeId);
      if (!route) return null;
      state.selectedRouteId = route.route_id;
      state.navigationMode = route.route_mode;
      state.navigationPoints.origin = origin;
      controls.startInput.value = origin ? formatOrigin(origin) : "";
      controls.navigationRouteName.textContent = route.route_name;
      renderNavigationMode(route, controls);
      renderDetail(route, controls.navigationRouteDetail);
      invalidateNavigationPlan(state, controls, options, origin
        ? "已沿用当前选择的位置。"
        : "请选择出发地后规划接驳路线。");
      options.onSelect(route.route_id);
      options.onRouteMetrics?.(route);
      controls.selectionView.hidden = true;
      controls.navigationView.hidden = false;
      options.onNavigationViewChange?.(true);
      return route;
    },
    endNavigationPreview() {
      const wasPreviewing = state.navigationStatus === "previewing";
      invalidateNavigationPlan(state, controls, options, "");
      return wasPreviewing;
    },
  };
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

function bindSelectionControls(catalog, state, controls, options) {
  controls.resetButton.addEventListener("click", () => {
    resetNavigationFlow(state, controls, options);
    resetSelectionControls(controls);
    initializeRouteSelection(catalog, state, controls, options);
  });

  controls.sportModeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      controls.sportModeTabs.forEach((item) => {
        const active = item === tab;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      initializeRouteSelection(catalog, state, controls, options);
    });
  });

  const refreshPreview = () => {
    initializeRouteSelection(catalog, state, controls, options);
  };
  controls.zoneFilter.addEventListener("change", refreshPreview);
  controls.distanceFilter.addEventListener("change", refreshPreview);

  controls.routeSelect.addEventListener("change", () => {
    const route = findRoute(state.filteredRoutes, controls.routeSelect.value);
    if (route) {
      showRoute(route, catalog, state, controls, options);
    }
  });
}

function bindNavigationControls(catalog, state, controls, options) {
  controls.navigationBackButton.addEventListener("click", () => {
    invalidateNavigationPlan(state, controls, options, "");
    controls.navigationView.hidden = true;
    options.onNavigationViewChange?.(false);
  });

  const handleMapPick = (result) => {
    if (result?.error) {
      controls.navigationStatus.textContent = result.error;
      return;
    }
    const point = result?.point;
    if (!point) {
      controls.navigationStatus.textContent = "地图选点未返回有效出发地。";
      return;
    }
    invalidateNavigationPlan(state, controls, options, "");
    state.navigationPoints.origin = point;
    controls.startInput.value = formatPoint(point);
    controls.navigationStatus.textContent = "出发地已选择。";
    options.onLocationChange?.(point);
  };

  controls.startPickButton.addEventListener("click", () => {
    if (!options.onPickNavigationPoint) {
      controls.navigationStatus.textContent = "地图选点暂不可用。";
      return;
    }
    try {
      options.onPickNavigationPoint("origin", handleMapPick);
      controls.navigationStatus.textContent = "在地图选择出发地";
    } catch (error) {
      controls.navigationStatus.textContent = errorMessage(error);
    }
  });

  controls.navigateButton.addEventListener("click", () => {
    const route = findRoute(catalog, state.selectedRouteId);
    let request;
    try {
      const origin = navigationValue(controls.startInput.value, state.navigationPoints.origin);
      request = buildNavigationRequest(route, origin);
    } catch (error) {
      controls.navigationStatus.textContent = errorMessage(error);
      return;
    }
    if (!options.onNavigate) {
      controls.navigationStatus.textContent = "接驳规划暂不可用。";
      return;
    }

    const planningRevision = beginNavigationPlanning(state, controls, options);
    controls.navigationStatus.textContent = "正在规划接驳路线…";
    Promise.resolve()
      .then(() => options.onNavigate(request))
      .then((plan) => {
        if (!commitNavigationPlan(state, planningRevision, plan, request)) {
          return;
        }
        controls.navigationStatus.textContent = plan.summary || "接驳路线已规划。";
        renderNavigationPrimaryAction(state.navigationStatus, controls);
      })
      .catch((error) => {
        if (!isCurrentPlanningRevision(state, planningRevision)) {
          return;
        }
        state.navigationStatus = "ready";
        state.plannedNavigationRequest = null;
        state.plannedNavigationPlan = null;
        renderNavigationPrimaryAction(state.navigationStatus, controls);
        controls.navigationStatus.textContent = errorMessage(error);
      });
  });

  controls.startInput.addEventListener("input", () => {
    state.navigationPoints.origin = null;
    invalidateNavigationPlan(state, controls, options, "");
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
      state.navigationStatus = "previewing";
      renderNavigationPrimaryAction(state.navigationStatus, controls);
      controls.navigationStatus.textContent = "导航预览已打开。";
    } catch (error) {
      controls.navigationStatus.textContent = errorMessage(error);
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

export function resetNavigationForModeChange() {
  return {
    navigationStatus: "ready",
    selectedRouteId: "",
    plannedRequest: null,
    plannedPlan: null,
  };
}

export function resetPlannedNavigationForRouteChange() {
  return {
    navigationStatus: "ready",
    statusText: "路线已更新，请重新规划接驳路线。",
  };
}

export function advancePlanningRevision(state) {
  state.planningRevision += 1;
  return state.planningRevision;
}

export function isCurrentPlanningRevision(state, revision) {
  return state.planningRevision === revision;
}

export function commitNavigationPlan(state, revision, plan, request) {
  if (!isCurrentPlanningRevision(state, revision)) {
    return false;
  }
  state.navigationStatus = "planned";
  state.plannedNavigationRequest = request;
  state.plannedNavigationPlan = plan;
  return true;
}

export function navigationPrimaryActionState(status) {
  const showPreview = status === "planned" || status === "previewing";
  return {
    showPlan: !showPreview,
    planDisabled: status === "planning",
    showPreview,
    previewDisabled: status !== "planned",
  };
}

export function selectBestRoute(routes) {
  return routes.find((route) => route.validation_status === "accepted") || null;
}

function initializeRouteSelection(catalog, state, controls, options) {
  state.filters = readSelectionFilters(controls);
  state.filteredRoutes = filterCandidateRoutes(catalog, state.filters);
  state.selectedRouteId = "";
  renderRouteSelect(state.filteredRoutes, controls, "");
  controls.summary.textContent = "";
  controls.detail.innerHTML = "";
  options.onRouteMetrics?.(null);
  renderSelectionPreview(state.filteredRoutes, catalog, state, controls, options);
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

function showRoute(route, catalog, state, controls, options) {
  state.selectedRouteId = route.route_id;
  state.navigationMode = route.route_mode;
  controls.routeSelect.value = route.route_id;
  renderDetail(route, controls.detail);
  invalidateNavigationPlan(state, controls, options, "");
  controls.summary.textContent = "";
  options.onShowRoute(route, state.filters.preferences);
  options.onRouteMetrics?.(route);
}

function renderEmptySelection(controls, options, message) {
  controls.summary.textContent = message;
  controls.detail.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
  controls.routeSelect.value = "";
  options.onClearRoutes();
  options.onRouteMetrics?.(null);
}

function renderSelectionPreview(routes, catalog, state, controls, options) {
  options.onPreviewRoutes?.(routes, (routeId) => {
    const route = findRoute(routes, routeId);
    if (route) {
      showRoute(route, catalog, state, controls, options);
    }
  });
}

function applyNavigationRouteSelection(catalog, routeId, state, controls, options) {
  const route = selectNavigationRoute(catalog, routeId, options);
  if (!route) {
    return null;
  }
  state.selectedRouteId = route.route_id;
  const hadPlan = state.navigationStatus !== "ready"
    || state.plannedNavigationRequest
    || state.plannedNavigationPlan;
  const reset = resetPlannedNavigationForRouteChange();
  invalidateNavigationPlan(state, controls, options, hadPlan ? reset.statusText : "");
  renderDetail(route, controls.detail);
  renderNavigationMode(route, controls);
  if (!hadPlan) {
    controls.navigationStatus.textContent = state.navigationPoints.origin || controls.startInput.value.trim()
      ? "可以规划接驳路线。"
      : "选择出发地后即可规划接驳路线。";
  }
  return route;
}

function readSelectionFilters(controls) {
  return {
    zone: controls.zoneFilter.value,
    keyword: "",
    mode: controls.sportModeTabs.find((tab) => tab.classList.contains("active"))?.dataset.routeMode || "walk",
    distance: controls.distanceFilter.value,
    preferences: [],
  };
}

export function buildNavigationRequest(route, origin) {
  if (!origin) {
    throw new Error("请先输入上海地点或在地图选择出发地。");
  }
  if (!route) {
    throw new Error("请先选择一条路线。");
  }
  const destination = route.start_location;
  if (!destination || !Number.isFinite(destination.lng_gcj02) || !Number.isFinite(destination.lat_gcj02)) {
    throw new Error(`路线 ${route.route_id || "未知"} 缺少起点数据。`);
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

function resetNavigationFlow(state, controls, options) {
  invalidateNavigationPlan(state, controls, options, "");
  state.navigationPoints = { origin: null };
  state.selectedRouteId = "";
  controls.startInput.value = "";
  renderNavigationMode(null, controls);
  options.onRouteMetrics?.(null);
}

function beginNavigationPlanning(state, controls, options) {
  const hadPlan = state.navigationStatus !== "ready"
    || state.plannedNavigationRequest
    || state.plannedNavigationPlan;
  const revision = advancePlanningRevision(state);
  state.navigationStatus = "planning";
  state.plannedNavigationRequest = null;
  state.plannedNavigationPlan = null;
  if (hadPlan) {
    options.onEndInlineNavigation?.();
  }
  renderNavigationPrimaryAction(state.navigationStatus, controls);
  return revision;
}

function invalidateNavigationPlan(state, controls, options, statusText) {
  const hadPlan = state.navigationStatus !== "ready"
    || state.plannedNavigationRequest
    || state.plannedNavigationPlan;
  advancePlanningRevision(state);
  state.navigationStatus = "ready";
  state.plannedNavigationRequest = null;
  state.plannedNavigationPlan = null;
  renderNavigationPrimaryAction(state.navigationStatus, controls);
  if (statusText !== undefined) {
    controls.navigationStatus.textContent = statusText;
  }
  if (hadPlan) {
    options.onEndInlineNavigation?.();
  }
}

function renderNavigationPrimaryAction(status, controls) {
  const action = navigationPrimaryActionState(status);
  controls.navigateButton.hidden = !action.showPlan;
  controls.navigateButton.disabled = action.planDisabled;
  controls.startSportButton.hidden = !action.showPreview;
  controls.startSportButton.disabled = action.previewDisabled;
}

export function routeOptionLabel(route) {
  const shape = route.route_shape === "strict_loop" ? "环线" : "单程";
  return `${route.route_name}｜${route.region_zone}｜${(Number(route.distance_m || 0) / 1000).toFixed(1)} km｜${shape}`;
}

function renderDetail(route, detail) {
  const startName = route.start_location?.name || "路线起点";
  const endName = route.end_location?.name || "路线终点";
  const endpointHtml = route.route_shape === "strict_loop"
    ? `<span><b>起终</b>${escapeHtml(startName)}</span>`
    : `<span><b>起</b>${escapeHtml(startName)}</span><i></i><span><b>终</b>${escapeHtml(endName)}</span>`;
  const shape = route.route_shape === "strict_loop" ? "环线" : "单程";
  detail.innerHTML = `
    <div class="route-card-topline">
      <span class="mode-pill" data-mode="${escapeHtml(route.route_mode)}">${MODE_LABELS[route.route_mode] || route.route_mode}</span>
      <span class="shape-pill" data-shape="${escapeHtml(route.route_shape)}">${shape}</span>
    </div>
    <h2>${escapeHtml(route.route_name)}</h2>
    <p class="route-card-place">${escapeHtml(route.region_zone)} · ${Number(route.distance_m || 0).toFixed(0)} 米 · ${Number(route.duration_min || 0).toFixed(0)} 分钟</p>
    <div class="route-endpoints">${endpointHtml}</div>
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
    if (routePreferenceTypes(route).has(preference)) {
      score += 12;
    }
  }
  return score;
}

function matchesPreferences(route, preferences) {
  const hits = routePreferenceTypes(route);
  return preferences.every((preference) => hits.has(preference));
}

function routePreferenceTypes(route) {
  return new Set((route.nearby_pois || []).map((poi) => poi.poi_type).filter(Boolean));
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
  score += routePreferenceTypes(route).size;
  return score;
}

function getControls() {
  return {
    selectionView: document.querySelector("#routeSelectionView"),
    navigationView: document.querySelector("#routeNavigationView"),
    zoneFilter: document.querySelector("#zoneFilter"),
    sportModeTabs: [...document.querySelectorAll("#sportModeTabs [data-route-mode]")],
    distanceFilter: document.querySelector("#distanceFilter"),
    resetButton: document.querySelector("#resetButton"),
    summary: document.querySelector("#routeSummary"),
    routeSelect: document.querySelector("#routeSelect"),
    routeOptionCount: document.querySelector("#routeOptionCount"),
    detail: document.querySelector("#routeDetail"),
    navigationBackButton: document.querySelector("#navigationBackButton"),
    navigationRouteName: document.querySelector("#navigationRouteName"),
    navigationRouteDetail: document.querySelector("#navigationRouteDetail"),
    startInput: document.querySelector("#startInput"),
    startPickButton: document.querySelector("#startPickButton"),
    navigationModeSummary: document.querySelector("#navigationModeSummary"),
    navigateButton: document.querySelector("#navigateButton"),
    startSportButton: document.querySelector("#startSportButton"),
    navigationStatus: document.querySelector("#navigationStatus"),
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
    const routes = catalog.filter((route) => route.route_mode === tab.dataset.routeMode);
    tab.querySelector("span").textContent = `${routes.length} 条`;
  }
}

function routeDistanceBand(route) {
  const distance = Number(route.target_distance_m || route.distance_m || 0);
  const bands = {
    walk: [[500, 2000], [2000, 3500], [3500, 5000]],
    run: [[1000, 5000], [5000, 10000], [10000, 15000]],
    bike: [[5000, 10000], [10000, 20000], [20000, 30000]],
  }[route.route_mode] || [];
  const index = bands.findIndex(([lower, upper], bandIndex) =>
    distance >= lower && (distance < upper || bandIndex === bands.length - 1 && distance === upper));
  return ["short", "medium", "long"][index] || "outside";
}

function renderNavigationMode(route, controls) {
  controls.navigationModeSummary.textContent = route?.route_mode === "bike" ? "骑行" : "步行";
}

function resetSelectionControls(controls) {
  controls.zoneFilter.value = "all";
  controls.sportModeTabs.forEach((tab, index) => {
    const active = index === 0;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  controls.distanceFilter.value = "all";
}

function findRoute(catalog, routeId) {
  return catalog.find((route) => route.route_id === routeId);
}

function formatPoint(point) {
  return `${Number(point.lng_gcj02).toFixed(6)},${Number(point.lat_gcj02).toFixed(6)}`;
}

function formatOrigin(point) {
  return point.label || formatPoint(point);
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function errorMessage(error) {
  return error instanceof Error ? error.message : "操作失败，请重试。";
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
