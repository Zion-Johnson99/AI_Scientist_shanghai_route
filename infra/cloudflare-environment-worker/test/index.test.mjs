import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/index.js", import.meta.url);
const source = await readFile(sourceUrl, "utf8");
const worker = (await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`)).default;

const DASHBOARD_KEY = "environment_dashboard.json";

class MemoryR2 {
  constructor(initial = {}) {
    this.objects = new Map(Object.entries(initial));
    this.failPut = false;
  }

  async get(key) {
    if (!this.objects.has(key)) return null;
    const text = this.objects.get(key);
    return {
      body: text,
      async text() {
        return text;
      },
    };
  }

  async put(key, value) {
    if (this.failPut) throw new Error("R2 write failed");
    const text = typeof value === "string" ? value : new TextDecoder().decode(value);
    this.objects.set(key, text);
  }
}

function dashboard(generatedAt = "2026-09-01T06:00:00.000Z") {
  const records = (count, values) => Array.from({ length: count }, () => ({ status: "ok", values }));
  return {
    metadata: { schema_version: "1.0", generated_at: generatedAt },
    current: {
      weather: {
        status: "ok",
        values: { temperature_c: 30, relative_humidity_pct: 60, weather_text: "晴" },
      },
      aqi: { status: "ok", values: { aqi: 25 } },
      life_indices: records(6, { value: "1", category: "适宜", text: "适宜户外活动" }),
    },
    forecast: {
      weather_hourly: records(24, { temperature_c: 30, weather_text: "晴" }),
      aqi_hourly: records(24, { aqi: 25 }),
      life_indices_daily: records(6, {
        value: "1",
        category: "适宜",
        text: "适宜户外活动",
      }),
    },
    grids: { items: [{ grid_id: "XH_PM25_G001" }] },
    routes: {
      items: Array.from({ length: 90 }, (_, index) => ({
        route_id: `XH_WALK_${String(index + 1).padStart(4, "0")}`,
        pm2_5: { status: "ok", value: 12.4 },
      })),
    },
  };
}

function request(method, body, token = "publish-secret") {
  const headers = {};
  if (token) headers.authorization = `Bearer ${token}`;
  return new Request(`https://environment.example/${DASHBOARD_KEY}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function env(bucket) {
  return {
    ENVIRONMENT_BUCKET: bucket,
    ENVIRONMENT_PUBLISH_TOKEN: "publish-secret",
    GITHUB_TOKEN: "github-secret",
    GITHUB_OWNER: "Zion-Johnson99",
    GITHUB_REPO: "AI_Scientist_shanghai_route",
    GITHUB_WORKFLOW: "environment-refresh.yml",
    GITHUB_REF: "main",
  };
}

test("GET 返回 R2 中最后成功数据并禁止缓存", async () => {
  const old = dashboard();
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: JSON.stringify(old) });

  const response = await worker.fetch(request("GET"), env(bucket));

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("access-control-allow-origin"), "*");
  assert.deepEqual(await response.json(), old);
});

test("POST 拒绝未认证和结构不完整数据，旧对象保持不变", async () => {
  const oldText = JSON.stringify(dashboard());
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: oldText });

  const unauthenticated = await worker.fetch(request("POST", dashboard(), null), env(bucket));
  assert.equal(unauthenticated.status, 401);

  const invalid = dashboard();
  invalid.forecast.weather_hourly = invalid.forecast.weather_hourly.slice(0, 23);
  const rejected = await worker.fetch(request("POST", invalid), env(bucket));
  assert.equal(rejected.status, 422);
  assert.equal(bucket.objects.get(DASHBOARD_KEY), oldText);
});

test("POST 拒绝条数完整但含空记录或缺路线 PM2.5 的数据", async () => {
  const oldText = JSON.stringify(dashboard());
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: oldText });

  const emptyForecastRecord = dashboard("2026-09-01T06:15:00.000Z");
  emptyForecastRecord.forecast.aqi_hourly[7].values = {};
  const emptyResponse = await worker.fetch(request("POST", emptyForecastRecord), env(bucket));
  assert.equal(emptyResponse.status, 422);
  assert.equal(bucket.objects.get(DASHBOARD_KEY), oldText);

  const missingRoutePm25 = dashboard("2026-09-01T06:15:00.000Z");
  delete missingRoutePm25.routes.items[12].pm2_5;
  const routeResponse = await worker.fetch(request("POST", missingRoutePm25), env(bucket));
  assert.equal(routeResponse.status, 422);
  assert.equal(bucket.objects.get(DASHBOARD_KEY), oldText);
});

test("发布密钥未配置时拒绝写入", async () => {
  const oldText = JSON.stringify(dashboard());
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: oldText });
  const missingSecretEnv = env(bucket);
  delete missingSecretEnv.ENVIRONMENT_PUBLISH_TOKEN;

  const response = await worker.fetch(request("POST", dashboard(), "undefined"), missingSecretEnv);

  assert.equal(response.status, 503);
  assert.equal(bucket.objects.get(DASHBOARD_KEY), oldText);
});

test("POST 仅在验证和 R2 写入成功后替换对象", async () => {
  const oldText = JSON.stringify(dashboard());
  const next = dashboard("2026-09-01T06:15:00.000Z");
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: oldText });

  bucket.failPut = true;
  const failed = await worker.fetch(request("POST", next), env(bucket));
  assert.equal(failed.status, 503);
  assert.equal(bucket.objects.get(DASHBOARD_KEY), oldText);

  bucket.failPut = false;
  const accepted = await worker.fetch(request("POST", next), env(bucket));
  assert.equal(accepted.status, 204);
  assert.deepEqual(JSON.parse(bucket.objects.get(DASHBOARD_KEY)), next);
});

test("当前项目环境看板满足线上原子发布闸门", async () => {
  const actualPath = new URL(
    "../../../xuhui_route_builder/data/web/environment_dashboard.json",
    import.meta.url,
  );
  const actual = JSON.parse(await readFile(actualPath, "utf8"));
  const bucket = new MemoryR2();

  const response = await worker.fetch(request("POST", actual), env(bucket));

  assert.equal(response.status, 204);
  assert.equal(bucket.objects.has(DASHBOARD_KEY), true);
});

test("正文超过限制时拒绝写入", async () => {
  const oldText = JSON.stringify(dashboard());
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: oldText });
  const oversized = "x".repeat(2 * 1024 * 1024 + 1);
  const response = await worker.fetch(
    new Request(`https://environment.example/${DASHBOARD_KEY}`, {
      method: "POST",
      headers: { authorization: "Bearer publish-secret" },
      body: oversized,
    }),
    env(bucket),
  );

  assert.equal(response.status, 413);
  assert.equal(bucket.objects.get(DASHBOARD_KEY), oldText);
});

test("常规定时刷新后数据已推进时 watchdog 不重复触发", async (t) => {
  const initial = dashboard();
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: JSON.stringify(initial) });
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(null, { status: 204 });
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  await worker.scheduled(
    { cron: "0,15,30,45 * * * *", scheduledTime: Date.parse("2026-09-01T06:15:00.000Z") },
    env(bucket),
  );
  bucket.objects.set(DASHBOARD_KEY, JSON.stringify(dashboard("2026-09-01T06:16:00.000Z")));
  await worker.scheduled(
    { cron: "3,18,33,48 * * * *", scheduledTime: Date.parse("2026-09-01T06:18:00.000Z") },
    env(bucket),
  );

  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /actions\/workflows\/environment-refresh\.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    ref: "main",
    inputs: { tier: "weather", deploy_pages: false },
  });
});

test("常规定时刷新后三分钟数据未推进时 watchdog 补触发", async (t) => {
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: JSON.stringify(dashboard()) });
  let dispatches = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    if (options.method === "GET") {
      return Response.json({ workflow_runs: [] });
    }
    dispatches += 1;
    return new Response(null, { status: 204 });
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  await worker.scheduled(
    { cron: "0,15,30,45 * * * *", scheduledTime: Date.parse("2026-09-01T06:30:00.000Z") },
    env(bucket),
  );
  await worker.scheduled(
    { cron: "3,18,33,48 * * * *", scheduledTime: Date.parse("2026-09-01T06:33:00.000Z") },
    env(bucket),
  );

  assert.equal(dispatches, 2);
});

test("watchdog 发现活动中的工作流时不重复触发", async (t) => {
  const bucket = new MemoryR2({ [DASHBOARD_KEY]: JSON.stringify(dashboard()) });
  let dispatches = 0;
  let runQueries = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    if (options.method === "GET") {
      runQueries += 1;
      return Response.json({ workflow_runs: [{ status: "queued" }] });
    }
    dispatches += 1;
    return new Response(null, { status: 204 });
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  await worker.scheduled(
    { cron: "0,15,30,45 * * * *", scheduledTime: Date.parse("2026-09-01T06:45:00.000Z") },
    env(bucket),
  );
  await worker.scheduled(
    { cron: "3,18,33,48 * * * *", scheduledTime: Date.parse("2026-09-01T06:48:00.000Z") },
    env(bucket),
  );

  assert.equal(runQueries, 1);
  assert.equal(dispatches, 1);
});
