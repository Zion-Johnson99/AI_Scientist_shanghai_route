const ROUTE_STYLES = {
  run: { color: "#ff5d5d", weight: 4 },
  walk: { color: "#13bfa6", weight: 4 },
  bike: { color: "#7C3AED", weight: 4 },
  access: { color: "#ff9f1a", weight: 4 },
};

const ROUTE_LAYER_STATES = {
  active: {
    mainOpacity: 0.98,
    mainWeightOffset: 2,
    mainZIndex: 100,
    haloOpacity: 0.82,
    haloWeightOffset: 8,
    haloZIndex: 99,
  },
  inactive: {
    mainOpacity: 0.4,
    mainWeightOffset: 0,
    mainZIndex: 70,
    haloOpacity: 0.34,
    haloWeightOffset: 5,
    haloZIndex: 69,
  },
  preview: {
    mainOpacity: 0.3,
    mainWeightOffset: 0,
    mainZIndex: 82,
    haloOpacity: 0.28,
    haloWeightOffset: 5,
    haloZIndex: 81,
  },
  muted: {
    mainOpacity: 0.1,
    mainWeightOffset: -1,
    mainZIndex: 62,
    haloOpacity: 0.12,
    haloWeightOffset: 3,
    haloZIndex: 61,
  },
  sporting: {
    mainOpacity: 1,
    mainWeightOffset: 3,
    mainZIndex: 112,
    haloOpacity: 0.9,
    haloWeightOffset: 9,
    haloZIndex: 111,
  },
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
  run: "跑步接驳",
  bike: "骑行接驳",
};

const NAVIGATION_POINT_LABELS = {
  origin: "用户位置",
  destination: "路线起点",
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
        destination: null,
      },
      inlineLayers: null,
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
        strokeColor: "#1677ff",
        strokeWeight: 5,
        strokeOpacity: 0.96,
        fillColor: "#dcecff",
        fillOpacity: 0.16,
        zIndex: 30,
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
    const style = routeStyle(properties.route_mode);
    const sharedExtData = {
      routeId: properties.route_id,
      routeMode: properties.route_mode,
    };
    const halo = new mapContext.AMap.Polyline({
      path,
      strokeColor: "#ffffff",
      strokeWeight: style.weight + 8,
      strokeOpacity: active ? 0.82 : 0.34,
      lineJoin: "round",
      lineCap: "round",
      showDir: false,
      zIndex: active ? 99 : 69,
      extData: { ...sharedExtData, layerRole: "halo" },
    });
    const main = new mapContext.AMap.Polyline({
      path,
      strokeColor: style.color,
      strokeWeight: active ? style.weight + 2 : style.weight,
      strokeOpacity: active ? 0.98 : 0.4,
      lineJoin: "round",
      lineCap: "round",
      showDir: properties.route_shape === "one_way",
      zIndex: active ? 100 : 70,
      extData: { ...sharedExtData, layerRole: "main" },
    });
    main.on("click", () => openRouteInfo(mapContext, main, route));
    mapContext.amap.add(halo);
    mapContext.amap.add(main);
    mapContext.routeLayers.set(properties.route_id, {
      halo,
      main,
      routeMode: properties.route_mode,
      state: active ? "active" : "inactive",
    });
    boundsOverlays.push(main);
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

  const properties = route.properties || {};
  const isLoop = properties.route_shape === "strict_loop";
  const markerSpecs = isLoop
    ? [{ role: "start", label: "起终点", name: properties.start_location?.name || "路线起终点", position: locationPosition(properties.start_location, path[0]) }]
    : [
        { role: "start", label: "起点", name: properties.start_location?.name || "路线起点", position: locationPosition(properties.start_location, path[0]) },
        { role: "end", label: "终点", name: properties.end_location?.name || "路线终点", position: locationPosition(properties.end_location, path.at(-1)) },
      ];
  markerSpecs.push(...landmarkSpecs(route, pois));
  for (const spec of markerSpecs) {
    const marker = createRouteMarker(mapContext, spec);
    mapContext.amap.add(marker);
    mapContext.entryLayers.push(marker);
  }
}

function landmarkSpecs(route, pois) {
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

  const nodes = (properties.ordered_nodes || []).slice(1, -1);
  const remaining = Math.min(3 - specs.length, nodes.length);
  for (const node of nodes.slice(0, remaining)) {
    if (Number.isFinite(node.lng_gcj02) && Number.isFinite(node.lat_gcj02)) {
      specs.push({ role: "landmark", label: "途经", name: node.node_name || node.name, position: [node.lng_gcj02, node.lat_gcj02] });
    }
  }
  return specs;
}

function locationPosition(location, fallback) {
  if (Number.isFinite(location?.lng_gcj02) && Number.isFinite(location?.lat_gcj02)) {
    return [location.lng_gcj02, location.lat_gcj02];
  }
  return fallback;
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
  for (const [routeId, layers] of mapContext.routeLayers.entries()) {
    setRouteLayerState(layers, routeId === selectedRouteId ? "active" : "inactive");
  }
}

export function focusSportRoute(mapContext, selectedRouteId) {
  clearNavigationService(mapContext);
  clearInlineNavigation(mapContext);
  clearNavigationPoints(mapContext);
  for (const [routeId, layers] of mapContext.routeLayers.entries()) {
    setRouteLayerState(layers, routeId === selectedRouteId ? "sporting" : "muted");
  }
  mapContext.navigation.state = "sporting";
}

export function clearRouteResults(mapContext) {
  const routeOverlays = [...mapContext.routeLayers.values()].flatMap(({ halo, main }) => [halo, main]);
  const overlays = [...routeOverlays, ...mapContext.entryLayers, ...mapContext.poiLayers];
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
  clearInlineNavigation(mapContext);
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
  if (role !== "origin") {
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

  for (const [role, point] of [
    ["origin", origin],
    ["destination", destination],
  ]) {
    setNavigationPoint(mapContext, role, lngLatToPoint(point, NAVIGATION_POINT_LABELS[role]));
  }
  const mode = navigationServiceMode(request.routeMode);
  const service = navigationServiceForMode(mapContext, mode);
  clearNavigationService(mapContext);
  mapContext.navigationService = service;
  mapContext.navigation.state = "planned";
  previewSportRoute(mapContext, request.routeId);

  const result = await searchNavigationPath(service, origin, destination);
  const distanceText = result.distance ? `${result.distance.toFixed(0)} 米` : "距离待确认";
  const durationText = result.duration ? `${Math.round(result.duration / 60)} 分钟` : "时间待确认";
  return {
    ...result,
    routeId: request.routeId,
    routeMode: request.routeMode,
    summary: `${NAVIGATION_LABELS[request.routeMode] || "接驳导航"}：${distanceText}，约 ${durationText}。`,
  };
}

export function beginInlineNavigation(mapContext, plan) {
  clearNavigationService(mapContext);
  clearInlineNavigation(mapContext);
  if (!Array.isArray(plan?.path) || plan.path.length < 2) {
    throw new Error("接驳规划缺少网页内导航路径。");
  }

  const halo = new mapContext.AMap.Polyline({
    path: plan.path,
    strokeColor: "#ffffff",
    strokeWeight: 12,
    strokeOpacity: 0.9,
    lineJoin: "round",
    lineCap: "round",
    zIndex: 139,
  });
  const remaining = new mapContext.AMap.Polyline({
    path: plan.path,
    strokeColor: ROUTE_STYLES.access.color,
    strokeWeight: 6,
    strokeOpacity: 1,
    lineJoin: "round",
    lineCap: "round",
    showDir: true,
    zIndex: 140,
  });
  const traveled = new mapContext.AMap.Polyline({
    path: [plan.path[0], plan.path[0]],
    strokeColor: "#7f918c",
    strokeWeight: 5,
    strokeOpacity: 0.8,
    lineJoin: "round",
    lineCap: "round",
    zIndex: 141,
  });
  const user = new mapContext.AMap.Marker({
    position: plan.path[0],
    content: '<span class="amap-navigation-user"><i></i></span>',
    anchor: "center",
    zIndex: 150,
  });
  mapContext.amap.add([halo, remaining, traveled, user]);
  mapContext.navigation.inlineLayers = { halo, remaining, traveled, user };
  mapContext.navigation.state = "navigating";
  mapContext.amap.setFitView([remaining], false, [110, 90, 180, 90]);
}

export function updateInlineNavigation(mapContext, progress) {
  const layers = mapContext.navigation.inlineLayers;
  if (!layers) {
    throw new Error("网页内导航图层尚未初始化。");
  }
  layers.traveled.setPath(progress.traveledPath);
  layers.remaining.setPath(progress.remainingPath);
  layers.remaining.setOptions({
    strokeColor: progress.status === "off_route" ? "#e14f3d" : ROUTE_STYLES.access.color,
  });
  const position = [progress.position.lng, progress.position.lat];
  layers.user.setPosition(position);
  if (Number.isFinite(progress.position.heading)) {
    layers.user.setAngle(progress.position.heading);
  }
  mapContext.navigation.state = progress.status;
  mapContext.amap.panTo(position, 280);
}

export function clearInlineNavigation(mapContext) {
  const layers = mapContext.navigation.inlineLayers;
  if (!layers) {
    return;
  }
  mapContext.amap.remove([layers.halo, layers.remaining, layers.traveled, layers.user]);
  mapContext.navigation.inlineLayers = null;
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
    walking: null,
    riding: null,
  };

  if (AMap.Geocoder) {
    hooks.geocoder = new AMap.Geocoder({ city: "上海" });
  }
  if (AMap.Walking) {
    hooks.walking = new AMap.Walking({ city: "上海", map: amap, hideMarkers: false });
  }
  if (AMap.Riding) {
    hooks.riding = new AMap.Riding({ city: "上海", map: amap, hideMarkers: false });
  }
  return hooks;
}

function previewSportRoute(mapContext, selectedRouteId) {
  for (const [routeId, layers] of mapContext.routeLayers.entries()) {
    setRouteLayerState(layers, routeId === selectedRouteId ? "preview" : "muted");
  }
}

function navigationServiceForMode(mapContext, mode) {
  const services = {
    walk: mapContext.serviceHooks.walking,
    bike: mapContext.serviceHooks.riding,
  };
  const service = services[mode];
  if (!service) {
    throw new Error("当前高德 JS API 未加载对应导航插件。");
  }
  return service;
}

export function navigationServiceMode(routeMode) {
  if (routeMode === "walk" || routeMode === "run") {
    return "walk";
  }
  if (routeMode === "bike") {
    return "bike";
  }
  throw new Error(`不支持的运动类型：${routeMode || "空"}`);
}

function searchNavigationPath(service, origin, destination) {
  return new Promise((resolve, reject) => {
    const callback = (status, result) => {
      const plan = navigationPlanFromResult(result);
      if (status !== "complete" || !plan) {
        reject(new Error("高德路线导航失败，请检查起点、终点或 Key 权限。"));
        return;
      }
      resolve(plan);
    };
    service.search(origin, destination, callback);
  });
}

export function navigationPlanFromResult(result) {
  const route = result?.routes?.[0] || result?.paths?.[0];
  if (!route) {
    return null;
  }
  const rawSteps = route.steps || route.rides || [];
  const steps = rawSteps.map((step) => ({
    instruction: String(step.instruction || step.action || "沿接驳路线继续前行"),
    distance: Number(step.distance || 0),
  }));
  const routePath = normalizeServicePath(route.path);
  const stepPath = rawSteps.flatMap((step) => normalizeServicePath(step.path));
  const path = dedupePath(routePath.length >= 2 ? routePath : stepPath);
  if (path.length < 2) {
    return null;
  }
  return {
    distance: Number(route.distance || 0),
    duration: Number(route.time || route.duration || 0),
    path,
    steps,
  };
}

function normalizeServicePath(path) {
  return (path || []).map((point) => {
    if (Array.isArray(point)) {
      return [Number(point[0]), Number(point[1])];
    }
    return [
      Number(point?.lng ?? point?.getLng?.()),
      Number(point?.lat ?? point?.getLat?.()),
    ];
  }).filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
}

function dedupePath(path) {
  return path.filter((point, index) => {
    const previous = path[index - 1];
    return !previous || previous[0] !== point[0] || previous[1] !== point[1];
  });
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
    zIndex: 35,
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

function routeStyle(mode) {
  const style = ROUTE_STYLES[mode] || ROUTE_STYLES.access;
  return {
    color: style.color,
    weight: style.weight,
  };
}

function setRouteLayerState(layers, stateName) {
  const state = ROUTE_LAYER_STATES[stateName];
  if (!state) {
    throw new Error(`未知路线显示状态：${stateName}`);
  }
  const style = routeStyle(layers.routeMode);
  layers.halo.setOptions({
    strokeColor: "#ffffff",
    strokeWeight: style.weight + state.haloWeightOffset,
    strokeOpacity: state.haloOpacity,
    zIndex: state.haloZIndex,
  });
  layers.main.setOptions({
    strokeColor: style.color,
    strokeWeight: style.weight + state.mainWeightOffset,
    strokeOpacity: state.mainOpacity,
    zIndex: state.mainZIndex,
  });
  layers.state = stateName;
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
