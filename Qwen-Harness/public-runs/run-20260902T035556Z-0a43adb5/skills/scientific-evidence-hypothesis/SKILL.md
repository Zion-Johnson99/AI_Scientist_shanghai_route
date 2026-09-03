---
name: scientific-evidence-hypothesis
description: Turn research goals into registered sources, traceable evidence claims, knowledge gaps, falsifiable hypotheses, and a pre-registered scientific plan for the Shanghai Xuhui healthy-route AI Scientist project. Use for literature/source collection, PubMed/Crossref metadata, PDF and repository extraction, fact cards, research gaps, hypothesis generation and critique, citation verification, contest scientific-plan fields (References/Rationale), or validating runtime/runs source registries and evidence links.
---

# 科学证据与假设

## Outcome

把研究目标转成一条可审计的证据链：来源注册表（`SourceRecord`）→ 证据卡（`EvidenceClaim`）→ 知识缺口（`KnowledgeGap`）→ 候选假设（`HypothesisCandidate`）→ 批判审查 → 预注册实验计划。所有引用可回溯，证据不足时明确返回缺口，不补写事实。

## When to use

- 论文、政策、官方数据平台来源收集与核验。
- PDF、摘要与仓库资料提取事实卡片。
- 研究缺口识别、假设生成与批判审查。
- 引用真实性核验（DOI、PMID、标题、年份一致性）。
- 生成《科学假设与研究计划》的 References、Rationale 与赛题标准字段。
- 对 `runtime/runs/<run-id>/` 产物做确定性 Schema 与引用校验。

## Authoritative files

```text
Qwen-Harness/src/qwen_harness/models.py            # SourceRecord / EvidenceClaim / KnowledgeGap / HypothesisCandidate 等模型
Qwen-Harness/src/qwen_harness/sources/             # local_files / pubmed / crossref / web / repository 适配器
Qwen-Harness/src/qwen_harness/workflow/gates.py    # CitationGate / EvidenceGate / HypothesisGate
Qwen-Harness/schemas/evidence-card.schema.json
Qwen-Harness/schemas/hypothesis-set.schema.json
Qwen-Harness/schemas/scientific-plan.schema.json
Qwen-Harness/config/source_policy.json
docs/qwen-harness-build/01-Qwen-Harness详细工程设计.md  # §6、§11、§18、§19
```

> `Qwen-Harness/*` 各路径为施工新增（模型、来源适配器、门禁、Schema 与配置在施工轮次中落地），未落地前以 01 设计文档 §6、§11、§18、§19 为契约依据；`docs/qwen-harness-build/` 已存在。

## Inputs

- `ResearchGoal`（title、question、constraints、seed_sources）。
- 用户提供文件、PubMed 元数据与摘要、Crossref DOI 元数据、官方政府或数据平台页面、仓库内可追溯的代码/配置/数据产物。
- 运行目录路径（校验脚本参数），如 `Qwen-Harness/runtime/runs/<run-id>/`。

## Outputs

- `sources/source_registry.jsonl`：逐行一个 `SourceRecord`（source_id、source_type、title、authors、year、doi、pmid、url、local_path、accessed_at、sha256、license_note、verification_status）。
- `sources/evidence_cards.jsonl`：逐行一个 `EvidenceClaim`（claim_id、source_id、claim、evidence_location、short_excerpt、evidence_type、support_strength、caveats）。
- 阶段产物：`KnowledgeGapSet`、`HypothesisSet`（3 个候选 + 推荐项）、`HypothesisReview`、`ExperimentPlan`。
- `reports/scientific_plan.json` + `scientific_plan.md`：覆盖赛题标准字段（见 references/contest-output-fields.md）。

## Workflow

1. 先建立 `SourceRecord`，后生成 Claim。任何 Claim 只引用已注册来源的 `source_id`。
2. 提取证据时区分结果、方法、数据集、局限、定义、政策六类 `evidence_type`，并给出 `support_strength` 与 caveats。
3. 知识缺口必须由多个 Claim 支持，或明确说明单一来源的局限；缺口写明 available_data 与 missing_data。
4. 假设包含机制、自变量、因变量、调节变量、预期方向、反证条件、数据需求和风险；至少 3 个候选。
5. 按 rubric 打分（见 references/hypothesis-rubric.md），Critic 列出反例和数据风险后再选择。
6. 参考论文只从来源注册表生成；报告生成前由 CitationGate 再次核验。
7. 证据不足时返回缺口记录，不补写作者、DOI、PMID 或数值。
8. 产出后运行三个确定性校验脚本（见 Commands）。

## Allowed operations

- 读取用户提供的文件、仓库产物与允许列表内的 HTTPS 来源（网络需显式授权）。
- 写入运行目录内的 `sources/`、`stages/`、`reports/`。
- 调用 `scripts/validate_*.py` 做确定性校验。
- 只读四个业务模块的稳定产物，把代码/数据事实作为 `repository_file` 来源登记（附文件路径与 SHA256）。
- 不修改模块源码、路线数据或网页文件。

## Commands

```powershell
# 校验来源注册表（run 目录为参数）
python .qoder/skills/scientific-evidence-hypothesis/scripts/validate_source_registry.py Qwen-Harness/runtime/runs/<run-id>

# 校验证据卡与来源的引用关系
python .qoder/skills/scientific-evidence-hypothesis/scripts/validate_evidence_links.py Qwen-Harness/runtime/runs/<run-id>

# 校验科学计划的赛题字段与引用完整性
python .qoder/skills/scientific-evidence-hypothesis/scripts/validate_scientific_plan.py Qwen-Harness/runtime/runs/<run-id>
```

脚本只做确定性校验：标准库实现，无网络、无模型调用；0 通过、1 失败、2 用法错误。

## Quality gates

- EvidenceGate：核心来源数量达标；参考文献核验率 100%；核心 Claim 有页码/章节/摘要字段/模块路径；模型未创建新 DOI、PMID 或数据值。
- HypothesisGate：假设可证伪；自变量、因变量、预期方向、失败条件齐全；数据需求可由当前仓库或允许来源满足；创新论证引用现有研究局限。
- CitationGate：`source_id` 存在；证据位置存在；`verification_status` 达标；结论数值可追溯到 Claim 或模块结果；参考文献去重；标题/DOI/PMID 组合一致。
- 结果报告区分观测事实、模型估计、代理变量和推断。

## Failure handling

- 核心引用无法核验：标记 `rejected`/`unverified`，从结论中移除该引用并记录缺口。
- PDF 页面无文本（需 OCR）：v1 停止该来源并报告，不猜测内容。
- 标题相似度过低、年份冲突或 DOI 格式异常：标记 `partial` 或 `rejected`。
- 网络来源 429/超时簇：停止该来源，保留检索词、返回顺序和错误上下文。
- Claim 指向不存在的 `source_id`：引用门禁拒绝，不用自由文本回退。

## Stop conditions

- 核心引用无法核验。
- 假设依赖本阶段缺失的实测数据且无代理方案。
- 输出把代理噪声写成实时分贝。
- 输出把网格 PM2.5 写成道路实测值。
- 输出宣称全路网全局最优。
- 需要开展问卷、盲评、传感器或线下实测才能验证假设（超出项目实验边界）。

## Handoff

报告：注册来源数量与核验状态分布；证据卡数量与类型分布；知识缺口列表；候选假设与最终选择及 rubric 得分；反例与数据风险；三个校验脚本的 PASS/FAIL 结果；剩余未核验来源清单。细节见：

- [references/evidence-schema.md](references/evidence-schema.md)
- [references/hypothesis-rubric.md](references/hypothesis-rubric.md)
- [references/citation-policy.md](references/citation-policy.md)
- [references/source-adapters.md](references/source-adapters.md)
- [references/contest-output-fields.md](references/contest-output-fields.md)
