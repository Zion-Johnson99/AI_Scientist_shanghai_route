// Contract tests for the web payload and the published local product.
// Run with: node --test   (from workspace/source/node)
// Skips gracefully when the parallel data build has not produced files yet.

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const sourceRoot = join(here, "..");
const runRoot = join(sourceRoot, "..", "..");

const CRS_EXACT = "CRS84/WGS84 (lon,lat)";
const ROUTE_ID_RE = /^XH_(WALK|RUN|BIKE)_\d{4}$/;
const STATUS_DOMAIN = new Set(["measured", "derived", "estimated", "unavailable"]);
const RISK_DOMAIN = new Set(["normal", "caution", "pause", "stop", "unknown"]);

function readJsonIfExists(path) {
  if (!existsSync(path)) return { data: null, reason: `file not built yet: ${path}` };
  try {
    return { data: JSON.parse(readFileSync(path, "utf8")), reason: null };
  } catch (err) {
    return { data: null, reason: `unparseable JSON: ${err.message}` };
  }
}

function readTextIfExists(path) {
  if (!existsSync(path)) return null;
  return readFileSync(path, "utf8");
}

function* walkValues(node, path = "$") {
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i += 1) yield* walkValues(node[i], `${path}[${i}]`);
  } else if (node && typeof node === "object") {
    for (const [k, v] of Object.entries(node)) yield* walkValues(v, `${path}.${k}`);
  } else {
    yield { path, value: node };
  }
}

const targets = [
  {
    label: "dev",
    payloadPath: join(sourceRoot, "web", "data", "app_payload.json"),
    htmlPath: join(sourceRoot, "web", "index.html"),
    cssPath: join(sourceRoot, "web", "styles.css"),
    jsPaths: [join(sourceRoot, "web", "app.js"), join(sourceRoot, "web", "map.js")],
  },
  {
    label: "published",
    payloadPath: join(runRoot, "publish", "local-product", "data", "app_payload.json"),
    htmlPath: join(runRoot, "publish", "local-product", "index.html"),
    cssPath: join(runRoot, "publish", "local-product", "styles.css"),
    jsPaths: [
      join(runRoot, "publish", "local-product", "app.js"),
      join(runRoot, "publish", "local-product", "map.js"),
    ],
  },
];

function degradedReason(payload) {
  if (!payload) return "payload file not built yet";
  if (!Array.isArray(payload.routes) || payload.routes.length === 0) {
    const missing = (payload.missing_inputs || []).join(", ") || "unknown";
    return `payload degraded, route data not generated yet (missing_inputs: ${missing})`;
  }
  return null;
}

function envReason(payload) {
  const base = degradedReason(payload);
  if (base) return base;
  const env = payload.environment;
  if (!env || !Array.isArray(env.cells) || env.cells.length === 0) {
    return "environment_dashboard.json not generated yet; environment section degraded";
  }
  return null;
}

// A portfolio shorter than 90 routes is a contract violation, not a missing
// precondition. Skipping instead of failing let `node --test` exit 0 — skipped
// tests never affect the exit code — so checks/generated_quality.json recorded
// the Node contract gate as passed on an 87-route payload with these three
// assertions never executed.

for (const target of targets) {
  const { label } = target;
  const { data: payload, reason: payloadReason } = readJsonIfExists(target.payloadPath);
  const html = readTextIfExists(target.htmlPath);
  const css = readTextIfExists(target.cssPath);
  const skipData = payloadReason || degradedReason(payload);
  const skipEnv = payloadReason || envReason(payload);

  test(`[${label}] payload parses and exposes schema_version 1`, { skip: payloadReason || false }, () => {
    assert.equal(payload.schema_version, 1);
    assert.equal(typeof payload.run_id, "string");
    assert.ok(payload.run_id.length > 0);
  });

  test(`[${label}] crs is exactly "${CRS_EXACT}"`, { skip: skipData || false }, () => {
    assert.equal(payload.crs, CRS_EXACT);
  });

  test(`[${label}] payload contains 90 routes`, { skip: skipData || false }, () => {
    assert.equal(payload.routes.length, 90);
  });

  test(`[${label}] each mode has exactly 30 routes`, { skip: skipData || false }, () => {
    const counts = {};
    for (const r of payload.routes) counts[r.mode] = (counts[r.mode] || 0) + 1;
    assert.equal(counts.walk, 30);
    assert.equal(counts.run, 30);
    assert.equal(counts.bike, 30);
  });

  test(`[${label}] band counts per mode are 10/10/10`, { skip: skipData || false }, () => {
    const perMode = {};
    for (const r of payload.routes) {
      perMode[r.mode] = perMode[r.mode] || {};
      perMode[r.mode][r.band] = (perMode[r.mode][r.band] || 0) + 1;
    }
    for (const mode of ["walk", "run", "bike"]) {
      const bands = Object.values(perMode[mode]).sort((a, b) => a - b);
      assert.deepEqual(bands, [10, 10, 10], `mode ${mode} band counts`);
    }
  });

  test(`[${label}] route_id unique and matches XH_(WALK|RUN|BIKE)_dddd`, { skip: skipData || false }, () => {
    const ids = new Set();
    for (const r of payload.routes) {
      assert.match(r.route_id, ROUTE_ID_RE);
      assert.ok(!ids.has(r.route_id), `duplicate route_id ${r.route_id}`);
      ids.add(r.route_id);
    }
  });

  test(`[${label}] every route has >= 2 in-range [lon,lat] coordinates`, { skip: skipData || false }, () => {
    for (const r of payload.routes) {
      assert.ok(Array.isArray(r.coordinates) && r.coordinates.length >= 2, `${r.route_id} coords`);
      for (const c of r.coordinates) {
        assert.ok(Array.isArray(c) && c.length === 2, `${r.route_id} coord shape`);
        assert.ok(c[0] >= 121.30 && c[0] <= 121.55, `${r.route_id} lon ${c[0]}`);
        assert.ok(c[1] >= 31.05 && c[1] <= 31.30, `${r.route_id} lat ${c[1]}`);
      }
    }
  });

  test(`[${label}] boundary ring has >= 100 vertices and is closed`, { skip: skipData || false }, () => {
    const boundary = payload.boundary;
    assert.ok(boundary && boundary.type === "Polygon", "boundary polygon present");
    const ring = boundary.coordinates[0];
    assert.ok(ring.length >= 100, `ring vertex count ${ring.length}`);
    assert.deepEqual(ring[0], ring[ring.length - 1], "ring must be closed");
  });

  test(`[${label}] environment grid has exactly 54 cells`, { skip: skipEnv || false }, () => {
    assert.equal(payload.environment.cells.length, 54);
  });

  test(`[${label}] environment route keys all exist in route id set`, { skip: skipEnv || false }, () => {
    const ids = new Set(payload.routes.map((r) => r.route_id));
    for (const key of Object.keys(payload.environment.routes || {})) {
      assert.ok(ids.has(key), `environment route key ${key} not a known route`);
    }
  });

  test(`[${label}] env units match canonical field_specs units and statuses in domain`, { skip: skipEnv || false }, () => {
    const specUnit = new Map(payload.environment.field_specs.map((s) => [s.key, s.unit]));
    const checkRecord = (field, rec, where) => {
      if (!rec || typeof rec !== "object") return;
      if (rec.unit !== undefined && specUnit.has(field)) {
        assert.equal(rec.unit, specUnit.get(field), `unit mismatch ${where}.${field}`);
      }
      if (rec.status !== undefined) {
        assert.ok(STATUS_DOMAIN.has(rec.status), `bad status ${rec.status} at ${where}.${field}`);
      }
    };
    for (const cell of payload.environment.cells) {
      for (const [field, rec] of Object.entries(cell.values || {})) checkRecord(field, rec, `cell ${cell.cell_id}`);
    }
    for (const [routeId, rec] of Object.entries(payload.environment.routes || {})) {
      for (const [field, val] of Object.entries(rec.exposure || {})) checkRecord(field, val, `route ${routeId}`);
      for (const level of Object.values(rec.risk || {})) {
        assert.ok(RISK_DOMAIN.has(level), `bad risk level ${level} at route ${routeId}`);
      }
      assert.ok(RISK_DOMAIN.has(rec.overall_risk), `bad overall_risk at route ${routeId}`);
    }
  });

  test(`[${label}] missing_rate per field <= 0.10`, { skip: skipEnv || false }, () => {
    const mr = payload.environment.missing_rate;
    assert.ok(mr && typeof mr === "object", "missing_rate present");
    for (const [field, rate] of Object.entries(mr)) {
      assert.ok(typeof rate === "number" && rate <= 0.10, `missing_rate ${field} = ${rate}`);
    }
  });

  test(`[${label}] no NaN/Infinity numbers in serialised payload`, { skip: payloadReason || false }, () => {
    for (const { path, value } of walkValues(payload)) {
      if (typeof value === "number") {
        assert.ok(Number.isFinite(value), `non-finite number at ${path}`);
      }
      assert.notEqual(value, undefined, `undefined at ${path}`);
    }
    const raw = readFileSync(target.payloadPath, "utf8");
    assert.ok(!/\bNaN\b/.test(raw), "raw JSON contains NaN token");
    assert.ok(!/\bInfinity\b/.test(raw), "raw JSON contains Infinity token");
  });

  test(`[${label}] no absolute user paths leak into payload strings`, { skip: payloadReason || false }, () => {
    for (const { path, value } of walkValues(payload)) {
      if (typeof value === "string") {
        assert.ok(!value.includes("D:\\"), `absolute path D:\\ at ${path}`);
        assert.ok(!value.includes("C:\\Users"), `absolute path C:\\Users at ${path}`);
      }
    }
  });

  test(`[${label}] index.html/css reference no external script/style/img/font/tile resource`, { skip: html ? false : "index.html not built yet" }, () => {
    const external = (u) => /^(https?:)?\/\//.test(u.trim());
    const scriptSrcs = [...html.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)].map((m) => m[1]);
    const linkHrefs = [...html.matchAll(/<link[^>]+href=["']([^"']+)["']/gi)].map((m) => m[1]);
    const imgSrcs = [...html.matchAll(/<img[^>]+src=["']([^"']+)["']/gi)].map((m) => m[1]);
    for (const u of [...scriptSrcs, ...linkHrefs, ...imgSrcs]) {
      assert.ok(!external(u), `external resource in index.html: ${u}`);
    }
    assert.ok(!/@import\s+url\(\s*["']?https?:/i.test(html), "@import external in html");
    if (css) {
      assert.ok(!/@import/i.test(css), "@import present in styles.css");
      const urls = [...css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/gi)].map((m) => m[1]);
      for (const u of urls) assert.ok(!external(u), `external url() in styles.css: ${u}`);
    }
  });

  test(`[${label}] js avoids innerHTML/eval/document.write`, { skip: target.jsPaths.every((p) => existsSync(p)) ? false : "js not built yet" }, () => {
    for (const jsPath of target.jsPaths) {
      const code = readFileSync(jsPath, "utf8");
      assert.ok(!code.includes(".innerHTML"), `.innerHTML used in ${jsPath}`);
      assert.ok(!/\beval\s*\(/.test(code), `eval used in ${jsPath}`);
      assert.ok(!code.includes("document.write"), `document.write used in ${jsPath}`);
    }
  });
}

// ---------- research harness adapter (single copy under publish/) ----------
const harnessPath = join(runRoot, "publish", "research_harness_latest.json");
const { data: harness, reason: harnessReason } = readJsonIfExists(harnessPath);

test("research_harness_latest.json exists and parses", { skip: harnessReason || false }, () => {
  assert.ok(harness && typeof harness === "object");
});

for (const key of ["run_id", "generated_at", "status", "research_question", "hypothesis"]) {
  test(`research_harness_latest.json has non-empty ${key}`, { skip: harnessReason || false }, () => {
    const value = harness[key];
    assert.equal(typeof value, "string", `${key} must be a string`);
    assert.ok(value.trim().length > 0, `${key} must be non-empty`);
  });
}

test("research_harness_latest.json declares offline qoder_session provenance", { skip: harnessReason || false }, () => {
  assert.equal(harness.provider, "qoder_session");
  assert.equal(harness.model_name, "qwen3.8-max");
  assert.equal(harness.dashscope_api_used, false);
  assert.ok(["completed", "partial"].includes(harness.status));
});
