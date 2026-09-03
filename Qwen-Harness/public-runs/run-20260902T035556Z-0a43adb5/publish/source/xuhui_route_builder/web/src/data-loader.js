/**
 * data-loader.js
 * 数据加载器：从 ../data/web/ 读取 route_catalog.json、xuhui_routes.geojson、
 * environment_dashboard.json 和 research_harness_latest.json。
 * 文件缺失时不阻塞页面，加载失败记录控制台警告，返回类型化数据对象。
 */

const DATA_BASE = '../data/web/';

/**
 * @typedef {Object} RouteEntry
 * @property {string} route_id
 * @property {string} route_name
 * @property {string} route_mode
 * @property {string} validation_status
 * @property {string} geometry_status
 */

/**
 * @typedef {Object} EnvironmentDashboard
 * @property {Object} metadata
 * @property {Object} current
 * @property {Object} forecast
 * @property {Object} routes
 */

/**
 * @typedef {Object} ResearchPayload
 * @property {string} [run_id]
 * @property {Object} [research_question]
 * @property {Object} [hypothesis]
 * @property {Object} [selected_route]
 * @property {Array} [baselines]
 * @property {Array} [metrics]
 * @property {Array} [timeline]
 * @property {Array} [limitations]
 */

/**
 * @typedef {Object} LoadedData
 * @property {RouteEntry[]} routeCatalog - 路线目录数组，加载失败时为空数组
 * @property {Object|null} routeGeoJSON - GeoJSON FeatureCollection，加载失败时为 null
 * @property {EnvironmentDashboard|null} environmentDashboard - 环境面板数据，加载失败时为 null
 * @property {ResearchPayload|null} researchPayload - 研究面板数据，加载失败或不存在时为 null
 * @property {string[]} errors - 加载过程中遇到的错误信息列表
 */

/**
 * 安全地获取并解析 JSON 文件。
 * 文件不存在或解析失败时返回 null 并记录警告。
 * @param {string} url - 相对路径或完整 URL
 * @param {string} label - 用于日志的标签
 * @returns {Promise<*>} 解析后的 JSON 或 null
 */
async function fetchJSON(url, label) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      if (response.status === 404) {
        console.warn(`[data-loader] ${label}: 文件不存在 (${response.status}) - ${url}`);
      } else {
        console.warn(`[data-loader] ${label}: 请求失败 (${response.status}) - ${url}`);
      }
      return null;
    }
    const data = await response.json();
    return data;
  } catch (err) {
    console.warn(`[data-loader] ${label}: 加载或解析失败 - ${url}`, err.message || err);
    return null;
  }
}

/**
 * 验证路线目录数据的基本结构。
 * @param {*} data - 待验证的数据
 * @returns {{ valid: boolean, routes: RouteEntry[], warnings: string[] }}
 */
function validateRouteCatalog(data) {
  const warnings = [];
  if (!Array.isArray(data)) {
    warnings.push('route_catalog.json 顶层不是数组');
    return { valid: false, routes: [], warnings };
  }
  if (data.length === 0) {
    warnings.push('route_catalog.json 为空数组');
    return { valid: false, routes: [], warnings };
  }
  const requiredFields = ['route_id', 'route_name', 'route_mode', 'validation_status', 'geometry_status'];
  const validRoutes = [];
  for (let i = 0; i < data.length; i++) {
    const item = data[i];
    const missing = requiredFields.filter(f => !(f in item));
    if (missing.length > 0) {
      warnings.push(`route_catalog.json 第 ${i} 项缺少字段: ${missing.join(', ')}`);
    } else {
      validRoutes.push(item);
    }
  }
  if (validRoutes.length === 0) {
    warnings.push('route_catalog.json 无有效路线条目');
    return { valid: false, routes: [], warnings };
  }
  return { valid: true, routes: validRoutes, warnings };
}

/**
 * 验证 GeoJSON FeatureCollection 的基本结构。
 * @param {*} data - 待验证的数据
 * @returns {{ valid: boolean, geojson: Object|null, warnings: string[] }}
 */
function validateRouteGeoJSON(data) {
  const warnings = [];
  if (!data || typeof data !== 'object') {
    warnings.push('xuhui_routes.geojson 数据无效');
    return { valid: false, geojson: null, warnings };
  }
  if (data.type !== 'FeatureCollection') {
    warnings.push('xuhui_routes.geojson type 不是 FeatureCollection');
    return { valid: false, geojson: null, warnings };
  }
  if (!Array.isArray(data.features)) {
    warnings.push('xuhui_routes.geojson features 不是数组');
    return { valid: false, geojson: null, warnings };
  }
  if (data.features.length === 0) {
    warnings.push('xuhui_routes.geojson features 为空');
    return { valid: false, geojson: null, warnings };
  }
  // 检查每个 feature 是否有 route_id 和有效几何
  const validFeatures = data.features.filter(f => {
    if (!f || !f.properties || !f.properties.route_id) {
      return false;
    }
    if (!f.geometry || !f.geometry.type || !Array.isArray(f.geometry.coordinates)) {
      return false;
    }
    return true;
  });
  if (validFeatures.length < data.features.length) {
    warnings.push(`xuhui_routes.geojson 有 ${data.features.length - validFeatures.length} 个无效 Feature`);
  }
  if (validFeatures.length === 0) {
    warnings.push('xuhui_routes.geojson 无有效 Feature');
    return { valid: false, geojson: null, warnings };
  }
  return { valid: true, geojson: data, warnings };
}

/**
 * 验证环境面板数据的基本结构。
 * @param {*} data - 待验证的数据
 * @returns {{ valid: boolean, dashboard: Object|null, warnings: string[] }}
 */
function validateEnvironmentDashboard(data) {
  const warnings = [];
  if (!data || typeof data !== 'object') {
    warnings.push('environment_dashboard.json 数据无效');
    return { valid: false, dashboard: null, warnings };
  }
  const requiredKeys = ['metadata', 'current', 'forecast', 'routes'];
  const missing = requiredKeys.filter(k => !(k in data));
  if (missing.length > 0) {
    warnings.push(`environment_dashboard.json 缺少顶层键: ${missing.join(', ')}`);
    // 部分缺失仍可使用，标记为 partial 但不完全拒绝
    if (missing.length === requiredKeys.length) {
      return { valid: false, dashboard: null, warnings };
    }
  }
  // 检查 routes.items
  if (data.routes && data.routes.items) {
    if (!Array.isArray(data.routes.items)) {
      warnings.push('environment_dashboard.json routes.items 不是数组');
    } else if (data.routes.items.length === 0) {
      warnings.push('environment_dashboard.json routes.items 为空');
    }
  } else {
    warnings.push('environment_dashboard.json 缺少 routes.items');
  }
  return { valid: true, dashboard: data, warnings };
}

/**
 * 验证研究面板 payload 的基本结构。
 * @param {*} data - 待验证的数据
 * @returns {{ valid: boolean, payload: Object|null, warnings: string[] }}
 */
function validateResearchPayload(data) {
  const warnings = [];
  if (!data || typeof data !== 'object') {
    warnings.push('research_harness_latest.json 数据无效');
    return { valid: false, payload: null, warnings };
  }
  // research payload 是可选的，结构宽松；仅做基本类型检查
  if (data.selected_route && typeof data.selected_route !== 'object') {
    warnings.push('research_harness_latest.json selected_route 不是对象');
  }
  if (data.baselines && !Array.isArray(data.baselines)) {
    warnings.push('research_harness_latest.json baselines 不是数组');
  }
  if (data.metrics && !Array.isArray(data.metrics)) {
    warnings.push('research_harness_latest.json metrics 不是数组');
  }
  if (data.timeline && !Array.isArray(data.timeline)) {
    warnings.push('research_harness_latest.json timeline 不是数组');
  }
  if (data.limitations && !Array.isArray(data.limitations)) {
    warnings.push('research_harness_latest.json limitations 不是数组');
  }
  return { valid: true, payload: data, warnings };
}

/**
 * 加载全部数据文件并返回类型化结果。
 * 任何文件缺失或解析失败均不阻塞页面；错误记录在 errors 数组中。
 * @returns {Promise<LoadedData>}
 */
async function loadAllData() {
  const errors = [];

  // 1. route_catalog.json
  const catalogRaw = await fetchJSON(`${DATA_BASE}route_catalog.json`, 'route_catalog');
  const catalogResult = validateRouteCatalog(catalogRaw);
  if (!catalogResult.valid) {
    errors.push(...catalogResult.warnings);
  }

  // 2. xuhui_routes.geojson
  const geojsonRaw = await fetchJSON(`${DATA_BASE}xuhui_routes.geojson`, 'xuhui_routes.geojson');
  const geojsonResult = validateRouteGeoJSON(geojsonRaw);
  if (!geojsonResult.valid) {
    errors.push(...geojsonResult.warnings);
  }

  // 3. environment_dashboard.json
  const envRaw = await fetchJSON(`${DATA_BASE}environment_dashboard.json`, 'environment_dashboard');
  const envResult = validateEnvironmentDashboard(envRaw);
  if (!envResult.valid) {
    errors.push(...envResult.warnings);
  }

  // 4. research_harness_latest.json（可选）
  const researchRaw = await fetchJSON(`${DATA_BASE}research_harness_latest.json`, 'research_harness_latest');
  let researchPayload = null;
  if (researchRaw !== null) {
    const researchResult = validateResearchPayload(researchRaw);
    if (researchResult.valid) {
      researchPayload = researchResult.payload;
    } else {
      errors.push(...researchResult.warnings);
    }
  }

  return {
    routeCatalog: catalogResult.routes,
    routeGeoJSON: geojsonResult.geojson,
    environmentDashboard: envResult.dashboard,
    researchPayload,
    errors
  };
}

export { DATA_BASE, fetchJSON, validateRouteCatalog, validateRouteGeoJSON, validateEnvironmentDashboard, validateResearchPayload, loadAllData };
