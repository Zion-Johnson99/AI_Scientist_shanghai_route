---
name: web-product-integration
description: Turn Qwen-Harness research results into the native HTML/CSS/JS product pages of the Xuhui healthy-route map. Use for research_harness_latest.json payload contract, the AI Scientist research panel (research-harness-ui.js/css), route-id map linkage, hiding the panel when data is missing, frontend contract tests, or payload sensitivity checks (no absolute paths/keys/raw model text).
---

# 网页产品整合

## Outcome

把科研过程和实验结果转换为现有静态网页可读取的产品视图（“AI Scientist 实验”面板），同时保持地图、推荐和导航功能稳定。数据来自 `xuhui_route_builder/data/web/research_harness_latest.json`；文件缺失时页面正常运行并隐藏面板。

## When to use

- 施工或维护研究结果面板（`research-harness-ui.js`、`research-harness.css`）。
- 校验网页 payload 结构（`verify_web_payload.py`）。
- 路线 ID 与地图选中逻辑联动。
- 桌面与 500×700 窄屏验收、可访问性检查。
- 处理面板与现有契约测试的兼容问题。

## Authoritative files

```text
xuhui_route_builder/web/index.html
xuhui_route_builder/web/src/data-loader.js
xuhui_route_builder/web/src/main.js
xuhui_route_builder/web/src/map.js
xuhui_route_builder/web/src/recommendation-ui.js
xuhui_route_builder/web/styles/main.css
xuhui_route_builder/web/styles/recommendation.css
xuhui_route_builder/tests/*.test.mjs
```

> `xuhui_route_builder/data/web/research_harness_latest.json` 为施工新增的发布产物（首次 `qwen-harness publish` 后才存在）；此前页面按缺数据路径运行。

新文件（第一次施工新增）：

```text
xuhui_route_builder/web/src/research-harness-ui.js
xuhui_route_builder/web/styles/research-harness.css
xuhui_route_builder/tests/research_harness_data_contract.test.mjs
xuhui_route_builder/tests/research_harness_ui_contract.test.mjs
```

并对 `index.html`、`main.js` 或 `data-loader.js` 做最小接线。

## Inputs

- `research_harness_latest.json`（由 Harness `web_payload` 阶段发布，经 `qwen-harness publish` 写入）。
- 现有 `route_catalog.json` 与地图选中机制（路线联动）。
- 现有契约测试基线（不得因新面板失败）。

## Outputs

- 研究面板：研究问题、假设与支持状态、证据与引用数量、基线对比、关键指标、候选集约束最优路线、迭代时间线、数据限制与代理变量说明、研究报告相对路径。
- 契约测试：数据契约与 UI 契约两个 `.test.mjs`。
- 面板缺失数据时的隐藏行为（不影响地图与推荐）。

## Workflow

1. 读取权威文件，确认现有加载与渲染链路。
2. 运行 `python .qoder/skills/web-product-integration/scripts/verify_web_payload.py` 校验当前/目标 payload。
3. 实现 `research-harness-ui.js` 与样式；对 `index.html`/`main.js`/`data-loader.js` 只做最小接线。
4. 数据文件存在且通过 Schema → 展示入口；缺失或状态错误 → 隐藏入口。
5. 选中路线通过现有 route ID 机制联动地图，不改写地图核心状态管理。
6. 运行新旧契约测试与浏览器验收（桌面 + 500×700）。

## Allowed operations

- 新增上述四个新文件；最小修改 `index.html`、`main.js`、`data-loader.js` 的接线。
- 读取 `research_harness_latest.json` 与路线目录；只读地图模块状态。
- 用 `textContent`/安全 DOM API 渲染模型生成文本；不执行未验证的 HTML。
- 不引入 React、Vue、构建器或包管理依赖；延续原生 HTML、CSS、JavaScript。

## Commands

```powershell
# 前端契约测试
node --test xuhui_route_builder/tests/*.test.mjs
node --test xuhui_route_builder/tests/research_harness_data_contract.test.mjs
node --test xuhui_route_builder/tests/research_harness_ui_contract.test.mjs

# payload 结构自检
python .qoder/skills/web-product-integration/scripts/verify_web_payload.py

# 路线契约（联动前提）
python .qoder/skills/xuhui-route-builder-engineering/scripts/verify_route_catalog.py
```

## Quality gates

- payload 通过 Schema 校验；`selected_route.route_id` 存在于当前 `route_catalog.json`。
- 数据缺失或错误时页面正常运行，面板隐藏。
- 引用 URL 为 HTTPS 或明确本地来源；`artifacts` 只含仓库相对路径或公开 URL。
- payload 与页面不出现本地绝对路径、模型密钥、内部日志和完整自由文本。
- 桌面与 500×700 窄屏验收通过；面板不覆盖地图核心控件；无横向溢出；长标题与引用可换行。
- 键盘可操作；状态不只依赖颜色。
- 新旧契约测试全部通过。

## Failure handling

- payload 缺失/JSON 错误：隐藏面板，控制台记录一次警告，不影响地图与推荐。
- `selected_route.route_id` 不在目录：不联动地图，展示降级文案。
- 模型文本未验证：只按纯文本渲染，禁止 `innerHTML` 注入。
- 旧契约测试因新面板失败：回退接线，定位冲突后再实施。

## Stop conditions

- 需要改写现有地图核心状态管理。
- 新面板使旧契约测试失败。
- payload 暴露本地路径、Key 或原始模型内部推理。
- 前端从未验证的模型文本直接执行 HTML。
- 需要引入前端框架或构建器才能实现目标。

## Handoff

报告：新增/修改文件清单；面板行为（展示/隐藏/联动）；契约测试结果；桌面与窄屏验收；`verify_web_payload.py` 结果；可访问性检查；剩余风险。细节见：

- [references/web-payload-contract.md](references/web-payload-contract.md)：payload Schema 与脱敏规则
- [references/ui-contract.md](references/ui-contract.md)：面板内容、视觉与可访问性
