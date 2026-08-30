import { normalizeHealthProfile } from "./profile-store.js";
import { createRouteCard, routeCardModel } from "./route-card.js";

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

export function buildRecommendationViewModel(result, currentRouteId = null) {
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
    .map(normalizeFinalRoute)
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
  let requestRevision = 0;
  let intentRevision = 0;
  let chatBusy = false;
  let chatDraft = "";
  let chatHistory = [];
  let intentPatch = {};
  let intentReady = false;
  let chatError = "";
  let preChatState = null;
  const answers = defaultAnswers(questionnaire);

  const controller = {
    showQuestionnaire() {
      requestRevision += 1;
      switchProductView("questionnaire");
      currentRouteId = null;
      onReturnRouteOverview?.();
      render();
    },
    restartRecommendation() {
      const routeMode = answers.route_mode;
      const reset = defaultAnswers(currentQuestionnaire);
      reset.route_mode = routeMode;
      reset.distance_range = currentQuestionnaire?.distance_ranges?.[routeMode]?.[0]?.value || "";
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
      intentReady = false;
      chatError = "";
      render();
      onRestartRecommendation?.();
    },
    showLoading() {
      switchProductView("loading");
      render();
    },
    showResult(result) {
      currentResult = result;
      currentRouteId = null;
      switchProductView("result");
      render();
      const model = buildRecommendationViewModel(result);
      if (["result", "degraded"].includes(model.kind) && shouldSelectRoute()) {
        onShowRoutes?.(model.routes.map((route) => route.source));
      }
    },
    showError(error) {
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
    setRouteMode(value) {
      if (!(currentQuestionnaire?.route_modes || []).some((option) => option.value === value)) return;
      answers.route_mode = value;
      const available = currentQuestionnaire?.distance_ranges?.[value] || [];
      if (!available.some((option) => option.value === answers.distance_range)) {
        answers.distance_range = available[0]?.value || "";
      }
      render();
    },
    setHoveredRoute(routeId) {
      hoveredRouteId = routeId || null;
      if (viewState === "result") render();
    },
    selectRoute(routeId) {
      const model = buildRecommendationViewModel(currentResult, routeId);
      if (!["result", "degraded"].includes(model.kind) || !model.selectedRoute) return;
      currentRouteId = routeId;
      hoveredRouteId = null;
      viewState = "result";
      render();
      onSelectRoute?.(routeId, model.selectedRoute);
    },
    getCurrentRouteId() {
      return currentRouteId;
    },
    getResultRoutes() {
      const model = buildRecommendationViewModel(currentResult, currentRouteId);
      return ["result", "degraded"].includes(model.kind) ? model.routes.map((route) => route.source) : [];
    },
    getAnswers() {
      return { ...answers, interests: [...answers.interests] };
    },
    openChat,
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

  function closeChat() {
    if (viewState !== "chat") return;
    intentRevision += 1;
    chatBusy = false;
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
    if (viewState === "questionnaire") {
      root.append(renderQuestionnaire());
    } else if (viewState === "chat") {
      root.append(renderChat());
    } else {
      const state = viewState === "loading"
        ? { view: "loading" }
        : viewState === "error"
          ? { view: "error", message: errorMessage }
          : currentResult;
      root.append(renderRecommendationState(buildRecommendationViewModel(state, currentRouteId)));
    }
    container.replaceChildren(root);
  }

  function renderQuestionnaire() {
    const form = element("form", "recommendation-form");
    form.append(
      segmentedField("计划时间", currentQuestionnaire?.target_times, answers.target_time, (value) => {
        answers.target_time = value;
        render();
      }),
    );
    if (answers.target_time === "custom") {
      form.append(inputField("自定义时间", "datetime-local", answers.custom_time, (value) => {
        answers.custom_time = value;
      }));
    }
    form.append(
      segmentedField("距离", currentQuestionnaire?.distance_ranges?.[answers.route_mode], answers.distance_range, (value) => {
        answers.distance_range = value;
        render();
      }),
      segmentedField("主要目标", currentQuestionnaire?.goals, answers.goal, (value) => {
        answers.goal = value;
        render();
      }),
    );
    const advanced = element("details", "recommendation-advanced");
    advanced.append(element("summary", "recommendation-advanced__summary", "更多偏好"));
    advanced.append(segmentedField("搜索范围", currentQuestionnaire?.search_scopes, answers.search_scope, (value) => {
      answers.search_scope = value;
      render();
    }));
    if (answers.search_scope === "area") {
      advanced.append(selectField("指定片区", currentQuestionnaire?.areas, answers.area_id, (value) => {
        answers.area_id = value;
      }));
    }
    advanced.append(
      segmentedField("路线形态", currentQuestionnaire?.route_shapes, answers.route_shape, (value) => {
        answers.route_shape = value;
        render();
      }),
      segmentedField("兴趣需求", currentQuestionnaire?.interests, answers.interests, (value) => {
        answers.interests = toggleValue(answers.interests, value);
        render();
      }, true),
    );
    form.append(advanced);
    form.append(textAreaField(answers.free_text, (value) => {
      answers.free_text = value;
    }));
    form.append(element("p", "recommendation-form__summary", preferenceSummary()));
    const submit = element("button", "recommendation-form__submit", "为我推荐路线");
    submit.type = "submit";
    form.append(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
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
    return form;
  }

  function renderChat() {
    const workspace = element("section", "recommendation-chat");
    const close = element("button", "recommendation-chat__close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "关闭千问聊天");
    close.setAttribute("title", "关闭千问聊天");
    close.addEventListener("click", closeChat);
    workspace.append(close);

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
        button.addEventListener("click", () => {
          chatDraft = example;
          render();
        });
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
    if (chatError) {
      const warning = element("p", "recommendation-chat__error", chatError);
      warning.setAttribute("role", "alert");
      scroll.append(warning);
    }
    if (intentReady) {
      const confirm = element("button", "recommendation-chat__confirm", "开始推荐");
      confirm.type = "button";
      confirm.addEventListener("click", async () => {
        const revision = ++requestRevision;
        try {
          const base = buildUserProfile({ questionnaire: currentQuestionnaire, answers, profile: currentProfile, location: currentLocation });
          await runRecommendation(applyIntentPatch(base, intentPatch), revision);
        } catch (error) {
          controller.showError(error);
        }
      });
      scroll.append(confirm);
    }
    workspace.append(scroll);

    const form = element("form", "recommendation-chat__composer");
    const input = element("textarea", "recommendation-chat__input");
    input.setAttribute("aria-label", "描述路线需求");
    input.setAttribute("maxlength", "500");
    input.setAttribute("placeholder", "例如：想跑 5 公里，安静一点，沿途有厕所");
    input.value = chatDraft;
    input.addEventListener("input", (event) => { chatDraft = event.target.value; });
    const send = element("button", "recommendation-chat__send", chatBusy ? "整理中…" : "发送");
    send.type = "submit";
    send.disabled = chatBusy;
    send.setAttribute("aria-label", chatBusy ? "正在整理路线需求" : "发送路线需求");
    form.append(input, send);
    form.addEventListener("submit", handleIntentSubmit);
    workspace.append(form);
    return workspace;
  }

  async function handleIntentSubmit(event) {
    event.preventDefault();
    const message = chatDraft.trim();
    if (!message || chatBusy) return;
    const revision = ++intentRevision;
    const priorHistory = chatHistory.slice(-6);
    chatHistory.push({ role: "user", content: message });
    chatDraft = "";
    chatBusy = true;
    chatError = "";
    intentReady = false;
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
      chatHistory.push({ role: "assistant", content: String(response.reply || "已整理你的偏好。") });
      intentPatch = { ...intentPatch, ...(response.preference_patch || {}) };
      applyPatchToAnswers(intentPatch);
      intentReady = Boolean(response.ready);
    } catch (error) {
      if (revision !== intentRevision) return;
      chatError = `${String(error?.message || "千问暂时不可用。")} 已填写的条件仍会保留。`;
    } finally {
      if (revision === intentRevision) {
        chatBusy = false;
        render();
      }
    }
  }

  async function runRecommendation(payload, revision) {
    controller.showLoading();
    const result = await onRecommend?.(payload);
    if (!result) throw new Error("推荐服务未返回结果。");
    if (revision !== requestRevision) return;
    controller.showResult(result);
  }

  function renderRecommendationState(model) {
    const region = element("div", `recommendation-state recommendation-state--${model.kind}`);
    region.setAttribute("aria-live", "polite");
    if (model.kind === "loading") {
      region.append(element("h2", "recommendation-state__title", model.title));
      const steps = element("ol", "recommendation-progress");
      model.steps.forEach((step) => {
        const item = element("li", `recommendation-progress__step is-${step.state}`, step.label);
        item.setAttribute("aria-current", step.state === "active" ? "step" : "false");
        steps.append(item);
      });
      region.append(steps, element("p", "recommendation-state__summary", preferenceSummary()));
      return region;
    }
    if (!["result", "degraded"].includes(model.kind)) {
      region.append(element("h2", "recommendation-state__title", model.title));
      region.append(element("p", "recommendation-state__message", model.message));
      if (["error", "no_candidates"].includes(model.kind)) {
        const missingQuestionnaire = !currentQuestionnaire;
        const retry = element(
          "button",
          "recommendation-state__retry",
          missingQuestionnaire ? "重新加载问卷" : "调整条件",
        );
        retry.type = "button";
        retry.addEventListener("click", async () => {
          if (!missingQuestionnaire) {
            controller.showQuestionnaire();
            return;
          }
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
    if (model.notice) {
      const notice = element("p", "recommendation-state__notice", model.notice);
      notice.setAttribute("role", "status");
      region.append(notice);
    }
    const bar = element("div", "recommendation-results__bar");
    bar.append(element("h2", "recommendation-results__title", "为你推荐"));
    const restart = element("button", "recommendation-results__restart", "重新推荐");
    restart.type = "button";
    restart.addEventListener("click", () => controller.restartRecommendation());
    bar.append(restart);
    region.append(bar);
    model.routes.forEach((route, index) => {
      if (index === 0) region.append(element("h3", "recommendation-results__group", "首选路线"));
      if (index === 1) region.append(element("h3", "recommendation-results__group", "备选路线"));
      region.append(renderRouteCard(route, index));
    });
    return region;
  }

  function renderRouteCard(route, index) {
    const model = routeCardModel(route.source, {
      preferredLabel: route.isPrimary ? "首选" : "",
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

  function preferenceSummary() {
    const mode = optionLabel(currentQuestionnaire?.route_modes, answers.route_mode);
    const time = optionLabel(currentQuestionnaire?.target_times, answers.target_time);
    const distance = optionLabel(currentQuestionnaire?.distance_ranges?.[answers.route_mode], answers.distance_range);
    const goal = optionLabel(currentQuestionnaire?.goals, answers.goal);
    return [currentLocation?.label, mode, time, distance, goal].filter(Boolean).join(" · ");
  }

  function applyPatchToAnswers(patch) {
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

function segmentedField(label, options, selected, onChange, multiple = false) {
  const fieldset = element("fieldset", "recommendation-question");
  fieldset.append(element("legend", "recommendation-question__legend", label));
  const choices = element("div", "recommendation-question__choices");
  for (const option of options || []) {
    const active = multiple ? selected?.includes(option.value) : selected === option.value;
    const button = element("button", `recommendation-choice${active ? " is-selected" : ""}`, option.label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(Boolean(active)));
    button.addEventListener("click", () => onChange(option.value));
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
  const routeMode = questionnaire?.route_modes?.[0]?.value || "walk";
  const searchScope = questionnaire?.search_scopes?.find((option) => option.value === "nearby_5000")?.value
    || questionnaire?.search_scopes?.[0]?.value
    || "nearby_5000";
  return {
    route_mode: routeMode,
    target_time: questionnaire?.target_times?.[0]?.value || "now",
    custom_time: "",
    distance_range: questionnaire?.distance_ranges?.[routeMode]?.[0]?.value || "",
    goal: questionnaire?.goals?.[0]?.value || "balanced",
    search_scope: searchScope,
    area_id: questionnaire?.areas?.[0]?.value || "",
    route_shape: questionnaire?.route_shapes?.[0]?.value || "any",
    interests: [],
    free_text: "",
  };
}

function normalizeFinalRoute(finalRoute) {
  const scored = finalRoute?.route;
  const route = scored?.route;
  const routeId = route?.route_id;
  if (!routeId) {
    return null;
  }
  return {
    source: finalRoute,
    routeId,
    routeName: String(route.route_name || "未命名路线"),
    distanceText: formatDistance(route.distance_m),
    durationText: formatDuration(route.duration_min),
    pm25Text: compactPm25(scored?.environment_summary?.pm2_5),
    advantages: uniqueTextValues(finalRoute?.advantages).slice(0, 3),
    suggestions: uniqueTextValues(finalRoute?.suggestions).slice(0, 2),
  };
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
    if (patch?.[field] !== undefined) next[field] = cloneValue(patch[field]);
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
