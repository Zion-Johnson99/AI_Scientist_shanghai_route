import { createRouteCard, routeCardModel } from "./route-card.js?v=20260831-ui-35";

export function renderRoutePlanner(catalog, options) {
  const controls = getControls();
  updateModeCounts(catalog, controls);

  const state = {
    selectedRouteId: "",
    hoveredRouteId: null,
    listScrollTop: 0,
    filters: readSelectionFilters(controls),
    filteredRoutes: [],
    directNavigationStatus: "idle",
    directNavigationRevision: 0,
  };

  bindSelectionControls(catalog, state, controls, options);
  initializeRouteSelection(catalog, state, controls, options);

  return {
    showBrowse() {
      controls.selectionView.hidden = false;
      renderBrowseRouteList(state, controls, options);
      renderSelectionPreview(state.filteredRoutes, catalog, state, controls, options);
    },
    showBrowsePreviews() {
      renderSelectionPreview(state.filteredRoutes, catalog, state, controls, options);
    },
    selectRoute(routeId) {
      const route = findRoute(catalog, routeId);
      if (!route) return null;
      showRoute(route, state, controls, options);
      return route;
    },
    restoreBrowseOverview() {
      controls.selectionView.hidden = false;
      renderBrowseRouteList(state, controls, options);
      renderSelectionPreview(state.filteredRoutes, catalog, state, controls, options);
      return [...state.filteredRoutes];
    },
    setHoveredRoute(routeId) {
      setHoveredRoute(state, controls, routeId);
    },
    async startDirectNavigation(routeId, origin) {
      const route = findRoute(catalog, routeId);
      if (!route) throw new Error(`路线 ${routeId || "未知"} 不存在。`);
      const revision = ++state.directNavigationRevision;
      state.directNavigationStatus = "planning";
      try {
        const payload = await startDirectNavigation(route, origin, {
          ...options,
          shouldStart: () => revision === state.directNavigationRevision,
        });
        state.directNavigationStatus = "previewing";
        return payload;
      } catch (error) {
        if (revision === state.directNavigationRevision) {
          state.directNavigationStatus = "idle";
        }
        throw error;
      }
    },
    endNavigationPreview() {
      const wasActive = state.directNavigationStatus !== "idle";
      state.directNavigationRevision += 1;
      state.directNavigationStatus = "idle";
      if (wasActive) options.onEndInlineNavigation?.();
      return wasActive;
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
    cancelDirectNavigation(state);
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
  controls.distanceFilter.addEventListener("change", refreshPreview);
  controls.preferenceFilter.addEventListener("change", refreshPreview);
  controls.routeList.addEventListener("scroll", () => {
    state.listScrollTop = controls.routeList.scrollTop;
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

export async function startDirectNavigation(route, origin, options = {}) {
  const request = buildNavigationRequest(route, origin);
  if (typeof options.onNavigate !== "function") {
    throw new Error("接驳规划暂不可用。");
  }
  const plan = await options.onNavigate(request);
  if (!plan) {
    throw new Error(`路线 ${request.routeId} 的接驳规划未返回结果。`);
  }
  if (options.shouldStart && !options.shouldStart()) {
    throw new Error("接驳规划已取消，请重新开始。");
  }
  if (typeof options.onStartInlineNavigation !== "function") {
    throw new Error("导航预览暂不可用。");
  }
  const payload = { plan, request };
  options.onStartInlineNavigation(payload);
  return payload;
}

export function isMapLocationSelectionAllowed({ detailOpen, navigationActive }) {
  return !detailOpen && !navigationActive;
}

export function selectBestRoute(routes) {
  return routes.find((route) => route.validation_status === "accepted") || null;
}

function initializeRouteSelection(catalog, state, controls, options) {
  state.filters = readSelectionFilters(controls);
  state.filteredRoutes = filterCandidateRoutes(catalog, state.filters);
  state.selectedRouteId = "";
  state.hoveredRouteId = null;
  state.listScrollTop = 0;
  renderBrowseRouteList(state, controls, options);
  options.onRouteMetrics?.(null);
  renderSelectionPreview(state.filteredRoutes, catalog, state, controls, options);
}

function renderBrowseRouteList(state, controls, options) {
  controls.routeList.replaceChildren();
  controls.routeOptionCount.textContent = `${state.filteredRoutes.length} 条路线`;
  controls.routeEmpty.hidden = state.filteredRoutes.length > 0;
  controls.routeList.hidden = state.filteredRoutes.length === 0;
  for (const route of state.filteredRoutes) {
    const model = routeCardModel(route, {
      environment: options.getRouteEnvironment?.(route.route_id),
      selected: route.route_id === state.selectedRouteId,
    });
    const card = createRouteCard(model, {
      onSelect(routeId) {
        const selected = findRoute(state.filteredRoutes, routeId);
        if (selected) showRoute(selected, state, controls, options);
      },
      onPreview(routeId) {
        setHoveredRoute(state, controls, routeId);
        options.onPreviewRoute?.(routeId);
      },
    });
    if (route.route_id === state.hoveredRouteId) card.classList.add("is-previewed");
    controls.routeList.append(card);
  }
  controls.routeList.scrollTop = state.listScrollTop;
}

function showRoute(route, state, controls, options) {
  state.listScrollTop = controls.routeList.scrollTop;
  state.selectedRouteId = route.route_id;
  renderBrowseRouteList(state, controls, options);
  cancelDirectNavigation(state);
  options.onSelect?.(route.route_id);
  options.onRouteMetrics?.(route);
}

function setHoveredRoute(state, controls, routeId) {
  state.hoveredRouteId = findRoute(state.filteredRoutes, routeId) ? routeId : null;
  for (const card of controls.routeList.children) {
    card.classList.toggle("is-previewed", card.dataset.routeId === state.hoveredRouteId);
  }
}

function renderSelectionPreview(routes, catalog, state, controls, options) {
  options.onPreviewRoutes?.(routes, (routeId) => {
    const route = findRoute(routes, routeId);
    if (route) {
      showRoute(route, state, controls, options);
    }
  }, (routeId) => {
    setHoveredRoute(state, controls, routeId);
    options.onPreviewRoute?.(routeId);
  });
}

function readSelectionFilters(controls) {
  return {
    zone: "all",
    keyword: "",
    mode: controls.sportModeTabs.find((tab) => tab.classList.contains("active"))?.dataset.routeMode || "walk",
    distance: controls.distanceFilter.value,
    preferences: controls.preferenceFilter.value === "all" ? [] : [controls.preferenceFilter.value],
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

function cancelDirectNavigation(state) {
  state.directNavigationRevision += 1;
  state.directNavigationStatus = "idle";
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
    sportModeTabs: [...document.querySelectorAll("#sportModeTabs [data-route-mode]")],
    distanceFilter: document.querySelector("#distanceFilter"),
    preferenceFilter: document.querySelector("#preferenceFilter"),
    resetButton: document.querySelector("#resetButton"),
    routeOptionCount: document.querySelector("#routeOptionCount"),
    routeList: document.querySelector("#browseRouteList"),
    routeEmpty: document.querySelector("#browseRouteEmpty"),
  };
}

function updateModeCounts(catalog, controls) {
  for (const tab of controls.sportModeTabs) {
    const routes = catalog.filter((route) => route.route_mode === tab.dataset.routeMode);
    const modeLabel = tab.querySelector("b")?.textContent?.trim() || "运动";
    tab.setAttribute("aria-label", `${modeLabel}，${routes.length} 条路线`);
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

function resetSelectionControls(controls) {
  controls.sportModeTabs.forEach((tab, index) => {
    const active = index === 0;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  controls.distanceFilter.value = "all";
  controls.preferenceFilter.value = "all";
}

function findRoute(catalog, routeId) {
  return catalog.find((route) => route.route_id === routeId);
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}
