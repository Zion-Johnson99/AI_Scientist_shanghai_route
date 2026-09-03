---
name: qwen-harness-orchestration
description: Build, run, inspect, resume, and validate the Qwen-Harness research workflow CLI for the Shanghai Xuhui healthy-route AI Scientist project (Qwen-Harness/). Use for qwen-harness run/doctor/validate/status/resume/report/publish/list-runs, workflow stages and state machine, run records and artifacts, module adapters, quality gates, permission model, feedback iterations, resume/recovery, or CLI packaging.
---

# Qwen-Harness 编排

## Outcome

交付并维护 `Qwen-Harness/`：一条 `qwen-harness run --goal ...` 命令驱动完整科研闭环（研究目标 → 证据 → 缺口 → 假设 → 审查 → 实验设计 → 模块调用 → 结果分析 → 反馈迭代 → 科学计划与网页发布），全部阶段输出结构化、可恢复、可审计。正式运行各阶段统一 `reasoning_effort=medium`，模型为 `qwen3.8-max`（temperature=0.2，seed=1234）。

## When to use

- 新建或修改 `Qwen-Harness/` 的 CLI、配置、状态机、运行目录、模型客户端、Adapter、门禁、恢复和报告。
- 新增或调整工作流阶段（`config/workflows/*.json`）与阶段级权限。
- 修复结构化输出解析、断点恢复、运行锁、权限或审计问题。
- 解释退出码、运行状态或产物结构。
- 不在本 Skill 范围：路线几何/POI 深度修复（用 `optimize-xuhui-routes`）、证据与假设内容生产（用 `scientific-evidence-hypothesis`）、单模块算法（用对应模块 Skill）。

## Authoritative files

```text
Qwen-Harness/pyproject.toml
Qwen-Harness/config/harness.json
Qwen-Harness/config/source_policy.json
Qwen-Harness/config/experiment_variants.json
Qwen-Harness/config/quality_gates.json
Qwen-Harness/config/workflows/full-research.json
Qwen-Harness/config/workflows/research-only.json
Qwen-Harness/config/workflows/reproduce-existing.json
Qwen-Harness/src/qwen_harness/cli.py
Qwen-Harness/src/qwen_harness/run_store.py
Qwen-Harness/src/qwen_harness/subprocess_runner.py
Qwen-Harness/src/qwen_harness/skills.py
Qwen-Harness/src/qwen_harness/workflow/
Qwen-Harness/tests/
docs/qwen-harness-build/00-需求与总体架构.md
docs/qwen-harness-build/01-Qwen-Harness详细工程设计.md
```

> `Qwen-Harness/*` 各路径为施工新增（轮1 核心平台与轮2 各层依次落地），未落地的路径按 01 设计文档 §2 目录树施工；`docs/qwen-harness-build/` 已存在。

先读上述文件再修改；路径、命令、阶段名以 01 设计文档为准。

## Inputs

- 研究目标：`--goal` 文本或 `--goal-file`（JSON，字段见 `schemas/research-goal.schema.json`）。
- 工作流选择：`--workflow full-research|research-only|reproduce-existing`。
- 权限参数：`--offline`、`--allow-network`、`--refresh-environment none|weather|hourly|daily`、`--approval-mode auto|critical|all`、`--publish-web`、`--max-iterations N`。
- 恢复输入：`resume <run-id>`；`status/report` 只读运行目录。
- v1 不提供通用模块写入开关 `--allow-module-write`；不要实现或引用它。

## Outputs

- 运行目录 `Qwen-Harness/runtime/runs/<run-id>/`：`run_manifest.json`、`state.json`、`lock.json`、`events.jsonl`、`sources/`、`skills/`、`stages/<stage>/{input,output,audit}.json`、`modules/{route,environment,evaluation}/result.json`、`experiments/experiment_results.json`、`experiments/metrics_summary.json`、`reports/scientific_plan.{json,md}`、`reports/experiment_report.md`、`reports/reproducibility.md`、`publish/research_harness_latest.json`。
- `run_manifest.json` 必须含：run_id、创建时间、仓库根目录、Git 分支与 HEAD、工作树是否干净、Harness 版本、Python 版本与平台、模型/温度/seed/各阶段推理强度、工作流名称与版本、Skills 文件哈希、配置哈希、模块数据文件哈希、网络与写入权限。
- CLI 错误输出含 `error_type`、`message`、`run_id`、`stage` 和建议动作；禁止输出 API Key、Authorization 头、完整自由文本画像。

## Workflow

1. 读取权威文件与当前 `state.json`，确认任务属于新建、修改、恢复还是检查。
2. 改动前先跑 `python .qoder/skills/qwen-harness-orchestration/scripts/verify_harness_layout.py` 记录基线。
3. 小步修改：一次任务不超过 3 个文件；大文件保持 400 行内；先写失败测试再修实现。
4. 阶段定义改动同步更新 `workflow-contract.md` 与 `run-artifact-contract.md`。
5. 完成后运行离线端到端验证与本地质量命令（见 Commands）。
6. 复跑 verify 脚本，输出 PASS 后再交付。

## Allowed operations

- 读写 `Qwen-Harness/` 内文件（含测试与配置）。
- 读取 `.qoder/skills/` 全部技能内容（技能源边界固定为此目录，不扫描 `.agents/skills` 或用户主目录技能）。
- 读取四个业务模块的稳定产物用于契约校验，不修改模块源码。
- 通过 `SafeSubprocessRunner` 的固定命令模板调用 `uv`、`python`、`node`、`git`；禁止 shell 字符串拼接，模型只能选择预注册操作 ID，不能注入 `argv`。
- 所有写入路径必须通过仓库边界校验；未显式授权时只写 `Qwen-Harness/runtime/`。

## Commands

```powershell
# 离线复现（无网络、无 Key）
uv run --directory Qwen-Harness --frozen --workflow reproduce-existing `
  qwen-harness run --offline --goal-file examples/goals/multisource-route.json

# 正式运行
uv run --directory Qwen-Harness --frozen qwen-harness run --goal "..." [--allow-network]

# 检查与恢复
uv run --directory Qwen-Harness --frozen qwen-harness doctor
uv run --directory Qwen-Harness --frozen qwen-harness validate --scope all
uv run --directory Qwen-Harness --frozen qwen-harness status <run-id> --json
uv run --directory Qwen-Harness --frozen qwen-harness resume <run-id>
uv run --directory Qwen-Harness --frozen qwen-harness report <run-id>
uv run --directory Qwen-Harness --frozen qwen-harness publish <run-id>
uv run --directory Qwen-Harness --frozen qwen-harness list-runs --limit 10

# 本地质量
uv sync --directory Qwen-Harness --extra dev
uv run --directory Qwen-Harness --extra dev pytest -q
uv run --directory Qwen-Harness --extra dev ruff format --check .
uv run --directory Qwen-Harness --extra dev ruff check .
uv run --directory Qwen-Harness --extra dev pyright --pythonpath .venv\Scripts\python.exe

# 布局自检
python .qoder/skills/qwen-harness-orchestration/scripts/verify_harness_layout.py
```

退出码：0 成功；1 门禁未通过或结果不支持假设但程序完整；2 配置/输入/契约错误；3 模型 API 或外部来源故障且无回退；4 模块命令失败；5 运行状态损坏、锁冲突或恢复失败。

## Quality gates

- 离线端到端可运行（`--offline` 无网络、无真实 Key 完成示例闭环）。
- 失败后可恢复：`resume` 从最近成功阶段继续，原子写入（临时文件 → flush → fsync → `os.replace`）。
- 模型无法注入任意命令；可执行文件仅限允许列表。
- 所有阶段有结构化输出（Pydantic + JSON Schema），解析失败走有限重试，不接收自由文本。
- 所有写入路径通过仓库边界校验。
- run manifest 含 Git、Skill、配置和数据哈希。
- pytest、ruff format/check、pyright 全部通过。
- `verify_harness_layout.py` 输出 PASS。

## Failure handling

- 结构化输出校验失败：携带简短校验错误重试 1 次；仍失败记录 `retryable`，不降级为自由文本。
- 连接超时、5xx、限流：最多重试 2 次，指数退避，逐次写入 `ModelCallAudit`。
- 阶段中断且无完整输出：恢复时标记 `retryable`；已通过阶段输入哈希未变则跳过。
- 配置、Skill、Git HEAD 或数据快照漂移：提示新建 run；显式继续时记录漂移。
- 运行锁存活进程存在时拒绝并发恢复。
- 上游故障无回退：按退出码 3 终止并保留已完成产物。

## Stop conditions

- 工作树出现来源未知或超出施工范围的变更（`docs/qwen-harness-build/` 与新建 `Qwen-Harness/` 骨架属于已知输入）。
- 路径解析指向仓库外。
- 新依赖缺少用途/替代方案/体积/维护风险说明（禁止 Agent 框架、向量数据库、消息队列、浏览器自动化框架、大型数据框依赖）。
- 离线 fixture 或状态机测试失败。
- 单个变更同时跨越编排、四个模块和前端——必须拆分。
- 发现需要 `--allow-module-write` 通用开关才能实现目标时停止并上报。

## Handoff

报告：改动文件清单；阶段/状态机/权限变化；新增或修改的命令与退出码；离线端到端结果；`verify_harness_layout.py` 输出；数据哈希与 prompt 版本；失败重试与降级行为；剩余风险。引用契约细节见：

- [references/workflow-contract.md](references/workflow-contract.md)：阶段顺序、状态转换、恢复规则
- [references/run-artifact-contract.md](references/run-artifact-contract.md)：运行目录与 JSON 产物
- [references/permission-model.md](references/permission-model.md)：网络、写入、发布授权
- [references/cli-contract.md](references/cli-contract.md)：命令、参数、退出码
