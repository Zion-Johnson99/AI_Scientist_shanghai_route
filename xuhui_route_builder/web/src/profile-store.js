export const HEALTH_PROFILE_STORAGE_KEY = "xuhui.healthProfile.v1";

export const DEFAULT_HEALTH_PROFILE = Object.freeze({
  version: 1,
  age_group: "undisclosed",
  gender: "undisclosed",
  experience: "regular",
  sensitivities: Object.freeze([]),
});

const AGE_GROUPS = new Set(["under_18", "18_39", "40_59", "60_plus", "undisclosed"]);
const GENDERS = new Set(["male", "female", "undisclosed"]);
const EXPERIENCE_LEVELS = new Set(["beginner", "regular", "frequent"]);
const SENSITIVITIES = new Set(["air", "pollen", "heat", "noise"]);

export function loadHealthProfile(storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem?.(HEALTH_PROFILE_STORAGE_KEY);
    if (!raw) {
      return defaultProfile();
    }
    return normalizeHealthProfile(JSON.parse(raw));
  } catch {
    return defaultProfile();
  }
}

export function saveHealthProfile(profile, storage = globalThis.localStorage) {
  const normalized = normalizeHealthProfile(profile);
  try {
    storage?.setItem?.(HEALTH_PROFILE_STORAGE_KEY, JSON.stringify(normalized));
  } catch (error) {
    throw new Error("无法保存健康档案，请检查浏览器本地存储权限。", { cause: error });
  }
  return normalized;
}

export function clearHealthProfile(storage = globalThis.localStorage) {
  try {
    storage?.removeItem?.(HEALTH_PROFILE_STORAGE_KEY);
  } catch (error) {
    throw new Error("无法清除健康档案。", { cause: error });
  }
}

export function normalizeHealthProfile(value) {
  if (!isRecord(value)
    || value.version !== 1
    || !AGE_GROUPS.has(value.age_group)
    || !GENDERS.has(value.gender)
    || !EXPERIENCE_LEVELS.has(value.experience)
    || !Array.isArray(value.sensitivities)
    || value.sensitivities.some((item) => !SENSITIVITIES.has(item))) {
    return defaultProfile();
  }
  return {
    version: 1,
    age_group: value.age_group,
    gender: value.gender,
    experience: value.experience,
    sensitivities: [...new Set(value.sensitivities)],
  };
}

function defaultProfile() {
  return { ...DEFAULT_HEALTH_PROFILE, sensitivities: [] };
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
