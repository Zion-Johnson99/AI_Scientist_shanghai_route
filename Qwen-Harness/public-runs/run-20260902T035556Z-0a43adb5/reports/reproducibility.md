# 可复现性说明

## 复现命令
```
uv run --directory Qwen-Harness --frozen qwen-harness run --goal-file examples/goals/multisource-route.json
uv run --directory Qwen-Harness --frozen qwen-harness status run-20260902T035556Z-0a43adb5 --json
uv run --directory Qwen-Harness --frozen qwen-harness report run-20260902T035556Z-0a43adb5
python .qoder/skills/scientific-evidence-hypothesis/scripts/validate_source_registry.py Qwen-Harness/runtime/runs/run-20260902T035556Z-0a43adb5
python .qoder/skills/scientific-evidence-hypothesis/scripts/validate_evidence_links.py Qwen-Harness/runtime/runs/run-20260902T035556Z-0a43adb5
python .qoder/skills/scientific-evidence-hypothesis/scripts/validate_scientific_plan.py Qwen-Harness/runtime/runs/run-20260902T035556Z-0a43adb5
```

## 运行环境
| 项 | 值 |
| --- | --- |
- 工作流: "full-research"
- 统计: seed=—，bootstrap 迭代 —
- Git: 分支 —，HEAD —，工作树干净=None

## 配置哈希
（无配置哈希）

## 技能哈希
（无技能哈希）

## 数据快照哈希
| 数据 | sha256 |
| --- | --- |
| route_catalog | sha256 记录于 route.read_snapshot 操作（具体哈希见运行目录 run_manifest.json） |
| environment_dashboard | sha256 记录于 environment.read_snapshot 操作（具体哈希见运行目录 run_manifest.json） |
| source_registry_sha256 | d876c8cd6c73b512495ccc9385eb615021dc1efeb3f5a6865bf86136fbcd8146 (src-web-www-who-int-b625d67c6f53); 4536c8aea95bdfb1b78786bad05537cb209e7c01407f2db853ca71b86cb933a9 (src-pubmed-18994660); ab5a6818c64308ae4d01c57770c6c7c7e092b68897a7dc24dda881361fd17fce (src-local-00-需求与总体架构); e239423f54350a9cb2cdc4249c97aadc21ccf457cbad91402da191043248dade (src-repo-Qwen-Harness-config-source-policy-json) |

## 结果产物
- experiments/experiment_results.json
- experiments/metrics_summary.json（与 reports/metrics_summary.json 内容一致）
- reports/scientific_plan.json / scientific_plan.md / experiment_report.md
- publish/research_harness_latest.json
