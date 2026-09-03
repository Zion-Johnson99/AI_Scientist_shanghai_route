/**
 * map.js — Leaflet 地图初始化、路线图层绘制、选中高亮
 *
 * 坐标系声明：
 *   路线 GeoJSON 坐标为 WGS84 (EPSG:4326)。
 *   Leaflet 默认使用 WGS84 输入，底图瓦片为 Web Mercator (EPSG:3857) 投影，
 *   Leaflet 内部自动完成投影变换，无需手动转换。
 *   若数据源为 GCJ-02，必须先转换为 WGS84 再传入本模块。
 */

/** 默认地图中心：上海徐汇区 */
const DEFAULT_CENTER = [31.1885, 121.4365];
const DEFAULT_ZOOM = 13;

/** 路线模式颜色映射 */
const MODE_COLORS = {
  walk: '#2196F3',
  run: '#4CAF50',
  bike: '#FF9800',
};

/** 选中路线高亮样式 */
const SELECTED_STYLE = {
  weight: 6,
  opacity: 1,
  dashArray: null,
};

/** 默认路线样式 */
const DEFAULT_STYLE = {
  weight: 3,
  opacity: 0.7,
  dashArray: null,
};

/**
 * 初始化地图实例。
 * @param {string} containerId - 地图容器 DOM 元素 ID
 * @param {object} [options] - 可选配置
 * @param {number[]} [options.center] - 初始中心 [lat, lng]
 * @param {number} [options.zoom] - 初始缩放级别
 * @returns {L.Map} Leaflet 地图实例
 */
export function initMap(containerId, options = {}) {
  const center = options.center || DEFAULT_CENTER;
  const zoom = options.zoom || DEFAULT_ZOOM;

  const map = L.map(containerId, {
    center: center,
    zoom: zoom,
    zoomControl: true,
    attributionControl: true,
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);

  return map;
}

/**
 * 获取路线模式对应的颜色。
 * @param {string} mode - 路线模式 (walk|run|bike)
 * @returns {string} 颜色值
 */
export function getModeColor(mode) {
  return MODE_COLORS[mode] || '#9E9E9E';
}

/**
 * 创建路线图层组。
 * @param {L.Map} map - Leaflet 地图实例
 * @param {object} geojsonData - GeoJSON FeatureCollection
 * @param {object} [callbacks] - 事件回调
 * @param {function} [callbacks.onRouteClick] - 路线点击回调 (routeId, feature)
 * @returns {{ layerGroup: L.LayerGroup, layersById: Map<string, L.Path> }}
 */
export function createRouteLayers(map, geojsonData, callbacks = {}) {
  const layersById = new Map();
  const layerGroup = L.layerGroup().addTo(map);

  if (!geojsonData || !geojsonData.features || !Array.isArray(geojsonData.features)) {
    console.warn('[map.js] GeoJSON data is missing or invalid; no route layers created.');
    return { layerGroup, layersById };
  }

  for (const feature of geojsonData.features) {
    const routeId = feature.properties && feature.properties.route_id;
    if (!routeId) {
      console.warn('[map.js] Feature missing route_id, skipping.');
      continue;
    }

    const mode = feature.properties.route_mode || 'walk';
    const color = getModeColor(mode);

    const layer = L.geoJSON(feature, {
      style: {
        color: color,
        weight: DEFAULT_STYLE.weight,
        opacity: DEFAULT_STYLE.opacity,
        dashArray: DEFAULT_STYLE.dashArray,
      },
      onEachFeature: function (feat, lyr) {
        lyr.on('click', function () {
          if (typeof callbacks.onRouteClick === 'function') {
            callbacks.onRouteClick(routeId, feat);
          }
        });

        const name = feat.properties.route_name || routeId;
        lyr.bindTooltip(name, { sticky: true });
      },
    });

    layer.addTo(layerGroup);
    layersById.set(routeId, layer);
  }

  return { layerGroup, layersById };
}

/**
 * 高亮选中路线，取消之前的高亮。
 * @param {Map<string, L.Path>} layersById - route_id → layer 映射
 * @param {string|null} selectedRouteId - 当前选中的路线 ID；null 表示取消所有高亮
 * @param {string|null} [previousRouteId] - 之前选中的路线 ID
 */
export function highlightRoute(layersById, selectedRouteId, previousRouteId) {
  // 取消之前的高亮
  if (previousRouteId && layersById.has(previousRouteId)) {
    const prevLayer = layersById.get(previousRouteId);
    resetLayerStyle(prevLayer);
  }

  // 应用新高亮
  if (selectedRouteId && layersById.has(selectedRouteId)) {
    const layer = layersById.get(selectedRouteId);
    applySelectedStyle(layer);
  }
}

/**
 * 将图层恢复为默认样式。
 * @param {L.GeoJSON|L.Path} layer
 */
function resetLayerStyle(layer) {
  if (layer && typeof layer.setStyle === 'function') {
    layer.setStyle({
      weight: DEFAULT_STYLE.weight,
      opacity: DEFAULT_STYLE.opacity,
      dashArray: DEFAULT_STYLE.dashArray,
    });
  } else if (layer && typeof layer.eachLayer === 'function') {
    layer.eachLayer(function (subLayer) {
      if (typeof subLayer.setStyle === 'function') {
        subLayer.setStyle({
          weight: DEFAULT_STYLE.weight,
          opacity: DEFAULT_STYLE.opacity,
          dashArray: DEFAULT_STYLE.dashArray,
        });
      }
    });
  }
}

/**
 * 将图层应用选中高亮样式。
 * @param {L.GeoJSON|L.Path} layer
 */
function applySelectedStyle(layer) {
  if (layer && typeof layer.setStyle === 'function') {
    layer.setStyle({
      weight: SELECTED_STYLE.weight,
      opacity: SELECTED_STYLE.opacity,
      dashArray: SELECTED_STYLE.dashArray,
    });
    if (typeof layer.bringToFront === 'function') {
      layer.bringToFront();
    }
  } else if (layer && typeof layer.eachLayer === 'function') {
    layer.eachLayer(function (subLayer) {
      if (typeof subLayer.setStyle === 'function') {
        subLayer.setStyle({
          weight: SELECTED_STYLE.weight,
          opacity: SELECTED_STYLE.opacity,
          dashArray: SELECTED_STYLE.dashArray,
        });
      }
      if (typeof subLayer.bringToFront === 'function') {
        subLayer.bringToFront();
      }
    });
  }
}

/**
 * 缩放到指定路线的边界。
 * @param {L.Map} map - Leaflet 地图实例
 * @param {Map<string, L.Path>} layersById - route_id → layer 映射
 * @param {string} routeId - 目标路线 ID
 */
export function fitToRoute(map, layersById, routeId) {
  if (!layersById.has(routeId)) {
    console.warn('[map.js] Route not found for fit: ' + routeId);
    return;
  }
  const layer = layersById.get(routeId);
  if (layer && typeof layer.getBounds === 'function') {
    map.fitBounds(layer.getBounds(), { padding: [40, 40] });
  } else if (layer && typeof layer.eachLayer === 'function') {
    const group = L.featureGroup();
    layer.eachLayer(function (subLayer) {
      group.addLayer(subLayer);
    });
    if (group.getBounds && group.getBounds().isValid()) {
      map.fitBounds(group.getBounds(), { padding: [40, 40] });
    }
  }
}

/**
 * 按模式过滤路线图层可见性。
 * @param {Map<string, L.Path>} layersById - route_id → layer 映射
 * @param {object} routeCatalog - 路线目录数组（含 route_id 与 route_mode）
 * @param {string[]} visibleModes - 需要显示的模式列表，如 ['walk','run','bike']
 */
export function filterByMode(layersById, routeCatalog, visibleModes) {
  if (!Array.isArray(routeCatalog)) {
    return;
  }
  const visibleSet = new Set(visibleModes);

  for (const entry of routeCatalog) {
    const routeId = entry.route_id;
    const mode = entry.route_mode;
    const layer = layersById.get(routeId);
    if (!layer) {
      continue;
    }
    if (visibleSet.has(mode)) {
      if (typeof layer.addTo === 'function' && !layer._map) {
        // 如果图层不在地图上则不操作（由 layerGroup 管理）
      }
      if (typeof layer.setOpacity === 'function') {
        layer.setOpacity(DEFAULT_STYLE.opacity);
      }
      if (layer._path) {
        layer._path.style.display = '';
      }
    } else {
      if (typeof layer.setOpacity === 'function') {
        layer.setOpacity(0);
      }
      if (layer._path) {
        layer._path.style.display = 'none';
      }
    }
  }
}

/**
 * 按模式过滤路线图层可见性（基于 layerGroup 管理）。
 * 更可靠的方式：移除并重新添加图层。
 * @param {L.LayerGroup} layerGroup - 路线图层组
 * @param {Map<string, L.Path>} layersById - route_id → layer 映射
 * @param {object[]} routeCatalog - 路线目录数组
 * @param {string[]} visibleModes - 需要显示的模式列表
 */
export function filterByModeGroup(layerGroup, layersById, routeCatalog, visibleModes) {
  if (!Array.isArray(routeCatalog)) {
    return;
  }
  const visibleSet = new Set(visibleModes);

  layerGroup.clearLayers();

  for (const entry of routeCatalog) {
    const routeId = entry.route_id;
    const mode = entry.route_mode;
    if (!visibleSet.has(mode)) {
      continue;
    }
    const layer = layersById.get(routeId);
    if (layer) {
      layerGroup.addLayer(layer);
    }
  }
}
