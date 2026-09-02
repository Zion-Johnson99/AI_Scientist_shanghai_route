# Qwen-Harness

徐汇健康路线 AI Scientist 科研编排工程的施工骨架。Qwen-Harness 是一套确定性的科研
工作流平台：以 `qwen-harness` CLI 驱动「目标 → 证据 → 假设 → 实验设计 →
架构规划 → 逐文件生成 → 模块联调与修复 → 报告 → 本地交付」的固定流水线。
全部中间产物写入 `runtime/runs/<run-id>/`，并通过质量门禁与审批策略约束自动化边界。

权威施工文档位于仓库根目录 `docs/qwen-harness-build/`，阅读顺序：

1. `00-需求与总体架构.md`
2. `01-Qwen-Harness详细工程设计.md`
3. `02-项目专属Skills设计规范.md`
4. `03-分阶段实施与验收方案.md`
5. `04-Qoder执行总提示词.md`

实施分支：`Qwen_Harness_Build`。实施工作树：`D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop`。

## 1. 安装与环境

需要 Python 3.11 与 `uv`。

```powershell
& .\Qwen-Harness\scripts\setup-local.ps1
cd Qwen-Harness
# 编辑 .env，填入真实 DASHSCOPE_API_KEY，并替换 DASHSCOPE_BASE_URL 中的 WorkspaceId
uv run qwen-harness doctor
```

`doctor` 会检查：API Key 是否配置、Base URL、配置目录与三个工作流文件是否可加载、
六个项目专属 Skills 是否存在于仓库 `.qoder/skills/`、`runtime/` 可写性。任何
error 级问题会以非零退出码返回。

## 2. 常用命令

执行一次完整研究（19 阶段全流水线）：

```powershell
uv run qwen-harness run `
  --goal "验证多源环境与有限附加距离约束能否提升个性化路线效用" `
  --workflow full-research `
  --allow-network `
  --approval-mode critical
```

无 API Key 的离线复现（使用 `examples/fixtures/model-responses/` 下的预置夹具）：

```powershell
uv run qwen-harness run --offline --workflow reproduce-existing --goal-file examples/goals/multisource-route.json
```

其他工作流：`--workflow research-only`（14 阶段，跳过模块实验与网页交付）。

继续中断的运行：

```powershell
uv run qwen-harness resume <run-id>
```

确认已通过最终门禁的本地交付包：

```powershell
uv run qwen-harness publish <run-id>
```

进入该运行的 `publish/` 目录并执行 `launch-local.ps1`，随后访问
`http://127.0.0.1:8130/web/`。本地地图与 `data/web` 均来自本次 run 中由千问生成的
`workspace/source/xuhui_route_builder`。仓库现有四个工程只作功能验收基准，发布链路不读取其源码，
也不向原目录写入。

辅助命令：

```powershell
uv run qwen-harness status <run-id>          # 查看状态机与各阶段结果
uv run qwen-harness report <run-id>          # 查看运行摘要与报告产物
uv run qwen-harness list-runs --limit 20     # 列出运行记录
uv run qwen-harness validate --scope all     # 校验 config / skills / adapters / runs
```

## 3. run 命令选项

| 选项 | 说明 |
| --- | --- |
| `--goal` / `--goal-file` | 研究目标（二选一），`--goal-file` 接收 ResearchGoal JSON |
| `--workflow` | `full-research`（默认）/ `research-only` / `reproduce-existing` |
| `--offline` | 离线夹具模式，不调用真实模型、不访问网络 |
| `--allow-network` | 显式允许网络访问（默认禁止，来源采集阶段将跳过或失败） |
| `--refresh-environment` | `none`（默认）/ `weather` / `hourly` / `daily` |
| `--approval-mode` | `auto` / `critical`（默认）/ `all`，见第 5 节 |
| `--max-iterations` | 反馈迭代上限，默认 2 |
| `--publish-web` | 当前本地发布模式无需设置；交付包在最终门禁通过后自动生成 |
| `--run-id` | 复用指定运行目录（用于续跑既有目录） |
| `--json` | 以 JSON 输出摘要 |

## 4. 运行目录结构

每次运行在 `runtime/runs/<run-id>/` 下留下完整证据链：

```text
runtime/runs/<run-id>/
├── run_manifest.json   # 溯源清单：Harness Git 状态、模型参数、配置哈希
├── state.json          # 状态机（各阶段状态、迭代次数、支持结论）
├── lock.json           # 进程锁（含 pid 活性检查）
├── events.jsonl        # 事件流（审计日志，敏感信息自动脱敏）
├── inputs/             # 研究目标与运行选项
├── sources/            # 来源登记与证据卡片（JSONL）
├── skills/             # 本次运行引用的 Skills 快照
├── stages/             # 各阶段 input/output/audit JSON
├── workspace/          # 本次千问生成工作区
│   ├── architecture.json
│   ├── generation_result.json
│   └── source/         # Qwen-Harness 及三个业务模块的新生成源码
├── modules/            # 模块操作结果（按模块/操作分文件）
├── experiments/        # 实验矩阵与指标
├── reports/            # 科学报告与指标摘要
├── checks/             # 功能契约、测试、类型与浏览器验收证据
└── publish/            # 固定本地交付结构
    ├── source/         # 只来自 workspace/source
    ├── local-product/
    │   ├── web/
    │   └── data/web/
    ├── reports/
    │   ├── 完整运行报告.md
    │   ├── 科学计划.md
    │   └── 实验报告.md
    ├── checks/
    ├── source_manifest.json
    └── launch-local.ps1
```

## 5. 审批与权限模式

每个阶段在 `config/workflows/*.json` 中声明审批级别（`none` / `critical` / `always`），
与 `--approval-mode` 组合决定执行行为（v1 为非交互式：不弹窗等待，遇审批阶段时暂停或跳过）：

| 审批模式 | `none` 阶段 | `critical` 阶段 | `always` 阶段 |
| --- | --- | --- | --- |
| `auto` | 直接执行 | 直接执行 | 直接执行 |
| `critical`（默认） | 直接执行 | 有显式授权则执行；否则运行暂停为 `needs_approval`（退出码 0），补授权参数后 `resume` | 本地交付包自动生成 |
| `all` | 直接执行 | 有显式授权则执行；否则暂停为 `needs_approval` | 有显式授权则执行；否则该阶段被跳过 |

显式授权参数按阶段定义：

- `publish_web`：仅构建当前运行目录内的本地交付包，自动放行。
- `module_execution`：`--offline`，或 `--refresh-environment none`（默认），或 `--allow-network`。
- 其他阶段：默认视为已授权。

高风险动作均需显式授权，默认保持关闭：

- 本地发布：只写当前运行的 `publish/`，现有网页产品目录保持只读。
- 网络访问：`run --allow-network`，否则 `run_manifest.json` 记录 `network_enabled=false`，
  来源采集不得发起网络请求。
- 子进程命令：仅允许白名单 `uv` / `python` / `node` / `git`，工作目录被限制在
  仓库或 `runtime/` 边界内。
- 配置修改：反馈循环只允许派生配置补丁（权重、附加距离上限），不改源配置。

## 6. 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功，或运行暂停于审批等待 |
| 1 | 质量门禁未通过 / 结论为不支持 / 审批被拒 |
| 2 | 配置、输入契约、路径越界或 Skills 错误 |
| 3 | 模型不可用（如缺少 API Key）或来源不可用 |
| 4 | 模块命令执行失败（超时、非零退出码） |
| 5 | 运行状态损坏、中断或其他内部错误 |

## 7. 目录约定

- `config/`：平台配置与工作流定义（`harness.json`、`source_policy.json`、
  `quality_gates.json`、`workflows/`）。
- `prompts/`、`schemas/`：提示词与数据契约（第二轮包落地）。
- `src/qwen_harness/`：平台实现（CLI、配置、RunStore、状态机引擎、门禁、子进程运行器）。
- `.qoder/skills/`（仓库根）：六个项目专属 Skills 的唯一扫描位置。
- `runtime/`：全部运行产物，默认被版本控制忽略。
- `examples/`：示例目标与离线夹具。
