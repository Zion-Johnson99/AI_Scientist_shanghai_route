const DASHBOARD_PATH = "/environment_dashboard.json";
const DASHBOARD_KEY = "environment_dashboard.json";
const SCHEDULER_STATE_KEY = "_scheduler/environment-refresh.json";
const MAX_BODY_BYTES = 2 * 1024 * 1024;
const REGULAR_CRON = "0,15,30,45 * * * *";
const WATCHDOG_CRON = "3,18,33,48 * * * *";
const WATCHDOG_DELAY_MS = 3 * 60 * 1000;

const JSON_HEADERS = {
  "access-control-allow-origin": "*",
  "cache-control": "no-store",
  "content-type": "application/json; charset=utf-8",
};

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasValues(record) {
  return isObject(record) && isObject(record.values) && Object.keys(record.values).length > 0;
}

function hasFiniteValue(record, key) {
  return hasValues(record) && Number.isFinite(Number(record.values[key]));
}

function hasTextValue(record, key) {
  return hasValues(record) && String(record.values[key] ?? "").trim().length > 0;
}

function hasCompleteLifeIndex(record) {
  return hasTextValue(record, "value")
    && hasTextValue(record, "category")
    && hasTextValue(record, "text");
}

function validateDashboard(value) {
  if (!isObject(value)) return "root must be an object";
  if (!isObject(value.metadata)) return "metadata is required";
  if (typeof value.metadata.schema_version !== "string") return "metadata.schema_version is required";
  if (
    typeof value.metadata.generated_at !== "string" ||
    !Number.isFinite(Date.parse(value.metadata.generated_at))
  ) {
    return "metadata.generated_at must be a valid timestamp";
  }
  if (!isObject(value.current)) return "current is required";
  if (
    !hasFiniteValue(value.current.weather, "temperature_c")
    || !hasFiniteValue(value.current.weather, "relative_humidity_pct")
    || !hasTextValue(value.current.weather, "weather_text")
  ) {
    return "current.weather values are incomplete";
  }
  if (!hasFiniteValue(value.current.aqi, "aqi")) return "current.aqi.values.aqi is required";
  if (
    !Array.isArray(value.current.life_indices)
    || value.current.life_indices.length < 6
    || !value.current.life_indices.every(hasCompleteLifeIndex)
  ) {
    return "current.life_indices must contain at least 6 records";
  }
  if (!isObject(value.forecast)) return "forecast is required";
  if (
    !Array.isArray(value.forecast.weather_hourly)
    || value.forecast.weather_hourly.length < 24
    || !value.forecast.weather_hourly.every((record) => (
      hasFiniteValue(record, "temperature_c") && hasTextValue(record, "weather_text")
    ))
  ) {
    return "forecast.weather_hourly must contain complete records";
  }
  if (
    !Array.isArray(value.forecast.aqi_hourly)
    || value.forecast.aqi_hourly.length < 24
    || !value.forecast.aqi_hourly.every((record) => hasFiniteValue(record, "aqi"))
  ) {
    return "forecast.aqi_hourly must contain complete records";
  }
  if (
    !Array.isArray(value.forecast.life_indices_daily)
    || value.forecast.life_indices_daily.length < 6
    || !value.forecast.life_indices_daily.every(hasCompleteLifeIndex)
  ) {
    return "forecast.life_indices_daily must contain complete records";
  }
  if (!isObject(value.grids) || !Array.isArray(value.grids.items) || value.grids.items.length === 0) {
    return "grids.items must not be empty";
  }
  if (
    !isObject(value.routes)
    || !Array.isArray(value.routes.items)
    || value.routes.items.length < 90
    || !value.routes.items.every((route) => Number.isFinite(Number(route?.pm2_5?.value)))
  ) {
    return "routes.items must contain 90 PM2.5 values";
  }
  return null;
}

async function readJsonObject(bucket, key) {
  const object = await bucket.get(key);
  if (!object) return { object: null, value: null };
  try {
    return { object, value: JSON.parse(await object.text()) };
  } catch (error) {
    console.error(
      JSON.stringify({ level: "ERROR", event: "r2_json_parse_failed", key, message: error.message }),
    );
    return { object, value: null };
  }
}

function generatedAtOf(value) {
  const generatedAt = value?.metadata?.generated_at;
  return typeof generatedAt === "string" && Number.isFinite(Date.parse(generatedAt)) ? generatedAt : null;
}

async function getDashboard(env) {
  const object = await env.ENVIRONMENT_BUCKET.get(DASHBOARD_KEY);
  if (!object) return jsonResponse(404, { error: "environment dashboard not published" });
  return new Response(object.body, { status: 200, headers: JSON_HEADERS });
}

async function publishDashboard(request, env) {
  if (typeof env.ENVIRONMENT_PUBLISH_TOKEN !== "string" || env.ENVIRONMENT_PUBLISH_TOKEN.length === 0) {
    console.error(JSON.stringify({ level: "ERROR", event: "publish_token_missing" }));
    return jsonResponse(503, { error: "publisher is not configured" });
  }
  if (request.headers.get("authorization") !== `Bearer ${env.ENVIRONMENT_PUBLISH_TOKEN}`) {
    return jsonResponse(401, { error: "unauthorized" });
  }

  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { error: "payload too large" });
  }

  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > MAX_BODY_BYTES) return jsonResponse(413, { error: "payload too large" });

  let dashboard;
  try {
    dashboard = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return jsonResponse(400, { error: "invalid json" });
  }

  const validationError = validateDashboard(dashboard);
  if (validationError) return jsonResponse(422, { error: validationError });

  const current = await readJsonObject(env.ENVIRONMENT_BUCKET, DASHBOARD_KEY);
  const currentGeneratedAt = generatedAtOf(current.value);
  const incomingGeneratedAt = generatedAtOf(dashboard);
  if (
    currentGeneratedAt &&
    Date.parse(incomingGeneratedAt) <= Date.parse(currentGeneratedAt)
  ) {
    return jsonResponse(409, { error: "generated_at did not advance" });
  }

  const putOptions = {
    httpMetadata: { contentType: "application/json; charset=utf-8", cacheControl: "no-store" },
    customMetadata: { generatedAt: incomingGeneratedAt },
  };
  if (current.object?.httpEtag) {
    putOptions.onlyIf = new Headers({ "if-match": current.object.httpEtag });
  }

  try {
    const stored = await env.ENVIRONMENT_BUCKET.put(
      DASHBOARD_KEY,
      JSON.stringify(dashboard),
      putOptions,
    );
    if (stored === null) return jsonResponse(409, { error: "concurrent publish conflict" });
  } catch (error) {
    console.error(
      JSON.stringify({
        level: "ERROR",
        event: "dashboard_publish_failed",
        generatedAt: incomingGeneratedAt,
        message: error.message,
      }),
    );
    return jsonResponse(503, { error: "storage unavailable" });
  }

  console.info(
    JSON.stringify({ level: "INFO", event: "dashboard_published", generatedAt: incomingGeneratedAt }),
  );
  return new Response(null, { status: 204, headers: JSON_HEADERS });
}

async function dispatchWorkflow(env, reason) {
  if (typeof env.GITHUB_TOKEN !== "string" || env.GITHUB_TOKEN.length === 0) {
    throw new Error("GITHUB_TOKEN is not configured");
  }
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "content-type": "application/json",
      "user-agent": "xuhui-environment-scheduler",
      "x-github-api-version": "2022-11-28",
    },
    body: JSON.stringify({
      ref: env.GITHUB_REF,
      inputs: { tier: "weather", deploy_pages: false },
    }),
  });
  if (!response.ok) {
    throw new Error(`GitHub workflow dispatch failed with status ${response.status}`);
  }
  console.info(JSON.stringify({ level: "INFO", event: "workflow_dispatched", reason }));
}

async function hasActiveWorkflowRun(env) {
  const url = new URL(
    `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/runs`,
  );
  url.searchParams.set("branch", env.GITHUB_REF);
  url.searchParams.set("event", "workflow_dispatch");
  url.searchParams.set("per_page", "20");
  const response = await fetch(url.toString(), {
    method: "GET",
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "user-agent": "xuhui-environment-scheduler",
      "x-github-api-version": "2022-11-28",
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub workflow runs query failed with status ${response.status}`);
  }
  const payload = await response.json();
  const runs = Array.isArray(payload.workflow_runs) ? payload.workflow_runs : [];
  return runs.some((run) => run?.status === "queued" || run?.status === "in_progress");
}

async function handleRegularSchedule(controller, env) {
  const { value } = await readJsonObject(env.ENVIRONMENT_BUCKET, DASHBOARD_KEY);
  const state = {
    scheduledAt: new Date(controller.scheduledTime).toISOString(),
    generatedAt: generatedAtOf(value),
  };
  try {
    await env.ENVIRONMENT_BUCKET.put(SCHEDULER_STATE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn(
      JSON.stringify({ level: "WARN", event: "scheduler_state_write_failed", message: error.message }),
    );
  }
  await dispatchWorkflow(env, "quarter-hour");
}

async function handleWatchdogSchedule(controller, env) {
  const { value: state } = await readJsonObject(env.ENVIRONMENT_BUCKET, SCHEDULER_STATE_KEY);
  const expectedRegularTime = new Date(controller.scheduledTime - WATCHDOG_DELAY_MS).toISOString();
  if (!isObject(state) || state.scheduledAt !== expectedRegularTime) {
    console.warn(JSON.stringify({ level: "WARN", event: "watchdog_state_missing" }));
    return;
  }

  const { value: current } = await readJsonObject(env.ENVIRONMENT_BUCKET, DASHBOARD_KEY);
  if (generatedAtOf(current) !== state.generatedAt) return;
  if (await hasActiveWorkflowRun(env)) {
    console.info(JSON.stringify({ level: "INFO", event: "watchdog_active_run_found" }));
    return;
  }
  await dispatchWorkflow(env, "watchdog-no-progress");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== DASHBOARD_PATH) return jsonResponse(404, { error: "not found" });
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          ...JSON_HEADERS,
          "access-control-allow-headers": "authorization, content-type",
          "access-control-allow-methods": "GET, POST, OPTIONS",
        },
      });
    }
    if (request.method === "GET") return getDashboard(env);
    if (request.method === "POST") return publishDashboard(request, env);
    return jsonResponse(405, { error: "method not allowed" });
  },

  async scheduled(controller, env) {
    if (controller.cron === REGULAR_CRON) return handleRegularSchedule(controller, env);
    if (controller.cron === WATCHDOG_CRON) return handleWatchdogSchedule(controller, env);
    console.warn(JSON.stringify({ level: "WARN", event: "unknown_cron", cron: controller.cron }));
  },
};
