export const DEFAULT_LOCATION = Object.freeze({
  label: "上海交通大学徐汇校区",
  lng_gcj02: 121.433,
  lat_gcj02: 31.2015,
});

export const LOCATION_PLACEHOLDER = "搜索地点";

const LOCATION_STATUSES = new Set(["idle", "searching", "locating"]);
const ROUTE_MODES = new Set(["walk", "run", "bike"]);

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

export function createAmapLocationServices(mapContext) {
  const AMap = mapContext?.AMap;
  if (!AMap?.AutoComplete || !AMap?.Geolocation) {
    throw new Error("高德地点搜索或定位插件未加载。");
  }
  const autocomplete = new AMap.AutoComplete({ city: "上海", citylimit: true });
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

  return {
    suggest(query) {
      const keyword = String(query || "").trim();
      if (!keyword) return Promise.resolve([]);
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
          if (result === "USER_DAILY_QUERY_OVER_LIMIT" && geocoder) {
            geocodeSuggestion(keyword).then(resolve, reject);
            return;
          }
          reject(new Error(String(result?.info || result?.message || result || "地点联想搜索失败。")));
        });
      });
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
