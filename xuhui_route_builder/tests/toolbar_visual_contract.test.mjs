import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../web/styles/main.css", import.meta.url), "utf8");
const main = readFileSync(new URL("../web/src/main.js", import.meta.url), "utf8");
const sportIcons = readFileSync(new URL("../web/assets/icons/sport-icons.svg", import.meta.url), "utf8");

test("地点搜索与运动方式组成紧凑胶囊工具", () => {
  assert.match(html, /<div class="route-search-shell" role="search"/);
  assert.match(html, /<details id="sportModeTabs"[\s\S]*<div class="toolbar-location">/);
  assert.match(css, /\.route-search-shell\s*\{[\s\S]*?height:\s*46px;[\s\S]*?border-radius:\s*999px;/);
  assert.match(css, /\.route-search-shell\s*\{[\s\S]*?width:\s*clamp\(400px,\s*36vw,\s*560px\);/);
  assert.match(css, /\.product-toolbar \.sport-mode-tabs\s*\{[\s\S]*?border-right:\s*1px solid/);
});

test("三种运动方式使用统一圆润填充 SVG 与说明", () => {
  for (const mode of ["walk", "run", "bike"]) {
    assert.match(html, new RegExp(`data-route-mode="${mode}"[\\s\\S]*?<svg class="sport-icon" data-sport-icon="${mode}"`));
    assert.match(html, new RegExp(`sport-icons\\.svg#sport-${mode}`));
    assert.match(sportIcons, new RegExp(`<symbol id="sport-${mode}"`));
  }
  assert.match(css, /\.sport-icon\s*\{[\s\S]*?width:\s*24px;[\s\S]*?height:\s*24px;/);
  assert.match(css, /\.sport-icon\s*\{[\s\S]*?fill:\s*currentColor;[\s\S]*?stroke:\s*none;/);
  assert.match(css, /\.product-toolbar \.sport-mode-menu svg\s*\{[\s\S]*?width:\s*40px;[\s\S]*?height:\s*40px;[\s\S]*?border-radius:\s*8px;[\s\S]*?background:\s*#ede9de;/);
  assert.match(html, /<b>步行<\/b><small>城市漫步与日常出行<\/small>/);
  assert.match(html, /<b>跑步<\/b><small>道路慢跑与节奏训练<\/small>/);
  assert.match(html, /<b>骑行<\/b><small>铺装道路与城市骑游<\/small>/);
});

test("环境摘要为棕橄榄绿圆角长条并保留半透明白色分隔线", () => {
  const legacyToggleStart = css.indexOf(".environment-panel:not(.is-expanded) .environment-toggle {");
  const legacyToggleBlock = css.slice(legacyToggleStart, css.indexOf("}", legacyToggleStart));

  assert.match(css, /\.product-toolbar \.environment-toggle\s*\{[\s\S]*?border:\s*0;[\s\S]*?border-radius:\s*16px;[\s\S]*?color:\s*#fff;[\s\S]*?background:\s*var\(--brand-primary\);/);
  assert.match(css, /\.product-toolbar \.environment-toggle\s*\{[^}]*padding:\s*0 24px 0 12px;/);
  assert.doesNotMatch(legacyToggleBlock, /padding:/);
  assert.match(css, /\.environment-toggle__item \+ \.environment-toggle__item\s*\{[\s\S]*?border-left:\s*1px solid rgba\(255, 255, 255,/);
  assert.match(css, /\.environment-toggle__chevron\s*\{[\s\S]*?width:\s*18px;[\s\S]*?stroke:\s*currentColor;/);
});

test("环境摘要数值增大并统一基线，AQI 等级使用语义色", () => {
  assert.doesNotMatch(css, /\.environment-panel:not\(\.is-expanded\) \.environment-toggle span\s*\{[^}]*font-size:\s*0;/);
  assert.doesNotMatch(css, /\.environment-panel:not\(\.is-expanded\) \.environment-toggle span::after\s*\{[^}]*content:\s*"详情";/);
  assert.doesNotMatch(css, /\.product-toolbar \.environment-panel \.environment-toggle span\s*\{[^}]*font-size:\s*inherit;/);
  assert.match(css, /\.environment-toggle__item\s*\{[\s\S]*?height:\s*24px;[\s\S]*?gap:\s*7px;[\s\S]*?padding:\s*0 13px;/);
  assert.match(css, /\.environment-toggle__label\s*\{[\s\S]*?font-size:\s*11px;[\s\S]*?line-height:\s*1;/);
  assert.match(css, /\.environment-toggle__item strong\s*\{[\s\S]*?font-size:\s*14px;[\s\S]*?font-variant-numeric:\s*tabular-nums;[\s\S]*?line-height:\s*1;/);
  assert.match(css, /\.environment-toggle__aqi-number\s*\{[\s\S]*?font-size:\s*15px;[\s\S]*?line-height:\s*1;/);
  assert.match(css, /\.environment-toggle__aqi-level\s*\{[\s\S]*?width:\s*22px;[\s\S]*?height:\s*22px;[\s\S]*?border-radius:\s*7px;/);
  assert.match(css, /\.environment-toggle__aqi-level\s*\{[^}]*font-size:\s*11px;/);
  assert.match(css, /\.environment-toggle__aqi-level--excellent\s*\{[\s\S]*?background:\s*#22a06b;/);
  assert.match(css, /\.environment-toggle__aqi-level--good\s*\{[\s\S]*?color:\s*#10213b;[\s\S]*?background:\s*#f2c94c;/);
  assert.match(css, /\.environment-toggle__aqi-level--moderate\s*\{[\s\S]*?background:\s*#e45656;/);
  assert.match(css, /\.environment-toggle__aqi-level--severe\s*\{[\s\S]*?background:\s*#6f2537;/);
});

test("环境摘要所有图标、标签和值共享同一垂直中心", () => {
  assert.match(css, /\.environment-toggle__item\s*\{[^}]*align-items:\s*center;/);
  assert.match(
    css,
    /\.environment-toggle__label,\s*\.environment-toggle__item > strong\s*\{[^}]*height:\s*24px;[^}]*align-items:\s*center;[^}]*transform:\s*none;/,
  );
  assert.match(
    css,
    /\.environment-toggle__icon\s*\{[^}]*flex:\s*0 0 20px;[^}]*width:\s*20px;[^}]*height:\s*20px;/,
  );
  assert.match(css, /span\.environment-toggle__icon\s*\{[^}]*place-items:\s*center;/);
  assert.match(css, /\.environment-toggle__aqi\s*\{[^}]*align-items:\s*center;[^}]*gap:\s*7px;/);
  assert.match(css, /\.environment-toggle__aqi-level\s*\{[^}]*align-self:\s*center;/);
  assert.match(
    css,
    /\.environment-toggle__item--temperature > strong,\s*\.environment-toggle__item--humidity > strong,\s*\.environment-toggle__aqi-number\s*\{[^}]*transform:\s*translateY\(1px\);/,
  );
});

test("地点搜索仅保留外层焦点环并隐藏空状态占位", () => {
  assert.match(
    css,
    /\.toolbar-location input\[type="search"\]:focus\s*\{[^}]*box-shadow:\s*none;/,
  );
  assert.match(css, /\.location-editor \.field-status:empty\s*\{[^}]*display:\s*none;/);
});

test("个人档案齿轮默认透明无框并提供交互反馈", () => {
  assert.match(css, /\.profile-action\s*\{[\s\S]*?border:\s*0;[\s\S]*?background:\s*transparent;/);
  assert.match(css, /\.profile-action:hover,[\s\S]*?\.profile-action:focus-visible\s*\{[\s\S]*?background:\s*var\(--surface-brand-soft\);/);
});

test("千问入口与聊天态三项操作在标题栏按顺序切换", () => {
  assert.match(
    html,
    /<div class="workbench-header__actions">[\s\S]*?id="workbenchQwenButton"[\s\S]*?id="workbenchNewChatButton"[\s\S]*?data-workbench-new-chat[\s\S]*?hidden[\s\S]*?id="workbenchCollapseButton"[\s\S]*?id="workbenchChatCloseButton"[\s\S]*?data-workbench-chat-close[\s\S]*?hidden/,
  );
  assert.match(css, /\.workbench-qwen-button,\s*\.workbench-new-chat-button,\s*\.workbench-chat-close-button,\s*\.workbench-collapse-button\s*\{/);
  assert.match(css, /\.workbench-qwen-button\[hidden\],\s*\.workbench-new-chat-button\[hidden\]\s*\{[^}]*display:\s*none;/);
  assert.match(css, /\.workbench-chat-close-button\[hidden\]\s*\{[^}]*display:\s*none;/);
  assert.match(css, /\.workbench-chat-close-button svg\s*\{[\s\S]*?stroke:\s*currentColor;/);
});

test("旧接驳中间页面已从静态结构移除", () => {
  assert.doesNotMatch(html, /id="routeNavigationView"/);
  assert.doesNotMatch(html, /id="startPickButton"/);
  assert.doesNotMatch(html, /规划接驳路线/);
  assert.doesNotMatch(main, /\bnavigationView\b/);
});

test("启动失败与路线缺图错误不再写入已删除的旧详情节点", () => {
  assert.doesNotMatch(main, /querySelector\("#routeDetail"\)/);
  assert.doesNotMatch(main, /querySelector\("#routeSummary"\)/);
  assert.doesNotMatch(main, /querySelector\("#navigationStatus"\)/);
  assert.match(main, /console\.error\("应用启动失败",\s*\{ error \}\)/);
  assert.match(main, /querySelector\("#recommendationView"\)/);
});

test("图层面板默认选择健康地图并提供标准地图备用入口", () => {
  assert.match(
    html,
    /class="map-style-option is-selected"[^>]*data-base-map-mode="health"[^>]*aria-pressed="true"/,
  );
  assert.match(
    html,
    /class="map-style-option"[^>]*data-base-map-mode="standard"[^>]*aria-pressed="false"/,
  );
  assert.match(html, /<strong>健康地图<\/strong><small>低干扰路线视图<\/small>/);
  assert.match(html, /<strong>标准地图<\/strong><small>显示完整地图要素<\/small>/);
  assert.match(main, /setBaseMapMode\(map, mode\)/);
  assert.match(main, /candidate\.classList\.toggle\("is-selected", selected\)/);
  assert.match(main, /candidate\.setAttribute\("aria-pressed", String\(selected\)\)/);
});

test("图例使用步行蓝、跑步红、骑行紫和接驳棕橙", () => {
  const legendStart = html.indexOf('class="map-legend__routes"');
  const legendEnd = html.indexOf("</div>", legendStart);
  const legend = html.slice(legendStart, legendEnd);

  assert.match(css, /--walk:\s*#197cff/i);
  assert.match(css, /--run:\s*#D45A50/i);
  assert.match(css, /--bike:\s*#6F5AB7/i);
  assert.match(css, /--access:\s*#C9872F/i);
  assert.ok(legend.indexOf("legend-walk") < legend.indexOf("legend-run"));
  assert.match(legend, /legend-walk[^>]*><\/i>步行/);
});
