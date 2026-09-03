# Qwen Harness 完整运行报告

> 执行状态、耗时、门禁和产物路径来自 Harness 引擎审计；模型内容仅用于科研摘要。

## 运行概览

- 运行 ID：`run-20260902T035556Z-0a43adb5`
- 工作流：`full-research`
- 运行状态：passed
- 支持结论：inconclusive
- 运行模式：千问 API
- 总耗时：182 min 14.6 s
- 已审计阶段耗时合计：24 min 21.8 s
- 本地网页：已生成本地地图网页
- checks 文件数：2

## 阶段执行

| 阶段 | 状态 | 耗时 | 主要摘要 |
| --- | --- | ---: | --- |
| `initialize` | passed | 236 ms | 初始化完成：快照技能 6 个 |
| `problem_framing` | passed | 42.09 s | 问题框架就绪：5 个可测量目标 |
| `source_collection` | passed | 25.00 s | 采集来源 11 个（已验证 11） |
| `evidence_extraction` | passed | 3 min 39.9 s | 证据卡 card-001：14 条 Claim |
| `citation_validation` | passed | 17 ms | 引用核验通过：14 条 Claim / 9 个来源 |
| `gap_analysis` | passed | 1 min 21.4 s | 识别知识缺口 7 个 |
| `hypothesis_generation` | passed | 2 min 36.7 s | 生成候选假设 5 个，推荐 hyp-001 |
| `hypothesis_critique` | passed | 1 min 59.0 s | 评审完成：5 个候选，冲突 4 项 |
| `hypothesis_selection` | passed | 1 min 39.4 s | 选定假设 hyp-001 |
| `experiment_design` | passed | 1 min 37.2 s | 实验计划就绪：基线 3、指标 5、操作 4 |
| `project_generation` | passed | 2 min 44.5 s | 生成工程功能契约得分 90/100 |
| `module_preflight` | passed | 256 ms | 预检状态: route=ok, environment=partial, evaluation=ok, web=ok |
| `module_execution` | passed | 4 min 26.7 s | 执行模块操作 12 个 |
| `experiment_analysis` | passed | 856 ms | 实验分析完成: 单元 45 个，就绪 27 个，支持状态 inconclusive |
| `feedback_decision` | passed | 29.90 s | 迭代决策: stop_inconclusive |
| `scientific_report` | passed | 2 min 36.0 s | 科学计划就绪：参考文献 6 条 |
| `web_payload` | passed | 125 ms | 网页 payload 就绪（status=inconclusive） |
| `final_validation` | passed | 52 ms | 最终门禁通过 |
| `publish_web` | passed | 2.61 s | 本地产品与源码交付包已生成 |

## 四个源码模块

| 模块 | 代码目录 | 预检 | 执行情况 | 源文件数 | 根目录结构 |
| --- | --- | --- | --- | ---: | --- |
| Harness 编排 | `Qwen-Harness` | 不适用 | 本轮工作区已生成 | 19 | config、launch-local.ps1、pyproject.toml、src、tests |
| 路线构建 | `xuhui_route_builder` | ok | passed；记录 1 项操作 | 19 | data、pyproject.toml、src、tests、web |
| 环境数据 | `weather_api_data` | partial | passed；记录 1 项操作 | 7 | config、pyproject.toml、src、tests |
| 评价模型 | `evaluation_model_qwen` | ok | passed；记录 9 项操作 | 10 | config、pyproject.toml、src、tests、uv.lock |

## 门禁与检测

| 阶段 | 门禁 | 结果 | 详情 |
| --- | --- | --- | --- |
| `citation_validation` | citation_validation | 通过 | 检查 12 项 |
| `hypothesis_selection` | hypothesis | 通过 | 检查 5 项 |
| `experiment_design` | experiment_preregistration | 通过 | 检查 5 项 |
| `project_generation` | generation_functional_contract | 通过 | 检查 13 项；未通过：environment_interface |
| `scientific_report` | citation | 通过 | 检查 3 项 |
| `final_validation` | publish | 通过 | 检查 7 项 |

- 最终验证阶段：passed
- 最终验证输出：{'support_status': None, 'route_ids_checked': 90, 'generation_score': 90, 'result_gate': {'gate': 'result', 'passed': True, 'checks': [{'name': 'module_provenance', 'passed': True, 'detail': "provenance='module_outputs'"}, {'name': 'composite_not_sole_metric', 'passed': True, 'detail': '指标数 11'}, {'name': 'negative_results_reported', 'passed': True, 'detail': None}], 'summary': '全部检查通过'}}

## 假设与实验结论

- 选定假设：`hyp-001` — 在徐汇区 90 条候选路线中，当多源加权复合指标中任一维度权重在基准值 ±30% 范围内扰动时，各运动类型（步行/跑步/骑行）前 5 名路线集合的 Jaccard 相似度不低于 0.6，即路线排序对单维度权重扰动具有稳健性。
- 实验支持状态：inconclusive
- 科研解读：按 quality_gates.json 预注册阈值：绕路通过率 0.00、环境胜率 0.00、偏好胜率 0.50、参考核验率 1.00，支持状态判定为 inconclusive。预设画像为固定案例矩阵，不作为独立人群样本外推。
- 迭代决策：结果解释判定为 inconclusive（置信度 low）：detour_pass_rate=0.00、environment_win_rate=0.00、constraint_pass_rate=0.00、no_candidate_rate=0.40，仅 reference_verification_rate=1.00 通过；9 个画像（P01–P09）在 M1 距离门禁下候选集被清空并降级，18 个变体×画像单元无候选。数据质量同时下降：environment 模块预检为 partial，缺少 6 个导出快照文件（environment_latest.json、environment_hourly.json、grid_environment_latest.json、pollen_grid_scores.json、noise_segments.json、route_environment.json），270 个指标块为 estimated 估算值，且全部 90 条路线的 pm2_5/noise/pollen_daily 单位与文档化单位不一致；evaluation 多组候选风险状态为未知；存在 1 个致命数据错误。按决策规则，证据不足且数据质量下降时应停止（stop_inconclusive），不继续迭代；且当前为离线夹具语义下的固定案例矩阵，不触发网络刷新类动作。

## 关键产物路径

- `reports/full_run_report.md` — 已生成
- `reports/scientific_plan.json` — 已生成
- `reports/scientific_plan.md` — 已生成
- `reports/experiment_report.md` — 已生成
- `publish/reports/完整运行报告.md` — 已生成
- `publish/reports/科学计划.md` — 已生成
- `publish/reports/实验报告.md` — 已生成
- `publish/local-product/web/index.html` — 已生成
- `publish/checks/` — 已生成
