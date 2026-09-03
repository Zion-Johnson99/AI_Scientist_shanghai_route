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
 * Clears the container with replaceChildren() instead of innerHTML.
 * @param {HTMLElement} container - The panel container element
 * @param {object} data - Validated research payload
 * @param {object} options - { routeCatalog, onSelectRoute }
 */
export function renderResearchPanel(container, data, options = {}) {
  const { routeCatalog = [], onSelectRoute = null } = options;

  container.replaceChildren();
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

    const blTable = document.createElement('table');
    blTable.className = 'rh-panel__baseline-table';
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['基线', '得分', '差异'].forEach(h => {
      const th = document.createElement('th');
      th.textContent = h;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    blTable.appendChild(thead);

    const tbody = document.createElement('tbody');
    data.baselines.forEach(bl => {
      const row = document.createElement('tr');
      const nameCell = document.createElement('td');
      nameCell.textContent = bl.name || bl.id || '未知';
      row.appendChild(nameCell);
      const scoreCell = document.createElement('td');
      scoreCell.textContent = typeof bl.score === 'number' ? bl.score.toFixed(2) : '—';
      row.appendChild(scoreCell);
      const diffCell = document.createElement('td');
      diffCell.textContent = typeof bl.delta === 'number' ? (bl.delta >= 0 ? '+' : '') + bl.delta.toFixed(2) : '—';
      row.appendChild(diffCell);
      tbody.appendChild(row);
    });
    blTable.appendChild(tbody);
    baselineSection.appendChild(blTable);
    container.appendChild(baselineSection);
  }

  // Key metrics
  if (data.metrics && typeof data.metrics === 'object') {
    const metricsSection = document.createElement('div');
    metricsSection.className = 'rh-panel__section';
    const mLabel = document.createElement('h3');
    mLabel.className = 'rh-panel__section-title';
    mLabel.textContent = '关键指标';
    metricsSection.appendChild(mLabel);

    const metricsList = document.createElement('dl');
    metricsList.className = 'rh-panel__metrics';
    Object.entries(data.metrics).forEach(([key, value]) => {
      const dt = document.createElement('dt');
      dt.textContent = key;
      metricsList.appendChild(dt);
      const dd = document.createElement('dd');
      dd.textContent = typeof value === 'number' ? value.toFixed(2) : String(value);
      metricsList.appendChild(dd);
    });
    metricsSection.appendChild(metricsList);
    container.appendChild(metricsSection);
  }

  // Selected route
  if (data.selected_route && data.selected_route.route_id) {
    const routeSection = document.createElement('div');
    routeSection.className = 'rh-panel__section';
    const rLabel = document.createElement('h3');
    rLabel.className = 'rh-panel__section-title';
    rLabel.textContent = '候选集约束最优路线';
    routeSection.appendChild(rLabel);

    const routeInfo = document.createElement('p');
    routeInfo.className = 'rh-panel__route-info';
    routeInfo.textContent = data.selected_route.route_name || data.selected_route.route_id;
    routeSection.appendChild(routeInfo);

    if (routeExistsInCatalog(data.selected_route.route_id, routeCatalog)) {
      const selectBtn = document.createElement('button');
      selectBtn.className = 'rh-panel__route-btn';
      selectBtn.textContent = '在地图中查看';
      selectBtn.addEventListener('click', () => {
        if (typeof onSelectRoute === 'function') {
          onSelectRoute(data.selected_route.route_id);
        }
      });
      routeSection.appendChild(selectBtn);
    } else {
      const fallback = document.createElement('p');
      fallback.className = 'rh-panel__route-fallback';
      fallback.textContent = '该路线在当前目录中不可用。';
      routeSection.appendChild(fallback);
    }
    container.appendChild(routeSection);
  }

  // Iteration timeline
  if (data.iterations && Array.isArray(data.iterations)) {
    const timelineSection = document.createElement('div');
    timelineSection.className = 'rh-panel__section';
    const tLabel = document.createElement('h3');
    tLabel.className = 'rh-panel__section-title';
    tLabel.textContent = '迭代时间线';
    timelineSection.appendChild(tLabel);

    const timeline = document.createElement('ol');
    timeline.className = 'rh-panel__timeline';
    data.iterations.forEach(iter => {
      const li = document.createElement('li');
      li.className = 'rh-panel__timeline-item';
      const time = document.createElement('time');
      time.textContent = iter.timestamp || iter.date || '';
      li.appendChild(time);
      const desc = document.createElement('span');
      desc.textContent = iter.summary || iter.action || '迭代';
      li.appendChild(desc);
      timeline.appendChild(li);
    });
    timelineSection.appendChild(timeline);
    container.appendChild(timelineSection);
  }

  // Data limitations & proxy variables
  if (data.limitations && Array.isArray(data.limitations)) {
    const limSection = document.createElement('div');
    limSection.className = 'rh-panel__section';
    const limLabel = document.createElement('h3');
    limLabel.className = 'rh-panel__section-title';
    limLabel.textContent = '数据限制与代理变量';
    limSection.appendChild(limLabel);

    const limList = document.createElement('ul');
    limList.className = 'rh-panel__limitations';
    data.limitations.forEach(item => {
      const li = document.createElement('li');
      li.textContent = typeof item === 'string' ? item : item.description || '';
      limList.appendChild(li);
    });
    limSection.appendChild(limList);
    container.appendChild(limSection);
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
 * Hides the research panel and removes visible state.
 * @param {HTMLElement} container - The panel container element
 */
export function hideResearchPanel(container) {
  container.replaceChildren();
  container.classList.remove('rh-panel--visible');
  container.removeAttribute('role');
  container.removeAttribute('aria-label');
}

/**
 * Initializes the research panel: fetches data, validates, renders or hides.
 * @param {HTMLElement} container - The panel container element
 * @param {object} options - { routeCatalog, onSelectRoute }
 * @returns {Promise<boolean>} True if panel was rendered
 */
export async function initResearchPanel(container, options = {}) {
  try {
    const response = await fetch(RESEARCH_DATA_URL);
    if (!response.ok) {
      hideResearchPanel(container);
      console.warn('[research-harness-ui] Data file not found or HTTP error:', response.status);
      return false;
    }
    const data = await response.json();
    if (!validatePayload(data)) {
      hideResearchPanel(container);
      console.warn('[research-harness-ui] Payload validation failed.');
      return false;
    }
    renderResearchPanel(container, data, options);
    return true;
  } catch (err) {
    hideResearchPanel(container);
    console.warn('[research-harness-ui] Failed to load research data:', err);
    return false;
  }
}
