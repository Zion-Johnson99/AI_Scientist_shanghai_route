# Workflow Contract

## 阶段顺序（full-research）

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

`research-only` 止于报告（跳过模块执行与发布）；`reproduce-existing` 使用 `examples/fixtures/` 固定响应复现已有结论。每次迭代以独立子目录保存；达到 `max_iterations`（默认 2）仍不清晰时输出 `inconclusive`。

## Stage 定义与状态

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

`StageStatus = pending | running | passed | needs_approval | retryable | failed | skipped`

合法转换：`pending → running → passed|needs_approval|retryable|failed`；`retryable → running`（未超 `retry_limit`）；`needs_approval → running|skipped`（审批结果）；`failed` 为终态，等待人工或 `resume`。

## 技能映射

工作流配置为每个阶段显式列出 `required_skills`，名称必须存在于 `.qoder/skills/`。核心映射：

```json
{
  "hypothesis_generation": ["scientific-evidence-hypothesis", "qwen-harness-orchestration"],
  "route_module": ["xuhui-route-builder-engineering", "optimize-xuhui-routes"],
  "environment_module": ["weather-environment-pipeline"],
  "evaluation_module": ["evaluation-qwen-experiments"],
  "web_payload": ["web-product-integration"]
}
```

Harness 加载 `SKILL.md` + 阶段显式列出的 reference 文件，并记录文件 SHA256。

## 迭代规则

默认最大迭代次数 2。每轮仅允许：补充检索词或来源、切换已有实验变体、调整配置中的权重与约束（写入 run 派生配置，不覆盖仓库默认）、使用较新环境快照重跑。涉及源代码修改的建议写入 `change_proposal.json`，运行时不自动改写生产代码。

`IterationDecision.status`：`continue | stop_supported | stop_partial | stop_unsupported | stop_inconclusive`。

## 恢复规则（resume）

1. 读取 `state.json` 与阶段输出 SHA256。
2. `lock.json` 存在且进程存活 → 拒绝并发恢复。
3. 最近阶段为 `running` 且无完整输出 → 标记 `retryable`。
4. 已通过阶段输入哈希未变化 → 跳过。
5. 配置、Skill、Git HEAD 或数据快照变化 → 提示新建 run；显式继续时记录漂移。
6. 网页发布采用临时文件 + 原子替换。
