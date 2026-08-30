import { routeSemanticWaypoints } from "./route-dock.js";

const ROUTE_STYLES = {
  run: { color: "#ff5d5d", weight: 4 },
  walk: { color: "#13bfa6", weight: 4 },
  bike: { color: "#7C3AED", weight: 4 },
  access: { color: "#ff9f1a", weight: 4 },
};

const ROUTE_LAYER_STATES = {
  overview: {
    mainOpacity: 0.78,
    mainWeightOffset: 1,
    mainZIndex: 84,
    haloOpacity: 0.62,
    haloWeightOffset: 6,
    haloZIndex: 83,
  },
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
  "preview-muted": {
    mainOpacity: 0.2,
    mainWeightOffset: -1,
    mainZIndex: 66,
    haloOpacity: 0.18,
    haloWeightOffset: 3,
    haloZIndex: 65,
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

const ROUTE_REVEAL_DURATION_MS = 1200;

const NAVIGATION_LABELS = {
  walk: "步行接驳",
  run: "跑步接驳",
  bike: "骑行接驳",
};

const NAVIGATION_POINT_LABELS = {
  origin: "出发地",
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
  const scaleControl = new AMap.Scale({
    position: "RB",
    offset: new AMap.Pixel(20, 38),
  });
  amap.addControl(scaleControl);

  return {
    AMap,
    amap,
    scaleControl,
    boundaryLayer: null,
    boundaryRings: [],
    routeLayers: new Map(),
    recommendationMapState: createRecommendationMapState(),
    routePreviewLayers: [],
    routePreviewMarkers: [],
    routePreviewZoomHandler: null,
    entryLayers: [],
    poiLayers: [],
    semanticMarkerLayers: [],
    routeRevealAnimation: null,
    userLocationMarker: null,
    navigationService: null,
    navigation: {
      state: "idle",
      planRevision: 0,
      serviceRevision: 0,
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
        strokeColor: "#0b2856",
        strokeWeight: 4,
        strokeOpacity: 0.96,
        fillColor: "#dcecff",
        fillOpacity: 0.16,
        bubble: true,
        zIndex: 30,
      }),
  });

  amap.add(layer);
  mapContext.boundaryLayer = layer;
  fitBoundaryView(mapContext);
  return layer;
}

export function fitBoundaryView(mapContext) {
  const overlays = mapContext.boundaryLayer?.getOverlays?.() || [];
  mapContext.amap.setFitView(overlays.length ? overlays : undefined, false, [30, 30, 30, 30]);
}

export function showRoutePreviews(
  mapContext,
  routes,
  onSelectRoute = () => {},
  onPreviewRoute = () => {},
) {
  clearRouteResults(mapContext);
  const markerGroups = new Map();

  for (const route of routes) {
    const path = getLinePath(route);
    if (path.length < 2) {
      continue;
    }

    const properties = route.properties || {};
    const line = new mapContext.AMap.Polyline({
      path,
      strokeColor: "#3d91ff",
      strokeWeight: 4,
      strokeOpacity: 0.34,
      lineJoin: "round",
      lineCap: "round",
      showDir: false,
      zIndex: 64,
      extData: { routeId: properties.route_id, layerRole: "preview" },
    });
    mapContext.amap.add(line);
    line.__routeId = properties.route_id;
    line.on?.("mouseover", () => onPreviewRoute(properties.route_id));
    line.on?.("mouseout", () => onPreviewRoute(null));
    mapContext.routePreviewLayers.push(line);

    const position = locationPosition(properties.start_location, path[0]);
    const marker = createRoutePreviewMarker(mapContext, route, position, onSelectRoute, onPreviewRoute);
    mapContext.amap.add(marker);
    const groupKey = `${Number(position[0]).toFixed(6)},${Number(position[1]).toFixed(6)}`;
    const group = markerGroups.get(groupKey) || [];
    group.push(marker);
    markerGroups.set(groupKey, group);
  }

  for (const markers of markerGroups.values()) {
    markers.forEach((marker, index) => {
      mapContext.routePreviewMarkers.push({
        marker,
        index,
        count: markers.length,
        routeId: marker.__routeId,
        content: marker.__routePreviewContent,
      });
    });
  }
  applyRoutePreviewOffsets(mapContext);
  mapContext.routePreviewZoomHandler = () => applyRoutePreviewOffsets(mapContext);
  mapContext.amap.on("zoomend", mapContext.routePreviewZoomHandler);

  if (mapContext.routePreviewLayers.length) {
    mapContext.amap.setFitView(mapContext.routePreviewLayers, false, [56, 56, 56, 56]);
  }
}

export function routePreviewCardModel(route) {
  const properties = route?.properties || route || {};
  const fullName = String(properties.route_name || "候选路线");
  const characters = [...fullName];
  const shortName = characters.length > 6 ? `${characters.slice(0, 6).join("")}…` : fullName;
  const distanceM = Number(
    properties.actual_distance_m ?? properties.distance_m ?? properties.target_distance_m ?? 0,
  );
  const distanceText = `${(Math.max(0, distanceM) / 1000).toFixed(2)} 公里`;
  return {
    routeId: properties.route_id,
    fullName,
    shortName,
    distanceText,
    ariaLabel: `${fullName}，${distanceText}`,
  };
}

export function previewMarkerOffset(index, count, zoom) {
  if (count <= 1) {
    return { x: 0, y: -8 };
  }
  if (zoom < 15) {
    return {
      x: Math.round((index - (count - 1) / 2) * 12),
      y: -8 - index * 9,
    };
  }
  const row = Math.floor(index / 2);
  const direction = index % 2 === 0 ? -1 : 1;
  return {
    x: direction * (82 + row * 18),
    y: -12 - row * 54,
  };
}

export function showRouteResults(
  mapContext,
  routes,
  entries,
  pois,
  selectedRouteId,
  selectedPreferences = [],
  routeInteractions = {},
) {
  clearRouteResults(mapContext);

  const boundsOverlays = [];

  for (const route of routes) {
    const properties = route.properties || {};
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
      showDir: true,
      zIndex: active ? 100 : 70,
      extData: { ...sharedExtData, layerRole: "main" },
    });
    main.on("click", () => {
      if (routeInteractions.onSelectRoute) {
        routeInteractions.onSelectRoute(properties.route_id);
        return;
      }
      openRouteInfo(mapContext, main, route);
    });
    if (routeInteractions.onPreviewRoute) {
      main.on("mouseover", () => routeInteractions.onPreviewRoute(properties.route_id));
    }
    if (routeInteractions.onClearPreview) {
      main.on("mouseout", () => routeInteractions.onClearPreview(properties.route_id));
    }
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

  if (boundsOverlays.length && routeInteractions.fitView !== false) {
    mapContext.amap.setFitView(boundsOverlays, false, [44, 44, 44, 44]);
  }
}

export function createRecommendationMapController(mapContext, callbacks = {}) {
  const state = ensureRecommendationMapState(mapContext);
  let routeById = new Map();
  let availablePois = { features: [] };
  let activePreferences = [];

  function getState() {
    return recommendationMapSnapshot(state);
  }

  function emitStateChange() {
    const snapshot = getState();
    callbacks.onStateChange?.(snapshot);
    return snapshot;
  }

  function showRoutes(routes, entries = { features: [] }, pois = { features: [] }, selectedPreferences = []) {
    routeById = new Map(routes.map((route) => [route?.properties?.route_id, route]));
    availablePois = pois;
    activePreferences = [...selectedPreferences];
    showRouteResults(
      mapContext,
      routes,
      entries,
      pois,
      null,
      selectedPreferences,
      {
        fitView: false,
        onPreviewRoute(routeId) {
          previewRoute(routeId);
          callbacks.onRouteHover?.(routeId);
        },
        onClearPreview(routeId) {
          if (state.hoveredRouteId !== routeId) {
            return;
          }
          clearPreview(routeId);
          callbacks.onRouteHover?.(null);
        },
        onSelectRoute(routeId) {
          focusRoute(routeId);
          callbacks.onRouteSelect?.(routeId);
        },
      },
    );
    state.recommendedRouteIds = [...mapContext.routeLayers.keys()];
    state.hoveredRouteId = null;
    state.selectedRouteId = null;
    state.mapMode = "overview";
    applyRecommendationOverview(mapContext, state, true);
    clearSemanticMarkers(mapContext);
    return emitStateChange();
  }

  function previewRoute(routeId) {
    if (!hasRecommendedRoute(state, routeId) || state.mapMode === "focused") {
      return getState();
    }
    state.hoveredRouteId = routeId;
    state.selectedRouteId = null;
    state.mapMode = "preview";
    for (const [candidateRouteId, layers] of mapContext.routeLayers.entries()) {
      setRouteLayerState(layers, candidateRouteId === routeId ? "active" : "preview-muted");
    }
    clearSemanticMarkers(mapContext);
    return emitStateChange();
  }

  function clearPreview(routeId) {
    if (state.mapMode !== "preview" || state.hoveredRouteId !== routeId) {
      return getState();
    }
    state.hoveredRouteId = null;
    state.mapMode = "overview";
    applyRecommendationOverview(mapContext, state, false);
    clearSemanticMarkers(mapContext);
    return emitStateChange();
  }

  function focusRoute(routeId) {
    if (!hasRecommendedRoute(state, routeId)) {
      return getState();
    }
    if (state.mapMode === "focused" && state.selectedRouteId === routeId) {
      return getState();
    }
    cancelRouteReveal(mapContext, false);
    state.hoveredRouteId = null;
    state.selectedRouteId = routeId;
    state.mapMode = "focused";
    for (const [candidateRouteId, layers] of mapContext.routeLayers.entries()) {
      setRouteLayerState(layers, candidateRouteId === routeId ? "sporting" : "muted");
    }
    showSemanticRoute(routeId, true);
    const selectedLayer = mapContext.routeLayers.get(routeId)?.main;
    if (selectedLayer) {
      mapContext.amap.setFitView([selectedLayer], true, [110, 90, 180, 90], 18);
    }
    startRouteReveal(mapContext, routeById.get(routeId), mapContext.routeLayers.get(routeId));
    return emitStateChange();
  }

  function showOverview() {
    cancelRouteReveal(mapContext, false);
    state.hoveredRouteId = null;
    state.selectedRouteId = null;
    state.mapMode = "overview";
    applyRecommendationOverview(mapContext, state, true);
    clearSemanticMarkers(mapContext);
    return emitStateChange();
  }

  function showSemanticRoute(routeId, includeLandmarks) {
    renderRouteSemanticMarkers(
      mapContext,
      routeById.get(routeId),
      availablePois,
      activePreferences,
      includeLandmarks,
    );
  }

  return {
    showRoutes,
    previewRoute,
    clearPreview,
    focusRoute,
    showOverview,
    getState,
  };
}

export function showSingleRoute(mapContext, route, entries, pois, selectedPreferences = []) {
  const routeId = route?.properties?.route_id;
  if (!routeId) {
    clearRouteResults(mapContext);
    return;
  }
  showRouteResults(mapContext, [route], entries, pois, routeId, selectedPreferences);
  const path = getLinePath(route);
  if (path.length < 2) {
    return;
  }

  renderRouteSemanticMarkers(mapContext, route, pois, selectedPreferences, true);
  const activeRoute = mapContext.routeLayers.get(routeId)?.main;
  const focusOverlays = [activeRoute, ...mapContext.semanticMarkerLayers].filter(Boolean);
  mapContext.amap.setFitView(focusOverlays, true, [110, 90, 180, 90], 18);
}

function renderRouteSemanticMarkers(mapContext, route, pois, selectedPreferences, includeLandmarks) {
  clearSemanticMarkers(mapContext);
  if (!route) return;
  const path = getLinePath(route);
  if (path.length < 2) return;
  const properties = route.properties || {};
  const isLoop = ["strict_loop", "loop"].includes(properties.route_shape)
    && positionsMatch(path[0], path.at(-1));
  const start = {
    role: isLoop ? "start-end" : "start",
    label: isLoop ? "A/B" : "A",
    name: properties.start_location?.name || "路线起点",
    position: locationPosition(properties.start_location, path[0]),
  };
  const end = {
    role: "end",
    label: "B",
    name: properties.end_location?.name || "路线终点",
    position: locationPosition(properties.end_location, path.at(-1)),
  };
  const landmarks = includeLandmarks
    ? routeSemanticWaypoints(properties, {
        pois,
        selectedPreferences,
        requireCoordinates: true,
      }).map((point) => ({
        role: "landmark",
        label: point.poiType ? poiMarkerLabel({ poi_type: point.poiType }) : "途经",
        name: point.name,
        position: point.position,
      }))
    : [];
  const specs = isLoop ? [start, ...landmarks] : [start, ...landmarks, end];
  mapContext.semanticMarkerLayers = specs.map((spec) => {
    const marker = createRouteMarker(mapContext, spec);
    mapContext.amap.add(marker);
    return marker;
  });
}

function clearSemanticMarkers(mapContext) {
  const markers = mapContext.semanticMarkerLayers || [];
  if (markers.length) mapContext.amap.remove(markers);
  mapContext.semanticMarkerLayers = [];
}

function startRouteReveal(mapContext, route, sourceLayers) {
  const path = getLinePath(route);
  const motion = routeRevealMotion(mapContext);
  if (path.length < 2 || !sourceLayers || motion.prefersReducedMotion || !motion.requestFrame) {
    return;
  }

  const properties = route.properties || {};
  const style = routeStyle(properties.route_mode);
  const startPath = [path[0], path[0]];
  const sharedExtData = { routeId: properties.route_id, routeMode: properties.route_mode };
  const halo = new mapContext.AMap.Polyline({
    path: startPath,
    strokeColor: "#ffffff",
    strokeWeight: style.weight + 9,
    strokeOpacity: 0.9,
    lineJoin: "round",
    lineCap: "round",
    showDir: false,
    zIndex: 113,
    extData: { ...sharedExtData, layerRole: "reveal-halo" },
  });
  const main = new mapContext.AMap.Polyline({
    path: startPath,
    strokeColor: style.color,
    strokeWeight: style.weight + 3,
    strokeOpacity: 1,
    lineJoin: "round",
    lineCap: "round",
    showDir: true,
    zIndex: 114,
    extData: { ...sharedExtData, layerRole: "reveal-main" },
  });
  mapContext.amap.add(halo);
  mapContext.amap.add(main);
  sourceLayers.halo.setOptions({ strokeOpacity: 0 });
  sourceLayers.main.setOptions({ strokeOpacity: 0 });

  const metrics = routePathMetrics(path);
  const animation = {
    frameId: null,
    startedAt: null,
    layers: [halo, main],
    sourceLayers,
  };
  mapContext.routeRevealAnimation = animation;

  const advance = (timestamp) => {
    if (mapContext.routeRevealAnimation !== animation) return;
    if (animation.startedAt === null) animation.startedAt = timestamp;
    const elapsed = Math.max(0, timestamp - animation.startedAt);
    const progress = Math.min(1, elapsed / ROUTE_REVEAL_DURATION_MS);
    const revealedPath = routePathAtProgress(path, metrics, smoothProgress(progress));
    setOverlayPath(halo, revealedPath);
    setOverlayPath(main, revealedPath);
    if (progress >= 1) {
      finishRouteReveal(mapContext, animation);
      return;
    }
    animation.frameId = motion.requestFrame(advance);
  };
  animation.frameId = motion.requestFrame(advance);
}

function finishRouteReveal(mapContext, animation) {
  if (mapContext.routeRevealAnimation !== animation) return;
  removeRevealLayers(mapContext, animation.layers);
  setRouteLayerState(animation.sourceLayers, "sporting");
  mapContext.routeRevealAnimation = null;
}

function cancelRouteReveal(mapContext, restoreSource = true) {
  const animation = mapContext.routeRevealAnimation;
  if (!animation) return;
  const motion = routeRevealMotion(mapContext);
  if (animation.frameId !== null && motion.cancelFrame) {
    motion.cancelFrame(animation.frameId);
  }
  removeRevealLayers(mapContext, animation.layers);
  if (restoreSource) setRouteLayerState(animation.sourceLayers, "sporting");
  mapContext.routeRevealAnimation = null;
}

function removeRevealLayers(mapContext, layers) {
  layers.forEach((layer) => mapContext.amap.remove(layer));
}

function routeRevealMotion(mapContext) {
  const configured = mapContext.routeRevealMotion;
  return {
    prefersReducedMotion: configured?.prefersReducedMotion
      ?? globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches
      ?? false,
    requestFrame: configured?.requestFrame
      ?? globalThis.requestAnimationFrame?.bind(globalThis)
      ?? null,
    cancelFrame: configured?.cancelFrame
      ?? globalThis.cancelAnimationFrame?.bind(globalThis)
      ?? null,
  };
}

function routePathMetrics(path) {
  const cumulative = [0];
  for (let index = 1; index < path.length; index += 1) {
    cumulative.push(cumulative.at(-1) + coordinateDistance(path[index - 1], path[index]));
  }
  return { cumulative, total: cumulative.at(-1) };
}

function routePathAtProgress(path, metrics, progress) {
  if (progress <= 0 || metrics.total <= 0) return [path[0], path[0]];
  if (progress >= 1) return [...path];
  const target = metrics.total * progress;
  let endIndex = 1;
  while (endIndex < metrics.cumulative.length && metrics.cumulative[endIndex] < target) {
    endIndex += 1;
  }
  const segmentStart = metrics.cumulative[endIndex - 1];
  const segmentLength = metrics.cumulative[endIndex] - segmentStart;
  const segmentProgress = segmentLength > 0 ? (target - segmentStart) / segmentLength : 1;
  const start = path[endIndex - 1];
  const end = path[endIndex];
  const head = [
    start[0] + (end[0] - start[0]) * segmentProgress,
    start[1] + (end[1] - start[1]) * segmentProgress,
  ];
  return [...path.slice(0, endIndex), head];
}

function coordinateDistance(left, right) {
  const meanLatitude = ((left[1] + right[1]) / 2) * Math.PI / 180;
  const longitude = (right[0] - left[0]) * Math.cos(meanLatitude);
  const latitude = right[1] - left[1];
  return Math.hypot(longitude, latitude);
}

function smoothProgress(progress) {
  return progress * progress * (3 - 2 * progress);
}

function setOverlayPath(overlay, path) {
  if (typeof overlay.setPath === "function") {
    overlay.setPath(path);
    return;
  }
  overlay.setOptions({ path });
}

function positionsMatch(left, right) {
  return Array.isArray(left) && Array.isArray(right)
    && Number(left[0]) === Number(right[0])
    && Number(left[1]) === Number(right[1]);
}

export function poiMarkerLabel(properties) {
  const labels = {
    coffee: "咖啡",
    toilet: "厕所",
    convenience: "补给",
  };
  if (properties?.poi_type !== "park_gate") {
    return labels[properties?.poi_type] || "途经点";
  }
  if (properties.route_relation !== "nearby") {
    return "公园入口";
  }
  const distance = Number(properties.distance_m ?? properties.distance_to_route_m);
  return Number.isFinite(distance) ? `邻近公园·约${Math.round(distance)}米` : "邻近公园";
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
    offset: new mapContext.AMap.Pixel(0, spec.role === "landmark" ? -60 : -4),
    zIndex: spec.role === "landmark" ? 120 : 130,
    extData: { role: spec.role, name: spec.name },
  });
}

function createRoutePreviewMarker(mapContext, route, position, onSelectRoute, onPreviewRoute) {
  const model = routePreviewCardModel(route);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "amap-route-option";
  button.dataset.routeId = model.routeId;
  button.title = model.fullName;
  button.setAttribute("aria-label", model.ariaLabel);

  const name = document.createElement("span");
  name.className = "amap-route-option__name";
  name.textContent = model.shortName;
  const distance = document.createElement("span");
  distance.className = "amap-route-option__distance";
  distance.textContent = model.distanceText;
  button.append(name, distance);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onSelectRoute(model.routeId);
  });
  button.addEventListener("mouseenter", () => onPreviewRoute(model.routeId));
  button.addEventListener("mouseleave", () => onPreviewRoute(null));
  button.addEventListener("focus", () => onPreviewRoute(model.routeId));
  button.addEventListener("blur", () => onPreviewRoute(null));

  const marker = new mapContext.AMap.Marker({
    position,
    content: button,
    anchor: "bottom-center",
    offset: new mapContext.AMap.Pixel(0, -8),
    zIndex: 92,
    extData: { routeId: model.routeId, layerRole: "preview-option" },
  });
  marker.__routeId = model.routeId;
  marker.__routePreviewContent = button;
  return marker;
}

function applyRoutePreviewOffsets(mapContext) {
  const zoom = Number(mapContext.amap.getZoom?.() || 13);
  for (const { marker, index, count } of mapContext.routePreviewMarkers || []) {
    const { x, y } = previewMarkerOffset(index, count, zoom);
    marker.setOffset(new mapContext.AMap.Pixel(x, y));
  }
}

export function highlightRoute(mapContext, selectedRouteId) {
  for (const [routeId, layers] of mapContext.routeLayers.entries()) {
    setRouteLayerState(layers, routeId === selectedRouteId ? "active" : "inactive");
  }
}

export function focusSportRoute(mapContext, selectedRouteId) {
  invalidateNavigationPlan(mapContext);
  clearNavigationService(mapContext);
  clearInlineNavigation(mapContext);
  clearNavigationPoints(mapContext);
  for (const [routeId, layers] of mapContext.routeLayers.entries()) {
    setRouteLayerState(layers, routeId === selectedRouteId ? "sporting" : "muted");
  }
  mapContext.navigation.state = "sporting";
}

export function clearRouteResults(mapContext) {
  cancelRouteReveal(mapContext, false);
  if (mapContext.navigation) {
    invalidateNavigationPlan(mapContext);
    clearNavigationService(mapContext);
    clearNavigationPoints(mapContext);
    if (mapContext.navigation.state !== "idle") {
      mapContext.navigation.state = "editing";
    }
  }
  const routeOverlays = [...mapContext.routeLayers.values()].flatMap(({ halo, main }) => [halo, main]);
  const previewLayers = mapContext.routePreviewLayers || [];
  const previewMarkers = (mapContext.routePreviewMarkers || []).map(({ marker }) => marker);
  const semanticMarkers = mapContext.semanticMarkerLayers || [];
  const overlays = [...routeOverlays, ...previewLayers, ...previewMarkers, ...mapContext.entryLayers, ...mapContext.poiLayers, ...semanticMarkers];
  if (overlays.length) {
    mapContext.amap.remove(overlays);
  }
  if (mapContext.routePreviewZoomHandler) {
    mapContext.amap.off("zoomend", mapContext.routePreviewZoomHandler);
  }
  mapContext.routeLayers.clear();
  mapContext.routePreviewLayers = [];
  mapContext.routePreviewMarkers = [];
  mapContext.routePreviewZoomHandler = null;
  mapContext.entryLayers = [];
  mapContext.poiLayers = [];
  mapContext.semanticMarkerLayers = [];
  resetRecommendationMapState(mapContext.recommendationMapState);
}

export function highlightRoutePreview(mapContext, routeId = null) {
  const activeRouteId = String(routeId || "");
  for (const line of mapContext.routePreviewLayers || []) {
    const active = line.__routeId === activeRouteId;
    const muted = Boolean(activeRouteId) && !active;
    setPreviewLineOptions(line, {
      strokeWeight: active ? 6 : muted ? 3 : 4,
      strokeOpacity: active ? 0.9 : muted ? 0.12 : 0.34,
      zIndex: active ? 90 : muted ? 60 : 64,
    });
  }
  for (const preview of mapContext.routePreviewMarkers || []) {
    const active = preview.routeId === activeRouteId;
    preview.content?.classList?.toggle("is-previewed", active);
    preview.content?.setAttribute("aria-current", active ? "true" : "false");
  }
}

function setPreviewLineOptions(line, options) {
  if (typeof line.setOptions === "function") {
    line.setOptions(options);
    return;
  }
  Object.assign(line.options || {}, options);
}

export function startNavigationSession(mapContext, onPick) {
  endNavigationSession(mapContext);
  mapContext.navigation.state = "editing";
  mapContext.navigation.onPick = onPick;
  const handlePickedPoint = (role, point) => {
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
  invalidateNavigationPlan(mapContext);
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
  if (!normalized) {
    throw new Error("无效导航点。");
  }
  if (role !== "origin" && !isPointInsideXuhui(mapContext, normalized)) {
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

export async function resolveUserLocation(mapContext, value) {
  const point = normalizePoint(value);
  if (point) {
    return {
      lng_gcj02: point.lng_gcj02,
      lat_gcj02: point.lat_gcj02,
      label: point.label || "已选位置",
      source: point.source || "point",
    };
  }
  const text = String(value?.text || value || "").trim();
  if (!text) {
    throw new Error("请输入上海地点或在地图选择位置。");
  }
  const lnglat = await geocodeToLngLat(mapContext, text);
  return lngLatToPoint(lnglat, text);
}

export function showUserLocation(mapContext, value) {
  const point = normalizePoint(value);
  if (!point) {
    throw new Error("无效用户位置。");
  }
  if (mapContext.userLocationMarker) {
    mapContext.amap.remove(mapContext.userLocationMarker);
  }
  const marker = new mapContext.AMap.Marker({
    position: [point.lng_gcj02, point.lat_gcj02],
    content: '<span class="amap-user-location" aria-label="已选位置"><i></i></span>',
    anchor: "center",
    offset: new mapContext.AMap.Pixel(0, 0),
    zIndex: 125,
  });
  mapContext.amap.add(marker);
  mapContext.userLocationMarker = marker;
  mapContext.amap.setZoomAndCenter?.(14, [point.lng_gcj02, point.lat_gcj02]);
  return point;
}

export function isPointInsideXuhui(mapContext, point) {
  const normalized = normalizePoint(point);
  if (!mapContext.boundaryRings.length) {
    return true;
  }
  return mapContext.boundaryRings.some((ring) => pointInRing([normalized.lng_gcj02, normalized.lat_gcj02], ring));
}

export async function planNavigation(mapContext, request) {
  const planRevision = beginNavigationPlan(mapContext);
  clearNavigationService(mapContext);
  mapContext.navigation.state = "planning";

  try {
    const origin = await resolveNavigationValue(mapContext, request.origin, "origin");
    assertCurrentNavigationPlan(mapContext, planRevision);
    const destination = await resolveNavigationValue(mapContext, request.destination, "destination");
    assertCurrentNavigationPlan(mapContext, planRevision);

    for (const [role, point] of [
      ["origin", origin],
      ["destination", destination],
    ]) {
      setNavigationPoint(mapContext, role, lngLatToPoint(point, NAVIGATION_POINT_LABELS[role]));
    }
    const mode = navigationServiceMode(request.routeMode);
    const service = navigationServiceForMode(mapContext, mode);
    mapContext.navigationService = service;
    mapContext.navigation.serviceRevision = planRevision;
    previewSportRoute(mapContext, request.routeId);

    const result = await searchNavigationPath(service, origin, destination);
    assertCurrentNavigationPlan(mapContext, planRevision);
    mapContext.navigation.state = "planned";
    const distanceText = result.distance ? `${result.distance.toFixed(0)} 米` : "距离待确认";
    const durationText = result.duration ? `${Math.round(result.duration / 60)} 分钟` : "时间待确认";
    return {
      ...result,
      routeId: request.routeId,
      routeMode: request.routeMode,
      summary: `${NAVIGATION_LABELS[request.routeMode] || "接驳导航"}：${distanceText}，约 ${durationText}。`,
    };
  } catch (error) {
    if (!isCurrentNavigationPlan(mapContext, planRevision)) {
      throw navigationPlanCancelledError();
    }
    clearNavigationService(mapContext, planRevision);
    clearNavigationPoints(mapContext);
    if (mapContext.navigation.state !== "idle") {
      mapContext.navigation.state = "editing";
    }
    throw error;
  }
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
  const route = new mapContext.AMap.Polyline({
    path: plan.path,
    strokeColor: ROUTE_STYLES.access.color,
    strokeWeight: 6,
    strokeOpacity: 1,
    lineJoin: "round",
    lineCap: "round",
    showDir: true,
    zIndex: 140,
  });
  mapContext.amap.add([halo, route]);
  mapContext.navigation.inlineLayers = { halo, route };
  mapContext.navigation.state = "previewing";
  mapContext.amap.setFitView([route], false, [110, 90, 180, 90]);
}

export function clearInlineNavigation(mapContext) {
  const layers = mapContext.navigation.inlineLayers;
  if (!layers) {
    return;
  }
  mapContext.amap.remove([layers.halo, layers.route]);
  mapContext.navigation.inlineLayers = null;
}

function clearNavigationService(mapContext, expectedRevision) {
  if (
    expectedRevision !== undefined
    && mapContext.navigation.serviceRevision !== expectedRevision
  ) {
    return;
  }
  if (mapContext.navigationService?.clear) {
    mapContext.navigationService.clear();
  }
  mapContext.navigationService = null;
  mapContext.navigation.serviceRevision = 0;
}

function beginNavigationPlan(mapContext) {
  mapContext.navigation.planRevision = Number(mapContext.navigation.planRevision || 0) + 1;
  return mapContext.navigation.planRevision;
}

function invalidateNavigationPlan(mapContext) {
  mapContext.navigation.planRevision = Number(mapContext.navigation.planRevision || 0) + 1;
}

function isCurrentNavigationPlan(mapContext, planRevision) {
  return mapContext.navigation.planRevision === planRevision;
}

function assertCurrentNavigationPlan(mapContext, planRevision) {
  if (!isCurrentNavigationPlan(mapContext, planRevision)) {
    throw navigationPlanCancelledError();
  }
}

function navigationPlanCancelledError() {
  return new Error("规划已取消，请重新规划。");
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

function resolveNavigationValue(mapContext, value, role) {
  const point = normalizePoint(value);
  if (point) {
    if (role !== "origin" && !isPointInsideXuhui(mapContext, point)) {
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
    if (role !== "origin" && !isPointInsideXuhui(mapContext, resolved)) {
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

function openRouteInfo(mapContext, layer, route) {
  const props = route.properties || {};
  const info = new mapContext.AMap.InfoWindow({
    content: `<strong>${escapeHtml(props.route_name || "候选路线")}</strong><br>${escapeHtml(props.region_zone || "徐汇区")}`,
    offset: new mapContext.AMap.Pixel(0, -8),
  });
  const path = layer.getPath();
  info.open(mapContext.amap, path[Math.floor(path.length / 2)]);
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

function createRecommendationMapState() {
  return {
    recommendedRouteIds: [],
    hoveredRouteId: null,
    selectedRouteId: null,
    mapMode: "overview",
  };
}

function ensureRecommendationMapState(mapContext) {
  mapContext.recommendationMapState ||= createRecommendationMapState();
  return mapContext.recommendationMapState;
}

function resetRecommendationMapState(state) {
  if (!state) {
    return;
  }
  state.recommendedRouteIds = [];
  state.hoveredRouteId = null;
  state.selectedRouteId = null;
  state.mapMode = "overview";
}

function recommendationMapSnapshot(state) {
  return {
    recommendedRouteIds: [...state.recommendedRouteIds],
    hoveredRouteId: state.hoveredRouteId,
    selectedRouteId: state.selectedRouteId,
    mapMode: state.mapMode,
  };
}

function hasRecommendedRoute(state, routeId) {
  return Boolean(routeId) && state.recommendedRouteIds.includes(routeId);
}

function applyRecommendationOverview(mapContext, state, fitView) {
  const routeLayers = state.recommendedRouteIds
    .map((routeId) => mapContext.routeLayers.get(routeId))
    .filter(Boolean);
  for (const layers of routeLayers) {
    setRouteLayerState(layers, "overview");
  }
  if (fitView && routeLayers.length) {
    mapContext.amap.setFitView(
      routeLayers.map(({ main }) => main),
      false,
      [72, 72, 72, 72],
      18,
    );
  }
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
