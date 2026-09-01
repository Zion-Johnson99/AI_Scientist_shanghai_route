# 项目专属 Skills 设计规范

> 目标：在 `.qoder/skills/` 建立可同时被 Qoder IDE、Qoder CLI 和 `Qwen-Harness` 使用的项目专属技能。新 Harness 只从该目录加载技能。
> 施工环境：工作树 `D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop`，分支 `Qwen_Harness_Build`；权威设计文档位于 `docs/qwen-harness-build/`。

---

## 1. Skill 定位

Skill = 一组稳定的领域操作说明、真实命令、数据契约、修改边界和验收门禁。

本项目采用六个核心 Skill。它们负责告诉模型“每个环节怎样操作”；工作流顺序、权限、状态和重试由 `Qwen-Harness` 控制。

```text
.qoder/skills/
├── qwen-harness-orchestration/
├── scientific-evidence-hypothesis/
├── xuhui-route-builder-engineering/
├── weather-environment-pipeline/
├── evaluation-qwen-experiments/
└── web-product-integration/
```

已有 `optimize-xuhui-routes/` 保留，作为路线几何、POI 和显示验收的深度规则库。

---

## 2. 通用目录规范

每个新 Skill 采用：

```text
<skill-name>/
├── SKILL.md
├── references/
│   ├── contracts.md
│   ├── commands.md
│   ├── failure-modes.md
│   └── examples.md
└── scripts/
    └── verify_*.py
```

并非每个 Skill 都需要四个 reference 文件；只保留高价值内容。`SKILL.md` 控制在模型容易读取的长度，详细 Schema 和命令放到 `references/`。

### 2.1 front matter

```yaml
---
name: qwen-harness-orchestration
description: Build, run, inspect, resume, and validate the Qwen-Harness research workflow for the Shanghai healthy route AI Scientist project. Use for research-goal execution, workflow stages, run records, module adapters, quality gates, feedback iterations, or CLI packaging.
---
```

要求：

- `name` 与目录名一致。
- `description` 包含用户常用关键词、模块名和触发场景。
- 描述使用英文或中英混合均可；正文优先中文，代码与字段保留英文。
- 新会话使用 `/skills reload` 或重启后检查 `/skills`。

### 2.2 `SKILL.md` 固定章节

1. Outcome
2. When to use
3. Authoritative files
4. Inputs
5. Outputs
6. Workflow
7. Allowed operations
8. Commands
9. Quality gates
10. Failure handling
11. Stop conditions
12. Handoff

### 2.3 通用行为规则

- 先读取权威文件，再提出修改。
- 缺少数据时明确标记，不生成占位事实。
- 模块命令使用仓库真实路径和 `uv run --directory`。
- 网络调用仅在显式授权后执行，并记录调用状态、重试和错误。
- 发现 bug 时先增加可复现测试。
- 共享数据文件只允许一个写入者。
- 每批改动保持小范围，完成 focused tests 后再扩大范围。
- 完成前运行 formatter、linter、类型检查和相关测试。
- 结果报告包含输入、输出、命令、数据哈希、异常和剩余风险。

---

## 3. Skill 与 Harness 的共用机制

Qoder 自动根据 `description` 选择 Skill。独立 Harness 采用显式映射：

```json
{
  "hypothesis_generation": [
    "scientific-evidence-hypothesis",
    "qwen-harness-orchestration"
  ],
  "route_module": [
    "xuhui-route-builder-engineering",
    "optimize-xuhui-routes"
  ]
}
```

Harness 加载：

- `SKILL.md`
- 当前阶段显式列出的 reference 文件
- 文件 SHA256

Harness 的技能源边界固定为 `.qoder/skills/`，并按工作流阶段映射加载所需内容，不扫描 `.agents/skills`、用户主目录技能或未知插件技能。v1 暂不实现额外的 Skills 白名单配置与运行时校验。Qoder 会看到仓库中其他既有技能；执行本施工任务时总提示词要求优先使用本文定义的六个项目技能。

---

## 4. `qwen-harness-orchestration`

### 4.1 目标

指导 Qoder 构建和维护 `Qwen-Harness/` 的 CLI、状态机、运行目录、模型调用、Adapter、门禁、恢复和报告。

正式 Harness API 各阶段默认使用 `reasoning_effort=medium`，v1 不设置阶段级高强度覆盖，也不实现模型费用上限模块。

### 4.2 触发场景

- 新建 `Qwen-Harness/`
- 修改 `qwen-harness run`、`resume`、`doctor`、`validate`
- 新增工作流阶段
- 调整运行目录或状态模型
- 接入新的模块 Adapter
- 修复结构化输出、恢复、权限或审计问题

### 4.3 权威文件

```text
Qwen-Harness/config/
Qwen-Harness/src/qwen_harness/workflow/
Qwen-Harness/src/qwen_harness/run_store.py
Qwen-Harness/src/qwen_harness/subprocess_runner.py
Qwen-Harness/src/qwen_harness/skills.py
Qwen-Harness/tests/
docs/qwen-harness-build/00-需求与总体架构.md
docs/qwen-harness-build/01-Qwen-Harness详细工程设计.md
```

### 4.4 `references/`

- `workflow-contract.md`：阶段顺序、状态转换、恢复规则
- `run-artifact-contract.md`：运行目录与 JSON 文件
- `permission-model.md`：网络、Adapter 内部写入授权、发布权限
- `cli-contract.md`：命令、公开参数、退出码；v1 不公开通用参数 `--allow-module-write`

### 4.5 建议脚本

`scripts/verify_harness_layout.py`：

- 检查必需目录和文件。
- 检查 `pyproject.toml` console script。
- 检查 workflow 配置中的 handler 与 Skill 名称。
- 检查 `.env.example` 无密钥。
- 检查 runtime 被 `.gitignore` 排除。

### 4.6 质量门禁

- 离线端到端可运行。
- 失败后可恢复。
- 模型无法注入任意命令。
- 所有阶段有结构化输出。
- 所有写入路径通过仓库边界校验。
- run manifest 含 Git、Skill、配置和数据哈希。

### 4.7 停止条件

- 工作树出现来源未知或超出本施工范围的变更。`docs/qwen-harness-build/` 与新建 `Qwen-Harness/` 骨架属于已知施工输入。
- Qwen-Harness 路径解析指向仓库外。
- 新依赖缺少方案说明。
- 离线 fixture 或状态机测试失败。
- 变更同时跨越编排、四个模块和前端，需拆分。

---

## 5. `scientific-evidence-hypothesis`

### 5.1 目标

把研究目标转成可追踪证据、知识缺口、可证伪假设和预注册实验计划。

### 5.2 触发场景

- 论文和政策来源收集
- PDF、摘要与仓库资料提取
- 事实卡片
- 研究缺口
- 假设生成与批判
- 引用真实性核验
- 科学计划的 References 与 Rationale

### 5.3 权威来源

- 用户提供文件
- PubMed 元数据与摘要
- Crossref DOI 元数据
- 官方政府或数据平台页面
- 仓库中可追溯的代码、配置和数据产物

### 5.4 `SKILL.md` 要求

正文需明确：

1. 先建立 `SourceRecord`，后生成 Claim。
2. Claim 只引用已注册来源。
3. 知识缺口需由多个 Claim 或明确单一局限支持。
4. 假设含机制、变量、方向、反证条件、数据需求和风险。
5. 参考论文只从来源注册表生成。
6. 证据不足时返回缺口，不补写作者、DOI、PMID 或数值。
7. 结果区分事实、估计、代理和推断。

### 5.5 `references/`

- `evidence-schema.md`
- `hypothesis-rubric.md`
- `citation-policy.md`
- `source-adapters.md`
- `contest-output-fields.md`

### 5.6 建议脚本

- `scripts/validate_source_registry.py`
- `scripts/validate_evidence_links.py`
- `scripts/validate_scientific_plan.py`

脚本只做确定性校验，不调用模型。

### 5.7 假设评分 Rubric

| 维度 | 分值 | 核心检查 |
| --- | ---: | --- |
| 科学价值 | 0-25 | 是否针对真实缺口 |
| 新颖性 | 0-20 | 是否超出 PM2.5 单因素 |
| 可证伪性 | 0-20 | 失败条件是否清楚 |
| 数据可得性 | 0-15 | 当前模块能否支持 |
| 工程落地 | 0-10 | 是否能进入产品 |
| 表述边界 | 0-10 | 是否避免夸大 |

总分只是选择辅助，Critic 仍需列出反例和数据风险。

### 5.8 停止条件

- 核心引用无法核验。
- 假设依赖本阶段缺失的实测数据且无代理方案。
- 输出把代理噪声写成实时分贝。
- 输出把网格 PM2.5 写成道路实测值。
- 输出宣称全路网全局最优。

---

## 6. `xuhui-route-builder-engineering`

### 6.1 目标

指导 Harness 安全读取、验收、快照和按需维护路线模块，并向实验引擎提供稳定路线契约。

### 6.2 与现有 Skill 的关系

- 本 Skill 负责模块级接口、数据契约、命令和 Harness Adapter。
- `optimize-xuhui-routes` 负责 90 条路线的几何、重复、距离带、真实节点、POI 和视觉验收。
- 发现具体路线缺陷时同时加载两个 Skill。

### 6.3 权威文件

```text
xuhui_route_builder/src/xuhui_route_builder/models.py
xuhui_route_builder/src/xuhui_route_builder/validation.py
xuhui_route_builder/src/xuhui_route_builder/cli.py
xuhui_route_builder/data/web/route_catalog.json
xuhui_route_builder/data/web/xuhui_routes.geojson
xuhui_route_builder/tests/
.qoder/skills/optimize-xuhui-routes/
```

### 6.4 输入输出契约

输入：

- 操作 ID
- 路线目录路径
- 是否允许网络
- Adapter 内部模块写入授权，来源为显式工作流操作，不接受 CLI 通用开关
- run 输出目录

输出 `RouteModuleResult`：

- 总路线数与模式分布
- 验收状态分布
- 距离带分布
- 几何与目录 ID 一致性
- 数据哈希
- 命令审计
- 警告和阻塞项

### 6.5 固定命令

```powershell
uv run --directory xuhui_route_builder --frozen xuhui-route-builder validate-seeds
uv run --directory xuhui_route_builder --frozen xuhui-route-builder validate-routes
uv run --directory xuhui_route_builder --frozen xuhui-route-builder export-candidates
uv run --directory xuhui_route_builder --frozen --extra dev pytest -q
node --test xuhui_route_builder/tests/*.test.mjs
```

### 6.6 修改边界

- 科研运行默认不生成路线。
- 实验使用稳定的 90 条路线快照。
- 路线修复先写测试，再修改种子、生成或验证逻辑。
- 不为命中 POI 改变路线几何。
- 保留 GCJ-02 与 WGS84 的明确声明。

### 6.7 质量门禁

- 90 条路线。
- 每种模式 30 条。
- 路线目录与 GeoJSON ID 一致。
- 无重复 ID。
- 选中最优路线存在且通过验收。
- 快照记录 SHA256 与 Git HEAD。

---

## 7. `weather-environment-pipeline`

### 7.1 目标

指导 Harness 预检、刷新、读取和解释天气、AQI、PM2.5、花粉、噪声与路线暴露数据。

### 7.2 权威文件

```text
weather_api_data/src/weather_api_data/cli.py
weather_api_data/src/weather_api_data/pipeline.py
weather_api_data/src/weather_api_data/pm25_fusion.py
weather_api_data/src/weather_api_data/pollen_model.py
weather_api_data/src/weather_api_data/noise_model.py
weather_api_data/src/weather_api_data/route_environment.py
weather_api_data/src/weather_api_data/web_export.py
weather_api_data/config/
weather_api_data/tests/
```

### 7.3 数据语义

- PM2.5：格网与站点融合估计。
- 花粉：日级网格背景，可能含代理修正。
- 噪声：0-100 风险代理，来源于道路与空间特征。
- `partial`：部分来源或字段缺失。
- `stale`：沿用上一份有效快照。
- `estimated`：模型或代理估计。

Skill 需要求所有报告保留 `business_time`、`valid_until`、`status`、`spatial_scale`、`estimated`、`confidence`、`unit`。

### 7.4 固定命令

```powershell
uv run --directory weather_api_data --frozen weather-api-data config-check
uv run --directory weather_api_data --frozen weather-api-data dry-run
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier weather
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier hourly
uv run --directory weather_api_data --frozen --extra chap weather-api-data scheduled-refresh --tier daily
uv run --directory weather_api_data --frozen weather-api-data publish-web
```

### 7.5 网络与回退

- `config-check` 和 `dry-run` 先于刷新。
- 缺 Key 时使用 last-known-good，不创建填充值。
- 上游异常时记录错误类型、来源、尝试次数与回退快照。
- API 硬限额、429、超时簇触发停止。
- 每次实验冻结环境快照，后续迭代需要新快照时显式记录。

### 7.6 建议脚本

`scripts/verify_environment_snapshot.py` 检查：

- dashboard 顶层结构
- 90 条路线环境 ID
- 时间字段
- status 枚举
- 单位与估计标记
- 缺失率
- 绝对路径和敏感字段

---

## 8. `evaluation-qwen-experiments`

### 8.1 目标

指导评价模块的硬约束、五维评分、候选导出、基线矩阵、千问审核和结果审计。

### 8.2 权威文件

```text
evaluation_model_qwen/src/evaluation_model_qwen/models.py
evaluation_model_qwen/src/evaluation_model_qwen/constraints.py
evaluation_model_qwen/src/evaluation_model_qwen/scoring.py
evaluation_model_qwen/src/evaluation_model_qwen/service.py
evaluation_model_qwen/src/evaluation_model_qwen/qwen_client.py
evaluation_model_qwen/config/default_weights.json
evaluation_model_qwen/tests/
```

### 8.3 核心规则

- Python 负责硬约束、风险暂停和基础分。
- Qwen 只审核候选与生成解释，不重算硬约束。
- 实验候选导出使用新增 `score-candidates`，返回全部可行候选。
- 基线规则由 Harness 预注册，模型无法临时改动。
- 结果同时报告原始指标、维度分、数据可靠度和约束状态。
- 千问服务异常时保留 Python 结果和完整审计。

### 8.4 新接口施工

新增：

```text
score-candidates --profile --weights --route-catalog --environment-dashboard --json
```

实现顺序：

1. 先为当前缺口增加 CLI 失败测试。
2. 新建 `CandidateScoreResult`。
3. 增加 service 层函数，复用已有评分。
4. 接入 CLI。
5. 添加路径、Schema、暂停、无候选和全候选测试。

### 8.5 实验变体

以下变体仅用于验证核心假设所需的最小基线对比，v1 暂不扩展为系统性消融实验，也不引入多时段环境快照实验。

- `B0_shortest_feasible`
- `B1_pm25_only`
- `B2_multi_environment`
- `B3_non_personalized`
- `M1_personalized_constrained`

### 8.6 停止条件

- 实验逻辑复制 `score_routes`。
- Qwen 输出修改硬约束或候选 ID。
- 评价使用过期数据却未标记。
- 最终结论只依据 `base_score`。
- 权重变化未记录 before/after。

---

## 9. `web-product-integration`

### 9.1 目标

把科研过程和实验结果转换为现有静态网页可读取的产品视图，同时保持地图、推荐和导航功能稳定。

### 9.2 技术约束

- 延续原生 HTML、CSS、JavaScript。
- 不引入 React、Vue、构建器或包管理依赖。
- 数据来自 `research_harness_latest.json`。
- 页面缺少科研数据时正常运行。
- 选中路线通过现有 route ID 机制联动地图。

### 9.3 权威文件

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

### 9.4 新文件

```text
xuhui_route_builder/web/src/research-harness-ui.js
xuhui_route_builder/web/styles/research-harness.css
xuhui_route_builder/tests/research_harness_data_contract.test.mjs
xuhui_route_builder/tests/research_harness_ui_contract.test.mjs
```

### 9.5 UI 内容

- 研究问题
- 当前假设与支持状态
- 证据与引用数量
- 基线对比
- 关键指标
- 候选集约束最优路线
- 迭代时间线
- 数据限制与代理变量说明
- 研究报告相对路径

### 9.6 视觉与可访问性

- 桌面与 500×700 窄屏验收。
- 面板不覆盖地图核心控件。
- 键盘可操作。
- 状态不只依赖颜色。
- 长标题与引用可换行。
- 无横向溢出。

### 9.7 停止条件

- 需要改写现有地图核心状态管理。
- 新面板使旧契约测试失败。
- payload 暴露本地路径、Key 或原始模型内部推理。
- 前端从未验证的模型文本直接执行 HTML。

---

## 10. Skill 验收清单

每个 Skill 完成后检查：

- [ ] 路径为 `.qoder/skills/<name>/SKILL.md`
- [ ] front matter 有 `name` 和 `description`
- [ ] `name` 与目录一致
- [ ] 描述包含明确触发词
- [ ] 权威文件路径真实存在
- [ ] 命令来自当前仓库
- [ ] 输入输出与 Harness 模型一致
- [ ] 修改边界和停止条件明确
- [ ] reference 链接有效
- [ ] verify 脚本无网络依赖
- [ ] `/skills reload` 后可见
- [ ] Harness `validate --scope skills` 通过

---

## 11. 维护规则

- Schema、命令或路径变化时，同一 PR 更新相关 Skill。
- Skill 的数值门禁尽量引用单一 reference 文件。
- 高频评审反馈沉淀进 Skill 或规则文件。
- 删除失效命令和过期路径。
- Skill 更新进入 run manifest，旧运行仍保留当时快照。
- 新增 Skill 前先判断现有六个 Skill 能否承载，避免粒度过碎。
