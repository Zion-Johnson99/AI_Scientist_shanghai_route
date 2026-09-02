# Run Artifact Contract

## 运行目录

```text
Qwen-Harness/runtime/runs/<run-id>/
├── run_manifest.json        # 运行元数据与哈希（见下）
├── state.json               # 阶段状态机当前状态
├── lock.json                # 并发锁
├── events.jsonl             # 追加式事件日志
├── inputs/                  # 研究目标等输入快照
├── sources/
│   ├── source_registry.jsonl    # SourceRecord，逐行一条
│   └── evidence_cards.jsonl     # EvidenceClaim，逐行一条
├── skills/                  # 本次运行加载的技能快照（含 SHA256）
├── stages/<stage>/
│   ├── input.json
│   ├── output.json
│   └── audit.json           # 模型调用审计、门禁结果
├── modules/
│   ├── route/result.json
│   ├── environment/result.json
│   └── evaluation/result.json
├── experiments/
│   ├── experiment_results.json
│   └── metrics_summary.json
├── reports/
│   ├── scientific_plan.json
│   ├── scientific_plan.md
│   ├── experiment_report.md
│   └── reproducibility.md
└── publish/
    └── research_harness_latest.json
```

## run_manifest.json 必备字段

`run_id`、创建时间、仓库根目录、Git 分支与 HEAD、工作树是否干净、Harness 版本、Python 版本与平台、模型名/温度/seed/各阶段推理强度、工作流名称与版本、Skills 文件哈希、配置文件哈希、模块数据文件哈希、网络与写入权限状态。

## ModuleResult

```python
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

`CommandAudit` 记录 `command_id`、`argv`、`cwd`、起止时间、退出码、stdout/stderr 落盘路径、是否超时。

## 原子写入

同目录临时文件 → `flush` → `fsync` → `os.replace`。恢复时校验 `state.json` 与阶段输出的 SHA256。共享数据文件只允许一个写入者。

## 隐私与脱敏

运行目录与日志不得出现：API Key、Authorization 头、URL 凭据、Windows/Unix 用户目录绝对路径、用户自由文本画像原文、模型内部推理文本（仅显式 `rationale`、`mechanism`、审查意见进入输出模型）。环境变量日志只记名称，敏感值写 `[REDACTED]`。
