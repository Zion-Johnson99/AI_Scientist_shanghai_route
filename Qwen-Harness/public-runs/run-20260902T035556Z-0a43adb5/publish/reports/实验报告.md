# 实验报告：多目标环境暴露约束与个性化路线选择

## 1. 研究问题与假设
- 研究问题: 在满足运动方式、目标距离、安全阈值、搜索范围和有限附加距离约束的候选路线中，融合 PM2.5、花粉、噪声、天气、绿地水体、路线质量、接驳成本和用户偏好的多源模型，相较最短或单一 PM2.5 基线，能否降低环境暴露风险并提高个性化匹配度？
- 预注册假设: 在徐汇区 90 条候选路线中，当多源加权复合指标中任一维度权重在基准值 ±30% 范围内扰动时，各运动类型（步行/跑步/骑行）前 5 名路线集合的 Jaccard 相似度不低于 0.6，即路线排序对单维度权重扰动具有稳健性。（hyp-001）

## 2. 数据快照
- run_id: run-20260902T035556Z-0a43adb5；git_head: 52cd03950b7b31e4fe8ae194bdf11b6ff36bc37e
- 结果来源: module_outputs；致命数据错误: 1
- 候选数据生成时间: 2026-09-02T06:53:10+00:00, 2026-09-02T06:53:11+00:00, 2026-09-02T06:53:12+00:00, 2026-09-02T06:53:13+00:00, 2026-09-02T06:53:14+00:00, 2026-09-02T06:53:15+00:00
- 模块预检状态: {"route": "ok", "environment": "partial", "evaluation": "ok", "web": "ok"}

## 3. 预设画像与约束
| 案例 | 模式 | 目标 | 目标距离(m) | 偏差容忍 | 搜索半径(m) |
| --- | --- | --- | --- | --- | --- |
| P01_walk_balanced | — | balanced | 3000 | — | — |
| P02_run_balanced | — | balanced | 5000 | — | — |
| P03_bike_balanced | — | balanced | 8000 | — | — |
| P04_walk_health_environment | — | health_environment | 3000 | — | — |
| P05_run_health_environment | — | health_environment | 5000 | — | — |
| P06_bike_nearby | — | nearby | 8000 | — | — |
| P07_walk_scenery | — | scenery | 3000 | — | — |
| P08_run_scenery | — | scenery | 5000 | — | — |
| P09_bike_health_environment | — | health_environment | 8000 | — | — |
- 全局约束: 绕路上限 0.2，目标距离偏差容忍 0.15

## 4. 基线与模型（预注册，冻结）
| 变体 | 名称 | 选择规则 | 权重来源 |
| --- | --- | --- | --- |
| B0_shortest_feasible | 最短可行基线 | 在可行候选中最小化目标距离偏差，其次最小化接驳距离，再按 route_id 字典序；不使用环境、兴趣或个性化信息。 | none:选择规则不使用权重 |
| B1_pm25_only | 单一 PM2.5 基线 | 在目标距离偏差门禁内最小化 PM2.5 浓度（网格/站点融合估计值）；PM2.5 缺失的候选不参与选择，全部缺失时回退 B0 规则并记录降级。 | none:单指标最小化 |
| B2_multi_environment | 多环境非个性化基线 | 在目标距离偏差门禁内最小化综合暴露风险 R_env=alpha*R_pm25+beta*R_noise+gamma*R_pollen（预注册归一化），忽略个人兴趣；任一环境分量缺失的候选不参与选择，全部缺失时回退 B0 规则并记录降级。 | experiment_variants.json:exposure_risk_coefficients |
| B3_non_personalized | 默认权重非个性化基线 | 使用评价模块默认平衡权重，不提升敏感项与兴趣项；按 route_quality、sport_match、data_confidence 依次降序选择并以 route_id 字典序决出平局。候选文件必须由默认平衡权重生成（记录 weights_sha256）；若检测到权重被个性化覆盖，按契约违规上报。 | evaluation_module:config/default_weights.json(goal=balanced) |
| M1_personalized_constrained | 个性化约束模型 | 使用用户目标、敏感项、兴趣、接驳距离和数据可信度的个性化综合分：先按目标距离偏差、接驳半径与绕路上限门禁过滤，再按匹配偏好数、base_score、data_confidence 依次降序选择并以 route_id 字典序决出平局；门禁过滤清空候选集时回退无门禁选择并记录降级。 | derived_config.weights 覆盖下的评价模块权重（记录 weights_sha256，无覆盖时为默认权重） |

## 5. 指标与公式
| 指标 | 名称 | 方向 | 主指标 | 公式 |
| --- | --- | --- | --- | --- |
| jaccard_top5 | 前 5 名路线集合 Jaccard 相似度 | higher | 是 | J(A,B) = \|A ∩ B\| / \|A ∪ B\|，其中 A 为基准权重下某运动类型前 5 名路线 ID 集合，B 为单维度权重 ±30% 扰动后同运动类型前 5 名路线 ID 集合；对每个画像、每个被扰动维度、每个扰动方向（+30%、−30%）分别计算，报告最小值与中位数 |
| spearman_rank_all90 | 全部 90 条路线 Spearman 秩相关系数 | higher | 否 | ρ = 1 − 6Σd_i² / (n(n²−1))，其中 d_i 为基准权重与扰动权重下第 i 条路线的排名差，n 为该运动类型可行候选数（≤30）；对每个画像、每个被扰动维度、每个扰动方向分别计算 |
| dimension_variance | 被扰动维度在候选集内的方差 | target | 否 | Var(x_dim) = Σ(x_i − x̄)² / (n−1)，x_i 为第 i 条可行候选在该维度的归一化分值；用于解释排序翻转与维度方差的关系（调节变量） |
| constraint_pass_rate | 硬约束通过率 | higher | 否 | 通过硬约束的候选数 / 该运动类型全部候选数；权重扰动不应改变硬约束过滤结果，若扰动前后通过率不一致则标记异常 |
| candidate_count | 可行候选数 | target | 否 | 该画像与运动类型下通过硬约束与距离门禁的候选路线数；用于判断样本是否足以计算前 5 名集合（需 ≥5） |

## 6. 结果表
**总体率**:
| 指标 | 数值 |
| --- | --- |
| detour_pass_rate | 0.000 |
| environment_win_rate | 0.000 |
| preference_win_rate | 0.500 |
| constraint_pass_rate | 0.000 |
| no_candidate_rate | 0.400 |
| reference_verification_rate | 1.000 |
| mean_data_reliability_m1 | — |
**配对比较（变体 vs B0；env_risk 已按“越低越好”翻转口径呈现胜率）**:
| 变体 | 指标 | 配对数 | 变体均值 | B0 均值 | 均值差 | 95% CI | 胜率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1_pm25_only | env_risk | 0 | — | — | — | — | 0.000 |
| B1_pm25_only | preference_hit_rate | 0 | — | — | — | — | 0.000 |
| B2_multi_environment | env_risk | 0 | — | — | — | — | 0.000 |
| B2_multi_environment | preference_hit_rate | 0 | — | — | — | — | 0.000 |
| B3_non_personalized | env_risk | 0 | — | — | — | — | 0.000 |
| B3_non_personalized | preference_hit_rate | 9 | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 0.500 |
| M1_personalized_constrained | env_risk | 0 | — | — | — | — | 0.000 |
| M1_personalized_constrained | preference_hit_rate | 9 | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 0.500 |

## 7. 失败案例（如实记录，不伪造）
- P01_walk_balanced×B1_pm25_only: no_candidate — 选择规则未选出候选
- P01_walk_balanced×B2_multi_environment: no_candidate — 选择规则未选出候选
- P02_run_balanced×B1_pm25_only: no_candidate — 选择规则未选出候选
- P02_run_balanced×B2_multi_environment: no_candidate — 选择规则未选出候选
- P03_bike_balanced×B1_pm25_only: no_candidate — 选择规则未选出候选
- P03_bike_balanced×B2_multi_environment: no_candidate — 选择规则未选出候选
- P04_walk_health_environment×B1_pm25_only: no_candidate — 选择规则未选出候选
- P04_walk_health_environment×B2_multi_environment: no_candidate — 选择规则未选出候选
- P05_run_health_environment×B1_pm25_only: no_candidate — 选择规则未选出候选
- P05_run_health_environment×B2_multi_environment: no_candidate — 选择规则未选出候选
- P06_bike_nearby×B1_pm25_only: no_candidate — 选择规则未选出候选
- P06_bike_nearby×B2_multi_environment: no_candidate — 选择规则未选出候选
- P07_walk_scenery×B1_pm25_only: no_candidate — 选择规则未选出候选
- P07_walk_scenery×B2_multi_environment: no_candidate — 选择规则未选出候选
- P08_run_scenery×B1_pm25_only: no_candidate — 选择规则未选出候选
- P08_run_scenery×B2_multi_environment: no_candidate — 选择规则未选出候选
- P09_bike_health_environment×B1_pm25_only: no_candidate — 选择规则未选出候选
- P09_bike_health_environment×B2_multi_environment: no_candidate — 选择规则未选出候选

## 8. 反馈迭代
- iteration-1: stop_inconclusive（结果解释判定为 inconclusive（置信度 low）：detour_pass_rate=0.00、environment_win_rate=0.00、constraint_pass_rate=0.00、no_candidate_rate=0.40，仅 reference_verification_rate=1.00 通过；9 个画像（P01–P09）在 M1 距离门禁下候选集被清空并降级，18 个变体×画像单元无候选。数据质量同时下降：environment 模块预检为 partial，缺少 6 个导出快照文件（environment_latest.json、environment_hourly.json、grid_environment_latest.json、pollen_grid_scores.json、noise_segments.json、route_environment.json），270 个指标块为 estimated 估算值，且全部 90 条路线的 pm2_5/noise/pollen_daily 单位与文档化单位不一致；evaluation 多组候选风险状态为未知；存在 1 个致命数据错误。按决策规则，证据不足且数据质量下降时应停止（stop_inconclusive），不继续迭代；且当前为离线夹具语义下的固定案例矩阵，不触发网络刷新类动作。）

## 9. 支持状态
- 判定: **证据不足**（inconclusive）
- 解释: 按 quality_gates.json 预注册阈值：绕路通过率 0.00、环境胜率 0.00、偏好胜率 0.50、参考核验率 1.00，支持状态判定为 inconclusive。预设画像为固定案例矩阵，不作为独立人群样本外推。
- 判定口径: 全部条件满足→supported；仅部分改善→partially_supported；方向相反→unsupported；证据不足→inconclusive

## 10. 局限与下一步
- PM2.5 暴露为网格/站点融合估计，不是站点实测或传感器实测值
- 花粉为日级背景/代理指标，不是逐时实测浓度
- 噪声为 0-100 风险代理，不是声级计实测
- 接驳距离为 GCJ-02 直线估算，实际道路距离通常更长
- 预设画像为固定案例矩阵，不解释为独立人群样本，不外推临床或人群结论
- 负结果: 18 个变体×画像单元无候选（硬约束过滤后为空）
- 负结果: M1 距离门禁未通过的画像: P01_walk_balanced, P02_run_balanced, P03_bike_balanced, P04_walk_health_environment, P05_run_health_environment, P06_bike_nearby, P07_walk_scenery, P08_run_scenery, P09_bike_health_environment
- 下一步: 补充缺失候选单元、接入实测环境数据核验融合估计、扩大画像矩阵后复核阈值
