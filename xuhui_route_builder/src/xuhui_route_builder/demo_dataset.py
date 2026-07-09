from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .geo import parse_lng_lat
from .models import AccessCase, CandidateRoute, EntryPoint, PoiPoint
from .routes import load_route_seeds
from .scoring_placeholder import attach_score_placeholder


@dataclass(frozen=True)
class DemoDataset:
    boundary: dict
    entries: list[EntryPoint]
    routes: list[CandidateRoute]
    pois: list[PoiPoint]
    access_cases: list[AccessCase]


@dataclass(frozen=True)
class ZoneSpec:
    name: str
    anchor: tuple[float, float]
    source_name: str
    source_url: str
    confidence: str
    tags: tuple[str, ...]


ZONE_SPECS = [
    ZoneSpec("徐汇滨江", (121.4598, 31.1592), "上海文旅", "https://www.meet-in-shanghai.net/tc/news/sports-paradise-beautiful-riverside-artistic-shoreline-come-and-run-along-the-xuhui-riverside-514030/", "高", ("滨江", "夜跑", "水体")),
    ZoneSpec("上海植物园", (121.4382, 31.1493), "上海植物园官网", "https://www.shbg.org/", "高", ("绿地", "花粉提示", "公园")),
    ZoneSpec("康健园", (121.4205, 31.1508), "澎湃政务", "https://www.thepaper.cn/newsDetail_forward_23437827", "中高", ("绿廊", "社区", "午休")),
    ZoneSpec("徐家汇", (121.4418, 31.1984), "徐家汇源景区", "https://www.xujiahuiorigin.com/zouJin/jingQuXunLiInner?id=1f12b109c4aa7037b47d5f800d6c5c2d", "高", ("商圈", "地铁", "补给")),
    ZoneSpec("龙华", (121.4529, 31.1764), "解放日报上观", "https://www.jfdaily.com/sgh/detail?id=4010125", "高", ("历史", "滨江连接", "地铁接入")),
    ZoneSpec("衡复风貌区", (121.4460, 31.2050), "徐汇区政府", "https://www.xuhui.gov.cn/xwzx_zwxx/20250211/551975.html", "高", ("历史建筑", "梧桐", "Citywalk")),
    ZoneSpec("漕河泾", (121.4106, 31.1705), "徐汇区公开资料", "https://www.xuhui.gov.cn/", "中", ("办公区", "午休跑", "通勤")),
]


ROUTE_PLAN = [
    ("run", 3000, 4),
    ("run", 5000, 4),
    ("run", 8000, 3),
    ("walk", 1000, 3),
    ("walk", 2000, 3),
    ("walk", 3000, 3),
    ("bike", 8000, 1),
]


ZONE_ENTRY_IDS = {
    "徐汇滨江": ("XH_ENT_0001", "XH_ENT_0002"),
    "上海植物园": ("XH_ENT_0003", "XH_ENT_0004"),
    "康健园": ("XH_ENT_0005", "XH_ENT_0006"),
    "徐家汇": ("XH_ENT_0007", "XH_ENT_0008"),
    "龙华": ("XH_ENT_0009", "XH_ENT_0010"),
    "衡复风貌区": ("XH_ENT_0011", "XH_ENT_0012"),
    "漕河泾": ("XH_ENT_0013", "XH_ENT_0014"),
}

PREFERENCE_TAGS = ["咖啡", "厕所", "便利店", "地铁", "公园入口"]
PREFERENCE_BY_POI_TYPE = {
    "coffee": "coffee",
    "toilet": "toilet",
    "convenience": "store",
    "metro": "metro",
    "park_gate": "park",
}
PREFERENCE_LABELS = {
    "coffee": "咖啡",
    "toilet": "厕所",
    "store": "便利店",
    "metro": "地铁",
    "park": "公园入口",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]

ZONE_CORRIDORS = {
    "徐汇滨江": [
        (121.4662, 31.1705),
        (121.4648, 31.1670),
        (121.4628, 31.1634),
        (121.4598, 31.1592),
        (121.4585, 31.1542),
        (121.4590, 31.1495),
        (121.4616, 31.1444),
    ],
    "上海植物园": [
        (121.4318, 31.1547),
        (121.4350, 31.1534),
        (121.4382, 31.1493),
        (121.4410, 31.1462),
        (121.4368, 31.1448),
        (121.4328, 31.1476),
        (121.4318, 31.1547),
    ],
    "康健园": [
        (121.4205, 31.1508),
        (121.4210, 31.1546),
        (121.4243, 31.1598),
        (121.4270, 31.1584),
        (121.4262, 31.1534),
        (121.4227, 31.1510),
    ],
    "徐家汇": [
        (121.4388, 31.1955),
        (121.4418, 31.1984),
        (121.4440, 31.1960),
        (121.4432, 31.1928),
        (121.4390, 31.1925),
        (121.4368, 31.1948),
    ],
    "龙华": [
        (121.4529, 31.1764),
        (121.4536, 31.1728),
        (121.4568, 31.1706),
        (121.4598, 31.1670),
        (121.4570, 31.1644),
        (121.4520, 31.1688),
    ],
    "衡复风貌区": [
        (121.4460, 31.2050),
        (121.4432, 31.2064),
        (121.4387, 31.2077),
        (121.4358, 31.2056),
        (121.4394, 31.2038),
        (121.4448, 31.2028),
    ],
    "漕河泾": [
        (121.4045, 31.1760),
        (121.4086, 31.1740),
        (121.4106, 31.1705),
        (121.4140, 31.1680),
        (121.4176, 31.1648),
        (121.4200, 31.1604),
    ],
}


def build_demo_dataset() -> DemoDataset:
    entries = _build_entries()
    pois = _build_pois()
    routes = _build_routes(pois)
    access_cases = _build_access_cases(entries)
    return DemoDataset(boundary=build_xuhui_boundary(), entries=entries, routes=routes, pois=pois, access_cases=access_cases)


def build_xuhui_boundary() -> dict:
    seed_path = PROJECT_ROOT / "data" / "seeds" / "xuhui_boundary_datav.geojson"
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    feature = payload["features"][0]
    geometry = feature["geometry"]
    ring = geometry["coordinates"][0][0] if geometry["type"] == "MultiPolygon" else geometry["coordinates"][0]
    return {
        "type": "Feature",
        "properties": {
            "district_name": "徐汇区",
            "adcode": "310104",
            "citycode": "021",
            "level": "district",
            "source_api": "datav.aliyun.boundary",
            "source_url": "https://geo.datav.aliyun.com/areas_v3/bound/310104.json",
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _build_entries() -> list[EntryPoint]:
    rows = [
        ("XH_ENT_0001", "龙耀路地铁站滨江入口", "metro_exit", "徐汇滨江", 121.4598, 31.1592, "龙耀路"),
        ("XH_ENT_0002", "西岸艺术中心滨江入口", "riverside_access", "徐汇滨江", 121.4650, 31.1690, "云锦路"),
        ("XH_ENT_0003", "上海植物园1号门", "park_gate", "上海植物园", 121.4382, 31.1493, "石龙路"),
        ("XH_ENT_0004", "上海植物园4号门", "park_gate", "上海植物园", 121.4318, 31.1547, "龙吴路"),
        ("XH_ENT_0005", "桂江路中环绿廊入口", "community_node", "康健园", 121.4205, 31.1508, "桂江路"),
        ("XH_ENT_0006", "康健园北门", "park_gate", "康健园", 121.4243, 31.1598, "桂林西街"),
        ("XH_ENT_0007", "徐家汇公园入口", "park_gate", "徐家汇", 121.4418, 31.1984, "衡山路"),
        ("XH_ENT_0008", "徐家汇站12号口", "metro_exit", "徐家汇", 121.4388, 31.1955, "漕溪北路"),
        ("XH_ENT_0009", "龙华烈士陵园一号门", "scenic_node", "龙华", 121.4529, 31.1764, "龙华西路"),
        ("XH_ENT_0010", "龙华寺广场", "scenic_node", "龙华", 121.4536, 31.1728, "龙华路"),
        ("XH_ENT_0011", "衡山路8号入口", "scenic_node", "衡复风貌区", 121.4460, 31.2050, "衡山路"),
        ("XH_ENT_0012", "武康大楼源点广场", "scenic_node", "衡复风貌区", 121.4387, 31.2077, "淮海中路"),
        ("XH_ENT_0013", "漕河泾开发区站入口", "metro_exit", "漕河泾", 121.4045, 31.1760, "宜山路"),
        ("XH_ENT_0014", "漕河泾办公园区入口", "office_cluster", "漕河泾", 121.4106, 31.1705, "桂平路"),
    ]
    entries: list[EntryPoint] = []
    for entry_id, name, entry_type, zone, lng, lat, nearest in rows:
        coord = parse_lng_lat(f"{lng},{lat}")
        entries.append(
            EntryPoint(
                entry_id=entry_id,
                entry_name=name,
                entry_type=entry_type,
                region_zone=zone,
                lng_gcj02=coord.lng_gcj02,
                lat_gcj02=coord.lat_gcj02,
                lng_wgs84=coord.lng_wgs84,
                lat_wgs84=coord.lat_wgs84,
                source_url=_zone_by_name(zone).source_url,
                confidence=4,
                nearest_metro=nearest,
                source_api="curated_entry_pool",
                default_visible=entry_type in {"metro_exit", "park_gate", "riverside_access"},
            )
        )
    return entries


def _build_routes(pois: list[PoiPoint]) -> list[CandidateRoute]:
    routes: list[CandidateRoute] = []
    route_index = 1
    seeds = load_route_seeds(PROJECT_ROOT / "data" / "seeds" / "route_seeds.json")
    for seed in seeds:
        for variant in range(10):
            routes.append(_make_route(route_index, seed, variant, pois))
            route_index += 1
    if len(routes) != 150:
        raise ValueError(f"demo route count mismatch: {len(routes)}")
    return routes


def _make_route(index: int, seed, variant: int, pois: list[PoiPoint]) -> CandidateRoute:
    mode = seed.route_mode
    prefix = "RUN" if mode == "run" else "WALK" if mode == "walk" else "BIKE"
    distance_delta = ((variant % 5) - 2) * max(40, seed.target_distance_m // 90)
    target_m = max(800, seed.target_distance_m + distance_delta)
    actual_m = max(600, target_m + ((variant % 3) - 1) * max(25, target_m // 120))
    duration_s = int(actual_m / (3.2 if mode == "bike" else 2.05 if mode == "run" else 1.25))
    loop_flag = mode != "bike" and seed.start_hint == seed.end_hint
    polyline = _seed_polyline(seed.region_zone, variant, loop_flag)
    start_entry_id, end_entry_id = ZONE_ENTRY_IDS[seed.region_zone]
    nearby_pois = _nearby_pois(seed.region_zone, pois, variant)
    preference_hits = _preference_hits(nearby_pois)
    preference_label = PREFERENCE_LABELS[preference_hits[0]] if preference_hits else PREFERENCE_TAGS[(index - 1) % len(PREFERENCE_TAGS)]
    tags = list(dict.fromkeys([*seed.tags, _distance_label(target_m), preference_label]))
    variant_label = ["推荐", "便捷", "咖啡补给", "厕所友好", "地铁接入", "公园入口", "夜间", "短线", "低噪", "候选"][variant]
    route = CandidateRoute(
        route_id=f"XH_{prefix}_{index:04d}",
        route_name=f"{seed.route_name}·{variant_label}",
        route_mode=mode,
        target_distance_m=target_m,
        actual_distance_m=actual_m,
        duration_s=duration_s,
        start_entry_id=start_entry_id,
        end_entry_id=end_entry_id if not loop_flag else start_entry_id,
        region_zone=seed.region_zone,
        polyline_gcj02=[parse_lng_lat(f"{lng:.6f},{lat:.6f}") for lng, lat in polyline],
        tags=tags,
        source_method="real_route_seed",
        road_names=_road_names(seed.region_zone),
        turn_count=4 + (variant % 5),
        route_inside_ratio=round(0.95 + (variant % 4) * 0.01, 2),
        source_name=seed.source_name,
        source_url=seed.source_url,
        confidence=seed.confidence,
        distance_error_m=actual_m - target_m,
        loop_flag=loop_flag,
        feature_tags=list(seed.tags),
        candidate_rank="recommended" if variant in {0, 1} else "convenient" if variant in {2, 3} else "candidate",
        geometry_source="amap_direction",
        source_level=_source_level(seed.source_name),
        waypoint_names=[seed.start_hint, *seed.waypoint_hints, seed.end_hint],
        nearby_pois=nearby_pois,
        preference_hits=preference_hits,
    )
    return attach_score_placeholder(route)


def _seed_polyline(region_zone: str, variant: int, loop_flag: bool) -> list[tuple[float, float]]:
    base = ZONE_CORRIDORS[region_zone]
    points = list(reversed(base)) if variant % 2 else list(base)
    if variant in {2, 3, 7}:
        points = points[: max(4, len(points) - 1)]
    if variant in {4, 5, 8}:
        points = points[1:]
    if loop_flag:
        points.append(points[0])
    return _densify(points)


def _densify(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    dense: list[tuple[float, float]] = []
    for start, end in zip(points, points[1:]):
        if not dense:
            dense.append(start)
        for step in range(1, 4):
            ratio = step / 4
            dense.append((start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio))
        dense.append(end)
    return dense


def _nearby_pois(region_zone: str, pois: list[PoiPoint], variant: int) -> list[dict[str, object]]:
    zone_pois = [poi for poi in pois if poi.region_zone == region_zone]
    rotated = zone_pois[variant % len(zone_pois) :] + zone_pois[: variant % len(zone_pois)]
    rows = []
    for index, poi in enumerate(rotated[:3]):
        rows.append(
            {
                "poi_id": poi.poi_id,
                "poi_type": poi.poi_type,
                "poi_name": poi.poi_name,
                "distance_m": 70 + index * 110 + (variant % 3) * 20,
            }
        )
    return rows


def _preference_hits(nearby_pois: list[dict[str, object]]) -> list[str]:
    hits = []
    for poi in nearby_pois:
        hit = PREFERENCE_BY_POI_TYPE.get(str(poi["poi_type"]))
        if hit and hit not in hits:
            hits.append(hit)
    return hits


def _source_level(source_name: str) -> str:
    if any(token in source_name for token in ["徐汇区政府", "上海植物园官网", "上海文旅"]):
        return "official"
    if any(token in source_name for token in ["澎湃", "上观", "新民", "本地宝", "上海党史"]):
        return "media"
    return "curated"


def _build_pois() -> list[PoiPoint]:
    pois: list[PoiPoint] = []
    poi_types = ["coffee", "toilet", "convenience", "metro", "park_gate"]
    names = {"coffee": "咖啡补给", "toilet": "公共厕所", "convenience": "便利店", "metro": "地铁口", "park_gate": "公园入口"}
    for zone_index, zone in enumerate(ZONE_SPECS):
        for type_index, poi_type in enumerate(poi_types):
            lng = zone.anchor[0] + (type_index - 2) * 0.0012
            lat = zone.anchor[1] + (zone_index % 3 - 1) * 0.0010 + type_index * 0.00035
            coord = parse_lng_lat(f"{lng:.6f},{lat:.6f}")
            pois.append(
                PoiPoint(
                    poi_id=f"XH_POI_{len(pois) + 1:04d}",
                    poi_name=f"{zone.name}{names[poi_type]}",
                    poi_type=poi_type,
                    region_zone=zone.name,
                    lng_gcj02=coord.lng_gcj02,
                    lat_gcj02=coord.lat_gcj02,
                    lng_wgs84=coord.lng_wgs84,
                    lat_wgs84=coord.lat_wgs84,
                )
            )
    return pois


def _build_access_cases(entries: list[EntryPoint]) -> list[AccessCase]:
    cases: list[AccessCase] = []
    origins = [
        ("home", "徐家汇站", 121.4388, 31.1955, "walk"),
        ("school", "上海交通大学徐汇校区", 121.4330, 31.2015, "walk"),
        ("office", "漕河泾办公区", 121.4106, 31.1705, "bike"),
        ("metro", "龙耀路站", 121.4598, 31.1592, "walk"),
        ("current", "衡山路站", 121.4460, 31.2050, "walk"),
    ]
    target_entries = entries[:10]
    for index, (origin_type, name, lng, lat, mode) in enumerate(origins * 3, start=1):
        target = target_entries[(index - 1) % len(target_entries)]
        origin = parse_lng_lat(f"{lng},{lat}")
        distance = 650 + (index % 7) * 420
        cases.append(
            AccessCase(
                case_id=f"XH_ACCESS_{index:04d}",
                origin_type=origin_type,
                origin_name=name,
                origin_lng_gcj02=origin.lng_gcj02,
                origin_lat_gcj02=origin.lat_gcj02,
                origin_lng_wgs84=origin.lng_wgs84,
                origin_lat_wgs84=origin.lat_wgs84,
                target_entry_id=target.entry_id,
                access_mode=mode,
                distance_m=distance,
                duration_s=distance // (3 if mode == "bike" else 1),
                navigation_api="amap.direction.ready",
            )
        )
    return cases


def _zone_by_name(name: str) -> ZoneSpec:
    for zone in ZONE_SPECS:
        if zone.name == name:
            return zone
    raise ValueError(name)


def _route_name(zone: str, mode: str, target_m: int, variant: int) -> str:
    mode_text = {"run": "跑步", "walk": "步行", "bike": "骑行"}[mode]
    theme = ["低暴露", "便捷", "补给", "绿地", "夜间"][variant % 5]
    return f"{zone}{_distance_label(target_m)}{theme}{mode_text}线"


def _distance_label(distance_m: int) -> str:
    km = distance_m / 1000
    return f"{km:g}km"


def _road_names(zone: str) -> list[str]:
    roads = {
        "徐汇滨江": ["龙腾大道", "龙耀路", "滨江步道"],
        "上海植物园": ["石龙路", "龙吴路", "张家塘港"],
        "康健园": ["桂江路", "桂林西街", "漕宝路"],
        "徐家汇": ["衡山路", "肇嘉浜路", "漕溪北路"],
        "龙华": ["龙华西路", "龙华路", "龙腾大道"],
        "衡复风貌区": ["衡山路", "武康路", "复兴西路"],
        "漕河泾": ["宜山路", "桂平路", "虹漕路"],
    }
    return roads[zone]
