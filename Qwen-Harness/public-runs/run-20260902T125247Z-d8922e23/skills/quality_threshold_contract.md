# Qwen-Harness 第二轮 · Skill 质量阈值契约（Quality Threshold Contract）

本文件只从项目 Skill 定义（`.qoder/skills/` 下的 SKILL.md、references/*.md 与 Skill 自带门禁脚本）中提取规则、阈值、Schema 与验收标准。所有数字均逐字引自 Skill；推断项标注 `[inferred]`；Skill 未给出的项标注“未在 Skill 中定义”。未读取、未执行 `xuhui_route_builder/`、`weather_api_data/`、`evaluation_model_qwen/` 中的任何业务数据。

来源 Skill（下文缩写）：

- `OPT` = optimize-xuhui-routes（SKILL.md、references/route-quality-contract.md、references/evidence-and-poi-rules.md、references/route-rebuild-playbook.md、scripts/route_quality_gate.py、scripts/route_portfolio_gate.py）
- `RBE` = xuhui-route-builder-engineering（SKILL.md、route-data-contract.md、module-operations.md、failure-modes.md）
- `WEP` = weather-environment-pipeline（SKILL.md、data-semantics.md、snapshot-files.md、refresh-fallback.md、scripts/verify_environment_snapshot.py）
- `EVE` = evaluation-qwen-experiments（SKILL.md、scoring-contract.md、experiment-matrix.md、score-candidates-contract.md）
- `WEB` = web-product-integration（SKILL.md、ui-contract.md、web-payload-contract.md、scripts/verify_web_payload.py）
- `QHO` = qwen-harness-orchestration（SKILL.md、workflow-contract.md、run-artifact-contract.md、cli-contract.md、permission-model.md）
- `SEH` = scientific-evidence-hypothesis（SKILL.md、evidence-schema.md、hypothesis-rubric.md、citation-policy.md、source-adapters.md、contest-output-fields.md、scripts/validate_*.py）

---

## 1. ROUTE PORTFOLIO GATES（路线组合门禁）

来源：OPT SKILL.md「Portfolio contract」、OPT route-quality-contract.md §1、RBE route-data-contract.md、OPT scripts/route_portfolio_gate.py。

### 1.1 总数与分运动数量

- 路线总数固定 **90** 条；`walk`、`run`、`bike` 各 **30** 条（`route_mode` 字段，注意“字段名是 route_mode，不是 mode”——RBE）。
- `route_catalog.json` 与路线 GeoJSON **始终导出 90 条**（OPT §7）。
- 脚本判据：`expected_route_count = 30 if mode else 90`；`mode_counts[route_mode] != 30` → `mode_count_mismatch`。

### 1.2 距离档（按生成后的实际距离统计）

| 运动 | 短距离（10 条） | 中距离（10 条） | 长距离（10 条） |
| --- | --- | --- | --- |
| `walk` | 0.5–2 km | 2–3.5 km | 3.5–5 km |
| `run` | 1–5 km | 5–10 km | 10–15 km |
| `bike` | 5–10 km | 10–20 km | 20–30 km |

- 每档 **10** 条（脚本：`bucket_counts[label] != 10` → `distance_bucket_count_mismatch`；距离取字段优先级 `actual_distance_m` → `distance_m` → `target_distance_m`）。
- 边界归属规则（逐字）：“区间边界归入从该边界起始的下一档，最后一档包含上界。例如 2 km 步行归入 2–3.5 km，5 km 步行归入 3.5–5 km。档位统计使用生成后的实际距离。”脚本实现：`lower <= distance < upper`，最后一档 `distance == upper` 也计入；越界 → `distance_out_of_range`。
- 目标里程容差：“实际距离与目标里程误差 | 不高于 **15%**”（OPT §3；脚本 `TARGET_ERROR_MAX = 0.15`，`target_error = |actual - target| / target`）。评价模块同口径：ρ_target = |d_route − d_target| / d_target ≤ **0.15**（EVE experiment-matrix.md）。

### 1.3 形态配额（strict_loop vs one_way）

- “每种运动以 **15** 条 `strict_loop`、**15** 条 `one_way` 为设计目标。正式验收允许每种运动 **14–16** 条 `strict_loop`，其余为 `one_way`。”（OPT §1）
- 脚本：`not 14 <= counts["strict_loop"] <= 16 or counts["one_way"] + counts["strict_loop"] != 30` → `shape_balance_mismatch`。
- “Prefer route quality over the loop quota.”（OPT SKILL.md）

### 1.4 区域覆盖（8 个命名区域）

组合必须覆盖（OPT §6 / SKILL.md / 脚本 `POPULAR_AREAS`，每个区域计数为 0 → `popular_area_coverage_gap`）：

| area_id | 名称别名（脚本逐字） |
| --- | --- |
| `west_bund` | 徐汇滨江、西岸、龙腾大道 |
| `longhua` | 龙华 |
| `xujiahui` | 徐家汇 |
| `hengfu` | 衡复、衡山路、复兴路 |
| `shanghai_botanical_garden` | 上海植物园、植物园 |
| `kangjian` | 康健园、康健 |
| `caohejing` | 漕河泾 |
| `huajing` | 华泾 |

- 初筛用 `popular_area_ids` 或路线名称/区域标签；“最终空间覆盖以路线全景、实际轨迹经过位置和入口证据为准”。
- 每区域最少条数（>1）：未在 Skill 中定义（只要求每区域 ≥1 条覆盖）。

### 1.5 ID 唯一性与一致性

- `route_id` 全局唯一（如 `XH_BIKE_0061`）；重复 → `duplicate_route_ids`（RBE + OPT 脚本）。
- “`route_catalog.json` 的 `route_id` 集合必须等于 `xuhui_routes.geojson` 的 `properties.route_id` 集合。”（RBE）脚本：集合不等或多出 → `web_catalog_route_set_mismatch`。
- 评价模块与网页选中的 `route_id` 必须存在于目录（RBE / WEB）。

### 1.6 重复 / 反向重复 / 高重叠

- “同模式路线重复 | 相同、反向相同和高比例重叠路线进入重复组并阻断交付。”（OPT §3）
- “同类型双向轨迹重合率 | 低于 **90%**”（OPT §3，即同类型路线双向轨迹重合率必须 <90%）。
- 去重同时检查（OPT playbook §6）：相同坐标序列；反向坐标序列；高比例重叠的同向或反向轨迹；名称不同但骨架、起终点和覆盖区域高度一致的路线。“仅修改名称不构成有效去重。”
- “高比例重叠”的具体百分比阈值：除上述 90% 重合率外，未在 Skill 中另行定义。

---

## 2. GEOMETRY / SPATIAL QUALITY THRESHOLDS（几何与空间质量阈值）

来源：OPT route-quality-contract.md §2–§3（下表为逐字引用）与 OPT scripts/route_quality_gate.py 常量。

OPT §3 硬性几何门槛表（逐字）：

| 检查项 | 门槛 |
| --- | ---: |
| 连续性 | 单一连续 `LineString`，至少两个有效坐标 |
| 严格闭环拓扑 | 单一连通分量、环秩为 1、节点度数均为 2 |
| 重复无向边 | 累计比例不高于 2% |
| 单条重复边 | 低于 30 米 |
| 局部折返 | 地图上无可感知折返；短刺探测为失败信号 |
| 分叉或自交 | 清零；路线图节点度数高于 2 时进入人工复核 |
| 步行、跑步途经点偏移 | 不高于 50 米 |
| 骑行途经点偏移 | 不高于 100 米 |
| 高德距离与几何长度误差 | 不高于 3% |
| 实际距离与目标里程误差 | 不高于 15% |
| 徐汇区内轨迹比例 | 达到 90%，已批准跨区连接场景除外 |
| 存疑路段 OSM 可通行路网贴合率 | 查询到有效证据时达到 98% |
| 同类型双向轨迹重合率 | 低于 90% |
| 同模式路线重复 | 相同、反向相同和高比例重叠路线进入重复组并阻断交付 |

逐项说明与脚本对应值：

1. **徐汇区内轨迹比例 ≥ 90%**（已批准跨区连接场景除外）。测量方式：统一坐标系后相对徐汇区边界计算 [inferred：Skill 未给出具体算法，仅要求“区内比例……计算前统一坐标系”]。
2. **道路贴合（road-snapping）**：“存疑路段 OSM 可通行路网贴合率 | 查询到有效证据时达到 **98%**”；测量方式：“OSM 或 Overpass 仅处理通行性、运动模式或路网贴合存疑片段”，主门禁为“高德原始路径、本地几何门禁和浏览器全景目视”。
3. **距离误差**：高德 API 距离 vs 几何长度 ≤ **3%**（脚本 `DISTANCE_ERROR_MAX = 0.03`）；实际 vs 目标 ≤ **15%**（`TARGET_ERROR_MAX = 0.15`）。
4. **闭环闭合容差**：“严格闭环首尾距离不高于 **30 米**”（脚本 `LOOP_ENDPOINT_MAX_M = 30.0`；超过 → `open_loop`）。闭环起终点标记相距同样 ≤30 米（`MARKER_ENDPOINT_MAX_M = 30.0` → `loop_marker_mismatch`）。闭合点附近 **75 米**（`STRICT_LOOP_CLOSURE_MARGIN_M = 75.0`）内的首尾接近不计为局部回环。
5. **单程端点分离**：“单程路线的起终点直线距离高于 **200 米**”（脚本 `ONE_WAY_ENDPOINT_MIN_M = 200.0`；≤200 → `weak_one_way` / `weak_one_way_markers`）。
6. **重复边（repeated edge）**：累计比例 ≤ **2%**（`RETRACE_RATIO_MAX = 0.02`），单条重复边 < **30 米**（`RETRACE_EDGE_MAX_M = 30.0`；≥30 → `retraced_edges`）。边按坐标四舍五入到 **5 位小数**（`ROUND_DIGITS = 5`）后作无向边去重统计。
7. **自交 / 分叉**：清零（proper 自交 = 非相邻线段内部交叉，`proper_self_intersection_count` 必须为 0）；节点度数 > 2 → `branch_or_self_intersection` 失败并“进入人工复核”。
8. **折返（retracing）检测**（脚本数值定义）：
   - 局部 U 型折返（`local_uturn`）：连续三点 A-B-C，`dist(A,B) ≥ 15 m` 且 `dist(B,C) ≥ 15 m` 且 `dist(A,C) ≤ 10 m`，检出数必须为 0。
   - 局部回环（`local_return_loop`）：轨迹上两点路径距离 ≥ **200 m**（`LOCAL_RETURN_PATH_MIN_M = 200.0`）而直线距离 ≤ **20 m**（`LOCAL_RETURN_RADIUS_M = 20.0`），检出数必须为 0。
   - 单程曲折系数：几何长度 / 起终点直线距离 ≤ **2.5**（`ONE_WAY_CIRCUITY_MAX = 2.5` → `excessive_circuity`）。
9. **端点标记偏移容差**：起点/终点标记偏离轨迹首/末端 ≤ **30 米**（`MARKER_ENDPOINT_MAX_M = 30.0` → `start_marker_offset` / `end_marker_offset`）。
10. **途经点偏移**：walk/run ≤ **50 m**，bike ≤ **100 m**（脚本 `limit = 100.0 if mode == "bike" else 50.0` → `waypoint_offset`）；首末导航节点与轨迹端点偏移同限值（`node_order_endpoint_mismatch`）。
11. **最少顶点/节点数**：轨迹“至少两个有效坐标”（<2 → `missing_geometry`）；导航节点“普通路线使用 **2–6** 个真实命名节点；长距离骑行上限为 **8** 个”。节点数下限的硬门禁：未在 Skill 中定义（2–6 为设计要求）。
12. **坐标系要求**：“每份轨迹、边界、节点和 POI 数据声明 GCJ-02 或 WGS84。区内比例、最近距离、端点偏移和路线重合计算前统一坐标系。使用一个已知区内点、一个已知区外点和一条跨边界样例验证转换方向。”距离计算用 haversine，地球半径 `EARTH_RADIUS_M = 6_371_008.8` 米（脚本常量）。
13. **严格闭环拓扑**（脚本 `strict_loop_topology`）：吸附图单一连通分量（`component_count == 1`）、环秩 `cycle_rank == 1`、所有节点度数为 2（`non_degree_two_node_count == 0`）；不满足 → `false_loop_topology`。
14. 占位名称：“全数据链不存在‘实测节点’、带编号占位节点和纯数字节点”，检出即阻断交付（OPT §8 / playbook §2）。

---

## 3. FALSE-LOOP / SHAPE DEFECT DEFINITIONS（假闭环与形态缺陷定义）

来源：OPT SKILL.md「Shape contract」、route-quality-contract.md §2/§4、playbook §3–§4。

`strict_loop` 有效闭环的四个必要条件（逐字，OPT §2）：

1. 轨迹吸附后形成一个连通分量。
2. 图的环秩为 1，每个节点度数为 2。
3. 全图只有一个清晰主环，覆盖一个连贯空间区域。
4. 无哑铃形、葫芦形、双叶形、长柄环或两个环共用连接段。

“出现多个环、异常度数节点或重复连接段时标记 `false_loop_topology`。”

各缺陷定义：

| 缺陷 | Skill 定义 / 数值判据 |
| --- | --- |
| 双环（double loop / 双叶形） | “上下两个大环由窄段拼接——只满足首尾闭合，路线形成双环或哑铃形”；拓扑判据为环秩 >1 或多连通分量（`cycle_rank == 1` 与 `component_count == 1` 之外即失败）。处理：“保留一个真实环，或沿全区外围重画单一大环”；“距离不足时……禁止拼接第二个小环”。 |
| 哑铃形（dumbbell） | 两个大环由窄连接段拼接（同“双环”成因行）；reject 列表包含 “dumbbells”。独立数值判据：未在 Skill 中定义（由环秩/度数/视觉判定）。 |
| 葫芦形（gourd） | reject 列表：“Reject double loops, dumbbells, gourds, figure eights, long entrance stems, repeated connectors, internal spurs, and local loops.”；视觉验收“无双环、哑铃形、葫芦形、长柄环和多叶形态”。独立数值判据：未在 Skill 中定义。 |
| 长柄环（long entrance stem / 长入口柄） | “闭环带长入口柄——起点未落在真实环路上”；处理：“移动起终点到环路，或改成单程”；要求“起终点落在真实环路上，移除共用入口柄”。柄长数值阈值：未在 Skill 中定义（由环秩 1 + 度数 2 + 视觉判定；闭合点 75 m margin 只用于豁免局部回环检测）。 |
| 局部折返（local retrace） | 数值判据见 §2.8：U 型折返（两腿 ≥15 m、端距 ≤10 m）计 0；局部回环（路径 ≥200 m、闭合半径 ≤20 m）计 0；重复边累计 ≤2%、单条 <30 m。“地图上无可感知折返；短刺探测为失败信号。” |
| 断头（dead end） | “Remove … dead ends”（节点清理）；视觉验收“无矩形回环、局部折返、支叉、断头和重复走廊”。“进入景点后原路退出——景点位于尽端、院内或单一入口 → 转为沿线 POI，主线留在公共道路”。数值判据：未在 Skill 中定义。 |
| 支叉（spur / fork） | “internal spurs” 被 reject；“一条线出现视觉分叉——共用路段重复经过或节点顺序跨越 → 重画主骨架”；脚本判据：分叉节点（去重邻接度 >2）计数必须为 0，`strict_loop` 除闭合点外任何节点度数必须为 2。 |
| 穿越不可通行区域 | 审计项：“轨迹跨越封闭园区、围墙、河道或快速路”；`nearby` 公园“还需核实步行连接；河道、快速路、围墙或封闭门区等明显阻隔进入复核”。数值判据：未在 Skill 中定义（OSM/Overpass 存疑段贴合率 98% 为证据门槛）。 |
| 矩形回环 | “地铁站附近出现矩形回环——节点落在道路另一侧或分段路由各自选择入口 → 删除该导航节点，改用主路交叉口”。 |
| 8 字交叉（figure eight） | reject 列表项；对应“分叉或自交清零”与 proper 自交计数为 0。 |

形态二选一的语义（OPT SKILL.md 逐字）：

- `one_way`：distinct recognizable endpoints, continuous forward movement, no local return leg（起终点直线距离 >200 m）。
- `strict_loop`：start and end together, one connected simple cycle, cycle rank 1, degree 2 at every snapped graph node, one coherent spatial area（首尾 ≤30 m）。
- “Endpoint proximity proves coordinate closure only. A visual full-route check remains required after topology passes.”

---

## 4. ROUTE STATUS MODEL（accepted vs needs_review）

来源：OPT §7、RBE failure-modes.md、OPT SKILL.md。

- `validation_status` 枚举：**`accepted` | `needs_review`**（脚本：其他值 → `invalid_validation_status`）。
- “`validation_status` 只由几何、实际里程、起终点、道路证据和视觉质量决定。POI 数量、四类偏好覆盖数和补给告警进入独立 `poi_audit`，真实空结果不会改变路线状态。”（OPT §7；SKILL.md：“POI quantity never changes `validation_status`.”）
- `accepted` 含义：路线验收“covers geometry, actual distance, endpoints, road evidence, coordinate correctness, and full-map visual quality” 全部通过。
- `needs_review` 触发条件：
  - “A visually confusing route remains `needs_review` even when local metrics pass.”（OPT SKILL.md）
  - 视觉验收清单（OPT §8，9 项）任何一项失败：“任何一项失败时保持 `needs_review`，回到骨架设计阶段。”
  - RBE：“视觉存疑 | 本地指标通过但视觉混乱 | 保持 `needs_review`，不标 `accepted`”；停止条件：“视觉验收存疑的路线仍标 `accepted`（应为 `needs_review`）”。
- 状态使用规则：
  - “`accepted` 与 `needs_review` 均在地图和路线目录中可查看。”
  - “推荐结果与正式导航选择仅使用 `validation_status == accepted` 的路线。”
  - “过程门禁允许 `needs_review` 留在可查看目录；最终门禁使用 `--require-all-accepted`，验收状态达到 **90 条 `accepted`、0 条 `needs_review`**。”
  - 脚本：`--require-all-accepted` 时 `accepted != expected_route_count` → `not_all_routes_accepted`；web 目录中 `recommendation_eligible`/`navigation_eligible` 必须等于 `status == "accepted"`。

---

## 5. ENVIRONMENT DATA CONTRACT（环境数据契约）

来源：WEP SKILL.md、data-semantics.md、snapshot-files.md、scripts/verify_environment_snapshot.py。

### 5.1 网格

- PM2.5：“格网与站点融合估计（和风天气、上海空气质量站点、CHAP 背景）| **54 个约 1 km 网格** | 空间估计，不等同道路旁实时监测仪读数”。
- `grid_environment_latest.json`：“**54** 个约 1 km 网格的环境量”。
- 花粉：“日级网格背景，可能含天气条件代理修正 | 约 1 km 网格、按日”。
- 噪声：“**0-100 风险代理**，来自道路类型、交通邻近、POI、路口、绿地水体等特征 | 约 **100 m** 路段”。
- 网格精确 extent / 分辨率定义（如边界框、行列数）：未在 Skill 中定义（只有“54 个约 1 km 网格”）。

### 5.2 必备变量与文件

快照文件（`weather_api_data/runtime/exports/`）：`environment_latest.json`（当前天气、AQI、生活指数、预警）、`environment_hourly.json`（未来 **24 小时**逐小时序列）、`grid_environment_latest.json`（54 网格）、`pollen_grid_scores.json`（网格花粉日级）、`noise_segments.json`（约 100 m 路段噪声代理）、`route_environment.json`（**90 条**路线暴露汇总）。

绿地、水体作为独立变量：未在 Skill 中定义（仅作为噪声代理的输入特征“绿地水体等特征”出现）。

### 5.3 dashboard 结构与路线连接

- `environment_dashboard.json` 顶层必须含 **`current`、`forecast`、`grids`、`metadata`、`routes`** 五个键（脚本 `TOP_KEYS`）。
- `routes`：“count / items / status；items 覆盖 **90** 条路线”（脚本 `EXPECTED_ROUTES = 90`；`routes.count` 必须等于 items 长度）。
- **连接方式**：`routes.items[]` 通过 `route_id` 与 `route_catalog.json` 连接——“`routes` 覆盖 90 条路线且 `route_id` 与路线目录一致”（WEP Quality gates）；脚本双向检查：目录中缺环境条目、或环境条目不在目录中，均为 FAIL。
- 每个 item 字段（脚本 `ITEM_KEYS` + snapshot-files.md）：`route_id`、`status`、`pm2_5`、`noise`、`pollen_daily`、`access_route_environment`、`segment_count`、`total_length_m`。
- `pm2_5` / `noise` 块字段：`business_time`、`status`、`spatial_scale`、`estimated`、`confidence`、`unit`、`value`、`coverage_ratio`、`fetched_at`、`expires_at`、`source`；`pollen_daily` 为按日对象数组，字段同上。
- `access_route_environment`：“接驳路径环境，当前为 `not_computed` / `not_aggregated`”。

### 5.4 单位、时间粒度、状态与缺值编码

- 单位（data-semantics.md）：`unit` 例如 “**µg/m³**、**0-100 risk index**”。
- `spatial_scale` 例如 “about_1000m_grid、about_100m_road_segment_proxy”。
- 时间粒度：当前天气/AQI（实时）、未来 24 小时逐小时、花粉按日、噪声按路段（时间粒度未在 Skill 中定义）。
- 状态枚举（脚本 `STATUS_ENUM`）：`ok`、`partial`、`stale`、`error`、`missing`、`not_computed`、`not_aggregated`、`skipped`。语义（data-semantics.md）：`partial`=部分来源或字段缺失；`stale`=沿用上一份有效快照；`estimated`=模型或代理估计（布尔标记）；`ok`=来源齐全且新鲜；`error`=来源失败；`not_computed`/`not_aggregated`=未计算或未汇总。
- 所有报告必须保留字段：`business_time`、`valid_until`、`status`、`spatial_scale`、`estimated`、`confidence`、`unit`（脚本检查其中 `business_time, status, spatial_scale, estimated, confidence, unit` 六个，`REPORT_FIELDS`）。
- **缺值率上限**：脚本 `MISSING_RATE_LIMIT = 0.10` —— 每个报告字段在 90 条路线条目中的缺失率 > **10%** 即 FAIL（“缺失率被计算并报告”）。
- 缺值编码规则：“缺 Key 时使用 last-known-good，不创建填充值；`partial`/`stale`/`estimated` 如实标记”；“未来 PM2.5 缺值保留缺值，不从 AQI 反推浓度”。
- 时间字段 `generated_at`、`business_time`、`fetched_at` 必须可解析（ISO-8601）。
- 敏感信息：快照与报告中不含绝对路径、Key（脚本正则扫描 `sk-…`、`LTAI…`、`AKIA…`、`ghp_…`、`Bearer …` 与 Windows/Unix 绝对路径）。
- 表述边界：“不把网格 PM2.5 写成道路实测值；不把 0-100 噪声代理写成实时分贝。”
- 在线更新节奏（背景）：Cloudflare 每 **15 分钟**触发天气主刷新；GitHub Actions 小时级空气质量更新与每日完整更新。

---

## 6. EVALUATION MODEL CONTRACT（评价模型契约）

来源：EVE SKILL.md、scoring-contract.md、experiment-matrix.md、score-candidates-contract.md。

### 6.1 五维评分

维度顺序固定（与 `scoring.py` 一致）：

1. `environment_health`
2. `sport_match`
3. `access_convenience`
4. `route_quality`
5. `interest_service`

- 维度权重：“权重来自 `config/default_weights.json` 的 `goal_weights`（按目标意图：`balanced`、`health_environment`、`distance_training`、`relax`、`scenery`、`family`、`nearby`）”。**五维各自的具体权重数值：未在 Skill 中定义**（在模块配置文件中，且本次任务边界禁止读取）。
- 分数范围：未在 Skill 中定义 [inferred：由 `missing_metric_score=50.0` 与预警惩罚 8/15 分推测为 0–100 分制]。
- 环境子权重（逐字）：`environment_weights`：`pm2_5=45`、`noise=35`、`pollen=20`。
- 其他常量：敏感项加成 `sensitivity_boost=30`；缺指标默认分 `missing_metric_score=50.0`；核心兴趣权重下限 `core_interest_weight_floor=60.0`。

### 6.2 数据可靠度

| 机制 | 取值（逐字） |
| --- | --- |
| `status_reliability` | `ok=1.0`、`partial=0.7`、`stale=0.0`、`no_data=0.0`、`error=0.0` |
| `confidence_reliability` | `high=1.0` … `low=0.5`（含中文别名） |
| `estimated_reliability` | `0.9` |

“可靠度用于降权与标记；`stale`/`error` 数据不得静默参与排序。”

### 6.3 硬约束与风险暂停（`risk_thresholds`，逐字）

- 降水：警告 **2.5 mm**，暂停 **10.0 mm**。
- 体感温度：警告 **35°C**，暂停 **40°C**。
- 阵风：警告 **40 km/h**，暂停 **62 km/h**。
- AQI：警告 **100**，敏感人群暂停 **150**，全员暂停 **200**。
- 预警惩罚：蓝色 **8** 分、黄色 **15** 分。
- “命中暂停阈值时输出暂停结论，不强行推荐。”

距离硬约束（experiment-matrix.md）：

- 同端点附加距离：ρ_detour = (d_candidate − d_shortest) / d_shortest ≤ **0.20**。
- 运动路线目标距离偏差：ρ_target = |d_route − d_target| / d_target ≤ **0.15**。
- 接驳距离服从用户搜索半径与现有硬约束（数值：未在 Skill 中定义）。

### 6.4 基线实验矩阵

基线（预注册，模型无法临时改动）：

| ID | 规则（逐字摘要） |
| --- | --- |
| `B0_shortest_feasible` | 在可行候选中最小化目标距离偏差与接驳距离 |
| `B1_pm25_only` | 在距离门禁内最小化 PM2.5 |
| `B2_multi_environment` | 综合 PM2.5、噪声和花粉，忽略个人兴趣 |
| `B3_non_personalized` | 使用默认平衡权重，不提升敏感项与兴趣项 |
| `M1_personalized_constrained` | 使用用户目标、敏感项、兴趣、接驳和数据可信度，受附加距离门禁约束 |

预设画像至少覆盖：walk/run/bike；balanced/health_environment/nearby/scenery；空气、花粉、噪声敏感；滨水、公园、安静、厕所、便利设施偏好；无出发点全徐汇筛选与有出发点接驳筛选；每案例唯一 `case_id`。“v1 不扩展为系统性消融实验，也不引入多时段环境快照实验。”

统计：只用标准库，固定 **seed 1234**；输出中位数、四分位距、胜率、约束通过率、配对差值、配对 **bootstrap 95%** 区间。

### 6.5 支持状态门禁（`quality_gates.json` 预注册，逐字）

```json
{
  "supported": {
    "detour_pass_rate_min": 0.90,
    "environment_win_rate_min": 0.60,
    "preference_win_rate_min": 0.60,
    "reference_verification_rate_min": 1.0,
    "fatal_data_errors_max": 0
  }
}
```

状态：`supported`、`partially_supported`、`unsupported`、`inconclusive`。

### 6.6 职责边界与接口

- Python 负责硬约束、风险暂停和基础分；“Qwen 只审核候选与生成解释，不重算硬约束、不修改候选 ID”。
- `score-candidates` 输出 JSON：`profile`、`risk`、`data_generated_at`、`candidate_count`（等于 candidates 长度）、`candidates`（全部通过硬约束、保留排序和维度分）、`weights_sha256`。
- 千问审核用 `QWEN_MODEL=qwen3.8-max` 环境变量覆盖；异常时回退本地 Python 排序并保留审计。
- “综合效用不作为唯一验证指标”；“最终结论只依据 `base_score`”是停止条件。

---

## 7. WEB PRODUCT CONTRACT（网页产品契约）

来源：WEB SKILL.md、web-payload-contract.md、ui-contract.md、scripts/verify_web_payload.py；OPT §7–§8。

### 7.1 Payload：`xuhui_route_builder/data/web/research_harness_latest.json`

- 由 `qwen-harness publish <run-id>` 在 PublishGate 通过后原子写入（临时文件 + 原子替换）。
- Schema（`schema_version: "1.0"`）必备键：`schema_version`、`run_id`、`generated_at`、`status`、`research_question`、`hypothesis`、`selected_route{route_id, route_name, reason}`、`key_metrics[]`、`baseline_comparison[]`、`iterations[]`、`references[]`、`limitations[]`、`artifacts[]`。
- `status` ∈ `supported | partially_supported | unsupported | inconclusive`。
- `selected_route.route_id` 必须存在于当前 `route_catalog.json`；结论表述固定为“当前候选集中的约束最优路线”。
- `references`：HTTPS 或明确本地来源（脚本拒绝其他 scheme）；`artifacts`：只允许仓库相对路径或 https URL（http:// 与绝对路径 FAIL）。
- 脱敏：payload 与页面不出现本地绝对路径、模型密钥、内部日志和完整自由文本（脚本正则同 §5.4）。
- `baseline_comparison` 含变体 ID（B0–B3、M1）。

### 7.2 页面结构与面板

- 新文件：`web/src/research-harness-ui.js`、`web/styles/research-harness.css`、`tests/research_harness_data_contract.test.mjs`、`tests/research_harness_ui_contract.test.mjs`；对 `index.html`、`main.js`、`data-loader.js` 只做最小接线。
- 技术约束：原生 HTML/CSS/JS，“不引入 React、Vue、构建器或包管理依赖”。
- 面板内容（9 项）：研究问题、当前假设与支持状态、证据与引用数量、基线对比、关键指标、候选集约束最优路线、迭代时间线、数据限制与代理变量说明、研究报告相对路径。
- 行为：数据文件存在且通过 Schema → 展示“AI Scientist 实验”入口；缺失或状态错误 → 隐藏入口，控制台记录一次警告，不影响地图与推荐。
- 地图联动：选中路线通过现有 route ID 机制联动地图，不改写地图核心状态管理；`selected_route.route_id` 不在目录 → 不联动，展示降级文案。
- 渲染安全：模型文本只用 `textContent` 等安全 DOM API，禁止 `innerHTML` 注入。

### 7.3 路线卡片 / 地图要素（OPT §7–§8）

- 页面显示运动类型、里程档和 `strict_loop` / `one_way` 形态。
- “环线显示单一‘起终点’，单程显示独立起点和终点”；“三种运动、两种形态均显示方向箭头”。
- 公园标签：直接经过（≤100 m）显示“公园入口”；100–200 m 显示“邻近公园·约 N 米”；标记落在真实入口位置；零 POI 路线不出现设施标记。
- 待考证路线清晰显示状态，退出自动推荐与正式导航入口。
- 最终发布前检查：展示 90 条、三种运动各 30 条、环线与单程统计以及推荐和导航过滤。

### 7.4 响应式与可访问性验收

- 断点：**桌面 + 500×700 窄屏**（“Run desktop and 500×700 browser acceptance”；OPT/RBE/WEB 一致）。其他断点数值：未在 Skill 中定义。
- 检查项：marker overlap（标记碰撞）、horizontal overflow（横向溢出）、文字遮挡；面板不覆盖地图核心控件；长标题与引用可换行；键盘可操作；“状态不只依赖颜色（配文字或图标）”。
- 新旧契约测试全部通过（`node --test xuhui_route_builder/tests/*.test.mjs`）。

### 7.5 PublishGate 检查（web-payload-contract.md 逐字）

- `scientific_plan.json` 通过 Schema。
- 网页 payload 无敏感信息和绝对路径。
- 选中路线 ID 存在于当前 `route_catalog.json`。
- 引用 URL 为 HTTPS 或明确本地来源。
- 前端契约测试通过。

---

## 8. EVIDENCE / HYPOTHESIS CONTRACT（证据与假设契约）

来源：SEH SKILL.md、evidence-schema.md、citation-policy.md、hypothesis-rubric.md、source-adapters.md、contest-output-fields.md、scripts/validate_*.py。

### 8.1 SourceRecord（`sources/source_registry.jsonl`，逐行一条）

字段：`source_id`、`source_type`、`title`、`authors`、`year`、`doi`、`pmid`、`url`、`local_path`、`accessed_at`、`sha256`、`license_note`、`verification_status`。

- `source_type` ∈ `local_file | pubmed | crossref | https_url | repository_file`。
- `verification_status` ∈ `verified | partial | unverified | rejected`。
- 脚本判据：`source_id` 全局唯一；`sha256` 必须为 64 位十六进制（<code>^[0-9a-fA-F]{64}$</code>）；DOI 格式 <code>^10\.\d{4,9}/\S+$</code>；`accessed_at` ISO-8601；`repository_file` 必须有 `local_path`。
- “缺作者、年份、DOI/PMID 时置 `null`，不推断。”`https_url` 记录抓取页面正文哈希；仅 HTTPS、允许域名；“URL 含用户名、密码或片段时拒绝”。

### 8.2 EvidenceClaim（`sources/evidence_cards.jsonl`）

字段：`claim_id`、`source_id`、`claim`、`evidence_location`、`short_excerpt`、`evidence_type`、`support_strength`、`caveats`。

- `evidence_type` ∈ `result | method | dataset | limitation | definition | policy`（六类）。
- `support_strength` ∈ `high | medium | low`。
- `source_id` 必须已在注册表（否则引用门禁拒绝，`validate_evidence_links.py` 校验）；`evidence_location` 用页码、章节、摘要字段或模块文件路径；“涉及数值的 claim 必须在原文或模块结果中可找到”；`short_excerpt` 长度受 `source_policy.json` 上限约束（具体字节数：未在 Skill 中定义）。

### 8.3 KnowledgeGap

字段：`gap_id`、`statement`、`supported_by_claim_ids`、`affected_variables`、`why_unresolved`、`available_data`、`missing_data`、`testability`（high/medium/low）、`product_relevance`（high/medium/low）。“知识缺口必须由多个 Claim 支持，或明确说明单一来源的局限。”

### 8.4 HypothesisCandidate / HypothesisSet / ExperimentPlan

- `HypothesisCandidate` 字段：`hypothesis_id`、`statement`、`mechanism`、`independent_variables`、`dependent_variables`、`moderators`、`expected_direction`、`falsification_criteria`、`required_data`、`supporting_claim_ids`、`novelty_argument`、`feasibility_score`、`scientific_value_score`、`risks`。
- `HypothesisSet` 含 **3 个候选** 与 `recommended_hypothesis_id`；`supporting_claim_ids` 必须全部可解析。
- 所有模型继承 `StrictModel`（`extra="forbid"`）。
- 假设 rubric（总分 **100**）：科学价值 **0-25**、新颖性 **0-20**、可证伪性 **0-20**、数据可得性 **0-15**、工程落地 **0-10**、表述边界 **0-10**。“可证伪性为 0 的假设直接淘汰，无论总分。”“总分只是选择辅助：Critic 仍必须列出反例和数据风险。”
- 通过分数阈值（多少分算合格）：未在 Skill 中定义。

### 8.5 可接受引用（citation policy）

- “先注册来源，后生成 Claim”；“模型不得创建新的作者、DOI、PMID、年份或数值”；“证据不足时返回缺口，不补写”。
- CitationGate：`source_id` 存在；证据位置存在；`verification_status` 达标（**核心结论要求 `verified`**）；结论数值可追溯到 Claim 或模块结果；参考文献去重；标题/DOI/PMID 组合一致。
- EvidenceGate：**参考文献核验率 100%**（`reference_verification_rate_min: 1.0`，与 EVE 支持门禁一致）；“任何无法核验的核心引用触发停止条件，必须从结论中移除或降级为非核心背景”。
- Crossref 适配器：“标题相似度过低、年份冲突或 DOI 格式异常时标记 `partial` 或 `rejected`”（相似度数值阈值：未在 Skill 中定义）。
- `scientific_plan.json` 校验（validate_scientific_plan.py）：必备非空字段 `problem_statement`、`rationale`、`technical_details`、`paper_title`、`paper_abstract`、`methods`、`results`、`references`、`limitations`、`reproducibility`；`datasets.source`/`datasets.target`；`experiments.baselines`/`experiments.metrics`；`references` 至少 1 条、全部解析到注册表且不重复。

### 8.6 Provenance（溯源）记录方式

- `ScientificPlan` 必含溯源字段：**`run_id`、`git_head`、`data_snapshot_hashes`**（脚本 `PROVENANCE_FIELDS`，缺失或为空即 FAIL）；另有 `evidence_map`：“结论到 `claim_id`/模块结果的映射”。
- 表述分类要求（逐字）：“结果报告区分**观测事实、模型估计、代理变量和推断**”；证据类型六分类（result/method/dataset/limitation/definition/policy）承担 Claim 级溯源；环境块用 `estimated`（布尔）、`confidence`、`source`、`status` 标记模型/代理来源。
- 任务中提到的四分类“raw data / deterministic computation / model judgement / manual setting”这一确切枚举：**未在 Skill 中定义**；Skill 中最接近的对应物是上述“观测事实 / 模型估计 / 代理变量 / 推断”四分类与 `run_id`/`git_head`/`data_snapshot_hashes` 溯源字段 [inferred：如需四类 provenance 标签，应在 run 派生配置中按此映射自行登记]。
- 隐私脱敏（QHO run-artifact-contract.md）：运行目录与日志不得出现 API Key、Authorization 头、URL 凭据、用户目录绝对路径、用户自由文本画像原文、模型内部推理文本（“仅显式 `rationale`、`mechanism`、审查意见进入输出模型”）；环境变量日志只记名称，敏感值写 `[REDACTED]`。

---

## 9. HARNESS 运行参数（补充，来源 QHO）

- 模型 `qwen3.8-max`，`temperature=0.2`，`seed=1234`，各阶段 `reasoning_effort=medium`。
- `max_iterations` 默认 **2**；达到上限仍不清晰 → 输出 `inconclusive`。
- 退出码：**0** 成功；**1** 门禁未通过或结果不支持假设但程序完整；**2** 配置/输入/契约错误；**3** 模型 API 或外部来源故障且无回退；**4** 模块命令失败；**5** 运行状态损坏、锁冲突或恢复失败。
- 重试：结构化输出解析失败重试 **1** 次；连接超时/5xx/限流最多重试 **2** 次（指数退避）。
- 施工纪律：一次任务不超过 **3** 个文件；大文件保持 **400** 行内。
- 批次上限（OPT）：每批最多 **5** 条路线。
- 技能源边界：`.qoder/skills/`（不扫描 `.agents/skills`）。

---

## 10. GATE TABLE（数值门禁总表）

| gate id | metric | threshold | source skill | how to measure |
| --- | --- | --- | --- | --- |
| G-01 | 路线总数 | = 90 | OPT / RBE | `route_portfolio_gate.py`：`route_count_mismatch` |
| G-02 | 每模式路线数 | walk=30, run=30, bike=30 | OPT / RBE | 同上：`mode_count_mismatch` |
| G-03 | 每模式每距离档条数 | = 10（三档） | OPT | 实际距离入档计数：`distance_bucket_count_mismatch` |
| G-04 | walk 距离档 | 0.5–2 / 2–3.5 / 3.5–5 km | OPT / RBE | `DISTANCE_BUCKETS`（500–2000/2000–3500/3500–5000 m，下闭上开，末档含上界） |
| G-05 | run 距离档 | 1–5 / 5–10 / 10–15 km | OPT / RBE | 同上（1000–5000/5000–10000/10000–15000 m） |
| G-06 | bike 距离档 | 5–10 / 10–20 / 20–30 km | OPT / RBE | 同上（5000–10000/10000–20000/20000–30000 m） |
| G-07 | strict_loop 数（每模式） | 目标 15，允许 14–16 | OPT | `shape_balance_mismatch` |
| G-08 | one_way + strict_loop（每模式） | = 30 | OPT | 同上 |
| G-09 | 区域覆盖 | 8 个命名区域各 ≥1 条 | OPT | `popular_area_coverage_gap`（`POPULAR_AREAS`） |
| G-10 | route_id 唯一性 | 重复数 = 0 | OPT / RBE | `duplicate_route_ids`；目录集合 == GeoJSON 集合 |
| G-11 | 徐汇区内轨迹比例 | ≥ 90%（批准跨区连接除外） | OPT | 统一坐标系后对徐汇边界计算 |
| G-12 | 存疑路段 OSM 可通行路网贴合率 | ≥ 98%（查询到有效证据时） | OPT | Overpass/OSM 对存疑片段贴合 |
| G-13 | 高德距离 vs 几何长度误差 | ≤ 3% | OPT | `DISTANCE_ERROR_MAX = 0.03`：`api_geometry_distance_mismatch` |
| G-14 | 实际 vs 目标里程误差 | ≤ 15% | OPT / EVE | `TARGET_ERROR_MAX = 0.15`；ρ_target ≤ 0.15 |
| G-15 | strict_loop 首尾闭合距离 | ≤ 30 m | OPT | `LOOP_ENDPOINT_MAX_M = 30.0`：`open_loop` |
| G-16 | one_way 起终点直线距离 | > 200 m | OPT | `ONE_WAY_ENDPOINT_MIN_M = 200.0`：`weak_one_way` |
| G-17 | 起/终点标记偏移 | ≤ 30 m | OPT | `MARKER_ENDPOINT_MAX_M = 30.0`：`start/end_marker_offset` |
| G-18 | 重复无向边累计比例 | ≤ 2% | OPT | `RETRACE_RATIO_MAX = 0.02`：`retraced_edges` |
| G-19 | 单条重复边长度 | < 30 m | OPT | `RETRACE_EDGE_MAX_M = 30.0` |
| G-20 | 局部 U 型折返 | 计数 = 0（两腿 ≥15 m 且端距 ≤10 m） | OPT | `local_uturn_metrics`：`local_uturn` |
| G-21 | 局部回环 | 计数 = 0（路径 ≥200 m 且闭合半径 ≤20 m；闭环首尾 75 m 内豁免） | OPT | `local_return_loops`：`local_return_loop` |
| G-22 | 分叉节点 / proper 自交 | = 0（度数 >2 进入人工复核） | OPT | `branch_or_self_intersection` |
| G-23 | strict_loop 拓扑 | 连通分量 =1、环秩 =1、非 2 度节点 =0 | OPT | `strict_loop_topology`：`false_loop_topology` |
| G-24 | one_way 曲折系数 | ≤ 2.5 | OPT | `ONE_WAY_CIRCUITY_MAX = 2.5`：`excessive_circuity` |
| G-25 | 途经点偏移 | walk/run ≤ 50 m；bike ≤ 100 m | OPT | `waypoint_offset` / `node_order_endpoint_mismatch` |
| G-26 | 轨迹最少有效坐标 | ≥ 2 | OPT | `missing_geometry` |
| G-27 | 导航节点数 | 普通 2–6；长距离骑行 ≤ 8 | OPT | 设计规则（骨架审查） |
| G-28 | 同类型双向轨迹重合率 | < 90% | OPT | 同模式轨迹重合计算（统一坐标系） |
| G-29 | 相同/反向/高重叠重复路线 | 重复组 = 0（阻断交付） | OPT / RBE | 坐标序列正反向比对 + 相似组 |
| G-30 | 占位节点名 | “实测节点”/编号/纯数字节点 = 0 | OPT | 全数据链负向搜索 |
| G-31 | validation_status 枚举 | ∈ {accepted, needs_review} | OPT | `invalid_validation_status` |
| G-32 | 最终验收状态 | 90 accepted、0 needs_review | OPT / RBE | `--require-all-accepted`：`not_all_routes_accepted` |
| G-33 | 坐标系声明 | 每份产物声明 GCJ-02 或 WGS84，计算前统一 | OPT / RBE | 声明检查 + 已知区内/区外/跨界样例验证 |
| G-34 | PM2.5 网格数 | 54 个约 1 km 网格 | WEP | `grid_environment_latest.json` / dashboard `grids` |
| G-35 | 噪声空间粒度 | 约 100 m 路段，0-100 风险代理 | WEP | `noise_segments.json`、`spatial_scale` 字段 |
| G-36 | dashboard 顶层键 | current/forecast/grids/metadata/routes 全存在 | WEP | `verify_environment_snapshot.py` |
| G-37 | 环境路线条目数 | = 90 且 route_id 集合 == 路线目录 | WEP | `EXPECTED_ROUTES = 90` + 双向 ID 比对 |
| G-38 | 环境报告字段缺失率 | ≤ 10%（每字段） | WEP | `MISSING_RATE_LIMIT = 0.10` |
| G-39 | 环境状态枚举 | ok/partial/stale/error/missing/not_computed/not_aggregated/skipped | WEP | `STATUS_ENUM` 检查 |
| G-40 | 环境快照敏感信息 | 绝对路径/Key = 0 | WEP / QHO | 正则扫描 |
| G-41 | 五维评分维度 | 5 个维度齐全、顺序固定 | EVE | Quality gates 检查 |
| G-42 | 环境子权重 | pm2_5=45, noise=35, pollen=20 | EVE | `config/default_weights.json` 契约值 |
| G-43 | 敏感项加成 / 缺指标默认分 / 核心兴趣权重下限 | 30 / 50.0 / 60.0 | EVE | scoring-contract.md |
| G-44 | status_reliability | ok=1.0, partial=0.7, stale=0.0, no_data=0.0, error=0.0 | EVE | scoring-contract.md |
| G-45 | estimated_reliability | 0.9 | EVE | scoring-contract.md |
| G-46 | 降水阈值 | 警告 2.5 mm / 暂停 10.0 mm | EVE | `risk_thresholds` |
| G-47 | 体感温度阈值 | 警告 35°C / 暂停 40°C | EVE | 同上 |
| G-48 | 阵风阈值 | 警告 40 km/h / 暂停 62 km/h | EVE | 同上 |
| G-49 | AQI 阈值 | 警告 100 / 敏感暂停 150 / 全员暂停 200 | EVE | 同上 |
| G-50 | 预警惩罚 | 蓝色 8 分 / 黄色 15 分 | EVE | 同上 |
| G-51 | 附加距离约束 ρ_detour | ≤ 0.20 | EVE | experiment-matrix.md |
| G-52 | 基线矩阵 | B0/B1/B2/B3/M1 全运行 | EVE | 预注册变体 |
| G-53 | detour_pass_rate_min | ≥ 0.90 | EVE | `quality_gates.json` |
| G-54 | environment_win_rate_min | ≥ 0.60 | EVE | 同上 |
| G-55 | preference_win_rate_min | ≥ 0.60 | EVE | 同上 |
| G-56 | reference_verification_rate_min | = 1.0（100%） | EVE / SEH | 同上 + CitationGate |
| G-57 | fatal_data_errors_max | = 0 | EVE | 同上 |
| G-58 | 统计 seed / bootstrap | seed 1234；95% 配对 bootstrap 区间 | EVE | `statistics.py` 契约 |
| G-59 | web payload schema | schema_version "1.0"；必备键齐全非空 | WEB | `verify_web_payload.py` |
| G-60 | payload status 枚举 | supported/partially_supported/unsupported/inconclusive | WEB | 同上 |
| G-61 | selected_route.route_id | 存在于 route_catalog.json | WEB | 同上 |
| G-62 | 引用 URL | HTTPS 或明确本地来源；artifacts 仓库相对或 https | WEB | 同上 |
| G-63 | 响应式验收 | 桌面 + 500×700 窄屏通过 | WEB / OPT | 浏览器验收（无横向溢出/标记碰撞） |
| G-64 | POI 走廊 | coffee/toilet/convenience：walk/run 100 m、bike 200 m | OPT | `_poi_relation_issue`（relation 必须 along_route） |
| G-65 | 公园入口关系 | along_route ≤ 100 m；nearby >100–200 m；>200 m 排除 | OPT | 同上 |
| G-66 | 补给告警 | run > 5 km、bike > 10 km 缺 toilet/convenience → 警告（不改状态） | OPT | `long_route_supply_gap` |
| G-67 | preference_hits 一致性 | == 由核实 nearby_pois 派生的类型集合 | OPT | `preference_relation_mismatch` |
| G-68 | 四类偏好搜索状态 | coffee/park_gate/toilet/convenience 各有 ∈ {verified, no_verified_match, needs_review, source_failed} | OPT | `incomplete_preference_search` |
| G-69 | 假设候选数 | HypothesisSet = 3 候选 + 1 推荐 | SEH | evidence-schema.md |
| G-70 | 假设 rubric | 总分 100（25/20/20/15/10/10）；可证伪性 = 0 直接淘汰 | SEH | hypothesis-rubric.md |
| G-71 | SourceRecord 校验 | sha256 64 hex；DOI <code>^10\.\d{4,9}/\S+$</code>；accessed_at ISO-8601；source_id 唯一 | SEH | `validate_source_registry.py` |
| G-72 | scientific_plan 溯源字段 | run_id / git_head / data_snapshot_hashes 非空；references ≥1 且全部解析、去重 | SEH | `validate_scientific_plan.py` |
| G-73 | Harness 模型参数 | qwen3.8-max；temperature=0.2；seed=1234；reasoning_effort=medium | QHO | run_manifest.json |
| G-74 | max_iterations | 默认 2；超限仍不清晰 → inconclusive | QHO | workflow-contract.md |
| G-75 | 批次上限 | 每批 ≤ 5 条路线 | OPT | SKILL.md「Bounded execution」 |
| G-76 | 退出码 | 0/1/2/3/4/5 语义固定 | QHO | cli-contract.md |

### 未在 Skill 中定义（明确缺口清单）

- 五维评分各自的具体权重数值（在 `evaluation_model_qwen/config/default_weights.json`，禁止读取的业务配置）。
- 维度分数范围（0–100 为 [inferred]）。
- PM2.5 网格的精确 extent / 行列定义（只有“54 个约 1 km 网格”）。
- 接驳距离硬约束的具体数值（“服从用户搜索半径与现有硬约束”）。
- “高比例重叠”除 90% 重合率外的独立阈值；哑铃/葫芦/长柄环的独立数值判据（由拓扑 + 视觉判定）。
- 轨迹最少顶点数（只有 ≥2 个有效坐标）与每区域最少路线条数（≥1）。
- `short_excerpt` 长度上限、Crossref 标题相似度阈值（均由 `source_policy.json` 配置控制，数值未在 Skill 中给出）。
- 除 500×700 外的响应式断点数值。
- “raw data / deterministic computation / model judgement / manual setting”四分类枚举本身（最接近的是“观测事实/模型估计/代理变量/推断” + run_id/git_head/data_snapshot_hashes）。
- 假设 rubric 的合格分数线。
