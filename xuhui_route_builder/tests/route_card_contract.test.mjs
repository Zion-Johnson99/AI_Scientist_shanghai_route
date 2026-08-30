import assert from "node:assert/strict";
import test from "node:test";

import { createRouteCard, routeCardModel } from "../web/src/route-card.js";
import { ROUTE_MEDIA, routeMediaFor } from "../web/src/route-media.js";

const browseRoute = {
  route_id: "XH_WALK_0001",
  route_name: "西岸油罐艺术短线",
  route_mode: "walk",
  distance_m: 868,
  duration_min: 12,
};

test("共享模型统一运动方式、名称、时间、距离与 PM2.5 文案", () => {
  const model = routeCardModel(browseRoute, {
    environment: { pm25: { value: 10.24, status: "ok", unit: "µg/m³" } },
  });

  assert.equal(model.routeId, "XH_WALK_0001");
  assert.equal(model.routeName, "西岸油罐艺术短线");
  assert.equal(model.labelText, "步行");
  assert.equal(model.durationText, "12 分钟");
  assert.equal(model.distanceText, "0.9 km");
  assert.equal(model.pm25Text, "PM2.5 10.2 µg/m³");
  assert.equal(model.journeyText, "12 分钟 · 0.9 km · PM2.5 10.2 µg/m³");
});

test("推荐嵌套记录支持首选标签并保留选中状态", () => {
  const model = routeCardModel({
    final_rank: 1,
    route: {
      environment_summary: { pm2_5: { value: 12.4, status: "ok" } },
      route: { ...browseRoute, route_id: "route-1" },
    },
  }, { preferredLabel: "首选", selected: true });

  assert.equal(model.routeId, "route-1");
  assert.equal(model.labelText, "首选");
  assert.equal(model.pm25Text, "PM2.5 12.4 µg/m³");
  assert.equal(model.selected, true);
});

test("PM2.5 缺失和过期状态不展示伪精度", () => {
  assert.equal(routeCardModel(browseRoute).pm25Text, "PM2.5 暂无数据");
  assert.equal(routeCardModel(browseRoute, {
    environment: { pm2_5: { value: 18.6, status: "stale" } },
  }).pm25Text, "PM2.5 数据更新中");
});

test("媒体映射返回副本，未配置路线保持空媒体", () => {
  assert.deepEqual(routeMediaFor("UNKNOWN"), { cover: null, gallery: [] });
  assert.deepEqual(ROUTE_MEDIA, {});

  const mediaMap = {
    XH_WALK_0001: {
      cover: "/assets/routes/walk-1-cover.webp",
      gallery: ["/assets/routes/walk-1-a.webp", "", "/assets/routes/walk-1-b.webp"],
    },
  };
  const media = routeMediaFor("XH_WALK_0001", mediaMap);
  assert.deepEqual(media, {
    cover: "/assets/routes/walk-1-cover.webp",
    gallery: ["/assets/routes/walk-1-a.webp", "/assets/routes/walk-1-b.webp"],
  });
  media.gallery.push("changed");
  assert.equal(mediaMap.XH_WALK_0001.gallery.length, 3);
});

test("整张卡承担点击与键盘选择，不创建 radio", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const selected = [];
    const previewed = [];
    const card = createRouteCard(routeCardModel(browseRoute, {
      selected: true,
      environment: { pm2_5: { value: 10.2, status: "ok" } },
    }), {
      onSelect: (routeId) => selected.push(routeId),
      onPreview: (routeId) => previewed.push(routeId),
    });

    assert.equal(card.dataset.routeId, "XH_WALK_0001");
    assert.equal(card.attributes.role, "button");
    assert.equal(card.attributes.tabindex, "0");
    assert.equal(card.attributes["aria-current"], "true");
    assert.equal(findByAttribute(card, "role", "radio"), null);
    assert.match(card.textContent, /12 分钟 · 0.9 km · PM2.5 10.2 µg\/m³/);

    card.dispatch("click", {});
    card.dispatch("keydown", keyEvent("Enter"));
    card.dispatch("keydown", keyEvent(" "));
    card.dispatch("keydown", keyEvent("Escape"));
    assert.deepEqual(selected, ["XH_WALK_0001", "XH_WALK_0001", "XH_WALK_0001"]);

    card.dispatch("mouseenter", {});
    card.dispatch("mouseleave", {});
    assert.deepEqual(previewed, ["XH_WALK_0001", null]);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("有封面时渲染图片，缺图时收起媒体区并标记纯文字卡", () => {
  const previousDocument = globalThis.document;
  globalThis.document = createDocumentStub();
  try {
    const textOnlyCard = createRouteCard(routeCardModel(browseRoute));
    assert.ok(findByClass(textOnlyCard, "route-card--text-only"));
    assert.equal(findByClass(textOnlyCard, "route-card__media"), null);
    assert.equal(findByClass(textOnlyCard, "route-card__placeholder"), null);
    assert.equal(findByTag(textOnlyCard, "IMG"), null);

    const imageCard = createRouteCard(routeCardModel(browseRoute, {
      mediaMap: { XH_WALK_0001: { cover: "/route.webp", gallery: [] } },
    }));
    assert.equal(findByClass(imageCard, "route-card--text-only"), null);
    assert.ok(findByClass(imageCard, "route-card__media"));
    const image = findByTag(imageCard, "IMG");
    assert.equal(image.attributes.src, "/route.webp");
    assert.equal(image.attributes.alt, "西岸油罐艺术短线");
  } finally {
    globalThis.document = previousDocument;
  }
});

function keyEvent(key) {
  return {
    key,
    prevented: false,
    preventDefault() { this.prevented = true; },
  };
}

function createDocumentStub() {
  return {
    createElement(tagName) {
      return new NodeStub(tagName);
    },
  };
}

class NodeStub {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.listeners = {};
    this._text = "";
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent || "").join("");
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  append(...children) {
    this.children.push(...children);
  }

  addEventListener(type, handler) {
    this.listeners[type] ||= [];
    this.listeners[type].push(handler);
  }

  dispatch(type, event) {
    for (const handler of this.listeners[type] || []) handler(event);
  }
}

function findByAttribute(node, name, value) {
  if (node?.attributes?.[name] === value) return node;
  for (const child of node?.children || []) {
    const match = findByAttribute(child, name, value);
    if (match) return match;
  }
  return null;
}

function findByClass(node, className) {
  if (String(node?.className || "").split(/\s+/).includes(className)) return node;
  for (const child of node?.children || []) {
    const match = findByClass(child, className);
    if (match) return match;
  }
  return null;
}

function findByTag(node, tagName) {
  if (node?.tagName === tagName) return node;
  for (const child of node?.children || []) {
    const match = findByTag(child, tagName);
    if (match) return match;
  }
  return null;
}
