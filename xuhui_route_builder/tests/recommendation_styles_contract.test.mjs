import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const mainCss = readFileSync(new URL("../web/styles/main.css", import.meta.url), "utf8");
const recommendationCss = readFileSync(new URL("../web/styles/recommendation.css", import.meta.url), "utf8");

test("健康档案使用 XH Logo 色板且不再使用亮蓝渐变", () => {
  assert.match(mainCss, /--brand-blue:\s*#0b2856/i);
  assert.match(mainCss, /--teal-dark:\s*#071d3f/i);
  assert.match(mainCss, /--focus:\s*#197cff/i);
  assert.match(mainCss, /--surface-brand-soft:\s*#e8edf4/i);
  assert.match(mainCss, /\.profile-dialog__choice\.is-selected\s*\{[^}]*color:\s*var\(--brand-blue\)[^}]*background:\s*var\(--surface-brand-soft\)/s);
  assert.match(mainCss, /\.profile-dialog__save\s*\{[^}]*background:\s*var\(--brand-blue\)/s);
  assert.doesNotMatch(mainCss, /\.profile-dialog__save\s*\{[^}]*linear-gradient/s);
});

test("地图顶部筛选轨紧凑排列、自然滚动且只由详情状态避让", () => {
  assert.match(recommendationCss, /\.recommendation-filters\s*\{[^}]*position:\s*(?:absolute|fixed)[^}]*left:\s*var\(--recommendation-filter-left\)[^}]*width:\s*(?:fit-content|max-content)[^}]*max-width:\s*calc\(/s);
  assert.match(recommendationCss, /\.recommendation-filters__viewport\s*\{[^}]*min-width:\s*0[^}]*overflow:\s*hidden/s);
  assert.match(recommendationCss, /\.recommendation-filters__track\s*\{[^}]*gap:\s*6px[^}]*overflow-x:\s*auto[^}]*scrollbar-width:\s*none/s);
  assert.doesNotMatch(recommendationCss, /\.recommendation-filters__arrow/);
  assert.match(recommendationCss, /\.recommendation-filters\.is-detail-open\s*\{[^}]*--recommendation-filter-left:/s);
  assert.doesNotMatch(recommendationCss, /\.has-route-detail\s+\.recommendation-filters/);
});

test("筛选 chip 与弹出菜单保持品牌化、可聚焦的 Komoot 式表面", () => {
  assert.match(recommendationCss, /\.recommendation-filter__chip\s*\{[^}]*border-radius:\s*999px[^}]*background:\s*var\(--surface-main\)/s);
  assert.match(recommendationCss, /\.recommendation-filter__chip\.is-open\s*\{[^}]*color:\s*var\(--brand-blue\)[^}]*background:\s*var\(--surface-brand-soft\)/s);
  assert.match(recommendationCss, /\.recommendation-filter__popover\s*\{[^}]*position:\s*absolute[^}]*box-shadow:/s);
  assert.match(recommendationCss, /\.recommendation-filter__chip:focus-visible\s*\{[^}]*var\(--focus\)/s);
});

test("路线卡运动图标使用品牌蓝和清晰的 20px 填充比例", () => {
  assert.match(recommendationCss, /\.route-card__sport-icon\s*\{[^}]*width:\s*20px[^}]*height:\s*20px[^}]*color:\s*var\(--brand-blue\)/s);
  assert.match(recommendationCss, /\.route-card__sport-icon svg\s*\{[^}]*fill:\s*currentcolor[^}]*stroke:\s*none/s);
});

test("左栏路线卡滚动，补充需求与 CTA 固定在底部", () => {
  assert.match(recommendationCss, /\.recommendation-workspace\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)\s+auto/s);
  assert.match(recommendationCss, /\.recommendation-results-list\s*\{[^}]*overflow-y:\s*auto[^}]*overscroll-behavior:\s*contain/s);
  assert.match(recommendationCss, /\.recommendation-workspace__footer\s*\{[^}]*flex:\s*0\s+0\s+auto/s);
});

test("CTA 在原位加载时显示蓝色流光与轻微呼吸", () => {
  assert.match(recommendationCss, /\.recommendation-form__submit\.is-loading\s*\{[^}]*animation:\s*recommendation-cta-breathe/s);
  assert.match(recommendationCss, /\.recommendation-form__submit\.is-loading::before\s*\{[^}]*linear-gradient\([^}]*#197cff[^}]*animation:\s*recommendation-cta-shimmer/s);
  assert.match(recommendationCss, /@keyframes\s+recommendation-cta-breathe/);
  assert.match(recommendationCss, /@keyframes\s+recommendation-cta-shimmer/);
  assert.match(recommendationCss, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.recommendation-form__submit\.is-loading/s);
});

test("移动端保留顶部筛选轨与底部抽屉的可用高度", () => {
  assert.match(recommendationCss, /@media\s*\(max-width:\s*980px\)[\s\S]*\.recommendation-filters[\s\S]*\{[^}]*top:\s*74px[^}]*right:\s*8px[^}]*left:\s*8px/s);
  assert.match(mainCss, /@media\s*\(max-width:\s*980px\)[\s\S]*\.sidebar\s*\{[^}]*top:\s*auto[^}]*bottom:\s*0[^}]*height:\s*min\(76dvh,\s*680px\)/s);
});
