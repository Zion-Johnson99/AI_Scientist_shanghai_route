from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Sequence, cast

from pydantic import ValidationError

from .models import Coordinate, QuestionnaireConfig, RecommendationResult, UserProfile
from .qwen_client import QwenClient
from .service import evaluation_root, recommend, write_audit_result

SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="徐汇健康路线评价与千问审核")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api_parser = subparsers.add_parser("api-check", help="验证百炼结构化输出调用")
    api_parser.add_argument("--env-file", type=Path, default=evaluation_root() / ".env")
    api_parser.add_argument("--json", action="store_true", dest="as_json")

    recommend_parser = subparsers.add_parser("recommend", help="执行路线推荐")
    recommend_parser.add_argument("--profile", type=Path)
    recommend_parser.add_argument("--offline", action="store_true")
    recommend_parser.add_argument("--json", action="store_true", dest="as_json")
    recommend_parser.add_argument("--env-file", type=Path, default=evaluation_root() / ".env")
    recommend_parser.add_argument("--route-catalog", type=Path)
    recommend_parser.add_argument("--environment-dashboard", type=Path)
    recommend_parser.add_argument("--runtime-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_console_encoding()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "api-check":
            return _api_check(args)
        return _recommend(args)
    except (OSError, RuntimeError, TypeError, ValueError, ValidationError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _api_check(args: argparse.Namespace) -> int:
    audit = QwenClient.from_env(args.env_file).api_check()
    if args.as_json:
        print(audit.model_dump_json(indent=2))
    elif audit.status == "ok":
        print(f"千问 API 检查成功：model={audit.model}, latency_ms={audit.latency_ms}")
    else:
        print(
            f"千问 API 检查失败：{audit.error_type}: {audit.error_message}",
            file=sys.stderr,
        )
    return 0 if audit.status == "ok" else 1


def _recommend(args: argparse.Namespace) -> int:
    profile = _load_profile(args.profile) if args.profile else interactive_profile()
    result = recommend(
        profile,
        offline=args.offline,
        route_catalog_path=args.route_catalog,
        environment_path=args.environment_dashboard,
        env_file=args.env_file,
    )
    audit_path = write_audit_result(result, args.runtime_root)
    if args.as_json:
        document = result.model_dump(mode="json")
        if document["profile"].get("free_text"):
            document["profile"]["free_text"] = "[已省略]"
        print(json.dumps(document, ensure_ascii=False, indent=2))
    else:
        _print_result(result, audit_path)
    return 0


def _load_profile(path: Path) -> UserProfile:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"用户画像读取失败: path={path}, error={exc}") from exc
    if not isinstance(document, dict):
        raise TypeError(f"用户画像顶层需为对象: path={path}")
    document = cast(dict[str, Any], document)
    if document.get("target_time") == "now":
        document["target_time"] = datetime.now(SHANGHAI_TZ).isoformat()
    return UserProfile.model_validate(document)


def interactive_profile() -> UserProfile:
    questionnaire = _load_questionnaire()
    print("徐汇健康路线交互问卷（直接回车使用推荐值）")
    mode = _choose("运动方式", [(item.value, item.label) for item in questionnaire.route_modes], 1)
    distance_options = questionnaire.distance_ranges
    distance_labels = [
        (str(index), f"{low / 1000:g}-{high / 1000:g} km（目标 {target / 1000:g} km）")
        for index, (low, high, target) in enumerate(distance_options[mode], start=1)
    ]
    distance_index = int(_choose("目标距离", distance_labels, 1)) - 1
    low, high, target = distance_options[mode][distance_index]
    hours = int(
        _choose(
            "出发时间",
            [
                ("0", "现在"),
                ("3", "3小时后"),
                ("6", "6小时后"),
                ("12", "12小时后"),
                ("24", "24小时后"),
            ],
            1,
        )
    )
    target_time = datetime.now(SHANGHAI_TZ) + timedelta(hours=hours)
    origin = _prompt_origin()
    radius = (
        int(_choose("搜索范围", [("2000", "2 km"), ("5000", "5 km"), ("10000", "10 km")], 3))
        if origin
        else None
    )
    area_ids = (
        [] if origin else _multi("片区（逗号分隔）", [item.value for item in questionnaire.areas])
    )
    goal = _choose("运动目标", [(item.value, item.label) for item in questionnaire.goals], 1)
    experience = _choose(
        "运动经验", [(item.value, item.label) for item in questionnaire.experience_levels], 2
    )
    age_group = _choose(
        "年龄区间", [(item.value, item.label) for item in questionnaire.age_groups], 5
    )
    shape = _choose("路线形态", [("any", "均可"), ("strict_loop", "环线"), ("one_way", "单程")], 1)
    sensitivities = _multi("环境敏感（逗号分隔）", questionnaire.sensitivities)
    interests = _multi("兴趣服务（逗号分隔）", questionnaire.interests)
    free_text = input("补充需求（可留空）：").strip()
    return UserProfile.model_validate(
        {
            "route_mode": mode,
            "target_time": target_time,
            "distance_min_m": low,
            "target_distance_m": target,
            "distance_max_m": high,
            "origin": origin,
            "search_radius_m": radius,
            "area_ids": area_ids,
            "goal": goal,
            "experience": experience,
            "age_group": age_group,
            "route_shape": shape,
            "sensitivities": sensitivities,
            "interests": interests,
            "free_text": free_text,
        }
    )


def _load_questionnaire(path: Path | None = None) -> QuestionnaireConfig:
    resolved = path or evaluation_root() / "config" / "questionnaire.json"
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"问卷配置读取失败: path={resolved}, error={exc}") from exc
    return QuestionnaireConfig.model_validate(document)


def _choose(prompt: str, options: list[tuple[str, str]], default_index: int) -> str:
    print(prompt + "：")
    for index, (_, label) in enumerate(options, start=1):
        print(f"  {index}. {label}")
    raw = input(f"请选择 [{default_index}]：").strip()
    index = int(raw) if raw else default_index
    if index < 1 or index > len(options):
        raise ValueError(f"{prompt}选项超出范围")
    return options[index - 1][0]


def _multi(prompt: str, values: Sequence[str]) -> list[str]:
    print(f"{prompt}：{', '.join(values)}")
    raw = input("输入值或留空：").strip()
    if not raw:
        return []
    selected = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(values))
    if unknown:
        raise ValueError(f"未知选项: {', '.join(unknown)}")
    return selected


def _prompt_origin() -> Coordinate | None:
    raw = input("GCJ-02 出发坐标 lng,lat（留空表示全徐汇）：").strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise ValueError("出发坐标格式应为 lng,lat")
    return Coordinate(lng_gcj02=float(parts[0]), lat_gcj02=float(parts[1]))


def _print_result(result: RecommendationResult, audit_path: Path) -> None:
    print(f"状态：{result.status}｜决策来源：{result.decision_source}")
    print(f"目标时段风险：{result.risk.status}")
    for reason in result.risk.reasons:
        print(f"  - {reason}")
    if result.final_routes:
        print("推荐路线：")
    for item in result.final_routes[:4]:
        scored = item.route
        route = scored.route
        rank_change = scored.base_rank - item.final_rank
        change_text = f"，名次变化 {rank_change:+d}" if result.decision_source == "qwen" else ""
        print(
            f"  {item.final_rank}. {route.route_name} ({route.route_id}) "
            f"{route.distance_m / 1000:.2f} km，基础分 {scored.base_score:.1f}{change_text}"
        )
        print(f"     起点：{route.start_location.name}｜数据可信度：{scored.data_confidence:.3f}")
        environment_text = format_environment(scored.environment_summary)
        if environment_text:
            print(f"     环境：{environment_text}")
        print(f"     {item.personalized_fit}")
        for caution in item.cautions:
            print(f"     提醒：{caution}")
    print(f"说明：{result.decision_summary}")
    if result.api_audit.status == "degraded":
        print(f"千问降级：{result.api_audit.error_type}: {result.api_audit.error_message}")
    print(f"本地审计记录：{audit_path}")


def format_environment(summary: dict[str, Any]) -> str:
    values: list[str] = []
    for key, label in (("pm2_5", "PM2.5"), ("noise", "噪声"), ("pollen", "花粉")):
        raw_metric = summary.get(key)
        if not isinstance(raw_metric, dict):
            continue
        metric = cast(dict[str, Any], raw_metric)
        value = metric.get("value")
        unit = str(metric.get("unit") or "").replace("µg/m³", "ug/m3")
        time = metric.get("business_time") or metric.get("scenario") or "时间未知"
        scale = metric.get("spatial_scale") or "尺度未知"
        reliability = metric.get("reliability")
        reliability_text = (
            f"{float(reliability):.3f}" if isinstance(reliability, (int, float)) else "未知"
        )
        values.append(f"{label} {value} {unit} ({time}, {scale}, 可信度 {reliability_text})")
    return "；".join(values)


if __name__ == "__main__":
    raise SystemExit(main())
