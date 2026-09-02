# Qwen-Harness 第二轮 Qoder Goal 完整提示词

## 1. 文档用途

本文件用于在 Qoder 编程模式中启动 Qwen-Harness 第二轮正式实验。当前 Qoder Goal 会话直接承担研究推理、工程生成、测试与集中修正，模型选择 Qwen3.8-Max，费用通道使用 Qoder Credits。Harness 提供工作流契约、Schemas、Prompts、Skills、确定性计算与质量门禁，`Qwen-Harness/.env` 和百炼在线模型客户端不进入本轮调用链。

第二轮只创建一个新 run，在同一 run 内依次完成独立构建、盲测检查点、成品交互基准辅助的一次集中修正和最终验收。全部新增代码、数据、网页、截图、日志和报告写入 `Qwen-Harness/runtime/runs/<run-id>/`。

## 2. Qoder 启动配置

在 Qoder 中创建一个全新任务，并设置以下选项：

| 配置项 | 设置值 |
| --- | --- |
| 工作区 | `D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop` |
| 分支 | `Qwen_Harness_Build` |
| 运行环境 | 本地模式 |
| 权限 | 完全访问 |
| 模型 | Qwen3.8-Max |
| 执行方式 | Goal |
| 任务数量 | 一个新任务 |
| 正式 run 数量 | 一个新 run |

Qoder 可以运行测试、脚本、本地服务器、浏览器验收和离线夹具。以下在线 Harness 命令保持停用，因为它们会进入 Harness 的百炼模型客户端：

```powershell
uv run qwen-harness run --workflow full-research --allow-network
uv run qwen-harness resume <run-id>
```

开始前保存 Qoder Credits 当前余量和百炼模型调用量截图。任务结束后再次保存相同页面，用于核对模型费用来源。截图属于运行证据，不参与生成内容。

## 3. 可直接粘贴的完整提示词

```text
你正在执行Qwen-Harness第二轮正式实验。

工作区：
D:\SJTU\交大\揭榜挂帅\AI_Scientist_develop

固定分支：
Qwen_Harness_Build

执行模型：
当前Qoder Goal会话中选择的Qwen3.8-Max

任务目标：
由当前Qoder会话直接完成一次完整的Qwen-Harness第二轮研究、工程构建、测试、浏览器验收和一次集中修正。全部新增代码、数据、网页、截图、日志、报告和检查结果只写入一个新的Qwen-Harness/runtime/runs/<run-id>/目录。最终产品需要全面超过第一轮，并达到现有在线成品约60%—70%的功能与视觉完整度。

一、模型与费用边界

1. 模型执行来源固定记录为provider=qoder_session，模型记录为qwen3.8-max。
2. 禁止读取Qwen-Harness/.env及其中的任何Key。
3. 禁止调用DashScope、百炼OpenAI兼容接口、Bailian SDK或任何付费大模型API。
4. 禁止执行会初始化QwenModelClient.from_env()的在线Harness命令。
5. 禁止运行在线qwen-harness run和在线resume。
6. 允许运行离线fixture、确定性脚本、pytest、Ruff、Pyright、Node测试、本地服务器和浏览器验收。
7. 允许访问公开论文、政府页面、公开地理数据、OSM、公开地图服务和普通网页资源。
8. 不生成虚假的百炼request ID。run_manifest.json中明确写入：
   - provider: qoder_session
   - model_name: qwen3.8-max
   - billing_channel: qoder_credits
   - dashscope_api_used: false
9. 若Qoder缺少可读取的任务ID或Credits数值，对应字段写unknown或evidence_pending_user_capture，禁止编造。

二、单run与写入边界

1. 创建符合Harness格式的新run ID：
   run-YYYYMMDDTHHMMSSZ-8位标识
2. 所有交付内容只写入：
   Qwen-Harness/runtime/runs/<run-id>/
3. 仓库根目录下现有Qwen-Harness源码、三个业务模块、文档和第一轮run保持只读。
4. 禁止修改、覆盖或删除：
   - Qwen-Harness现有源码和配置
   - xuhui_route_builder
   - weather_api_data
   - evaluation_model_qwen
   - run-20260902T035556Z-0a43adb5
   - 其他现有run
5. 禁止创建Git提交、分支、PR或远程推送。
6. 包管理器缓存、操作系统临时文件和本地进程文件不作为交付物；仓库内新增成果仍只允许进入本次run。
7. 整个任务采用一个Qoder Goal、一个run ID、一次独立构建、一个blind_checkpoint和一次集中修正。
8. 若会话因上下文或Credits暂停，恢复时继续同一个Goal和run ID，禁止新建第二个run。

三、允许读取的材料

可以读取：

1. Qwen-Harness/README.md
2. Qwen-Harness/src/**
3. Qwen-Harness/config/**
4. Qwen-Harness/schemas/**
5. Qwen-Harness/prompts/**
6. Qwen-Harness/tests/**
7. Qwen-Harness/scripts/**
8. docs/qwen-harness-build/**
9. .qoder/skills/**，包括optimize-xuhui-routes
10. AISci模板和文档/0902文档架构构建.md
11. 第一轮以下诊断材料：
    - run_manifest.json
    - state.json
    - events.jsonl
    - checks/**
    - commands中的测试日志
    - metrics_summary及质量汇总
12. 公开论文、公开数据、公开地理边界与公共路网资料。

读取项目Skill时，将其中规则作为质量契约。若Skill中的脚本引用仓库现有业务数据，只读取规则与阈值，禁止执行脚本去读取现有答案数据。

四、全程隔离的答案材料

以下内容全程禁止读取、搜索、复制或改写：

1. 仓库现有xuhui_route_builder实现代码、网页源码、路线数据、图片与媒体清单。
2. 仓库现有weather_api_data实现代码及生成数据。
3. 仓库现有evaluation_model_qwen实现代码与推荐结果。
4. 第一轮workspace/source/**。
5. 第一轮publish/local-product/**及其中的网页、数据和素材。
6. 第一轮生成源码、页面实现和可直接复用的产品文件。
7. 在线产品的HTML、CSS、JavaScript、接口响应、GeoJSON、JSON和静态资源地址。

公开数据可以作为独立事实来源，但需要在source_registry.jsonl中记录来源、访问时间、用途和许可信息。

五、在线成品参照规则

在blind_checkpoint生成前，禁止访问：

https://zion-johnson99.github.io/AI_Scientist_shanghai_route/web/

blind_checkpoint冻结后，允许通过普通浏览器观察该页面，范围限定为：

1. 桌面与移动端可见界面。
2. 普通鼠标点击、滚动、键盘输入和页面导航。
3. 推荐、筛选、路线详情、地图联动、环境信息、位置输入和移动端布局的可见表现。
4. 浏览器渲染截图。

禁止使用：

1. 查看网页源代码。
2. DOM查询、页面evaluate、元素结构提取或可访问性树导出。
3. 开发者工具。
4. 网络面板、请求拦截和接口响应读取。
5. curl、wget、Invoke-WebRequest或类似方式下载成品页面。
6. 资源文件、图片地址、数据文件和媒体清单提取。
7. 复制成品图片、图标、样式、文案或布局代码。

需要自动截图时，只允许浏览器导航、设置视口、截图以及基于屏幕坐标的鼠标和键盘操作。形成独立视觉语言，禁止逐像素复刻。

六、执行主链

阶段0：执行前核验

1. 核对仓库根目录、分支、HEAD和git status。
2. 记录允许清单、限制清单和模型费用边界。
3. 检查现有进程环境中的DASHSCOPE_API_KEY和OPENAI_API_KEY；测试子进程中清除这些变量。
4. 禁止显示或记录任何Key值。
5. 建立run_manifest.json、provider_manifest.json、inputs/task_prompt.md和inputs/input_boundary.json。
6. 保存本提示词全文及SHA-256。

阶段1：第一轮缺陷基线

只读取第一轮允许的诊断材料，形成checks/round1_defect_baseline.json和reports/第一轮缺陷基线.md。

至少记录：

1. generated_quality.json未通过。
2. pytest、Ruff、Pyright、Node契约测试和评价API失败。
3. 浏览器验收未通过。
4. 页面缺少可验收的route-card交互架构。
5. 徐汇边界、路线区内比例、道路贴合与路线几何质量不足。
6. 第一轮阶段结束状态与工程质量状态存在差异。

禁止读取第一轮生成源码和成品网页。

阶段2：科研过程

按Harness的Schemas、Prompts和工作流契约完成：

研究目标定义
→ 公开证据采集
→ SourceRegistry
→ 证据卡片
→ 知识缺口
→ 候选假设
→ 假设审查
→ 实验设计
→ 基线设计
→ 评价指标
→ 停止条件

科研结论需要区分原始数据、确定性计算、Qoder判断和人工设置。证据不足时记录inconclusive。禁止虚构来源、DOI、PMID、数据值和实验结果。

阶段3：独立工程生成

在本次run的workspace/source/中从零构建独立版本，至少包含：

1. Qwen-Harness运行副本和复现入口。
2. 徐汇区步行、跑步和骑行路线模块。
3. 环境数据与路线暴露模块。
4. 确定性推荐和评价模块。
5. 完整本地网页产品。
6. 自动化测试和质量检查脚本。
7. 本地启动脚本。
8. 数据来源、许可和复现说明。

网页采用原创设计语言，重点完成：

1. 徐汇区边界与清晰地图首屏。
2. 推荐路线与浏览路线双流程。
3. 运动方式、距离、偏好和环境条件筛选。
4. 用户位置或指定地点输入。
5. 首选路线和两条备选路线。
6. 路线卡片、详情、距离、时长、环境风险和推荐理由。
7. 地图与路线列表双向联动。
8. 选中路线高亮及其余路线弱化。
9. 环境信息与数据可靠度展示。
10. 前往路线起点的接驳导航入口。
11. 加载、空结果、部分数据和错误状态。
12. 桌面端与500×700移动端响应式布局。

阶段4：路线和数据门禁

路线组合达到：

1. 共90条路线。
2. 步行、跑步、骑行各30条。
3. 每种运动三个实际距离档各10条。
4. 每种运动保留14—16条自然strict_loop，其余采用one_way。
5. 覆盖徐汇滨江与西岸、龙华、徐家汇、衡复风貌区、上海植物园、康健园、漕河泾和华泾。
6. ID唯一，无相同、反向相同或高度重合路线。
7. 坐标系声明完整，边界计算前完成统一。
8. 徐汇区内轨迹比例、道路贴合、距离误差、闭环拓扑、重复边、自交、折返和端点偏移达到optimize-xuhui-routes定义的正式门槛。
9. 90条路线最终状态均为accepted，needs_review为0。
10. 54个环境网格与90条路线的ID、单位、时间、状态和缺失值契约一致。
11. 地图上逐条检查路线全景，排除双环、哑铃形、葫芦形、长柄环、局部折返、断头、支叉和跨越不可通行区域。

阶段5：盲测检查点

在访问在线成品前完成：

1. 运行全部单元测试、契约测试和集成测试。
2. 运行Ruff和Pyright。
3. 运行Node测试。
4. 运行评价API本地健康检查。
5. 启动本次run内的本地网页。
6. 完成桌面与500×700移动端浏览器验收。
7. 验证推荐、筛选、详情、地图联动、位置输入、备选路线和错误状态。
8. 保存桌面、移动端及主要交互状态截图。
9. 保存workspace/source全部文件哈希。
10. 生成blind_checkpoint/manifest.json。
11. 生成blind_checkpoint/test_summary.json。
12. 生成blind_checkpoint/screenshots/**。
13. 生成blind_checkpoint/product_matrix.json。

blind_checkpoint写入时间、文件哈希和检查结果后保持冻结。

阶段6：成品交互基准辅助的一次集中修正

blind_checkpoint冻结后，首次访问在线成品页面。

只从可见界面和正常交互整理差距，形成checks/reference_visible_gap_list.json。

采用12项可见产品矩阵：

1. 地图首屏与徐汇区边界。
2. 路线列表和路线卡片。
3. 运动、距离和偏好筛选。
4. 用户需求输入。
5. 推荐主路线与备选路线。
6. 路线详情与环境解释。
7. 地图和列表联动。
8. 路线高亮和视野调整。
9. 地点输入与起点接驳。
10. 桌面信息层级。
11. 移动端布局与操作。
12. 加载、空结果和失败反馈。

目标为至少8项达到同等级可用状态，对应约66.7%的可见功能覆盖。视觉质量采用原创方案，关注信息层级、留白、颜色、字体、交互反馈和地图可读性。

随后执行一次集中修正。所有修正合并为一个correction_batch，禁止重新生成整个工程，也禁止再次读取成品页面。修正期间可持续解决测试暴露的实现缺陷，但不再进行第二次成品对照。

阶段7：最终质量门禁

集中修正后重跑完整验收：

1. pytest全部通过。
2. Ruff无错误。
3. Pyright无错误。
4. Node契约测试全部通过。
5. 评价API本地健康检查通过。
6. generated_quality.json中的required检查全部通过。
7. 浏览器桌面与移动端验收通过。
8. 90条路线空间与组合门禁通过。
9. 54个环境网格契约通过。
10. 12项产品矩阵至少通过8项。
11. 页面无横向溢出、遮挡、空白首屏和失效按钮。
12. 仓库run目录以外无新增或修改文件。
13. 敏感信息、Key、用户绝对路径和虚假request ID检查通过。
14. 本地启动脚本能够打开最终网页。

阶段8：最终交付

在同一run中生成：

1. final_checkpoint/manifest.json
2. final_checkpoint/test_summary.json
3. final_checkpoint/product_matrix.json
4. final_checkpoint/screenshots/**
5. checks/generated_quality.json
6. checks/browser_acceptance.json
7. checks/route_spatial_quality.json
8. checks/environment_contract.json
9. checks/output_boundary.json
10. checks/secret_scan.json
11. publish/local-product/**
12. publish/launch-local.ps1
13. reports/完整运行报告.md
14. reports/科学计划.md
15. reports/实验报告.md
16. reports/复现说明.md
17. reports/第一轮与第二轮对比.md
18. reports/盲测版本与集中修正版对比.md
19. evidence/model_channel.json
20. evidence/user_screenshot_checklist.md

最终状态规则：

- 所有强制门禁通过：passed。
- 已完成集中修正但仍有强制门禁失败：failed_quality_gate。
- 浏览器、空间或模型来源证据缺失：implementation_complete_unverified。
- 禁止把流程结束直接记录为质量通过。

最终汇报只包含：

1. run ID与绝对目录。
2. provider和模型通道。
3. blind_checkpoint结果。
4. 一次集中修正内容。
5. final_checkpoint结果。
6. 第一轮与第二轮的量化差值。
7. 12项产品矩阵通过数。
8. 90条路线空间门禁结果。
9. 全部测试与浏览器结果。
10. 本地网页启动命令与访问地址。
11. 仍未改善的问题。
12. Qoder Credits和百炼调用量的用户截图待办状态。

现在开始执行。阶段之间持续推进，不等待人工确认。除真实权限、Credits耗尽或不可恢复的环境故障外，持续运行到final_checkpoint完成。
```

## 4. 运行后的费用证据

Qoder结束后，重新截取Qoder Credits和百炼模型调用量页面。百炼调用次数保持不变时，配合本次run中的`provider_manifest.json`、命令日志、`evidence/model_channel.json`和`checks/secret_scan.json`，形成第二轮模型通道与费用来源的完整证据链。
