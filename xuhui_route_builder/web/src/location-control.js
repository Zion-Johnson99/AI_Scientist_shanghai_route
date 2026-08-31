export const DEFAULT_LOCATION = Object.freeze({
  label: "上海交通大学徐汇校区",
  lng_gcj02: 121.433095,
  lat_gcj02: 31.199005,
});

const XUHUI_CORE_LANDMARKS = Object.freeze([
  Object.freeze({
    id: "xuhui:shanghai-jiao-tong-university",
    ...DEFAULT_LOCATION,
    address: "上海市 徐汇区 华山路1954号",
  }),
  Object.freeze({
    id: "amap:B00155AMEJ",
    label: "龙华寺",
    address: "上海市 徐汇区 龙华路2853号",
    lng_gcj02: 121.451842,
    lat_gcj02: 31.175174,
  }),
]);

export const LOCATION_PLACEHOLDER = "搜索地点";

const LOCATION_STATUSES = new Set(["idle", "searching", "locating"]);
const ROUTE_MODES = new Set(["walk", "run", "bike"]);
const MAX_LOCATION_SUGGESTIONS = 8;
const AUTOCOMPLETE_SUFFICIENT_COUNT = 6;
const LOCAL_SUGGESTION_SUFFICIENT_COUNT = 2;

export function shouldShowCurrentLocationOption(query) {
  return !String(query || "").trim();
}

export function normalizeAmapTips(tips) {
  return (Array.isArray(tips) ? tips : [])
    .map((tip) => {
      const location = tip?.location;
      const lng = firstFinite(location?.lng, location?.getLng?.());
      const lat = firstFinite(location?.lat, location?.getLat?.());
      if (lng === null || lat === null) return null;
      const district = String(tip?.district || "").trim();
      const address = String(tip?.address || "").trim();
      return {
        id: String(tip?.id || `${lng},${lat}`),
        label: String(tip?.name || "已选位置").trim() || "已选位置",
        address: [district, address].filter(Boolean).join(" "),
        lng_gcj02: lng,
        lat_gcj02: lat,
      };
    })
    .filter(Boolean);
}

export function normalizeAmapPlaces(places) {
  return (Array.isArray(places) ? places : [])
    .map((place) => {
      const location = place?.location;
      const lng = firstFinite(location?.lng, location?.getLng?.());
      const lat = firstFinite(location?.lat, location?.getLat?.());
      if (lng === null || lat === null) return null;
      const city = String(place?.cityname || "").trim();
      const district = String(place?.adname || "").trim();
      const address = String(place?.address || "").trim();
      return {
        id: String(place?.id || `${lng},${lat}`),
        label: String(place?.name || "已选位置").trim() || "已选位置",
        address: [city, district, address].filter(Boolean).join(" "),
        lng_gcj02: lng,
        lat_gcj02: lat,
      };
    })
    .filter(Boolean);
}

export function buildLocalLocationCandidates(entries, pois) {
  const features = [
    ...(Array.isArray(entries?.features) ? entries.features : []),
    ...(Array.isArray(pois?.features) ? pois.features : []),
  ];
  const featureCandidates = features.map((feature) => {
    const properties = feature?.properties || {};
    const coordinates = feature?.geometry?.coordinates || [];
    const lng = firstFinite(properties.lng_gcj02, coordinates[0]);
    const lat = firstFinite(properties.lat_gcj02, coordinates[1]);
    const label = String(properties.entry_name || properties.poi_name || "").trim();
    if (!label || lng === null || lat === null) return null;
    return {
      id: String(properties.entry_id || properties.poi_id || `${lng},${lat}`),
      label,
      address: ["上海市徐汇区", properties.region_zone].filter(Boolean).join(" "),
      lng_gcj02: lng,
      lat_gcj02: lat,
    };
  }).filter(Boolean);
  return mergeLocationCandidates(XUHUI_CORE_LANDMARKS, featureCandidates);
}

export function createAmapLocationServices(mapContext, { localCandidates = [] } = {}) {
  const AMap = mapContext?.AMap;
  if (!AMap?.AutoComplete || !AMap?.PlaceSearch || !AMap?.Geolocation) {
    throw new Error("高德地点联想、POI 搜索或定位插件未加载。");
  }
  const autocomplete = new AMap.AutoComplete({ city: "上海", citylimit: true });
  const placeSearch = new AMap.PlaceSearch({
    city: "上海",
    citylimit: true,
    pageSize: MAX_LOCATION_SUGGESTIONS,
    pageIndex: 1,
    extensions: "base",
  });
  const geolocation = new AMap.Geolocation({
    enableHighAccuracy: true,
    timeout: 10_000,
    showButton: false,
    showMarker: false,
    showCircle: false,
    panToLocation: false,
    zoomToAccuracy: false,
  });
  const geocoder = AMap.Geocoder ? new AMap.Geocoder({ city: "上海" }) : null;

  function geocodeSuggestion(keyword) {
    return new Promise((resolve, reject) => {
      geocoder.getLocation(keyword, (status, result) => {
        const geocode = result?.geocodes?.[0];
        const lng = firstFinite(geocode?.location?.lng, geocode?.location?.getLng?.());
        const lat = firstFinite(geocode?.location?.lat, geocode?.location?.getLat?.());
        if (status !== "complete" || lng === null || lat === null) {
          reject(new Error(String(result?.info || result || "地点搜索失败。")));
          return;
        }
        resolve([{
          id: `geocode:${lng},${lat}`,
          label: keyword,
          address: String(geocode.formattedAddress || keyword),
          lng_gcj02: lng,
          lat_gcj02: lat,
        }]);
      });
    });
  }

  function autocompleteSuggestions(keyword) {
    return new Promise((resolve, reject) => {
      autocomplete.search(keyword, (status, result) => {
        if (status === "complete") {
          resolve(normalizeAmapTips(result?.tips));
          return;
        }
        if (status === "no_data") {
          resolve([]);
          return;
        }
        reject(new Error(String(result?.info || result?.message || result || "地点联想搜索失败。")));
      });
    });
  }

  function placeSuggestions(keyword) {
    return new Promise((resolve, reject) => {
      placeSearch.search(keyword, (status, result) => {
        if (status === "complete") {
          resolve(normalizeAmapPlaces(result?.poiList?.pois));
          return;
        }
        if (status === "no_data") {
          resolve([]);
          return;
        }
        reject(new Error(String(result?.info || result?.message || result || "POI 搜索失败。")));
      });
    });
  }

  return {
    async suggest(query) {
      const keyword = String(query || "").trim();
      if (!keyword) return [];
      const localMatches = searchLocalLocationCandidates(localCandidates, keyword);
      if (localMatches.length >= LOCAL_SUGGESTION_SUFFICIENT_COUNT) {
        return localMatches.slice(0, MAX_LOCATION_SUGGESTIONS);
      }

      let autocompleteCandidates = [];
      let autocompleteError = null;
      try {
        autocompleteCandidates = await autocompleteSuggestions(keyword);
      } catch (error) {
        autocompleteError = error;
      }
      if (autocompleteCandidates.length >= AUTOCOMPLETE_SUFFICIENT_COUNT) {
        return mergeLocationCandidates(autocompleteCandidates, localMatches)
          .slice(0, MAX_LOCATION_SUGGESTIONS);
      }

      try {
        const placeCandidates = await placeSuggestions(keyword);
        const candidates = mergeLocationCandidates(autocompleteCandidates, placeCandidates, localMatches);
        if (candidates.length) return candidates.slice(0, MAX_LOCATION_SUGGESTIONS);
      } catch (error) {
        const candidates = mergeLocationCandidates(autocompleteCandidates, localMatches);
        if (candidates.length) {
          return candidates.slice(0, MAX_LOCATION_SUGGESTIONS);
        }
        autocompleteError = error;
      }

      if (geocoder) return geocodeSuggestion(keyword);
      if (autocompleteError) throw autocompleteError;
      return [];
    },
    locate() {
      return new Promise((resolve, reject) => {
        geolocation.getCurrentPosition((status, result) => {
          if (status !== "complete") {
            reject(new Error(String(result?.message || result?.info || "定位失败，请重试。")));
            return;
          }
          const source = result?.position || result?.coords || result;
          resolve(normalizeLocation({
            label: "当前位置",
            lng_gcj02: source?.lng ?? source?.longitude ?? source?.getLng?.(),
            lat_gcj02: source?.lat ?? source?.latitude ?? source?.getLat?.(),
          }));
        });
      });
    },
    reverse(point) {
      const location = normalizeLocation(point);
      if (!geocoder) return Promise.resolve(location);
      return new Promise((resolve) => {
        geocoder.getAddress([location.lng_gcj02, location.lat_gcj02], (status, result) => {
          const label = status === "complete"
            ? String(result?.regeocode?.formattedAddress || location.label)
            : location.label;
          resolve({ ...location, label });
        });
      });
    },
  };
}

function mergeLocationCandidates(...groups) {
  const candidates = [];
  const ids = new Set();
  const coordinates = new Set();
  groups.flat().forEach((candidate) => {
    const id = String(candidate?.id || "");
    const coordinate = `${Number(candidate?.lng_gcj02).toFixed(6)},${Number(candidate?.lat_gcj02).toFixed(6)}`;
    if ((id && ids.has(id)) || coordinates.has(coordinate)) return;
    if (id) ids.add(id);
    coordinates.add(coordinate);
    candidates.push(candidate);
  });
  return candidates;
}

function searchLocalLocationCandidates(candidates, keyword) {
  const query = String(keyword || "").trim().toLocaleLowerCase("zh-CN");
  if (!query) return [];
  return (Array.isArray(candidates) ? candidates : [])
    .map((candidate) => {
      const label = String(candidate?.label || "").toLocaleLowerCase("zh-CN");
      const address = String(candidate?.address || "").toLocaleLowerCase("zh-CN");
      let rank = Number.POSITIVE_INFINITY;
      if (label === query) rank = 0;
      else if (label.startsWith(query)) rank = 1;
      else if (label.includes(query)) rank = 2;
      else if (address.includes(query)) rank = 3;
      return { candidate, rank };
    })
    .filter(({ rank }) => Number.isFinite(rank))
    .sort((left, right) => left.rank - right.rank || left.candidate.label.length - right.candidate.label.length)
    .map(({ candidate }) => candidate);
}

export function createLocationController({
  initialLocation = DEFAULT_LOCATION,
  initialMode = "walk",
  onCommit = () => {},
} = {}) {
  let state = {
    status: "idle",
    query: "",
    location: normalizeLocation(initialLocation),
    mode: normalizeMode(initialMode),
    error: "",
  };

  function getState() {
    return { ...state };
  }

  function update(next) {
    state = { ...state, ...next };
    if (!LOCATION_STATUSES.has(state.status)) {
      throw new Error("地点控制器状态无效。");
    }
    return getState();
  }

  function setQuery(value) {
    const query = String(value ?? "");
    return update({
      query,
      status: query.trim() ? "searching" : "idle",
      error: "",
    });
  }

  function commitCandidate(candidate) {
    const location = normalizeLocation(candidate);
    update({
      status: "idle",
      query: "",
      location,
      error: "",
    });
    onCommit(location);
    return location;
  }

  function commitActiveCandidate(candidates, activeIndex = 0) {
    const candidate = Array.isArray(candidates) ? candidates[activeIndex] : null;
    return candidate ? commitCandidate(candidate) : null;
  }

  function beginLocating() {
    return update({ status: "locating", error: "" });
  }

  function commitGeolocation(position) {
    return commitCandidate(position?.coords || position);
  }

  function failGeolocation(error) {
    return update({
      status: "idle",
      error: errorMessage(error, "定位失败，请重试。"),
    });
  }

  function setMode(mode) {
    return update({ mode: normalizeMode(mode) });
  }

  return {
    getState,
    setQuery,
    commitCandidate,
    commitActiveCandidate,
    beginLocating,
    commitGeolocation,
    failGeolocation,
    setMode,
  };
}

export function createMapPointSelection({ onConfirm = () => {} } = {}) {
  let candidate = null;
  return {
    preview(point) {
      candidate = normalizeLocation(point);
      return candidate;
    },
    confirm() {
      if (!candidate) return null;
      const confirmed = candidate;
      candidate = null;
      onConfirm(confirmed);
      return confirmed;
    },
    cancel() {
      candidate = null;
    },
    getCandidate() {
      return candidate ? { ...candidate } : null;
    },
  };
}

export function selectNearbyRoutes(routes, origin, {
  mode = "walk",
  min_distance_m = 1500,
  max_distance_m = 3000,
  search_radius_m = 5000,
  limit = 3,
} = {}) {
  const normalizedOrigin = normalizeLocation(origin);
  const routeMode = normalizeMode(mode);
  const minimum = finiteNonNegative(min_distance_m, "路线最小长度");
  const maximum = finiteNonNegative(max_distance_m, "路线最大长度");
  const radius = finiteNonNegative(search_radius_m, "搜索半径");
  const resultLimit = Math.max(0, Math.floor(Number(limit) || 0));
  if (minimum > maximum) {
    throw new Error("路线最小长度不能大于最大长度。");
  }

  return (Array.isArray(routes) ? routes : [])
    .map((route, index) => ({
      route,
      index,
      properties: routeProperties(route),
      start: routeStart(route),
    }))
    .filter(({ properties, start }) => {
      const distance = routeDistance(properties);
      return properties.route_mode === routeMode
        && distance >= minimum
        && distance <= maximum
        && start !== null;
    })
    .map((candidate) => ({
      ...candidate,
      accessDistanceM: haversineDistanceM(normalizedOrigin, candidate.start),
    }))
    .filter(({ accessDistanceM }) => accessDistanceM <= radius)
    .sort((left, right) => left.accessDistanceM - right.accessDistanceM || left.index - right.index)
    .slice(0, resultLimit)
    .map(({ route }) => route);
}

function normalizeLocation(value) {
  const source = value?.location || value;
  const lng = firstFinite(
    source?.lng_gcj02,
    source?.lng,
    source?.longitude,
    source?.getLng?.(),
  );
  const lat = firstFinite(
    source?.lat_gcj02,
    source?.lat,
    source?.latitude,
    source?.getLat?.(),
  );
  if (lng === null || lat === null) {
    throw new Error("地点缺少有效经纬度。");
  }
  const label = String(value?.label || value?.name || "当前位置").trim();
  return {
    label: label || "当前位置",
    lng_gcj02: lng,
    lat_gcj02: lat,
  };
}

function normalizeMode(mode) {
  const normalized = String(mode || "");
  if (!ROUTE_MODES.has(normalized)) {
    throw new Error("运动方式无效。");
  }
  return normalized;
}

function routeProperties(route) {
  return route?.type === "Feature" ? route.properties || {} : route || {};
}

function routeDistance(properties) {
  return Number(properties.distance_m ?? properties.actual_distance_m);
}

function routeStart(route) {
  const properties = routeProperties(route);
  const location = properties.start_location;
  const startLng = firstFinite(location?.lng_gcj02);
  const startLat = firstFinite(location?.lat_gcj02);
  if (startLng !== null && startLat !== null) {
    return { lng_gcj02: startLng, lat_gcj02: startLat };
  }
  const firstCoordinate = route?.geometry?.coordinates?.[0];
  if (!Array.isArray(firstCoordinate) || firstCoordinate.length < 2) return null;
  const lng = firstFinite(firstCoordinate[0]);
  const lat = firstFinite(firstCoordinate[1]);
  return lng === null || lat === null ? null : { lng_gcj02: lng, lat_gcj02: lat };
}

function haversineDistanceM(from, to) {
  const earthRadiusM = 6_371_000;
  const latitudeDelta = radians(to.lat_gcj02 - from.lat_gcj02);
  const longitudeDelta = radians(to.lng_gcj02 - from.lng_gcj02);
  const fromLatitude = radians(from.lat_gcj02);
  const toLatitude = radians(to.lat_gcj02);
  const haversine = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(fromLatitude) * Math.cos(toLatitude) * Math.sin(longitudeDelta / 2) ** 2;
  return earthRadiusM * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

function radians(value) {
  return Number(value) * Math.PI / 180;
}

function finiteNonNegative(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    throw new Error(`${field}无效。`);
  }
  return number;
}

function firstFinite(...values) {
  const value = values.find((candidate) => (
    candidate !== null
    && candidate !== undefined
    && candidate !== ""
    && Number.isFinite(Number(candidate))
  ));
  return value === undefined ? null : Number(value);
}

function errorMessage(error, fallback) {
  const message = String(error?.message || error || "").trim();
  return message || fallback;
}
