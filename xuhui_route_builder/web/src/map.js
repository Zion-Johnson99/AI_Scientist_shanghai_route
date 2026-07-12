const ROUTE_STYLES = {
  run: { color: "#c84636", weight: 4 },
  walk: { color: "#25734f", weight: 4 },
  bike: { color: "#256db3", weight: 4 },
  access: { color: "#a66f1d", weight: 4 },
};

const ENTRY_COLORS = {
  metro_exit: "#256db3",
  park_gate: "#25734f",
  scenic_node: "#a66f1d",
  community_node: "#717b84",
  riverside_access: "#25734f",
  office_cluster: "#384247",
};

const POI_COLORS = {
  coffee: "#8a5a2b",
  toilet: "#516070",
  convenience: "#b06a20",
  metro: "#256db3",
  park_gate: "#25734f",
};

const POI_TYPES_BY_PREFERENCE = {
  coffee: ["coffee"],
  toilet: ["toilet"],
  store: ["convenience"],
  metro: ["metro"],
  park: ["park_gate"],
};

const NAVIGATION_LABELS = {
  walk: "步行接驳",
  bike: "骑行接驳",
  drive: "驾车接驳",
};

const NAVIGATION_POINT_LABELS = {
  origin: "起点",
  waypoint: "途经点",
  destination: "终点",
};

export async function createMap(targetId) {
  const AMap = await window.XUHUI_AMAP_READY;
  const amap = new AMap.Map(targetId, {
    center: [121.4361, 31.1763],
    zoom: 13,
    resizeEnable: true,
    viewMode: "2D",
    mapStyle: "amap://styles/normal",
  });

  return {
    AMap,
    amap,
    boundaryLayer: null,
    boundaryRings: [],
    routeLayers: new Map(),
    entryLayers: [],
    poiLayers: [],
    navigationService: null,
    navigation: {
      state: "idle",
      pickRole: "",
      onPick: null,
      clickHandler: null,
      domClickHandler: null,
      markers: new Map(),
      points: {
        origin: null,
        waypoint: null,
        destination: null,
      },
    },
    serviceHooks: createServiceHooks(AMap, amap),
  };
}

export function drawBoundary(mapContext, boundary) {
  const { AMap, amap } = mapContext;
  mapContext.boundaryRings = extractBoundaryRings(boundary);
  const layer = new AMap.GeoJSON({
    geoJSON: boundary,
    getPolygon: (_feature, lnglats) =>
      new AMap.Polygon({
        path: lnglats,
        strokeColor: "#17483f",
        strokeWeight: 5,
        strokeOpacity: 0.96,
        fillColor: "#dce8df",
        fillOpacity: 0.16,
        zIndex: 120,
      }),
  });

  amap.add(layer);
  mapContext.boundaryLayer = layer;
  addBoundaryLabel(mapContext);
  const overlays = layer.getOverlays ? layer.getOverlays() : [];
  amap.setFitView(overlays.length ? overlays : undefined, false, [30, 30, 30, 30]);
  return layer;
}

export function showRouteResults(mapContext, routes, entries, pois, selectedRouteId, selectedPreferences = []) {
  clearRouteResults(mapContext);

  const relatedEntryIds = new Set();
  const relatedPoiIds = new Set();
  const boundsOverlays = [];

  for (const route of routes) {
    const properties = route.properties || {};
    addRelatedEntryIds(relatedEntryIds, properties);
    addRelatedPoiIds(relatedPoiIds, properties, selectedPreferences);
    const path = getLinePath(route);
    if (path.length < 2) {
      continue;
    }

    const active = properties.route_id === selectedRouteId;
    const style = routeStyle(properties.route_mode, active);
    const layer = new mapContext.AMap.Polyline({
      path,
      strokeColor: style.color,
      strokeWeight: style.weight,
      strokeOpacity: active ? 0.95 : 0.44,
      lineJoin: "round",
      lineCap: "round",
      zIndex: active ? 100 : 70,
      extData: {
        routeId: properties.route_id,
        routeMode: properties.route_mode,
      },
    });
    layer.on("click", () => openRouteInfo(mapContext, layer, route));
    mapContext.amap.add(layer);
    mapContext.routeLayers.set(properties.route_id, layer);
    boundsOverlays.push(layer);
  }

  for (const entry of entries.features || []) {
    const props = entry.properties || {};
    const entryId = props.entry_id;
    if (!relatedEntryIds.has(entryId)) {
      continue;
    }

    const marker = createEntryMarker(mapContext, entry);
    if (marker) {
      mapContext.amap.add(marker);
      mapContext.entryLayers.push(marker);
      boundsOverlays.push(marker);
    }
  }

  for (const poi of pois?.features || []) {
    const props = poi.properties || {};
    if (!relatedPoiIds.has(props.poi_id)) {
      continue;
    }
    const marker = createPoiMarker(mapContext, poi);
    if (marker) {
      mapContext.amap.add(marker);
      mapContext.poiLayers.push(marker);
      boundsOverlays.push(marker);
    }
  }

  if (boundsOverlays.length) {
    mapContext.amap.setFitView(boundsOverlays, false, [44, 44, 44, 44]);
  }
}

export function showSingleRoute(mapContext, route, entries, pois) {
  const routeId = route?.properties?.route_id;
  if (!routeId) {
    clearRouteResults(mapContext);
    return;
  }
  showRouteResults(mapContext, [route], entries, pois, routeId, []);
  const path = getLinePath(route);
  if (path.length < 2) {
    return;
  }

  const names = route.properties?.waypoint_names || [];
  const markerSpecs = [
    { role: "start", label: "起点", name: names[0] || "路线起点", position: path[0] },
    { role: "end", label: "终点", name: names.at(-1) || "路线终点", position: path.at(-1) },
    ...landmarkSpecs(route, path, pois),
  ];
  for (const spec of markerSpecs) {
    const marker = createRouteMarker(mapContext, spec);
    mapContext.amap.add(marker);
    mapContext.entryLayers.push(marker);
  }
}

function landmarkSpecs(route, path, pois) {
  const specs = [];
  const properties = route.properties || {};
  const poiById = new Map((pois?.features || []).map((poi) => [poi.properties?.poi_id, poi]));
  for (const related of properties.nearby_pois || []) {
    const poi = poiById.get(related.poi_id);
    const position = poi?.geometry?.coordinates;
    if (Array.isArray(position) && position.length >= 2) {
      specs.push({ role: "landmark", label: "补给", name: related.poi_name, position });
    }
    if (specs.length >= 3) {
      return specs;
    }
  }

  const names = (properties.waypoint_names || []).slice(1, -1);
  const remaining = Math.min(3 - specs.length, names.length);
  for (let index = 0; index < remaining; index += 1) {
    const pathIndex = Math.round(((index + 1) * (path.length - 1)) / (remaining + 1));
    specs.push({ role: "landmark", label: "途经", name: names[index], position: path[pathIndex] });
  }
  return specs;
}

function createRouteMarker(mapContext, spec) {
  const content = `
    <span class="amap-route-marker" data-role="${spec.role}">
      <b>${escapeHtml(spec.label)}</b><em>${escapeHtml(spec.name)}</em>
    </span>`;
  return new mapContext.AMap.Marker({
    position: spec.position,
    content,
    anchor: "bottom-center",
    offset: new mapContext.AMap.Pixel(0, -4),
    zIndex: spec.role === "landmark" ? 120 : 130,
  });
}

export function highlightRoute(mapContext, selectedRouteId) {
  for (const [routeId, layer] of mapContext.routeLayers.entries()) {
    const mode = layer.getExtData()?.routeMode;
    const active = routeId === selectedRouteId;
    const style = routeStyle(mode, active);
    layer.setOptions({
      strokeColor: style.color,
      strokeWeight: style.weight,
      strokeOpacity: active ? 0.95 : 0.38,
      zIndex: active ? 110 : 70,
    });
  }
}

export function clearRouteResults(mapContext) {
  const overlays = [...mapContext.routeLayers.values(), ...mapContext.entryLayers, ...mapContext.poiLayers];
  if (overlays.length) {
    mapContext.amap.remove(overlays);
  }
  mapContext.routeLayers.clear();
  mapContext.entryLayers = [];
  mapContext.poiLayers = [];
}

export function startNavigationSession(mapContext, onPick) {
  endNavigationSession(mapContext);
  mapContext.navigation.state = "editing";
  mapContext.navigation.onPick = onPick;
  const handlePickedPoint = (role, point) => {
    if (!isPointInsideXuhui(mapContext, point)) {
      onPick?.({ role, error: "点位不在徐汇区范围内，请重新选择。" });
      return;
    }
    setNavigationPoint(mapContext, role, point);
    mapContext.navigation.pickRole = "";
    onPick?.({ role, point });
  };
  mapContext.navigation.clickHandler = (event) => {
    const role = mapContext.navigation.pickRole;
    if (!role) {
      return;
    }
    const point = lngLatToPoint(event.lnglat, "地图点");
    handlePickedPoint(role, point);
  };
  mapContext.navigation.domClickHandler = (event) => {
    const role = mapContext.navigation.pickRole;
    if (!role) {
      return;
    }
    const point = containerEventToPoint(mapContext, event);
    if (point) {
      handlePickedPoint(role, point);
    }
  };
  mapContext.amap.on("click", mapContext.navigation.clickHandler);
  mapContainer(mapContext)?.addEventListener("click", mapContext.navigation.domClickHandler);
}

export function endNavigationSession(mapContext) {
  clearNavigationService(mapContext);
  clearNavigationPoints(mapContext);
  if (mapContext.navigation.clickHandler) {
    mapContext.amap.off("click", mapContext.navigation.clickHandler);
  }
  if (mapContext.navigation.domClickHandler) {
    mapContainer(mapContext)?.removeEventListener("click", mapContext.navigation.domClickHandler);
  }
  mapContext.navigation.state = "idle";
  mapContext.navigation.pickRole = "";
  mapContext.navigation.onPick = null;
  mapContext.navigation.clickHandler = null;
  mapContext.navigation.domClickHandler = null;
}

export function enablePointPicker(mapContext, role) {
  if (!["origin", "waypoint", "destination"].includes(role)) {
    throw new Error("未知的导航点类型。");
  }
  if (mapContext.navigation.state === "idle") {
    throw new Error("请先点击开始导航。");
  }
  mapContext.navigation.pickRole = role;
}

export function setNavigationPoint(mapContext, role, point) {
  const normalized = normalizePoint(point);
  if (!isPointInsideXuhui(mapContext, normalized)) {
    throw new Error("点位不在徐汇区范围内。");
  }

  const oldMarker = mapContext.navigation.markers.get(role);
  if (oldMarker) {
    mapContext.amap.remove(oldMarker);
  }

  const marker = createNavigationMarker(mapContext, role, normalized);
  mapContext.amap.add(marker);
  mapContext.navigation.markers.set(role, marker);
  mapContext.navigation.points[role] = normalized;
  return normalized;
}

export function isPointInsideXuhui(mapContext, point) {
  const normalized = normalizePoint(point);
  if (!mapContext.boundaryRings.length) {
    return true;
  }
  return mapContext.boundaryRings.some((ring) => pointInRing([normalized.lng_gcj02, normalized.lat_gcj02], ring));
}

export async function planNavigation(mapContext, request) {
  const origin = await resolveNavigationValue(mapContext, request.origin);
  const destination = await resolveNavigationValue(mapContext, request.destination);
  const waypoints = [];
  for (const waypoint of request.waypoints || []) {
    if (waypoint) {
      waypoints.push(await resolveNavigationValue(mapContext, waypoint));
    }
  }

  for (const [role, point] of [
    ["origin", origin],
    ["destination", destination],
  ]) {
    setNavigationPoint(mapContext, role, lngLatToPoint(point, NAVIGATION_POINT_LABELS[role]));
  }
  if (waypoints[0]) {
    setNavigationPoint(mapContext, "waypoint", lngLatToPoint(waypoints[0], NAVIGATION_POINT_LABELS.waypoint));
  }

  const service = navigationServiceForMode(mapContext, request.mode);
  clearNavigationService(mapContext);
  mapContext.navigationService = service;
  mapContext.navigation.state = "planned";

  const result = await searchNavigationPath(service, request.mode, origin, destination, waypoints);
  const viaText = waypoints.length ? `，途经 ${waypoints.length} 点` : "";
  const distanceText = result.distance ? `${result.distance.toFixed(0)} 米` : "距离待确认";
  const durationText = result.duration ? `${Math.round(result.duration / 60)} 分钟` : "时间待确认";
  return `${NAVIGATION_LABELS[request.mode] || "接驳导航"}${viaText}：${distanceText}，约 ${durationText}。`;
}

function clearNavigationService(mapContext) {
  if (mapContext.navigationService?.clear) {
    mapContext.navigationService.clear();
  }
  mapContext.navigationService = null;
}

function clearNavigationPoints(mapContext) {
  const markers = [...mapContext.navigation.markers.values()];
  if (markers.length) {
    mapContext.amap.remove(markers);
  }
  mapContext.navigation.markers.clear();
  mapContext.navigation.points = {
    origin: null,
    waypoint: null,
    destination: null,
  };
}

function mapContainer(mapContext) {
  return mapContext.amap.getContainer?.() || document.getElementById("map");
}

function containerEventToPoint(mapContext, event) {
  const container = mapContainer(mapContext);
  if (!container || typeof mapContext.amap.containerToLngLat !== "function") {
    return null;
  }
  const rect = container.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
    return null;
  }
  const lnglat = mapContext.amap.containerToLngLat(new mapContext.AMap.Pixel(x, y));
  return lngLatToPoint(lnglat, "地图点");
}

function createServiceHooks(AMap, amap) {
  const hooks = {
    geocoder: null,
    driving: null,
    walking: null,
    riding: null,
  };

  if (AMap.Geocoder) {
    hooks.geocoder = new AMap.Geocoder({ city: "上海" });
  }
  if (AMap.Driving) {
    hooks.driving = new AMap.Driving({ city: "上海", map: amap, hideMarkers: false });
  }
  if (AMap.Walking) {
    hooks.walking = new AMap.Walking({ city: "上海", map: amap, hideMarkers: false });
  }
  if (AMap.Riding) {
    hooks.riding = new AMap.Riding({ city: "上海", map: amap, hideMarkers: false });
  }
  return hooks;
}

function navigationServiceForMode(mapContext, mode) {
  const services = {
    walk: mapContext.serviceHooks.walking,
    bike: mapContext.serviceHooks.riding,
    drive: mapContext.serviceHooks.driving,
  };
  const service = services[mode];
  if (!service) {
    throw new Error("当前高德 JS API 未加载对应导航插件。");
  }
  return service;
}

function searchNavigationPath(service, mode, origin, destination, waypoints) {
  if (waypoints.length && mode !== "drive") {
    return searchNavigationSegments(service, [origin, ...waypoints, destination]);
  }

  return new Promise((resolve, reject) => {
    const callback = (status, result) => {
      const summary = firstRouteSummary(result);
      if (status !== "complete" || !summary) {
        reject(new Error("高德路线导航失败，请检查起点、终点或 Key 权限。"));
        return;
      }
      resolve(summary);
    };
    if (waypoints.length && mode === "drive") {
      service.search(origin, destination, { waypoints }, callback);
      return;
    }
    service.search(origin, destination, callback);
  });
}

async function searchNavigationSegments(service, points) {
  let distance = 0;
  let duration = 0;
  for (let index = 0; index < points.length - 1; index += 1) {
    const segment = await new Promise((resolve, reject) => {
      service.search(points[index], points[index + 1], (status, result) => {
        const summary = firstRouteSummary(result);
        if (status !== "complete" || !summary) {
          reject(new Error("高德路线导航失败，请检查途经点或 Key 权限。"));
          return;
        }
        resolve(summary);
      });
    });
    distance += segment.distance;
    duration += segment.duration;
  }
  return { distance, duration };
}

function firstRouteSummary(result) {
  const route = result?.routes?.[0] || result?.paths?.[0];
  if (!route) {
    return null;
  }
  return {
    distance: Number(route.distance || 0),
    duration: Number(route.time || route.duration || 0),
  };
}

function resolveNavigationValue(mapContext, value) {
  const point = normalizePoint(value);
  if (point) {
    if (!isPointInsideXuhui(mapContext, point)) {
      return Promise.reject(new Error("导航点不在徐汇区范围内。"));
    }
    return Promise.resolve(new mapContext.AMap.LngLat(point.lng_gcj02, point.lat_gcj02));
  }

  const text = String(value?.text || value || "").trim();
  if (!text) {
    return Promise.reject(new Error("缺少导航点。"));
  }
  return geocodeToLngLat(mapContext, text).then((lnglat) => {
    const resolved = lngLatToPoint(lnglat, text);
    if (!isPointInsideXuhui(mapContext, resolved)) {
      throw new Error(`地点不在徐汇区范围内：${text}`);
    }
    return lnglat;
  });
}

function geocodeToLngLat(mapContext, text) {
  const parsed = parseLngLat(text);
  if (parsed) {
    return Promise.resolve(new mapContext.AMap.LngLat(parsed.lng_gcj02, parsed.lat_gcj02));
  }
  const geocoder = mapContext.serviceHooks.geocoder;
  if (!geocoder) {
    return Promise.reject(new Error("当前高德 JS API 未加载地理编码插件。"));
  }
  return new Promise((resolve, reject) => {
    geocoder.getLocation(text, (status, result) => {
      const location = result?.geocodes?.[0]?.location;
      if (status !== "complete" || !location) {
        reject(new Error(`无法识别地点：${text}`));
        return;
      }
      resolve(location);
    });
  });
}

function parseLngLat(text) {
  const parts = String(text || "")
    .split(",")
    .map((part) => Number(part.trim()));
  if (parts.length !== 2 || parts.some((part) => Number.isNaN(part))) {
    return null;
  }
  return { lng_gcj02: parts[0], lat_gcj02: parts[1], label: text, source: "text" };
}

function addRelatedEntryIds(relatedEntryIds, properties) {
  for (const key of ["start_entry_id", "end_entry_id"]) {
    if (properties[key]) {
      relatedEntryIds.add(properties[key]);
    }
  }
}

function addRelatedPoiIds(relatedPoiIds, properties, selectedPreferences) {
  const allowedTypes = new Set(selectedPreferences.flatMap((preference) => POI_TYPES_BY_PREFERENCE[preference] || []));
  for (const poi of properties.nearby_pois || []) {
    if (!allowedTypes.size || allowedTypes.has(poi.poi_type)) {
      relatedPoiIds.add(poi.poi_id);
    }
  }
}

function createEntryMarker(mapContext, entry) {
  const props = entry.properties || {};
  const coordinates = entry.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) {
    return null;
  }

  const color = ENTRY_COLORS[props.entry_type] || "#384247";
  const content = `<span class="amap-entry-dot" style="background:${color}"></span>`;
  const marker = new mapContext.AMap.Marker({
    position: coordinates,
    content,
    anchor: "center",
    offset: new mapContext.AMap.Pixel(0, 0),
    zIndex: props.entry_type === "community_node" ? 45 : 60,
  });
  marker.on("click", () => openEntryInfo(mapContext, marker, entry));
  return marker;
}

function createPoiMarker(mapContext, poi) {
  const props = poi.properties || {};
  const coordinates = poi.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) {
    return null;
  }

  const color = POI_COLORS[props.poi_type] || "#384247";
  const content = `<span class="amap-poi-dot" style="background:${color}"></span>`;
  const marker = new mapContext.AMap.Marker({
    position: coordinates,
    content,
    anchor: "center",
    offset: new mapContext.AMap.Pixel(0, 0),
    zIndex: 75,
  });
  marker.on("click", () => openPoiInfo(mapContext, marker, poi));
  return marker;
}

function createNavigationMarker(mapContext, role, point) {
  const label = NAVIGATION_POINT_LABELS[role] || "导航点";
  const content = `<span class="amap-navigation-dot" data-role="${role}">${escapeHtml(label.slice(0, 1))}</span>`;
  return new mapContext.AMap.Marker({
    position: [point.lng_gcj02, point.lat_gcj02],
    content,
    anchor: "center",
    offset: new mapContext.AMap.Pixel(0, 0),
    zIndex: 130,
  });
}

function addBoundaryLabel(mapContext) {
  const ring = mapContext.boundaryRings[0];
  if (!ring?.length) {
    return;
  }
  const center = ringCenter(ring);
  const marker = new mapContext.AMap.Marker({
    position: center,
    content: `<span class="amap-boundary-label">徐汇区</span>`,
    anchor: "center",
    zIndex: 125,
  });
  mapContext.amap.add(marker);
}

function openRouteInfo(mapContext, layer, route) {
  const props = route.properties || {};
  const info = new mapContext.AMap.InfoWindow({
    content: `<strong>${escapeHtml(props.route_name || "候选路线")}</strong><br>${escapeHtml(props.region_zone || "徐汇区")}`,
    offset: new mapContext.AMap.Pixel(0, -8),
  });
  const path = layer.getPath();
  info.open(mapContext.amap, path[Math.floor(path.length / 2)]);
}

function openEntryInfo(mapContext, marker, entry) {
  const props = entry.properties || {};
  const info = new mapContext.AMap.InfoWindow({
    content: `<strong>${escapeHtml(props.entry_name || "运动入口")}</strong><br>${escapeHtml(props.region_zone || "徐汇区")}<br>${escapeHtml(props.entry_type || "entry")}`,
    offset: new mapContext.AMap.Pixel(0, -18),
  });
  info.open(mapContext.amap, marker.getPosition());
}

function openPoiInfo(mapContext, marker, poi) {
  const props = poi.properties || {};
  const info = new mapContext.AMap.InfoWindow({
    content: `<strong>${escapeHtml(props.poi_name || "POI")}</strong><br>${escapeHtml(props.region_zone || "徐汇区")}<br>${escapeHtml(props.poi_type || "")}`,
    offset: new mapContext.AMap.Pixel(0, -18),
  });
  info.open(mapContext.amap, marker.getPosition());
}

function getLinePath(route) {
  const coordinates = route.geometry?.coordinates;
  if (!Array.isArray(coordinates)) {
    return [];
  }
  return coordinates.filter((point) => Array.isArray(point) && point.length >= 2);
}

function routeStyle(mode, active) {
  const style = ROUTE_STYLES[mode] || ROUTE_STYLES.access;
  return {
    color: style.color,
    weight: style.weight,
  };
}

function extractBoundaryRings(boundary) {
  const rings = [];
  for (const feature of boundary?.features || [boundary]) {
    const geometry = feature?.geometry;
    if (!geometry) {
      continue;
    }
    if (geometry.type === "Polygon") {
      rings.push(...geometry.coordinates);
    }
    if (geometry.type === "MultiPolygon") {
      for (const polygon of geometry.coordinates) {
        rings.push(...polygon);
      }
    }
  }
  return rings;
}

function ringCenter(ring) {
  const total = ring.reduce(
    (acc, point) => {
      acc.lng += Number(point[0]);
      acc.lat += Number(point[1]);
      return acc;
    },
    { lng: 0, lat: 0 },
  );
  return [total.lng / ring.length, total.lat / ring.length];
}

function pointInRing(point, ring) {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi || Number.EPSILON) + xi;
    if (intersects) {
      inside = !inside;
    }
  }
  return inside;
}

function normalizePoint(value) {
  if (!value) {
    return null;
  }
  if (Array.isArray(value) && value.length >= 2) {
    return { lng_gcj02: Number(value[0]), lat_gcj02: Number(value[1]), label: "", source: "array" };
  }
  if (typeof value.getLng === "function" && typeof value.getLat === "function") {
    return { lng_gcj02: value.getLng(), lat_gcj02: value.getLat(), label: "", source: "amap" };
  }
  if (typeof value.lng === "number" && typeof value.lat === "number") {
    return { lng_gcj02: value.lng, lat_gcj02: value.lat, label: value.label || "", source: value.source || "amap" };
  }
  if (typeof value.lng_gcj02 === "number" && typeof value.lat_gcj02 === "number") {
    return value;
  }
  if (typeof value.text === "string") {
    return null;
  }
  return null;
}

function lngLatToPoint(lnglat, label) {
  const normalized = normalizePoint(lnglat);
  if (!normalized) {
    throw new Error("无效导航点。");
  }
  return {
    lng_gcj02: normalized.lng_gcj02,
    lat_gcj02: normalized.lat_gcj02,
    label: label || normalized.label || "地图点",
    source: normalized.source || "map",
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char];
  });
}
