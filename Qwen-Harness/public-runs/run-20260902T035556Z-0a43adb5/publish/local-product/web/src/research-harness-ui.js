/**
 * Research Harness UI Panel
 * Displays research question, hypothesis support status, baseline comparisons,
 * key metrics, and iteration timeline from research_harness_latest.json.
 * Hidden when data file is missing or invalid.
 */

const RESEARCH_DATA_URL = 'data/web/research_harness_latest.json';

/**
 * Validates the research harness payload structure.
 * @param {object} data - Parsed JSON payload
 * @returns {boolean} True if payload is valid
 */
export function validatePayload(data) {
  if (!data || typeof data !== 'object') return false;
  if (!data.research_question || typeof data.research_question !== 'string') return false;
  if (!data.hypothesis || typeof data.hypothesis !== 'object') return false;
  if (!data.hypothesis.id || typeof data.hypothesis.id !== 'string') return false;
  if (!data.hypothesis.support_status || typeof data.hypothesis.support_status !== 'string') return false;
  const validStatuses = ['supported', 'partially_supported', 'unsupported', 'inconclusive'];
  if (!validStatuses.includes(data.hypothesis.support_status)) return false;
  if (data.selected_route && data.selected_route.route_id && typeof data.selected_route.route_id !== 'string') return false;
  return true;
}

/**
 * Checks if a route_id exists in the route catalog.
 * @param {string} routeId - The route ID to check
 * @param {Array} routeCatalog - Array of route entries
 * @returns {boolean}
 */
export function routeExistsInCatalog(routeId, routeCatalog) {
  if (!Array.isArray(routeCatalog)) return false;
  return routeCatalog.some(r => r.route_id === routeId);
}

/**
 * Renders the research panel into the given container.
 * Uses textContent exclusively to prevent XSS from model-generated text.
 * @param {HTMLElement} container - The panel container element
 * @param {object} data - Validated research payload
 * @param {object} options - { routeCatalog, onSelectRoute }
 */
export function renderResearchPanel(container, data, options = {}) {
  const { routeCatalog = [], onSelectRoute = null } = options;

  container.innerHTML = '';
  container.classList.add('rh-panel', 'rh-panel--visible');
  container.setAttribute('role', 'region');
  container.setAttribute('aria-label', 'AI Scientist 实验面板');

  // Header
  const header = document.createElement('div');
  header.className = 'rh-panel__header';

  const title = document.createElement('h2');
  title.className = 'rh-panel__title';
  title.textContent = 'AI Scientist 实验';
  header.appendChild(title);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'rh-panel__close';
  closeBtn.textContent = '✕';
  closeBtn.setAttribute('aria-label', '关闭研究面板');
  closeBtn.addEventListener('click', () => {
    hideResearchPanel(container);
  });
  header.appendChild(closeBtn);
  container.appendChild(header);

  // Research question
  const questionSection = document.createElement('div');
  questionSection.className = 'rh-panel__section';
  const questionLabel = document.createElement('h3');
  questionLabel.className = 'rh-panel__section-title';
  questionLabel.textContent = '研究问题';
  questionSection.appendChild(questionLabel);
  const questionText = document.createElement('p');
  questionText.className = 'rh-panel__question';
  questionText.textContent = data.research_question;
  questionSection.appendChild(questionText);
  container.appendChild(questionSection);

  // Hypothesis & support status
  const hypothesisSection = document.createElement('div');
  hypothesisSection.className = 'rh-panel__section';
  const hypLabel = document.createElement('h3');
  hypLabel.className = 'rh-panel__section-title';
  hypLabel.textContent = '假设与支持状态';
  hypothesisSection.appendChild(hypLabel);

  const hypId = document.createElement('p');
  hypId.className = 'rh-panel__hypothesis-id';
  hypId.textContent = `假设 ID: ${data.hypothesis.id}`;
  hypothesisSection.appendChild(hypId);

  const statusBadge = document.createElement('span');
  statusBadge.className = `rh-panel__status rh-panel__status--${data.hypothesis.support_status}`;
  statusBadge.setAttribute('role', 'status');
  const statusLabels = {
    supported: '支持',
    partially_supported: '部分支持',
    unsupported: '不支持',
    inconclusive: '证据不足'
  };
  statusBadge.textContent = statusLabels[data.hypothesis.support_status] || data.hypothesis.support_status;
  hypothesisSection.appendChild(statusBadge);

  if (data.hypothesis.statement) {
    const hypStatement = document.createElement('p');
    hypStatement.className = 'rh-panel__hypothesis-statement';
    hypStatement.textContent = data.hypothesis.statement;
    hypothesisSection.appendChild(hypStatement);
  }
  container.appendChild(hypothesisSection);

  // Evidence summary
  if (data.evidence && Array.isArray(data.evidence)) {
    const evidenceSection = document.createElement('div');
    evidenceSection.className = 'rh-panel__section';
    const evLabel = document.createElement('h3');
    evLabel.className = 'rh-panel__section-title';
    evLabel.textContent = `证据与引用 (${data.evidence.length})`;
    evidenceSection.appendChild(evLabel);

    const evList = document.createElement('ul');
    evList.className = 'rh-panel__evidence-list';
    data.evidence.forEach(item => {
      const li = document.createElement('li');
      li.className = 'rh-panel__evidence-item';
      const text = document.createElement('span');
      text.textContent = item.claim || item.title || item.source_id || '未命名证据';
      li.appendChild(text);
      if (item.url) {
        const link = document.createElement('a');
        link.href = item.url;
        link.textContent = ' [来源]';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        li.appendChild(link);
      }
      evList.appendChild(li);
    });
    evidenceSection.appendChild(evList);
    container.appendChild(evidenceSection);
  }

  // Baseline comparison
  if (data.baselines && Array.isArray(data.baselines)) {
    const baselineSection = document.createElement('div');
    baselineSection.className = 'rh-panel__section';
    const blLabel = document.createElement('h3');
    blLabel.className = 'rh-panel__section-title';
    blLabel.textContent = '基线对比';
    baselineSection.appendChild(blLabel);

    const table = document.createElement('table');
    table.className = 'rh-panel__baseline-table';
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    ['基线', '指标', '值'].forEach(text => {
      const th = document.createElement('th');
      th.textContent = text;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    data.baselines.forEach(bl => {
      const row = document.createElement('tr');
      const nameCell = document.createElement('td');
      nameCell.textContent = bl.name || bl.baseline_id || '';
      row.appendChild(nameCell);
      const metricCell = document.createElement('td');
      metricCell.textContent = bl.metric || '';
      row.appendChild(metricCell);
      const valueCell = document.createElement('td');
      valueCell.textContent = bl.value != null ? String(bl.value) : '—';
      row.appendChild(valueCell);
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    baselineSection.appendChild(table);
    container.appendChild(baselineSection);
  }

  // Key metrics
  if (data.metrics && Array.isArray(data.metrics)) {
    const metricsSection = document.createElement('div');
    metricsSection.className = 'rh-panel__section';
    const mLabel = document.createElement('h3');
    mLabel.className = 'rh-panel__section-title';
    mLabel.textContent = '关键指标';
    metricsSection.appendChild(mLabel);

    const metricsGrid = document.createElement('div');
    metricsGrid.className = 'rh-panel__metrics-grid';
    data.metrics.forEach(m => {
      const card = document.createElement('div');
      card.className = 'rh-panel__metric-card';
      const name = document.createElement('span');
      name.className = 'rh-panel__metric-name';
      name.textContent = m.name || m.metric_id || '';
      card.appendChild(name);
      const value = document.createElement('span');
      value.className = 'rh-panel__metric-value';
      value.textContent = m.value != null ? String(m.value) : '—';
      card.appendChild(value);
      if (m.primary) {
        const badge = document.createElement('span');
        badge.className = 'rh-panel__metric-primary';
        badge.textContent = '主要';
        card.appendChild(badge);
      }
      metricsGrid.appendChild(card);
    });
    metricsSection.appendChild(metricsGrid);
    container.appendChild(metricsSection);
  }

  // Selected route (constraint-optimal in current candidate set)
  if (data.selected_route && data.selected_route.route_id) {
    const routeSection = document.createElement('div');
    routeSection.className = 'rh-panel__section';
    const rLabel = document.createElement('h3');
    rLabel.className = 'rh-panel__section-title';
    rLabel.textContent = '候选集约束最优路线';
    routeSection.appendChild(rLabel);

    const routeId = data.selected_route.route_id;
    const exists = routeExistsInCatalog(routeId, routeCatalog);

    if (exists) {
      const routeBtn = document.createElement('button');
      routeBtn.className = 'rh-panel__route-link';
      routeBtn.textContent = data.selected_route.route_name || routeId;
      routeBtn.setAttribute('aria-label', `在地图上查看路线 ${routeId}`);
      routeBtn.addEventListener('click', () => {
        if (typeof onSelectRoute === 'function') {
          onSelectRoute(routeId);
        }
      });
      routeSection.appendChild(routeBtn);
    } else {
      const degraded = document.createElement('p');
      degraded.className = 'rh-panel__route-degraded';
      degraded.textContent = `路线 ${routeId} 不在当前目录中，无法联动地图。`;
      routeSection.appendChild(degraded);
    }

    if (data.selected_route.reason) {
      const reason = document.createElement('p');
      reason.className = 'rh-panel__route-reason';
      reason.textContent = data.selected_route.reason;
      routeSection.appendChild(reason);
    }
    container.appendChild(routeSection);
  }

  // Iteration timeline
  if (data.timeline && Array.isArray(data.timeline)) {
    const timelineSection = document.createElement('div');
    timelineSection.className = 'rh-panel__section';
    const tLabel = document.createElement('h3');
    tLabel.className = 'rh-panel__section-title';
    tLabel.textContent = '迭代时间线';
    timelineSection.appendChild(tLabel);

    const timelineList = document.createElement('ol');
    timelineList.className = 'rh-panel__timeline';
    data.timeline.forEach(entry => {
      const li = document.createElement('li');
      li.className = 'rh-panel__timeline-item';
      const time = document.createElement('time');
      time.textContent = entry.timestamp || '';
      if (entry.timestamp) {
        time.setAttribute('datetime', entry.timestamp);
      }
      li.appendChild(time);
      const desc = document.createElement('span');
      desc.textContent = entry.description || entry.stage || '';
      li.appendChild(desc);
      timelineList.appendChild(li);
    });
    timelineSection.appendChild(timelineList);
    container.appendChild(timelineSection);
  }

  // Data limitations & proxy variables
  if (data.limitations && Array.isArray(data.limitations)) {
    const limitSection = document.createElement('div');
    limitSection.className = 'rh-panel__section rh-panel__section--limitations';
    const lLabel = document.createElement('h3');
    lLabel.className = 'rh-panel__section-title';
    lLabel.textContent = '数据限制与代理变量';
    limitSection.appendChild(lLabel);

    const limitList = document.createElement('ul');
    limitList.className = 'rh-panel__limitations-list';
    data.limitations.forEach(item => {
      const li = document.createElement('li');
      li.textContent = typeof item === 'string' ? item : (item.description || '');
      limitList.appendChild(li);
    });
    limitSection.appendChild(limitList);
    container.appendChild(limitSection);
  }

  // Report link
  if (data.report_path && typeof data.report_path === 'string') {
    const reportSection = document.createElement('div');
    reportSection.className = 'rh-panel__section';
    const reportLink = document.createElement('a');
    reportLink.className = 'rh-panel__report-link';
    reportLink.href = data.report_path;
    reportLink.textContent = '查看研究报告';
    reportLink.target = '_blank';
    reportLink.rel = 'noopener noreferrer';
    reportSection.appendChild(reportLink);
    container.appendChild(reportSection);
  }
}

/**
 * Hides the research panel.
 * @param {HTMLElement} container
 */
export function hideResearchPanel(container) {
  container.classList.remove('rh-panel--visible');
  container.classList.add('rh-panel--hidden');
  container.setAttribute('aria-hidden', 'true');
}

/**
 * Initializes the research harness panel.
 * Fetches data, validates, and renders or hides accordingly.
 * @param {HTMLElement} container - The panel container element
 * @param {object} options - { routeCatalog, onSelectRoute }
 * @returns {Promise<boolean>} True if panel was shown
 */
export async function initResearchPanel(container, options = {}) {
  if (!container) return false;

  try {
    const response = await fetch(RESEARCH_DATA_URL);
    if (!response.ok) {
      hideResearchPanel(container);
      return false;
    }

    let data;
    try {
      data = await response.json();
    } catch (e) {
      console.warn('[research-harness-ui] Failed to parse research data JSON:', e.message);
      hideResearchPanel(container);
      return false;
    }

    if (!validatePayload(data)) {
      console.warn('[research-harness-ui] Research payload failed validation, hiding panel.');
      hideResearchPanel(container);
      return false;
    }

    renderResearchPanel(container, data, options);
    return true;
  } catch (e) {
    console.warn('[research-harness-ui] Failed to load research data:', e.message);
    hideResearchPanel(container);
    return false;
  }
}
