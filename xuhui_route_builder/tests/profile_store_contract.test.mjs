import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_HEALTH_PROFILE,
  HEALTH_PROFILE_STORAGE_KEY,
  clearHealthProfile,
  loadHealthProfile,
  saveHealthProfile,
} from "../web/src/profile-store.js";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

test("健康档案使用固定的版本化本地存储键", () => {
  assert.equal(HEALTH_PROFILE_STORAGE_KEY, "xuhui.healthProfile.v1");
  assert.equal(DEFAULT_HEALTH_PROFILE.version, 1);
});

test("保存并读取年龄、性别、经验与环境敏感项", () => {
  const storage = memoryStorage();
  const saved = saveHealthProfile({
    version: 1,
    age_group: "40_59",
    gender: "female",
    experience: "frequent",
    sensitivities: ["air", "pollen", "air"],
  }, storage);

  assert.deepEqual(saved, {
    version: 1,
    age_group: "40_59",
    gender: "female",
    experience: "frequent",
    sensitivities: ["air", "pollen"],
  });
  assert.deepEqual(loadHealthProfile(storage), saved);
});

test("损坏、过期或非法档案整体回退默认值", () => {
  const cases = [
    "{broken",
    JSON.stringify({ ...DEFAULT_HEALTH_PROFILE, version: 0 }),
    JSON.stringify({ ...DEFAULT_HEALTH_PROFILE, gender: "unknown-value" }),
    JSON.stringify({ ...DEFAULT_HEALTH_PROFILE, sensitivities: ["smoke"] }),
  ];

  for (const value of cases) {
    assert.deepEqual(
      loadHealthProfile(memoryStorage({ [HEALTH_PROFILE_STORAGE_KEY]: value })),
      DEFAULT_HEALTH_PROFILE,
    );
  }
});

test("清除档案后恢复默认值", () => {
  const storage = memoryStorage();
  saveHealthProfile({ ...DEFAULT_HEALTH_PROFILE, gender: "male" }, storage);
  clearHealthProfile(storage);
  assert.deepEqual(loadHealthProfile(storage), DEFAULT_HEALTH_PROFILE);
});

test("本地存储写入失败时给出明确错误", () => {
  const storage = {
    setItem() {
      throw new Error("denied");
    },
  };
  assert.throws(
    () => saveHealthProfile(DEFAULT_HEALTH_PROFILE, storage),
    /无法保存健康档案/,
  );
});
