import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_RECOMMENDATION_API_BASE_URL,
  DEFAULT_RECOMMENDATION_INTENT_TIMEOUT_MS,
  DEFAULT_RECOMMENDATION_TIMEOUT_MS,
  RecommendationApiError,
  createRecommendationApi,
  toRecommendationIntentPayload,
  toRecommendationPayload,
} from "../web/src/recommendation-api.js";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    },
  };
}

test("默认连接 8124 端口下的 v1 接口", async () => {
  const calls = [];
  const api = createRecommendationApi({
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return jsonResponse({ status: "ok" });
    },
  });

  await api.health();
  await api.questionnaire();

  assert.equal(DEFAULT_RECOMMENDATION_API_BASE_URL, "http://127.0.0.1:8124/api/v1");
  assert.equal(DEFAULT_RECOMMENDATION_TIMEOUT_MS, 35000);
  assert.deepEqual(calls.map((call) => call.url), [
    `${DEFAULT_RECOMMENDATION_API_BASE_URL}/health`,
    `${DEFAULT_RECOMMENDATION_API_BASE_URL}/questionnaire`,
  ]);
  assert.deepEqual(calls.map((call) => call.options.method), ["GET", "GET"]);
});

test("部署配置可覆盖推荐服务地址", async () => {
  globalThis.XUHUI_RECOMMENDATION_API_BASE_URL = "https://api.example.com/api/v1/";
  try {
    const configuredModule = await import(
      "../web/src/recommendation-api.js?runtime-config-test"
    );
    assert.equal(
      configuredModule.DEFAULT_RECOMMENDATION_API_BASE_URL,
      "https://api.example.com/api/v1",
    );
  } finally {
    delete globalThis.XUHUI_RECOMMENDATION_API_BASE_URL;
  }
});

test("推荐请求严格排除性别与本地档案版本", async () => {
  let sentBody = null;
  const api = createRecommendationApi({
    fetchImpl: async (_url, options) => {
      sentBody = JSON.parse(options.body);
      return jsonResponse({ status: "ok", final_routes: [] });
    },
  });
  await api.recommend(profileFixture());

  assert.equal(sentBody.gender, undefined);
  assert.equal(sentBody.version, undefined);
  assert.equal(sentBody.route_mode, "walk");
  assert.deepEqual(sentBody.origin, { lng_gcj02: 121.44, lat_gcj02: 31.18 });
});

test("推荐载荷只保留 UserProfile 允许的字段", () => {
  const payload = toRecommendationPayload({
    ...profileFixture(),
    gender: "female",
    secret: "should-not-leave-browser",
  });
  assert.deepEqual(Object.keys(payload), [
    "route_mode",
    "target_time",
    "distance_min_m",
    "target_distance_m",
    "distance_max_m",
    "origin",
    "search_radius_m",
    "area_ids",
    "goal",
    "experience",
    "age_group",
    "sensitivities",
    "route_shape",
    "interests",
    "free_text",
  ]);
});

test("千问意图请求使用独立接口和较短超时", async () => {
  const calls = [];
  const api = createRecommendationApi({
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return jsonResponse({ reply: "已整理偏好。", ready: true, missing_fields: [], preference_patch: {} });
    },
  });

  await api.interpretIntent(intentFixture());

  assert.equal(DEFAULT_RECOMMENDATION_INTENT_TIMEOUT_MS, 15000);
  assert.equal(calls[0].url, `${DEFAULT_RECOMMENDATION_API_BASE_URL}/recommendation-intent`);
  assert.equal(calls[0].options.method, "POST");
});

test("千问意图载荷限制消息、历史并排除档案敏感字段", () => {
  const payload = toRecommendationIntentPayload({
    ...intentFixture(),
    history: Array.from({ length: 8 }, (_, index) => ({ role: index % 2 ? "assistant" : "user", content: `消息${index}` })),
    context: {
      ...intentFixture().context,
      profile: { version: 1, gender: "female", age_group: "18_39", experience: "regular", sensitivities: ["air"] },
      secret: "browser-only",
    },
  });

  assert.equal(payload.history.length, 6);
  assert.deepEqual(payload.context.profile, { experience: "regular", sensitivities: ["air"] });
  assert.equal(payload.context.secret, undefined);
  assert.equal(payload.context.profile.gender, undefined);
  assert.throws(
    () => toRecommendationIntentPayload({ ...intentFixture(), message: "长".repeat(501) }),
    (error) => error instanceof RecommendationApiError && error.code === "invalid_intent",
  );
});

test("422 与 503 统一映射为带状态和业务代码的错误", async () => {
  for (const [status, expectedCode] of [[422, "invalid_request"], [503, "service_unavailable"]]) {
    const api = createRecommendationApi({
      fetchImpl: async () => jsonResponse({
        error: { code: expectedCode, message: `failure-${status}`, details: { run_id: "r1" } },
      }, status),
    });

    await assert.rejects(
      api.recommend(profileFixture()),
      (error) => error instanceof RecommendationApiError
        && error.status === status
        && error.code === expectedCode
        && error.message === `failure-${status}`,
    );
  }
});

test("请求超时后中止连接并返回 timeout 错误", async () => {
  const api = createRecommendationApi({
    timeoutMs: 5,
    fetchImpl: (_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        reject(new DOMException("aborted", "AbortError"));
      });
    }),
  });

  await assert.rejects(
    api.health(),
    (error) => error instanceof RecommendationApiError && error.code === "timeout",
  );
});

function profileFixture() {
  return {
    version: 1,
    gender: "female",
    route_mode: "walk",
    target_time: "2026-08-28T10:00:00+08:00",
    distance_min_m: 700,
    target_distance_m: 1000,
    distance_max_m: 1500,
    origin: { lng_gcj02: 121.44, lat_gcj02: 31.18 },
    search_radius_m: 3000,
    area_ids: [],
    goal: "balanced",
    experience: "regular",
    age_group: "18_39",
    sensitivities: ["air"],
    route_shape: "any",
    interests: ["park"],
    free_text: "梧桐树多",
  };
}

function intentFixture() {
  return {
    message: "想跑 5 公里，安静一点，沿途有厕所",
    history: [],
    context: {
      location: { label: "上海交通大学徐汇校区", lng_gcj02: 121.433, lat_gcj02: 31.2 },
      route_mode: "run",
      profile: { experience: "regular", sensitivities: ["air"] },
      preferences: { interests: ["quiet", "toilet"] },
    },
  };
}
