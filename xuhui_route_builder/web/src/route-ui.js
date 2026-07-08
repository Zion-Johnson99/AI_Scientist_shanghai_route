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

export function renderRoutePlanner(catalog, options) {
  const controls = getControls();
  populateZoneFilter(controls.zoneFilter, catalog);
  populateNavigationRoutes(controls.navigationRouteSelect, catalog);

  const state = {
    activeAppTab: "selection",
    activeResultTab: "recommend",
    selectedRouteId: catalog[0]?.route_id || "",
    groups: buildGroups(catalog, readSelectionFilters(controls)),
  };

  bindAppTabs(state, controls, options);
  bindResultTabs(state, controls, options);
  bindSelectionControls(catalog, state, controls, options);
  bindNavigationControls(catalog, state, controls, options);

  paintResults(state, controls, options);
  if (catalog[0]) {
    renderDetail(catalog[0], controls.detail);
  }
}

export function filterCandidateRoutes(catalog, filters) {
  const textFilters = [filters.keyword].map(normalizeText).filter(Boolean);
  const preferredKeywords = filters.preferences.flatMap((preference) => PREFERENCE_KEYWORDS[preference] || []);

  return catalog
    .map((route, index) => ({
      route,
      index,
      score: scoreRoute(route, textFilters, preferredKeywords),
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
      if (!textFilters.length && !preferredKeywords.length) {
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
    state.groups = buildGroups(catalog, readSelectionFilters(controls));
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
      request = readNavigationRequest(route, controls);
    } catch (error) {
      controls.navigationStatus.textContent = error.message;
      return;
    }
    controls.navigationStatus.textContent = "正在调用高德路线导航...";
    options.onNavigate(request)
      .then((summary) => {
        controls.navigationStatus.textContent = summary;
      })
      .catch((error) => {
        controls.navigationStatus.textContent = error.message;
      });
  });

  for (const input of [controls.startInput, controls.endInput]) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        controls.navigateButton.click();
      }
    });
  }
}

function runSearch(catalog, state, controls, options) {
  state.groups = buildGroups(catalog, readSelectionFilters(controls));
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
    options.onSearch([], "");
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
  options.onSearch(visibleOnMap, selectedRoute.route_id);
}

function selectRoute(route, state, controls, options, flags = {}) {
  state.selectedRouteId = route.route_id;
  setActive(route.route_id);
  renderDetail(route, controls.detail);
  syncNavigationRoute(route.route_id, controls);
  options.onSelect(route.route_id);
  if (!flags.skipSearch) {
    const visibleRoutes = state.groups[state.activeResultTab] || [];
    options.onSearch(visibleRoutes.slice(0, 24), route.route_id);
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

function readNavigationRequest(route, controls) {
  const originText = controls.startInput.value.trim();
  const destinationText = controls.endInput.value.trim() || route?.start_entry_location || route?.end_entry_location || route?.start_entry_name || "";
  if (!originText) {
    throw new Error("请先输入导航起点。");
  }
  if (!destinationText) {
    throw new Error("缺少目标入口，请先选择候选路线。");
  }
  return {
    originText,
    destinationText,
    mode: controls.navigationMode.value,
    routeId: route?.route_id || "",
    routeName: route?.route_name || "",
  };
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
  detail.innerHTML = `
    <h2>${escapeHtml(route.route_name)}</h2>
    <p>${escapeHtml(route.region_zone)} · ${MODE_LABELS[route.route_mode] || route.route_mode} · ${escapeHtml(route.distance_level)}</p>
    <dl>
      <div><dt>入口</dt><dd>${escapeHtml(startName)} → ${escapeHtml(endName)}</dd></div>
      <div><dt>距离</dt><dd>${Number(route.distance_m || route.target_distance_m || 0).toFixed(0)} 米，预计 ${Number(route.duration_min || 0).toFixed(1)} 分钟</dd></div>
      <div><dt>标签</dt><dd>${escapeHtml(tags)}</dd></div>
    </dl>
    <p>${escapeHtml(route.score_note || "当前阶段展示候选路线，后续接入环境暴露评分。")}</p>
  `;
}

function scoreRoute(route, textFilters, preferredKeywords) {
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
  ].join(" "));

  let score = 0;
  for (const text of textFilters) {
    if (searchable.includes(text)) {
      score += 8;
    }
  }
  for (const keyword of preferredKeywords.map(normalizeText)) {
    if (searchable.includes(keyword)) {
      score += 3;
    }
  }
  return score;
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
    startInput: document.querySelector("#startInput"),
    endInput: document.querySelector("#endInput"),
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
