const ROUTE_STYLES = {
  run: { color: "#c74a3e", weight: 7 },
  walk: { color: "#2f7d57", weight: 6 },
  bike: { color: "#2f6fb4", weight: 6 },
  access: { color: "#a66f1d", weight: 5 },
};

const ENTRY_COLORS = {
  metro_exit: "#2f6fb4",
  park_gate: "#2f7d57",
  scenic_node: "#a66f1d",
  community_node: "#717b84",
  riverside_access: "#2f7d57",
  office_cluster: "#384247",
};

const NAVIGATION_LABELS = {
  walk: "步行接驳",
  bike: "骑行接驳",
  drive: "驾车接驳",
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
    routeLayers: new Map(),
    entryLayers: [],
    navigationService: null,
    serviceHooks: createServiceHooks(AMap, amap),
  };
}

export function drawBoundary(mapContext, boundary) {
  const { AMap, amap } = mapContext;
  const layer = new AMap.GeoJSON({
    geoJSON: boundary,
    getPolygon: (_feature, lnglats) =>
      new AMap.Polygon({
        path: lnglats,
        strokeColor: "#2f5f55",
        strokeWeight: 2,
        strokeOpacity: 0.9,
        fillColor: "#dfe8df",
        fillOpacity: 0.22,
        zIndex: 20,
      }),
  });

  amap.add(layer);
  mapContext.boundaryLayer = layer;
  const overlays = layer.getOverlays ? layer.getOverlays() : [];
  amap.setFitView(overlays.length ? overlays : undefined, false, [30, 30, 30, 30]);
  return layer;
}

export function showRouteResults(mapContext, routes, entries, selectedRouteId) {
  clearRouteResults(mapContext);

  const relatedEntryIds = new Set();
  const boundsOverlays = [];

  for (const route of routes) {
    const properties = route.properties || {};
    addRelatedEntryIds(relatedEntryIds, properties);
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
      strokeOpacity: active ? 0.95 : 0.48,
      lineJoin: "round",
      lineCap: "round",
      zIndex: active ? 80 : 50,
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

  if (boundsOverlays.length) {
    mapContext.amap.setFitView(boundsOverlays, false, [44, 44, 44, 44]);
  }
}

export function highlightRoute(mapContext, selectedRouteId) {
  for (const [routeId, layer] of mapContext.routeLayers.entries()) {
    const mode = layer.getExtData()?.routeMode;
    const active = routeId === selectedRouteId;
    const style = routeStyle(mode, active);
    layer.setOptions({
      strokeColor: style.color,
      strokeWeight: style.weight,
      strokeOpacity: active ? 0.95 : 0.42,
      zIndex: active ? 90 : 50,
    });
  }
}

export function clearRouteResults(mapContext) {
  const overlays = [...mapContext.routeLayers.values(), ...mapContext.entryLayers];
  if (overlays.length) {
    mapContext.amap.remove(overlays);
  }
  mapContext.routeLayers.clear();
  mapContext.entryLayers = [];
}

export async function planNavigation(mapContext, request) {
  const origin = await geocodeToLngLat(mapContext, request.originText);
  const destination = await geocodeToLngLat(mapContext, request.destinationText);
  const service = navigationServiceForMode(mapContext, request.mode);

  clearNavigation(mapContext);
  mapContext.navigationService = service;

  return new Promise((resolve, reject) => {
    service.search(origin, destination, (status, result) => {
      if (status !== "complete") {
        reject(new Error("高德路线导航失败，请检查起点、终点或 Key 权限。"));
        return;
      }
      const route = result?.routes?.[0];
      const distance = Number(route?.distance || 0);
      const duration = Number(route?.time || 0);
      const distanceText = distance ? `${distance.toFixed(0)} 米` : "距离待确认";
      const durationText = duration ? `${Math.round(duration / 60)} 分钟` : "时间待确认";
      resolve(`${NAVIGATION_LABELS[request.mode] || "接驳导航"}：${distanceText}，约 ${durationText}。`);
    });
  });
}

function clearNavigation(mapContext) {
  if (mapContext.navigationService?.clear) {
    mapContext.navigationService.clear();
  }
  mapContext.navigationService = null;
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

function geocodeToLngLat(mapContext, text) {
  const parsed = parseLngLat(text);
  if (parsed) {
    return Promise.resolve(parsed);
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
  const parts = String(text || "").split(",").map((part) => Number(part.trim()));
  if (parts.length !== 2 || parts.some((part) => Number.isNaN(part))) {
    return null;
  }
  return parts;
}

function addRelatedEntryIds(relatedEntryIds, properties) {
  for (const key of ["start_entry_id", "end_entry_id"]) {
    if (properties[key]) {
      relatedEntryIds.add(properties[key]);
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
    weight: active ? style.weight + 2 : style.weight,
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
