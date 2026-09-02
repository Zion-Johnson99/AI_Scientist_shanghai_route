"""预设实验画像矩阵（设计文档 01 §16.1）。

画像字段与 ``evaluation_model_qwen`` 的 ``UserProfile`` 兼容（参考
``evaluation_model_qwen/examples/profile_walk.json``），可直接作为
``score-candidates --profile`` 的输入。目标时段不使用“现在”：每个案例声明
固定的 ``target_time_offset_minutes``，由 :func:`resolve_target_time` 相对
环境快照时间确定性解析，保证同一快照永远得到同一目标时刻（评价模块要求
目标时刻位于数据生成时刻至未来 24 小时内）。

预设画像案例不解释为独立人群样本，不外推临床或人群结论。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

#: 预设案例矩阵；新增案例必须维持 case_id 唯一，并保持在
#: 路线目录现有距离带内（步行 0.76-4.92 km、跑步 1.14-13.38 km、
#: 骑行 5.81-28.58 km），否则该案例会如实计为无候选。
PRESET_CASES: tuple[dict, ...] = (
    {
        "case_id": "XH-WALK-HEALTH-AIR",
        "description": "步行 2.5 km，环境健康目标，空气敏感，公园与厕所偏好，无出发点全徐汇筛选",
        "target_time_offset_minutes": 60,
        "profile": {
            "route_mode": "walk",
            "distance_min_m": 1500,
            "target_distance_m": 2500,
            "distance_max_m": 3500,
            "area_ids": [],
            "goal": "health_environment",
            "experience": "regular",
            "age_group": "18_39",
            "sensitivities": ["air"],
            "route_shape": "any",
            "interests": ["park", "toilet"],
        },
    },
    {
        "case_id": "XH-WALK-SCENERY-WATERFRONT",
        "description": "步行 4.0 km，景观目标，滨水与安静偏好，无出发点全徐汇筛选",
        "target_time_offset_minutes": 90,
        "profile": {
            "route_mode": "walk",
            "distance_min_m": 3000,
            "target_distance_m": 4000,
            "distance_max_m": 4900,
            "area_ids": [],
            "goal": "scenery",
            "experience": "frequent",
            "age_group": "40_59",
            "sensitivities": [],
            "route_shape": "any",
            "interests": ["waterfront", "quiet"],
        },
    },
    {
        "case_id": "XH-WALK-NEARBY-NOISE",
        "description": "步行 1.2 km，就近目标，噪声敏感，便利设施偏好，徐家汇出发点接驳筛选",
        "target_time_offset_minutes": 30,
        "profile": {
            "route_mode": "walk",
            "distance_min_m": 800,
            "target_distance_m": 1200,
            "distance_max_m": 1600,
            "origin": {"lng_gcj02": 121.4377, "lat_gcj02": 31.1958},
            "search_radius_m": 3000,
            "area_ids": [],
            "goal": "nearby",
            "experience": "beginner",
            "age_group": "60_plus",
            "sensitivities": ["noise"],
            "route_shape": "any",
            "interests": ["convenience"],
        },
    },
    {
        "case_id": "XH-WALK-BALANCED-POLLEN",
        "description": "步行 3.0 km，平衡目标，花粉敏感，公园偏好，龙华出发点接驳筛选",
        "target_time_offset_minutes": 120,
        "profile": {
            "route_mode": "walk",
            "distance_min_m": 2000,
            "target_distance_m": 3000,
            "distance_max_m": 4000,
            "origin": {"lng_gcj02": 121.4526, "lat_gcj02": 31.1665},
            "search_radius_m": 5000,
            "area_ids": [],
            "goal": "balanced",
            "experience": "regular",
            "age_group": "18_39",
            "sensitivities": ["pollen"],
            "route_shape": "any",
            "interests": ["park"],
        },
    },
    {
        "case_id": "XH-RUN-HEALTH-AIR-NOISE",
        "description": "跑步 5.5 km，环境健康目标，空气与噪声敏感，滨水与厕所偏好，衡复出发点接驳筛选",
        "target_time_offset_minutes": 60,
        "profile": {
            "route_mode": "run",
            "distance_min_m": 4500,
            "target_distance_m": 5500,
            "distance_max_m": 6500,
            "origin": {"lng_gcj02": 121.4450, "lat_gcj02": 31.2050},
            "search_radius_m": 6000,
            "area_ids": [],
            "goal": "health_environment",
            "experience": "frequent",
            "age_group": "18_39",
            "sensitivities": ["air", "noise"],
            "route_shape": "any",
            "interests": ["waterfront", "toilet"],
        },
    },
    {
        "case_id": "XH-RUN-BALANCED-LOOP",
        "description": "跑步 5.0 km，平衡目标，严格环线形态，无出发点全徐汇筛选",
        "target_time_offset_minutes": 90,
        "profile": {
            "route_mode": "run",
            "distance_min_m": 4000,
            "target_distance_m": 5000,
            "distance_max_m": 6000,
            "area_ids": [],
            "goal": "balanced",
            "experience": "regular",
            "age_group": "18_39",
            "sensitivities": [],
            "route_shape": "strict_loop",
            "interests": [],
        },
    },
    {
        "case_id": "XH-RUN-SCENERY-WATERFRONT",
        "description": "跑步 7.0 km，景观目标，滨水与公园偏好，无出发点全徐汇筛选",
        "target_time_offset_minutes": 120,
        "profile": {
            "route_mode": "run",
            "distance_min_m": 6000,
            "target_distance_m": 7000,
            "distance_max_m": 8000,
            "area_ids": [],
            "goal": "scenery",
            "experience": "frequent",
            "age_group": "40_59",
            "sensitivities": [],
            "route_shape": "any",
            "interests": ["waterfront", "park"],
        },
    },
    {
        "case_id": "XH-BIKE-NEARBY-CONVENIENCE",
        "description": "骑行 6.5 km，就近目标，厕所与便利设施偏好，漕河泾出发点接驳筛选",
        "target_time_offset_minutes": 30,
        "profile": {
            "route_mode": "bike",
            "distance_min_m": 5800,
            "target_distance_m": 6500,
            "distance_max_m": 8000,
            "origin": {"lng_gcj02": 121.3955, "lat_gcj02": 31.1685},
            "search_radius_m": 8000,
            "area_ids": [],
            "goal": "nearby",
            "experience": "regular",
            "age_group": "18_39",
            "sensitivities": [],
            "route_shape": "any",
            "interests": ["toilet", "convenience"],
        },
    },
    {
        "case_id": "XH-BIKE-HEALTH-PARK",
        "description": "骑行 10.0 km，环境健康目标，空气敏感，公园与安静偏好，无出发点全徐汇筛选",
        "target_time_offset_minutes": 60,
        "profile": {
            "route_mode": "bike",
            "distance_min_m": 8000,
            "target_distance_m": 10000,
            "distance_max_m": 12000,
            "area_ids": [],
            "goal": "health_environment",
            "experience": "regular",
            "age_group": "40_59",
            "sensitivities": ["air"],
            "route_shape": "any",
            "interests": ["park", "quiet"],
        },
    },
    {
        "case_id": "XH-BIKE-SCENERY-LONG",
        "description": "骑行 13.0 km，景观目标，滨水偏好，无出发点全徐汇筛选",
        "target_time_offset_minutes": 120,
        "profile": {
            "route_mode": "bike",
            "distance_min_m": 12000,
            "target_distance_m": 13000,
            "distance_max_m": 15000,
            "area_ids": [],
            "goal": "scenery",
            "experience": "frequent",
            "age_group": "18_39",
            "sensitivities": [],
            "route_shape": "any",
            "interests": ["waterfront"],
        },
    },
)

_REQUIRED_MODES = frozenset({"walk", "run", "bike"})
_REQUIRED_GOALS = frozenset({"balanced", "health_environment", "nearby", "scenery"})
_REQUIRED_SENSITIVITIES = frozenset({"air", "pollen", "noise"})
_REQUIRED_INTERESTS = frozenset({"waterfront", "park", "quiet", "toilet", "convenience"})


def resolve_target_time(snapshot_time: str | datetime, offset_minutes: int) -> datetime:
    """把快照时间确定性平移为案例目标时刻（保留或补齐 +08:00 时区）。"""
    if isinstance(snapshot_time, str):
        try:
            parsed = datetime.fromisoformat(snapshot_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"快照时间不是合法 ISO-8601: {snapshot_time!r}") from exc
    elif isinstance(snapshot_time, datetime):
        parsed = snapshot_time
    else:
        raise TypeError("快照时间必须是 ISO-8601 字符串或 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timedelta(hours=8))
    if not isinstance(offset_minutes, int) or isinstance(offset_minutes, bool):
        raise TypeError("偏移量必须是整数分钟")
    if not 0 <= offset_minutes < 24 * 60:
        raise ValueError("偏移量必须位于 [0, 1440) 分钟，保证目标时刻落在数据生成后 24 小时窗口内")
    return parsed + timedelta(minutes=offset_minutes)


def render_case_profiles(snapshot_time: str | datetime) -> list[dict]:
    """生成全部预设案例画像（含确定性 ``target_time`` 与 ``case_id``）。"""
    rendered: list[dict] = []
    for case in PRESET_CASES:
        offset = int(case["target_time_offset_minutes"])
        profile = dict(case["profile"])
        profile["target_time"] = resolve_target_time(snapshot_time, offset).isoformat()
        rendered.append(
            {
                "case_id": case["case_id"],
                "description": case["description"],
                "target_time_offset_minutes": offset,
                "profile": profile,
            }
        )
    return rendered


def ensure_case_coverage(cases: tuple[dict, ...] | None = None) -> None:
    """校验案例矩阵覆盖方式、目标、敏感项与兴趣维度（违反即抛 ValueError）。"""
    items = PRESET_CASES if cases is None else tuple(cases)
    if not items:
        raise ValueError("案例矩阵为空")
    seen_ids: set[str] = set()
    for case in items:
        case_id = str(case.get("case_id", ""))
        if not case_id or case_id in seen_ids:
            raise ValueError(f"case_id 缺失或重复: {case_id!r}")
        seen_ids.add(case_id)
    profiles = [case["profile"] for case in items]
    modes = {profile["route_mode"] for profile in profiles}
    goals = {profile["goal"] for profile in profiles}
    sensitivities = {name for profile in profiles for name in profile.get("sensitivities", [])}
    interests = {name for profile in profiles for name in profile.get("interests", [])}
    origins = {profile.get("origin") is not None for profile in profiles}
    problems: list[str] = []
    for label, required, actual in (
        ("route_mode", _REQUIRED_MODES, modes),
        ("goal", _REQUIRED_GOALS, goals),
        ("sensitivity", _REQUIRED_SENSITIVITIES, sensitivities),
        ("interest", _REQUIRED_INTERESTS, interests),
    ):
        missing = sorted(required - actual)
        if missing:
            problems.append(f"{label} 缺少覆盖: {', '.join(missing)}")
    if origins != {True, False}:
        problems.append("案例必须同时包含有出发点（接驳）与无出发点（全徐汇筛选）两类")
    if problems:
        raise ValueError("；".join(problems))


def dump_profiles_json(snapshot_time: str | datetime) -> str:
    """序列化画像矩阵为 JSON 文本（先做覆盖校验，字段与 UserProfile 兼容）。"""
    ensure_case_coverage()
    return json.dumps(render_case_profiles(snapshot_time), ensure_ascii=False, indent=2)
