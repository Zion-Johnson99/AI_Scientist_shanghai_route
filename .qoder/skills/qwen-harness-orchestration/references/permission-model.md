# Permission Model

## 运行模式

| 模式 | 网络 | 现有模块写入 | 产品发布 | 用途 |
| --- | --- | --- | --- | --- |
| `offline` | 关闭 | 关闭 | 关闭 | CI、示例复现、无 Key 体验 |
| `research` | 可选 | 关闭 | 关闭 | 文献、假设和实验计划生成 |
| `experiment` | 可选 | 仅运行目录 | 关闭 | 使用现有模块产物开展实验 |
| `full` | 可选 | 受限 | 可选 | 完整科研闭环 |
| `publish` | 关闭 | 仅网页结果文件 | 开启 | 将已通过门禁的运行写入网页数据 |

## CLI 授权参数

- `--allow-network`：允许模型 API、PubMed/Crossref/允许列表网页、健康检查。
- `--refresh-environment none|weather|hourly|daily`：非 `none` 值必须同时提供 `--allow-network`；仅触发环境模块的分层刷新，不开放其他模块写入。
- `--publish-web`：只在最终质量门禁通过后把 `publish/research_harness_latest.json` 写入 `xuhui_route_builder/data/web/`（临时文件 + 原子替换）。
- `--approval-mode auto|critical|all`：默认 `critical`，关键门禁要求确认。
- v1 不公开 `--allow-module-write`。路线候选导出与路线生成操作保持禁用，Adapter 内部能力仅为后续版本预留。

## 默认保守值

网络关闭、网页发布关闭、模块写入关闭；未显式授权时 Harness 只写 `Qwen-Harness/runtime/`。

## Adapter 内部写入

模块写入授权只来自显式工作流操作（操作 ID），不接受 CLI 通用开关。例如路线模块的 `route_snapshot`、`route_validate_seeds` 默认可用；`route_validate_routes` 需要网络时显式授权；`route_export_candidates`、`route_generate` 在 v1 禁用。

## 命令执行边界

可执行文件允许列表：`uv`、`python`、`node`、`git`。统一 `subprocess.run(argv, shell=False)`。`cwd` 与写入路径必须位于仓库或运行目录内。模型不能直接传入 `argv`，只能选择预注册操作 ID。

## 网络来源策略（source_policy）

只允许 HTTPS；URL 含用户名、密码或片段时拒绝；域名允许列表、最大下载字节数、PDF 最大页数、短摘录长度上限、请求间隔与重试次数由 `config/source_policy.json` 控制。
