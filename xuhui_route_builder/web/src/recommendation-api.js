export const DEFAULT_RECOMMENDATION_API_BASE_URL = "http://127.0.0.1:8124/api/v1";
export const DEFAULT_RECOMMENDATION_TIMEOUT_MS = 35000;
export const DEFAULT_RECOMMENDATION_INTENT_TIMEOUT_MS = 15000;

const USER_PROFILE_FIELDS = [
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
];

export class RecommendationApiError extends Error {
  constructor(message, { status = 0, code = "request_failed", details = null, cause } = {}) {
    super(message, { cause });
    this.name = "RecommendationApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function createRecommendationApi({
  baseUrl = DEFAULT_RECOMMENDATION_API_BASE_URL,
  fetchImpl = globalThis.fetch,
  timeoutMs = DEFAULT_RECOMMENDATION_TIMEOUT_MS,
  intentTimeoutMs = DEFAULT_RECOMMENDATION_INTENT_TIMEOUT_MS,
} = {}) {
  if (typeof fetchImpl !== "function") {
    throw new Error("当前环境缺少 fetch，无法连接推荐服务。");
  }
  const normalizedBaseUrl = String(baseUrl).replace(/\/$/, "");

  return {
    health: () => requestJson(fetchImpl, `${normalizedBaseUrl}/health`, { method: "GET" }, timeoutMs),
    questionnaire: () => requestJson(
      fetchImpl,
      `${normalizedBaseUrl}/questionnaire`,
      { method: "GET" },
      timeoutMs,
    ),
    recommend: (profile) => requestJson(fetchImpl, `${normalizedBaseUrl}/recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toRecommendationPayload(profile)),
    }, timeoutMs),
    interpretIntent: (request) => requestJson(fetchImpl, `${normalizedBaseUrl}/recommendation-intent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toRecommendationIntentPayload(request)),
    }, intentTimeoutMs),
  };
}

export function toRecommendationPayload(profile) {
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
    throw new RecommendationApiError("推荐条件格式无效。", { code: "invalid_profile" });
  }
  return Object.fromEntries(USER_PROFILE_FIELDS.map((field) => [field, cloneField(profile[field])]));
}

export function toRecommendationIntentPayload(request) {
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw invalidIntent("千问请求格式无效。");
  }
  const message = String(request.message || "").trim();
  if (!message || message.length > 500) {
    throw invalidIntent("请将需求控制在 500 字以内。");
  }
  const history = Array.isArray(request.history)
    ? request.history.slice(-6).map(normalizeHistoryMessage)
    : [];
  const context = request.context && typeof request.context === "object" && !Array.isArray(request.context)
    ? request.context
    : {};
  const profile = context.profile && typeof context.profile === "object" && !Array.isArray(context.profile)
    ? context.profile
    : {};
  return {
    message,
    history,
    context: {
      location: cloneLocation(context.location),
      route_mode: String(context.route_mode || ""),
      profile: {
        experience: String(profile.experience || "regular"),
        sensitivities: Array.isArray(profile.sensitivities) ? [...profile.sensitivities] : [],
      },
      preferences: context.preferences && typeof context.preferences === "object" && !Array.isArray(context.preferences)
        ? { ...context.preferences }
        : {},
    },
  };
}

async function requestJson(fetchImpl, url, options, timeoutMs) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), positiveTimeout(timeoutMs));
  try {
    const response = await fetchImpl(url, { ...options, signal: controller.signal });
    const body = await parseJson(response);
    if (!response.ok) {
      throw responseError(response.status, body);
    }
    return body;
  } catch (error) {
    if (error instanceof RecommendationApiError) {
      throw error;
    }
    if (controller.signal.aborted || error?.name === "AbortError") {
      throw new RecommendationApiError("推荐服务响应超时，请稍后重试。", {
        code: "timeout",
        cause: error,
      });
    }
    throw new RecommendationApiError("无法连接推荐服务，请确认本地服务已启动。", {
      code: "network_error",
      cause: error,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

async function parseJson(response) {
  try {
    return await response.json();
  } catch (error) {
    throw new RecommendationApiError("推荐服务返回了无效数据。", {
      status: Number(response?.status || 0),
      code: "invalid_response",
      cause: error,
    });
  }
}

function responseError(status, body) {
  const errorBody = body?.error || {};
  const detail = body?.detail;
  const fallback = status === 422
    ? "推荐条件未通过校验。"
    : status === 503
      ? "推荐服务暂时不可用。"
      : "推荐请求失败。";
  return new RecommendationApiError(
    String(errorBody.message || (typeof detail === "string" ? detail : fallback)),
    {
      status,
      code: String(errorBody.code || (status === 422 ? "invalid_request" : status === 503 ? "service_unavailable" : "http_error")),
      details: errorBody.details || (Array.isArray(detail) ? detail : null),
    },
  );
}

function positiveTimeout(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_RECOMMENDATION_TIMEOUT_MS;
}

function cloneField(value) {
  if (Array.isArray(value)) {
    return [...value];
  }
  if (value && typeof value === "object") {
    return { ...value };
  }
  return value;
}

function normalizeHistoryMessage(item) {
  const role = item?.role === "assistant" ? "assistant" : item?.role === "user" ? "user" : null;
  const content = String(item?.content || "").trim();
  if (!role || !content || content.length > 500) {
    throw invalidIntent("千问对话历史格式无效。");
  }
  return { role, content };
}

function cloneLocation(location) {
  if (!location || typeof location !== "object" || Array.isArray(location)) return null;
  const lng = Number(location.lng_gcj02);
  const lat = Number(location.lat_gcj02);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  return {
    label: String(location.label || "当前位置"),
    lng_gcj02: lng,
    lat_gcj02: lat,
  };
}

function invalidIntent(message) {
  return new RecommendationApiError(message, { code: "invalid_intent" });
}
