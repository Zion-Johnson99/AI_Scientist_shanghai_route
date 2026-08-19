from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .geo import parse_lng_lat
from .models import AccessCase, AccessMode, CandidateRoute, EntryPoint, PoiPoint


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
    ZoneSpec(
        "徐汇滨江",
        (121.4598, 31.1592),
        "上海文旅",
        "https://www.meet-in-shanghai.net/tc/news/sports-paradise-beautiful-riverside-artistic-shoreline-come-and-run-along-the-xuhui-riverside-514030/",
        "高",
        ("滨江", "夜跑", "水体"),
    ),
    ZoneSpec(
        "上海植物园",
        (121.4382, 31.1493),
        "上海植物园官网",
        "https://www.shbg.org/",
        "高",
        ("绿地", "花粉提示", "公园"),
    ),
    ZoneSpec(
        "康健园",
        (121.4205, 31.1508),
        "澎湃政务",
        "https://www.thepaper.cn/newsDetail_forward_23437827",
        "中高",
        ("绿廊", "社区", "午休"),
    ),
    ZoneSpec(
        "徐家汇",
        (121.4418, 31.1984),
        "徐家汇源景区",
        "https://www.xujiahuiorigin.com/zouJin/jingQuXunLiInner?id=1f12b109c4aa7037b47d5f800d6c5c2d",
        "高",
        ("商圈", "地铁", "补给"),
    ),
    ZoneSpec(
        "龙华",
        (121.4529, 31.1764),
        "解放日报上观",
        "https://www.jfdaily.com/sgh/detail?id=4010125",
        "高",
        ("历史", "滨江连接", "地铁接入"),
    ),
    ZoneSpec(
        "衡复风貌区",
        (121.4460, 31.2050),
        "徐汇区政府",
        "https://www.xuhui.gov.cn/xwzx_zwxx/20250211/551975.html",
        "高",
        ("历史建筑", "梧桐", "Citywalk"),
    ),
    ZoneSpec(
        "漕河泾",
        (121.4106, 31.1705),
        "徐汇区公开资料",
        "https://www.xuhui.gov.cn/",
        "中",
        ("办公区", "午休跑", "通勤"),
    ),
]


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_demo_dataset() -> DemoDataset:
    entries = _build_entries()
    pois = _build_pois()
    access_cases = _build_access_cases(entries)
    return DemoDataset(
        boundary=build_xuhui_boundary(),
        entries=entries,
        routes=[],
        pois=pois,
        access_cases=access_cases,
    )


def build_xuhui_boundary() -> dict:
    seed_path = PROJECT_ROOT / "data" / "seeds" / "xuhui_boundary_datav.geojson"
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    feature = payload["features"][0]
    geometry = feature["geometry"]
    ring = (
        geometry["coordinates"][0][0]
        if geometry["type"] == "MultiPolygon"
        else geometry["coordinates"][0]
    )
    return {
        "type": "Feature",
        "properties": {
            "district_name": "徐汇区",
            "adcode": "310104",
            "citycode": "021",
            "level": "district",
            "coordinate_system": "gcj02",
            "source_api": "datav.aliyun.boundary",
            "source_url": "https://geo.datav.aliyun.com/areas_v3/bound/310104.json",
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _build_entries() -> list[EntryPoint]:
    rows = [
        (
            "XH_ENT_0001",
            "龙耀路地铁站滨江入口",
            "metro_exit",
            "徐汇滨江",
            121.4598,
            31.1592,
            "龙耀路",
        ),
        (
            "XH_ENT_0002",
            "西岸艺术中心滨江入口",
            "riverside_access",
            "徐汇滨江",
            121.4650,
            31.1690,
            "云锦路",
        ),
        (
            "XH_ENT_0003",
            "上海植物园1号门",
            "park_gate",
            "上海植物园",
            121.4382,
            31.1493,
            "石龙路",
        ),
        (
            "XH_ENT_0004",
            "上海植物园4号门",
            "park_gate",
            "上海植物园",
            121.4318,
            31.1547,
            "龙吴路",
        ),
        (
            "XH_ENT_0005",
            "桂江路中环绿廊入口",
            "community_node",
            "康健园",
            121.4205,
            31.1508,
            "桂江路",
        ),
        (
            "XH_ENT_0006",
            "康健园北门",
            "park_gate",
            "康健园",
            121.4243,
            31.1598,
            "桂林西街",
        ),
        (
            "XH_ENT_0007",
            "徐家汇公园入口",
            "park_gate",
            "徐家汇",
            121.4418,
            31.1984,
            "衡山路",
        ),
        (
            "XH_ENT_0008",
            "徐家汇站12号口",
            "metro_exit",
            "徐家汇",
            121.4388,
            31.1955,
            "漕溪北路",
        ),
        (
            "XH_ENT_0009",
            "龙华烈士陵园一号门",
            "scenic_node",
            "龙华",
            121.4529,
            31.1764,
            "龙华西路",
        ),
        (
            "XH_ENT_0010",
            "龙华寺广场",
            "scenic_node",
            "龙华",
            121.4536,
            31.1728,
            "龙华路",
        ),
        (
            "XH_ENT_0011",
            "衡山路8号入口",
            "scenic_node",
            "衡复风貌区",
            121.4460,
            31.2050,
            "衡山路",
        ),
        (
            "XH_ENT_0012",
            "武康大楼源点广场",
            "scenic_node",
            "衡复风貌区",
            121.4387,
            31.2077,
            "淮海中路",
        ),
        (
            "XH_ENT_0013",
            "漕河泾开发区站入口",
            "metro_exit",
            "漕河泾",
            121.4045,
            31.1760,
            "宜山路",
        ),
        (
            "XH_ENT_0014",
            "漕河泾办公园区入口",
            "office_cluster",
            "漕河泾",
            121.4106,
            31.1705,
            "桂平路",
        ),
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
                default_visible=entry_type
                in {"metro_exit", "park_gate", "riverside_access"},
            )
        )
    return entries


def _build_pois() -> list[PoiPoint]:
    pois: list[PoiPoint] = []
    poi_types: tuple[
        Literal["coffee", "toilet", "convenience", "metro", "park_gate"], ...
    ] = ("coffee", "toilet", "convenience", "metro", "park_gate")
    names = {
        "coffee": "咖啡补给",
        "toilet": "公共厕所",
        "convenience": "便利店",
        "metro": "地铁口",
        "park_gate": "公园入口",
    }
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
    origins: list[tuple[str, str, float, float, AccessMode]] = [
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
