// 徐汇户外健康路线 · 本地离线应用逻辑
// 纯 ES2020 模块，无框架、无构建步骤、无任何运行时外部请求。
// 所有 DOM 写入均通过 createElement / textContent，不使用 innerHTML。

import { MapView } from "./map.js";

const RISK_LABELS = {
  normal: "正常",
  caution: "注意",
  pause: "暂停建议",
  stop: "停止建议",
  unknown: "未知",
};
const STATUS_LABELS = {
  measured: "实测",
  derived: "推算",
  estimated: "估计",
  unavailable: "不可用",
};
const RELIABILITY_MULTIPLIER = { measured: 1.0, derived: 0.9, estimated: 0.75 };
const PREF_OPTIONS = ["滨江", "公园", "安静", "绿荫", "水岸", "城市风景"];
const REC_PREF_SETS = [
  { key: "riverside", label: "滨江水岸", labels: ["滨江", "水岸"] },
  { key: "park", label: "公园绿荫", labels: ["公园", "绿荫"] },
  { key: "quiet", label: "安静", labels: ["安静"] },
  { key: "urban", label: "城市风景", labels: ["城市风景"] },
];
// 与 scripts/build_web_payload.py 中 ORIGINS 保持一致的固定原点网格
const CANONICAL_ORIGINS = [
  { key: "xujiahui", name_zh: "徐家汇", coord: [121.4365, 31.1945] },
  { key: "longhua", name_zh: "龙华", coord: [121.4505, 31.1815] },
  { key: "south_station", name_zh: "上海南站", coord: [121.4275, 31.1545] },
];
const DEFAULT_ORIGIN = { name_zh: "徐家汇（默认）", coord: CANONICAL_ORIGINS[0].coord, key: "xujiahui" };
const ACCESS_SPEED_KMH = { walk: 4.8, run: 8.0, bike: 14.0 };
const FALLBACK_DETOUR = 1.3;

const state = {
  payload: null,
  harness: null,
  flow: "recommend",
  routesById: new Map(),
  filters: { mode: "all", bands: new Set(), prefs: new Set(), env: new Set() },
  recPrefs: new Set(["riverside"]),
  origin: { ...DEFAULT_ORIGIN },
  selectedId: null,
  candidates: null, // 推荐流当前结果
  candidateByRouteId: new Map(),
  fallbackRankingUsed: false,
  map: null,
};

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, String(v));
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function fmtKm(meters) {
  if (typeof meters !== "number" || !Number.isFinite(meters)) return "—";
  return (meters / 1000).toFixed(1);
}

function fmtMin(min) {
  if (typeof min !== "number" || !Number.isFinite(min)) return "—";
  return String(Math.round(min));
}

function haversineKm(a, b) {
  const R = 6371.0088;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

function riskBadge(level) {
  const key = RISK_LABELS[level] ? level : "unknown";
  return el("span", { class: `risk-badge risk-${key}` }, [
    el("i", { class: "risk-dot", "aria-hidden": "true" }),
    el("span", { text: `环境风险：${RISK_LABELS[key]}` }),
  ]);
}

function statusBadge(status) {
  const key = STATUS_LABELS[status] ? status : "unavailable";
  return el("span", { class: `status-badge st-${key}`, text: STATUS_LABELS[key] });
}

// ---------- 数据加载 ----------
async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} ${url}`);
  return resp.json();
}

async function boot() {
  $("skeleton-state").hidden = false;
  $("error-state").hidden = true;
  $("main-layout").hidden = true;
  try {
    state.payload = await fetchJson("data/app_payload.json");
  } catch (err) {
    $("skeleton-state").hidden = true;
    $("error-state").hidden = false;
    $("error-message").textContent = `读取 data/app_payload.json 失败：${err.message}`;
    return;
  }
  try {
    state.harness = await fetchJson("data/web/research_harness_latest.json");
  } catch {
    state.harness = null; // 研究面板降级显示，不阻塞主产品
  }
  $("skeleton-state").hidden = true;
  $("main-layout").hidden = false;
  initAll();
}

function initAll() {
  const p = state.payload;
  for (const route of p.routes || []) state.routesById.set(route.route_id, route);

  $("header-run-id").textContent = p.run_id || "—";
  const dataTime = (p.environment && p.environment.data_generated_at) || p.generated_at || "—";
  $("header-data-time").textContent = dataTime;

  if (p.partial_data || (p.missing_inputs && p.missing_inputs.length)) {
    $("partial-banner").hidden = false;
    $("partial-banner-text").textContent =
      `部分输入缺失（${(p.missing_inputs || []).join("、") || "未知项"}），页面以降级模式展示真实数据，不伪造内容。`;
  } else {
    $("partial-banner").hidden = true;
  }
  $("partial-detail-btn").addEventListener("click", () => {
    const list = (state.payload.missing_inputs || []).join("、") || "无";
    $("partial-banner-text").textContent = `缺失输入清单：${list}。routes=${(p.routes || []).length} 条，recommendations=${Object.keys(p.recommendations || {}).length} 组。`;
  });

  initMap();
  initFlowSwitch();
  initRecommendPanel();
  initBrowseFilters();
  initOrigin();
  initProvenance();
  initResearchPanel();
  initMapButtons();
  initMobileBar();
  initAccessPanel();
  $("detail-close-btn").addEventListener("click", closeDetail);
  $("retry-btn").addEventListener("click", boot);

  applyFilters();
  renderEnvironment(null);
}

// ---------- 地图 ----------
function initMap() {
  const canvas = $("map-canvas");
  state.map = new MapView(canvas, {
    onSelect: (routeId) => {
      if (routeId) selectRoute(routeId, { fromMap: true });
      else showAll();
    },
    onHover: (routeId, x, y) => {
      const tip = $("map-tooltip");
      if (routeId) {
        const route = state.routesById.get(routeId);
        tip.textContent = route ? `${route.name_zh} · ${fmtKm(route.distance_m)} km` : routeId;
        tip.style.left = `${Math.min(x + 12, canvas.clientWidth - 200)}px`;
        tip.style.top = `${Math.max(y - 28, 4)}px`;
        tip.hidden = false;
      } else {
        tip.hidden = true;
      }
    },
  });
  const p = state.payload;
  if (p.boundary && Array.isArray(p.boundary.coordinates) && p.boundary.coordinates[0]) {
    state.map.setBoundary(p.boundary.coordinates[0]);
  }
  state.map.setRoutes((p.routes || []).map((r) => ({
    route_id: r.route_id,
    mode: r.mode,
    coordinates: r.coordinates || [],
  })));
  state.map.setEntries(p.entries || []);
  state.map.setEnvCells((p.environment && p.environment.cells) || []);
  state.map.setOriginMarker(state.origin.coord, state.origin.name_zh);
  requestAnimationFrame(() => {
    if (p.boundary) state.map.fitDistrict();
    else if (p.district) state.map.fitBounds([121.36, 31.10, 121.50, 31.26]);
    applyFilters();
  });
}

function initMapButtons() {
  $("zoom-in-btn").addEventListener("click", () => state.map.zoomBy(1.35));
  $("zoom-out-btn").addEventListener("click", () => state.map.zoomBy(1 / 1.35));
  $("fit-district-btn").addEventListener("click", () => {
    if (state.payload.boundary) state.map.fitDistrict();
    else state.map.fitBounds([121.36, 31.10, 121.50, 31.26]);
  });
  $("show-all-btn").addEventListener("click", showAll);
  const layers = [
    ["layer-entries-btn", "entries"],
    ["layer-envgrid-btn", "envGrid"],
  ];
  for (const [buttonId, layer] of layers) {
    $(buttonId).addEventListener("click", (event) => {
      const button = event.currentTarget;
      const on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(on));
      state.map.setLayerVisibility({ [layer]: on });
    });
  }
}

function showAll() {
  state.selectedId = null;
  state.map.setSelected(null, null);
  applyFilters();
  closeDetail();
}

// ---------- 双入口切换 ----------
function initFlowSwitch() {
  $("flow-recommend-btn").addEventListener("click", () => setFlow("recommend"));
  $("flow-browse-btn").addEventListener("click", () => setFlow("browse"));
}

function setFlow(flow) {
  state.flow = flow;
  const isRec = flow === "recommend";
  $("flow-recommend-btn").classList.toggle("is-active", isRec);
  $("flow-browse-btn").classList.toggle("is-active", !isRec);
  $("flow-recommend-btn").setAttribute("aria-selected", String(isRec));
  $("flow-browse-btn").setAttribute("aria-selected", String(!isRec));
  $("recommend-panel").hidden = !isRec;
  $("browse-panel").hidden = isRec;
  $("recommend-results").hidden = !isRec || !state.candidates;
  $("results-title").textContent = isRec ? "推荐候选路线" : "路线列表";
  if (!isRec) {
    state.candidates = null;
    state.candidateByRouteId.clear();
    state.fallbackRankingUsed = false;
  }
  applyFilters();
}

// ---------- 推荐流 ----------
function initRecommendPanel() {
  const prefWrap = $("rec-prefs");
  for (const set of REC_PREF_SETS) {
    const chip = el("button", {
      type: "button",
      class: "chip",
      "data-pref": set.key,
      "aria-pressed": state.recPrefs.has(set.key) ? "true" : "false",
      text: set.label,
      onclick: () => {
        state.recPrefs = new Set([set.key]); // 单选，对应 108 组固定 profile
        for (const btn of prefWrap.querySelectorAll(".chip")) {
          btn.setAttribute("aria-pressed", String(btn.dataset.pref === set.key));
        }
      },
    });
    prefWrap.append(chip);
  }
  updateRecBandLabels();
  $("rec-mode").addEventListener("change", updateRecBandLabels);
  $("recommend-submit-btn").addEventListener("click", runRecommend);

  const note = $("rec-note-input");
  const noteStatus = $("rec-note-status");
  const syncNote = () => {
    const parsed = parseNotePreference(note.value);
    if (parsed.set && !state.recPrefs.has(parsed.set.key)) {
      state.recPrefs = new Set([parsed.set.key]); // 单选，对应 108 组固定 profile
      for (const btn of prefWrap.querySelectorAll(".chip")) {
        btn.setAttribute("aria-pressed", String(btn.dataset.pref === parsed.set.key));
      }
    }
    noteStatus.textContent = noteStatusText(parsed);
  };
  note.addEventListener("input", syncNote);
}

function parseNotePreference(text) {
  const raw = String(text || "").trim();
  if (!raw) return { set: null, matchedLabels: [], residual: "" };
  let set = null;
  let residual = raw;
  const matchedLabels = [];
  for (const pref of REC_PREF_SETS) {
    const hit = pref.labels.find((label) => raw.includes(label));
    if (!hit) continue;
    matchedLabels.push(hit);
    residual = residual.split(hit).join("");
    if (!set) set = pref;
  }
  residual = residual.replace(/[\s,，、;；。.!！?？]/g, "");
  return { set, matchedLabels, residual };
}

function noteStatusText(parsed) {
  const parts = [];
  if (parsed.set) {
    parts.push(`偏好已切到「${parsed.set.label}」`);
    if (parsed.matchedLabels.length > 1) {
      parts.push(`同时提到的「${parsed.matchedLabels.slice(1).join("、")}」未采用，偏好为单选`);
    }
  } else if (parsed.residual) {
    parts.push(`未识别到偏好词，当前仍为「${currentPrefLabel()}」`);
  }
  if (parsed.residual) parts.push(`「${parsed.residual}」仅作为备注，不改变评分`);
  return parts.length ? `${parts.join("；")}。` : "";
}

function currentPrefLabel() {
  const key = [...state.recPrefs][0] || "riverside";
  const set = REC_PREF_SETS.find((s) => s.key === key);
  return set ? set.label : key;
}

function updateRecBandLabels() {
  const mode = $("rec-mode").value;
  const select = $("rec-band");
  // catalog 的 band 是整数索引(0/1/2)，label 取该 mode+band 的 band_label_zh
  const seen = new Map();
  for (const r of state.payload.routes || []) {
    if (r.mode !== mode || r.band === undefined || r.band === null) continue;
    const key = String(r.band);
    if (!seen.has(key)) seen.set(key, r.band_label_zh || `档位${key}`);
  }
  const entries = seen.size
    ? [...seen].sort((a, b) => Number(a[0]) - Number(b[0]))
    : [["0", "档位一"], ["1", "档位二"], ["2", "档位三"]];
  const prev = select.value;
  clearNode(select);
  for (const [value, label] of entries) select.append(el("option", { value, text: label }));
  if (entries.some(([v]) => v === prev)) select.value = prev;
  else select.value = entries[0][0];
}

function buildProfileKey() {
  const mode = $("rec-mode").value;
  const bandValue = $("rec-band").value;
  // profile slug 使用 band1..band3；select 值为 catalog 的整数 band 索引
  const bandSlug = /^\d+$/.test(bandValue) ? `band${Number(bandValue) + 1}` : bandValue;
  const pref = [...state.recPrefs][0] || "riverside";
  const originKey = nearestCanonicalOrigin(state.origin.coord).key;
  return `${mode}__${bandSlug}__${pref}__${originKey}`;
}

function nearestCanonicalOrigin(coord) {
  let best = CANONICAL_ORIGINS[0];
  let bestD = Infinity;
  for (const cand of CANONICAL_ORIGINS) {
    const d = haversineKm(coord, cand.coord);
    if (d < bestD) { bestD = d; best = cand; }
  }
  return best;
}

function runRecommend() {
  const key = buildProfileKey();
  const rec = (state.payload.recommendations || {})[key];
  const mode = $("rec-mode").value;
  const band = $("rec-band").value;
  const hasRec = Boolean(rec && Array.isArray(rec.candidates));
  state.fallbackRankingUsed = !hasRec;
  const candidates = hasRec ? rec.candidates : clientFallbackRank(mode, band);
  state.candidates = { key, rec, candidates };
  state.candidateByRouteId.clear();
  for (const c of candidates) state.candidateByRouteId.set(c.route_id, c);

  const note = $("rec-source-note");
  if (rec && rec.empty_reason && !candidates.length) {
    note.textContent = `评估模块返回空结果：${rec.empty_reason}`;
  } else if (hasRec) {
    note.textContent = `评估模块结果 · profile ${key} · weights_sha256 ${(state.payload.weights_sha256 || "").slice(0, 12)}…`;
  } else if ((state.payload.routes || []).length) {
    note.textContent = `评估模块缺失（${key}），已使用客户端确定性回退排序，仅基于真实路线字段，未调用任何在线 API。`;
  } else {
    note.textContent = "路线数据尚未生成，无法推荐。请先运行路线构建与 build_web_payload.py。";
  }
  renderRecommendResults(candidates);
  applyFilters();
  if (candidates.length) {
    selectRoute(candidates[0].route_id, { fromList: true, keepView: true });
  }
}

function clientFallbackRank(mode, band) {
  const prefSet = REC_PREF_SETS.find((s) => s.key === ([...state.recPrefs][0] || "riverside"));
  const prefLabels = prefSet ? prefSet.labels : [];
  const envRoutes = (state.payload.environment && state.payload.environment.routes) || {};
  const riskScore = { normal: 1, caution: 0.7, unknown: 0.5, pause: 0.2, stop: 0 };
  const scored = (state.payload.routes || [])
    .filter((r) => r.mode === mode && String(r.band) === String(band) && r.status === "accepted")
    .map((r) => {
      const env = envRoutes[r.route_id] || {};
      const pref = prefLabels.some((label) => routeMatchesLabels(r, [label])) ? 1 : 0.3;
      const risk = riskScore[env.overall_risk] ?? 0.5;
      const accessKm = state.origin.coord ? haversineKm(state.origin.coord, r.start || r.coordinates[0]) : 5;
      const access = 1 / (1 + accessKm);
      const circ = typeof r.circuity === "number" ? Math.max(0, 1.6 - r.circuity) : 0.5;
      const err = typeof r.distance_m === "number" && typeof r.actual_distance_m === "number" && r.distance_m > 0
        ? Math.max(0, 1 - Math.abs(r.actual_distance_m - r.distance_m) / r.distance_m)
        : 0.5;
      const clean = 1 - Math.min(1, ((r.repeated_edge_count || 0) + (r.local_uturn_count || 0) * 2) / 10);
      const total = 0.3 * pref + 0.25 * risk + 0.2 * access + 0.15 * circ + 0.1 * (err + clean) / 2;
      return {
        ...r,
        total_score: Math.round(total * 1000) / 10,
        overall_risk: env.overall_risk || "unknown",
        recommendation_reason_zh:
          `客户端回退排序：偏好“${prefLabels.join("、") || "未指定”匹配度一般"}，环境风险 ${RISK_LABELS[env.overall_risk] || "未知"}，` +
          `距出发点约 ${accessKm.toFixed(1)} km，环线系数 ${typeof r.circuity === "number" ? r.circuity.toFixed(2) : "—"}。`,
        rank: 0,
        provenance: "client_fallback_deterministic",
      };
    })
    .sort((a, b) => b.total_score - a.total_score || String(a.route_id).localeCompare(String(b.route_id)));
  scored.forEach((c, i) => { c.rank = i + 1; });
  return scored;
}

function renderRecommendResults(candidates) {
  const wrap = $("recommend-results");
  wrap.hidden = false;
  const primarySlot = $("primary-card-slot");
  const altSlot = $("alt-cards");
  clearNode(primarySlot);
  clearNode(altSlot);
  if (!candidates.length) {
    wrap.hidden = true;
    return;
  }
  primarySlot.append(renderRouteCard(candidates[0], { rankLabel: "首选", isPrimary: true }));
  const alts = candidates.slice(1, 3);
  const altLabels = ["备选一", "备选二"];
  alts.forEach((c, i) => altSlot.append(renderRouteCard(c, { rankLabel: altLabels[i], isPrimary: false })));
}

// ---------- 浏览流筛选 ----------
function initBrowseFilters() {
  const sportWrap = $("sport-filter");
  for (const btn of sportWrap.querySelectorAll(".seg-btn")) {
    btn.addEventListener("click", () => {
      state.filters.mode = btn.dataset.mode;
      for (const other of sportWrap.querySelectorAll(".seg-btn")) {
        other.classList.toggle("is-active", other === btn);
        other.setAttribute("aria-pressed", String(other === btn));
      }
      rebuildBandChips();
      applyFilters();
    });
  }
  rebuildBandChips();

  const prefWrap = $("pref-filter");
  for (const label of PREF_OPTIONS) {
    prefWrap.append(el("button", {
      type: "button",
      class: "chip",
      "data-pref": label,
      "aria-pressed": "false",
      text: label,
      onclick: (ev) => {
        const btn = ev.currentTarget;
        if (state.filters.prefs.has(label)) {
          state.filters.prefs.delete(label);
          btn.setAttribute("aria-pressed", "false");
        } else {
          state.filters.prefs.add(label);
          btn.setAttribute("aria-pressed", "true");
        }
        applyFilters();
      },
    }));
  }

  const envKeys = ["air_ok", "avoid_risk", "near_water", "high_green"];
  const envAvailable = Boolean(
    state.payload.environment &&
    (Object.keys(state.payload.environment.routes || {}).length ||
      (state.payload.environment.cells || []).length)
  );
  for (const key of envKeys) {
    const btn = $(`env-${key.replace(/_/g, "-")}`);
    if (!envAvailable) {
      btn.disabled = true;
      btn.title = "环境数据缺失，此筛选不可用";
      continue;
    }
    btn.addEventListener("click", () => {
      if (state.filters.env.has(key)) {
        state.filters.env.delete(key);
        btn.setAttribute("aria-pressed", "false");
      } else {
        state.filters.env.add(key);
        btn.setAttribute("aria-pressed", "true");
      }
      applyFilters();
    });
  }

  $("clear-filters-btn").addEventListener("click", clearFilters);
  $("empty-clear-btn").addEventListener("click", clearFilters);
}

function rebuildBandChips() {
  const wrap = $("band-filter");
  clearNode(wrap);
  state.filters.bands.clear();
  const mode = state.filters.mode;
  const seen = new Map();
  for (const r of state.payload.routes || []) {
    if (mode !== "all" && r.mode !== mode) continue;
    if (r.band && !seen.has(r.band)) seen.set(r.band, r.band_label_zh || r.band);
  }
  if (!seen.size) {
    wrap.append(el("span", { class: "hint", text: "当前无可用档位数据" }));
    return;
  }
  for (const [band, label] of seen) {
    wrap.append(el("button", {
      type: "button",
      class: "chip",
      "data-band": band,
      "aria-pressed": "false",
      text: label,
      onclick: (ev) => {
        const btn = ev.currentTarget;
        if (state.filters.bands.has(band)) {
          state.filters.bands.delete(band);
          btn.setAttribute("aria-pressed", "false");
        } else {
          state.filters.bands.add(band);
          btn.setAttribute("aria-pressed", "true");
        }
        applyFilters();
      },
    }));
  }
}

function clearFilters() {
  state.filters = { mode: "all", bands: new Set(), prefs: new Set(), env: new Set() };
  for (const btn of $("sport-filter").querySelectorAll(".seg-btn")) {
    const isAll = btn.dataset.mode === "all";
    btn.classList.toggle("is-active", isAll);
    btn.setAttribute("aria-pressed", String(isAll));
  }
  for (const btn of document.querySelectorAll("#band-filter .chip, #pref-filter .chip, #env-filter .chip")) {
    btn.setAttribute("aria-pressed", "false");
  }
  rebuildBandChips();
  showAll();
}

function routeMatchesLabels(route, labels) {
  const hay = [
    route.name_zh, route.area_name_zh, route.area,
    typeof route.park_relation === "string" ? route.park_relation : JSON.stringify(route.park_relation || ""),
    JSON.stringify(route.nearby_services || []),
  ].join(" ");
  return labels.some((label) => {
    if (hay.includes(label)) return true;
    // 关键词代理：偏好标签到地物词组的确定性映射
    const proxy = {
      滨江: ["滨江", "黄浦江", "江畔", "水岸"],
      水岸: ["水岸", "河", "湖", "江", "浜"],
      公园: ["公园", "植物园", "绿地", "园"],
      绿荫: ["绿荫", "林荫", "绿道", "树"],
      安静: ["安静", "幽静"],
      城市风景: ["城市", "风貌", "徐家汇", "衡复", "街区"],
    }[label] || [];
    return proxy.some((w) => hay.includes(w));
  });
}

function routeEnvFor(routeId) {
  return (state.payload.environment && state.payload.environment.routes[routeId]) || null;
}

// A live recommendation response wins over the catalog-level baseline: only the
// response knows the request (sport, band, origin, preferences) that the other
// three dimensions need. Outside a response there is still a two-dimension
// baseline for every route, so browse mode never shows an empty breakdown.
function routeScoreFor(routeId) {
  return (
    state.candidateByRouteId.get(routeId) ||
    (state.payload.route_scores && state.payload.route_scores[routeId]) ||
    null
  );
}

function envFieldKeyIncludes(patterns) {
  const specs = (state.payload.environment && state.payload.environment.field_specs) || [];
  return specs
    .map((s) => s.key)
    .filter((k) => patterns.some((pat) => String(k).toLowerCase().includes(pat)));
}

function routePassesEnvFilters(route) {
  const env = routeEnvFor(route.route_id);
  for (const key of state.filters.env) {
    if (key === "air_ok") {
      const risk = env ? env.overall_risk : "unknown";
      if (risk === "pause" || risk === "stop") return false;
    } else if (key === "avoid_risk") {
      if (!env || env.overall_risk !== "normal") return false;
    } else if (key === "near_water") {
      const waterKeys = envFieldKeyIncludes(["water", "shui"]);
      const hasWaterField = env && waterKeys.some((k) => env.exposure && env.exposure[k] &&
        typeof env.exposure[k].value === "number" && env.exposure[k].value > 0);
      if (!hasWaterField && !routeMatchesLabels(route, ["滨江", "水岸"])) return false;
    } else if (key === "high_green") {
      const greenKeys = envFieldKeyIncludes(["green", "ndvi", "lv"]);
      const vals = greenKeys.length ? greenValuesForRoutes(greenKeys) : [];
      const routeVal = env && greenKeys.length ? Math.max(...greenKeys.map((k) => (env.exposure && env.exposure[k] && typeof env.exposure[k].value === "number") ? env.exposure[k].value : -Infinity)) : -Infinity;
      const median = vals.length ? medianOf(vals) : null;
      const fieldOk = median !== null && Number.isFinite(routeVal) && routeVal >= median;
      if (!fieldOk && !routeMatchesLabels(route, ["绿荫", "公园"])) return false;
    }
  }
  return true;
}

function greenValuesForRoutes(greenKeys) {
  const out = [];
  const envRoutes = (state.payload.environment && state.payload.environment.routes) || {};
  for (const rec of Object.values(envRoutes)) {
    for (const k of greenKeys) {
      const v = rec.exposure && rec.exposure[k] && rec.exposure[k].value;
      if (typeof v === "number" && Number.isFinite(v)) out.push(v);
    }
  }
  return out;
}

function medianOf(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function currentFilteredRoutes() {
  const f = state.filters;
  let routes = (state.payload.routes || []).filter((r) => {
    if (state.flow === "recommend" && state.candidates) {
      const cMode = $("rec-mode").value;
      const cBand = $("rec-band").value;
      if (r.mode !== cMode || String(r.band) !== String(cBand)) return false;
    } else {
      if (f.mode !== "all" && r.mode !== f.mode) return false;
      if (f.bands.size && !f.bands.has(r.band)) return false;
    }
    if (f.prefs.size && ![...f.prefs].some((label) => routeMatchesLabels(r, [label]))) return false;
    if (f.env.size && !routePassesEnvFilters(r)) return false;
    return true;
  });
  if (state.flow === "recommend" && state.candidates) {
    const order = new Map(state.candidates.candidates.map((c, i) => [c.route_id, i]));
    routes = routes.sort((a, b) => (order.get(a.route_id) ?? 999) - (order.get(b.route_id) ?? 999));
  }
  return routes;
}

function applyFilters() {
  const routes = currentFilteredRoutes();
  const idSet = new Set(routes.map((r) => r.route_id));
  state.map.setFilteredIds(idSet);
  renderRouteList(routes);
  const empty = routes.length === 0 && (state.payload.routes || []).length > 0;
  $("empty-state").hidden = !empty;
  if (empty) {
    $("empty-reason").textContent = state.flow === "recommend"
      ? "当前运动方式与距离档位下没有已接受的路线，可切换档位或改用浏览模式。"
      : "当前筛选组合没有匹配路线，试试放宽距离档位或减少环境条件。";
  }
  const countText = (state.payload.routes || []).length
    ? `共 ${(state.payload.routes || []).length} 条 · 当前显示 ${routes.length} 条`
    : "路线数据尚未生成（见顶部缺失提示）";
  $("result-count").textContent = countText;
}

// ---------- 路线卡片 ----------
function renderRouteList(routes) {
  const list = $("route-list");
  clearNode(list);
  for (const route of routes) {
    const candidate = routeScoreFor(route.route_id);
    const rankLabel = candidate && state.candidates
      ? (candidate.rank === 1 ? "首选" : candidate.rank === 2 ? "备选一" : candidate.rank === 3 ? "备选二" : null)
      : null;
    list.append(el("li", {}, renderRouteCard(
      candidate ? { ...route, ...candidateFields(candidate) } : route,
      { rankLabel, isPrimary: rankLabel === "首选" }
    )));
  }
}

function candidateFields(candidate) {
  return {
    total_score: candidate.total_score,
    overall_risk: candidate.overall_risk,
    recommendation_reason_zh: candidate.recommendation_reason_zh,
    score_breakdown: candidate.score_breakdown,
    risk_pause: candidate.risk_pause,
    data_reliability: candidate.data_reliability,
  };
}

function routeGlyph(route) {
  const coords = Array.isArray(route.coordinates) ? route.coordinates : null;
  if (!coords || coords.length < 2) return null;
  const NS = "http://www.w3.org/2000/svg";
  const W = 46;
  const H = 32;
  const PAD = 3;
  let minLon = Infinity; let maxLon = -Infinity;
  let minLat = Infinity; let maxLat = -Infinity;
  for (const c of coords) {
    if (!Array.isArray(c) || c.length < 2) return null;
    if (c[0] < minLon) minLon = c[0];
    if (c[0] > maxLon) maxLon = c[0];
    if (c[1] < minLat) minLat = c[1];
    if (c[1] > maxLat) maxLat = c[1];
  }
  const spanLon = maxLon - minLon || 1;
  const spanLat = maxLat - minLat || 1;
  // 经纬度各自独立缩放：glyph 只表达路径拓扑，不是等比例地图。
  const step = Math.max(1, Math.floor(coords.length / 60));
  const pts = [];
  for (let i = 0; i < coords.length; i += step) {
    const x = PAD + ((coords[i][0] - minLon) / spanLon) * (W - PAD * 2);
    const y = H - PAD - ((coords[i][1] - minLat) / spanLat) * (H - PAD * 2);
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", String(W));
  svg.setAttribute("height", String(H));
  svg.setAttribute("class", "card-glyph");
  svg.setAttribute("aria-hidden", "true");
  const poly = document.createElementNS(NS, "polyline");
  poly.setAttribute("points", pts.join(" "));
  poly.setAttribute("fill", "none");
  poly.setAttribute("stroke", "currentColor");
  poly.setAttribute("stroke-width", "1.6");
  poly.setAttribute("stroke-linejoin", "round");
  poly.setAttribute("stroke-linecap", "round");
  svg.append(poly);
  return svg;
}

function routePm25(routeId) {
  const env = routeEnvFor(routeId);
  const rec = env && env.exposure ? env.exposure.pm25_ug_m3 : null;
  if (!rec || typeof rec.value !== "number") return null;
  return { value: rec.value.toFixed(0), status: rec.status || "unknown" };
}

function renderRouteCard(route, opts = {}) {
  const env = routeEnvFor(route.route_id);
  const pm25 = routePm25(route.route_id);
  const glyph = routeGlyph(route);
  const riskLevel = route.overall_risk || (env && env.overall_risk) || "unknown";
  const modeLabel = route.mode_label || { walk: "步行", run: "跑步", bike: "骑行" }[route.mode] || route.mode;
  const reason = route.recommendation_reason_zh ||
    (env ? `环境综合风险为「${RISK_LABELS[riskLevel] || "未知"}」，详见环境面板。` : "评估与环境数据缺失，卡片仅展示路线本体字段。");

  const card = el("article", {
    class: `route-card${opts.isPrimary ? " is-primary" : ""}${state.selectedId === route.route_id ? " is-selected" : ""}`,
    id: `route-card-${route.route_id}`,
    tabindex: "0",
    role: "button",
    "aria-label": `路线 ${route.name_zh}，${modeLabel}，${fmtKm(route.actual_distance_m ?? route.distance_m)} 公里`,
    onclick: () => selectRoute(route.route_id, { fromList: true }),
    onmouseenter: () => state.map.setHovered(route.route_id),
    onmouseleave: () => state.map.setHovered(null),
    onkeydown: (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectRoute(route.route_id, { fromList: true }); }
    },
  }, [
    el("div", { class: "card-top" }, [
      el("div", { class: "card-name", text: route.name_zh || route.route_id }),
      opts.rankLabel
        ? el("span", { class: `rank-badge${opts.isPrimary ? "" : " is-alt"}`, text: opts.rankLabel })
        : riskBadge(riskLevel),
    ]),
    el("div", { class: "card-tags" }, [
      el("span", { class: `tag tag-${route.mode}`, text: modeLabel }),
      el("span", { class: "tag", text: route.band_label_zh || route.band || "—" }),
      el("span", { class: "tag", text: route.kind_label || route.kind || "—" }),
      opts.rankLabel ? riskBadge(riskLevel) : null,
      typeof route.total_score === "number"
        ? el("span", { class: "tag num", text: `总分 ${route.total_score.toFixed(1)}` })
        : null,
    ]),
    el("div", { class: "card-metrics num" }, [
      el("span", { class: "metric" }, [el("b", { text: fmtKm(route.actual_distance_m ?? route.distance_m) }), el("span", { text: "公里" })]),
      el("span", { class: "metric" }, [el("b", { text: fmtMin(route.duration_min) }), el("span", { text: "分钟" })]),
      el("span", { class: "metric" }, [el("b", { text: typeof route.circuity === "number" ? route.circuity.toFixed(2) : "—" }), el("span", { text: "环线系数" })]),
      pm25
        ? el("span", { class: "metric", title: `PM2.5 数据状态：${pm25.status}` }, [
          el("b", { text: pm25.value }), el("span", { text: "µg/m³" }),
        ])
        : null,
      glyph ? el("span", { class: "card-glyph-wrap" }, [glyph]) : null,
    ]),
    el("p", { class: "card-reason", text: reason }),
    el("div", { class: "card-actions" }, [
      el("button", {
        type: "button",
        class: "btn btn-ghost goto-start-btn",
        text: "前往起点",
        onclick: (ev) => { ev.stopPropagation(); openAccess(route.route_id); },
      }),
      el("button", {
        type: "button",
        class: "btn btn-ghost",
        text: "详情",
        onclick: (ev) => { ev.stopPropagation(); selectRoute(route.route_id, { fromList: true }); },
      }),
    ]),
  ]);
  return card;
}

// ---------- 选中与详情 ----------
function selectRoute(routeId, opts = {}) {
  const route = state.routesById.get(routeId);
  if (!route) return;
  state.selectedId = routeId;
  state.map.setSelected(routeId, { start: route.start, end: route.end });
  if (!opts.keepView && route.bbox) {
    state.map.fitBounds(route.bbox, 60);
  }
  for (const node of document.querySelectorAll(".route-card")) node.classList.remove("is-selected");
  const card = $(`route-card-${routeId}`);
  if (card) {
    card.classList.add("is-selected");
    if (opts.fromMap) card.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }
  const candidate = routeScoreFor(routeId);
  openDetail(route, candidate);
  renderEnvironment(routeId);
  if (window.matchMedia("(max-width: 900px)").matches && opts.fromList) {
    // 移动端保持地图可见，详情以底部抽屉展示
    document.body.classList.add("detail-open");
  }
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function closeDetail() {
  $("detail-panel").hidden = true;
  document.body.classList.remove("detail-open");
}

function openDetail(route, candidate) {
  const panel = $("detail-panel");
  panel.hidden = false;
  $("detail-title").textContent = route.name_zh || route.route_id;
  const env = routeEnvFor(route.route_id);
  const riskLevel = (candidate && candidate.overall_risk) || (env && env.overall_risk) || "unknown";
  const summary = $("detail-summary");
  clearNode(summary);
  summary.append(
    riskBadge(riskLevel),
    el("span", {
      class: "hint",
      text: ` ${route.mode_label || route.mode} · ${route.band_label_zh || ""} · ${route.kind_label || ""} · ${fmtKm(route.actual_distance_m ?? route.distance_m)} km · ${fmtMin(route.duration_min)} 分钟 · ${route.route_id}`,
    })
  );

  const breakdownWrap = $("score-breakdown");
  clearNode(breakdownWrap);
  const breakdown = candidate && candidate.score_breakdown;
  if (breakdown && Object.keys(breakdown).length) {
    const scopeLabel = candidate.note_zh ? "目录级基线" : "本次请求";
    breakdownWrap.append(el("h3", {
      text: `评分分解 · ${scopeLabel}（总分 ${typeof candidate.total_score === "number" ? candidate.total_score.toFixed(1) : "—"}）`,
    }));
    for (const [dim, info] of Object.entries(breakdown)) {
      breakdownWrap.append(renderDimension(dim, info));
    }
    if (candidate.recommendation_reason_zh) {
      breakdownWrap.append(el("p", { class: "hint", text: `推荐理由：${candidate.recommendation_reason_zh}` }));
    }
    if (candidate.note_zh) {
      breakdownWrap.append(el("p", { class: "fallback-note", text: candidate.note_zh }));
    }
  } else {
    breakdownWrap.append(
      el("h3", { text: "评分分解" }),
      el("p", { class: "fallback-note", text: "评估模块结果缺失（见顶部 partial 提示），无法展示五维分解；以下为路线本体的真实质量指标。" })
    );
  }

  const gates = $("gate-metrics");
  clearNode(gates);
  const gateRows = [
    ["实际距离", `${fmtKm(route.actual_distance_m)} km（目标 ${fmtKm(route.distance_m)} km）`],
    ["道路吸附率", fmtRatio(route.road_snapping_ratio)],
    ["区内比例", fmtRatio(route.in_district_ratio)],
    ["环线系数", typeof route.circuity === "number" ? route.circuity.toFixed(3) : "—"],
    ["重复边数", String(route.repeated_edge_count ?? "—")],
    ["真实自交数", String(route.proper_self_intersection_count ?? "—")],
    ["局部掉头数", String(route.local_uturn_count ?? "—")],
    ["局部回环数", String(route.local_return_loop_count ?? "—")],
    ["坐标点数", String(route.coordinate_count ?? (route.coordinates || []).length)],
    ["状态", String(route.status ?? "—")],
  ];
  for (const [k, v] of gateRows) {
    gates.append(el("dt", { text: k }), el("dd", { class: "num", text: v }));
  }

  const park = $("park-relation");
  park.textContent = route.park_relation
    ? (typeof route.park_relation === "string" ? route.park_relation : JSON.stringify(route.park_relation))
    : "无公园关系记录";

  const services = $("nearby-services");
  clearNode(services);
  const svcList = Array.isArray(route.nearby_services) ? route.nearby_services : [];
  if (!svcList.length) services.append(el("li", { class: "hint", text: "无就近服务点记录" }));
  for (const svc of svcList.slice(0, 12)) {
    const text = typeof svc === "string" ? svc : `${svc.name_zh || svc.name || svc.poi_id || "?"}${svc.category ? ` · ${svc.category}` : ""}${typeof svc.distance_m === "number" ? ` · ${Math.round(svc.distance_m)} m` : ""}`;
    services.append(el("li", { class: "tag", text }));
  }

  const cellIds = $("env-cell-ids");
  cellIds.textContent = env && Array.isArray(env.cell_ids) && env.cell_ids.length
    ? env.cell_ids.join(", ")
    : "环境网格数据缺失";

  const accessBtn = $("detail-access-btn");
  accessBtn.onclick = () => openAccess(route.route_id);
  // 移动端详情为 fixed 底部抽屉，覆盖在当前视图之上，不强制切换视图
}

function fmtRatio(v) {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(3) : "—";
}

function renderDimension(dim, info) {
  const score = typeof info.score === "number" ? info.score : null;
  const block = el("div", { class: "dim-block" }, [
    el("div", { class: "dim-head" }, [
      el("span", { text: dimLabel(dim) }),
      el("span", { class: "dim-score num", text: score !== null ? `${score.toFixed(1)} × ${fmtWeight(info.weight)}` : "—" }),
    ]),
    el("div", { class: "score-bar" }, [
      el("div", { class: "score-fill", style: `width:${score !== null ? Math.max(0, Math.min(100, score)) : 0}%` }),
    ]),
    info.reason_zh ? el("p", { class: "dim-reason", text: info.reason_zh }) : null,
  ]);
  if (Array.isArray(info.contributors) && info.contributors.length) {
    const table = el("table", { class: "contrib-table" }, [
      el("thead", {}, el("tr", {}, [
        el("th", { text: "指标" }), el("th", { text: "原始值" }), el("th", { text: "单位" }),
        el("th", { text: "归一化" }), el("th", { text: "来源" }),
      ])),
    ]);
    const tbody = el("tbody");
    for (const c of info.contributors) {
      tbody.append(el("tr", {}, [
        el("td", { text: String(c.indicator ?? "—") }),
        el("td", { class: "num", text: c.raw_value === null || c.raw_value === undefined ? "缺失" : String(c.raw_value) }),
        el("td", { text: String(c.unit ?? "—") }),
        el("td", { class: "num", text: typeof c.normalised === "number" ? c.normalised.toFixed(2) : "—" }),
        el("td", { text: String(c.provenance ?? "—") }),
      ]));
    }
    table.append(tbody);
    block.append(table);
  }
  return block;
}

function dimLabel(dim) {
  return {
    environment_health: "环境健康",
    sport_match: "运动匹配",
    access_convenience: "接驳便利",
    route_quality: "路线质量",
    user_preference: "用户偏好",
    preference_fit: "偏好匹配",
  }[dim] || dim;
}

function fmtWeight(w) {
  return typeof w === "number" ? w.toFixed(2) : "—";
}

// ---------- 环境面板 ----------
function renderEnvironment(routeId) {
  const envRoot = state.payload.environment || {};
  const scope = $("environment-scope");
  const list = $("env-field-list");
  clearNode(list);
  const specs = envRoot.field_specs || [];
  const specByKey = new Map(specs.map((s) => [s.key, s]));
  let records = [];

  if (routeId && envRoot.routes && envRoot.routes[routeId]) {
    const rec = envRoot.routes[routeId];
    scope.textContent = `当前路线 ${routeId} 的逐字段暴露值（聚合自 ${ (rec.cell_ids || []).length } 个网格单元）。`;
    records = Object.entries(rec.exposure || {}).map(([key, v]) => ({
      key,
      value: v.value,
      unit: v.unit,
      status: v.status,
      as_of: v.as_of || envRoot.data_generated_at || "—",
      provenance: v.provenance || "",
      aggregation: v.aggregation || "",
    }));
    for (const missing of rec.missing_fields || []) {
      records.push({ key: missing, value: null, unit: (specByKey.get(missing) || {}).unit || "—", status: "unavailable", as_of: "—", provenance: "", missing: true });
    }
  } else {
    scope.textContent = envRoot.data_generated_at
      ? `网格级概览（${(envRoot.cells || []).length} 个单元 · 数据生成于 ${envRoot.data_generated_at}）。选择一条路线可查看逐字段暴露值。`
      : "环境数据缺失（environment_dashboard.json 未生成），环境筛选与阈值展示不可用。";
    const missingRate = envRoot.missing_rate || {};
    records = specs.map((s) => ({
      key: s.key,
      value: null,
      unit: s.unit,
      status: missingRate[s.key] === undefined ? "unavailable" : "estimated",
      as_of: envRoot.data_generated_at || "—",
      provenance: s.provenance || "",
      rateNote: missingRate[s.key] !== undefined ? `缺失率 ${(missingRate[s.key] * 100).toFixed(1)}%` : "字段规格已声明，数据未生成",
    }));
  }

  for (const rec of records) {
    const spec = specByKey.get(rec.key) || {};
    const valueText = rec.missing || rec.value === null || rec.value === undefined
      ? "缺失"
      : `${rec.value} ${rec.unit || spec.unit || ""}`;
    list.append(el("li", {}, [
      el("span", { class: "env-field-name", text: rec.key }),
      el("span", { class: "env-field-value num", text: valueText }),
      el("span", { class: "env-field-meta" }, [
        statusBadge(rec.status),
        el("span", { text: `截至 ${rec.as_of}` }),
        rec.aggregation ? el("span", { text: `聚合：${rec.aggregation}` }) : null,
        rec.rateNote ? el("span", { text: rec.rateNote }) : null,
        rec.provenance ? el("span", { class: "mono", text: rec.provenance }) : null,
        rec.missing ? el("span", { text: "缺失原因：本 run 数据源未提供该字段" }) : null,
      ]),
    ]));
  }

  // 数据可靠度：measured 1.0 / derived 0.9 / estimated 0.75，unavailable 不计入
  const usable = records.filter((r) => RELIABILITY_MULTIPLIER[r.status] !== undefined && !r.missing && r.value !== null);
  const reliability = $("data-reliability");
  if (usable.length) {
    const avg = usable.reduce((acc, r) => acc + RELIABILITY_MULTIPLIER[r.status], 0) / usable.length;
    reliability.textContent = "";
    reliability.append(el("span", { text: "数据可靠度 " }), el("b", { class: "num", text: `${Math.round(avg * 100)}%` }),
      el("span", { class: "hint", text: ` （measured 1.0 / derived 0.9 / estimated 0.75，unavailable 不计入，样本 ${usable.length} 项）` }));
  } else {
    reliability.textContent = "数据可靠度 —（无可用字段记录）";
  }

  const missingBlock = $("env-missing-block");
  const missingList = $("env-missing-list");
  clearNode(missingList);
  const missingRecords = records.filter((r) => r.missing || r.value === null);
  missingBlock.hidden = missingRecords.length === 0;
  for (const r of missingRecords) {
    missingList.append(el("li", { text: `${r.key}：缺失${r.rateNote ? ` · ${r.rateNote}` : ""}` }));
  }

  const thBlock = $("env-threshold-block");
  const thList = $("risk-thresholds");
  clearNode(thList);
  const thresholds = envRoot.thresholds || envRoot.risk_thresholds || {};
  const thKeys = Object.keys(thresholds);
  thBlock.hidden = thKeys.length === 0;
  const currentExposure = routeId && envRoot.routes && envRoot.routes[routeId]
    ? envRoot.routes[routeId].exposure || {}
    : {};
  for (const key of thKeys) {
    const th = thresholds[key];
    const cur = currentExposure[key] && currentExposure[key].value;
    const breached = typeof cur === "number" && thresholdBreached(cur, th);
    thList.append(el("li", { class: breached ? "threshold-breached" : "" }, [
      el("span", { text: key }),
      el("span", { class: "num", text: `${JSON.stringify(th)}${typeof cur === "number" ? ` · 当前 ${cur}${breached ? " · 已触发" : ""}` : ""}` }),
    ]));
  }

  const exBlock = $("excluded-fields-block");
  const exList = $("excluded-fields");
  clearNode(exList);
  const excluded = envRoot.excluded_fields || [];
  exBlock.hidden = excluded.length === 0;
  for (const item of excluded) {
    const text = typeof item === "string" ? item : `${item.key || item.field || "?"}：${item.reason || item.reason_zh || "未说明原因"}`;
    exList.append(el("li", { text }));
  }
}

function thresholdBreached(value, th) {
  if (typeof th === "number") return value >= th;
  if (Array.isArray(th)) return th.some((t) => typeof t === "number" && value >= t);
  if (th && typeof th === "object") {
    const nums = Object.values(th).filter((v) => typeof v === "number");
    return nums.some((t) => value >= t);
  }
  return false;
}

function initEnvironmentToggle() {
  const btn = $("environment-toggle-btn");
  btn.addEventListener("click", () => {
    const body = $("environment-body");
    body.hidden = !body.hidden;
    btn.setAttribute("aria-expanded", String(!body.hidden));
  });
}

// ---------- 出发点 ----------
function initOrigin() {
  const input = $("origin-input");
  const sug = $("origin-suggestions");
  const statusEl = $("origin-status");
  statusEl.textContent = `当前出发点：${state.origin.name_zh}（默认）`;

  const entries = (state.payload.entries || []).filter((e) => e.name_zh && Array.isArray(e.coord));
  input.addEventListener("input", () => {
    const q = input.value.trim();
    clearNode(sug);
    if (!q) { sug.hidden = true; return; }
    const matches = entries.filter((e) => e.name_zh.includes(q)).slice(0, 8);
    if (!matches.length) {
      sug.append(el("li", {}, el("span", { class: "suggest-btn", text: "无匹配地点，可直接回车使用文本作为标注" })));
      sug.hidden = false;
      return;
    }
    for (const m of matches) {
      sug.append(el("li", { role: "option" }, el("button", {
        type: "button",
        class: "suggest-btn",
        onclick: () => {
          setOrigin({ name_zh: m.name_zh, coord: m.coord, key: m.poi_id });
          sug.hidden = true;
          input.value = m.name_zh;
        },
      }, [
        document.createTextNode(m.name_zh),
        el("span", { class: "suggest-kind", text: `${m.kind || ""}${m.category ? ` · ${m.category}` : ""}` }),
      ])));
    }
    sug.hidden = false;
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      const q = input.value.trim();
      const hit = entries.find((e) => e.name_zh === q) || entries.find((e) => e.name_zh.includes(q));
      if (hit) {
        setOrigin({ name_zh: hit.name_zh, coord: hit.coord, key: hit.poi_id });
        sug.hidden = true;
      } else if (q) {
        statusEl.textContent = `未在本地地点库中找到「${q}」，保持当前出发点不变。`;
      }
    } else if (ev.key === "Escape") {
      sug.hidden = true;
    }
  });
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".origin-input-wrap")) sug.hidden = true;
  });

  $("use-my-location-btn").addEventListener("click", () => {
    if (!("geolocation" in navigator)) {
      setOrigin({ ...DEFAULT_ORIGIN });
      statusEl.textContent = "此浏览器不支持地理定位，已回退到默认出发点（徐家汇）。";
      return;
    }
    statusEl.textContent = "正在获取定位……";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coord = [
          Math.round(pos.coords.longitude * 1e6) / 1e6,
          Math.round(pos.coords.latitude * 1e6) / 1e6,
        ];
        const distToDistrict = haversineKm(coord, [121.43, 31.18]);
        setOrigin({ name_zh: "我的位置", coord, key: "geolocation" });
        statusEl.textContent = distToDistrict > 25
          ? `定位成功，但距徐汇区约 ${distToDistrict.toFixed(0)} km，接驳估算仅供参考。`
          : "定位成功，已更新出发点标记。";
      },
      (err) => {
        const msg = err.code === err.PERMISSION_DENIED
          ? "定位权限被拒绝，已回退到默认出发点（徐家汇）。"
          : err.code === err.TIMEOUT
            ? "定位超时，已回退到默认出发点（徐家汇）。"
            : "定位不可用，已回退到默认出发点（徐家汇）。";
        setOrigin({ ...DEFAULT_ORIGIN });
        statusEl.textContent = msg;
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
    );
  });
}

function setOrigin(origin) {
  state.origin = origin;
  $("origin-status").textContent = `当前出发点：${origin.name_zh}（${origin.coord[0].toFixed(4)}, ${origin.coord[1].toFixed(4)}）`;
  state.map.setOriginMarker(origin.coord, origin.name_zh);
  if (state.selectedId) openAccess(state.selectedId, { silent: true });
}

// ---------- 接驳面板 ----------
function initAccessPanel() {
  $("access-close-btn").addEventListener("click", () => { $("access-panel").hidden = true; });
  initEnvironmentToggle();
}

function openAccess(routeId, opts = {}) {
  const route = state.routesById.get(routeId);
  if (!route) return;
  const panel = $("access-panel");
  const start = route.start || (route.coordinates || [])[0];
  if (!start) return;
  const origin = state.origin.coord;

  const cases = (state.payload.access_cases || []).filter(
    (c) => c.destination && c.destination.route_id === routeId
  );
  let match = null;
  if (cases.length) {
    // 多个接驳样例时，取出发点与当前原点最接近的一个（确定性）
    match = cases.reduce((best, c) => {
      const coord = (c.origin && c.origin.coord) || null;
      const d = coord ? haversineKm(origin, coord) : Infinity;
      const bestCoord = best && best.origin && best.origin.coord;
      const bestD = bestCoord ? haversineKm(origin, bestCoord) : Infinity;
      return d < bestD ? c : best;
    }, cases[0]);
  }

  let data;
  if (match) {
    data = {
      straight: match.straight_line_m,
      estimated: match.estimated_access_m,
      minutes: match.estimated_access_min,
      detour: match.detour_factor,
      mode: match.access_mode || route.mode || "walk",
      speed: match.access_speed_kmh,
      provenance: match.provenance || "access_cases.json",
      note: match.note || "确定性估算，未调用任何在线路径规划 API。",
    };
  } else {
    const straightKm = haversineKm(origin, start);
    const speed = ACCESS_SPEED_KMH[route.mode] || 4.8;
    const estKm = straightKm * FALLBACK_DETOUR;
    data = {
      straight: Math.round(straightKm * 1000),
      estimated: Math.round(estKm * 1000),
      minutes: Math.round((estKm / speed) * 60),
      detour: FALLBACK_DETOUR,
      mode: route.mode || "walk",
      speed,
      provenance: "客户端确定性估算（build_web_payload 未提供匹配 access case）",
      note: "这是直线距离 × 固定绕行系数的确定性估算，没有调用任何在线路径规划 API。",
    };
  }

  const details = $("access-details");
  clearNode(details);
  const rows = [
    ["路线起点", `${route.name_zh} · ${start[0].toFixed(6)}, ${start[1].toFixed(6)}`],
    ["出发点", `${state.origin.name_zh} · ${origin[0].toFixed(6)}, ${origin[1].toFixed(6)}`],
    ["直线距离", `${(data.straight / 1000).toFixed(2)} km`],
    ["估算接驳距离", `${(data.estimated / 1000).toFixed(2)} km`],
    ["估算接驳时间", `${data.minutes} 分钟`],
    ["绕行系数", String(data.detour)],
    ["接驳方式 / 速度", `${data.mode} · ${data.speed} km/h`],
    ["数据来源", data.provenance],
  ];
  for (const [k, v] of rows) {
    details.append(el("dt", { text: k }), el("dd", { class: "num", text: v }));
  }
  $("access-note").textContent = data.note;

  const from = `${origin[0].toFixed(6)},${origin[1].toFixed(6)}`;
  const to = `${start[0].toFixed(6)},${start[1].toFixed(6)}`;
  const osmLink = $("access-osm-link");
  osmLink.href = `https://www.openstreetmap.org/directions?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
  const amapLink = $("access-amap-link");
  amapLink.href = `https://uri.amap.com/navigation?from=${encodeURIComponent(`${origin[0].toFixed(6)},${origin[1].toFixed(6)},起点`)}&to=${encodeURIComponent(`${start[0].toFixed(6)},${start[1].toFixed(6)},终点`)}&mode=walk`;

  if (!opts.silent) panel.hidden = false;
}

// ---------- 研究面板 / 溯源 ----------
function initResearchPanel() {
  const btn = $("research-toggle-btn");
  btn.addEventListener("click", () => {
    const body = $("research-body");
    body.hidden = !body.hidden;
    btn.setAttribute("aria-expanded", String(!body.hidden));
  });
  const h = state.harness;
  $("research-question").textContent = h && h.research_question ? h.research_question : "研究摘要文件缺失（data/web/research_harness_latest.json）。";
  $("research-hypothesis").textContent = h && h.hypothesis ? h.hypothesis : "—";
  const weightsList = $("research-weights");
  clearNode(weightsList);
  const weights = state.payload.weights || {};
  const weightKeys = Object.keys(weights);
  if (weightKeys.length) {
    for (const key of weightKeys) {
      const w = weights[key];
      weightsList.append(el("li", {}, [
        el("span", { text: dimLabel(key) }),
        el("b", { class: "num", text: typeof w === "number" ? w.toFixed(2) : String(w) }),
      ]));
    }
  } else {
    weightsList.append(el("li", { text: "权重文件缺失（default_weights.json）" }));
  }
  const metrics = h && h.metrics ? h.metrics : null;
  $("research-metrics").textContent = metrics && metrics.available
    ? `评分维度：${(metrics.scoring_dimensions || []).map(dimLabel).join("、")}；缺失指标默认分 ${metrics.missing_metric_score ?? "—"}。`
    : "实验指标摘要缺失。";
  $("research-status").textContent = h
    ? `status=${h.status} · provider=${h.provider} · model=${h.model_name} · dashscope_api_used=${String(h.dashscope_api_used)}`
    : "";
}

function initProvenance() {
  const list = $("provenance-list");
  const prov = state.payload.provenance || {};
  for (const src of prov.sources || []) list.append(el("li", { class: "mono", text: src }));
  for (const lic of prov.licences || []) list.append(el("li", { text: `许可：${lic}` }));
  for (const note of prov.notes || []) list.append(el("li", { text: note }));
  list.append(el("li", { class: "mono", text: `crs=${state.payload.crs} · weights_sha256=${(state.payload.weights_sha256 || "—").slice(0, 16)}…` }));
}

// ---------- 移动端 ----------
function initMobileBar() {
  for (const btn of document.querySelectorAll("#mobile-action-bar .mab-btn")) {
    btn.addEventListener("click", () => setMobileView(btn.dataset.view));
  }
}

function setMobileView(view) {
  if (!window.matchMedia("(max-width: 900px)").matches) return;
  document.body.classList.remove("view-map", "view-list", "view-filters", "view-detail");
  document.body.classList.add(`view-${view}`);
  for (const btn of document.querySelectorAll("#mobile-action-bar .mab-btn")) {
    const active = btn.dataset.view === view;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", String(active));
  }
  if (view === "detail" && $("detail-panel").hidden) {
    if (state.selectedId) {
      const candidate = routeScoreFor(state.selectedId);
      openDetail(state.routesById.get(state.selectedId), candidate);
    } else {
      $("detail-summary").textContent = "尚未选择路线：请先在地图或列表中点击一条路线。";
      $("detail-panel").hidden = false;
    }
  }
  if (view === "map") state.map.render();
}

// ---------- 启动 ----------
boot();
