# 路线依据与 POI 规则

## 1. 证据层级

| 等级 | 来源 | 用途 |
| --- | --- | --- |
| A | 政府、公园、体育场馆和路线运营方官方页面 | 确认路线主题、开放语义、入口和官方母线 |
| B | 高德当前道路、POI、路径响应和 OSM 可通行路网 | 确认坐标、道路生成、服务设施和网络贴合 |
| C | Komoot 等社区实走或实骑记录 | 发现连续道路骨架和风险线索 |

官方母线提供空间语义。进入正式路线前，仍需当前道路生成、边界、通行限制和视觉复核。社区轨迹只承担线索角色。

## 2. 优先路线依据

- [徐汇发布 7 条红色文化主题行走路线](https://whlyj.sh.gov.cn/gqfc/20241021/eec3bb2c96504b059712ec348032212a.html)
- [衡复音乐街区春日打卡清单](https://whlyj.sh.gov.cn/gqfc/20260417/60c0fdc9b9f8481ab6be378451285604.html)
- [徐家汇历史与体育 Citywalk](https://www.xuhui.gov.cn/xwzx_zwxx/20241115/547298.html)
- [上海西岸滨水体育空间](https://tyj.sh.gov.cn/gqfc/20210930/19e8d84a536a4a728d8598cba0179898.html)
- [徐汇滨江长跑节赛道](https://www.shanghai.gov.cn/nw15343/20251229/3f98aa90344d45f88f046371f74c92c3.html)
- [骑行浦江，寻踪徐汇艺文智岸](https://whlyj.sh.gov.cn/gqfc/20250521/6cd8a6e351814965b9b5f1cd515994d6.html)
- [上海植物园语音导览](https://www.shbg.org/sites/zhiwuyuan/InfoContent.aspx?ctgId=3c25f682-3f21-4cb3-994b-ab79489bacae&infoId=bc3ac58b-5775-4cb6-a921-53f179926c2b)

访问在线来源时记录访问日期。来源发生变化或开放信息过期时重新核实。

## 3. 社区骑行依据

- [交通大学出发龙腾大道环线](https://www.komoot.com/smarttour/21800865)
- [徐家汇出发龙腾大道变体](https://www.komoot.com/smarttour/33993515)
- [中山公园出发龙腾大道变体](https://www.komoot.com/smarttour/33978468)
- [上海城市骑行合集](https://www.komoot.com/collection/2180778/downtown-riding-and-day-tripping-shanghai-s-cycling-essentials)

提取连续道路骨架、常用接入方向、路面信息和禁骑提示。过滤跨区段、轮渡、临时限制和未经复核的坐标。

## 4. POI 类型与覆盖

支持以下服务类型：

- `coffee`
- `convenience`
- `toilet`
- `drinking_water`
- `sport_station`
- `bike_service`

每条路线执行沿线匹配。每种运动类型至少 18 条路线关联一个经核实服务 POI，并覆盖咖啡店、便利店和公共厕所中的至少两类。5 公里以上跑步线与 10 公里以上骑行线优先匹配厕所或便利店。

## 5. POI 空间规则

- 步行和跑步使用轨迹两侧 100 米走廊。
- 骑行使用轨迹两侧 200 米走廊。
- POI 作为“沿线”或“附近”服务展示，不进入高德导航节点。
- 相邻路线复用同一 POI，通过 `related_route_ids` 建立关联。
- POI 缺失时保留路线主骨架，记录覆盖缺口。

## 6. 真实性字段

正式 POI 至少保存：

- 稳定 POI ID；
- 当前名称与类型；
- GCJ-02 坐标；
- 来源与原始响应路径；
- 查询或访问时间；
- 营业、开放或服务状态；
- 关联路线；
- 到轨迹的最近距离；
- `verified` 或 `needs_review` 状态。

名称、坐标或状态缺失时标记 `needs_review`，不进入已核实偏好筛选。严禁使用泛化名称、推测营业状态或伪造示例 POI。

## 7. 调用与缓存

1. 先查 `data/raw/amap`、现有 POI 目录和官方来源记录。
2. 按区域或路线走廊批量查询 POI，并跨路线复用。
3. 用唯一节点对缓存高德路径响应。
4. 本地结构检查通过后再运行 Overpass。
5. 只重试失败或过期项。
6. 收到 `429`、`504` 或连续异常时停止该批次，保留路线编号、查询参数、状态和异常位置。
