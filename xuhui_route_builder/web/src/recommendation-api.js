export const DEFAULT_RECOMMENDATION_API_BASE_URL = "http://127.0.0.1:8124/api/v1";
export const DEFAULT_RECOMMENDATION_TIMEOUT_MS = 35000;

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
  };
}

export function toRecommendationPayload(profile) {
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
    throw new RecommendationApiError("推荐条件格式无效。", { code: "invalid_profile" });
  }
  return Object.fromEntries(USER_PROFILE_FIELDS.map((field) => [field, cloneField(profile[field])]));
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
