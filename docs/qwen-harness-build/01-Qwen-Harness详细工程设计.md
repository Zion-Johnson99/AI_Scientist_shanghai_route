# Qwen-Harness 详细工程设计

> 本文给出 `Qwen-Harness/` 的文件级施工规范。实现者按本文建立目录、类、函数、数据协议、CLI、工作流、模块 Adapter、实验引擎、报告与网页发布接口。

施工基线：权威设计文档位于 `docs/qwen-harness-build/`，目标分支为 `Qwen_Harness_Build`，工作树为 `D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop`。所有仓库相对路径均以该工作树根目录为起点。

---

## 1. 设计原则

1. **确定性编排优先**：阶段顺序、工具命令、输入输出和质量门禁由 Python 控制，模型只在定义好的推理节点工作。
2. **结构化输出优先**：所有 Agent 结果使用 Pydantic 模型与 JSON Schema，解析失败进入有限重试，禁止悄悄接收自由文本。
3. **现有模块为事实来源**：路线、环境、评价和网页模块继续负责真实计算。Harness 通过 Adapter 和 JSON 契约接入。
4. **单一技能源**：只扫描仓库根目录 `.qoder/skills/`。每次运行记录加载 Skill 的路径、名称和 SHA256。
5. **默认只读**：未显式授权时，Harness 只写入自身 `runtime/`。环境刷新、路线生成和网页发布分别受参数控制。
6. **可恢复**：每个阶段采用原子写入，状态机允许断点继续；重复运行同一阶段时使用幂等规则。
7. **引用受控**：模型只引用来源注册表中的 `source_id`，报告生成前再次核验。
8. **研究结论受边界约束**：输出使用候选集约束最优、暴露估计和代理风险等准确术语。

---

## 2. 完整目录树

```text
Qwen-Harness/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── config/
│   ├── harness.json
│   ├── source_policy.json
│   ├── experiment_variants.json
│   ├── quality_gates.json
│   └── workflows/
│       ├── full-research.json
│       ├── research-only.json
│       └── reproduce-existing.json
├── prompts/
│   ├── problem-framer.md
│   ├── evidence-extractor.md
│   ├── gap-analyst.md
│   ├── hypothesis-generator.md
│   ├── hypothesis-critic.md
│   ├── experiment-planner.md
│   ├── result-analyst.md
│   ├── feedback-planner.md
│   └── report-writer.md
├── schemas/
│   ├── research-goal.schema.json
│   ├── evidence-card.schema.json
│   ├── knowledge-gap.schema.json
│   ├── hypothesis-set.schema.json
│   ├── experiment-plan.schema.json
│   ├── module-result.schema.json
│   ├── iteration-decision.schema.json
│   ├── scientific-plan.schema.json
│   └── web-payload.schema.json
├── examples/
│   ├── goals/
│   │   └── multisource-route.json
│   ├── source-manifest.json
│   └── fixtures/
│       ├── sources/
│       ├── model-responses/
│       ├── route-catalog.sample.json
│       ├── route-geometry.sample.geojson
│       └── environment-dashboard.sample.json
├── src/
│   └── qwen_harness/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── paths.py
│       ├── errors.py
│       ├── logging_utils.py
│       ├── models.py
│       ├── subprocess_runner.py
│       ├── provenance.py
│       ├── run_store.py
│       ├── skills.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── prompts.py
│       │   └── audit.py
│       ├── sources/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── local_files.py
│       │   ├── pubmed.py
│       │   ├── crossref.py
│       │   ├── web.py
│       │   └── repository.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── problem_framer.py
│       │   ├── evidence_agent.py
│       │   ├── gap_agent.py
│       │   ├── hypothesis_agent.py
│       │   ├── critic_agent.py
│       │   ├── experiment_agent.py
│       │   ├── result_agent.py
│       │   ├── feedback_agent.py
│       │   └── report_agent.py
│       ├── workflow/
│       │   ├── __init__.py
│       │   ├── engine.py
│       │   ├── registry.py
│       │   ├── stages.py
│       │   ├── gates.py
│       │   └── resume.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── route_builder.py
│       │   ├── environment_data.py
│       │   ├── evaluation_model.py
│       │   └── web_product.py
│       ├── experiments/
│       │   ├── __init__.py
│       │   ├── profiles.py
│       │   ├── variants.py
│       │   ├── metrics.py
│       │   ├── runner.py
│       │   └── statistics.py
│       └── reporting/
│           ├── __init__.py
│           ├── scientific_plan.py
│           ├── markdown.py
│           └── web_payload.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   └── e2e/
└── runtime/
    └── .gitkeep
```

### 2.1 文件数量控制

施工按阶段创建。一次任务修改超过 3 个文件时，先拆成子任务；每个子任务围绕一条可验证链路。大文件优先控制在 400 行以内，超出后按职责拆分。

---

## 3. 依赖设计

`pyproject.toml`：

```toml
[project]
name = "qwen-harness"
version = "0.1.0"
description = "Qwen AI Scientist harness for multisource healthy route research"
requires-python = ">=3.10"
dependencies = [
  "openai>=2.0,<3",
  "pydantic>=2.0,<3",
  "python-dotenv>=1.0,<2",
  "requests>=2.31,<3",
  "pypdf>=6.0,<7",
  "PyYAML>=6.0,<7",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pyright>=1.1.411",
  "ruff>=0.16.3",
]

[project.scripts]
qwen-harness = "qwen_harness.cli:main"
```

依赖理由：

| 依赖 | 用途 | 替代方案与取舍 |
| --- | --- | --- |
| `openai` | 百炼 OpenAI 兼容 Chat API 与结构化输出 | 直接 HTTP 会增加错误处理与响应解析工作 |
| `pydantic` | 阶段模型、Schema、配置与输出校验 | 手写校验难以覆盖嵌套字段和错误位置 |
| `python-dotenv` | 本地空壳配置 | 现有三个模块已采用相同方式 |
| `requests` | PubMed、Crossref、允许列表网页与健康检查 | 标准库可实现，但重试与状态处理较繁琐 |
| `pypdf` | 提取可搜索 PDF 的页级文本 | v1 不做 OCR；避免引入重量级渲染库 |
| `PyYAML` | 安全读取 Skill 的 YAML front matter | 手写解析容易破坏多行字段和转义 |

禁止添加 Agent 框架、向量数据库、消息队列、浏览器自动化框架和大型数据框依赖。v1 的目标是可复现工作流，复杂扩展在后续 PR 评估。

---

## 4. 环境变量与配置

### 4.1 `.env.example`

```dotenv
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
QWEN_HARNESS_MODEL=qwen3.8-max
QWEN_HARNESS_TIMEOUT_SECONDS=180
QWEN_HARNESS_NETWORK_ENABLED=false
QWEN_HARNESS_MAX_ITERATIONS=2
QWEN_HARNESS_DEFAULT_REASONING_EFFORT=medium
QWEN_HARNESS_RUNTIME_ROOT=runtime
```

真实 Key、Workspace ID 和私人路径均不进入 Git。`doctor` 检测空值与 `<WorkspaceId>` 占位符。

### 4.2 `config/harness.json`

建议字段：

```json
{
  "schema_version": "1.0",
  "model": {
    "name": "qwen3.8-max",
    "temperature": 0.2,
    "seed": 1234,
    "default_reasoning_effort": "medium",
    "stage_reasoning_effort": {
      "problem_framing": "medium",
      "evidence_extraction": "medium",
      "gap_analysis": "medium",
      "hypothesis_generation": "medium",
      "hypothesis_critique": "medium",
      "experiment_design": "medium",
      "result_analysis": "medium",
      "feedback": "medium",
      "report": "medium"
    }
  },
  "runtime": {
    "max_iterations": 2,
    "atomic_writes": true,
    "approval_mode": "critical",
    "command_timeout_seconds": 900
  },
  "paths": {
    "skills_root": "../.qoder/skills",
    "route_module": "../xuhui_route_builder",
    "environment_module": "../weather_api_data",
    "evaluation_module": "../evaluation_model_qwen",
    "web_root": "../xuhui_route_builder/web",
    "web_data_root": "../xuhui_route_builder/data/web"
  }
}
```

正式 Harness API 的默认推理强度统一为 `medium`，单次模型调用超时设为 180 秒。Qoder 施工阶段可使用 `high` 提升工程分析深度，该设置只影响施工助手，不改变 Harness 运行期模型配置。

所有相对路径以 `Qwen-Harness/` 为基准解析，再验证解析结果位于仓库根目录内。

### 4.3 `config/source_policy.json`

至少包含：

- 允许的来源类型：`local_file`、`pubmed`、`crossref`、`https_url`、`repository_file`
- 默认允许域名
- 最大下载字节数
- PDF 最大页数
- 单来源短摘录长度上限
- 请求间隔与重试次数
- 用户代理字符串
- 许可与访问时间字段要求

网络来源只允许 HTTPS。URL 中含用户名、密码或片段时拒绝。

---

## 5. CLI 设计

### 5.1 主命令

```powershell
qwen-harness run --goal "..."
```

完整参数：

```text
qwen-harness run
  --goal TEXT | --goal-file PATH
  [--workflow full-research|research-only|reproduce-existing]
  [--offline]
  [--allow-network]
  [--refresh-environment none|weather|hourly|daily]
  [--approval-mode auto|critical|all]
  [--max-iterations N]
  [--publish-web]
  [--run-id ID]
  [--json]
```

约束：

- `--goal` 与 `--goal-file` 二选一。
- `--offline` 会关闭模型 API 和外部网络，并从 `examples/fixtures/` 读取固定响应。
- `--publish-web` 只在最终质量门禁通过后执行。
- `--refresh-environment` 的非 `none` 值要求 `--allow-network`。
- v1 不公开模块写入开关；路线候选导出与路线生成操作均保持禁用，只保留 Adapter 内部能力供后续版本接线。

### 5.2 辅助命令

```text
qwen-harness doctor
qwen-harness validate [--scope config|skills|adapters|runs|all]
qwen-harness status <run-id> [--json]
qwen-harness resume <run-id> [--publish-web]
qwen-harness report <run-id>
qwen-harness publish <run-id>
qwen-harness list-runs [--limit N]
```

### 5.3 退出码

| 退出码 | 含义 |
| ---: | --- |
| 0 | 成功 |
| 1 | 质量门禁未通过或研究结果不支持假设，但程序运行完整 |
| 2 | 配置、输入或数据契约错误 |
| 3 | 模型 API 或外部来源故障，且无可用回退 |
| 4 | 模块命令失败 |
| 5 | 运行状态损坏、并发锁冲突或恢复失败 |

CLI 错误输出包含 `error_type`、`message`、`run_id`、`stage` 和建议动作。禁止输出 API Key、Authorization 头和完整自由文本画像。

---

## 6. 核心数据模型

所有模型继承：

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

### 6.1 研究输入

```python
class ResearchGoal(StrictModel):
    title: str
    question: str
    domain: str = "urban_environmental_health"
    region: str = "Shanghai Xuhui"
    target_population: str = "outdoor walkers, runners and cyclists"
    desired_outcome: str
    constraints: list[str]
    seed_sources: list[str]
```

`goal-file` 示例需固定核心方向：

- 多源环境暴露
- 目标距离
- 有限附加距离
- 个性化偏好
- 候选集约束最优

### 6.2 来源与证据

```python
class SourceRecord(StrictModel):
    source_id: str
    source_type: Literal["local_file", "pubmed", "crossref", "https_url", "repository_file"]
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    pmid: str | None
    url: str | None
    local_path: str | None
    accessed_at: datetime
    sha256: str
    license_note: str
    verification_status: Literal["verified", "partial", "unverified", "rejected"]
```

```python
class EvidenceClaim(StrictModel):
    claim_id: str
    source_id: str
    claim: str
    evidence_location: str
    short_excerpt: str | None
    evidence_type: Literal["result", "method", "dataset", "limitation", "definition", "policy"]
    support_strength: Literal["high", "medium", "low"]
    caveats: list[str]
```

短摘录用于定位证据，长度由 `source_policy.json` 控制。完整报告优先使用转述。

### 6.3 知识缺口

```python
class KnowledgeGap(StrictModel):
    gap_id: str
    statement: str
    supported_by_claim_ids: list[str]
    affected_variables: list[str]
    why_unresolved: str
    available_data: list[str]
    missing_data: list[str]
    testability: Literal["high", "medium", "low"]
    product_relevance: Literal["high", "medium", "low"]
```

### 6.4 假设

```python
class HypothesisCandidate(StrictModel):
    hypothesis_id: str
    statement: str
    mechanism: str
    independent_variables: list[str]
    dependent_variables: list[str]
    moderators: list[str]
    expected_direction: str
    falsification_criteria: list[str]
    required_data: list[str]
    supporting_claim_ids: list[str]
    novelty_argument: str
    feasibility_score: float
    scientific_value_score: float
    risks: list[str]
```

`HypothesisSet` 包含 3 个候选和推荐项。Critic 输出逐项审查、冲突、缺证据项和最终选择。

### 6.5 实验计划

```python
class BaselineSpec(StrictModel):
    baseline_id: str
    name: str
    selection_rule: str
    required_fields: list[str]

class MetricSpec(StrictModel):
    metric_id: str
    name: str
    direction: Literal["higher", "lower", "target"]
    formula: str
    primary: bool
    data_source: str

class ExperimentPlan(StrictModel):
    hypothesis_id: str
    profiles: list[dict[str, object]]
    baselines: list[BaselineSpec]
    variants: list[str]
    metrics: list[MetricSpec]
    detour_limit: float
    target_distance_tolerance: float
    module_operations: list[dict[str, object]]
    acceptance_criteria: list[str]
    stop_conditions: list[str]
```

### 6.6 模块结果

```python
class CommandAudit(StrictModel):
    command_id: str
    argv: list[str]
    cwd: str
    started_at: datetime
    finished_at: datetime
    exit_code: int
    stdout_path: str
    stderr_path: str
    timeout: bool

class ModuleResult(StrictModel):
    module: Literal["route", "environment", "evaluation", "web"]
    status: Literal["ok", "partial", "skipped", "error"]
    input_artifacts: list[str]
    output_artifacts: list[str]
    data_hashes: dict[str, str]
    commands: list[CommandAudit]
    warnings: list[str]
    errors: list[str]
```

### 6.7 迭代与最终计划

```python
class IterationDecision(StrictModel):
    status: Literal["continue", "stop_supported", "stop_partial", "stop_unsupported", "stop_inconclusive"]
    reason: str
    automatic_actions: list[dict[str, object]]
    proposed_code_changes: list[dict[str, object]]
    next_iteration_goal: str | None
```

`ScientificPlan` 字段与赛题要求一一对应，并附加：

- `evidence_map`
- `limitations`
- `reproducibility`
- `run_id`
- `git_head`
- `data_snapshot_hashes`

---

## 7. 运行目录与原子存储

### 7.1 目录

```text
runtime/runs/<run-id>/
├── run_manifest.json
├── state.json
├── lock.json
├── events.jsonl
├── inputs/
├── sources/
├── skills/
├── stages/
├── modules/
├── experiments/
├── reports/
└── publish/
```

### 7.2 `run_manifest.json`

至少记录：

- `run_id`
- 创建时间
- 仓库根目录
- Git 分支与 HEAD
- 工作树是否干净
- Harness 版本
- Python 版本与平台
- 模型、温度、seed、各阶段推理强度
- 工作流名称与版本
- Skills 文件哈希
- 配置文件哈希
- 模块数据文件哈希
- 网络与写入权限

### 7.3 `RunStore`

核心接口：

```python
class RunStore:
    def create_run(self, goal: ResearchGoal, options: RunOptions) -> RunContext: ...
    def load_run(self, run_id: str) -> RunContext: ...
    def write_json_atomic(self, relative_path: str, value: object) -> Path: ...
    def append_event(self, event: RunEvent) -> None: ...
    def write_stage_output(self, stage: str, value: StrictModel) -> Path: ...
    def acquire_lock(self) -> None: ...
    def release_lock(self) -> None: ...
```

原子写入流程：同目录临时文件 → `flush` → `fsync` → `os.replace`。恢复时校验 `state.json` 和阶段输出的 SHA256。

---

## 8. SkillRegistry

文件：`src/qwen_harness/skills.py`

```python
class SkillDocument(StrictModel):
    name: str
    description: str
    root: Path
    skill_path: Path
    body: str
    referenced_files: list[Path]
    sha256: str

class SkillRegistry:
    def __init__(self, repository_root: Path) -> None: ...
    def discover(self) -> dict[str, SkillDocument]: ...
    def require(self, names: list[str]) -> list[SkillDocument]: ...
    def load_reference(self, skill_name: str, relative_path: str) -> str: ...
    def snapshot(self, run_store: RunStore, names: list[str]) -> list[Path]: ...
```

规则：

1. 技能根目录固定为 `<repo>/.qoder/skills`。
2. 每个技能目录需存在 `SKILL.md`。
3. 使用 `yaml.safe_load` 读取 front matter，仅接受 `name` 和 `description` 等声明字段。
4. `name` 与目录名一致。
5. 引用文件解析后仍位于当前 Skill 目录。
6. 每个阶段由工作流配置显式列出 Skill 名称，避免模型自行加载大量无关技能。
7. 独立 CLI 将 Skill 内容注入阶段系统上下文；Qoder IDE 仍按官方机制自动发现同一份 Skill。

---

## 9. Qwen 模型客户端

文件：`src/qwen_harness/llm/client.py`

```python
class QwenModelClient:
    @classmethod
    def from_env(cls, settings: HarnessSettings) -> "QwenModelClient": ...

    def generate_structured(
        self,
        *,
        stage_name: str,
        system_prompt: str,
        user_payload: dict[str, object],
        output_model: type[ModelT],
        prompt_version: str,
    ) -> tuple[ModelT, ModelCallAudit]: ...
```

调用要求：

- `model="qwen3.8-max"`
- OpenAI 兼容 Chat API
- `response_format` 使用 Pydantic `parse` 或 JSON Schema
- `temperature=0.2`
- `seed=1234`
- `extra_body` 只设置 `enable_thinking`、`reasoning_effort`、`preserve_thinking=false`
- `reasoning_effort` 与 `thinking_budget` 不同时设置
- 每个阶段独立调用，阶段间通过结构化产物传递上下文
- 内部推理内容不写入运行目录；显式 `rationale`、`mechanism` 和审查意见进入输出模型

重试规则：

- 连接超时、5xx、限流：最多 2 次，指数退避并记录每次审计。
- JSON Schema 或 Pydantic 校验失败：携带简短校验错误重试 1 次。
- 引用不存在、输出越权或字段语义冲突：由质量门禁处理，不以自由文本回退。

`ModelCallAudit` 记录模型、请求 ID、延迟、输入输出 token、prompt 版本、Skill 哈希和错误类型。

---

## 10. Prompt 设计

每个 `prompts/*.md` 包含：

1. 角色边界
2. 允许使用的输入
3. 输出模型说明
4. 引用规则
5. 禁止行为
6. 自检清单

统一系统片段：

- 只依据输入中的来源记录、证据卡和模块结果。
- 来源不足时输出证据缺口。
- 引用使用 `source_id` 或 `claim_id`。
- 避免创建 DOI、PMID、作者、年份和数据值。
- 结论区分观测事实、模型估计、代理变量和推断。
- 产品说明使用当前候选集约束最优。

`PromptBuilder`：

```python
class PromptBuilder:
    def load_template(self, name: str) -> str: ...
    def build_system_prompt(
        self,
        template_name: str,
        skills: list[SkillDocument],
        stage_contract: str,
    ) -> str: ...
```

Prompt 版本由文件 SHA256 的短值生成，进入审计。

---

## 11. 来源采集与引用核验

### 11.1 SourceAdapter 接口

```python
class SourceAdapter(Protocol):
    source_type: str
    def collect(self, request: SourceRequest) -> list[SourceRecord]: ...
    def extract_text(self, source: SourceRecord) -> ExtractedDocument: ...
```

### 11.2 本地文件

支持：`.md`、`.txt`、`.json`、可搜索 `.pdf`。

`LocalFileSource`：

- 限定路径位于仓库或用户显式允许的输入目录。
- PDF 使用 `pypdf` 按页提取。
- 记录页数、每页字符数和 SHA256。
- 页面无文本时标记 `requires_ocr`，v1 停止该来源并报告。

### 11.3 PubMed

`PubMedSource` 使用 E-utilities：

- ESearch 获取 PMID。
- EFetch 获取标题、作者、年份、摘要、期刊和 DOI。
- 按 `source_policy` 控制请求频率。
- 保留检索词、返回顺序和访问时间。

### 11.4 Crossref

`CrossrefSource` 负责 DOI 元数据核验与补充。标题相似度过低、年份冲突或 DOI 格式异常时标记 `partial` 或 `rejected`。

### 11.5 HTTPS 页面

`HttpsSource` 只访问允许域名，使用标准库 `HTMLParser` 去除脚本、样式和导航噪声。最大响应大小与超时由配置控制。

### 11.6 RepositorySource

读取现有仓库中的 README、配置、数据 Schema 与审计文件。任何代码事实都附文件路径和 SHA256。

### 11.7 CitationGate

```python
class CitationGate:
    def validate_claims(
        self,
        claims: list[EvidenceClaim],
        sources: dict[str, SourceRecord],
    ) -> GateResult: ...

    def validate_scientific_plan(
        self,
        plan: ScientificPlan,
        claims: dict[str, EvidenceClaim],
    ) -> GateResult: ...
```

检查：

- `source_id` 存在。
- 证据位置存在。
- `verification_status` 达到要求。
- 结论中的数值能追溯到 Claim 或模块结果。
- 参考文献去重。
- 标题、DOI、PMID 的组合一致。

---

## 12. 角色化 Agent

### 12.1 BaseAgent

```python
class BaseAgent(Generic[InputT, OutputT]):
    name: str
    prompt_name: str
    output_model: type[OutputT]
    required_skills: tuple[str, ...]

    def run(self, value: InputT, context: AgentContext) -> AgentResult[OutputT]: ...
```

`AgentContext` 包含模型客户端、PromptBuilder、SkillRegistry、RunStore、来源索引和阶段设置。

### 12.2 Agent 职责

| Agent | 输入 | 输出 | 核心门禁 |
| --- | --- | --- | --- |
| ProblemFramer | ResearchGoal、项目现状 | ProblemFrame | 问题可测量、边界明确 |
| EvidenceAgent | 来源文本、研究问题 | EvidenceCard | Claim 可追踪、无虚构引用 |
| GapAgent | EvidenceCard、项目现状 | KnowledgeGapSet | 缺口由证据支持 |
| HypothesisAgent | Gap、数据可用性 | HypothesisSet | 至少 3 个候选、可证伪 |
| CriticAgent | HypothesisSet、证据 | HypothesisReview | 创新、可行、数据、反例审查 |
| ExperimentAgent | 选中假设、模块契约 | ExperimentPlan | 基线、指标、约束预注册 |
| ResultAgent | 模块与实验结果 | ResultInterpretation | 不用综合分自证综合分 |
| FeedbackAgent | 结果、失败与门禁 | IterationDecision | 动作在允许类型内 |
| ReportAgent | 全部通过产物 | ScientificPlan | 赛题字段完整、引用真实 |

多 Agent 使用同一模型客户端，角色提示词、输入数据和输出模型分别隔离。无需引入并行 Agent 框架。

---

## 13. 工作流引擎

### 13.1 Stage 定义

```python
class StageSpec(StrictModel):
    name: str
    handler: str
    required_skills: list[str]
    dependencies: list[str]
    approval: Literal["none", "critical", "always"]
    retry_limit: int
    enabled: bool
```

### 13.2 Stage 状态

```python
StageStatus = Literal[
    "pending",
    "running",
    "passed",
    "needs_approval",
    "retryable",
    "failed",
    "skipped"
]
```

### 13.3 WorkflowEngine

```python
class WorkflowEngine:
    def run(self, goal: ResearchGoal, options: RunOptions) -> RunSummary: ...
    def resume(self, run_id: str, options: ResumeOptions) -> RunSummary: ...
    def execute_stage(self, stage: StageSpec, context: WorkflowContext) -> StageResult: ...
    def request_approval(self, gate: ApprovalGate) -> ApprovalDecision: ...
```

`full-research.json` 阶段顺序：

1. `initialize`
2. `problem_framing`
3. `source_collection`
4. `evidence_extraction`
5. `citation_validation`
6. `gap_analysis`
7. `hypothesis_generation`
8. `hypothesis_critique`
9. `hypothesis_selection`
10. `experiment_design`
11. `module_preflight`
12. `module_execution`
13. `experiment_analysis`
14. `feedback_decision`
15. 返回第 3、10 或 12 阶段，或进入报告
16. `scientific_report`
17. `web_payload`
18. `final_validation`
19. 可选 `publish_web`

每次迭代以独立子目录保存。达到 `max_iterations` 后，结果仍不清晰时输出 `inconclusive`。

---

## 14. 固定命令执行器

文件：`subprocess_runner.py`

```python
class CommandSpec(StrictModel):
    command_id: str
    argv: list[str]
    cwd: Path
    timeout_seconds: int
    allowed_exit_codes: set[int]
    env_overrides: dict[str, str]
    writes: list[Path]

class SafeSubprocessRunner:
    def run(self, spec: CommandSpec, run_store: RunStore) -> CommandAudit: ...
```

规则：

- 可执行文件允许列表：`uv`、`python`、`node`、`git`。
- 禁止 shell 字符串拼接，统一 `subprocess.run(argv, shell=False)`。
- `cwd` 与写入路径需位于仓库或运行目录。
- 环境变量日志只记录名称，敏感值写成 `[REDACTED]`。
- stdout 和 stderr 单独落盘，控制台只展示摘要。
- 超时后终止进程树并记录。
- 模型无法直接传入 `argv`；Agent 只选择预注册操作 ID。

---

## 15. 四个模块 Adapter

### 15.1 基类

```python
class ModuleAdapter(Protocol):
    name: str
    def preflight(self, context: AdapterContext) -> ModuleResult: ...
    def snapshot(self, context: AdapterContext) -> ModuleResult: ...
    def execute(self, operation: ModuleOperation, context: AdapterContext) -> ModuleResult: ...
    def validate(self, context: AdapterContext) -> ModuleResult: ...
```

### 15.2 RouteBuilderAdapter

读取：

```text
xuhui_route_builder/data/web/route_catalog.json
xuhui_route_builder/data/web/xuhui_routes.geojson
xuhui_route_builder/data/web/xuhui_entries.geojson
xuhui_route_builder/data/web/poi_catalog.json
xuhui_route_builder/data/web/access_cases.json
```

预检：

- 文件存在、JSON 可解析。
- 路线数为 90。
- `walk`、`run`、`bike` 各 30。
- 路线 ID 与 GeoJSON 一致。
- `validation_status`、`geometry_status` 和坐标字段满足现有契约。

允许操作：

| 操作 ID | 命令 | 默认权限 |
| --- | --- | --- |
| `route_snapshot` | 读取并哈希稳定产物 | 允许 |
| `route_validate_seeds` | `xuhui-route-builder validate-seeds` | 允许 |
| `route_validate_routes` | `xuhui-route-builder validate-routes` | 需要网络时显式授权 |
| `route_export_candidates` | `xuhui-route-builder export-candidates` | v1 禁用 |
| `route_generate` | `xuhui-route-builder generate-routes` | 高风险，v1 默认禁用 |

路线深度修复遵循 `.qoder/skills/optimize-xuhui-routes`。

### 15.3 EnvironmentDataAdapter

预检命令：

```powershell
uv run --directory weather_api_data weather-api-data config-check
uv run --directory weather_api_data weather-api-data dry-run
```

刷新映射：

| 选项 | 命令 |
| --- | --- |
| `weather` | `scheduled-refresh --tier weather` |
| `hourly` | `scheduled-refresh --tier hourly` |
| `daily` | `scheduled-refresh --tier daily` |
| `none` | 使用 last-known-good 快照 |

快照至少包含：

```text
weather_api_data/runtime/exports/environment_latest.json
weather_api_data/runtime/exports/environment_hourly.json
weather_api_data/runtime/exports/grid_environment_latest.json
weather_api_data/runtime/exports/pollen_grid_scores.json
weather_api_data/runtime/exports/noise_segments.json
weather_api_data/runtime/exports/route_environment.json
xuhui_route_builder/data/web/environment_dashboard.json
```

部分文件在首次刷新前可能缺失。Adapter 返回 `partial` 并列出缺失项；无 Key 时不创建伪数据。

### 15.4 EvaluationModelAdapter

现有接口：

```powershell
uv run --directory evaluation_model_qwen evaluation-model-qwen recommend --profile <file> --offline --json
```

新增窄接口：

```powershell
uv run --directory evaluation_model_qwen evaluation-model-qwen score-candidates \
  --profile <profile.json> \
  --weights <weights.json> \
  --route-catalog <route_catalog.json> \
  --environment-dashboard <environment_dashboard.json> \
  --json
```

`score-candidates` 返回：

```json
{
  "profile": {},
  "risk": {},
  "data_generated_at": "...",
  "candidate_count": 0,
  "candidates": [],
  "weights_sha256": "..."
}
```

实现要求：

- 复用现有 `load_data`、`evaluate_risk`、`score_routes`。
- 返回全部通过硬约束的候选，保留排序和维度分。
- 不调用 Qwen。
- 不改变现有 `recommend` 行为。
- 新增 Pydantic 输出模型和测试。

Harness 的研究 Agent 使用 `qwen3.8-max`。线上推荐模块的模型配置保持独立；实验需要千问审核时，通过子进程环境变量覆盖 `QWEN_MODEL=qwen3.8-max`，不修改模块 `.env`。

### 15.5 WebProductAdapter

读取当前网页结构，发布：

```text
xuhui_route_builder/data/web/research_harness_latest.json
```

第一次施工新增：

```text
xuhui_route_builder/web/src/research-harness-ui.js
xuhui_route_builder/web/styles/research-harness.css
xuhui_route_builder/tests/research_harness_data_contract.test.mjs
xuhui_route_builder/tests/research_harness_ui_contract.test.mjs
```

并对 `index.html`、`main.js` 或 `data-loader.js` 做最小接线。页面行为：

- 数据文件存在且通过 Schema 时展示“AI Scientist 实验”入口。
- 数据缺失或状态为错误时隐藏入口，不影响地图与推荐。
- 展示研究问题、假设、关键指标、基线对比、最优路线、迭代轨迹、引用和限制。
- 路线 ID 可联动现有地图选中逻辑。
- 页面禁止展示本地绝对路径、模型密钥、内部日志和完整自由文本。

---

## 16. 实验矩阵

### 16.1 预设画像

`profiles.py` 从现有问卷字段生成固定案例矩阵，至少覆盖：

- `walk`、`run`、`bike`
- `balanced`、`health_environment`、`nearby`、`scenery`
- 空气、花粉、噪声敏感
- 滨水、公园、安静、厕所、便利设施偏好
- 无出发点的全徐汇筛选与有出发点的接驳筛选

每个案例包含唯一 `case_id`。目标时段在复现实验中使用快照时间附近的固定时刻，避免“现在”导致不可复现。

### 16.2 基线与模型

| ID | 规则 |
| --- | --- |
| `B0_shortest_feasible` | 在可行候选中最小化目标距离偏差与接驳距离 |
| `B1_pm25_only` | 在距离门禁内最小化 PM2.5 |
| `B2_multi_environment` | 综合 PM2.5、噪声和花粉，忽略个人兴趣 |
| `B3_non_personalized` | 使用默认平衡权重，不提升敏感项与兴趣项 |
| `M1_personalized_constrained` | 使用用户目标、敏感项、兴趣、接驳和数据可信度，受附加距离门禁约束 |

### 16.3 原始指标

- PM2.5 数值与健康分
- 噪声代理值
- 花粉风险
- 环境数据可靠度
- 目标距离偏差
- 接驳距离
- 偏好命中率
- 五维得分
- 约束通过率
- 无候选率

### 16.4 派生指标

偏好命中率：

$$
F_{\mathrm{pref}}=\frac{|I_{\mathrm{requested}} \cap I_{\mathrm{matched}}|}{\max(1,|I_{\mathrm{requested}}|)}
$$

综合暴露风险采用预注册归一化，不从最终综合效用反推：

$$
R_{\mathrm{env}}=\alpha R_{\mathrm{PM2.5}}+\beta R_{\mathrm{noise}}+\gamma R_{\mathrm{pollen}}
$$

其中 $\alpha$、$\beta$、$\gamma$ 来自实验变体配置并在运行前冻结。

个性化增益：

$$
\Delta F_{\mathrm{pref}}=F_{\mathrm{pref}}^{M1}-F_{\mathrm{pref}}^{B0}
$$

环境风险改善：

$$
\Delta R_{\mathrm{env}}=R_{\mathrm{env}}^{B0}-R_{\mathrm{env}}^{M1}
$$

### 16.5 统计摘要

`statistics.py` 只使用标准库，固定 seed 1234，输出：

- 中位数
- 四分位距
- 胜率
- 约束通过率
- 配对差值
- 配对 bootstrap 95% 区间

不把预设画像案例解释为独立人群样本，不输出临床或人群外推结论。

### 16.6 支持状态

默认门禁示例：

```json
{
  "supported": {
    "detour_pass_rate_min": 0.90,
    "environment_win_rate_min": 0.60,
    "preference_win_rate_min": 0.60,
    "reference_verification_rate_min": 1.0,
    "fatal_data_errors_max": 0
  }
}
```

阈值在 `quality_gates.json` 中预注册。任何运行时调整均进入迭代记录。

---

## 17. 反馈迭代

允许自动执行的 `FeedbackAction`：

- `expand_sources`
- `refresh_environment`
- `rerun_profiles`
- `rerun_variant`
- `adjust_registered_weights`
- `tighten_detour_limit`
- `relax_noncritical_filter`

只生成建议的动作：

- `propose_route_data_change`
- `propose_environment_model_change`
- `propose_scoring_code_change`
- `propose_frontend_change`

动作应用规则：

1. 权重和阈值修改写入当前 run 的派生配置，不覆盖仓库默认配置。
2. 每轮保存 before/after 差异。
3. 同一动作最多连续执行一次。
4. 指标无改善或数据质量下降时停止。
5. 达到最大迭代次数后输出当前证据状态。

---

## 18. 质量门禁

### 18.1 EvidenceGate

- 核心来源数量达到配置要求。
- 参考文献核验率达到 100%。
- 核心 Claim 有页码、章节、摘要字段或模块路径。
- 模型未创建新 DOI、PMID 或数据值。

### 18.2 HypothesisGate

- 假设可证伪。
- 自变量、因变量、预期方向和失败条件齐全。
- 数据需求能由当前仓库或允许来源满足。
- 创新论证引用现有研究局限。

### 18.3 ExperimentGate

- 基线和主模型规则冻结。
- 主指标与辅助指标区分。
- 距离约束和停止条件明确。
- 输入快照和权重有哈希。

### 18.4 ResultGate

- 结果来自真实模块输出或固定离线 fixture。
- 综合效用不作为唯一验证指标。
- 负结果、无候选和缺失数据进入报告。
- 结论状态与门禁一致。

### 18.5 PublishGate

- `scientific_plan.json` 通过 Schema。
- 网页 payload 无敏感信息和绝对路径。
- 选中路线 ID 存在于当前 `route_catalog.json`。
- 引用 URL 为 HTTPS 或明确本地来源。
- 前端契约测试通过。

---

## 19. 报告与网页数据

### 19.1 `scientific_plan.json`

字段：

```text
problem_statement
rationale
technical_details
datasets.source
datasets.target
paper_title
paper_abstract
methods
experiments.baselines
experiments.metrics
results
references
limitations
reproducibility
```

### 19.2 `experiment_report.md`

建议结构：

1. 研究问题与假设
2. 数据快照
3. 预设画像与约束
4. 基线与模型
5. 指标与公式
6. 结果表
7. 失败案例
8. 反馈迭代
9. 支持状态
10. 局限与下一步

### 19.3 网页 payload

```json
{
  "schema_version": "1.0",
  "run_id": "...",
  "generated_at": "...",
  "status": "supported",
  "research_question": "...",
  "hypothesis": "...",
  "selected_route": {
    "route_id": "...",
    "route_name": "...",
    "reason": "..."
  },
  "key_metrics": [],
  "baseline_comparison": [],
  "iterations": [],
  "references": [],
  "limitations": [],
  "artifacts": []
}
```

`artifacts` 只放仓库相对路径或公开 URL。

---

## 20. 日志、错误与隐私

日志级别：

- `DEBUG`：阶段内部、Schema 字段、命令耗时
- `INFO`：阶段开始结束、产物路径、指标摘要
- `WARN`：降级、旧数据、来源部分核验
- `ERROR`：阶段失败、契约错误、命令异常

日志需包含 `run_id`、`stage`、`operation`、`status`、`elapsed_ms`。异常日志记录调用栈。RotatingFileHandler 限制单文件大小和备份数量。

脱敏项：

- `DASHSCOPE_API_KEY`
- Authorization 头
- URL 凭据
- Windows 与 Unix 用户目录绝对路径
- 用户自由文本
- 经纬度之外的个人地址文本

---

## 21. 恢复与幂等

`resume.py` 规则：

1. 读取 `state.json` 与阶段哈希。
2. 运行目录存在锁且进程仍存活时拒绝并发恢复。
3. 最近阶段为 `running` 且无完整输出时标记 `retryable`。
4. 已通过阶段的输入哈希未变化时跳过。
5. 配置、Skill、Git HEAD 或数据快照变化时提示新建 run；用户显式确认后允许继续并记录漂移。
6. 网页发布采用临时文件与原子替换。

---

## 22. 最小仓库外部修改

除 `Qwen-Harness/` 与 `.qoder/skills/` 外，允许以下最小接线：

1. `evaluation_model_qwen`：新增 `score-candidates` 机器接口及测试。
2. `xuhui_route_builder/web`：新增研究结果面板、样式和契约测试。
3. `.github/workflows/qwen-harness-ci.yml`：新增离线 CI。
4. 根 `README.md`：在功能稳定后增加 Harness 使用入口。

不在同一阶段改动全部位置。每条接线独立实施和验收。

---

## 23. 测试设计

### 23.1 单元测试

- 配置加载与占位符检测
- 路径越界拒绝
- Skill front matter 解析
- 原子写入
- RunStore 锁
- 状态转换
- Prompt 哈希
- 引用门禁
- 指标公式
- bootstrap 固定 seed
- 脱敏函数

### 23.2 Adapter 测试

使用 FakeSubprocessRunner 验证：

- argv 构造
- cwd
- 环境变量覆盖
- 超时与非零退出码
- 不允许的操作 ID
- 缺失模块文件
- 部分环境数据

### 23.3 契约测试

- 路线目录 90 条与三种模式分布
- 环境 dashboard Schema
- `score-candidates` 输出
- scientific plan Schema
- web payload Schema
- selected route ID 存在

### 23.4 离线端到端

```powershell
uv run --directory Qwen-Harness --frozen --extra dev \
  qwen-harness run \
  --offline \
  --workflow reproduce-existing \
  --goal-file examples/goals/multisource-route.json
```

断言：

- 退出码 0 或 1，取决于 fixture 的预设支持状态。
- 运行目录完整。
- 无网络请求。
- 无真实 Key。
- 科学计划字段齐全。
- 网页 payload 通过 Schema。

### 23.5 本地质量命令

```powershell
uv sync --directory Qwen-Harness --extra dev
uv run --directory Qwen-Harness --extra dev pytest -q
uv run --directory Qwen-Harness --extra dev ruff format --check .
uv run --directory Qwen-Harness --extra dev ruff check .
uv run --directory Qwen-Harness --extra dev pyright --pythonpath .venv\Scripts\python.exe
```

macOS/Linux 的 Pyright Python 路径使用 `Qwen-Harness/.venv/bin/python`。

---

## 24. README 最终示例

```powershell
cd Qwen-Harness
uv sync --extra dev
Copy-Item .env.example .env
uv run qwen-harness doctor
uv run qwen-harness run --goal "验证多源环境与有限附加距离约束能否提升个性化路线效用"
```

无 Key 复现：

```powershell
uv run qwen-harness run --offline --workflow reproduce-existing --goal-file examples/goals/multisource-route.json
```

继续运行：

```powershell
uv run qwen-harness resume <run-id>
```

发布已通过结果：

```powershell
uv run qwen-harness publish <run-id>
```
