#!/usr/bin/env python3
"""Rebuild selected cycling routes through the loaded AMap JS API."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _spec(
    shape: str,
    name: str,
    region: str,
    areas: list[str],
    target_range_m: tuple[int, int],
    nodes: list[str],
) -> dict[str, Any]:
    return {
        "shape": shape,
        "name": name,
        "region": region,
        "popular_area_ids": areas,
        "target_range_m": list(target_range_m),
        "simplify_m": 20,
        "endpoint_trim_m": 50,
        "nodes": nodes,
    }


ROUTE_SPECS: dict[str, dict[str, Any]] = {
    "XH_BIKE_0061": _spec(
        "strict_loop",
        "西岸—龙华公共道路短环",
        "徐汇滨江及龙华",
        ["west_bund", "longhua"],
        (5_500, 9_500),
        [
            "瑞宁路与云锦路交叉口",
            "瑞宁路与龙腾大道交叉口",
            "龙耀路与龙腾大道交叉口",
            "龙耀路与云锦路交叉口",
        ],
    ),
    "XH_BIKE_0062": _spec(
        "strict_loop",
        "上海植物园外围公共道路短环",
        "上海植物园及周边",
        ["shanghai_botanical_garden"],
        (6_500, 10_000),
        [
            "石龙路与老沪闵路交叉口",
            "石龙路与龙吴路交叉口",
            "百色路与龙吴路交叉口",
            "百色路与老沪闵路交叉口",
        ],
    ),
    "XH_BIKE_0063": _spec(
        "strict_loop",
        "漕河泾—桂江外围骑行短环",
        "漕河泾—桂江绿廊",
        ["caohejing", "kangjian"],
        (7_000, 9_800),
        [
            "宜山路与虹梅路交叉口",
            "桂江路与钦州南路交叉口",
            "江安路与桂江路交叉口",
            "江安路与虹漕南路交叉口",
            "蒲汇塘路与桂林路交叉口",
        ],
    ),
    "XH_BIKE_0064": _spec(
        "strict_loop",
        "徐家汇—衡复街区骑行短环",
        "徐家汇及衡复风貌区",
        ["xujiahui", "hengfu"],
        (5_000, 9_500),
        [
            "乌鲁木齐中路与复兴西路交叉口",
            "复兴中路与汾阳路交叉口",
            "龙华中路与瑞金南路交叉口",
            "肇嘉浜路与乌鲁木齐南路交叉口",
        ],
    ),
    "XH_BIKE_0065": _spec(
        "strict_loop",
        "康健—漕河泾公共道路短环",
        "康健—漕河泾",
        ["kangjian", "caohejing"],
        (6_000, 9_500),
        [
            "蒲汇塘路与桂林路交叉口",
            "宜山路与虹梅路交叉口",
            "桂江路与钦州南路交叉口",
            "江安路与桂江路交叉口",
        ],
    ),
    "XH_BIKE_0066": _spec(
        "one_way",
        "植物园—西岸龙腾大道骑行线",
        "上海植物园—徐汇滨江",
        ["shanghai_botanical_garden", "longhua", "west_bund"],
        (5_500, 9_500),
        [
            "上海植物园3号门外百色路",
            "百色路与龙吴路交叉口",
            "龙腾大道与瑞宁路交叉口",
        ],
    ),
    "XH_BIKE_0067": _spec(
        "one_way",
        "漕河泾—植物园—龙华骑行线",
        "漕河泾—上海植物园—龙华",
        ["caohejing", "shanghai_botanical_garden", "longhua"],
        (5_500, 9_500),
        [
            "蒲汇塘路与桂林路交叉口",
            "龙川北路与罗城路交叉口",
            "上海植物园4号门外罗城路",
            "龙华滨江休闲广场外侧道路",
        ],
    ),
    "XH_BIKE_0068": _spec(
        "one_way",
        "漕河泾—徐家汇地面骑行线",
        "漕河泾—徐家汇",
        ["caohejing", "xujiahui"],
        (5_000, 8_000),
        [
            "宜山路与虹梅路交叉口",
            "宜山路与虹漕路交叉口",
            "蒲汇塘路与桂林路交叉口",
            "中山南二路与天钥桥路交叉口",
        ],
    ),
    "XH_BIKE_0069": _spec(
        "one_way",
        "衡复—龙华—西岸骑行线",
        "衡复风貌区—龙华—徐汇滨江",
        ["hengfu", "xujiahui", "longhua", "west_bund"],
        (6_500, 9_800),
        [
            "乌鲁木齐中路与复兴西路交叉口",
            "肇嘉浜路与宛平南路交叉口",
            "龙华路与宛平南路交叉口",
            "龙水南路与龙腾大道交叉口",
        ],
    ),
    "XH_BIKE_0070": _spec(
        "one_way",
        "华泾—上海植物园骑行线",
        "华泾—上海植物园",
        ["huajing", "shanghai_botanical_garden"],
        (5_000, 8_500),
        [
            "华展路与龙吴路交叉口",
            "华发路与龙吴路交叉口",
            "百色路与龙吴路交叉口",
            "石龙路与龙吴路交叉口",
            "石龙路与老沪闵路交叉口",
        ],
    ),
    "XH_BIKE_0071": _spec(
        "strict_loop",
        "西岸—徐家汇—龙华骑行中环",
        "徐汇滨江—徐家汇—龙华",
        ["west_bund", "xujiahui", "longhua"],
        (10_000, 15_000),
        [
            "龙耀路与云锦路交叉口",
            "龙腾大道与瑞宁路交叉口",
            "虹桥路与华山路交叉口",
            "龙华西路与天钥桥路交叉口",
        ],
    ),
    "XH_BIKE_0072": _spec(
        "strict_loop",
        "植物园—康健—漕河泾骑行中环",
        "上海植物园—康健—漕河泾",
        ["shanghai_botanical_garden", "kangjian", "caohejing"],
        (10_000, 19_500),
        [
            "石龙路与老沪闵路交叉口",
            "石龙路与龙吴路交叉口",
            "华发路与龙吴路交叉口",
            "华发路与老沪闵路交叉口",
        ],
    ),
    "XH_BIKE_0073": _spec(
        "strict_loop",
        "衡复—西岸—龙华骑行中环",
        "衡复风貌区—徐汇滨江—龙华",
        ["hengfu", "xujiahui", "west_bund", "longhua"],
        (10_000, 18_000),
        [
            "龙耀路与龙腾大道交叉口",
            "龙腾大道与瑞宁路交叉口",
            "肇嘉浜路与天平路交叉口",
            "龙华西路与天钥桥路交叉口",
        ],
    ),
    "XH_BIKE_0074": _spec(
        "strict_loop",
        "华泾—植物园—龙华骑行中环",
        "华泾—上海植物园—龙华",
        ["huajing", "shanghai_botanical_garden", "longhua"],
        (10_000, 18_500),
        [
            "华泾路与龙吴路交叉口",
            "华泾路与老沪闵路交叉口",
            "石龙路与老沪闵路交叉口",
            "石龙路与龙吴路交叉口",
        ],
    ),
    "XH_BIKE_0075": _spec(
        "strict_loop",
        "漕河泾—衡复—徐家汇骑行中环",
        "漕河泾—衡复风貌区—徐家汇",
        ["caohejing", "hengfu", "xujiahui"],
        (13_000, 19_000),
        [
            "宜山路与桂平路交叉口",
            "乌鲁木齐中路与复兴西路交叉口",
            "肇嘉浜路与天平路交叉口",
            "中山南二路与天钥桥路交叉口",
            "桂林路与钦州南路交叉口",
        ],
    ),
    "XH_BIKE_0076": _spec(
        "one_way",
        "衡复—植物园—华泾骑行线",
        "衡复风貌区—上海植物园—华泾",
        ["hengfu", "xujiahui", "shanghai_botanical_garden", "huajing"],
        (12_000, 19_500),
        [
            "复兴中路与汾阳路交叉口",
            "肇嘉浜路与天平路交叉口",
            "蒲汇塘路与桂林路交叉口",
            "百色路与龙川北路交叉口",
            "华发路与龙吴路交叉口",
            "华展路与龙吴路交叉口",
        ],
    ),
    "XH_BIKE_0077": _spec(
        "one_way",
        "漕河泾—龙华—西岸骑行线",
        "漕河泾—徐家汇—龙华—徐汇滨江",
        ["caohejing", "xujiahui", "longhua", "west_bund"],
        (10_000, 15_000),
        [
            "宜山路与虹梅路交叉口",
            "蒲汇塘路与桂林路交叉口",
            "中山南二路与天钥桥路交叉口",
            "龙华路与宛平南路交叉口",
            "丰谷路与龙腾大道交叉口",
            "龙腾大道与瑞宁路交叉口",
        ],
    ),
    "XH_BIKE_0078": _spec(
        "one_way",
        "华泾—西岸龙腾大道骑行线",
        "华泾—龙华—徐汇滨江",
        ["huajing", "shanghai_botanical_garden", "longhua", "west_bund"],
        (10_000, 16_000),
        [
            "华展路与龙吴路交叉口",
            "华发路与龙吴路交叉口",
            "百色路与龙川北路交叉口",
            "龙耀路与龙腾大道交叉口",
            "龙腾大道与瑞宁路交叉口",
        ],
    ),
    "XH_BIKE_0079": _spec(
        "one_way",
        "衡复—漕河泾—桂江骑行线",
        "衡复风貌区—漕河泾—桂江绿廊",
        ["hengfu", "xujiahui", "caohejing", "kangjian"],
        (10_000, 16_000),
        [
            "乌鲁木齐中路与复兴西路交叉口",
            "肇嘉浜路与天平路交叉口",
            "中山南二路与天钥桥路交叉口",
            "漕宝路与桂平路交叉口",
            "桂江路与钦州南路交叉口",
            "罗秀路与虹梅南路交叉口",
        ],
    ),
    "XH_BIKE_0080": _spec(
        "one_way",
        "植物园—西岸—衡复骑行线",
        "上海植物园—徐汇滨江—衡复风貌区",
        ["shanghai_botanical_garden", "longhua", "west_bund", "hengfu"],
        (12_000, 19_000),
        [
            "上海植物园3号门外百色路",
            "石龙路与老沪闵路交叉口",
            "龙华西路与天钥桥路交叉口",
            "龙耀路与龙腾大道交叉口",
            "龙腾大道与瑞宁路交叉口",
            "复兴中路与嘉善路交叉口",
        ],
    ),
    "XH_BIKE_0081": _spec(
        "strict_loop",
        "徐汇全域公共道路外围长环",
        "徐汇全域",
        ["west_bund", "xujiahui", "caohejing", "kangjian", "huajing", "longhua"],
        (22_000, 29_500),
        [
            "龙腾大道与瑞宁路交叉口",
            "中山南二路与天钥桥路交叉口",
            "宜山路与虹梅路交叉口",
            "江安路与桂江路交叉口",
            "华展路与龙吴路交叉口",
            "龙耀路与龙腾大道交叉口",
        ],
    ),
    "XH_BIKE_0082": _spec(
        "strict_loop",
        "西岸—植物园—漕河泾—徐家汇长环",
        "徐汇滨江—上海植物园—漕河泾—徐家汇",
        ["west_bund", "longhua", "shanghai_botanical_garden", "caohejing", "xujiahui"],
        (20_000, 28_000),
        [
            "龙耀路与云锦路交叉口",
            "上海植物园3号门外百色路",
            "江安路与桂江路交叉口",
            "安顺路与淮海西路交叉口",
            "肇嘉浜路与宛平南路交叉口",
        ],
    ),
    "XH_BIKE_0083": _spec(
        "strict_loop",
        "华泾—漕河泾—徐家汇—西岸长环",
        "华泾—漕河泾—徐家汇—徐汇滨江",
        ["huajing", "caohejing", "xujiahui", "west_bund", "longhua"],
        (22_000, 30_000),
        [
            "华展路与龙吴路交叉口",
            "罗秀路与虹梅南路交叉口",
            "复兴中路与瑞金二路交叉口",
            "龙腾大道与瑞宁路交叉口",
            "龙耀路与龙腾大道交叉口",
        ],
    ),
    "XH_BIKE_0084": _spec(
        "strict_loop",
        "衡复—漕河泾—植物园—龙华长环",
        "衡复风貌区—漕河泾—上海植物园—龙华",
        ["hengfu", "caohejing", "shanghai_botanical_garden", "longhua", "west_bund"],
        (22_000, 30_000),
        [
            "复兴中路与汾阳路交叉口",
            "宜山路与桂平路交叉口",
            "罗秀路与虹梅南路交叉口",
            "百色路与龙川北路交叉口",
            "龙耀路与龙腾大道交叉口",
            "龙腾大道与瑞宁路交叉口",
        ],
    ),
    "XH_BIKE_0085": _spec(
        "strict_loop",
        "西岸—漕河泾—植物园—华泾长环",
        "徐汇滨江—漕河泾—上海植物园—华泾",
        ["west_bund", "xujiahui", "caohejing", "shanghai_botanical_garden", "huajing", "longhua"],
        (21_000, 29_000),
        [
            "龙耀路与云锦路交叉口",
            "龙腾大道与瑞宁路交叉口",
            "肇嘉浜路与宛平南路交叉口",
            "蒲汇塘路与桂林路交叉口",
            "百色路与龙川北路交叉口",
            "华展路与龙吴路交叉口",
            "龙耀路与龙腾大道交叉口",
        ],
    ),
    "XH_BIKE_0086": _spec(
        "one_way",
        "漕河泾—衡复—西岸—华泾骑行线",
        "漕河泾—衡复风貌区—徐汇滨江—华泾",
        ["caohejing", "hengfu", "xujiahui", "west_bund", "longhua", "huajing"],
        (20_000, 26_000),
        [
            "宜山路与虹梅路交叉口",
            "复兴中路与嘉善路交叉口",
            "龙腾大道与瑞宁路交叉口",
            "华展路与龙吴路交叉口",
        ],
    ),
    "XH_BIKE_0087": _spec(
        "one_way",
        "漕河泾—衡复—西岸—华泾南向线",
        "漕河泾—衡复风貌区—徐汇滨江—华泾",
        ["caohejing", "hengfu", "west_bund", "longhua", "shanghai_botanical_garden", "huajing"],
        (20_000, 27_000),
        [
            "复兴中路与嘉善路交叉口",
            "宜山路与虹梅路交叉口",
            "江安路与桂江路交叉口",
            "华展路与龙吴路交叉口",
            "华济路与龙吴路交叉口",
        ],
    ),
    "XH_BIKE_0088": _spec(
        "one_way",
        "衡复—徐家汇—西岸—植物园—华泾骑行线",
        "衡复风貌区—徐家汇—徐汇滨江—上海植物园—华泾",
        ["hengfu", "xujiahui", "west_bund", "longhua", "shanghai_botanical_garden", "huajing"],
        (20_000, 25_000),
        [
            "复兴中路与嘉善路交叉口",
            "中山南二路与天钥桥路交叉口",
            "宜山路与虹梅路交叉口",
            "江安路与桂江路交叉口",
            "百色路与龙川北路交叉口",
            "华泾路与老沪闵路交叉口",
            "华济路与龙吴路交叉口",
        ],
    ),
    "XH_BIKE_0089": _spec(
        "one_way",
        "华泾—漕河泾—衡复北向骑行线",
        "华泾—漕河泾—衡复风貌区",
        ["huajing", "shanghai_botanical_garden", "kangjian", "caohejing", "hengfu"],
        (20_000, 25_000),
        [
            "华展路与龙吴路交叉口",
            "华展路与虹梅南路交叉口",
            "罗秀路与虹梅南路交叉口",
            "漕宝路与桂平路交叉口",
            "宜山路与桂平路交叉口",
            "中山西路与宜山路交叉口",
            "龙腾大道与瑞宁路交叉口",
            "复兴中路与汾阳路交叉口",
        ],
    ),
    "XH_BIKE_0090": _spec(
        "one_way",
        "衡复—漕河泾—植物园—华泾骑行线",
        "衡复风貌区—漕河泾—上海植物园—华泾",
        ["hengfu", "xujiahui", "caohejing", "shanghai_botanical_garden", "huajing"],
        (20_000, 26_000),
        [
            "复兴中路与嘉善路交叉口",
            "肇嘉浜路与天平路交叉口",
            "中山南二路与天钥桥路交叉口",
            "宜山路与虹梅路交叉口",
            "江安路与桂江路交叉口",
            "百色路与龙川北路交叉口",
            "华发路与龙吴路交叉口",
            "华泾路与老沪闵路交叉口",
            "华济路与龙吴路交叉口",
        ],
    ),
}

ROUTE_SPECS["XH_BIKE_0086"]["simplify_m"] = 30
ROUTE_SPECS["XH_BIKE_0084"]["endpoint_trim_m"] = 300


def _load_engine():
    path = Path(__file__).with_name("rebuild_run_routes.py")
    spec = importlib.util.spec_from_file_location("bike_route_rebuild_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"route rebuild engine unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROUTE_MODE = "bike"
    module.AMAP_SERVICE = "Riding"
    module.CACHE_NAMESPACE = "Bike"
    module.SERVICE_LABEL = "riding"
    module.NETWORK_SOURCE = "amap_js_riding_20260820+local_topology"
    module.REVIEW_NOTE = "高德 JS 骑行路径经真实公共道路节点生成，本地几何门禁通过，等待全景目视复核"
    module.ROUTE_SPECS = ROUTE_SPECS
    return module


_ENGINE = _load_engine()

select_specs = _ENGINE.select_specs
browser_batch_expression = _ENGINE.browser_batch_expression
start_batch = _ENGINE.start_batch
wait_for_batch = _ENGINE.wait_for_batch
audit_routes = _ENGINE.audit_routes
apply_routes = _ENGINE.apply_routes


def main() -> int:
    return _ENGINE.main()


if __name__ == "__main__":
    raise SystemExit(main())
