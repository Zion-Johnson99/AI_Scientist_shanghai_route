# Contest Output Fields

《科学假设与研究计划》必须覆盖赛题标准字段，并与 `reports/scientific_plan.json` 对应。

## 字段映射

| 赛题字段 | scientific_plan.json 字段 |
| --- | --- |
| 待研究问题 | `problem_statement` |
| 解决思路 | `rationale` |
| 必要技术手段 | `technical_details` |
| 数据集 Source | `datasets.source` |
| 数据集 Target | `datasets.target` |
| 论文标题 | `paper_title` |
| 论文摘要 | `paper_abstract` |
| 方法论 | `methods` |
| 基线、指标与实验设计 | `experiments.baselines`、`experiments.metrics` |
| 实验结果 | `results` |
| 真实参考论文 | `references` |

## 附加字段

`ScientificPlan` 另含：

- `limitations`：局限与代理变量说明。
- `reproducibility`：复现说明（命令、数据快照、随机种子）。
- `run_id`、`git_head`、`data_snapshot_hashes`：可追溯性。
- `evidence_map`：结论到 `claim_id`/模块结果的映射。

## 数据集 Source / Target

- Source：输入数据集合（路线目录、环境快照、用户画像等），记录文件与哈希。
- Target：预测/决策目标（候选路线效用、约束最优路线等）。

## references

- 每条引用必须指向来源注册表中已核验的 `source_id`。
- 生成前由 CitationGate 核验；核验率必须 100%。

## 校验

`scripts/validate_scientific_plan.py` 检查上述字段非空、`references` 可解析、数据集字段存在。
