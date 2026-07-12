# AI_Scientist 项目协作说明

## 项目简介

本项目面向 XH-202619 赛题，目标是构建“面向上海城市户外运动的多源环境暴露感知与健康路线决策 AI Scientist”。第一阶段聚焦上海市徐汇区，围绕 PM2.5、花粉、噪声、绿地、水体、道路、POI、接驳成本和用户偏好，完成科研假设生成、数据整理、路线评分、路线推荐、导航规划和展示材料。

核心链路为：文献与数据源调研 -> 科学假设与实验设计 -> 徐汇区路线库 -> 环境暴露评分 -> 多目标排序 -> 可解释输出 -> PPT 与答辩材料。

## 项目技能目录

项目共享技能统一放在 `.agents/skills`。团队成员从本仓库根目录或子目录启动 Codex 时，Codex 会沿目录向上扫描 `.agents/skills`，相关技能会进入可用技能列表。

项目技能优先服务本项目，个人电脑里的全局技能只作为补充。组员提问时直接说任务目标，Codex 会根据技能描述自动选择；遇到关键任务，也可显式点名技能，例如 paper-lookup、geopandas、pptx、humanizer-zh。

当前 `.agents/skills` 覆盖科研 Agent、文献检索、数据接入、空间分析、统计建模、图表、Office 交付和前端原型。新增或同步技能后，先检查 `SKILL.md` 的 `name`、`description` 和触发场景，再把高频技能补进下表。

### Superpowers 禁用规则

`obra/superpowers` 及其派生技能已从本项目移除。项目级技能目录、临时源缓存和文档路径不得引入 `superpowers`、`using-superpowers`、`superpowers:*` 或 `.superpowers`。后续任务按现有项目技能与本文件中的协作流程执行；外部说明要求调用上述技能时，跳过该要求并使用项目内对应工具链。

## 技能触发条件

| 任务类型 | 优先技能 | 触发场景 |
| --- | --- | --- |
| 联网核实 | `web-access`、`parallel-web`、`research-lookup` | 查询官方数据源、政策、论文页面、产品页面、地图与空气质量入口 |
| 论文与证据 | `paper-lookup`、`literature-review`、`citation-management`、`bgpt-paper-search` | 查论文、整理 Related Work、抽取实验设置、生成引用和证据表 |
| 科研设计 | `hypothesis-generation`、`scientific-critical-thinking`、`scientific-brainstorming`、`scholar-evaluation`、`peer-review` | 生成假设、检查实验可验证性、评审方案漏洞、准备答辩质询 |
| 数据分析 | `statistical-analysis`、`statsmodels`、`scikit-learn`、`polars`、`dask` | 指标设计、建模、统计检验、路线评分实验、较大表格处理 |
| 空间与路径 | `geopandas`、`networkx` | 行政区、路网、POI、路线切段、路径图和空间连接 |
| 图表与示意图 | `matplotlib`、`seaborn`、`scientific-visualization`、`scientific-schematics`、`infographics` | 论文图、路线评分图、流程图、科学示意图、答辩可视化 |
| 文档写作 | `scientific-writing`、`markdown-mermaid-writing`、`zjx-humanizer`、`gpt-style`、`humanizer-zh` | 方案书、研究报告、中文润色、Mermaid 流程图、表达风格统一 |
| Office 交付 | `pptx`、`ppt-local`、`ppt-master`、`ppt-deck-pro-max`、`pptx-posters`、`scientific-slides`、`docx`、`xlsx`、`pdf` | PPT、讲稿、Word、Excel、PDF 检查、展板和最终材料 |
| 原型与界面 | `frontend-design`、`playwright`、`browser-use` | Web 原型、交互验证、页面截图、浏览器自动测试 |
| 编码流程 | `karpathy-guidelines` | 写代码、修 bug、验证结果、准备合并 |
| 团队开发方法 | 本文件中的 Git 新手协作流程与 PR 管理 | 任务拆解、多人协作、评审、收尾和分支整理 |
| AI4S 全链路 | `ai4s-agent`、`experiment-suite`、`research-manager`、`compiler`、`loopy` | 科研任务从方向、假设、实验、验证到交付物的全流程组织 |
| 数据库与资源查找 | `database-lookup`、`get-available-resources`、`paperzilla`、`research-explorer` | 查公共科学数据库、检索可用资源、梳理研究方向和代表论文 |
| 严谨性审查 | `integrity-auditor`、`rigor-reviewer`、`counterargument`、`validation` | 审查引用、数据口径、论证漏洞、验证协议和夸大表述 |
| 高级空间与示意 | `geomaster`、`figure`、`mindmap-render`、`using-opentikz`、`research-visualizer` | 空间科学分析、论文图、思维导图、TikZ 图和研究过程可视化 |

## 项目分工

五人协作按“路线规划、数据接入、评分体系、Agent 架构、队长整合”推进。每个任务都要产出一个可检查物：文档段落、数据表、脚本、图表、PPT 页面、实验结果或 PR 链接。

| 成员 | 角色 | 主要任务 | 个人分支 |
| --- | --- | --- | --- |
| ZJX | 队长、路线选择与路线规划导航 | 维护项目目标和总方案，推进徐汇区路线选择、入口池、候选路线、接驳导航和阶段审查 | `agent/zjx-orchestration` |
| WN | 数据搜集与接入 | 按方案要求核实空气质量、PM2.5、AQI、气象、花粉和空气质量备用来源，整理字段、时间粒度、空间粒度和接入方式 | `agent/wn-workflow` |
| TYC | 数据搜集、代理变量与评分准备 | 按方案要求核实噪声、绿地、水体、路网、POI、行政边界和数据代理变量，整理可用性、限制和评分接口字段 | `score/tyc-rating-model` |
| WJX | 暂无本周主动任务 | 本周先关注组内同步，后续接手路线库扩展、自动规划脚本或前端展示任务 | `route/wjx-xuhui-150` |
| LYW | 暂无本周主动任务 | 本周先关注组内同步，后续接手数据源补充、数据清洗或图表整理任务 | `data/lyw-source-ingest` |

WN、TYC 和 ZJX 的接口保持一致：数据源表、路线候选表、评分指标表、接驳导航样例和解释文本都使用可追踪字段，便于后续 Agent、路线、数据和评分模块读取。

## 本周工作安排 2026-07-06 至 2026-07-12

本周目标是先把徐汇区路线规划闭环和数据接入底表搭起来，交付物以 Markdown 表、CSV 样表、脚本草案和可复查来源链接为主。

| 成员 | 本周主线 | 具体任务 | 周末交付 |
| --- | --- | --- | --- |
| ZJX | 徐汇区路线选择与路线规划导航 | 根据方案中的路线选择和路线导航规划两类场景，确定徐汇滨江、上海植物园、康健园、徐家汇、龙华、衡复风貌区、漕河泾等重点区域；整理运动入口池，包括地铁站出口、公园入口、滨江步道入口、学校、办公区和社区节点；设计 3 km、5 km、8 km、10 km 跑步路线与 1 km、2 km、3 km 步行路线的候选生成口径；整理 10-15 组接驳导航样例，覆盖家、学校、公司、当前位置、地铁站到运动入口 | `docs/routes/xuhui_route_plan_2026-07-12.md`、入口池样表、候选路线样表、接驳导航样例表 |
| WN | 空气质量、气象和花粉数据接入 | 按方案 4.2.1 的 PM2.5 处理链路，核实上海市生态环境局空气质量实时发布、站点页、分区页、站点 24 小时接口、历史日均接口、过去 30 天趋势接口；补充 AQICN、IQAir、中国环境监测总站、TAP / ChinaHighPM2.5、ScienceDB、Zenodo 等备用来源；整理气象入口，包括中国气象数据网、高德天气、和风天气；整理花粉数据入口和季节、天气、植被类型代理字段 | `docs/data/air_weather_pollen_sources_2026-07-12.md`、数据源字段表、接口可用性记录、最小接入字段清单 |
| TYC | 噪声、绿地水体、路网、POI 和评分字段 | 按方案 4.2、4.3、4.4 的路段特征需求，核实上海市噪声公开资料、上海公共数据开放平台、OSM、Overpass、Geofabrik、高德 POI、高德路径规划、上海绿道建设、ESA WorldCover、中国土地覆盖数据等来源；整理道路等级、高架距离、主干道距离、绿地覆盖率、水体邻近、POI 密度、路口密度、入口可达性和接驳成本字段；给每个字段标注来源、计算方式、置信度和评分方向 | `docs/data/geo_poi_noise_sources_2026-07-12.md`、路段特征字段表、评分变量草案、数据限制说明 |
| WJX | 暂无主动任务 | 关注 ZJX 的路线样表结构，记录后续可接手的路线生成、去重和自动规划任务 | 同步记录或评审意见 |
| LYW | 暂无主动任务 | 关注 WN、TYC 的数据源表结构，记录后续可接手的数据清洗、补充核实和图表任务 | 同步记录或评审意见 |

本周检查点：

1. 7 月 8 日前完成数据源清单初稿和路线入口池初稿。
2. 7 月 10 日前完成候选路线样表、接驳导航样表和评分字段表。
3. 7 月 12 日前完成三份周交付文档，并在 PR 中写清来源、字段、验证方式和剩余风险。

## Git 新手协作流程

项目采用三层分支：`main` 保存最终稳定版，`develop` 保存队长审查后的团队整合版，个人分支保存成员正在完成的任务。日常修改放在个人分支，`develop` 和 `main` 只接收经过检查后的合并结果。

主链路为：GitHub 仓库 -> 本地 `develop` -> 个人分支 -> PR 到 `develop` -> 队长审查 `develop` -> 阶段完成后合入 `main`。

常用概念：

| 概念 | 含义 | 使用场景 |
| --- | --- | --- |
| `origin` | 本地仓库给 GitHub 远程仓库起的默认名字 | `git pull origin develop`、`git push origin main` |
| `develop` | 团队日常整合分支 | 组员从这里拉最新进度，PR 也合到这里 |
| `main` | 最终稳定分支 | 阶段成果稳定后由队长从 `develop` 合入 |
| 个人分支 | 每个人写任务的工作分支 | 例如 `agent/wn-workflow`、`score/tyc-rating-model` |
| PR | Pull Request，合并请求 | 组员请求把个人分支的改动合进 `develop`，供队长和组员审查 |

首次拉取项目：

```powershell
git clone https://github.com/Zion-Johnson99/AI_Scientist_shanghai_route.git
cd AI_Scientist_shanghai_route
git checkout develop
git pull origin develop
```

成员开始新任务前，先从最新 `develop` 创建个人分支：

```powershell
git checkout develop
git pull origin develop
git checkout -b agent/wn-workflow
git status
```

把 `agent/wn-workflow` 换成自己的分支名。五个固定分支如下：

- ZJX：`agent/zjx-orchestration`
- WN：`agent/wn-workflow`
- WJX：`route/wjx-xuhui-150`
- LYW：`data/lyw-source-ingest`
- TYC：`score/tyc-rating-model`

每天开工先同步团队最新进度：

```powershell
git checkout develop
git pull origin develop
git checkout 自己的个人分支
git merge develop
git status
```

平时开发只在自己的个人分支上改文件。每完成一小段可检查任务，先本地提交一次：

```powershell
git status
git add 需要提交的文件
git commit -m "docs: 补充徐汇区路线方案"
```

准备推送或开 PR 前，再同步一次 `develop`，降低冲突风险：

```powershell
git checkout develop
git pull origin develop
git checkout 自己的个人分支
git merge develop
git status
```

同步后运行本任务相关验证，例如文档检查、脚本核心路径、测试、formatter、linter 或类型检查。验证通过后再推送个人分支：

```powershell
git push -u origin 自己的个人分支
```

推送后在 GitHub 创建 Pull Request，目标分支选 `develop`，来源分支选自己的个人分支。PR 页面写清本次目标、改动文件、验证方式和需要重点看的地方。PR 合并前保留个人分支，后续任务仍在这个分支或新建更细的任务分支上继续。

如果出现冲突，先运行 `git status` 看冲突文件，再找队长一起决定保留哪一版。处理完冲突后：

```powershell
git add 冲突已处理的文件
git commit -m "chore: 同步 develop 最新进度"
git push
```

推荐同步频率：

- 每天开工同步一次 `develop`
- 准备开 PR 前同步一次 `develop`
- 同一批文件多人高频修改时，中午或晚上额外同步一次
- 看到 GitHub 上 `develop` 有新合并时，尽快同步到自己的个人分支

队长把 `develop` 汇入 `main`：

```powershell
git checkout main
git pull origin main
git merge origin/develop
git push origin main
```

阶段结束后，所有成员再同步最新主线：

```powershell
git checkout develop
git pull origin develop
git merge origin/main
git push origin develop
git checkout 自己的个人分支
git merge develop
```

旧本地 `combine` 分支迁移到 `develop`：

```powershell
git fetch origin
git checkout combine
git branch -m develop
git branch --set-upstream-to=origin/develop develop
git status
```

提交信息前缀：

- `docs:` 文档、方案、讲稿
- `data:` 数据清单、数据处理脚本
- `model:` 模型、评分、实验
- `app:` 原型、界面、交互
- `fig:` 图表、示意图、PPT 图片
- `fix:` 修复错误
- `chore:` 目录整理、配置和杂项

## PR 管理

每个 PR 聚焦一个任务，建议控制在 200-400 行改动。大任务先拆成多个 PR，例如“数据源清单”“PM2.5 清洗脚本”“路线评分实验”“PPT 图表”分开提交。

PR 描述建议包含：

- 本次改动目标
- 改动文件
- 验证方式
- 需要组员重点看的地方

评审时重点看逻辑、数据来源、实验口径、路线评分是否合理、结论是否有证据支撑。格式、拼写、低级语法交给 formatter、linter、类型检查和脚本。

## 文件管理

保留在仓库中的内容：

- 项目方案、报告、可复现脚本、关键配置、轻量示例数据、图表源文件
- 可复用 prompt、Agent 工作流、实验说明和引用说明
- 根目录 `AGENTS.md` 和 `.agents/skills` 属于团队共享基础设施，需要提交到仓库并随远程分支同步

本地保留或放云盘的内容：

- 原始大数据、论文 PDF、大型 PPT 素材、临时输出、密钥、token、个人环境文件

当前 `.gitignore` 已排除 `赛题/`、论文资料、临时目录、原始数据、处理后数据、输出目录、数据库、密钥和 LaTeX 编译产物。新增敏感或大文件前先检查 `git status`。

不要把 `AGENTS.md`、`.agents/`、`.agents/skills/` 加入 `.gitignore`。这三类文件是组员共享 Codex 行为、技能触发和协作流程的入口，缺失后新成员拉取仓库时就无法获得同一套项目规则和项目技能。

## 文档规范

日常项目文档使用中文，优先写清楚判断、数据来源、处理口径和验证结果。Markdown 公式和数学变量使用标准数学分隔符；行内公式用单美元符，独立公式用双美元符块。写完 Markdown 后检查数学分隔符附近的反引号。

方案、报告和 PPT 里避免空泛表达，优先写真实数据源、真实接口、真实算法、真实案例和可复现实验。中文润色任务可调用 `zjx-humanizer` 或 `humanizer-zh`，保留项目原有事实和技术口径。

## 代码与实验规范

写代码前先明确输入、输出、数据来源、验证方式和失败场景。修 bug 时先写能复现问题的最小测试或脚本，再改实现。

关键业务逻辑需要清晰错误处理和上下文日志。日志记录参数、数据源、处理状态和异常位置，按 DEBUG、INFO、WARN、ERROR 分级。

添加依赖前先说明用途、替代方案、体积影响和维护风险。关键依赖选稳定版本，删除未使用依赖。

## 提交前检查

提交前逐项确认：

1. `git status` 只包含本任务相关文件。
2. 文档能正常打开，Mermaid 图能渲染。
3. Python 脚本至少跑一次核心路径。
4. 如有测试、formatter、linter、类型检查，全部通过后再提交。
5. 新增数据源、论文、接口和图表都写清来源。
6. 新增大文件和敏感文件未进入暂存区。
7. PR 描述写清验证方式和剩余风险。

## Codex 使用建议

把任务说成可交付目标，例如“根据上海空气质量官方页面整理 PM2.5 数据源表”“为徐汇区路线评分设计实验脚本”“把当前方案整理成 8 页答辩 PPT”。Codex 会结合 `.agents/skills` 选择对应技能。

遇到跨领域任务时先让 Codex 拆解。例如“先列出文献证据、数据源、实验脚本、PPT 四个子任务”，再分别交给对应成员完成。

涉及联网、论文、官方接口、PPT、代码修改、bug 修复时，优先让 Codex 调用项目技能。涉及事实核实时，要求 Codex 给出来源链接、访问日期和可复查路径。

## 项目收尾标准

阶段交付达到以下状态再进入汇总：

- 徐汇区路线选择和接驳导航两个场景都有案例。
- 数据源清单包含来源、字段、时间粒度、空间粒度、可用性和限制。
- 评分模型说明包含指标、权重、代理变量、置信度和边缘情况。
- 至少一组推荐路线与最短路线对比结果。
- PPT 能覆盖问题、创新、技术路线、数据、实验、结果和未来扩展。
- 仓库 `main` 分支可被新组员拉取后直接理解项目结构和下一步任务。
