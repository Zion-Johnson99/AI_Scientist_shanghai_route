// DOM-stub smoke test for web/app.js: exercises boot, both flows, degraded
// states and every always-visible control without a browser. Run from
// workspace/source with: node tests/smoke_web_dom.mjs
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const webDir = join(sourceRoot, "web");
const errors = [];
process.on("unhandledRejection", (e) => errors.push(`unhandledRejection: ${(e && e.stack) || e}`));

class ClassList {
  constructor() { this.s = new Set(); }
  add(...c) { c.forEach((x) => this.s.add(x)); }
  remove(...c) { c.forEach((x) => this.s.delete(x)); }
  toggle(c, force) {
    const on = force === undefined ? !this.s.has(c) : Boolean(force);
    if (on) this.s.add(c); else this.s.delete(c);
    return on;
  }
  contains(c) { return this.s.has(c); }
}

const CTX = new Proxy({}, {
  get: (t, p) => (p in t ? t[p] : () => {}),
  set: (t, p, v) => { t[p] = v; return true; },
});

class FakeEl {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.classList = new ClassList(); this.style = {}; this.dataset = {};
    this.options = []; this.hidden = false; this.disabled = false;
    this.textContent = ""; this._value = ""; this.width = 0; this.height = 0;
    this.clientWidth = 800; this.clientHeight = 600;
  }
  get className() { return [...this.classList.s].join(" "); }
  set className(v) {
    this.classList = new ClassList();
    String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classList.add(c));
  }
  get value() { return this._value; }
  set value(v) { this._value = v; }
  get firstChild() { return this.children[0] || null; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "class") this.className = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  append(...ch) { for (const c of ch) { this.children.push(c); this.options.push(c); } }
  appendChild(c) { this.append(c); }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  closest() { return null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  setPointerCapture() {}
  getContext() { return CTX; }
  scrollIntoView() {}
  fire(type, ev = {}) {
    for (const fn of this.listeners[type] || []) {
      fn({ target: this, currentTarget: this, preventDefault() {}, ...ev });
    }
  }
}

const byId = new Map();
globalThis.document = {
  getElementById(id) { if (!byId.has(id)) byId.set(id, new FakeEl("div")); return byId.get(id); },
  createElement(tag) { return new FakeEl(tag); },
  createTextNode(t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
  querySelectorAll() { return []; },
  addEventListener() {},
  body: new FakeEl("body"),
};
globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {} }), devicePixelRatio: 1 };
Object.defineProperty(globalThis, "navigator", { value: {}, configurable: true });
globalThis.requestAnimationFrame = (cb) => cb();
globalThis.fetch = async (url) => {
  const p = join(webDir, String(url).split("?")[0]);
  if (!existsSync(p)) return { ok: false, status: 404, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => JSON.parse(readFileSync(p, "utf8")) };
};

// 与 index.html 初始状态保持一致：research-body 默认折叠
{
  const researchBody = new FakeEl("div");
  researchBody.hidden = true;
  byId.set("research-body", researchBody);
}
// 真实 <select> 会报告 selected 选项；stub 默认为空字符串
{
  const recMode = new FakeEl("select");
  recMode.value = "run";
  byId.set("rec-mode", recMode);
}

await import(pathToFileURL(join(webDir, "app.js")).href);
await new Promise((r) => setTimeout(r, 300));

const click = (id) => byId.get(id) && byId.get(id).fire("click");
let failed = 0;
const check = (name, cond) => {
  console.log(`${cond ? "PASS" : "FAIL"} ${name}`);
  if (!cond) failed += 1;
};
const text = (id) => byId.get(id)?.textContent || "";

check("main-layout shown after boot", byId.get("main-layout")?.hidden === false);
check("skeleton hidden after boot", byId.get("skeleton-state")?.hidden === true);
check("header run id filled", text("header-run-id").length > 3);

const payload = JSON.parse(readFileSync(join(webDir, "data", "app_payload.json"), "utf8"));
if (payload.partial_data) {
  check("partial banner visible (degraded data)", byId.get("partial-banner")?.hidden === false);
  click("partial-detail-btn");
  check("partial detail expands missing list", text("partial-banner-text").includes("缺失输入清单"));
}

click("flow-browse-btn");
check("browse flow activates panel", byId.get("browse-panel")?.hidden === false);
click("flow-recommend-btn");
check("recommend flow reactivates", byId.get("recommend-panel")?.hidden === false);
click("recommend-submit-btn");
check("recommend note explains data source", text("rec-source-note").length > 5);
click("use-my-location-btn");
check("geolocation degrades with Chinese message", text("origin-status").includes("默认出发点"));
click("clear-filters-btn");
click("show-all-btn");
click("zoom-in-btn"); click("zoom-out-btn"); click("fit-district-btn");
click("research-toggle-btn");
check("research body opens", byId.get("research-body")?.hidden === false);
check("research question filled", text("research-question").length > 20);
click("environment-toggle-btn");
check("environment body collapses", byId.get("environment-body")?.hidden === true);
click("environment-toggle-btn");
check("reliability line rendered", text("data-reliability").includes("数据可靠度"));
check("provenance list rendered", (byId.get("provenance-list")?.children.length || 0) > 0);

if (payload.routes.length > 0) {
  check("route list rendered from real data", (byId.get("route-list")?.children.length || 0) > 0);
  const firstCard = byId.get("route-list").children[0].children[0]; // li > article.route-card
  firstCard.fire("click");
  check("card click opens detail", byId.get("detail-panel")?.hidden === false);
  check("detail gate metrics rendered", (byId.get("gate-metrics")?.children.length || 0) > 0);
  click("detail-access-btn");
  check("access panel opens", byId.get("access-panel")?.hidden === false);
  const osmHref = byId.get("access-osm-link")?.href || byId.get("access-osm-link")?.attrs.href || "";
  const amapHref = byId.get("access-amap-link")?.href || byId.get("access-amap-link")?.attrs.href || "";
  check("access osm link built from start coord",
    osmHref.startsWith("https://www.openstreetmap.org/directions?from="));
  check("access amap link built from start coord",
    amapHref.startsWith("https://uri.amap.com/navigation?from="));
}

check("no uncaught errors", errors.length === 0 && failed === 0);
if (errors.length) console.log(errors.join("\n"));
if (failed || errors.length) process.exitCode = 1;
console.log(failed || errors.length ? "SMOKE FAIL" : "SMOKE OK");
