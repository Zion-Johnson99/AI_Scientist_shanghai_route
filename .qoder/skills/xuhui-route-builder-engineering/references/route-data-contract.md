# Route Data Contract

## 稳定产物（`xuhui_route_builder/data/web/`）

| 文件 | 结构 | 用途 |
| --- | --- | --- |
| `route_catalog.json` | JSON 数组，90 个路线对象 | 路线库主目录（网页与实验共用） |
| `xuhui_routes.geojson` | FeatureCollection，90 个 feature | 路线几何（`properties.route_id` 与目录一致） |
| `xuhui_entries.geojson` | FeatureCollection | 运动入口（地铁站出口、公园入口、滨江步道入口等） |
| `poi_catalog.json` | POI 对象集合 | 已核验服务设施（咖啡、公园门、厕所、便利店等） |
| `access_cases.json` | 接驳样例集合 | 家/学校/公司/地铁站到运动入口的接驳导航样例 |
| `xuhui_boundary.geojson` | FeatureCollection | 徐汇区边界 |

以上文件是共享数据文件，只允许一个写入者。

## route_catalog.json 对象关键字段

```text
route_id                 # 如 XH_BIKE_0061，全局唯一
route_name
route_mode               # walk | run | bike（注意字段名是 route_mode，不是 mode）
route_shape              # one_way | strict_loop
distance_level           # short | medium | long
target_distance_m / distance_m / duration_min
start_entry_id / end_entry_id / start_location / end_location
region_zone / tags / feature_tags
validation_status        # accepted 等；90 条验收路线全部 accepted
geometry_status / geometry_source / display_status
confidence / source_name / source_url / source_accessed_at
waypoint_names / ordered_nodes / nearby_pois / preference_hits
```

## 数量与分布门禁

- 总数 90；`walk`、`run`、`bike` 各 30。
- 每模式三个距离带各 10 条：
  - walk：0.5–2 km / 2–3.5 km / 3.5–5 km
  - run：1–5 km / 5–10 km / 10–15 km
  - bike：5–10 km / 10–20 km / 20–30 km
- 目标 15 `strict_loop` + 15 `one_way`（每模式），允许 14–16 个自然严格环。

## ID 一致性

- `route_catalog.json` 的 `route_id` 集合必须等于 `xuhui_routes.geojson` 的 `properties.route_id` 集合。
- 无重复 `route_id`；目录与几何的模式、名称字段保持一致。
- 评价模块与网页选中的 `route_id` 必须存在于目录。

## 坐标系

- 所有几何、边界、途经点和 POI 产物必须声明坐标系。
- GCJ-02 与 WGS84 在边界、距离、最近路线计算前转换到同一比较坐标系。
