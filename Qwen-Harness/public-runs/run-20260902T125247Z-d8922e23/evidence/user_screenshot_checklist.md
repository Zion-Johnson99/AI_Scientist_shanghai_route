# 用户截图待办清单

本次运行由当前 Qoder Goal 会话内的模型执行，未调用任何付费大模型接口。因此有两类证据只能由用户在 Qoder 界面中手动截取，Agent 无法自行读取，也不允许编造。

在补齐这两张截图之前，`run_manifest.json`、`provider_manifest.json`、`evidence/model_channel.json` 中对应字段一律保持 `evidence_pending_user_capture`，最终状态不得记为 `passed` 的证据完整形态。

## 一、Qoder Credits 消耗截图

需要证明本次运行确实通过 Qoder Credits 计费，且能看出消耗量级。

截取要求：

1. 打开 Qoder 的账户或用量页面，找到本次 Goal 会话对应的 Credits 消耗记录。
2. 截图中需要可见：会话或任务标识、消耗的 Credits 数值、统计时间范围。
3. 若 Qoder 不提供按会话拆分的用量，则截取整体用量页面，并在文件旁边用文本注明本次运行的大致起止时间。

保存位置：

```
Qwen-Harness/runtime/runs/run-20260902T125247Z-d8922e23/evidence/qoder_credits_usage.png
```

补齐后需要回填的字段：

| 文件 | 字段 | 当前值 | 补齐后 |
| --- | --- | --- | --- |
| `evidence/model_channel.json` | `qoder_credits_used` | `evidence_pending_user_capture` | 截图中的实际数值 |
| `evidence/model_channel.json` | `qoder_credits_evidence` | `evidence_pending_user_capture` | `evidence/qoder_credits_usage.png` |
| `run_manifest.json` | `credits_consumed` | `unknown` | 截图中的实际数值 |

## 二、百炼调用量为零的截图

需要证明本次运行没有触发任何 DashScope 或百炼付费调用。

截取要求：

1. 登录阿里云百炼控制台，进入调用量或账单统计页面。
2. 把统计时间范围设为本次运行的日期。
3. 截图中需要可见：模型调用次数或 Token 用量为零，或者与本次运行无关的历史用量曲线。

保存位置：

```
Qwen-Harness/runtime/runs/run-20260902T125247Z-d8922e23/evidence/bailian_usage_zero.png
```

补齐后需要回填的字段：

| 文件 | 字段 | 当前值 | 补齐后 |
| --- | --- | --- | --- |
| `evidence/model_channel.json` | `dashscope_call_count` | `0`（由代码路径推断） | 截图确认的数值 |
| `evidence/model_channel.json` | `bailian_usage_evidence` | `evidence_pending_user_capture` | `evidence/bailian_usage_zero.png` |

## 三、Agent 已经自证的部分

以下结论不依赖用户截图，由运行内的确定性证据支撑，可以直接复查：

1. `dashscope_api_used=false`：全部命令都在 `env -u DASHSCOPE_API_KEY -u OPENAI_API_KEY` 下执行，测试子进程另外通过 `_scrubbed_env()` 清除这两个变量。
2. 未读取 `Qwen-Harness/.env`：`checks/secret_scan.json` 的 `env_files_present` 为空，扫描器按设计只记录 `.env` 是否存在，从不打开它。
3. 未编造百炼 request ID 或 task ID：`checks/secret_scan.json` 的 `provider_identifier` 规则只放行 `unknown`、`evidence_pending_user_capture`、`not_applicable`、`not_applicable_no_credentials` 和空串。
4. 未运行在线 Harness：`commands/` 下没有任何 `qwen-harness run` 或 `resume` 调用记录。

## 四、补齐后的收尾动作

1. 把两张截图放进上面的路径。
2. 按两张表回填字段，删掉 `evidence_pending_user_capture`。
3. 重新运行 `uv run --no-project python scripts/check_secret_scan.py`，确认新增的截图文件名没有触发任何规则。
4. 重新运行 `uv run --no-project python scripts/build_checkpoint.py --stage final`，让 `final_checkpoint/manifest.json` 记录回填后的状态。
