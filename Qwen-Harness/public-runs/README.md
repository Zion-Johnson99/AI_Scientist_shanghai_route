# Qwen-Harness 两轮公开运行成果

本目录保存 Qwen-Harness 的两轮冻结成果。公开副本已移除虚拟环境、解释器缓存、测试缓存和本机绝对路径，原始运行目录仍保存在本地 `runtime/runs/`。

| 轮次 | Run ID | 工程状态 | 科研状态 | 公开目录大小 |
| --- | --- | --- | --- | --- |
| 第一轮 | `run-20260902T035556Z-0a43adb5` | 19 个流程阶段完成，7 项必需工程检查失败 | `inconclusive` | 8.61 MiB |
| 第二轮 | `run-20260902T125247Z-d8922e23` | 14 项工程门禁、90 条路线空间门禁、12 项产品矩阵和真实浏览器验收通过 | `partially_supported` | 29.16 MiB |

## 目录内容

每轮保留运行清单、输入、来源、实验摘要、检查结果、截图、报告、生成源码、发布网页和启动脚本。第二轮的发布网页位于 `publish/local-product/`，Windows 启动入口为 `publish/launch-local.ps1`。

第二轮 `experiments/score_candidates/` 的 243 个候选评分明细体积约 28.9 MiB，收录在 [GitHub Release](https://github.com/Zion-Johnson99/AI_Scientist_shanghai_route/releases/tag/qwen-harness-runs-2026-09-03) 附件 `qwen-harness-round2-score-candidates.zip`。源码工作区中与发布网页重复的 `workspace/source/web/data/app_payload.json` 未重复收录，完整网页载荷保留在 `publish/local-product/data/app_payload.json`。附件校验值见 `RELEASE_ASSETS.sha256`。

## 复查入口

- 第一轮：`run-20260902T035556Z-0a43adb5/reports/full_run_report.md`
- 第一轮工程门禁：`run-20260902T035556Z-0a43adb5/checks/generated_quality.json`
- 第二轮：`run-20260902T125247Z-d8922e23/reports/完整运行报告.md`
- 第二轮工程门禁：`run-20260902T125247Z-d8922e23/checks/generated_quality.json`
- 第二轮浏览器验收：`run-20260902T125247Z-d8922e23/checks/browser_acceptance.json`
- 第二轮复现说明：`run-20260902T125247Z-d8922e23/reports/复现说明.md`

## 数据许可

第二轮使用的 OpenStreetMap 数据遵循 ODbL 1.0，Open-Meteo 数据遵循 CC BY 4.0。署名与加工口径见 `run-20260902T125247Z-d8922e23/workspace/source/docs/licence.md` 和 `data_provenance.md`。

## 隐私处理

公开副本使用 `<repo_root>`、`<run_root>` 和 `<user_home>` 替代本机路径。常见凭据形态扫描未发现命中；`.env`、虚拟环境、依赖目录和工具缓存均未收录。
