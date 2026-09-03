/**
 * main.js — 网页主逻辑：初始化地图、加载数据、绑定事件、协调各 UI 模块
 */

import { loadAllData } from './data-loader.js';
import { initMap, createRouteLayers, highlightRoute } from './map.js';
import './recommendation-ui.js';
import { renderResearchPanel } from './research-harness-ui.js';

const MODE_LABELS = {
  walk: '步行',
  run: '跑步',
  bike: '骑行'
};

let appState = {
  routes: [],
  geojson: null,
  environment: null,
  filteredRoutes: [],
  selectedRouteId: null,
  activeModeFilter: null
};

let mapInstance = null;
let layersById = null;

/**
 * 初始化应用
 */
async function init() {
  const data = await loadAllData();

  appState.routes = data.routeCatalog || [];
  appState.geojson = data.routeGeoJSON || null;
  appState.environment = data.environmentDashboard || null;
  appState.filteredRoutes = [...appState.routes];

  mapInstance = initMap('map');
  const routeLayers = createRouteLayers(mapInstance, appState.geojson);
  layersById = routeLayers.layersById;
  layersById.__map = mapInstance;

  renderRouteList();
  bindFilterControls();

  const recUI = window.RecommendationUI;
  if (recUI && typeof recUI.init === 'function') {
    const recommendationContainer = document.getElementById('recommendation-result');
    recUI.init({
      container: recommendationContainer,
      onRouteSelect: selectRoute
    });
    recommendationContainer.hidden = false;
    bindRecommendationControl(recUI);
  }

  if (data.researchPayload) {
    const researchSection = document.getElementById('research-section');
    if (researchSection) {
      researchSection.hidden = false;
    }
    const researchContainer = document.getElementById('research-panel');
    if (researchContainer) {
      renderResearchPanel(researchContainer, data.researchPayload, {
        routeCatalog: appState.routes,
        onSelectRoute: selectRoute
      });
    }
  }
}

/**
 * 绑定本地评价 API，并把服务响应转换为推荐面板契约。
 */
function bindRecommendationControl(recUI) {
  const button = document.getElementById('recommend-btn');
  if (!button) return;

  button.addEventListener('click', async () => {
    const selectedRoute = appState.routes.find(
      route => route.route_id === appState.selectedRouteId
    );
    const routeMode = selectedRoute?.route_mode || appState.activeModeFilter || 'walk';
    const targetDistance = selectedRoute?.distance_m || 3000;

    button.disabled = true;
    recUI.renderLoading();
    try {
      const response = await fetch(
        'http://127.0.0.1:8124/api/v1/recommendations',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            route_mode: routeMode,
            goal: 'balanced',
            target_distance_m: targetDistance,
            sensitivities: [],
            interests: []
          })
        }
      );
      if (!response.ok) {
        throw new Error(`推荐服务返回 HTTP ${response.status}`);
      }
      const payload = await response.json();
      const recommendations = (payload.recommendations || []).map(route => ({
        ...route,
        scores: {
          environment_health: route.environment_health,
          sport_match: route.sport_match,
          access_convenience: route.access_convenience,
          route_quality: route.route_quality,
          interest_service: route.interest_service
        }
      }));
      recUI.renderResult({
        risk: payload.risk_assessment,
        candidates: recommendations,
        primary: recommendations[0] || null,
        alternatives: recommendations.slice(1, 4),
        explanation: recommendations.length
          ? '结果按环境健康、运动匹配、接驳便利、路线质量和兴趣服务综合排序。'
          : null
      });
    } catch (error) {
      recUI.renderError(error instanceof Error ? error.message : '推荐请求失败');
    } finally {
      button.disabled = false;
    }
  });
}

/**
 * 渲染路线列表
 */
function renderRouteList() {
  const container = document.getElementById('route-list');
  if (!container) return;

  container.innerHTML = '';

  if (appState.filteredRoutes.length === 0) {
    const emptyMsg = document.createElement('p');
    emptyMsg.className = 'route-list-empty';
    emptyMsg.textContent = '当前筛选条件下无路线';
    container.appendChild(emptyMsg);
    return;
  }

  appState.filteredRoutes.forEach(route => {
    const item = document.createElement('div');
    item.className = 'route-list-item';
    item.dataset.routeId = route.route_id;
    item.setAttribute('role', 'button');
    item.setAttribute('tabindex', '0');
    item.setAttribute('aria-label', `${route.route_name} (${MODE_LABELS[route.route_mode] || route.route_mode})`);

    const nameEl = document.createElement('span');
    nameEl.className = 'route-item-name';
    nameEl.textContent = route.route_name;

    const modeEl = document.createElement('span');
    modeEl.className = 'route-item-mode';
    modeEl.textContent = MODE_LABELS[route.route_mode] || route.route_mode;

    const distEl = document.createElement('span');
    distEl.className = 'route-item-distance';
    if (route.distance_m != null) {
      distEl.textContent = `${(route.distance_m / 1000).toFixed(1)} km`;
    }

    item.appendChild(nameEl);
    item.appendChild(modeEl);
    item.appendChild(distEl);

    item.addEventListener('click', () => selectRoute(route.route_id));
    item.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectRoute(route.route_id);
      }
    });

    container.appendChild(item);
  });
}

/**
 * 选中路线
 */
function selectRoute(routeId) {
  appState.selectedRouteId = routeId;

  document.querySelectorAll('.route-list-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.routeId === routeId);
  });

  if (layersById && layersById[routeId]) {
    highlightRoute(layersById, routeId);
  }

  renderRouteDetail(routeId);
}

/**
 * 渲染路线详情
 */
function renderRouteDetail(routeId) {
  const detailEl = document.getElementById('route-detail');
  if (!detailEl) return;

  detailEl.innerHTML = '';

  const route = appState.routes.find(r => r.route_id === routeId);
  if (!route) return;

  const titleEl = document.createElement('h3');
  titleEl.textContent = route.route_name;
  detailEl.appendChild(titleEl);

  const metaEl = document.createElement('p');
  metaEl.className = 'route-detail-meta';
  metaEl.textContent = `${MODE_LABELS[route.route_mode] || route.route_mode} · ${route.distance_m != null ? (route.distance_m / 1000).toFixed(1) + ' km' : '未知距离'}`;
  detailEl.appendChild(metaEl);

  if (appState.environment && appState.environment.routes && appState.environment.routes.items) {
    const envItem = appState.environment.routes.items.find(e => e.route_id === routeId);
    if (envItem) {
      const envSection = document.createElement('div');
      envSection.className = 'route-detail-env';

      const envTitle = document.createElement('h4');
      envTitle.textContent = '环境暴露';
      envSection.appendChild(envTitle);

      const envList = document.createElement('ul');
      envList.className = 'env-list';

      if (envItem.pm2_5 && envItem.pm2_5.value != null) {
        const li = document.createElement('li');
        li.textContent = `PM2.5: ${envItem.pm2_5.value} ${envItem.pm2_5.unit || 'μg/m³'}`;
        if (envItem.pm2_5.estimated) {
          const est = document.createElement('span');
          est.className = 'env-estimated';
          est.textContent = ' (估计值)';
          li.appendChild(est);
        }
        envList.appendChild(li);
      }

      if (envItem.noise && envItem.noise.value != null) {
        const li = document.createElement('li');
        li.textContent = `噪声风险: ${envItem.noise.value} ${envItem.noise.unit || ''}`;
        if (envItem.noise.estimated) {
          const est = document.createElement('span');
          est.className = 'env-estimated';
          est.textContent = ' (估计值)';
          li.appendChild(est);
        }
        envList.appendChild(li);
      }

      if (envItem.pollen_daily && envItem.pollen_daily.value != null) {
        const li = document.createElement('li');
        li.textContent = `花粉: ${envItem.pollen_daily.value} ${envItem.pollen_daily.unit || ''}`;
        if (envItem.pollen_daily.estimated) {
          const est = document.createElement('span');
          est.className = 'env-estimated';
          est.textContent = ' (估计值)';
          li.appendChild(est);
        }
        envList.appendChild(li);
      }

      envSection.appendChild(envList);
      detailEl.appendChild(envSection);
    }
  }
}

/**
 * 绑定筛选控件
 */
function bindFilterControls() {
  const modeSelect = document.getElementById('mode-filter');
  if (!modeSelect) return;

  modeSelect.addEventListener('change', () => {
    if (modeSelect.value === 'all') {
      appState.activeModeFilter = null;
    } else {
      appState.activeModeFilter = modeSelect.value;
    }
    applyFilters();
  });
}

/**
 * 应用筛选
 */
function applyFilters() {
  if (appState.activeModeFilter) {
    appState.filteredRoutes = appState.routes.filter(
      r => r.route_mode === appState.activeModeFilter
    );
  } else {
    appState.filteredRoutes = [...appState.routes];
  }
  renderRouteList();
}

/**
 * 启动
 */
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}
