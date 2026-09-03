/**
 * recommendation-ui.js
 * 推荐面板 UI：展示千问推荐结果、风险提醒、候选路线列表。
 *
 * 职责：
 * - 渲染推荐结果（首选 + 备选）
 * - 风险暂停时显示暂停提示
 * - 无候选时显示无候选文案
 * - 千问服务异常时显示降级提示
 *
 * 集成契约：
 * - 由 main.js 初始化并调用
 * - 通过 data-loader.js 获取数据（不直接 fetch）
 * - 使用 textContent 渲染模型生成文本，禁止 innerHTML 注入
 */

const RecommendationUI = (() => {
  'use strict';

  /** @type {HTMLElement|null} */
  let container = null;

  /** @type {Function|null} */
  let onRouteSelect = null;

  /**
   * 初始化推荐面板。
   * @param {Object} options
   * @param {HTMLElement} options.container - 面板容器元素
   * @param {Function} [options.onRouteSelect] - 路线选中回调，参数为 route_id
   */
  function init(options) {
    if (!options || !options.container) {
      console.warn('[RecommendationUI] init called without container; skipping.');
      return;
    }
    container = options.container;
    onRouteSelect = options.onRouteSelect || null;
    renderEmpty();
  }

  /**
   * 渲染空状态（初始或无数据）。
   */
  function renderEmpty() {
    if (!container) return;
    container.innerHTML = '';
    const msg = document.createElement('p');
    msg.className = 'rec-empty';
    msg.textContent = '暂无推荐数据，请尝试发起推荐请求。';
    container.appendChild(msg);
  }

  /**
   * 渲染加载中状态。
   */
  function renderLoading() {
    if (!container) return;
    container.innerHTML = '';
    const msg = document.createElement('p');
    msg.className = 'rec-loading';
    msg.textContent = '正在获取推荐结果…';
    container.appendChild(msg);
  }

  /**
   * 渲染风险暂停提示。
   * @param {Object} risk - RiskAssessment 对象
   * @param {string} risk.reason - 暂停原因
   * @param {string} [risk.level] - 风险等级
   */
  function renderRiskPause(risk) {
    if (!container) return;
    container.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'rec-risk-pause';

    const icon = document.createElement('span');
    icon.className = 'rec-risk-icon';
    icon.textContent = '⚠️';
    icon.setAttribute('aria-hidden', 'true');

    const title = document.createElement('h3');
    title.className = 'rec-risk-title';
    title.textContent = '运动暂停建议';

    const reason = document.createElement('p');
    reason.className = 'rec-risk-reason';
    reason.textContent = risk.reason || '当前环境条件不适合户外运动。';

    const level = document.createElement('p');
    level.className = 'rec-risk-level';
    if (risk.level) {
      level.textContent = '风险等级：' + risk.level;
    } else {
      level.textContent = '风险等级：未知';
    }

    wrapper.appendChild(icon);
    wrapper.appendChild(title);
    wrapper.appendChild(reason);
    wrapper.appendChild(level);
    container.appendChild(wrapper);
  }

  /**
   * 渲染无候选文案。
   * @param {string} [message] - 自定义无候选原因
   */
  function renderNoCandidates(message) {
    if (!container) return;
    container.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'rec-no-candidates';

    const title = document.createElement('h3');
    title.className = 'rec-no-candidates-title';
    title.textContent = '暂无可行候选路线';

    const desc = document.createElement('p');
    desc.className = 'rec-no-candidates-desc';
    desc.textContent = message || '在当前约束条件下没有满足要求的路线。请尝试调整目标距离或运动方式。';

    wrapper.appendChild(title);
    wrapper.appendChild(desc);
    container.appendChild(wrapper);
  }

  /**
   * 渲染降级提示（千问服务异常，使用本地排序）。
   */
  function renderDegradedNotice() {
    const notice = document.createElement('p');
    notice.className = 'rec-degraded-notice';
    notice.textContent = '⚠ 千问服务暂不可用，当前结果基于本地排序，仅供参考。';
    return notice;
  }

  /**
   * 渲染推荐结果。
   * @param {Object} result - 推荐结果对象
   * @param {Object} [result.risk] - 风险评估
   * @param {boolean} [result.risk.paused] - 是否暂停
   * @param {string} [result.risk.reason] - 暂停原因
   * @param {Array} [result.candidates] - 候选路线列表
   * @param {Object} [result.primary] - 首选推荐
   * @param {Array} [result.alternatives] - 备选推荐
   * @param {boolean} [result.degraded] - 是否降级
   * @param {string} [result.explanation] - 推荐理由
   */
  function renderResult(result) {
    if (!container) return;

    if (!result) {
      renderEmpty();
      return;
    }

    // 风险暂停
    if (result.risk && result.risk.paused) {
      renderRiskPause(result.risk);
      return;
    }

    // 无候选
    const candidates = result.candidates || [];
    if (candidates.length === 0 && !result.primary) {
      renderNoCandidates(result.no_candidate_reason);
      return;
    }

    container.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'rec-result';

    // 降级提示
    if (result.degraded) {
      wrapper.appendChild(renderDegradedNotice());
    }

    // 推荐理由
    if (result.explanation) {
      const explanation = document.createElement('p');
      explanation.className = 'rec-explanation';
      explanation.textContent = result.explanation;
      wrapper.appendChild(explanation);
    }

    // 首选推荐
    if (result.primary) {
      const primarySection = document.createElement('div');
      primarySection.className = 'rec-primary';

      const primaryTitle = document.createElement('h3');
      primaryTitle.className = 'rec-section-title';
      primaryTitle.textContent = '首选推荐';
      primarySection.appendChild(primaryTitle);

      primarySection.appendChild(renderRouteCard(result.primary, true));
      wrapper.appendChild(primarySection);
    }

    // 备选推荐
    const alternatives = result.alternatives || [];
    if (alternatives.length > 0) {
      const altSection = document.createElement('div');
      altSection.className = 'rec-alternatives';

      const altTitle = document.createElement('h3');
      altTitle.className = 'rec-section-title';
      altTitle.textContent = '备选路线';
      altSection.appendChild(altTitle);

      alternatives.forEach(function (route) {
        altSection.appendChild(renderRouteCard(route, false));
      });

      wrapper.appendChild(altSection);
    }

    // 如果只有 candidates 没有 primary/alternatives 结构
    if (!result.primary && candidates.length > 0) {
      const listSection = document.createElement('div');
      listSection.className = 'rec-candidates';

      const listTitle = document.createElement('h3');
      listTitle.className = 'rec-section-title';
      listTitle.textContent = '候选路线（共 ' + candidates.length + ' 条）';
      listSection.appendChild(listTitle);

      candidates.forEach(function (route) {
        listSection.appendChild(renderRouteCard(route, false));
      });

      wrapper.appendChild(listSection);
    }

    container.appendChild(wrapper);
  }

  /**
   * 渲染单条路线卡片。
   * @param {Object} route - 路线对象
   * @param {string} route.route_id
   * @param {string} [route.route_name]
   * @param {string} [route.route_mode]
   * @param {number} [route.distance_m]
   * @param {Object} [route.scores] - 五维分数
   * @param {number} [route.scores.environment_health]
   * @param {number} [route.scores.sport_match]
   * @param {number} [route.scores.access_convenience]
   * @param {number} [route.scores.route_quality]
   * @param {number} [route.scores.interest_service]
   * @param {number} [route.base_score]
   * @param {boolean} isPrimary - 是否为首选
   * @returns {HTMLElement}
   */
  function renderRouteCard(route, isPrimary) {
    const card = document.createElement('div');
    card.className = 'rec-route-card' + (isPrimary ? ' rec-route-card--primary' : '');
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', '选择路线 ' + (route.route_name || route.route_id));
    card.dataset.routeId = route.route_id || '';

    // 路线名称
    const name = document.createElement('span');
    name.className = 'rec-route-name';
    name.textContent = route.route_name || route.route_id || '未知路线';
    card.appendChild(name);

    // 模式标签
    if (route.route_mode) {
      const mode = document.createElement('span');
      mode.className = 'rec-route-mode rec-mode-' + route.route_mode;
      mode.textContent = formatMode(route.route_mode);
      card.appendChild(mode);
    }

    // 距离
    if (typeof route.distance_m === 'number') {
      const dist = document.createElement('span');
      dist.className = 'rec-route-distance';
      dist.textContent = formatDistance(route.distance_m);
      card.appendChild(dist);
    }

    // 综合分
    if (typeof route.base_score === 'number') {
      const score = document.createElement('span');
      score.className = 'rec-route-score';
      score.textContent = route.base_score.toFixed(1) + ' 分';
      card.appendChild(score);
    }

    // 五维分数（折叠展示）
    if (route.scores) {
      const scoresDiv = document.createElement('div');
      scoresDiv.className = 'rec-route-scores';

      const dimensions = [
        { key: 'environment_health', label: '环境健康' },
        { key: 'sport_match', label: '运动匹配' },
        { key: 'access_convenience', label: '接驳便利' },
        { key: 'route_quality', label: '路线质量' },
        { key: 'interest_service', label: '兴趣服务' }
      ];

      dimensions.forEach(function (dim) {
        const val = route.scores[dim.key];
        if (typeof val === 'number') {
          const item = document.createElement('span');
          item.className = 'rec-dim-score';
          item.textContent = dim.label + ' ' + val.toFixed(1);
          scoresDiv.appendChild(item);
        }
      });

      if (scoresDiv.children.length > 0) {
        card.appendChild(scoresDiv);
      }
    }

    // 点击与键盘事件
    card.addEventListener('click', function () {
      selectRoute(route.route_id);
    });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectRoute(route.route_id);
      }
    });

    return card;
  }

  /**
   * 选中路线回调。
   * @param {string} routeId
   */
  function selectRoute(routeId) {
    if (!routeId) return;
    if (typeof onRouteSelect === 'function') {
      onRouteSelect(routeId);
    }
  }

  /**
   * 格式化运动模式。
   * @param {string} mode
   * @returns {string}
   */
  function formatMode(mode) {
    const map = {
      walk: '步行',
      run: '跑步',
      bike: '骑行'
    };
    return map[mode] || mode;
  }

  /**
   * 格式化距离。
   * @param {number} meters
   * @returns {string}
   */
  function formatDistance(meters) {
    if (meters >= 1000) {
      return (meters / 1000).toFixed(1) + ' km';
    }
    return Math.round(meters) + ' m';
  }

  /**
   * 渲染错误状态。
   * @param {string} message - 错误信息
   */
  function renderError(message) {
    if (!container) return;
    container.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'rec-error';

    const title = document.createElement('h3');
    title.className = 'rec-error-title';
    title.textContent = '推荐服务异常';

    const desc = document.createElement('p');
    desc.className = 'rec-error-desc';
    desc.textContent = message || '无法获取推荐结果，请稍后重试。';

    wrapper.appendChild(title);
    wrapper.appendChild(desc);
    container.appendChild(wrapper);
  }

  /**
   * 销毁面板，清理事件。
   */
  function destroy() {
    if (container) {
      container.innerHTML = '';
    }
    container = null;
    onRouteSelect = null;
  }

  // 公开 API
  return {
    init: init,
    renderEmpty: renderEmpty,
    renderLoading: renderLoading,
    renderRiskPause: renderRiskPause,
    renderNoCandidates: renderNoCandidates,
    renderResult: renderResult,
    renderError: renderError,
    destroy: destroy
  };
})();

// 支持 ES module 导出（用于测试）与全局访问
if (typeof module !== 'undefined' && module.exports) {
  module.exports = RecommendationUI;
}
if (typeof window !== 'undefined') {
  window.RecommendationUI = RecommendationUI;
}
