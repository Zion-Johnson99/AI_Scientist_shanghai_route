# Qoder 执行总提示词

以下内容可直接复制到 Qoder Quest。开始前在模型选择器中选择 `qwen3.8-max`，施工会话使用高推理档位；生成后的 Harness 调用 Qwen API 时默认使用 `medium`。本版本采用快速一次性施工模式，目标是在一个连续 Quest 中完成全部功能代码，测试与正式验收转入后续 QA 阶段。

---

## 可复制提示词

```text
你正在仓库 Zion-Johnson99/AI_Scientist_shanghai_route 中施工 Qwen-Harness。目标是在现有路线、环境、评价与网页产品基础上，建立一套独立 Python CLI，实现：研究目标输入 → 文献与事实提取 → 知识缺口 → 候选假设 → 假设审查 → 实验设计 → 调用四个现有模块 → 实验分析 → 反馈迭代 → 科学计划与网页产品输出。

零、快速一次性施工模式，本节优先级高于本文后续开发流程以及 03 文档中的逐阶段测试、验收和提交安排：
1. 使用一个主 Quest 连续完成仓库盘点、代码施工、集成和交接，中途不等待阶段确认。
2. 主代理负责共享契约、任务调度、文件所有权、跨模块集成和最终完整性检查。
3. 创建 6 个专职子代理，最多同时运行 3 个：
   - 子代理 1：核心 Harness 平台，负责 CLI、配置、路径、模型、RunStore、SkillRegistry、状态机、恢复和安全子进程。
   - 子代理 2：科研智能层，负责 Qwen 客户端、来源 Adapter、证据、假设、科研 Agent、Prompt 和引用门禁。
   - 子代理 3：模块接入层，负责四个 Adapter 与 evaluation_model_qwen 的 score-candidates 窄接口。
   - 子代理 4：实验与报告层，负责预设画像、变体、指标、统计、反馈、科学计划和网页 payload。
   - 子代理 5：六个项目专属 Skills，负责 SKILL.md、必要 references 和确定性辅助脚本。
   - 子代理 6：网页集成层，负责研究结果面板、数据接线、样式和现有页面最小接入。
4. 第一轮并发子代理 1、5、6；主代理合并共享契约后，第二轮并发子代理 2、3、4；两轮结束后由主代理统一集成。
5. 主代理在每轮开始前划定互斥文件范围。子代理只编辑分配文件，公共模型和共享入口由主代理最终合并。
6. 本轮只完成生产代码、配置、Schema、Prompt、Skills、示例 fixture 和必要文档。新测试、CI workflow、浏览器验收、真实 API smoke、Ruff、Pyright 与完整项目测试统一留给后续 QA 阶段。
7. 最终只运行低成本生成期检查：必需文件完整性、JSON 可解析性、Python 语法编译、新增 JavaScript 语法和 git diff --check。该检查不等同于正式测试。
8. 不创建阶段提交，不推送远程。全部代码完成后保留工作树改动，交给后续 Codex QA、补测、修复和提交。
9. 最终状态统一标记为 implementation_complete_unverified，避免把未测试代码描述为已经验收。
10. 只有真实 Key、外部付费数据、生产部署授权、路线批量重建或未知工作树冲突会阻塞施工；单个子任务受阻时，主代理继续推进其他互不依赖任务并记录阻塞项。

一、先读取并遵循以下文档，顺序固定：
1. docs/qwen-harness-build/00-需求与总体架构.md
2. docs/qwen-harness-build/01-Qwen-Harness详细工程设计.md
3. docs/qwen-harness-build/02-项目专属Skills设计规范.md
4. docs/qwen-harness-build/03-分阶段实施与验收方案.md
5. docs/qwen-harness-build/04-Qoder执行总提示词.md

同时读取：
- README.md
- AGENTS.md
- xuhui_route_builder/README.md
- weather_api_data/README.md
- evaluation_model_qwen/README.md
- 当前 .qoder/skills/optimize-xuhui-routes/SKILL.md

二、工作区要求：
1. 先执行 git rev-parse --show-toplevel、git branch --show-current、git rev-parse HEAD、git status --short、git worktree list。
2. 固定工作树为 D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop，固定分支为从 main 创建的 Qwen_Harness_Build。
3. 核验结果与固定工作树或分支不符时先停止并报告，跳过新 worktree 和新分支创建。
4. 初始允许 docs/qwen-harness-build/** 与 Qwen-Harness/** 中存在预置文档和骨架变更；其他未知改动出现时先停止并报告文件列表。
5. 保持其他 worktree 原状。

三、实现范围：
1. 新建 Qwen-Harness/ 独立 Python 工程，console script 名称为 qwen-harness。
2. 主入口为：
   qwen-harness run --goal "研究目标"
3. 同时实现 doctor、validate、status、resume、report、publish、list-runs。
4. 新建六个项目 Skill，只放在 .qoder/skills：
   - qwen-harness-orchestration
   - scientific-evidence-hypothesis
   - xuhui-route-builder-engineering
   - weather-environment-pipeline
   - evaluation-qwen-experiments
   - web-product-integration
5. Qwen-Harness 只扫描 .qoder/skills，禁止读取 .agents/skills 作为运行时技能源。
6. 保留当前 .agents 旧目录，不在本任务批量删除；新 Skill 不复制到 .agents。
7. 为 evaluation_model_qwen 增加 score-candidates 窄接口，复用现有 load_data、evaluate_risk 和 score_routes，返回全部可行候选，不调用 Qwen，不改变 recommend 的现有行为。
8. 为现有静态网页增加可选的 AI Scientist 实验结果面板，读取 xuhui_route_builder/data/web/research_harness_latest.json。数据缺失时隐藏面板，现有地图、推荐、位置和导航继续运行。
9. 保留离线 CI 的设计接口和后续任务清单，本轮暂缓新增 CI workflow。

四、技术边界：
1. Python 版本保持 >=3.10。
2. 采用 argparse，不引入 CLI 框架。
3. 允许的新运行依赖仅限：openai、pydantic、python-dotenv、requests、pypdf、PyYAML。
4. 不引入 Agent 框架、向量数据库、消息队列、前端框架、构建器、pandas 或浏览器自动化依赖。
5. 现有四个模块通过固定 CLI 与 JSON 契约接入，禁止复制其业务算法。
6. 所有模型输出使用 Pydantic/JSON Schema；解析失败有限重试，禁止自由文本静默回退。
7. 模型只选择预注册操作 ID，无法直接生成和执行 shell 命令。
8. subprocess 使用 argv 列表和 shell=False；可执行文件、cwd、写入路径和超时均受控。
9. 默认只写 Qwen-Harness/runtime。网络、环境刷新和网页发布分别显式授权。
10. 不提交真实 API Key、Workspace ID、.env、runtime 产物或用户绝对路径。
11. Qwen API 默认模型 qwen3.8-max，使用百炼 OpenAI 兼容 Chat API、结构化输出、seed=1234、temperature=0.2、reasoning_effort=medium。reasoning_effort 与 thinking_budget 保持互斥。
12. 每个阶段独立模型调用，阶段间传递结构化结果。内部推理内容不保存，显式 rationale 与审查意见保存。
13. v1 CLI 暂缓公开 --allow-module-write；模块写入通过固定工作流和显式授权控制。
14. v1 暂缓 Skills 白名单、费用上限、多时段快照和消融扩展，只实现五份权威文档已经定义的对照实验。

五、科学边界：
1. 核心假设：在运动方式、目标距离、安全阈值、搜索范围和有限附加距离约束下，多源环境与个性化模型相较最短或 PM2.5 单因素基线，能够降低环境风险并提高偏好匹配度。
2. “最优路线”统一写成“当前候选集中的约束最优路线”。
3. PM2.5 写成网格/站点融合估计；花粉写成日级背景或代理风险；噪声写成 0-100 风险代理。
4. 不开展用户问卷、人工盲评、移动传感器和线下实测。
5. 软件单测、契约测试、集成测试、离线端到端和模块验证进入后续 QA 阶段，本轮生产代码预留稳定接口。
6. 结果不可只用综合 base_score 证明综合模型；需同时比较 PM2.5、噪声、花粉、目标距离偏差、接驳距离、偏好命中、数据可靠度和约束通过率。
7. 引用只来自 SourceRegistry。模型创建的 DOI、PMID、作者、年份、URL 或数值一律由门禁拒绝。
8. 证据不足时输出 inconclusive；部分支持输出 partially_supported；方向相反输出 unsupported。

六、开发流程：
1. 03 文档的阶段 0 到阶段 8 用于确定依赖顺序和完成范围，实际施工采用本提示词的两轮并发调度。
2. 主代理先冻结共享数据模型、CLI 契约、目录边界和文件所有权，再启动子代理。
3. 子代理完成分配代码后立即向主代理交接变更文件、公共接口、依赖假设和遗留风险，不输出测试报告。
4. 主代理持续合并各模块，发现接口冲突时直接统一契约并通知受影响子代理修正。
5. 暂缓 pytest、node --test、Ruff、Pyright、浏览器验证和真实 API smoke，不因缺少测试结果中断代码施工。
6. 保留清晰错误处理、上下文日志、路径边界、密钥脱敏和固定命令模板。
7. 不做无关重构，不批量改名，不改变当前在线推荐与部署行为。
8. 文档与实际代码冲突时，以当前代码契约为事实并记录调整；科学目标、权限边界或数据语义冲突交由主代理统一判断。
9. 本轮不创建提交和 PR，后续 QA 完成测试与修复后再进入提交阶段。
10. 上下文接近限制时主动压缩，保留共享契约、文件所有权、已完成模块、阻塞项和剩余任务后继续施工。

七、离线模式：
1. Qwen-Harness/examples/fixtures 提供固定来源、模型结构化响应、路线样例和环境样例。
2. qwen-harness run --offline --workflow reproduce-existing --goal-file examples/goals/multisource-route.json 在无网络、无 Key 环境完成闭环。
3. 离线结果明确标记 fixture/reproduction，不伪装成新检索结果。
4. 后续 QA 创建 CI 时只运行离线模式。

八、输出要求：
一次完整运行在 Qwen-Harness/runtime/runs/<run-id>/ 生成：
- run_manifest.json
- state.json
- events.jsonl
- source_registry.jsonl
- evidence_cards.jsonl
- 每阶段 input/output/audit
- 四模块 ModuleResult
- experiment_results.json
- metrics_summary.json
- scientific_plan.json
- scientific_plan.md
- experiment_report.md
- reproducibility.md
- research_harness_latest.json

scientific_plan 需覆盖赛题字段：Problem Statement、Rationale、Technical Details、Datasets Source/Target、Paper Title、Paper Abstract、Methods、Experiments、Results、References，并增加 limitations 与 reproducibility。

九、开始步骤：
1. 快速完成阶段 0 的只读仓库盘点，记录 HEAD、分支、worktree、实际目录、现有命令和文档差异，跳过基线测试。
2. 盘点后由主代理冻结共享契约和文件所有权，不等待用户回复。
3. 按快速一次性施工模式启动两轮子代理，持续集成到全部生产代码完成。
4. 单个模块涉及真实 Key、外部付费数据、生产部署授权或路线批量重建时记录为后续阻塞，其他模块继续施工。
5. 完成低成本生成期检查，修复其中发现的语法、JSON 和缺失文件问题。
6. 输出 implementation_complete_unverified 状态、代码清单、未验证风险和后续 QA 清单后结束。

十、最终汇报模板：
- 状态：implementation_complete_unverified
- 主代理和 6 个子代理的实际分工
- 已完成模块与关键入口
- 修改文件与新增文件概览
- 低成本生成期检查结果
- 阻塞项与未验证风险
- 后续 QA、测试和提交清单

现在开始并一次性推进到全部生产代码完成。阶段之间无需等待用户确认，也不输出逐阶段测试报告。
```

---

## 使用方式

### 方式 A：Quest

把上面的整段提示词发送给 Qoder Quest。Quest 会在同一次任务中完成仓库盘点、两轮子代理施工、主代理集成和最终交接，无需在阶段之间手工发送“继续”。

### 方式 B：Qoder CLI

在固定工作树根目录启动：

```powershell
Set-Location -LiteralPath 'D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop'
qoder
```

将提示词粘贴到会话。新 Skill 建立后执行：

```text
/skills reload
/skills
```

### 方式 C：上下文续接

长会话接近上下文限制时，使用 Qoder 的压缩功能保留：

- 当前阶段
- 已完成模块与文件所有权
- 公共接口和契约调整
- 数据契约
- 剩余任务

新会话先读取五份施工文档、主代理压缩摘要和当前 `git diff`，再继续未完成模块。

---

## Qoder 完成后的 Codex 审查提示

```text
请对 Qwen_Harness_Build 中标记为 implementation_complete_unverified 的 Qwen-Harness 实现开展完整 QA。按 docs/qwen-harness-build/00-04 检查状态机、权限、引用门禁、实验独立性、评价窄接口和网页脱敏；先补充可复现测试，再修复发现的问题。完成 pytest、Ruff、Pyright、Node 契约测试、离线端到端和浏览器验证后，给出可合并性判断与剩余科学边界。
```
