from __future__ import annotations

from typing import Any

from .geo import parse_lng_lat
from .models import EntryPoint


def entry_from_poi(poi: dict[str, Any], entry_id: str, entry_type: str, region_zone: str, source_url: str) -> EntryPoint:
    location = poi.get("entr_location") or poi.get("location")
    if not location:
        raise ValueError(f"POI has no usable location: {poi.get('name')}")
    coord = parse_lng_lat(str(location))
    return EntryPoint(
        entry_id=entry_id,
        entry_name=str(poi.get("name", entry_id)),
        entry_type=entry_type,
        region_zone=region_zone,
        lng_gcj02=coord.lng_gcj02,
        lat_gcj02=coord.lat_gcj02,
        lng_wgs84=coord.lng_wgs84,
        lat_wgs84=coord.lat_wgs84,
        source_url=source_url,
        confidence=4 if poi.get("entr_location") else 3,
        poi_id=poi.get("id"),
        address=poi.get("address") if isinstance(poi.get("address"), str) else None,
        parent_poi=poi.get("parent"),
        navi_poiid=poi.get("navi_poiid"),
        entr_location=poi.get("entr_location"),
        source_api="amap.poi",
    )


def sample_entries() -> list[EntryPoint]:
    rows = [
        ("XH_ENT_0001", "龙耀路地铁站滨江入口", "metro_exit", "徐汇滨江", 121.4598, 31.1592, "https://www.meet-in-shanghai.net/tc/news/sports-paradise-beautiful-riverside-artistic-shoreline-come-and-run-along-the-xuhui-riverside-514030/"),
        ("XH_ENT_0002", "上海植物园1号门", "park_gate", "上海植物园", 121.4382, 31.1493, "https://www.shbg.org/"),
        ("XH_ENT_0003", "衡山路8号入口", "scenic_node", "衡复风貌区", 121.4460, 31.2050, "https://www.xuhui.gov.cn/xwzx_zwxx/20250211/551975.html"),
        ("XH_ENT_0004", "龙华烈士陵园一号门", "scenic_node", "龙华", 121.4529, 31.1764, "https://www.jfdaily.com/sgh/detail?id=4010125"),
        ("XH_ENT_0005", "徐家汇公园入口", "park_gate", "徐家汇", 121.4418, 31.1984, "https://www.xujiahuiorigin.com/zouJin/jingQuXunLiInner?id=1f12b109c4aa7037b47d5f800d6c5c2d"),
        ("XH_ENT_0006", "桂江路中环绿廊入口", "community_node", "康健园", 121.4205, 31.1508, "https://www.thepaper.cn/newsDetail_forward_23437827"),
    ]
    entries: list[EntryPoint] = []
    for entry_id, name, entry_type, zone, lng, lat, source in rows:
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
                source_url=source,
                confidence=4,
                source_api="manual_seed",
            )
        )
    return entries
