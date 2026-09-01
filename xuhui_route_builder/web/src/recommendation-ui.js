import { normalizeHealthProfile } from "./profile-store.js";
import { createRouteCard, routeCardModel } from "./route-card.js?v=20260901-environment-2";

export const DEFAULT_RECOMMENDATION_LOCATION = Object.freeze({
  label: "上海交通大学徐汇校区",
  lng_gcj02: 121.433095,
  lat_gcj02: 31.199005,
});

export function buildInitialRecommendationResult({
  catalog,
  questionnaire,
  answers,
  location,
  limit = 3,
  getRouteEnvironment = () => null,
}) {
  const origin = normalizeLocation(location);
  if (!origin) throw new Error("默认推荐位置无效。");
  const distance = distanceOption(questionnaire, answers?.route_mode, answers?.distance_range);
  const searchRadius = nearbyRadiusFromScope(String(answers?.search_scope || ""));
  const routeShape = String(answers?.route_shape || "any");
  const candidates = (catalog || [])
    .map((route, index) => ({
      route,
      index,
      accessDistanceM: startAccessDistance(route, origin),
    }))
    .filter(({ route, accessDistanceM }) => (
      route?.route_mode === answers?.route_mode
      && route?.validation_status === "accepted"
      && Number(route?.distance_m) >= Number(distance.distance_min_m)
      && Number(route?.distance_m) <= Number(distance.distance_max_m)
      && (routeShape === "any" || route?.route_shape === routeShape)
      && (searchRadius === null || accessDistanceM <= searchRadius)
    ))
    .sort((left, right) => left.accessDistanceM - right.accessDistanceM || left.index - right.index)
    .slice(0, Math.max(0, Number(limit) || 0));

  return {
    status: candidates.length ? "ok" : "no_candidates",
    decision_source: "local_nearby",
    decision_summary: `已按起点距${String(location?.label || "默认位置")}的接驳距离排序。`,
    risk: { status: "ok", reasons: [] },
    final_routes: candidates.map(({ route, accessDistanceM }, index) => ({
      final_rank: index + 1,
      personalized_fit: `路线起点距默认位置约 ${formatAccessDistance(accessDistanceM)}`,
      advantages: [],
      suggestions: [],
      cautions: [],
      route: {
        data_confidence: null,
        matched_preferences: [],
        risk_notes: [],
        start_access_distance_m: accessDistanceM,
        environment_summary: recommendationEnvironmentSummary(getRouteEnvironment(route.route_id)),
        route: { ...route },
      },
    })),
  };
}

export function buildUserProfile({ questionnaire, answers, profile, location, now = () => new Date() }) {
  const distance = distanceOption(questionnaire, answers?.route_mode, answers?.distance_range);
  const targetTime = resolveTargetTime(answers, now);
  const searchScope = String(answers?.search_scope || "");
  const nearbyRadius = nearbyRadiusFromScope(searchScope);
  const origin = normalizeLocation(location);
  if (!origin) {
    throw new Error("请先选择位置。");
  }
  const areaIds = searchScope === "area" ? selectedAreaIds(questionnaire, answers?.area_id) : [];

  return {
    route_mode: requiredOption(questionnaire?.route_modes, answers?.route_mode, "运动方式"),
    target_time: targetTime,
    distance_min_m: distance.distance_min_m,
    target_distance_m: distance.target_distance_m,
    distance_max_m: distance.distance_max_m,
    origin,
    search_radius_m: nearbyRadius,
    area_ids: areaIds,
    goal: requiredOption(questionnaire?.goals, answers?.goal, "运动目标"),
    experience: String(profile?.experience || "regular"),
    age_group: String(profile?.age_group || "undisclosed"),
    sensitivities: cleanSelections(profile?.sensitivities, questionnaire?.sensitivities),
    route_shape: requiredOption(questionnaire?.route_shapes, answers?.route_shape, "路线形态"),
    interests: cleanSelections(answers?.interests, questionnaire?.interests),
    free_text: String(answers?.free_text || "").trim().slice(0, 500),
  };
}

export function createProfileDialog({ host, profile, onSave } = {}) {
  if (!host) {
    throw new Error("缺少档案弹层挂载容器。");
  }
  let draft = normalizeHealthProfile(profile);
  const dialog = element("dialog", "profile-dialog");
  dialog.setAttribute("aria-labelledby", "profileDialogTitle");
  dialog.addEventListener("cancel", () => dialog.close());
  host.append(dialog);

  function renderDialog() {
    const shell = element("div", "profile-dialog__shell");
    const header = element("header", "profile-dialog__header");
    const heading = element("div", "profile-dialog__heading");
    const title = element("h2", "profile-dialog__title", "建立健康档案");
    title.id = "profileDialogTitle";
    heading.append(title, element("p", "profile-dialog__intro", "用于调整距离匹配与环境提醒。"));
    header.append(heading);
    shell.append(header);
    shell.append(profileChoiceGroup({
      label: "年龄",
      options: [
        ["under_18", "18 岁以下"],
        ["18_39", "18-39 岁"],
        ["40_59", "40-59 岁"],
        ["60_plus", "60 岁及以上"],
        ["undisclosed", "暂不填写"],
      ],
      selected: draft.age_group,
      onChange(value) {
        draft.age_group = value;
        renderDialog();
      },
    }));
    const genderGroup = profileChoiceGroup({
      label: "性别",
      options: [["male", "男"], ["female", "女"], ["undisclosed", "暂不填写"]],
      selected: draft.gender,
      onChange(value) {
        draft.gender = value;
        renderDialog();
      },
    });
    genderGroup.append(element("p", "profile-dialog__privacy", "仅保存在本机，暂不参与推荐。"));
    shell.append(genderGroup);
    shell.append(profileChoiceGroup({
      label: "运动经验",
      options: [["beginner", "初学"], ["regular", "日常运动"], ["frequent", "高频训练"]],
      selected: draft.experience,
      onChange(value) {
        draft.experience = value;
        renderDialog();
      },
    }));
    shell.append(profileChoiceGroup({
      label: "环境敏感项",
      options: [["air", "空气"], ["pollen", "花粉"], ["heat", "高温"], ["noise", "噪声"]],
      selected: draft.sensitivities,
      multiple: true,
      onChange(value) {
        draft.sensitivities = toggleValue(draft.sensitivities, value);
        renderDialog();
      },
    }));
    const actions = element("footer", "profile-dialog__actions");
    const skip = element("button", "profile-dialog__skip", "暂时跳过");
    skip.type = "button";
    skip.addEventListener("click", saveDraft);
    const save = element("button", "profile-dialog__save", "保存档案");
    save.type = "button";
    save.addEventListener("click", saveDraft);
    actions.append(skip, save);
    shell.append(actions);
    dialog.replaceChildren(shell);
  }

  function saveDraft() {
    draft = normalizeHealthProfile(draft);
    onSave?.({ ...draft, sensitivities: [...draft.sensitivities] });
    dialog.close();
  }

  renderDialog();
  return {
    open() {
      renderDialog();
      if (!dialog.open) {
        dialog.showModal();
      }
    },
    close() {
      if (dialog.open) {
        dialog.close();
      }
    },
    setProfile(value) {
      draft = normalizeHealthProfile(value);
      renderDialog();
    },
    isOpen() {
      return Boolean(dialog.open);
    },
  };
}

export function buildRecommendationViewModel(result, currentRouteId = null, getRouteEnvironment = () => null) {
  if (result?.view === "loading") {
    return {
      kind: "loading",
      title: "正在为你匹配",
      steps: [
        { label: "汇总偏好", state: "done" },
        { label: "匹配路线", state: "active" },
        { label: "准备结果", state: "pending" },
      ],
    };
  }
  if (result?.view === "error") {
    return { kind: "error", title: "暂时没有完成推荐", message: String(result.message || "请稍后重试。") };
  }
  if (result?.status === "paused") {
    return {
      kind: "paused",
      title: "暂缓户外运动",
      message: result?.risk?.reasons?.join("；") || "当前环境风险较高，请稍后再看。",
    };
  }
  const routes = [...(result?.final_routes || [])]
    .sort((left, right) => Number(left?.final_rank || 999) - Number(right?.final_rank || 999))
    .slice(0, 3)
    .map((route) => normalizeFinalRoute(route, getRouteEnvironment))
    .filter(Boolean);
  if (result?.status === "no_candidates" || !routes.length) {
    return {
      kind: "no_candidates",
      title: "这组条件暂无合适路线",
      message: "试试扩大范围、调整距离或放宽路线形态。",
    };
  }
  const selectedRouteId = routes.some((route) => route.routeId === currentRouteId) ? currentRouteId : null;
  const explanationSource = String(
    result?.decision_source || (result?.status === "degraded" ? "python_fallback" : "qwen"),
  );
  const stableRoutes = routes.map((route, index) => ({
    ...route,
    isPrimary: index === 0,
    isSelected: route.routeId === selectedRouteId,
    explanationSource,
  }));
  return {
    kind: result.status === "degraded" ? "degraded" : "result",
    notice: result.status === "degraded" ? "个性化解释已简化，路线排序由本地评分完成。" : "",
    summary: String(result.decision_summary || ""),
    routes: stableRoutes,
    selectedRouteId,
    selectedRoute: stableRoutes.find((route) => route.isSelected) || null,
  };
}

export function createRecommendationUI({
  container,
  filterHost = null,
  questionnaire,
  profile,
  location = null,
  onRecommend,
  onReloadQuestionnaire,
  onInterpretIntent,
  onShowRoutes,
  onPreviewRoute,
  onSelectRoute,
  onReturnRouteOverview,
  onRestartRecommendation,
  onChatStateChange,
  onRouteModeChange,
  getRouteEnvironment = () => null,
  shouldSelectRoute = () => true,
} = {}) {
  if (!container) {
    throw new Error("缺少推荐面板容器。");
  }
  let currentQuestionnaire = questionnaire;
  let currentProfile = profile;
  let currentLocation = location;
  let currentResult = null;
  let currentRouteId = null;
  let hoveredRouteId = null;
  let viewState = "questionnaire";
  let errorMessage = "";
  let recommendationBusy = false;
  let openFilterKey = null;
  let filterTrack = null;
  let filterScrollLeft = 0;
  let pendingPopoverFocus = false;
  let filterChips = new Map();
  let detailOpen = false;
  let filtersVisible = true;
  let filterRoot = null;
  let requestRevision = 0;
  let intentRevision = 0;
  let chatBusy = false;
  let chatDraft = "";
  let chatHistory = [];
  let intentPatch = {};
  let chatError = "";
  let chatProgress = "";
  let chatResultVisible = false;
  let preChatState = null;
  const answers = defaultAnswers(questionnaire);

  const controller = {
    showQuestionnaire() {
      requestRevision += 1;
      recommendationBusy = false;
      switchProductView("questionnaire");
      currentRouteId = null;
      onReturnRouteOverview?.();
      render();
    },
    restartRecommendation() {
      const routeMode = answers.route_mode;
      const reset = defaultAnswers(currentQuestionnaire);
      reset.route_mode = routeMode;
      reset.distance_range = defaultDistanceRange(currentQuestionnaire, routeMode);
      Object.assign(answers, reset);
      requestRevision += 1;
      intentRevision += 1;
      currentResult = null;
      currentRouteId = null;
      hoveredRouteId = null;
      switchProductView("questionnaire");
      errorMessage = "";
      chatBusy = false;
      chatDraft = "";
      chatHistory = [];
      intentPatch = {};
      chatError = "";
      chatProgress = "";
      chatResultVisible = false;
      render();
      onRestartRecommendation?.();
    },
    showLoading() {
      recommendationBusy = true;
      render();
    },
    showResult(result) {
      recommendationBusy = false;
      errorMessage = "";
      currentResult = result;
      currentRouteId = null;
      switchProductView("result");
      render();
      const model = buildRecommendationViewModel(result, null, getRouteEnvironment);
      if (["result", "degraded"].includes(model.kind) && shouldSelectRoute()) {
        onShowRoutes?.(model.routes.map((route) => route.source), { source: "recommendation" });
      }
    },
    showError(error) {
      recommendationBusy = false;
      errorMessage = String(error?.message || error || "推荐服务暂时不可用。");
      switchProductView("error");
      render();
    },
    setQuestionnaire(value) {
      currentQuestionnaire = value;
      Object.assign(answers, defaultAnswers(value));
      render();
    },
    setProfile(value) {
      currentProfile = value;
      render();
    },
    setLocation(value) {
      currentLocation = value;
      render();
    },
    refreshEnvironment() {
      if (currentResult && ["result", "chat"].includes(viewState)) render();
    },
    setDetailOpen(value) {
      detailOpen = Boolean(value);
      if (detailOpen) {
        openFilterKey = null;
        pendingPopoverFocus = false;
      }
      renderFilters();
    },
    setFiltersVisible(value) {
      filtersVisible = Boolean(value);
      if (!filtersVisible) {
        openFilterKey = null;
        pendingPopoverFocus = false;
      }
      renderFilters();
    },
    setRouteMode(value) {
      if (!(currentQuestionnaire?.route_modes || []).some((option) => option.value === value)) return;
      const modeChanged = answers.route_mode !== value;
      answers.route_mode = value;
      const available = currentQuestionnaire?.distance_ranges?.[value] || [];
      if (modeChanged || !available.some((option) => option.value === answers.distance_range)) {
        answers.distance_range = defaultDistanceRange(currentQuestionnaire, value);
      }
      render();
    },
    setHoveredRoute(routeId) {
      hoveredRouteId = routeId || null;
      if (["result", "chat"].includes(viewState)) render();
    },
    selectRoute(routeId) {
      const model = buildRecommendationViewModel(currentResult, routeId, getRouteEnvironment);
      if (!["result", "degraded"].includes(model.kind) || !model.selectedRoute) return;
      currentRouteId = routeId;
      hoveredRouteId = null;
      if (viewState !== "chat") viewState = "result";
      render();
      onSelectRoute?.(routeId, model.selectedRoute);
    },
    getCurrentRouteId() {
      return currentRouteId;
    },
    getResultRoutes() {
      const model = buildRecommendationViewModel(currentResult, currentRouteId, getRouteEnvironment);
      return ["result", "degraded"].includes(model.kind) ? model.routes.map((route) => route.source) : [];
    },
    getAnswers() {
      return { ...answers, interests: [...answers.interests] };
    },
    openChat,
    newChat,
    closeChat,
    isChatOpen() {
      return viewState === "chat";
    },
    returnToOverview,
  };

  container.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !currentRouteId) return;
    event.preventDefault();
    returnToOverview();
  });
  const filterDocument = filterHost?.ownerDocument || globalThis.document;
  filterDocument?.addEventListener?.("pointerdown", (event) => {
    if (!openFilterKey || filterRoot?.contains?.(event.target)) return;
    closeFilter({ restoreFocus: true });
  });

  function returnToOverview() {
    currentRouteId = null;
    if (preChatState) preChatState.currentRouteId = null;
    hoveredRouteId = null;
    render();
    onReturnRouteOverview?.();
  }

  function openChat() {
    if (viewState === "chat") return;
    preChatState = {
      viewState,
      currentRouteId,
      scrollTop: Number(container.scrollTop || 0),
    };
    viewState = "chat";
    render();
    container.scrollTop = 0;
    onChatStateChange?.(true);
  }

  function newChat() {
    const chatWasOpen = viewState === "chat";
    if (!chatWasOpen) {
      preChatState = {
        viewState,
        currentRouteId,
        scrollTop: Number(container.scrollTop || 0),
      };
      viewState = "chat";
    }
    intentRevision += 1;
    chatBusy = false;
    chatDraft = "";
    chatHistory = [];
    intentPatch = {};
    chatError = "";
    chatProgress = "";
    chatResultVisible = false;
    currentRouteId = null;
    hoveredRouteId = null;
    render();
    container.scrollTop = 0;
    onReturnRouteOverview?.();
    if (!chatWasOpen) onChatStateChange?.(true);
  }

  function closeChat() {
    if (viewState !== "chat") return;
    intentRevision += 1;
    chatBusy = false;
    chatProgress = "";
    const previous = preChatState || {
      viewState: "questionnaire",
      currentRouteId: null,
      scrollTop: 0,
    };
    preChatState = null;
    viewState = previous.viewState;
    currentRouteId = previous.currentRouteId;
    render();
    container.scrollTop = previous.scrollTop;
    onChatStateChange?.(false);
  }

  function switchProductView(nextView) {
    const chatWasOpen = viewState === "chat";
    viewState = nextView;
    if (!chatWasOpen) return;
    preChatState = null;
    onChatStateChange?.(false);
  }

  function render() {
    const root = element("section", "recommendation-panel");
    root.setAttribute("aria-label", "个性化路线推荐");
    if (viewState === "chat") {
      root.append(renderChat());
    } else {
      root.append(renderWorkspace());
    }
    container.replaceChildren(root);
    renderFilters();
  }

  function renderWorkspace() {
    const workspace = element("section", "recommendation-workspace");
    const content = element("div", "recommendation-workspace__content");
    const model = buildRecommendationViewModel(currentResult, currentRouteId, getRouteEnvironment);
    const hasRoutes = ["result", "degraded"].includes(model.kind);
    if (hasRoutes) {
      const heading = currentResult?.decision_source === "local_nearby" ? "附近路线" : "为你推荐";
      content.append(element("h2", "recommendation-results__title", heading));
      if (model.notice) {
        const notice = element("p", "recommendation-state__notice", model.notice);
        notice.setAttribute("role", "status");
        content.append(notice);
      }
      const list = element("div", "recommendation-results-list");
      model.routes.forEach((route, index) => list.append(renderRouteCard(route, index)));
      content.append(list);
    } else if (viewState === "error") {
      content.append(renderWorkspaceError());
    } else if (currentResult && ["paused", "no_candidates"].includes(model.kind)) {
      const state = element("div", `recommendation-state recommendation-state--${model.kind}`);
      state.append(
        element("h2", "recommendation-state__title", model.title),
        element("p", "recommendation-state__message", model.message),
      );
      content.append(state);
    } else {
      content.append(element("p", "recommendation-workspace__empty", "设置顶部筛选条后，为你匹配附近路线。"));
    }
    if (errorMessage && hasRoutes) {
      const warning = element("p", "recommendation-workspace__error", errorMessage);
      warning.setAttribute("role", "alert");
      content.append(warning);
    }
    if (recommendationBusy) content.classList.add("is-loading");

    const footer = element("footer", "recommendation-workspace__footer");
    const form = element("form", "recommendation-form");
    form.append(textAreaField(answers.free_text, (value) => {
      answers.free_text = value;
    }));
    const submit = element(
      "button",
      `recommendation-form__submit${recommendationBusy ? " is-loading" : ""}`,
      recommendationBusy ? "正在推荐中" : "为我推荐路线",
    );
    submit.type = "submit";
    submit.disabled = recommendationBusy;
    submit.setAttribute("aria-busy", String(recommendationBusy));
    form.append(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (recommendationBusy) return;
      const revision = ++requestRevision;
      try {
        const payload = buildUserProfile({
          questionnaire: currentQuestionnaire,
          answers,
          profile: currentProfile,
          location: currentLocation,
        });
        await runRecommendation(payload, revision);
      } catch (error) {
        if (revision !== requestRevision) return;
        controller.showError(error);
      }
    });
    footer.append(form);
    workspace.append(content, footer);
    return workspace;
  }

  function renderWorkspaceError() {
    const region = element("div", "recommendation-state recommendation-state--error");
    region.setAttribute("role", "alert");
    region.append(
      element("h2", "recommendation-state__title", "暂时没有完成推荐"),
      element("p", "recommendation-state__message", errorMessage || "请稍后重试。"),
    );
    if (!currentQuestionnaire) {
      const retry = element("button", "recommendation-state__retry", "重新加载问卷");
      retry.type = "button";
      retry.addEventListener("click", async () => {
        controller.showLoading();
        try {
          const nextQuestionnaire = await onReloadQuestionnaire?.();
          if (!nextQuestionnaire) throw new Error("问卷服务未返回内容。");
          controller.setQuestionnaire(nextQuestionnaire);
          controller.showQuestionnaire();
        } catch (error) {
          controller.showError(error);
        }
      });
      region.append(retry);
    }
    return region;
  }

  function renderFilters() {
    if (!filterHost) return;
    if (filterTrack) filterScrollLeft = Number(filterTrack.scrollLeft || 0);
    if (!filterRoot) {
      filterRoot = element("section", "recommendation-filters");
      filterRoot.setAttribute("aria-label", "路线筛选");
      filterRoot.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !openFilterKey) return;
        event.preventDefault();
        closeFilter({ restoreFocus: true });
      });
      filterHost.append(filterRoot);
    }
    filterRoot.className = `recommendation-filters${detailOpen ? " is-detail-open" : ""}`;
    filterRoot.hidden = !filtersVisible || viewState === "chat";
    const viewport = element("div", "recommendation-filters__viewport");
    const track = element("div", "recommendation-filters__track");
    viewport.append(track);
    const definitions = filterDefinitions();
    const nextChips = new Map();
    let activeChip = null;
    definitions.forEach((definition) => {
      const item = element("div", "recommendation-filter");
      const chip = element("button", `recommendation-filter__chip${openFilterKey === definition.key ? " is-open" : ""}`);
      chip.type = "button";
      chip.setAttribute("aria-label", `设置${definition.label}`);
      chip.setAttribute("aria-expanded", String(openFilterKey === definition.key));
      chip.append(
        filterIcon(definition.icon),
        element("span", "recommendation-filter__label", definition.label),
      );
      chip.addEventListener("click", () => {
        const opening = openFilterKey !== definition.key;
        if (!opening) {
          closeFilter({ restoreFocus: true });
          return;
        }
        chip.setAttribute("aria-expanded", "true");
        openFilterKey = definition.key;
        pendingPopoverFocus = true;
        renderFilters();
      });
      if (openFilterKey === definition.key) activeChip = chip;
      nextChips.set(definition.key, chip);
      item.append(chip);
      track.append(item);
    });
    filterRoot.replaceChildren(viewport);
    track.scrollLeft = filterScrollLeft;
    track.addEventListener("scroll", () => {
      filterScrollLeft = Number(track.scrollLeft || 0);
    });
    filterTrack = track;
    filterChips = nextChips;
    const activeDefinition = definitions.find((definition) => definition.key === openFilterKey);
    if (activeDefinition) {
      const popover = renderFilterPopover(activeDefinition);
      popover.tabIndex = -1;
      filterRoot.append(popover);
      positionFilterPopover(popover, activeChip, filterRoot);
      if (pendingPopoverFocus) {
        pendingPopoverFocus = false;
        popover.focus?.();
      }
    }
  }

  function closeFilter({ restoreFocus }) {
    const triggerKey = openFilterKey;
    if (!triggerKey) return;
    openFilterKey = null;
    pendingPopoverFocus = false;
    renderFilters();
    if (restoreFocus) filterChips.get(triggerKey)?.focus?.();
  }

  function filterDefinitions() {
    const interests = currentQuestionnaire?.interests || [];
    const byValues = (values) => interests.filter((option) => values.includes(option.value));
    return [
      { key: "target_time", icon: "time", label: "时间", options: currentQuestionnaire?.target_times || [] },
      { key: "distance_range", icon: "distance", label: "距离", options: currentQuestionnaire?.distance_ranges?.[answers.route_mode] || [] },
      { key: "goal", icon: "goal", label: "运动目标", options: currentQuestionnaire?.goals || [] },
      { key: "search_scope", icon: "scope", label: "搜索范围", options: currentQuestionnaire?.search_scopes || [] },
      { key: "route_shape", icon: "route", label: "路线形态", options: currentQuestionnaire?.route_shapes || [] },
      { key: "rest_stops", icon: "rest", label: "休息与补给", options: byValues(["coffee", "toilet", "convenience"]), multiple: true },
      { key: "scenery", icon: "scenery", label: "景观与环境", options: byValues(["waterfront", "park", "quiet"]), multiple: true },
    ];
  }

  function renderFilterPopover(definition) {
    const popover = element("div", "recommendation-filter__popover");
    const titleId = `recommendationFilterTitle-${definition.key}`;
    popover.id = `recommendationFilter-${definition.key}`;
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-labelledby", titleId);
    const header = element("header", "recommendation-filter__header");
    const title = element("h2", "recommendation-filter__title", definition.label);
    title.id = titleId;
    const close = element("button", "recommendation-filter__close");
    close.type = "button";
    close.setAttribute("aria-label", `关闭${definition.label}筛选`);
    close.addEventListener("click", () => closeFilter({ restoreFocus: true }));
    header.append(title, close);
    const options = element("div", "recommendation-filter__options");
    options.setAttribute("role", definition.multiple ? "group" : "radiogroup");
    if (definition.multiple) {
      options.append(filterOptionButton(definition, { value: "", label: "不限" }, !definition.options.some((option) => answers.interests.includes(option.value))));
    }
    definition.options.forEach((option) => {
      const selected = definition.multiple
        ? answers.interests.includes(option.value)
        : answers[definition.key] === option.value;
      options.append(filterOptionButton(definition, option, selected));
    });
    const body = element("div", "recommendation-filter__body");
    body.append(options);
    if (definition.key === "target_time" && answers.target_time === "custom") {
      body.append(inputField("自定义时间", "datetime-local", answers.custom_time, (value) => {
        answers.custom_time = value;
      }));
    }
    if (definition.key === "search_scope" && answers.search_scope === "area") {
      body.append(selectField("指定片区", currentQuestionnaire?.areas, answers.area_id, (value) => {
        answers.area_id = value;
      }));
    }
    const footer = element("footer", "recommendation-filter__footer");
    const reset = element("button", "recommendation-filter__reset", "恢复默认");
    reset.type = "button";
    reset.disabled = filterUsesDefault(definition);
    reset.addEventListener("click", () => {
      resetFilter(definition);
      pendingPopoverFocus = true;
      render();
    });
    const done = element("button", "recommendation-filter__done", "完成");
    done.type = "button";
    done.addEventListener("click", () => closeFilter({ restoreFocus: true }));
    footer.append(reset, done);
    popover.append(header, body, footer);
    return popover;
  }

  function filterOptionButton(definition, option, selected) {
    const button = element("button", `recommendation-filter__option${selected ? " is-selected" : ""}`);
    button.type = "button";
    button.setAttribute("role", definition.multiple ? "checkbox" : "radio");
    button.setAttribute("aria-checked", String(selected));
    button.append(
      element("span", "recommendation-filter__option-label", option.label),
      element("span", "recommendation-filter__indicator"),
    );
    button.addEventListener("click", () => {
      if (definition.multiple) {
        const groupValues = new Set(definition.options.map((candidate) => candidate.value));
        if (!option.value) {
          answers.interests = answers.interests.filter((value) => !groupValues.has(value));
        } else {
          answers.interests = toggleValue(answers.interests, option.value);
        }
      } else {
        answers[definition.key] = option.value;
      }
      pendingPopoverFocus = true;
      render();
    });
    return button;
  }

  function filterUsesDefault(definition) {
    if (definition.multiple) {
      return !definition.options.some((option) => answers.interests.includes(option.value));
    }
    const defaults = defaultAnswers(currentQuestionnaire);
    return answers[definition.key] === defaults[definition.key];
  }

  function resetFilter(definition) {
    if (definition.multiple) {
      const groupValues = new Set(definition.options.map((option) => option.value));
      answers.interests = answers.interests.filter((value) => !groupValues.has(value));
      return;
    }
    const defaults = defaultAnswers(currentQuestionnaire);
    answers[definition.key] = defaults[definition.key];
    if (definition.key === "target_time") answers.custom_time = defaults.custom_time;
    if (definition.key === "search_scope") answers.area_id = defaults.area_id;
  }

  function positionFilterPopover(popover, chip, root) {
    if (!popover?.style || !chip?.getBoundingClientRect || !root?.getBoundingClientRect) return;
    if (globalThis.matchMedia?.("(max-width: 980px)")?.matches) return;
    const chipRect = chip.getBoundingClientRect();
    const rootRect = root.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect?.();
    const maxLeft = Math.max(0, rootRect.width - Number(popoverRect?.width || 0));
    popover.style.left = `${Math.min(maxLeft, Math.max(0, chipRect.left - rootRect.left))}px`;
    popover.style.top = `${Math.max(0, chipRect.bottom - rootRect.top + 8)}px`;
  }

  function renderChat() {
    const workspace = element("section", "recommendation-chat");
    const scroll = element("div", "recommendation-chat__scroll");
    scroll.append(element(
      "p",
      "recommendation-chat__notice",
      "请避免填写敏感个人信息，路线细节请结合地图与现场情况确认。",
    ));
    if (!chatHistory.length) {
      workspace.className += " is-empty";
      const starter = element("div", "recommendation-chat__starter");
      starter.append(element("p", "recommendation-chat__prompt", "你今天想走一条怎样的路线？"));
      starter.append(element("p", "recommendation-chat__suggestions-label", "推荐提问"));
      const examples = element("div", "recommendation-chat__examples");
      chatExamples().forEach((example) => {
        const button = element("button", "recommendation-chat__example", example);
        button.type = "button";
        button.addEventListener("click", () => submitChatMessage(example));
        examples.append(button);
      });
      starter.append(examples);
      scroll.append(starter);
    } else {
      const messages = element("div", "recommendation-chat__messages");
      messages.setAttribute("aria-live", "polite");
      chatHistory.forEach((message) => {
        messages.append(element("p", `recommendation-chat__message recommendation-chat__message--${message.role}`, message.content));
      });
      scroll.append(messages);
    }
    if (chatProgress) scroll.append(renderChatProgress(chatProgress));
    if (chatResultVisible) {
      const model = buildRecommendationViewModel(currentResult, currentRouteId, getRouteEnvironment);
      if (["result", "degraded"].includes(model.kind)) {
        const cards = element("div", "recommendation-chat__route-cards");
        model.routes.slice(0, 3).forEach((route, index) => cards.append(renderChatRouteCard(route, index)));
        scroll.append(cards);
      } else if (["paused", "no_candidates"].includes(model.kind)) {
        scroll.append(element("p", "recommendation-chat__empty-result", model.message));
      }
    }
    if (chatError) {
      const warning = element("p", "recommendation-chat__error", chatError);
      warning.setAttribute("role", "alert");
      scroll.append(warning);
    }
    workspace.append(scroll);

    const form = element("form", "recommendation-chat__composer");
    const input = element("textarea", "recommendation-chat__input");
    input.setAttribute("aria-label", "描述路线需求");
    input.setAttribute("maxlength", "500");
    input.setAttribute("placeholder", "例如：想跑 5 公里，安静一点，沿途有厕所");
    input.value = chatDraft;
    input.disabled = chatBusy;
    let isComposing = false;
    const send = element("button", "recommendation-chat__send");
    send.type = "submit";
    send.setAttribute("aria-label", "发送路线需求");
    send.setAttribute("title", "发送路线需求");
    const icon = element("img", "recommendation-chat__send-icon");
    icon.setAttribute("src", "./assets/icons/navigation-2.svg");
    icon.setAttribute("alt", "");
    icon.setAttribute("aria-hidden", "true");
    send.append(icon);
    input.addEventListener("input", (event) => {
      chatDraft = event.target.value;
      syncChatComposer(form, send);
    });
    input.addEventListener("compositionstart", () => { isComposing = true; });
    input.addEventListener("compositionend", (event) => {
      isComposing = false;
      chatDraft = event.target.value;
      syncChatComposer(form, send);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey || isComposing || event.isComposing) return;
      event.preventDefault();
      return form.requestSubmit();
    });
    form.append(input);
    syncChatComposer(form, send);
    form.addEventListener("submit", handleIntentSubmit);
    workspace.append(form);
    return workspace;
  }

  async function handleIntentSubmit(event) {
    event.preventDefault();
    return submitChatMessage(chatDraft);
  }

  async function submitChatMessage(value) {
    const message = String(value || "").trim();
    if (!message || chatBusy) return;
    const revision = ++intentRevision;
    const priorHistory = chatHistory.slice(-6);
    chatHistory.push({ role: "user", content: message });
    chatDraft = "";
    chatBusy = true;
    chatError = "";
    chatProgress = "正在理解路线需求";
    chatResultVisible = false;
    render();
    try {
      const response = await onInterpretIntent?.({
        message,
        history: priorHistory,
        context: {
          location: currentLocation,
          route_mode: answers.route_mode,
          profile: {
            experience: currentProfile?.experience || "regular",
            sensitivities: [...(currentProfile?.sensitivities || [])],
          },
          preferences: { ...answers, interests: [...answers.interests], ...intentPatch },
        },
      });
      if (!response) throw new Error("千问服务未返回内容。");
      if (revision !== intentRevision) return;
      intentPatch = { ...intentPatch, ...(response.preference_patch || {}) };
      applyPatchToAnswers(intentPatch);
      chatHistory.push({ role: "assistant", content: String(response.reply || "已整理你的偏好。") });
      if (response.ready) {
        chatProgress = "正在匹配合适路线";
        render();
        const base = buildUserProfile({
          questionnaire: currentQuestionnaire,
          answers,
          profile: currentProfile,
          location: currentLocation,
        });
        const result = await onRecommend?.(applyIntentPatch(base, intentPatch));
        if (!result) throw new Error("推荐服务未返回结果。");
        if (revision !== intentRevision) return;
        currentResult = result;
        currentRouteId = null;
        chatResultVisible = true;
        const model = buildRecommendationViewModel(result, null, getRouteEnvironment);
        if (["result", "degraded"].includes(model.kind) && shouldSelectRoute()) {
          onShowRoutes?.(model.routes.map((route) => route.source), { source: "chat" });
        }
      }
    } catch (error) {
      if (revision !== intentRevision) return;
      chatError = `${String(error?.message || "千问暂时不可用。")} 已填写的条件仍会保留。`;
    } finally {
      if (revision === intentRevision) {
        chatBusy = false;
        chatProgress = "";
        render();
      }
    }
  }

  function syncChatComposer(form, send) {
    const hasDraft = Boolean(String(chatDraft || "").trim()) && !chatBusy;
    form.classList.toggle("has-draft", hasDraft);
    if (hasDraft && send.parentElement !== form) {
      form.append(send);
    } else if (!hasDraft) {
      send.remove();
    }
  }

  function renderChatProgress(label) {
    const progress = element("div", "recommendation-chat__progress");
    progress.setAttribute("aria-live", "polite");
    const dots = element("span", "recommendation-chat__progress-dots");
    dots.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      const dot = element("span", "recommendation-chat__progress-dot");
      dot.style.animationDelay = `${index * 140}ms`;
      dots.append(dot);
    }
    progress.append(dots, element("span", "recommendation-chat__progress-label", label));
    return progress;
  }

  async function runRecommendation(payload, revision) {
    controller.showLoading();
    const result = await onRecommend?.(payload);
    if (!result) throw new Error("推荐服务未返回结果。");
    if (revision !== requestRevision) return;
    controller.showResult(result);
  }

  function renderRouteCard(route, index) {
    const model = routeCardModel(route.source, {
      environment: route.environment,
      preferredLabel: ["首选", "备选 1", "备选 2"][index] || "",
      selected: route.isSelected,
    });
    const card = createRouteCard(model, {
      onSelect: (routeId) => controller.selectRoute(routeId),
      onPreview: (routeId) => {
        hoveredRouteId = routeId || null;
        onPreviewRoute?.(routeId, route.source);
      },
    });
    card.dataset.recommendationRank = String(index + 1);
    if (route.routeId === hoveredRouteId) card.className += " is-hovered";
    return card;
  }

  function renderChatRouteCard(route, index) {
    const model = routeCardModel(route.source, {
      environment: route.environment,
      preferredLabel: ["首选", "备选 1", "备选 2"][index] || "",
      selected: route.isSelected,
    });
    const card = element(
      "article",
      `recommendation-chat__route-card${route.isSelected ? " is-selected" : ""}`,
    );
    card.dataset.routeId = model.routeId;
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-current", String(Boolean(route.isSelected)));
    card.setAttribute("aria-label", `查看路线 ${model.routeName}`);

    const media = element("div", "recommendation-chat__media");
    media.setAttribute("role", "img");
    media.setAttribute("aria-label", `${model.routeName}路线图片预留位置`);
    if (model.media?.cover) {
      const image = element("img", "recommendation-chat__image");
      image.setAttribute("src", model.media.cover);
      image.setAttribute("alt", model.routeName);
      image.setAttribute("loading", "lazy");
      image.addEventListener("error", () => {
        media.replaceChildren(element("span", "recommendation-chat__media-label", "路线照片"));
      });
      media.append(image);
    } else {
      media.append(element("span", "recommendation-chat__media-label", "路线照片"));
    }

    const body = element("div", "recommendation-chat__route-body");
    const topline = element("div", "recommendation-chat__route-topline");
    if (model.rankLabel) topline.append(element("span", "recommendation-chat__rank", model.rankLabel));
    topline.append(element("span", "recommendation-chat__mode", model.modeLabel));
    body.append(
      topline,
      element("strong", "recommendation-chat__route-name", model.routeName),
      element("span", "recommendation-chat__route-metrics", model.journeyText),
    );
    const fit = String(route.source?.personalized_fit || "").trim();
    if (fit) body.append(element("span", "recommendation-chat__route-fit", fit));
    card.append(media, body);

    const select = () => controller.selectRoute(model.routeId);
    card.addEventListener("click", select);
    card.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key) || event.repeat) return;
      event.preventDefault();
      select();
    });
    card.addEventListener("mouseenter", () => onPreviewRoute?.(model.routeId, route.source));
    card.addEventListener("mouseleave", () => onPreviewRoute?.(null, route.source));
    if (route.routeId === hoveredRouteId) card.className += " is-hovered";
    return card;
  }

  function applyPatchToAnswers(patch) {
    if ((currentQuestionnaire?.route_modes || []).some((option) => option.value === patch.route_mode)) {
      const modeChanged = answers.route_mode !== patch.route_mode;
      answers.route_mode = patch.route_mode;
      if (modeChanged) {
        answers.distance_range = defaultDistanceRange(currentQuestionnaire, patch.route_mode);
        onRouteModeChange?.(patch.route_mode);
      }
    }
    if ((currentQuestionnaire?.goals || []).some((option) => option.value === patch.goal)) {
      answers.goal = patch.goal;
    }
    if ((currentQuestionnaire?.route_shapes || []).some((option) => option.value === patch.route_shape)) {
      answers.route_shape = patch.route_shape;
    }
    if (Array.isArray(patch.interests)) {
      answers.interests = cleanSelections(patch.interests, currentQuestionnaire?.interests);
    }
    if (typeof patch.free_text === "string") answers.free_text = patch.free_text.slice(0, 500);
  }

  render();
  return controller;
}

function profileChoiceGroup({ label, options, selected, onChange, multiple = false }) {
  const fieldset = element("fieldset", "profile-dialog__group");
  fieldset.append(element("legend", "profile-dialog__legend", label));
  const choices = element("div", "profile-dialog__choices");
  for (const [value, optionLabel] of options) {
    const active = multiple ? selected?.includes(value) : selected === value;
    const button = element("button", `profile-dialog__choice${active ? " is-selected" : ""}`, optionLabel);
    button.type = "button";
    button.setAttribute("aria-pressed", String(Boolean(active)));
    button.addEventListener("click", () => onChange(value));
    choices.append(button);
  }
  fieldset.append(choices);
  return fieldset;
}

function selectField(label, options, selected, onChange) {
  const wrapper = element("label", "recommendation-select");
  wrapper.append(element("span", "recommendation-select__label", label));
  const select = element("select", "recommendation-select__control");
  for (const option of options || []) {
    const node = element("option", "", option.label);
    node.value = option.value;
    node.selected = selected === option.value;
    select.append(node);
  }
  select.addEventListener("change", (event) => onChange(event.target.value));
  wrapper.append(select);
  return wrapper;
}

function inputField(label, type, value, onChange) {
  const wrapper = element("label", "recommendation-input");
  wrapper.append(element("span", "recommendation-input__label", label));
  const input = element("input", "recommendation-input__control");
  input.type = type;
  input.value = value || "";
  input.required = true;
  input.addEventListener("change", (event) => onChange(event.target.value));
  wrapper.append(input);
  return wrapper;
}

function textAreaField(value, onChange) {
  const wrapper = element("label", "recommendation-note");
  wrapper.append(element("span", "recommendation-note__label", "补充需求（可跳过）"));
  const textarea = element("textarea", "recommendation-note__control");
  textarea.maxLength = 500;
  textarea.rows = 2;
  textarea.placeholder = "例如：想走梧桐树多、回程方便的路线";
  textarea.value = value || "";
  textarea.addEventListener("input", (event) => onChange(event.target.value));
  wrapper.append(textarea);
  return wrapper;
}

function defaultAnswers(questionnaire) {
  const routeMode = questionnaire?.route_modes?.find((option) => option.value === "walk")?.value
    || questionnaire?.route_modes?.[0]?.value
    || "walk";
  const searchScope = questionnaire?.search_scopes?.find((option) => option.value === "nearby_5000")?.value
    || questionnaire?.search_scopes?.[0]?.value
    || "nearby_5000";
  return {
    route_mode: routeMode,
    target_time: questionnaire?.target_times?.[0]?.value || "now",
    custom_time: "",
    distance_range: defaultDistanceRange(questionnaire, routeMode),
    goal: questionnaire?.goals?.[0]?.value || "balanced",
    search_scope: searchScope,
    area_id: questionnaire?.areas?.[0]?.value || "",
    route_shape: questionnaire?.route_shapes?.[0]?.value || "any",
    interests: [],
    free_text: "",
  };
}

function defaultDistanceRange(questionnaire, routeMode) {
  const options = questionnaire?.distance_ranges?.[routeMode] || [];
  return options[1]?.value || options[0]?.value || "";
}

function normalizeFinalRoute(finalRoute, getRouteEnvironment = () => null) {
  const scored = finalRoute?.route;
  const route = scored?.route;
  const routeId = route?.route_id;
  if (!routeId) {
    return null;
  }
  const apiPm25 = scored?.environment_summary?.pm2_5;
  const routeEnvironment = usablePm25Metric(apiPm25) ? null : getRouteEnvironment(routeId);
  const localPm25 = routeEnvironment?.pm25 || routeEnvironment?.pm2_5;
  const pm25 = preferredPm25Metric(apiPm25, localPm25);
  return {
    source: finalRoute,
    routeId,
    routeName: String(route.route_name || "未命名路线"),
    distanceText: formatDistance(route.distance_m),
    durationText: formatDuration(route.duration_min),
    pm25Text: compactPm25(pm25),
    environment: pm25 ? { pm25 } : null,
    advantages: uniqueTextValues(finalRoute?.advantages).slice(0, 3),
    suggestions: uniqueTextValues(finalRoute?.suggestions).slice(0, 2),
  };
}

function preferredPm25Metric(apiMetric, localMetric) {
  if (usablePm25Metric(apiMetric)) return apiMetric;
  if (numericPm25Metric(localMetric)) return displayablePm25Metric(localMetric);
  if (numericPm25Metric(apiMetric)) return displayablePm25Metric(apiMetric);
  return null;
}

function usablePm25Metric(metric) {
  const status = String(metric?.status || "").toLowerCase();
  return numericPm25Metric(metric) && !["stale", "no_data", "error", "unavailable"].includes(status);
}

function numericPm25Metric(metric) {
  const value = metric?.value ?? metric?.displayValue;
  return value !== null && value !== "" && Number.isFinite(Number(value));
}

function displayablePm25Metric(metric) {
  const value = Number(metric?.value ?? metric?.displayValue);
  return { ...metric, value, displayValue: value, status: "ok" };
}

function compactPm25(metric) {
  if (metric?.status === "stale") return "PM2.5 数据更新中";
  const value = Number(metric?.value);
  if (!Number.isFinite(value)) return "PM2.5 暂无数据";
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `PM2.5 ${formatted} µg/m³`;
}

function chatExamples() {
  return [
    "从交大徐汇校区出发，散步一小时，想走安静、有树荫的环线",
    "帮我找一条 5 公里左右的跑步路线，空气好一点，沿途有厕所",
    "周末骑行 10 公里左右，想看滨江风景，最后回到出发点",
  ];
}

function applyIntentPatch(profile, patch) {
  const allowed = [
    "route_mode",
    "distance_min_m",
    "target_distance_m",
    "distance_max_m",
    "search_radius_m",
    "area_ids",
    "goal",
    "route_shape",
    "interests",
    "free_text",
    "target_time",
  ];
  const next = { ...profile };
  allowed.forEach((field) => {
    if (patch?.[field] !== undefined && patch[field] !== null) {
      next[field] = cloneValue(patch[field]);
    }
  });
  return next;
}

function uniqueTextValues(values) {
  return [...new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean))];
}

function cloneValue(value) {
  if (Array.isArray(value)) return [...value];
  if (value && typeof value === "object") return { ...value };
  return value;
}

function optionLabel(options, value) {
  return (options || []).find((option) => option.value === value)?.label || "";
}

function resolveTargetTime(answers, now) {
  const mode = answers?.target_time;
  const base = now();
  if (!(base instanceof Date) || Number.isNaN(base.valueOf())) {
    throw new Error("当前时间无效。");
  }
  if (mode === "now") {
    return base.toISOString();
  }
  if (mode === "plus_2h") {
    return new Date(base.valueOf() + 2 * 60 * 60 * 1000).toISOString();
  }
  if (mode === "custom") {
    const custom = new Date(answers?.custom_time || "");
    if (Number.isNaN(custom.valueOf())) {
      throw new Error("请选择有效的自定义运动时间。");
    }
    return custom.toISOString();
  }
  throw new Error("计划时间选项无效。");
}

function distanceOption(questionnaire, routeMode, selectedValue) {
  const options = questionnaire?.distance_ranges?.[routeMode] || [];
  const selected = options.find((option) => option.value === selectedValue);
  if (!selected) {
    throw new Error("请选择有效的距离范围。");
  }
  return selected;
}

function selectedAreaIds(questionnaire, areaId) {
  const selected = requiredOption(questionnaire?.areas, areaId, "指定片区");
  return [selected];
}

function requiredOption(options, value, label) {
  if (!(options || []).some((option) => option.value === value)) {
    throw new Error(`请选择有效的${label}。`);
  }
  return value;
}

function cleanSelections(values, options) {
  const allowed = new Set((options || []).map((option) => option.value));
  return [...new Set(Array.isArray(values) ? values : [])].filter((value) => allowed.has(value));
}

function nearbyRadiusFromScope(scope) {
  const match = /^nearby_(3000|5000|8000)$/.exec(scope);
  return match ? Number(match[1]) : null;
}

function normalizeLocation(location) {
  const lng = Number(location?.lng_gcj02);
  const lat = Number(location?.lat_gcj02);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    return null;
  }
  return { lng_gcj02: lng, lat_gcj02: lat };
}

function startAccessDistance(route, origin) {
  const start = normalizeLocation(route?.start_location);
  if (!start) return Number.POSITIVE_INFINITY;
  const latitudeRadians = ((origin.lat_gcj02 + start.lat_gcj02) / 2) * Math.PI / 180;
  const northM = (start.lat_gcj02 - origin.lat_gcj02) * 111_320;
  const eastM = (start.lng_gcj02 - origin.lng_gcj02) * 111_320 * Math.cos(latitudeRadians);
  return Math.hypot(northM, eastM);
}

function recommendationEnvironmentSummary(environment) {
  if (!environment) return {};
  return {
    pm2_5: cloneValue(environment.pm25),
    pollen: cloneValue(environment.pollen),
    noise: cloneValue(environment.noise),
  };
}

function formatAccessDistance(value) {
  const meters = Math.max(0, Number(value || 0));
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} 公里` : `${Math.round(meters)} 米`;
}

function toggleValue(values, value) {
  const selected = new Set(values || []);
  if (selected.has(value)) {
    selected.delete(value);
  } else {
    selected.add(value);
  }
  return [...selected];
}

function routeIdOf(finalRoute) {
  return finalRoute?.route?.route?.route_id || null;
}

function formatDistance(value) {
  const distance = Number(value);
  return Number.isFinite(distance) && distance > 0 ? `${(distance / 1000).toFixed(1)} km` : "距离待确认";
}

function formatDuration(value) {
  const duration = Number(value);
  return Number.isFinite(duration) && duration > 0 ? `${Math.round(duration)} 分钟` : "时间待确认";
}

function element(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== null) {
    node.textContent = text;
  }
  return node;
}

function filterIcon(name) {
  const icon = element("span", "recommendation-filter__icon");
  icon.setAttribute("aria-hidden", "true");
  icon.setAttribute("data-filter-icon", name);
  icon.innerHTML = `<svg viewBox="0 0 24 24" focusable="false"><use href="./assets/icons/filter-icons.svg#filter-${name}" /></svg>`;
  return icon;
}
