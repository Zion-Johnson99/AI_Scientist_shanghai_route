import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const mainCss = readFileSync(new URL("../web/styles/main.css", import.meta.url), "utf8");
const recommendationCss = readFileSync(new URL("../web/styles/recommendation.css", import.meta.url), "utf8");
const filterIcons = readFileSync(new URL("../web/assets/icons/filter-icons.svg", import.meta.url), "utf8");

test("健康档案使用 Komoot 棕橄榄绿品牌色板且不再使用亮蓝渐变", () => {
  assert.match(mainCss, /--brand-primary:\s*#4f6814/i);
  assert.match(mainCss, /--brand-primary-hover:\s*#3f5310/i);
  assert.match(mainCss, /--walk:\s*#197cff/i);
  assert.match(mainCss, /--surface-brand-soft:\s*#ede9de/i);
  assert.match(mainCss, /\.profile-dialog__choice\.is-selected\s*\{[^}]*color:\s*var\(--brand-primary\)[^}]*background:\s*var\(--surface-brand-soft\)/s);
  assert.match(mainCss, /\.profile-dialog__save\s*\{[^}]*background:\s*var\(--brand-primary\)/s);
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
  assert.match(recommendationCss, /\.recommendation-filter__chip\s*\{[^}]*border-radius:\s*10px[^}]*background:\s*var\(--surface-main\)/s);
  assert.match(recommendationCss, /\.recommendation-filter__icon\s*\{[^}]*width:\s*19px[^}]*height:\s*19px/s);
  assert.doesNotMatch(recommendationCss, /\.recommendation-filter__value|\.recommendation-filter__chip::after/);
  assert.match(recommendationCss, /\.recommendation-filter__chip\.is-open\s*\{[^}]*color:\s*var\(--brand-primary\)[^}]*background:\s*var\(--surface-brand-soft\)/s);
  assert.match(recommendationCss, /\.recommendation-filter__popover\s*\{[^}]*position:\s*absolute[^}]*width:\s*min\(400px,[^}]*max-height:\s*min\(460px,[^}]*grid-template-rows:[^}]*border-radius:\s*16px[^}]*box-shadow:/s);
  assert.match(recommendationCss, /\.recommendation-filter__header\s*\{[^}]*min-height:\s*60px/s);
  assert.match(recommendationCss, /\.recommendation-filter__option\s*\{[^}]*min-height:\s*48px[^}]*font-size:\s*15px/s);
  assert.match(recommendationCss, /\.recommendation-filter__footer\s*\{[^}]*grid-template-columns:\s*1fr 1fr[^}]*padding:\s*12px 18px 16px[^}]*border-top:/s);
  assert.match(recommendationCss, /\.recommendation-filter__indicator\s*\{[^}]*width:\s*22px[^}]*border-radius:\s*50%/s);
  assert.match(recommendationCss, /\.recommendation-filter__chip:focus-visible\s*\{[^}]*var\(--focus\)/s);
});

test("七个筛选图标与运动标志使用同系列 Material Symbols Rounded 资产", () => {
  assert.match(filterIcons, /Google Material Symbols Rounded/);
  assert.match(filterIcons, /Licensed under Apache-2\.0/);
  for (const icon of ["time", "distance", "goal", "scope", "route", "rest", "scenery"]) {
    assert.match(filterIcons, new RegExp(`id="filter-${icon}"`));
  }
});

test("推荐卡与浏览卡运动图标使用步行蓝、跑步红和骑行紫", () => {
  assert.match(recommendationCss, /\.route-card__sport-icon\s*\{[^}]*width:\s*22px[^}]*height:\s*22px[^}]*color:\s*var\(--walk\)/s);
  assert.match(recommendationCss, /\.route-card__sport-icon--walk\s*\{[^}]*color:\s*var\(--walk\)/s);
  assert.match(recommendationCss, /\.route-card__sport-icon--run\s*\{[^}]*color:\s*var\(--run\)/s);
  assert.match(recommendationCss, /\.route-card__sport-icon--bike\s*\{[^}]*color:\s*var\(--bike\)/s);
  assert.match(recommendationCss, /\.route-card__sport-icon svg\s*\{[^}]*fill:\s*currentcolor[^}]*stroke:\s*none/s);
});

test("左侧路线卡保持白底无描边且选中态不增加彩色轮廓", () => {
  assert.match(recommendationCss, /\.route-card\s*\{[^}]*border:\s*0[^}]*background:\s*var\(--surface-main\)/s);
  assert.match(recommendationCss, /\.route-card\s*\{[^}]*grid-template-columns:\s*112px\s+minmax\(0,\s*1fr\)[^}]*gap:\s*16px/s);
  assert.match(recommendationCss, /\.route-card__media\s*\{[^}]*width:\s*112px[^}]*height:\s*112px/s);
  assert.match(recommendationCss, /\.route-card__body\s*\{[^}]*grid-template-rows:\s*auto\s+auto\s+auto[^}]*align-content:\s*center[^}]*gap:\s*5px/s);
  assert.doesNotMatch(recommendationCss, /\.route-card__body\s*\{[^}]*minmax\(40px,\s*auto\)/s);
  assert.match(recommendationCss, /\.route-card__name\s*\{[^}]*font-size:\s*17px[^}]*font-weight:\s*740/s);
  assert.match(recommendationCss, /\.route-card__metrics\s*\{[^}]*display:\s*grid[^}]*overflow:\s*visible[^}]*white-space:\s*normal/s);
  assert.match(recommendationCss, /\.route-card__metrics\s*\{[^}]*font-size:\s*14px[^}]*font-weight:\s*620/s);
  assert.match(recommendationCss, /\.route-card__metrics-travel\s*\{[^}]*display:\s*flex[^}]*gap:\s*12px[^}]*white-space:\s*nowrap/s);
  assert.match(recommendationCss, /\.route-card\.is-selected\s*\{[^}]*background:\s*var\(--surface-main\)/s);
  assert.doesNotMatch(recommendationCss, /\.route-card\.is-selected\s*\{[^}]*(?:border|box-shadow):/s);
  assert.doesNotMatch(recommendationCss, /\.route-card(?::hover|\.is-hovered)\s*\{[^}]*border(?:-color)?:/s);
});

test("左栏路线卡滚动，补充需求与 CTA 固定在底部", () => {
  assert.match(recommendationCss, /\.recommendation-view\.active:has\(\.recommendation-workspace\)\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)[^}]*align-content:\s*stretch[^}]*overflow:\s*hidden/s);
  assert.match(recommendationCss, /\.recommendation-workspace\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)\s+auto/s);
  assert.match(recommendationCss, /\.recommendation-results-list\s*\{[^}]*overflow-y:\s*auto[^}]*overscroll-behavior:\s*contain/s);
  assert.match(recommendationCss, /\.recommendation-workspace__footer\s*\{[^}]*flex:\s*0\s+0\s+auto/s);
});

test("千问输入框在扁长胶囊与外置圆形发送键之间切换", () => {
  assert.match(recommendationCss, /\.recommendation-chat__composer\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)[^}]*gap:\s*12px[^}]*padding:\s*0[^}]*border:\s*0[^}]*background:\s*transparent/s);
  assert.match(recommendationCss, /\.recommendation-chat__composer\.has-draft\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+56px/s);
  assert.match(recommendationCss, /\.recommendation-chat__input\s*\{[^}]*height:\s*56px[^}]*padding:\s*16px\s+18px\s+14px[^}]*border:\s*1px\s+solid[^}]*border-radius:\s*999px/s);
  assert.match(recommendationCss, /\.recommendation-chat__send\s*\{[^}]*width:\s*56px[^}]*height:\s*56px[^}]*border-radius:\s*50%/s);
  assert.match(recommendationCss, /\.recommendation-chat__send-icon\s*\{[^}]*transform:\s*rotate\(45deg\)/s);
});

test("千问消息、公开进度与无图路线卡采用独立 Komoot 式层级", () => {
  assert.match(recommendationCss, /\.recommendation-chat__message\s*\{[^}]*font-weight:\s*(?:6\d\d|7\d\d)/s);
  assert.match(recommendationCss, /\.recommendation-chat__message--assistant\s*\{[^}]*padding:\s*0[^}]*background:\s*transparent/s);
  assert.match(recommendationCss, /\.recommendation-chat__message--user\s*\{[^}]*border-radius:\s*999px[^}]*background:\s*(?:#f3f2ee|var\(--surface-soft\))/s);
  assert.match(recommendationCss, /\.recommendation-chat__progress\s*\{[^}]*font-weight:\s*(?:6\d\d|7\d\d)/s);
  assert.match(recommendationCss, /\.recommendation-chat__progress-dot\s*\{[^}]*animation:\s*recommendation-chat-progress/s);
  assert.match(recommendationCss, /@keyframes\s+recommendation-chat-progress/);
  assert.match(recommendationCss, /\.recommendation-chat__route-card\s*\{[^}]*border-radius:/s);
  assert.match(recommendationCss, /\.recommendation-chat__route-card\.is-selected\s*\{[^}]*border-color:\s*color-mix\(in srgb,\s*var\(--brand-primary\)[^}]*var\(--line\)\)/s);
  assert.doesNotMatch(recommendationCss, /\.recommendation-chat__route-card\[data-(?:mode|route-mode)/s);
  assert.match(recommendationCss, /\.recommendation-chat__media\s*\{[^}]*flex:\s*0\s+0\s+(?:112|116|120|124|128)px[^}]*background:/s);
});

test("桌面工作台收窄到 392px 且聊天角色切换增加纵向留白", () => {
  assert.match(mainCss, /\.sidebar\s*\{[^}]*width:\s*min\(392px,\s*calc\(100vw\s*-\s*32px\)\)/s);
  assert.match(recommendationCss, /\.recommendation-chat__message--assistant\s*\{[^}]*font-weight:\s*600/s);
  assert.match(
    recommendationCss,
    /\.recommendation-chat__message--user\s*\+\s*\.recommendation-chat__message--assistant,\s*\.recommendation-chat__message--assistant\s*\+\s*\.recommendation-chat__message--user\s*\{[^}]*margin-top:\s*12px/s,
  );
});

test("千问聊天移除开始推荐 CTA 并为动态状态提供减弱动画", () => {
  assert.doesNotMatch(recommendationCss, /\.recommendation-chat__confirm/);
  assert.match(recommendationCss, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.recommendation-chat__progress-dot/s);
});

test("CTA 在原位加载时显示森林绿流光与轻微呼吸", () => {
  assert.match(recommendationCss, /\.recommendation-form__submit\s*\{[^}]*background:\s*var\(--brand-primary\)/s);
  assert.match(recommendationCss, /\.recommendation-form__submit:hover\s*\{[^}]*background:\s*var\(--brand-primary-hover\)/s);
  assert.match(recommendationCss, /\.recommendation-form__submit\.is-loading\s*\{[^}]*var\(--brand-primary\)[^}]*var\(--brand-primary-hover\)[^}]*animation:\s*recommendation-cta-breathe/s);
  assert.match(recommendationCss, /\.recommendation-form__submit\.is-loading::before\s*\{[^}]*linear-gradient\([^}]*var\(--surface-brand-soft\)[^}]*animation:\s*recommendation-cta-shimmer/s);
  assert.match(recommendationCss, /@keyframes\s+recommendation-cta-breathe/);
  assert.match(recommendationCss, /@keyframes\s+recommendation-cta-shimmer/);
  assert.match(recommendationCss, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.recommendation-form__submit\.is-loading/s);
});

test("推荐区品牌用途不再引用旧深蓝变量与蓝色装饰阴影", () => {
  assert.doesNotMatch(recommendationCss, /var\(--brand-blue\)|var\(--teal-dark\)/);
  assert.doesNotMatch(recommendationCss, /#183858|#8ec9ed|#197cff|rgba?\(\s*(?:7\s*,\s*29\s*,\s*63|11\s*,\s*40\s*,\s*86|16\s*,\s*35\s*,\s*63|18\s+29\s+48|25\s*,\s*124\s*,\s*255)/i);
});

test("移动端保留顶部筛选轨与底部抽屉的可用高度", () => {
  assert.match(recommendationCss, /@media\s*\(max-width:\s*980px\)[\s\S]*\.recommendation-filters[\s\S]*\{[^}]*top:\s*74px[^}]*right:\s*8px[^}]*left:\s*8px/s);
  assert.match(mainCss, /@media\s*\(max-width:\s*980px\)[\s\S]*\.sidebar\s*\{[^}]*top:\s*auto[^}]*bottom:\s*0[^}]*height:\s*min\(76dvh,\s*680px\)/s);
  assert.match(mainCss, /@media\s*\(max-width:\s*980px\)[\s\S]*\.map-layer-button\s*\{[^}]*z-index:\s*330[^}]*top:\s*132px[^}]*bottom:\s*auto/s);
  assert.match(mainCss, /@media\s*\(max-width:\s*980px\)[\s\S]*\.map-legend\s*\{[^}]*z-index:\s*330[^}]*top:\s*182px[^}]*bottom:\s*auto/s);
});

test("地图与白色浮层形成健康绿灰画布和清晰层级", () => {
  assert.match(mainCss, /#map\s*\{[^}]*background:\s*#e8ece5/s);
  assert.match(mainCss, /\.sidebar\s*\{[^}]*box-shadow:/s);
  assert.match(recommendationCss, /\.recommendation-filter__chip\s*\{[^}]*box-shadow:\s*0 7px 20px color-mix\(in srgb,\s*var\(--ink\) 13%,\s*transparent\)/s);
});

test("图层面板用两张地图缩略色块表达当前选择", () => {
  assert.match(mainCss, /\.map-style-switch\s*\{[^}]*grid-template-columns:\s*1fr 1fr/s);
  assert.match(mainCss, /\.map-style-option\.is-selected\s*\{[^}]*border-color:\s*var\(--health-green\)/s);
  assert.match(mainCss, /\.map-style-option__swatch--health\s*\{[^}]*#e8ece5/s);
  assert.match(mainCss, /\.map-style-option__swatch--standard\s*\{[^}]*#ffd16a/s);
  assert.match(mainCss, /\.map-legend__routes\s*\{[^}]*border-top:\s*1px solid var\(--line\)/s);
});
