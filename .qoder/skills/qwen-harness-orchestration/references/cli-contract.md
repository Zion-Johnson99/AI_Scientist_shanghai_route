# CLI Contract

## 主命令

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
- `--offline` 关闭模型 API 与外部网络，从 `examples/fixtures/` 读取固定响应。
- `--publish-web` 只在最终质量门禁通过后执行。
- `--refresh-environment` 非 `none` 时要求 `--allow-network`。
- v1 不公开模块写入开关。

## 辅助命令

```text
qwen-harness doctor
qwen-harness validate [--scope config|skills|adapters|runs|all]
qwen-harness status <run-id> [--json]
qwen-harness resume <run-id> [--publish-web]
qwen-harness report <run-id>
qwen-harness publish <run-id>
qwen-harness list-runs [--limit N]
```

`doctor` 报告环境、Key（只报状态不报值）、Skills、模块和数据状态；检测 `.env` 空值与 `<WorkspaceId>` 占位符。

## 退出码

| 退出码 | 含义 |
| ---: | --- |
| 0 | 成功 |
| 1 | 质量门禁未通过或研究结果不支持假设，但程序运行完整 |
| 2 | 配置、输入或数据契约错误 |
| 3 | 模型 API 或外部来源故障，且无可用回退 |
| 4 | 模块命令失败 |
| 5 | 运行状态损坏、并发锁冲突或恢复失败 |

## 错误输出

JSON 结构含 `error_type`、`message`、`run_id`、`stage` 和建议动作。禁止输出 API Key、Authorization 头和完整自由文本画像。

## 典型调用（仓库根目录）

```powershell
uv run --directory Qwen-Harness --frozen --extra dev qwen-harness doctor
uv run --directory Qwen-Harness --frozen qwen-harness run --offline --workflow reproduce-existing --goal-file examples/goals/multisource-route.json
uv run --directory Qwen-Harness --frozen qwen-harness resume <run-id>
uv run --directory Qwen-Harness --frozen qwen-harness publish <run-id>
```

## console script

`pyproject.toml` 必须声明：

```toml
[project.scripts]
qwen-harness = "qwen_harness.cli:main"
```
