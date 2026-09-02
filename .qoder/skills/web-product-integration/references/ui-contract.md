# UI Contract

## 技术约束

- 延续原生 HTML、CSS、JavaScript；不引入 React、Vue、构建器或包管理依赖。
- 数据来自 `research_harness_latest.json`。
- 页面缺少科研数据时正常运行。
- 选中路线通过现有 route ID 机制联动地图。

## 面板内容

- 研究问题
- 当前假设与支持状态
- 证据与引用数量
- 基线对比
- 关键指标
- 候选集约束最优路线
- 迭代时间线
- 数据限制与代理变量说明
- 研究报告相对路径

## 视觉与可访问性验收

- 桌面与 500×700 窄屏验收。
- 面板不覆盖地图核心控件。
- 键盘可操作。
- 状态不只依赖颜色（配文字或图标）。
- 长标题与引用可换行。
- 无横向溢出。

## 渲染安全

- 模型生成文本只按纯文本渲染（`textContent` 等安全 DOM API）。
- 禁止从未验证的模型文本执行 HTML（不使用 `innerHTML` 注入）。
- 不展示本地绝对路径、模型密钥、内部日志和完整自由文本。

## 新文件与最小接线

新增：

```text
xuhui_route_builder/web/src/research-harness-ui.js
xuhui_route_builder/web/styles/research-harness.css
xuhui_route_builder/tests/research_harness_data_contract.test.mjs
xuhui_route_builder/tests/research_harness_ui_contract.test.mjs
```

对 `index.html`、`main.js`、`data-loader.js` 只做最小接线。不改写地图核心状态管理。
