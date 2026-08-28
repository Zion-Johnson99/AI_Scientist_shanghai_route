import { normalizeHealthProfile } from "./profile-store.js";

const ROUTE_SHAPE_LABELS = {
  any: "形态不限",
  one_way: "单程",
  strict_loop: "环线",
};

const MODE_LABELS = {
  walk: "步行",
  run: "跑步",
  bike: "骑行",
};

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
    return { kind: "loading", title: "正在筛选徐汇路线", message: "正在比较距离、环境与兴趣匹配。" };
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
  const routes = (result?.final_routes || []).slice(0, 3).map(normalizeFinalRoute).filter(Boolean);
  if (result?.status === "no_candidates" || !routes.length) {
    return {
      kind: "no_candidates",
      title: "这组条件暂无合适路线",
      message: "试试扩大范围、调整距离或放宽路线形态。",
    };
  }
  const selectedIndex = Math.max(0, routes.findIndex((route) => route.routeId === currentRouteId));
  const primary = routes[selectedIndex];
  const alternatives = routes.filter((_, index) => index !== selectedIndex).slice(0, 2);
  alternatives.forEach((route) => {
    route.differenceLabel = routeDifference(primary, route);
  });
  return {
    kind: result.status === "degraded" ? "degraded" : "result",
    notice: result.status === "degraded" ? "个性化解释已简化，路线排序由本地评分完成。" : "",
    summary: String(result.decision_summary || ""),
    primary,
    alternatives,
  };
}

export function createRecommendationUI({
  container,
  questionnaire,
  profile,
  location = null,
  onPickLocation,
  onRecommend,
  onReloadQuestionnaire,
  onSelectRoute,
  onNavigate,
  onOpenProfile,
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
  let viewState = "questionnaire";
  let errorMessage = "";
  let requestRevision = 0;
  const answers = defaultAnswers(questionnaire);

  const controller = {
    showQuestionnaire() {
      requestRevision += 1;
      viewState = "questionnaire";
      render();
    },
    showLoading() {
      viewState = "loading";
      render();
    },
    showResult(result) {
      currentResult = result;
      currentRouteId = routeIdOf(result?.final_routes?.[0]) || null;
      viewState = "result";
      render();
      if (
        currentRouteId
        && result?.status !== "paused"
        && result?.status !== "no_candidates"
        && shouldSelectRoute()
      ) {
        onSelectRoute?.(currentRouteId, result.final_routes[0]);
      }
    },
    showError(error) {
      errorMessage = String(error?.message || error || "推荐服务暂时不可用。");
      viewState = "error";
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
    getCurrentRouteId() {
      return currentRouteId;
    },
    getAnswers() {
      return { ...answers, interests: [...answers.interests] };
    },
  };

  function render() {
    const root = element("section", "recommendation-panel");
    root.setAttribute("aria-label", "个性化路线推荐");
    root.append(panelHeader(onOpenProfile));
    if (viewState === "questionnaire") {
      root.append(renderQuestionnaire());
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
    form.append(locationPicker(currentLocation, async () => {
      try {
        const picked = await onPickLocation?.();
        if (picked) {
          currentLocation = picked;
          render();
        }
      } catch (error) {
        controller.showError(error);
      }
    }));
    form.append(
      segmentedField("运动方式", currentQuestionnaire?.route_modes, answers.route_mode, (value) => {
        answers.route_mode = value;
        answers.distance_range = currentQuestionnaire?.distance_ranges?.[value]?.[0]?.value || "";
        render();
      }),
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
      segmentedField("搜索范围", currentQuestionnaire?.search_scopes, answers.search_scope, (value) => {
        answers.search_scope = value;
        render();
      }),
    );
    if (answers.search_scope === "area") {
      form.append(selectField("指定片区", currentQuestionnaire?.areas, answers.area_id, (value) => {
        answers.area_id = value;
      }));
    }
    form.append(
      segmentedField("路线形态", currentQuestionnaire?.route_shapes, answers.route_shape, (value) => {
        answers.route_shape = value;
        render();
      }),
      segmentedField("兴趣需求", currentQuestionnaire?.interests, answers.interests, (value) => {
        answers.interests = toggleValue(answers.interests, value);
        render();
      }, true),
      textAreaField(answers.free_text, (value) => {
        answers.free_text = value;
      }),
    );
    const submit = element("button", "recommendation-form__submit", "生成路线推荐");
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
        controller.showLoading();
        const result = await onRecommend?.(payload);
        if (!result) {
          throw new Error("推荐服务未返回结果。");
        }
        if (revision !== requestRevision) return;
        controller.showResult(result);
      } catch (error) {
        if (revision !== requestRevision) return;
        controller.showError(error);
      }
    });
    return form;
  }

  function renderRecommendationState(model) {
    const region = element("div", `recommendation-state recommendation-state--${model.kind}`);
    region.setAttribute("aria-live", "polite");
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
    region.append(element("h2", "recommendation-results__title", "首选路线"));
    region.append(primaryRouteCard(model.primary));
    if (model.alternatives.length) {
      const alternatives = element("div", "recommendation-alternatives");
      alternatives.append(element("h3", "recommendation-alternatives__title", "两条备选"));
      model.alternatives.forEach((route) => alternatives.append(alternativeRouteCard(route)));
      region.append(alternatives);
    }
    return region;
  }

  function primaryRouteCard(route) {
    const card = element("article", "recommendation-route recommendation-route--primary");
    const head = element("div", "recommendation-route__head");
    const placeholder = element("span", "recommendation-route__photo-placeholder");
    placeholder.setAttribute("aria-hidden", "true");
    placeholder.setAttribute("style", "width:48px;height:48px");
    const identity = element("div", "recommendation-route__identity");
    identity.append(element("h3", "recommendation-route__name", route.routeName));
    identity.append(element("p", "recommendation-route__journey", `${route.distanceText} · ${route.durationText} · ${route.shapeText}`));
    head.append(placeholder, identity);
    card.append(head);
    card.append(element("p", "recommendation-route__reason", route.reason));
    const tags = element("div", "recommendation-route__tags");
    tags.append(
      element("span", "recommendation-route__action", route.actionText),
      element("span", "recommendation-route__confidence", route.confidenceText),
    );
    card.append(tags);
    const navigate = element("button", "recommendation-route__navigate", "前往起点");
    navigate.type = "button";
    navigate.addEventListener("click", () => onNavigate?.(route.routeId, route.source));
    card.append(navigate);
    return card;
  }

  function alternativeRouteCard(route) {
    const button = element("button", "recommendation-alternative");
    button.type = "button";
    button.setAttribute("aria-label", `选择备选路线 ${route.routeName}`);
    const content = element("span", "recommendation-alternative__content");
    content.append(element("strong", "recommendation-alternative__name", route.routeName));
    content.append(element("small", "recommendation-alternative__journey", `${route.distanceText} · ${route.durationText}`));
    button.append(content, element("span", "recommendation-alternative__difference", route.differenceLabel));
    button.addEventListener("click", () => {
      currentRouteId = route.routeId;
      render();
      onSelectRoute?.(route.routeId, route.source);
    });
    return button;
  }

  render();
  return controller;
}

function panelHeader(onOpenProfile) {
  const header = element("header", "recommendation-panel__header");
  const title = element("div", "recommendation-panel__heading");
  title.append(element("span", "recommendation-panel__eyebrow", "XH ROUTE MATCH"));
  title.append(element("h2", "recommendation-panel__title", "帮我推荐"));
  const settings = element("button", "recommendation-panel__profile", "档案设置");
  settings.type = "button";
  settings.addEventListener("click", () => onOpenProfile?.());
  header.append(title, settings);
  return header;
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

function locationPicker(location, onPick) {
  const row = element("div", "recommendation-location");
  const text = element("div", "recommendation-location__text");
  text.append(element("span", "recommendation-location__label", "出发位置"));
  text.append(element("strong", "recommendation-location__value", location?.label || "未选择"));
  const button = element("button", "recommendation-location__pick", location ? "更换" : "选择位置");
  button.type = "button";
  button.addEventListener("click", onPick);
  row.append(text, button);
  return row;
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
  const confidence = Number(scored?.data_confidence);
  const caution = finalRoute?.cautions?.[0] || scored?.risk_notes?.[0] || "";
  return {
    source: finalRoute,
    routeId,
    routeName: String(route.route_name || "未命名路线"),
    routeMode: String(route.route_mode || "walk"),
    modeText: MODE_LABELS[route.route_mode] || "户外运动",
    distanceM: Number(route.distance_m || 0),
    distanceText: formatDistance(route.distance_m),
    durationText: formatDuration(route.duration_min),
    shapeText: ROUTE_SHAPE_LABELS[route.route_shape] || "形态待确认",
    reason: String(finalRoute.personalized_fit || "距离与当前偏好匹配。"),
    actionText: caution || "适合出发",
    confidence,
    confidenceText: Number.isFinite(confidence) ? `${Math.round(confidence * 100)}% 数据可信度` : "可信度待更新",
    placeholderSizePx: 48,
    differenceLabel: "备选",
  };
}

function routeDifference(primary, alternative) {
  const difference = alternative.distanceM - primary.distanceM;
  if (difference <= -200) {
    return "更近";
  }
  if (difference >= 200) {
    return "更长";
  }
  if (alternative.confidence > primary.confidence) {
    return "数据更完整";
  }
  return "不同风景";
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
