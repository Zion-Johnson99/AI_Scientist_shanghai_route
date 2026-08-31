import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_LOCATION,
  LOCATION_PLACEHOLDER,
  buildLocalLocationCandidates,
  createAmapLocationServices,
  createLocationController,
  createMapPointSelection,
  normalizeAmapPlaces,
  normalizeAmapTips,
  selectNearbyRoutes,
  shouldShowCurrentLocationOption,
} from "../web/src/location-control.js";

test("地点控制器默认从上海交通大学徐汇校区步行出发", () => {
  const controller = createLocationController();

  assert.deepEqual(DEFAULT_LOCATION, {
    label: "上海交通大学徐汇校区",
    lng_gcj02: 121.433095,
    lat_gcj02: 31.199005,
  });
  assert.equal(LOCATION_PLACEHOLDER, "搜索地点");
  assert.deepEqual(controller.getState(), {
    status: "idle",
    query: "",
    location: DEFAULT_LOCATION,
    mode: "walk",
    error: "",
  });
});

test("候选点击提交唯一地点并清空搜索词", () => {
  const committed = [];
  const controller = createLocationController({ onCommit: (location) => committed.push(location) });
  controller.setQuery("徐家汇");

  const location = controller.commitCandidate({
    name: "徐家汇公园",
    lng: 121.4382,
    lat: 31.1944,
  });

  assert.deepEqual(location, {
    label: "徐家汇公园",
    lng_gcj02: 121.4382,
    lat_gcj02: 31.1944,
  });
  assert.deepEqual(committed, [location]);
  assert.equal(controller.getState().query, "");
  assert.equal(controller.getState().status, "idle");
});

test("回车提交当前高亮候选且没有候选时不改变地点", () => {
  const controller = createLocationController();
  const candidates = [
    { label: "衡山公园", lng_gcj02: 121.446, lat_gcj02: 31.205 },
    { label: "徐汇滨江", lng_gcj02: 121.468, lat_gcj02: 31.177 },
  ];

  controller.setQuery("徐汇");
  assert.deepEqual(controller.commitActiveCandidate(candidates, 1), candidates[1]);
  assert.equal(controller.getState().query, "");

  const previous = controller.getState().location;
  assert.equal(controller.commitActiveCandidate([], 0), null);
  assert.deepEqual(controller.getState().location, previous);
});

test("设备定位成功复用提交流程，失败时保留已选地点", () => {
  const committed = [];
  const controller = createLocationController({ onCommit: (location) => committed.push(location) });

  controller.beginLocating();
  assert.equal(controller.getState().status, "locating");
  controller.commitGeolocation({ label: "当前位置", longitude: 121.44, latitude: 31.2 });
  assert.equal(controller.getState().status, "idle");
  assert.equal(committed.length, 1);

  const located = controller.getState().location;
  controller.beginLocating();
  const failureState = controller.failGeolocation(new Error("用户拒绝定位"));
  assert.equal(failureState.status, "idle");
  assert.equal(failureState.error, "用户拒绝定位");
  assert.deepEqual(failureState.location, located);
  assert.equal(committed.length, 1);
});

test("状态只在空闲、搜索和定位之间切换", () => {
  const controller = createLocationController();

  controller.setQuery("交通大学");
  assert.equal(controller.getState().status, "searching");
  controller.setQuery("   ");
  assert.equal(controller.getState().status, "idle");
  controller.beginLocating();
  assert.equal(controller.getState().status, "locating");
});

test("当前位置入口只在搜索词为空时显示", () => {
  assert.equal(shouldShowCurrentLocationOption(""), true);
  assert.equal(shouldShowCurrentLocationOption("   "), true);
  assert.equal(shouldShowCurrentLocationOption("龙华"), false);
});

test("缺失坐标的候选不会被误提交到零度坐标", () => {
  const controller = createLocationController();

  assert.throws(
    () => controller.commitCandidate({ label: "无效地点", lng_gcj02: null, lat_gcj02: null }),
    /缺少有效经纬度/,
  );
  assert.deepEqual(controller.getState().location, DEFAULT_LOCATION);
});

test("附近路线按步行、1.5至3公里和起点半径筛选，距离相同时保持输入顺序", () => {
  const origin = { lng_gcj02: 121.433, lat_gcj02: 31.2015 };
  const routes = [
    route("loop-a", 121.435, 31.2015, 2200, "strict_loop"),
    route("one-way", 121.434, 31.2015, 1600, "one_way"),
    route("too-short", 121.4332, 31.2015, 1499, "one_way"),
    route("run", 121.4331, 31.2015, 2000, "strict_loop", "run"),
    route("far", 121.50, 31.2015, 2200, "strict_loop"),
    route("tie-a", 121.436, 31.2015, 3000, "one_way"),
    route("tie-b", 121.436, 31.2015, 1500, "strict_loop"),
  ];

  assert.deepEqual(
    selectNearbyRoutes(routes, origin).map((route) => route.route_id),
    ["one-way", "loop-a", "tie-a"],
  );
});

test("附近路线筛选同时接受 GeoJSON 要素并支持自定义半径", () => {
  const origin = { lng_gcj02: 121.433, lat_gcj02: 31.2015 };
  const near = feature("near", 121.434, 31.2015, 2000);
  const outside = feature("outside", 121.45, 31.2015, 2500);

  assert.deepEqual(selectNearbyRoutes([near, outside], origin, { search_radius_m: 500 }), [near]);
});

test("高德联想候选只保留带唯一坐标的地点", () => {
  const tips = normalizeAmapTips([
    {
      id: "poi-1",
      name: "上海交通大学徐汇校区",
      district: "上海市徐汇区",
      address: "华山路1954号",
      location: { getLng: () => 121.433, getLat: () => 31.2015 },
    },
    { id: "city-only", name: "徐汇区", location: null },
  ]);

  assert.deepEqual(tips, [{
    id: "poi-1",
    label: "上海交通大学徐汇校区",
    address: "上海市徐汇区 华山路1954号",
    lng_gcj02: 121.433,
    lat_gcj02: 31.2015,
  }]);
});

test("高德 POI 搜索保留名称、行政区和坐标", () => {
  const places = normalizeAmapPlaces([
    {
      id: "B00155AMEJ",
      name: "龙华寺",
      cityname: "上海市",
      adname: "徐汇区",
      address: "龙华路2853号",
      location: { lng: 121.451842, lat: 31.175174 },
    },
  ]);

  assert.deepEqual(places, [{
    id: "B00155AMEJ",
    label: "龙华寺",
    address: "上海市 徐汇区 龙华路2853号",
    lng_gcj02: 121.451842,
    lat_gcj02: 31.175174,
  }]);
});

test("本地地点索引合并核心地标、路线入口和已核验 POI", () => {
  const candidates = buildLocalLocationCandidates(
    {
      features: [{
        properties: { entry_id: "entry-1", entry_name: "龙华寺广场", region_zone: "龙华" },
        geometry: { coordinates: [121.4536, 31.1728] },
      }],
    },
    {
      features: [{
        properties: { poi_id: "poi-1", poi_name: "上海龙华会店", poi_type: "coffee" },
        geometry: { coordinates: [121.453642, 31.174457] },
      }],
    },
  );

  assert.deepEqual(candidates.slice(0, 2).map((candidate) => candidate.label), [
    "上海交通大学徐汇校区",
    "龙华寺",
  ]);
  assert.deepEqual(candidates.slice(2).map((candidate) => candidate.label), [
    "龙华寺广场",
    "上海龙华会店",
  ]);
});

test("高德地点服务封装联想与设备定位，并显式暴露失败", async () => {
  class AutoComplete {
    search(query, callback) {
      assert.equal(query, "交大");
      callback("complete", { tips: [{ id: "1", name: "交大", location: { lng: 121.43, lat: 31.2 } }] });
    }
  }
  class Geolocation {
    getCurrentPosition(callback) {
      callback("complete", { position: { lng: 121.44, lat: 31.21 } });
    }
  }
  class PlaceSearch {
    search(_query, callback) {
      callback("complete", { poiList: { pois: [] } });
    }
  }
  const services = createAmapLocationServices({ AMap: { AutoComplete, PlaceSearch, Geolocation } });

  assert.equal((await services.suggest("交大"))[0].label, "交大");
  assert.deepEqual(await services.locate(), {
    label: "当前位置",
    lng_gcj02: 121.44,
    lat_gcj02: 31.21,
  });

  const failed = createAmapLocationServices({
    AMap: {
      AutoComplete,
      PlaceSearch,
      Geolocation: class {
        getCurrentPosition(callback) {
          callback("error", { message: "用户拒绝定位" });
        }
      },
    },
  });
  await assert.rejects(() => failed.locate(), /用户拒绝定位/);
});

test("高德联想额度耗尽时由 POI 搜索返回丰富候选", async () => {
  class AutoComplete {
    search(_query, callback) {
      callback("error", "USER_DAILY_QUERY_OVER_LIMIT");
    }
  }
  class Geolocation {}
  class PlaceSearch {
    search(query, callback) {
      assert.equal(query, "龙华");
      callback("complete", {
        poiList: {
          pois: [
            { id: "temple", name: "龙华寺", address: "龙华路2853号", location: { lng: 121.451842, lat: 31.175174 } },
            { id: "metro", name: "龙华(地铁站)", address: "11号线;12号线", location: { lng: 121.452958, lat: 31.172672 } },
          ],
        },
      });
    }
  }
  const services = createAmapLocationServices({ AMap: { AutoComplete, PlaceSearch, Geolocation } });

  assert.deepEqual((await services.suggest("龙华")).map((candidate) => candidate.label), [
    "龙华寺",
    "龙华(地铁站)",
  ]);
});

test("高德联想与 POI 额度同时耗尽时使用本地已核验地点", async () => {
  class QuotaLimitedSearch {
    search(_query, callback) {
      callback("error", "USER_DAILY_QUERY_OVER_LIMIT");
    }
  }
  class Geolocation {}
  const services = createAmapLocationServices(
    {
      AMap: {
        AutoComplete: QuotaLimitedSearch,
        PlaceSearch: QuotaLimitedSearch,
        Geolocation,
      },
    },
    {
      localCandidates: [
        { id: "temple", label: "龙华寺", address: "徐汇区 龙华路2853号", lng_gcj02: 121.451842, lat_gcj02: 31.175174 },
        { id: "plaza", label: "龙华寺广场", address: "徐汇区 龙华", lng_gcj02: 121.4536, lat_gcj02: 31.1728 },
      ],
    },
  );

  assert.deepEqual((await services.suggest("龙华")).map((candidate) => candidate.label), [
    "龙华寺",
    "龙华寺广场",
  ]);
});

test("本地命中两个地点时直接返回且不等待在线服务", async () => {
  let onlineSearchCalls = 0;
  class SearchService {
    search(_query, callback) {
      onlineSearchCalls += 1;
      callback("error", "USER_DAILY_QUERY_OVER_LIMIT");
    }
  }
  const services = createAmapLocationServices(
    {
      AMap: {
        AutoComplete: SearchService,
        PlaceSearch: SearchService,
        Geolocation: class {},
      },
    },
    {
      localCandidates: [
        { id: "temple", label: "龙华寺", address: "徐汇区", lng_gcj02: 121.451842, lat_gcj02: 31.175174 },
        { id: "plaza", label: "龙华寺广场", address: "徐汇区", lng_gcj02: 121.4536, lat_gcj02: 31.1728 },
      ],
    },
  );

  assert.equal((await services.suggest("龙华")).length, 2);
  assert.equal(onlineSearchCalls, 0);
});

test("地图选点先预览，点击从这里出发后才提交", () => {
  const committed = [];
  const selection = createMapPointSelection({ onConfirm: (point) => committed.push(point) });
  const first = { label: "地图点", lng_gcj02: 121.44, lat_gcj02: 31.2 };
  const second = { label: "新的地图点", lng_gcj02: 121.45, lat_gcj02: 31.19 };

  selection.preview(first);
  assert.deepEqual(selection.getCandidate(), first);
  assert.deepEqual(committed, []);
  selection.preview(second);
  assert.deepEqual(selection.confirm(), second);
  assert.deepEqual(committed, [second]);
  assert.equal(selection.getCandidate(), null);

  selection.preview(first);
  selection.cancel();
  assert.equal(selection.confirm(), null);
  assert.deepEqual(committed, [second]);
});

function route(routeId, lng, lat, distanceM, routeShape, routeMode = "walk") {
  return {
    route_id: routeId,
    route_mode: routeMode,
    route_shape: routeShape,
    distance_m: distanceM,
    start_location: { lng_gcj02: lng, lat_gcj02: lat },
  };
}

function feature(routeId, lng, lat, distanceM) {
  return {
    type: "Feature",
    properties: {
      route_id: routeId,
      route_mode: "walk",
      route_shape: "one_way",
      actual_distance_m: distanceM,
    },
    geometry: {
      type: "LineString",
      coordinates: [[lng, lat], [lng + 0.001, lat]],
    },
  };
}
