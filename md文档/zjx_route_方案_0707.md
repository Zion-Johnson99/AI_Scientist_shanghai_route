# ZJX 徐汇区路线选择与导航规划完整方案 2026-07-07

## 0. 核心判断

徐汇路线工作的第一阶段主线建议定为：徐汇区边界确定 -> 运动入口池建立 -> 候选路线生成 -> 网页互动地图 -> 起终点选点 -> 路线规划与接驳导航 -> 可解释展示。第一阶段先用高德地图开放平台解决徐汇边界、POI、地理编码和导航路径，用 Leaflet 或高德 JS API 做可互动网页地图，用静态 GeoJSON 和路线目录支撑演示；评分体系只保留未来接口。

OD = 起点到终点的一组输入。routing engine = 路径规划引擎。matrix = 多起点多终点距离和时间矩阵。route segment = 路线拆分后的路段单元。

本文件服务 ZJX 本周交付：`docs/routes/xuhui_route_plan_2026-07-12.md`、入口池样表、候选路线样表、接驳导航样例表。当前分支：`zjx_route`。

## 1. 本轮调研依据

### 1.1 文献主线

本课题最贴近的文献方向有五类：低污染路线、健康主动出行、绿色与安静路线、跑步路线推荐、多目标路径搜索。直接启发是把路线从“最短距离”扩展为“距离、PM2.5、噪声、绿地、水体、花粉、接驳成本、用户偏好”的综合排序。

| 类别 | 代表文献 | 核心方法 | 对徐汇路线工作的启发 |
| --- | --- | --- | --- |
| 低污染步行导航 | Sharker 等，2012，Health-optimal routing in pedestrian navigation services，DOI: https://doi.org/10.1145/2452516.2452518 | 将空气污染暴露写入步行导航边权 | 建立“健康成本边权”，生成低暴露路线 |
| 最小污染暴露路径 | Sharker 与 Karimi，2013，Computing least air pollution exposure routes，DOI: https://doi.org/10.1080/13658816.2013.841317 | 用 GIS 路网计算最低污染暴露路径 | 作为 PM2.5 单指标基线 |
| 骑行低暴露工具 | Hatzopoulou 等，2013，DOI: https://doi.org/10.1016/j.envres.2013.03.004 | NO2 空间面 + 低暴露替代路线 | 做“最短路线 vs 低暴露路线”的对照展示 |
| 路线选择降低吸入量 | Luo 等，2018，DOI: https://doi.org/10.1016/j.jth.2018.06.008 | 浓度、时长、呼吸率联合估算吸入量 | 跑步和步行可按运动强度修正暴露 |
| 在线健康路线规划 | Zou 等，2020，DOI: https://doi.org/10.1016/j.compenvurbsys.2019.101456 | AOD、LUR、GWR 融合污染面并在线路由 | 站点稀疏时用代理模型补空间分辨率 |
| 主动出行空气污染路线 | Wang 等，2022，DOI: https://doi.org/10.1016/j.trd.2022.103176 | 主动出行路径联合考虑污染暴露 | 步行、骑行、跑步统一为主动出行路线 |
| 路线选择可显著降暴露 | Hertel 等，2008，DOI: https://doi.org/10.1016/j.scitotenv.2007.08.058 | 不同城市街道路线暴露对比 | 路线选择有真实健康收益，可作为答辩论据 |
| 低污染绕行偏好 | Bigazzi 等，2016，DOI: https://doi.org/10.1016/j.jth.2015.12.002 | 距离和污染吸入剂量权衡 | 设置“愿意多走/多跑多少换低暴露”的偏好参数 |
| 健康骑行路线选择 | Wang 等，2018，DOI: https://doi.org/10.1016/j.orhc.2018.04.001 | 时间与污染剂量双目标模型 | 输出 Pareto 候选路线，再压缩成 3 条推荐路线 |
| 清洁路线价值 | Anowar 等，2017，DOI: https://doi.org/10.1016/j.tra.2017.08.017 | 离散选择模型估计低污染绕行接受度 | 建立用户偏好问卷或权重默认值 |
| 空气、噪声、绿地综合暴露 | Willberg 等，2023，DOI: https://doi.org/10.1186/s12942-023-00326-7 | AQI、噪声、绿视率的人群级空间分析 | 支持徐汇多指标暴露评分表 |
| Green Paths 软件 | Helle 等，2023，DOI: https://doi.org/10.5334/jors.400 | OSM 路网 + 空气质量 + 噪声 + 绿视率 + REST API | 本项目最贴近的系统架构参考 |
| 愉悦、安静、美丽路线 | Quercia 等，2014，DOI: https://doi.org/10.1145/2631775.2631799 | 众包街景感知生成 happy、quiet、beautiful 路线 | 推荐解释卡加入安静、景观、愉悦标签 |
| 过敏友好路线 | Temes-Cordovez 等，2016，DOI: https://doi.org/10.1016/j.gaceta.2015.11.003 | 树种、花粉季和过敏风险路径 | 徐汇花粉先用树种、花期、天气做代理风险 |
| 热暴露路径规划 | Rußig 与 Bruns，2017，DOI: https://doi.org/10.1553/giscience2017_01_s327 | 行人路径热压力最小化 | 夏季路线加入时段、阴影、绿荫和滨水降温 |
| 跑步路线推荐 | Knoch 等，2012，DOI: https://doi.org/10.1109/DEXA.2012.49 | 从用户历史学习跑步路线偏好 | 后续加入个人化路线记忆 |
| 跑步路线框架 | Loepp 与 Ziegler，2018，Framework and Demonstrator | 按距离、爬升、经过区域生成跑步路线 | 对应 3 km、5 km、8 km、10 km 跑步路线库 |
| 旅行式跑步推荐 | Shreepriya 等，2021，DOI: https://doi.org/10.1145/3411763.3451707 | 在陌生城市生成 pleasant running tours | 徐汇可做滨江、衡复、植物园 scenic route |
| 可跑区域导航 | Willamowski 等，2022，DOI: https://doi.org/10.1145/3491102.3502051 | connected runnable zones | 公园、滨江、衡复街区适合做自由跑步区域 |
| 感官跑步路线 | Hänsel 等，2025，DOI: https://doi.org/10.1016/j.ijhcs.2025.103512 | 感官地图与 scenic/urban 路线引擎 | 将用户分为景观型、安静型、探索型 |
| 多目标 A* | Mandow 与 Pérez de la Cruz，2010，DOI: https://doi.org/10.1145/1754399.1754400 | NAMOA* 求 Pareto 路径集合 | 后续升级多目标最短路 |
| 安全路径多目标 | Galbrun 等，2016，DOI: https://doi.org/10.1016/j.is.2015.10.005 | 距离和风险双目标路径 | 替换风险指标为 PM2.5、噪声、花粉、热暴露 |
| 用户偏好路径 | Kreller 与 Ludwig，2021，DOI: https://doi.org/10.4230/LIPIcs.GIScience.2021.II.11 | 比较用户偏好路径和最短路径 | 用用户反馈校准权重 |

### 1.2 项目和平台主线

| 项目或平台 | URL | 可借鉴点 | 使用建议 |
| --- | --- | --- | --- |
| GreenPaths 在线产品 | https://green-paths.web.app/?map=streets&od=t | OD 输入、地图图层、路线对比、解释面板 | 当前线上后端访问有波动，重点学习交互结构 |
| DigitalGeographyLab Green Paths | https://github.com/DigitalGeographyLab/green-paths | OSM、AQI、噪声、绿视率、Python 服务、React + Mapbox GL JS | 作为系统架构首要参考 |
| Mapbox Directions API | https://docs.mapbox.com/api/navigation/directions/ | walking、cycling、driving、alternatives、geometry | 展示原型可参考，国内落地优先高德 |
| 高德地图开放平台 | https://lbs.amap.com/api/webservice/summary | 行政区、POI、地理编码、路径规划、距离测量 | 本项目国内数据首选入口 |
| OSRM | https://github.com/Project-OSRM/osrm-backend | 高性能最短路、table、match、trip | 做最短路和最快路 baseline |
| GraphHopper | https://github.com/graphhopper/graphhopper | OSM routing、custom models、步行和骑行 profiles | 后期自建服务首选 |
| OpenRouteService | https://github.com/GIScience/openrouteservice | Directions、Matrix、Isochrones、POI | 早期验证候选路线与等时圈 |
| Valhalla | https://github.com/valhalla/valhalla | 多模式 routing、matrix、isochrone、costing | 后期复杂多模式导航候选 |
| OpenTripPlanner | https://github.com/opentripplanner/OpenTripPlanner | OSM + GTFS 多模式出行 | 处理地铁、公交到运动入口 |
| pgRouting | https://github.com/pgRouting/pgrouting | PostGIS 图算法、Dijkstra、A* | 存路段表、暴露字段、可解释查询 |
| OSMnx | https://github.com/gboeing/osmnx | 下载、建模、分析 OSM 街道网络 | 第一阶段科研脚本底座 |
| NetworkX | https://github.com/networkx/networkx | Python 图算法 | 候选路径搜索和指标实验 |
| MapLibre GL JS | https://github.com/maplibre/maplibre-gl-js | 开源矢量地图前端 | 正式前端地图底座 |
| Leaflet | https://github.com/Leaflet/Leaflet | 轻量地图和 polyline 展示 | 简单演示页面可用 |
| Turf.js | https://github.com/Turfjs/turf | 前端空间计算 | 前端测距、缓冲区、相交检查 |
| 百度地图开放平台 | https://lbsyun.baidu.com/ | 中文 POI、地理编码、路线规划 | 作为高德交叉核验源 |
| 腾讯位置服务 | https://lbs.qq.com/ | 地点搜索、路线、距离矩阵 | 作为 POI 与 matrix 备用源 |

本轮本地保存的证据文件在 `sources/`：`zjx_route_core_papers_crossref_20260707.json`、`zjx_route_github_search_20260707.json`、`zjx_route_known_repos_20260707.json`、`green_paths_github_repo_20260707.json`、`green_paths_cdp_dom_20260707.json` 等。

## 2. 徐汇区范围确定

### 2.1 边界基准

工程边界以高德行政区域查询接口返回的徐汇区多边形为第一版基准：

```text
https://restapi.amap.com/v3/config/district?keywords=徐汇区&subdistrict=0&extensions=all&key=AMAP_KEY
```

关键字段：

| 字段 | 含义 | 用途 |
| --- | --- | --- |
| `district_name` | 行政区名称 | 固定为徐汇区 |
| `adcode` | 行政区编码 | 数据源连接键 |
| `citycode` | 城市编码 | 上海市筛选 |
| `level` | 行政层级 | 区级边界确认 |
| `center_lng`、`center_lat` | 区域中心点 | 地图初始化 |
| `boundary_polyline_gcj02` | 高德返回边界线 | 区内过滤和可视化 |
| `boundary_geojson_wgs84` | 转换后的 GeoJSON | 与 OSM、GeoPandas 叠加 |
| `source_api` | 数据来源 | 溯源 |
| `fetched_at` | 拉取时间 | 版本管理 |

输出文件建议：

```text
data/boundary/xuhui_boundary_amap_raw.json
data/boundary/xuhui_boundary_amap_gcj02.geojson
data/boundary/xuhui_boundary_wgs84.geojson
```

### 2.2 坐标系统一

高德返回 GCJ-02，OSM 常用 WGS84。数据表中保留两套坐标字段：`lng_gcj02`、`lat_gcj02` 用于高德请求和国内地图展示；`lng_wgs84`、`lat_wgs84` 用于 OSMnx、GeoPandas、NetworkX 和公开地理数据叠加。每次转换记录 `coord_source` 和 `coord_transform_method`。

### 2.3 区域分层

徐汇路线库先按 7 类区域分层，便于覆盖不同户外运动场景：

| 区域 | 路线定位 | 入口重点 |
| --- | --- | --- |
| 徐汇滨江 | 线性滨水跑步、骑行、步行 | 滨江步道入口、龙华中路、东安路、龙耀路 |
| 上海植物园 | 绿地、花粉、季节性路线 | 公园门、地铁站、周边公交 |
| 康健园 | 社区慢走和短跑 | 社区节点、公园入口 |
| 徐家汇 | 城市核心区便捷路线 | 地铁站、办公楼、商圈 |
| 龙华 | 历史街区和滨江连接 | 地铁站、寺庙周边、滨江入口 |
| 衡复风貌区 | 风貌街区、安静路线 | 武康路、衡山路、复兴西路周边入口 |
| 漕河泾 | 办公区接驳和午休路线 | 园区门、地铁站、办公楼 |

## 3. 运动入口池构建

入口池 = 用户开始运动或进入运动空间的候选点。入口池质量决定后续路线质量，第一版建议覆盖 80-150 个入口点。

### 3.1 高德 API 入口

| 任务 | API | 建议参数 |
| --- | --- | --- |
| 地址转坐标 | `https://restapi.amap.com/v3/geocode/geo` | `address`、`city=上海` |
| 坐标转地址 | `https://restapi.amap.com/v3/geocode/regeo` | `location`、`extensions=all` |
| 行政区边界 | `https://restapi.amap.com/v3/config/district` | `keywords=徐汇区`、`extensions=all` |
| 关键字 POI | `https://restapi.amap.com/v5/place/text` | `keywords`、`region=上海`、`show_fields=navi,business` |
| 多边形内 POI | `https://restapi.amap.com/v5/place/polygon` | `polygon`、`types`、`show_fields=navi,business` |
| 周边 POI | `https://restapi.amap.com/v5/place/around` | `location`、`radius`、`types` |

### 3.2 入口类型

| `entry_type` | 来源 | 筛选口径 |
| --- | --- | --- |
| `metro_exit` | 高德 POI、地铁站出口 | 优先 `entr_location` |
| `park_gate` | 公园、绿地、植物园 | 取公园门和真实可达入口 |
| `riverside_access` | 滨江步道、桥下通道、亲水平台 | 人行可达点 |
| `campus_gate` | 学校门、校区入口 | 周边步行接驳 |
| `office_cluster` | 办公园区、商务楼 | 午休跑步和下班接驳 |
| `community_node` | 小区、社区中心 | 家门口步行路线 |
| `sports_facility` | 体育场、健身步道、运动场 | 运动目的地 |
| `scenic_node` | 风貌建筑、景观节点 | 衡复、龙华、滨江路线解释 |

### 3.3 入口池样表

```text
data/routes/xuhui_entry_pool.csv
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entry_id` | string | 唯一编号，如 `XH_ENT_0001` |
| `entry_name` | string | 入口名称 |
| `entry_type` | string | 入口类型 |
| `region_zone` | string | 徐汇滨江、植物园、衡复等 |
| `poi_id` | string | 高德 POI ID |
| `lng_gcj02`、`lat_gcj02` | float | 高德坐标 |
| `lng_wgs84`、`lat_wgs84` | float | OSM 和公开数据坐标 |
| `address` | string | 地址 |
| `parent_poi` | string | 所属公园、商圈、园区 |
| `navi_poiid` | string | 高德导航 POI |
| `entr_location` | string | 高德入口坐标 |
| `nearest_metro` | string | 最近地铁站 |
| `confidence` | int | 1-5，入口可信度 |
| `source_api` | string | 高德、人工核验、OSM 等 |
| `verified_at` | date | 核验日期 |

## 4. 候选路线生成

候选路线生成采用“入口点 -> 目标里程 -> 候选终点 -> 路径规划 -> 距离筛选 -> 网页展示”的流程。第一版先生成可在地图上打开和切换的路线库，再做算法自动化。

### 4.1 路线类型

| 类型 | 目标距离 | 场景 |
| --- | --- | --- |
| 步行短线 | 1 km | 饭后散步、地铁到公园 |
| 步行中线 | 2 km | 公园慢走、社区绕行 |
| 步行长线 | 3 km | 风貌区漫步、滨江步道 |
| 跑步入门 | 3 km | 初学者、午休短跑 |
| 跑步标准 | 5 km | 日常跑步 |
| 跑步进阶 | 8 km | 滨江、植物园、街区组合 |
| 跑步长线 | 10 km | 周末训练、滨江往返 |

### 4.2 三种生成方法

方法 A：高德路径规划快速生成。

1. 从入口池选 `start_entry_id`。
2. 按目标距离在 8-16 个方向生成候选终点，终点距离约为目标里程的一半或三分之一。
3. 调用高德步行或骑行路径规划。
4. 用返回的 `distance` 筛选误差 15% 以内的路线。
5. 保存 `steps`、`polyline`、`road_name`、`instruction`。

方法 B：OSMnx + NetworkX 本地生成。

1. 用徐汇边界下载 walking 路网。
2. 将道路边赋值为距离、道路等级、绿地邻近、水体邻近、主干道惩罚。
3. 使用 k-shortest paths 或多组扰动权重生成候选。
4. 对每条候选路线计算距离误差、转向次数、道路多样性和环境得分。

方法 C：区域模板生成。

| 模板 | 适用区域 | 形态 |
| --- | --- | --- |
| 闭环 | 植物园、康健园、衡复风貌区 | 起点终点接近 |
| 线性往返 | 徐汇滨江 | 沿滨江来回 |
| 片区串联 | 徐家汇、龙华、衡复 | 串联多个景观或地铁节点 |
| 接驳到运动入口 | 漕河泾、学校、社区 | 起点为家、公司、学校 |

### 4.3 路线样表

```text
data/routes/xuhui_candidate_routes.csv
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `route_id` | string | `XH_RUN_5K_0001` |
| `route_name` | string | 路线名称 |
| `route_mode` | string | walk、run、bike_assist |
| `target_distance_m` | int | 目标距离 |
| `actual_distance_m` | int | 实际距离 |
| `distance_error_m` | int | 距离偏差 |
| `start_entry_id` | string | 起点入口 |
| `end_entry_id` | string | 终点入口 |
| `loop_flag` | bool | 闭环标记 |
| `region_zone` | string | 所属区域 |
| `duration_s` | int | 预计时长 |
| `polyline_gcj02` | string | 高德 polyline |
| `polyline_wgs84` | string | 转换后 polyline |
| `road_names` | string | 道路名列表 |
| `turn_count` | int | 转向次数 |
| `route_inside_ratio` | float | 路线落在徐汇区内比例 |
| `source_method` | string | amap、osmnx、manual_template |
| `generated_at` | datetime | 生成时间 |

### 4.4 距离筛选规则

| 规则 | 建议阈值 | 说明 |
| --- | --- | --- |
| 距离误差 | 目标里程 15% 以内 | 跑步路线对距离更敏感 |
| 区内比例 | 大于 0.80 | 滨江边界附近可保留少量跨界 |
| 起终点距离 | 闭环小于 300 m | 适合日常跑步 |
| 转向次数 | 同距离候选中较低优先 | 降低导航负担 |
| 主干道贴边 | 长距离贴边降权 | 减少噪声和尾气 |
| 高架附近 | 近距离长段降权 | 噪声和颗粒物风险 |

## 5. 导航规划

导航规划分成两层：运动路线本身、用户到运动入口的接驳路线。

### 5.1 运动路线导航

高德路径规划 2.0 可用于步行、骑行、驾车路径。第一版跑步路线建议使用步行路径规划为主，滨江和绿道连续路线可用骑行路径补充，结果再由人工抽查。

常用接口：

```text
https://restapi.amap.com/v5/direction/walking
https://restapi.amap.com/v5/direction/bicycling
https://restapi.amap.com/v5/direction/driving
https://restapi.amap.com/v3/direction/transit/integrated
```

请求字段：

| 字段 | 说明 |
| --- | --- |
| `origin` | 起点坐标，格式 `lng,lat` |
| `destination` | 终点坐标，格式 `lng,lat` |
| `show_fields` | 需要返回的扩展字段 |
| `strategy` | 路径策略，按接口文档选择 |
| `city1`、`city2` | 公交路径城市参数 |

返回字段保留：

| 字段 | 说明 |
| --- | --- |
| `distance` | 路径距离 |
| `duration` | 预计时长 |
| `steps` | 分段导航 |
| `instruction` | 转向提示 |
| `road_name` | 道路名称 |
| `step_distance` | 分段距离 |
| `polyline` | 分段坐标 |

### 5.2 接驳导航

接驳导航覆盖 10-15 组样例，来源包括家、学校、公司、当前位置、地铁站到运动入口。

| 距离或场景 | 推荐方式 | API |
| --- | --- | --- |
| 1.5 km 内 | 步行 | 高德 walking |
| 1.5-5 km | 骑行或电动车 | 高德 bicycling |
| 地铁到入口 | 步行 + 公交/地铁 | 高德 transit |
| 跨区或携带装备 | 驾车 | 高德 driving |
| 多起点到多入口筛选 | 距离矩阵 | 高德距离测量或腾讯/百度 matrix |

样表：

```text
data/routes/xuhui_access_navigation_examples.csv
```

| 字段 | 说明 |
| --- | --- |
| `case_id` | 样例编号 |
| `user_origin_type` | home、school、office、current_location、metro |
| `origin_name` | 起点名称 |
| `origin_lng_gcj02`、`origin_lat_gcj02` | 起点高德坐标 |
| `target_entry_id` | 目标运动入口 |
| `access_mode` | walk、bike、transit、drive |
| `access_distance_m` | 接驳距离 |
| `access_duration_s` | 接驳时间 |
| `transfer_count` | 换乘次数 |
| `parking_or_station_hint` | 停车、地铁口或公交站提示 |
| `navigation_api` | 使用接口 |
| `risk_note` | 风险说明 |

### 5.3 给用户的三类路线

每次推荐固定输出 3 条，避免 Pareto 路线过多造成选择负担。

| 路线 | 优先目标 | 展示话术 |
| --- | --- | --- |
| 低暴露路线 | PM2.5、噪声、花粉和热风险较低 | “多用绿地和支路，主干道暴露较少” |
| 均衡路线 | 距离、环境、接驳、连续性均衡 | “距离接近目标，环境和便捷性平衡” |
| 便捷路线 | 接驳短、入口明确、转向少 | “最容易到达和跟随，适合临时出发” |

## 6. 第一阶段网页版地图原型

第一阶段产物应收敛到一个可打开、可互动、能选点和看路线的徐汇地图网页。地图网页承担展示和演示，后端脚本承担高德 API 调用、边界和路线数据整理。

### 6.1 网页核心功能

| 功能 | 第一阶段要求 | 交互结果 |
| --- | --- | --- |
| 徐汇区底图 | 显示徐汇区边界、重点区域和底图 | 用户一眼看到研究范围 |
| 入口点图层 | 显示地铁、公园、滨江、学校、办公区、社区入口 | 点击点位弹出名称、类型、地址 |
| 路线图层 | 显示 1/2/3 km 步行和 3/5/8/10 km 跑步路线 | 按路线类型开关显示 |
| 起终点选择 | 支持点击地图点位或选择入口点 | 地图上出现起点、终点 marker |
| 路线规划 | 调用高德步行、骑行、驾车或本地样例路线 | 地图绘制 polyline，并显示距离和时长 |
| 多路线选择 | 同一 OD 给出推荐路线、便捷路线、候选路线 | 用户切换路线查看差异 |
| 接驳导航 | 从家、学校、公司、当前位置、地铁站到运动入口 | 展示接驳路径和预计时间 |
| 路线详情面板 | 显示距离、预计时间、起点、终点、经过区域 | 方便截图和答辩演示 |

### 6.2 推荐页面布局

```text
左侧控制面板
  搜索/选择起点
  搜索/选择终点
  路线类型：步行、跑步、接驳
  距离档：1 km、2 km、3 km、5 km、8 km、10 km
  路线列表：推荐、便捷、候选

右侧地图
  徐汇区边界
  入口点 marker
  候选路线 polyline
  当前选中路线高亮
  弹窗和路线详情
```

### 6.3 前端技术选择

第一阶段建议用 Leaflet 起步，原因是接入快、文件轻、GeoJSON 展示直接，适合课程和比赛快速出图。后续需要矢量瓦片、复杂样式和更强交互时，再升级到 MapLibre GL JS。

| 技术 | 用途 | 当前建议 |
| --- | --- | --- |
| Leaflet | 互动地图、marker、polyline、popup | 第一阶段优先 |
| MapLibre GL JS | 矢量地图、复杂图层、热力图 | 第二阶段升级 |
| Turf.js | 前端测距、边界相交、缓冲区 | 按需引入 |
| 高德 JS API | 国内底图、搜索、定位、路线展示 | 有 Key 时可作为国产底图方案 |
| 静态 GeoJSON | 边界、入口、路线展示 | 第一阶段主数据格式 |

### 6.4 路线选择策略

第一阶段先展示路线规划能力，路线排序保持简单：

| 路线类别 | 生成口径 | 页面展示 |
| --- | --- | --- |
| 推荐路线 | 人工筛选或样表中 `is_recommended=true` | 默认高亮 |
| 便捷路线 | 接驳时间短、入口清楚、转向少 | 作为备选 |
| 候选路线 | 同一区域同距离档的其他路线 | 列表中展开 |

评分体系保留入口：路线数据中预留 `future_score`、`score_note`、`feature_tags` 字段，当前页面只展示标签和说明，后续再接 PM2.5、噪声、绿地、水体、花粉等指标。

## 7. 简化后的代码结构

### 7.1 第一阶段最小目录

```text
web/
  index.html
  src/
    main.js
    map.js
    route-ui.js
    amap-api.js
    data-loader.js
  styles/
    main.css
  data/
    xuhui_boundary.geojson
    xuhui_entries.geojson
    xuhui_routes.geojson
    route_catalog.json
scripts/
  fetch_amap_boundary.py
  build_entry_pool.py
  build_route_samples.py
  export_web_geojson.py
data/
  raw/
  boundary/
  routes/
docs/
  routes/
tests/
  test_web_data_schema.py
  test_route_catalog.py
```

### 7.2 模块职责

| 文件 | 职责 |
| --- | --- |
| `web/index.html` | 网页入口 |
| `web/src/main.js` | 初始化页面和全局状态 |
| `web/src/map.js` | 初始化地图、图层、marker、polyline |
| `web/src/route-ui.js` | 起终点选择、路线列表、详情面板 |
| `web/src/amap-api.js` | 调用高德路线规划接口 |
| `web/src/data-loader.js` | 加载本地 GeoJSON 和路线目录 |
| `web/styles/main.css` | 页面布局和样式 |
| `scripts/fetch_amap_boundary.py` | 获取徐汇区边界 |
| `scripts/build_entry_pool.py` | 生成入口点样表 |
| `scripts/build_route_samples.py` | 生成候选路线样例 |
| `scripts/export_web_geojson.py` | 导出网页可读数据 |

### 7.3 预留目录

```text
data/features/
```

`data/features/` 只作为未来评分体系入口，第一阶段放一个 `README.md` 说明字段计划即可。当前代码先聚焦地图、点位、路线和导航。

### 7.4 依赖控制

| 位置 | 依赖 | 用途 |
| --- | --- | --- |
| 前端 | Leaflet | 地图展示 |
| 前端 | 原生 JavaScript | 页面交互 |
| Python 脚本 | requests | 调用高德 API |
| Python 脚本 | pandas | 读写 CSV |
| Python 脚本 | geopandas、shapely | GeoJSON 和空间过滤 |
| 测试 | pytest | 检查数据 schema |

当前阶段先不引入后端框架、数据库、GraphHopper、pgRouting、复杂评分模块。等网页原型跑通后，再决定是否服务化。

## 8. 输出交付物

### 8.1 网页原型

```text
web/index.html
web/src/main.js
web/src/map.js
web/src/route-ui.js
web/src/amap-api.js
web/src/data-loader.js
web/styles/main.css
```

验收方式：本地打开或启动静态服务器后，能看到徐汇区边界、入口点、路线 polyline，并能通过面板选择起点终点和路线。

### 8.2 网页数据

```text
web/data/xuhui_boundary.geojson
web/data/xuhui_entries.geojson
web/data/xuhui_routes.geojson
web/data/route_catalog.json
```

`route_catalog.json` 建议字段：

| 字段 | 说明 |
| --- | --- |
| `route_id` | 路线编号 |
| `route_name` | 页面显示名称 |
| `route_mode` | walk、run、access |
| `distance_level` | 1km、2km、3km、5km、8km、10km |
| `start_entry_id` | 起点入口 |
| `end_entry_id` | 终点入口 |
| `distance_m` | 距离 |
| `duration_min` | 预计时间 |
| `tags` | 滨江、绿地、风貌、便捷等 |
| `future_score` | 未来评分占位 |
| `score_note` | 未来评分说明 |

### 8.3 本周文档和样表

```text
docs/routes/xuhui_route_plan_2026-07-12.md
data/routes/xuhui_entry_pool.csv
data/routes/xuhui_candidate_routes.csv
data/routes/xuhui_access_navigation_examples.csv
```

## 9. 执行计划

### 9.1 第一步：地图骨架

| 任务 | 输出 |
| --- | --- |
| 建立 `web/` 静态页面 | `web/index.html` |
| 接入 Leaflet 或高德 JS API | 地图能显示 |
| 加载徐汇边界 GeoJSON | 地图显示研究范围 |
| 加载入口点 GeoJSON | 地图显示可点击点位 |

### 9.2 第二步：路线样例

| 任务 | 输出 |
| --- | --- |
| 生成 7 个重点区域的样例路线 | `web/data/xuhui_routes.geojson` |
| 建立路线目录 | `web/data/route_catalog.json` |
| 页面路线列表 | 左侧面板可切换路线 |
| 当前路线高亮 | 地图 polyline 高亮 |

### 9.3 第三步：选点导航

| 任务 | 输出 |
| --- | --- |
| 起点和终点选择 | 地图 marker 和面板同步 |
| 调用高德步行路径 | 页面展示距离、时长和 polyline |
| 接驳样例展示 | 地铁站、学校、公司到运动入口 |
| 导出截图和演示材料 | 答辩图和网页录屏素材 |

### 9.4 第四步：评分入口

| 任务 | 输出 |
| --- | --- |
| 在路线数据中预留 `future_score` | 当前值留空或 `null` |
| 在页面详情面板预留“后续评分”位置 | 当前展示标签 |
| 建立 `data/features/README.md` | 说明后续 PM2.5、噪声、绿地、花粉字段 |

## 10. 验证方案

### 10.1 接口验证

| 用例 | 输入 | 检查点 |
| --- | --- | --- |
| 徐汇区边界 | `keywords=徐汇区` | `status=1`、`infocode=10000`、`polyline` 非空 |
| POI 搜索 | `types=地铁站/公园/体育场馆` | 返回数量、坐标字段、入口字段 |
| 步行路径 | 徐家汇站到衡山路入口 | `distance`、`duration`、`steps`、`polyline` 非空 |
| 骑行路径 | 龙耀路到徐汇滨江入口 | 路线连续、距离合理 |
| 驾车接驳 | 漕河泾办公点到滨江入口 | 驾车时长和距离合理 |

### 10.2 空间验证

| 用例 | 检查点 |
| --- | --- |
| 入口点在徐汇区内 | `within(xuhui_boundary)` |
| 路线区内比例 | `route_inside_ratio > 0.80` |
| 距离误差 | 目标里程 15% 以内 |
| 起终点闭环 | 闭环路线起终点距离小于 300 m |
| 坐标系一致 | 高德请求用 GCJ-02，OSM 分析用 WGS84 |

### 10.3 业务验证

| 区域 | 至少保留 |
| --- | --- |
| 徐汇滨江 | 1 条 5 km 或 8 km 线性往返路线 |
| 上海植物园 | 1 条 3 km 步行和 1 条 5 km 跑步路线 |
| 康健园 | 1 条社区慢走路线 |
| 徐家汇 | 1 条便捷接驳路线 |
| 龙华 | 1 条历史街区 + 滨江连接路线 |
| 衡复风貌区 | 1 条 scenic 步行路线 |
| 漕河泾 | 1 条办公区午休路线 |

## 11. 边缘情况

| 情况 | 处理 |
| --- | --- |
| 高德 API 返回空结果 | 降低 POI 类型粒度，改用关键词或周边搜索 |
| POI 中心点偏到建筑内部 | 优先使用 `entr_location` 或人工入口点 |
| 路线穿出徐汇区 | 记录区内比例，低于阈值的路线降权或剔除 |
| 实际距离偏离目标 | 扩大候选终点方向和半径后重算 |
| 同名 POI 混淆 | 用 `adcode`、地址、父 POI 和坐标范围过滤 |
| `road_name` 为空 | 保留 step instruction 和 polyline，后续用逆地理编码补充 |
| `polyline` 缺失 | 标记接口异常，进入重试或人工核验 |
| API 限额触发 | 缓存原始响应，分批请求，日志记录请求参数 |
| 坐标系错位 | 用徐家汇、龙华、植物园等控制点做地图叠加检查 |
| 花粉缺少实时数据 | 先用树种、花期、风雨湿度做代理风险 |
| 噪声缺少精细图层 | 用主干道、高架、轨交和道路等级做代理 |
| 夏季热暴露偏高 | 午后时段增强热风险权重，绿荫和滨水加分 |

## 12. 测试用例

| 测试文件 | 测试目标 |
| --- | --- |
| `tests/test_boundary_parse.py` | 高德边界 polyline 能解析为有效多边形 |
| `tests/test_coordinate_fields.py` | GCJ-02 和 WGS84 字段同时存在 |
| `tests/test_entry_pool_schema.py` | 入口池字段完整，入口类型在枚举内 |
| `tests/test_route_distance_filter.py` | 目标距离筛选规则稳定 |
| `tests/test_access_navigation_schema.py` | 接驳样例字段完整 |
| `tests/test_route_score_order.py` | 低暴露路线在污染权重提高后排序上升 |
| `tests/test_explanation_text.py` | 每条路线都有距离、暴露、舒适和风险解释 |

## 13. 推荐的第一批样例路线

| 路线 | 起点 | 终点 | 距离档 | 推荐类型 |
| --- | --- | --- | --- | --- |
| 徐汇滨江 5K 往返 | 龙耀路地铁站 | 滨江步道返回点 | 5 km | 低暴露、景观 |
| 徐汇滨江 8K 线性 | 东安路周边入口 | 龙华滨江入口 | 8 km | 长跑、滨水 |
| 上海植物园 3K 慢走 | 石龙路周边入口 | 植物园入口闭环 | 3 km | 绿地、花粉提示 |
| 衡复风貌 2K 步行 | 衡山路站 | 武康路周边 | 2 km | scenic、安静 |
| 徐家汇 1K 接驳 | 徐家汇站 | 公园或风貌入口 | 1 km | 便捷 |
| 漕河泾午休 3K | 漕河泾办公区 | 周边绿地闭环 | 3 km | 午休短跑 |
| 龙华 5K 组合 | 龙华站 | 滨江连接点 | 5 km | 历史街区 + 滨江 |

## 14. PR 和交付建议

本任务建议拆成 3 个小 PR：

| PR | 改动范围 | 行数目标 |
| --- | --- | --- |
| PR 1 | 边界、入口池和数据源文档 | 200-400 行 |
| PR 2 | 候选路线样表和接驳导航样例 | 200-400 行 |
| PR 3 | 网页地图、路线切换和预留评分入口 | 200-400 行 |

提交前检查：

1. `git status` 仅包含本任务相关文件。
2. Markdown 公式附近无反引号。
3. CSV 表头和字段说明一致。
4. API 原始响应保存在 `sources/` 或 `data/raw/`。
5. 新增样例路线能在地图上打开。
6. 新增来源有 URL、访问日期和字段口径。

## 15. 参考链接

- 高德地图开放平台 Web 服务 API：https://lbs.amap.com/api/webservice/summary，访问日期：2026-07-07。
- 高德行政区域查询：https://lbs.amap.com/api/webservice/guide/api/district，访问日期：2026-07-07。
- 高德搜索 POI 2.0：https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch，访问日期：2026-07-07。
- 高德路径规划：https://lbs.amap.com/api/webservice/guide/api/newroute，访问日期：2026-07-07。
- 高德地理编码：https://lbs.amap.com/api/webservice/guide/api/georegeo，访问日期：2026-07-07。
- Green Paths 在线产品：https://green-paths.web.app/?map=streets&od=t，访问日期：2026-07-07。
- Green Paths GitHub：https://github.com/DigitalGeographyLab/green-paths，访问日期：2026-07-07。
- Mapbox Directions API：https://docs.mapbox.com/api/navigation/directions/，访问日期：2026-07-07。
- OSRM：https://github.com/Project-OSRM/osrm-backend，访问日期：2026-07-07。
- GraphHopper：https://github.com/graphhopper/graphhopper，访问日期：2026-07-07。
- OpenRouteService：https://github.com/GIScience/openrouteservice，访问日期：2026-07-07。
- Valhalla：https://github.com/valhalla/valhalla，访问日期：2026-07-07。
- OpenTripPlanner：https://github.com/opentripplanner/OpenTripPlanner，访问日期：2026-07-07。
- pgRouting：https://github.com/pgRouting/pgrouting，访问日期：2026-07-07。
- OSMnx：https://github.com/gboeing/osmnx，访问日期：2026-07-07。
- NetworkX：https://github.com/networkx/networkx，访问日期：2026-07-07。
- MapLibre GL JS：https://github.com/maplibre/maplibre-gl-js，访问日期：2026-07-07。
